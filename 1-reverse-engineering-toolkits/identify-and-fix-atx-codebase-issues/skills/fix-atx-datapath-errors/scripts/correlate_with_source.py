#!/usr/bin/env python3
"""
correlate_with_source.py

Cross-references normalized findings (produced by parse_debug_bundle.py)
against the ORIGINAL source zip that was submitted to AWS Transform, to:

  1. Resolve the REAL physical file and line each finding refers to (AWS
     Transform reports line numbers against the COPY-expanded/preprocessed
     source, which is very often a different file than the one named in
     `relPath` — see the module-level note below).
  2. Pull real surrounding source lines at that resolved location (the
     debug bundle only ships a few "badLines"; this gets full context).
  3. Run a small, EXPLICITLY EXTENSIBLE library of pattern matchers
     (`PATTERN_LIBRARY`) against each finding to propose a root-cause
     category, confidence, and rationale, when a known pattern matches.
  4. Anything that does not match a known pattern is left as
     "needs-manual-classification" — this is the expected, common case for
     a real codebase, NOT an error in this script. AWS Transform can
     surface an open-ended variety of parser/DSL/CFG errors depending on
     the source dialect, vendor extensions, and prior transcription
     history; no fixed taxonomy can enumerate all of them up front.

IMPORTANT — root causes are effectively open-ended.
The pattern matchers below (see PATTERN_LIBRARY) encode a handful of
concrete, evidence-based examples encountered on one sample codebase
(documented in references/error_taxonomy.md as worked examples). They are
a STARTING POINT, not a closed list. When you encounter a new recurring
`summary`/`errorCause` shape that isn't recognized:
  - Add a new function to PATTERN_LIBRARY following the same signature
    (see `PatternMatcher` below), or
  - Leave it for manual/LLM-assisted triage using the generic evidence
    already gathered (resolved file/line, surrounding context, error
    stack) — do not force it into an existing category that doesn't
    actually match the evidence.

IMPORTANT — line numbers may not belong to the file you think.
AWS Transform (and mainframe COBOL compilers generally) report line
numbers against the PREPROCESSED source, i.e. after every COPY statement
has been textually replaced by the referenced copybook's contents. A
finding's lineNumber can therefore be far beyond the raw .cbl file's own
line count once one or more COPY members have been inlined above that
point. To correlate a finding back to an editable file, this script
expands COPY statements the same way and keeps a mapping from
expanded-line-number -> (original relPath, original line number). This
resolution step is generic and applies regardless of what the root cause
turns out to be.

Usage:
    python3 correlate_with_source.py \\
        --findings findings.json \\
        --source-zip full_source.zip \\
        --out annotated_findings.json
"""
import argparse
import json
import re
import sys
import zipfile
from pathlib import Path

CONTEXT_LINES = 8
COBOL_MAX_COLUMN = 72  # Area A/B ends at column 72 in fixed-format COBOL; 73-80 is the identification area

COPY_STATEMENT_RE = re.compile(
    r'^\s*COPY\s+([A-Za-z0-9$#@_-]+)(?:\s+(?:OF|IN)\s+[A-Za-z0-9$#@_-]+)?\s*(REPLACING\s+.*)?\.?\s*$',
    re.IGNORECASE,
)


def _read_zip_text(zf, rel_path):
    names = set(zf.namelist())
    candidates = [rel_path, rel_path.lstrip("/")]
    for c in candidates:
        if c in names:
            with zf.open(c) as f:
                raw = f.read()
            return raw.decode("utf-8", errors="replace")
    return None


def _find_copybook_path(zf, member_name, known_dirs=("cpy", "cobcopy", "copy")):
    """Locate a copybook member inside the zip regardless of extension/case."""
    names = zf.namelist()
    member_lower = member_name.lower()
    # Prefer exact matches under conventional copybook directories first.
    for n in names:
        base = n.rsplit("/", 1)[-1]
        stem = base.split(".")[0]
        if stem.lower() == member_lower:
            for d in known_dirs:
                if f"/{d}/" in f"/{n}" or n.startswith(f"{d}/"):
                    return n
    # Fall back to any file whose stem matches, anywhere in the archive.
    for n in names:
        base = n.rsplit("/", 1)[-1]
        stem = base.split(".")[0]
        if stem.lower() == member_lower:
            return n
    return None


def expand_copy_statements(zf, entry_rel_path, _visited=None, _depth=0):
    """Recursively expand COPY statements starting from entry_rel_path.

    Returns (expanded_lines, line_map) where line_map[i] (0-indexed into
    expanded_lines) = {"relPath": ..., "line": <1-indexed original line>}.
    Lines belonging to unresolved COPY members (not found in the zip) are
    left as the literal 'COPY X.' statement itself, mapped back to the
    including file/line, so callers can still flag "copybook not found".
    """
    if _visited is None:
        _visited = set()
    if _depth > 25:  # runaway recursion guard (circular COPY chains)
        return [], []

    text = _read_zip_text(zf, entry_rel_path)
    if text is None:
        return None, None

    raw_lines = text.splitlines()
    expanded_lines = []
    line_map = []

    for lineno, line in enumerate(raw_lines, start=1):
        m = COPY_STATEMENT_RE.match(line)
        member = m.group(1) if m else None
        if member and entry_rel_path not in _visited:
            copy_path = _find_copybook_path(zf, member)
            if copy_path:
                sub_visited = _visited | {entry_rel_path}
                sub_lines, sub_map = expand_copy_statements(zf, copy_path, sub_visited, _depth + 1)
                if sub_lines is not None:
                    expanded_lines.extend(sub_lines)
                    line_map.extend(sub_map)
                    continue
        # Not a COPY statement, or copybook unresolved/circular: keep as-is.
        expanded_lines.append(line)
        line_map.append({"relPath": entry_rel_path, "line": lineno})

    return expanded_lines, line_map


def read_source_lines(zf, rel_path):
    """Return list of RAW source lines (no trailing newline) for rel_path, or
    None if missing. Does NOT expand COPY statements — use
    build_expanded_view() for line-number-accurate lookups."""
    text = _read_zip_text(zf, rel_path)
    if text is None:
        return None
    return text.splitlines()


def build_expanded_view(zf, rel_path):
    """Build the expanded (COPY-resolved) view of rel_path plus its line map.
    Returns (expanded_lines, line_map) or (None, None) if rel_path itself is
    missing from the zip."""
    return expand_copy_statements(zf, rel_path)


def resolve_location(line_map, expanded_line_number):
    """Map an AWS-Transform-reported line number (against the COPY-expanded
    view of the entry file) back to the real (relPath, line) it came from."""
    if not line_map or not expanded_line_number:
        return None
    idx = int(expanded_line_number) - 1
    if idx < 0 or idx >= len(line_map):
        return None
    return line_map[idx]


# ---------------------------------------------------------------------------
# Pattern library — EXTENSIBLE, NOT EXHAUSTIVE.
#
# AWS Transform can surface an open-ended variety of parsing/DSL/CFG errors
# depending on COBOL dialect, vendor extensions, and the transcription
# history of the codebase being analyzed. The matchers registered in
# PATTERN_LIBRARY below encode a handful of concrete, evidence-based
# examples (documented with worked examples in
# references/error_taxonomy.md). Treat them as a starting point:
#
#   - Add a new matcher function with the same signature
#     `def my_matcher(ctx: PatternContext) -> dict | None` and register it
#     in PATTERN_LIBRARY when you discover a new recurring pattern.
#   - Each matcher should return None immediately if the finding's
#     evidence doesn't match its pattern, so matchers can be tried cheaply
#     in sequence.
#   - A matcher that DOES match must return a dict with at least:
#       category (str), confidence ("high"|"medium"|"low"),
#       is_false_positive (bool), rationale (str explaining the evidence).
#   - Never return a category based on guessing intent/business logic —
#     only on structural evidence available in the finding, the resolved
#     source lines, or the expanded view.
# ---------------------------------------------------------------------------

class PatternContext:
    """Evidence bundle passed to every pattern matcher."""

    def __init__(self, finding, resolved_lines, resolved_rel_path, expanded_lines):
        self.finding = finding
        self.summary = finding.get("summary") or ""
        self.issue_type = finding.get("type") or ""
        self.error_cause = finding.get("error_cause") or []
        main_bad = finding.get("main_bad_line") or {}
        self.line_content = main_bad.get("lineContent") or ""
        loc = finding.get("resolved_location")
        self.resolved_line_no = loc.get("line") if loc else None
        self.resolved_lines = resolved_lines
        self.resolved_rel_path = resolved_rel_path
        self.expanded_lines = expanded_lines
        self.is_copybook = bool(resolved_rel_path) and "/cpy/" in f"/{resolved_rel_path}"

    def resolved_raw_line(self):
        if self.resolved_lines and self.resolved_line_no and 1 <= self.resolved_line_no <= len(self.resolved_lines):
            return self.resolved_lines[self.resolved_line_no - 1]
        return None


def label_exists_in_source(lines, label):
    """Check whether a COBOL paragraph/section label is actually defined in source.
    A definition looks like '<label>.' starting near column 8-11 (Area A)."""
    if not lines:
        return False
    pattern = re.compile(r"^\s{0,11}" + re.escape(label) + r"\s*\.", re.IGNORECASE)
    for line in lines:
        if pattern.match(line):
            return True
    return False


def match_cascading_or_missing_label(ctx):
    """Example pattern: 'Unknown label "<name>"'.

    If the label actually exists somewhere in the expanded source, this is
    almost always a cascading symptom of an earlier, unrelated parse
    failure that corrupted the parser's label table — not a defect at the
    referenced label itself. If the label truly does not exist anywhere,
    it's a genuine dangling reference.
    """
    m = re.search(r'Unknown label "([^"]+)"', ctx.summary)
    if not m:
        return None
    label = m.group(1)
    if label_exists_in_source(ctx.expanded_lines, label):
        return {
            "category": "cascading-unknown-label",
            "confidence": "high",
            "is_false_positive": True,
            "rationale": (
                f"Label '{label}' IS defined in the expanded source. This 'Unknown label' "
                "error is almost always a downstream symptom of an earlier, unrelated parse "
                "failure that corrupted the parser's label/paragraph table for the rest of "
                "the PROCEDURE DIVISION. Fix the earliest Critical/Fatal parsing-step issue "
                "in this file first, then re-run; this finding will likely disappear on its "
                "own without touching the label."
            ),
        }
    return {
        "category": "genuine-missing-label",
        "confidence": "high",
        "is_false_positive": False,
        "rationale": (
            f"Label '{label}' is referenced (e.g. by PERFORM/GO TO) but not found anywhere "
            "in the resolved/expanded source. Likely a genuine typo or missing paragraph; "
            "needs manual review before changing control flow."
        ),
    }


NON_PRINTABLE_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\xff]")


def _find_non_printable(text):
    """Return (index, char) of the first non-printable/non-ASCII character
    in text, or None if the line is clean 7-bit-ASCII printable content."""
    m = NON_PRINTABLE_RE.search(text)
    if not m:
        return None
    return m.start(), text[m.start()]


def match_non_printable_or_non_ascii(ctx):
    """Example pattern: the flagged (or immediately surrounding) line
    contains non-printable or non-ASCII byte(s).

    Mainframe source is frequently round-tripped through EBCDIC<->ASCII
    code-page conversions, FTP transfers in the wrong transfer mode, or
    manual copy/paste from terminal emulators, any of which can leave
    behind stray control characters, replacement characters, or
    codepage-mismatched punctuation (curly quotes, em-dashes, NBSP, etc.)
    that a strict grammar-based parser cannot tokenize. This is one of the
    most common real-world causes of otherwise-inexplicable parse errors
    at what looks like ordinary text.
    """
    raw_line = ctx.resolved_raw_line()
    check_line = raw_line if raw_line is not None else ctx.line_content
    if not check_line:
        return None
    hit = _find_non_printable(check_line)
    if hit is None:
        return None
    idx, char = hit
    return {
        "category": "non-printable-or-non-ascii-character",
        "confidence": "high",
        "is_false_positive": False,
        "rationale": (
            f"Line contains a non-printable/non-ASCII byte (0x{ord(char):02x}) at column "
            f"{idx + 1}, which a strict COBOL/JCL grammar cannot tokenize as part of a "
            "normal statement, literal, or identifier. Commonly introduced by EBCDIC<->ASCII "
            "code-page conversion, binary-mode file transfer of text files, or copy/paste "
            "from a terminal emulator. Safe fix: replace the offending byte(s) with the "
            "correct ASCII character they were meant to represent (e.g. a straight quote/"
            "hyphen/space) — verify against surrounding context or the original mainframe "
            "encoding table rather than simply deleting the byte, since deleting can itself "
            "shift column alignment for the rest of the line."
        ),
    }


def match_column_alignment_violation(ctx):
    """Example pattern: fixed-format COBOL/JCL/copybook source where a
    statement/label does not start within its expected column range (Area
    A: cols 8-11 for level numbers/section/paragraph names, Area B: cols
    12-72 for statements; JCL: cols 1-71 for most statements, continuation
    conventions differ by record type). This matcher looks for generic
    structural symptoms of column misalignment rather than one specific
    keyword, so it generalizes beyond the VALUE-clause case handled by
    match_column72_overflow:

      (a) The analyzer's own message hints at a positional/column problem
          (checked first, cheap and precise when available).
      (b) The resolved line's sequence area (cols 1-6) or indicator
          column (col 7) don't match fixed-format conventions.
      (c) A more severe, easy-to-miss variant of (b): the line's program
          text starts AT column 1 instead of Area A (col 8+), i.e. the
          whole 6-column sequence area and column-7 indicator are simply
          absent. This happens when a copybook/program was re-typed,
          exported, or hand-edited by someone/something that stripped
          fixed-format columns entirely (common when source is pasted
          from a free-format text editor or a non-mainframe tool). Such a
          line is not just "misaligned" — every subsequent column-
          dependent rule (Area A vs B, continuation, comment indicator)
          is off by 6-7 characters for that line, so this is called out
          as its own case with a more specific rationale.
    """
    raw_line = ctx.resolved_raw_line()
    if not raw_line:
        return None

    stripped_content = raw_line.strip()

    # (c) Whole-line content shifted to start at column 1: a letter/digit
    # that looks like the start of a COBOL word/level-number sits in
    # column 1, with no sequence area and no indicator column at all.
    if stripped_content and raw_line[:1] not in ("", " ") and not raw_line[:6].strip().isdigit():
        # Column 1 holds a non-blank, non-purely-numeric-sequence character
        # AND this isn't itself a valid Area-A construct (Area A starts at
        # column 8, so anything meaningful at column 1 for a COBOL
        # statement/level-number/paragraph name is out of place).
        looks_like_cobol_token = bool(re.match(r"^[A-Za-z0-9][A-Za-z0-9$#@_-]*", raw_line))
        if looks_like_cobol_token and ctx.resolved_rel_path and (
            ctx.resolved_rel_path.endswith(".cbl") or ctx.resolved_rel_path.endswith(".cpy")
        ):
            return {
                "category": "code-starting-at-column1-not-area-a",
                "confidence": "medium",
                "is_false_positive": False,
                "rationale": (
                    "This line's program text begins at column 1 instead of Area A "
                    "(column 8+), meaning the fixed-format sequence area (cols 1-6) and "
                    "indicator column (col 7) are entirely missing for this line. This is a "
                    "more severe case than a small column drift: every column-dependent "
                    "parsing rule (level-number placement, paragraph/section name area, "
                    "comment indicator, continuation marker) is offset by 6-7 characters "
                    "for this line specifically. Commonly introduced when a copybook/program "
                    "was re-typed, exported from a non-mainframe tool, or hand-edited in a "
                    "free-format text editor that stripped leading columns. Safe fix: shift "
                    "this line's content right so it starts at column 8 (Area A) — matching "
                    "the column convention of the surrounding, correctly-formatted lines in "
                    "the same file — without changing the tokens themselves."
                ),
            }

    if "column" not in ctx.summary.lower() and "indicator" not in ctx.summary.lower() and "sequence" not in ctx.summary.lower():
        # Only apply the general (b) alignment check when the analyzer's
        # own message hints at a positional/column problem; otherwise this
        # matcher would be too eager and misclassify unrelated errors.
        return None

    seq_area = raw_line[:6] if len(raw_line) >= 6 else raw_line
    indicator = raw_line[6] if len(raw_line) > 6 else " "
    seq_ok = seq_area.strip() == "" or seq_area.strip().isdigit()
    indicator_ok = indicator in (" ", "-", "*", "/")
    if seq_ok and indicator_ok:
        return None
    return {
        "category": "column-alignment-violation",
        "confidence": "medium",
        "is_false_positive": False,
        "rationale": (
            f"Analyzer message references column/indicator/sequence positioning, and the "
            f"resolved line's sequence area (cols 1-6: '{seq_area}') or indicator column "
            f"(col 7: '{indicator}') does not match fixed-format conventions. This typically "
            "happens when source was re-indented, tab-expanded inconsistently, or edited "
            "with a non-column-aware editor. Fix by realigning the line to the file's fixed-"
            "format column layout (compare against neighboring, correctly-parsed lines in the "
            "same file) without changing any token's characters or order."
        ),
    }


def match_column72_overflow(ctx):
    """Example pattern: a VALUE/PICTURE structure error where the resolved
    physical line demonstrably extends past column 72 (the fixed-format
    COBOL program-text boundary) into the identification/sequence area.
    """
    if "structure" not in ctx.summary.lower() or "value" not in ctx.summary.lower():
        return None
    raw_line = ctx.resolved_raw_line()
    check_line = raw_line if raw_line is not None else ctx.line_content
    if not check_line or len(check_line.rstrip()) < COBOL_MAX_COLUMN:
        return {
            "category": "unresolved-value-structure-error",
            "confidence": "low",
            "is_false_positive": False,
            "rationale": (
                "Summary suggests a VALUE-clause parsing error but the resolved line did not "
                "clearly show a column-72 overflow. Needs manual review of the exact literal "
                "and surrounding context."
            ),
        }
    beyond_72 = check_line[COBOL_MAX_COLUMN:].strip()
    category = "column72-identification-area-overflow" if ctx.is_copybook else "column72-truncation"
    return {
        "category": category,
        "confidence": "high" if beyond_72 else "medium",
        "is_false_positive": False,
        "rationale": (
            f"Line extends past column 72 into the identification/sequence area "
            f"(columns 73-80 contain: '{beyond_72}'). Fixed-format COBOL parsers "
            "(compilers and AWS Transform alike) only read columns 1-72 as program text; "
            "anything past column 72 is ignored, truncating the statement mid-token. This "
            "is a pre-existing authoring/export defect in the " +
            ("copybook" if ctx.is_copybook else "program") +
            " (the line is simply too long), not a business-logic issue. Safe fix: move "
            "the overflow text onto a properly marked continuation line (col 7 '-'); the "
            "original characters are preserved exactly, only reformatted."
        ),
    }


def match_bms_macro_continuation(ctx):
    """Example pattern: BMS macro parser reports a broken continuation
    between parameter lines."""
    if "error while parsing macro" not in ctx.summary.lower() and "continuation detection" not in ctx.summary.lower():
        return None
    return {
        "category": "bms-macro-continuation",
        "confidence": "medium",
        "is_false_positive": False,
        "rationale": (
            "BMS macro parser expected a continuation marker and found whitespace instead, "
            "usually because the sequence-number/continuation area (columns 72-80) was "
            "altered (e.g. renumbered, or a continuation flag is missing/misaligned). "
            "Verify columns 72-80 of the flagged and surrounding lines against the map's "
            "original conventions before editing; recommend visual verification of the "
            "screen layout after any fix, not just structural re-parse."
        ),
    }


def match_copybook_comment_misparsed(ctx):
    """Example pattern: a stray '*' token trips the parser inside what
    reads as a comment block, usually because a sequence-number-like
    prefix pushed the comment indicator out of column 7."""
    if "copybook" not in ctx.summary.lower():
        return None
    if "OPERATOR_MULT_DIV" not in str(ctx.error_cause):
        return None
    return {
        "category": "copybook-comment-misparsed-as-code",
        "confidence": "medium",
        "is_false_positive": False,
        "rationale": (
            "Offending symbol is '*' inside what should be a comment line. Likely the "
            "comment indicator in column 7 is missing, or a sequence-number-like prefix was "
            "written into columns 1-6, pushing content out of alignment so the parser reads "
            "commentary as code. Fix by restoring standard comment formatting (col 7 = '*')."
        ),
    }


def match_benign_cfg_note(ctx):
    """Example pattern: the analyzer explicitly states a finding has no
    functional impact (e.g. control-flow aliasing approximations for
    built-in SQL functions). Take the tool at its word — no fix needed."""
    if "no functional impact on generated code" not in ctx.summary.lower():
        return None
    return {
        "category": "benign-analyzer-note",
        "confidence": "high",
        "is_false_positive": True,
        "rationale": (
            "The analyzer explicitly states this finding has no functional impact on "
            "generated code. No fix required; record as an informational note only."
        ),
    }


def match_unresolved_field_cascading(ctx):
    """Example pattern: 'Unknown field name X' — typically a symptom of a
    copybook that defines that field failing to parse earlier, rather than
    a genuinely missing field."""
    m = re.search(r'Unknown field name ([\w-]+)', ctx.summary)
    if not m:
        return None
    field = m.group(1)
    prefix = field.split("-")[0]
    return {
        "category": "unresolved-field-cascading",
        "confidence": "medium",
        "is_false_positive": False,
        "rationale": (
            f"Field '{field}' could not be resolved by the linker at this reference point. "
            "This is typically NOT a missing field, but a symptom of a copybook (often one "
            f"whose record-name prefix matches '{prefix}') failing to parse earlier in the "
            "run, so its structure was never registered. Check other findings/artifacts for "
            "a copybook with a matching prefix that has ERROR/WARNING status and fix that "
            "first; re-run to confirm this finding clears."
        ),
    }


def match_generic_parse_or_dsl_failure(ctx):
    """Catch-most-but-not-all: any Parsing/DSL-generation error that didn't
    match a more specific pattern above. This intentionally returns a
    low-confidence, non-actionable classification rather than pretending
    to know the cause — the point is to flag it for evidence-based manual
    or LLM-assisted review using the resolved location and context that
    have already been gathered, not to force-fit it into a category."""
    if ctx.issue_type in ("Parsing error", "Gapwalk dsl error"):
        return {
            "category": "unclassified-parse-or-dsl-error",
            "confidence": "low",
            "is_false_positive": False,
            "rationale": (
                "This is a parser/DSL-generation failure that did not match any pattern in "
                "PATTERN_LIBRARY. Review the resolved file/line and surrounding context to "
                "determine whether it is: a genuine malformed statement, an unsupported (but "
                "valid) COBOL/vendor extension, or a cascading effect of an earlier error in "
                "the same file (check whether other findings in this file have an earlier "
                "line number and a Critical/Fatal severity). If a new recurring shape is "
                "identified, consider adding a dedicated matcher to PATTERN_LIBRARY."
            ),
        }
    return None


# Order matters: more specific matchers should generally run before the
# generic catch-most matcher. Add new matchers here.
PATTERN_LIBRARY = [
    match_non_printable_or_non_ascii,
    match_cascading_or_missing_label,
    match_column72_overflow,
    match_column_alignment_violation,
    match_bms_macro_continuation,
    match_copybook_comment_misparsed,
    match_benign_cfg_note,
    match_unresolved_field_cascading,
    match_generic_parse_or_dsl_failure,
]


def classify_finding(finding, resolved_lines, resolved_rel_path, expanded_lines=None):
    """Attach a root-cause classification to a finding by trying each
    matcher in PATTERN_LIBRARY in order and using the first one that
    returns a result. If none match, the finding is explicitly flagged as
    needing manual/LLM-assisted classification — this is expected and
    common; AWS Transform's possible error surface is not enumerable.

    `resolved_lines` are the raw lines of the file that ACTUALLY contains
    the flagged line (which may be a copybook, not the entry .cbl).
    `expanded_lines` is the full COPY-expanded view of the entry file,
    useful for matchers that need to search across the whole preprocessed
    program (e.g. "does this label exist anywhere").

    Returns a dict with keys: category, confidence, rationale,
    is_false_positive, matched_by.
    """
    context = PatternContext(
        finding=finding,
        resolved_lines=resolved_lines or [],
        resolved_rel_path=resolved_rel_path,
        expanded_lines=expanded_lines if expanded_lines is not None else (resolved_lines or []),
    )

    for matcher in PATTERN_LIBRARY:
        result = matcher(context)
        if result is not None:
            result.setdefault("matched_by", matcher.__name__)
            return result

    return {
        "category": "needs-manual-classification",
        "confidence": "n/a",
        "is_false_positive": False,
        "matched_by": None,
        "rationale": (
            "No pattern in this skill's PATTERN_LIBRARY recognized this finding's "
            "summary/errorCause shape. This does NOT mean it is unimportant — it means "
            "a human (or an LLM given the resolved file/line and surrounding context "
            "captured in this finding) needs to read the actual source and decide the "
            "root cause. Common outcomes: a genuine, previously-unseen defect requiring "
            "a manual fix; a new cascading-failure pattern worth adding to "
            "PATTERN_LIBRARY for future runs; or an unsupported construct that is a "
            "candidate for exclusion from the target zip if it cannot be fixed in scope."
        ),
    }


def get_context(lines, line_number, context=CONTEXT_LINES):
    if not lines or not line_number:
        return []
    idx = int(line_number) - 1
    start = max(0, idx - context)
    end = min(len(lines), idx + context + 1)
    return [
        {"lineNumber": i + 1, "lineContent": lines[i]}
        for i in range(start, end)
    ]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--findings", required=True, type=Path, help="findings.json from parse_debug_bundle.py")
    parser.add_argument("--source-zip", required=True, type=Path, help="Original source zip submitted to AWS Transform")
    parser.add_argument("--out", required=True, type=Path, help="Output annotated findings JSON")
    args = parser.parse_args()

    with open(args.findings) as f:
        result = json.load(f)

    expanded_view_cache = {}   # entry_rel_path -> (expanded_lines, line_map) or (None, None)
    raw_lines_cache = {}       # rel_path -> raw lines or None
    missing_artifacts = set()

    with zipfile.ZipFile(args.source_zip, "r") as zf:

        def get_raw_lines(rel_path):
            if rel_path not in raw_lines_cache:
                raw_lines_cache[rel_path] = read_source_lines(zf, rel_path)
            return raw_lines_cache[rel_path]

        for finding in result["findings"]:
            entry_rel_path = finding["artifact"]

            if entry_rel_path not in expanded_view_cache:
                expanded_view_cache[entry_rel_path] = build_expanded_view(zf, entry_rel_path)
            expanded_lines, line_map = expanded_view_cache[entry_rel_path]

            if expanded_lines is None:
                missing_artifacts.add(entry_rel_path)
                finding["source_found"] = False
                finding["classification"] = {
                    "category": "source-file-not-found",
                    "confidence": "high",
                    "is_false_positive": False,
                    "rationale": f"'{entry_rel_path}' was not found in the provided source zip at the same relative path.",
                }
                continue

            finding["source_found"] = True
            location = resolve_location(line_map, finding.get("line_number"))
            finding["resolved_location"] = location

            if location:
                resolved_rel_path = location["relPath"]
                resolved_lines = get_raw_lines(resolved_rel_path)
                finding["source_context"] = get_context(resolved_lines, location["line"])
            else:
                resolved_rel_path = entry_rel_path
                resolved_lines = get_raw_lines(entry_rel_path)
                finding["source_context"] = get_context(resolved_lines, finding.get("line_number"))

            finding["classification"] = classify_finding(finding, resolved_lines, resolved_rel_path, expanded_lines)

    with open(args.out, "w") as f:
        json.dump(result, f, indent=2)

    cat_counts = {}
    fp_count = 0
    copybook_resolved = 0
    for finding in result["findings"]:
        cat = finding.get("classification", {}).get("category", "uncategorized")
        cat_counts[cat] = cat_counts.get(cat, 0) + 1
        if finding.get("classification", {}).get("is_false_positive"):
            fp_count += 1
        loc = finding.get("resolved_location")
        if loc and loc["relPath"] != finding["artifact"]:
            copybook_resolved += 1

    print(f"Annotated {len(result['findings'])} findings.")
    print(f"Category breakdown: {json.dumps(cat_counts, indent=2)}")
    print(f"Likely false positives / benign (no fix needed): {fp_count}")
    print(f"Findings resolved to a different physical file via COPY expansion: {copybook_resolved}")
    if missing_artifacts:
        print(f"WARNING: {len(missing_artifacts)} artifact path(s) not found in source zip:", file=sys.stderr)
        for m in sorted(missing_artifacts):
            print(f"  - {m}", file=sys.stderr)
    print(f"Wrote annotated findings to {args.out}")


if __name__ == "__main__":
    main()

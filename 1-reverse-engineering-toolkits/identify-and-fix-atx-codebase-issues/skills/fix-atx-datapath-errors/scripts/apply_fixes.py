#!/usr/bin/env python3
"""
apply_fixes.py

Applies safe, business-rule-neutral fixes to a copy of the ORIGINAL source
zip based on the annotated findings produced by correlate_with_source.py,
and writes a new "target" zip.

Design principles (important — read before extending):

  * This script NEVER changes program logic, calculations, conditions, or
    data values. It only repairs mechanical/syntactic defects that stop the
    AWS Transform parser from reading code that a mainframe compiler would
    otherwise accept (or that are themselves harmless transcription/export
    errors, e.g. a literal that spills past column 72, or a line typed
    starting at column 1 instead of Area A).
  * Fixes are applied at the RESOLVED location (the real physical file and
    line that the annotated finding points to via COPY expansion), not at
    the raw line number reported by AWS Transform against the entry
    program — those two are frequently different files. See
    correlate_with_source.py for why.
  * Every fix is applied from a specific, auditable classification category
    (see references/error_taxonomy.md). Unknown/low-confidence categories
    are NEVER auto-fixed — they are left as-is and reported for manual
    review, or removed from the target zip if explicitly requested via
    --remove-unfixable.
  * "Cascading" and "benign" classifications are never edited: editing them
    would either be a no-op (label already exists) or risk changing
    behavior for zero parsing benefit (CFG aliasing notes).
  * All changes are logged so a human can review exactly what changed and
    why before the target zip is trusted.

Currently automated fix categories (see references/error_taxonomy.md for
the full, extensible pattern library — these are the subset judged safe
to auto-apply without any semantic guessing):
  - column72-identification-area-overflow:
        The line's program text extends past column 72 into the
        identification/sequence area (columns 73-80), so any
        standards-compliant parser truncates it mid-token. Fix: move
        everything from column 73 onward onto a new continuation line
        (col 7 = '-', content resumes at col 8), preserving every
        character exactly as originally typed — no data is changed, only
        re-wrapped across two physical lines that together fit the
        original text.
  - copybook-comment-misparsed-as-code:
        Restores a comment line's column-7 indicator ('*') when a
        sequence-number prefix or missing indicator caused the parser to
        treat commentary as executable/data content.
  - code-starting-at-column1-not-area-a:
        Shifts a line's content right by 6 columns when it was authored
        starting at column 1 instead of Area A (column 8+), restoring the
        fixed-format sequence area (cols 1-6, left blank) and indicator
        column (col 7, left blank) ahead of the original text.

Everything else (cascading-unknown-label, benign-analyzer-note,
unresolved-field-cascading, unclassified-parse-or-dsl-error,
non-printable-or-non-ascii-character, column-alignment-violation,
unresolved-value-structure-error, source-file-not-found,
genuine-missing-label, needs-manual-classification) is left untouched by
default and reported for manual review — either because the analyzer
explicitly says no fix is needed (benign/cascading), or because a correct
fix would require judgment this script cannot safely automate (e.g.
guessing the intended character behind a non-printable byte, or deciding
whether a missing label is a typo vs. a deliberate removal).

Usage:
    # Preview only — no zip written, just prints what WOULD change
    python3 apply_fixes.py --annotated annotated_findings.json \\
        --source-zip full_source.zip --out-zip target_fixed.zip --dry-run

    # Apply automated fixes, write target zip + change log
    python3 apply_fixes.py --annotated annotated_findings.json \\
        --source-zip full_source.zip --out-zip target_fixed.zip \\
        --changelog changelog.json

    # Additionally remove files that still have unresolved ERROR-status
    # issues with no safe automated fix (last resort, logged in changelog)
    python3 apply_fixes.py --annotated annotated_findings.json \\
        --source-zip full_source.zip --out-zip target_fixed.zip \\
        --changelog changelog.json --remove-unfixable
"""
import argparse
import json
import zipfile
from collections import defaultdict
from pathlib import Path

AUTO_FIX_CATEGORIES = {
    "column72-identification-area-overflow",
    "copybook-comment-misparsed-as-code",
    "code-starting-at-column1-not-area-a",
}
COBOL_AREA_B_END = 72  # 1-indexed; columns 1-72 are program text in fixed-format COBOL
COBOL_AREA_A_START = 8  # 1-indexed; Area A (level numbers, section/paragraph names) starts here


def fix_column72_overflow(lines, line_no):
    """Move any text past column 72 onto a new continuation line.

    This is a pure reformatting operation: every character that was
    present in the original line is preserved, just split across two
    physical lines so that no program-text line exceeds column 72. The
    continuation line marks column 7 with '-' per fixed-format COBOL
    convention. If the original line is only sequence numbers past col 72
    (no actual program text there), this is still safe — worst case the
    continuation line has trailing sequence-number characters, which are
    themselves ignored by a compliant parser as they are also past col 72
    on the new line only if they still overflow (they won't, in the tested
    cases, since sequence numbers are short: e.g. 8 chars).
    """
    if not line_no or line_no > len(lines) or line_no < 1:
        return None
    idx = line_no - 1
    original = lines[idx]

    if len(original) <= COBOL_AREA_B_END:
        return None  # nothing overflows column 72; not this defect

    overflow = original[COBOL_AREA_B_END:]
    if not overflow.strip():
        return None  # only trailing whitespace past col 72; nothing to move

    head = original[:COBOL_AREA_B_END]
    continuation_line = " " * 6 + "-" + " " * 4 + overflow.strip()

    new_lines = list(lines)
    new_lines[idx] = head
    new_lines.insert(idx + 1, continuation_line)
    return new_lines


def fix_copybook_comment(lines, line_no):
    """Restore column-7 '*' indicator on a line that was misread as code
    because a sequence-number-like prefix was written into columns 1-6,
    pushing a comment's leading '*' out of column 7."""
    if not line_no or line_no > len(lines) or line_no < 1:
        return None
    idx = line_no - 1
    original = lines[idx]

    if len(original) < 7:
        return None

    col7 = original[6] if len(original) > 6 else " "
    if col7 == "*":
        return None  # already fine

    prefix = original[:6]
    rest = original[6:]
    if not prefix.strip().isdigit():
        return None
    if "*" not in rest[:4]:
        return None

    star_pos = rest.index("*")
    fixed = " " * 6 + "*" + rest[star_pos + 1:]
    new_lines = list(lines)
    new_lines[idx] = fixed
    return new_lines


def fix_code_starting_at_column1(lines, line_no):
    """Shift a line's content right by (COBOL_AREA_A_START - 1) columns
    when it was authored starting at column 1 instead of Area A, so the
    fixed-format sequence area and indicator column are restored ahead of
    the existing text. Declines (returns None) if shifting would push the
    line past column 72, since that would just create a NEW column-72
    overflow rather than fixing anything — that combined case needs
    manual review.
    """
    if not line_no or line_no > len(lines) or line_no < 1:
        return None
    idx = line_no - 1
    original = lines[idx]

    if not original or original[0] in (" ",):
        return None  # already has something in column 1 that isn't code text, or blank

    shift = COBOL_AREA_A_START - 1
    if len(original.rstrip()) + shift > COBOL_AREA_B_END:
        return None  # shifting would overflow column 72; needs manual review instead

    shifted = (" " * shift) + original
    new_lines = list(lines)
    new_lines[idx] = shifted
    return new_lines


FIXERS = {
    "column72-identification-area-overflow": fix_column72_overflow,
    "copybook-comment-misparsed-as-code": fix_copybook_comment,
    "code-starting-at-column1-not-area-a": fix_code_starting_at_column1,
}


def load_zip_bytes(zip_path):
    entries = {}
    with zipfile.ZipFile(zip_path, "r") as zf:
        for info in zf.infolist():
            with zf.open(info) as f:
                entries[info.filename] = f.read()
    return entries


def target_location(finding):
    """Return (relPath, line) to apply a fix at: the resolved (COPY-expanded)
    location if available, otherwise the finding's own artifact/line."""
    loc = finding.get("resolved_location")
    if loc and loc.get("relPath") and loc.get("line"):
        return loc["relPath"], loc["line"]
    return finding["artifact"], finding.get("line_number")


def apply_fixes(annotated, source_entries, remove_unfixable):
    findings_by_file = defaultdict(list)
    for finding in annotated["findings"]:
        rel_path, line_no = target_location(finding)
        findings_by_file[rel_path].append((line_no, finding))

    changelog = {"fixed": [], "skipped": [], "removed": [], "unchanged_note": []}
    updated_entries = dict(source_entries)

    artifact_status = {a["relPath"]: a["status"] for a in annotated.get("artifact_index", [])}
    unfixed_artifacts = set()

    for rel_path, items in findings_by_file.items():
        if rel_path not in source_entries:
            for _, finding in items:
                changelog["skipped"].append({
                    "artifact": finding["artifact"], "resolved_file": rel_path,
                    "line": finding.get("line_number"), "category": finding.get("classification", {}).get("category"),
                    "reason": f"Resolved file '{rel_path}' not present in source zip; cannot apply fix.",
                })
            continue

        text = source_entries[rel_path].decode("utf-8", errors="replace")
        lines = text.splitlines()

        # Sort by line number descending so earlier inserts don't shift
        # later line numbers within the same physical file during this pass.
        for line_no, finding in sorted(items, key=lambda t: (t[0] or 0), reverse=True):
            classification = finding.get("classification", {})
            category = classification.get("category")
            entry_artifact = finding["artifact"]

            if classification.get("is_false_positive"):
                changelog["unchanged_note"].append({
                    "artifact": entry_artifact, "resolved_file": rel_path, "line": line_no,
                    "category": category, "reason": classification.get("rationale"),
                })
                continue

            if category not in AUTO_FIX_CATEGORIES:
                unfixed_artifacts.add(entry_artifact)
                changelog["skipped"].append({
                    "artifact": entry_artifact, "resolved_file": rel_path, "line": line_no,
                    "category": category, "severity": finding.get("severity"),
                    "summary": finding.get("summary"),
                    "reason": "No automated fixer available for this category; needs manual review.",
                })
                continue

            fixer = FIXERS[category]
            result = fixer(lines, line_no)
            if result is None:
                unfixed_artifacts.add(entry_artifact)
                changelog["skipped"].append({
                    "artifact": entry_artifact, "resolved_file": rel_path, "line": line_no,
                    "category": category, "severity": finding.get("severity"),
                    "summary": finding.get("summary"),
                    "reason": "Automated fixer declined (line did not match expected pattern); needs manual review.",
                })
                continue

            lines = result
            changelog["fixed"].append({
                "artifact": entry_artifact, "resolved_file": rel_path, "line": line_no,
                "category": category, "summary": finding.get("summary"),
            })

        new_text = "\n".join(lines) + "\n"
        updated_entries[rel_path] = new_text.encode("utf-8")

    removed_paths = set()
    if remove_unfixable:
        for artifact in unfixed_artifacts:
            if artifact_status.get(artifact) == "ERROR":
                removed_paths.add(artifact)
                changelog["removed"].append({
                    "artifact": artifact,
                    "reason": (
                        "Artifact still has one or more unresolved Fatal/Critical issues with "
                        "no safe automated fix available; removed from target zip per "
                        "--remove-unfixable so it does not block the AWS Transform run. "
                        "Original file is preserved in the source zip for manual remediation."
                    ),
                })

    for path in removed_paths:
        updated_entries.pop(path, None)

    return updated_entries, changelog


def write_zip(entries, out_path):
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in entries.items():
            zf.writestr(name, data)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--annotated", required=True, type=Path, help="annotated_findings.json from correlate_with_source.py")
    parser.add_argument("--source-zip", required=True, type=Path, help="Original source zip")
    parser.add_argument("--out-zip", required=True, type=Path, help="Path to write the fixed target zip")
    parser.add_argument("--changelog", type=Path, help="Path to write JSON changelog (fixed/skipped/removed)")
    parser.add_argument("--remove-unfixable", action="store_true",
                         help="Remove artifacts from the target zip that still have unresolved ERROR-status issues with no safe automated fix")
    parser.add_argument("--dry-run", action="store_true", help="Compute and print the changelog without writing the target zip")
    args = parser.parse_args()

    with open(args.annotated) as f:
        annotated = json.load(f)

    source_entries = load_zip_bytes(args.source_zip)
    updated_entries, changelog = apply_fixes(annotated, source_entries, args.remove_unfixable)

    print(f"Fixed: {len(changelog['fixed'])} issue(s)")
    print(f"Skipped (needs manual review): {len(changelog['skipped'])} issue(s)")
    print(f"Removed artifacts: {len(changelog['removed'])}")
    print(f"No-op / benign notes: {len(changelog['unchanged_note'])}")

    if args.changelog:
        with open(args.changelog, "w") as f:
            json.dump(changelog, f, indent=2)
        print(f"Wrote changelog to {args.changelog}")

    if args.dry_run:
        print("Dry run: target zip NOT written.")
        return

    write_zip(updated_entries, args.out_zip)
    print(f"Wrote target zip to {args.out_zip}")


if __name__ == "__main__":
    main()

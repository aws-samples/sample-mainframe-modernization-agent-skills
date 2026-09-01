#!/usr/bin/env python3
"""
capture_learnings.py

Step 5 (optional but recommended): after unresolved findings from this run
have been triaged and fixed by hand (or with LLM assistance), capture
*how* each one was actually resolved, so the learning is preserved and can
be fed back into this skill's reusable pattern library for future runs —
on this codebase or any other.

Why this exists: `correlate_with_source.py`'s PATTERN_LIBRARY only
recognizes a handful of worked-example patterns (see
references/error_taxonomy.md). Every run will likely surface findings
that don't match anything known yet (`needs-manual-classification`,
`unclassified-parse-or-dsl-error`, or other `skipped` items). Once a human
or an LLM works out the real root cause and fix for one of those, that
knowledge is easy to lose if it isn't written down somewhere durable. This
script gives that a structured, low-friction home.

Workflow:

  1. Run this script with --list to print every unresolved finding from
     the current run in a compact form, with a ready-to-fill JSON
     skeleton.

         python3 capture_learnings.py --annotated annotated_findings.json \\
             --changelog changelog.json --list \\
             --skeleton-out resolutions.skeleton.json

  2. Copy resolutions.skeleton.json to resolutions.json and fill in the
     "resolution" block for whichever findings you actually root-caused
     and fixed this run (skip the rest — partial is fine, this is meant
     to be incremental across runs).

  3. Record the filled-in resolutions into this skill's persistent
     learnings log:

         python3 capture_learnings.py --annotated annotated_findings.json \\
             --changelog changelog.json --resolutions resolutions.json \\
             --learnings-log ../references/learnings.jsonl \\
             --out learnings_summary.md

     This appends one JSON-lines record per resolved finding to
     `references/learnings.jsonl` (created if missing) and writes a
     Markdown summary (`learnings_summary.md`) that flags which of the
     newly captured learnings look like good candidates to promote into
     a permanent PATTERN_LIBRARY matcher (and, if mechanically fixable,
     an AUTO_FIX_CATEGORIES entry) versus which are too one-off/context-
     specific to generalize.

This script never edits correlate_with_source.py or apply_fixes.py
automatically — promoting a learning into actual code is a deliberate,
reviewed change (see references/error_taxonomy.md "How to extend this
pattern library"), not something to do unattended from free-text input.
"""
import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

UNRESOLVED_CATEGORIES = {
    "needs-manual-classification",
    "unclassified-parse-or-dsl-error",
    "unresolved-value-structure-error",
    "column-alignment-violation",
    "non-printable-or-non-ascii-character",
    "genuine-missing-label",
    "bms-macro-continuation",
    "source-file-not-found",
}


def load(path):
    with open(path) as f:
        return json.load(f)


def collect_unresolved(annotated, changelog):
    """Return the list of findings from this run that still need (or
    needed) manual attention: anything in changelog['skipped'], plus any
    finding whose classification category is in UNRESOLVED_CATEGORIES for
    good measure (covers runs where apply_fixes.py wasn't used yet)."""
    skipped_keys = set()
    for item in changelog.get("skipped", []):
        skipped_keys.add((item.get("resolved_file") or item.get("artifact"), item.get("line")))

    unresolved = []
    seen = set()
    for finding in annotated.get("findings", []):
        classification = finding.get("classification", {})
        loc = finding.get("resolved_location")
        key = (loc["relPath"] if loc else finding["artifact"], loc["line"] if loc else finding.get("line_number"))
        is_skipped = key in skipped_keys
        is_unresolved_category = classification.get("category") in UNRESOLVED_CATEGORIES
        if (is_skipped or is_unresolved_category) and key not in seen:
            seen.add(key)
            unresolved.append(finding)
    return unresolved


def build_skeleton(unresolved):
    """Build a fill-in-the-blanks skeleton for the operator to complete."""
    entries = []
    for finding in unresolved:
        loc = finding.get("resolved_location")
        entries.append({
            "artifact": finding["artifact"],
            "resolved_file": loc["relPath"] if loc else finding["artifact"],
            "resolved_line": loc["line"] if loc else finding.get("line_number"),
            "category_at_time_of_run": finding.get("classification", {}).get("category"),
            "summary": finding.get("summary"),
            "severity": finding.get("severity"),
            "resolution": {
                "root_cause": "<FILL IN: what was actually wrong, in plain language>",
                "fix_applied": "<FILL IN: what change resolved it (describe precisely; do not paste customer-identifying code)>",
                "was_business_logic_changed": False,
                "generalizable": "<FILL IN: true/false — could this same detection+fix apply to other codebases, or is it specific to this file?>",
                "suggested_pattern_signature": "<FILL IN, if generalizable: what structural evidence (summary text, errorCause shape, column pattern) would identify this pattern elsewhere?>",
                "notes": ""
            },
        })
    return entries


def write_skeleton(entries, path):
    with open(path, "w") as f:
        json.dump(entries, f, indent=2)


def validate_resolution(entry):
    res = entry.get("resolution", {})
    root_cause = (res.get("root_cause") or "").strip()
    fix_applied = (res.get("fix_applied") or "").strip()
    if not root_cause or root_cause.startswith("<FILL IN"):
        return False
    if not fix_applied or fix_applied.startswith("<FILL IN"):
        return False
    return True


def append_to_learnings_log(entries, log_path):
    log_path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).isoformat()
    appended = 0
    with open(log_path, "a") as f:
        for entry in entries:
            if not validate_resolution(entry):
                continue
            record = dict(entry)
            record["captured_at"] = timestamp
            f.write(json.dumps(record) + "\n")
            appended += 1
    return appended


def build_summary(entries, appended_count, log_path):
    lines = []
    lines.append("# Captured Learnings Summary")
    lines.append("")
    lines.append(f"{appended_count} resolved finding(s) appended to `{log_path}`.")
    lines.append("")

    valid = [e for e in entries if validate_resolution(e)]
    invalid = [e for e in entries if not validate_resolution(e)]

    if invalid:
        lines.append(f"{len(invalid)} entr(y/ies) were left blank/unfilled and were skipped (not an error — fill them in on a future run if resolved later).")
        lines.append("")

    generalizable = [e for e in valid if str(e["resolution"].get("generalizable")).lower() in ("true", "yes")]
    one_off = [e for e in valid if e not in generalizable]

    lines.append("## Candidates to promote into PATTERN_LIBRARY")
    lines.append("")
    if generalizable:
        lines.append(
            f"{len(generalizable)} learning(s) were marked generalizable. Review each one and, "
            "if confirmed, add a corresponding `match_*` function to `PATTERN_LIBRARY` in "
            "`scripts/correlate_with_source.py` (and a fixer + `AUTO_FIX_CATEGORIES` entry in "
            "`scripts/apply_fixes.py` if `was_business_logic_changed` is false and the fix is a "
            "pure, mechanical reformat). Document the new pattern in "
            "`references/error_taxonomy.md` following the existing worked-example format."
        )
        lines.append("")
        lines.append("| File | Line | Root cause | Suggested pattern signature | Business logic changed? |")
        lines.append("|---|---|---|---|---|")
        for e in generalizable:
            res = e["resolution"]
            lines.append(
                f"| `{e['resolved_file']}` | {e['resolved_line']} | {res.get('root_cause')} | "
                f"{res.get('suggested_pattern_signature', '')} | {res.get('was_business_logic_changed')} |"
            )
    else:
        lines.append("None this run.")
    lines.append("")

    lines.append("## One-off / context-specific resolutions (logged, not promoted)")
    lines.append("")
    if one_off:
        lines.append(
            f"{len(one_off)} learning(s) were recorded for traceability but marked as "
            "not generalizable (or left unmarked) — they remain in the learnings log for "
            "future reference but were not proposed as new pattern matchers."
        )
        lines.append("")
        lines.append("| File | Line | Root cause | Fix applied |")
        lines.append("|---|---|---|---|")
        for e in one_off:
            res = e["resolution"]
            lines.append(f"| `{e['resolved_file']}` | {e['resolved_line']} | {res.get('root_cause')} | {res.get('fix_applied')} |")
    else:
        lines.append("None.")
    lines.append("")

    lines.append("## Reminder")
    lines.append("")
    lines.append(
        "Promoting a learning into `PATTERN_LIBRARY`/`AUTO_FIX_CATEGORIES` is a deliberate, "
        "reviewed code change — this script never edits those files automatically. Business-"
        "logic-changing fixes should never be auto-promoted into a mechanical fixer, "
        "regardless of how the `generalizable` flag was set."
    )
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--annotated", required=True, type=Path)
    parser.add_argument("--changelog", type=Path)
    parser.add_argument("--list", action="store_true", help="Print unresolved findings and write a fill-in skeleton")
    parser.add_argument("--skeleton-out", type=Path, help="Where to write the fill-in-the-blanks resolutions skeleton (used with --list)")
    parser.add_argument("--resolutions", type=Path, help="Path to a filled-in resolutions JSON file (from a previous --list run)")
    parser.add_argument("--learnings-log", type=Path, default=Path("references/learnings.jsonl"), help="Persistent JSONL learnings log to append to")
    parser.add_argument("--out", type=Path, help="Where to write the Markdown learnings summary (used with --resolutions)")
    args = parser.parse_args()

    annotated = load(args.annotated)
    changelog = load(args.changelog) if args.changelog else {"fixed": [], "skipped": [], "removed": [], "unchanged_note": []}
    unresolved = collect_unresolved(annotated, changelog)

    if args.list:
        print(f"{len(unresolved)} unresolved finding(s) from this run:")
        cat_counts = Counter(f.get("classification", {}).get("category") for f in unresolved)
        for cat, n in cat_counts.most_common():
            print(f"  - {cat}: {n}")
        skeleton = build_skeleton(unresolved)
        if args.skeleton_out:
            write_skeleton(skeleton, args.skeleton_out)
            print(f"Wrote fill-in skeleton to {args.skeleton_out}")
            print("Copy it, fill in 'resolution' for whichever findings you root-caused, then re-run with --resolutions.")
        return

    if args.resolutions:
        entries = load(args.resolutions)
        appended = append_to_learnings_log(entries, args.learnings_log)
        print(f"Appended {appended} resolved learning(s) to {args.learnings_log}")
        if args.out:
            summary = build_summary(entries, appended, args.learnings_log)
            args.out.write_text(summary)
            print(f"Wrote summary to {args.out}")
        return

    parser.error("Specify either --list (to generate a skeleton) or --resolutions (to record filled-in learnings).")


if __name__ == "__main__":
    main()

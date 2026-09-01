#!/usr/bin/env python3
"""
generate_report.py

Produces a human-readable Markdown report summarizing an AWS Transform
(ATX) triage/fix run: what failed, why (root cause), what was
automatically fixed, what still needs manual review, and what was removed
from the target zip.

Inputs (all produced by earlier steps in this skill):
  --annotated   annotated_findings.json  (correlate_with_source.py)
  --changelog   changelog.json           (apply_fixes.py)
  --out         report.md

The report never embeds full source dumps — only the specific flagged
lines and a few lines of surrounding context, which is the same
granularity already present in the debug bundle.

Usage:
    python3 generate_report.py --annotated annotated_findings.json \\
        --changelog changelog.json --out report.md
"""
import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from apply_fixes import AUTO_FIX_CATEGORIES  # noqa: E402 - keep report in sync with the fixer's actual capability

CATEGORY_LABELS = {
    "column72-identification-area-overflow": "Copybook/program line overflows into identification area (cols 73-80)",
    "copybook-comment-misparsed-as-code": "Comment misaligned / misread as code",
    "code-starting-at-column1-not-area-a": "Code starts at column 1 instead of Area A (missing sequence/indicator columns)",
    "column-alignment-violation": "General column/indicator alignment violation",
    "non-printable-or-non-ascii-character": "Non-printable / non-ASCII character in source",
    "cascading-unknown-label": "Cascading false positive (label exists; earlier error corrupted parse state)",
    "genuine-missing-label": "Genuinely missing/undefined paragraph label",
    "bms-macro-continuation": "BMS macro continuation/formatting issue",
    "benign-analyzer-note": "Benign analyzer note (no functional impact)",
    "unresolved-field-cascading": "Unresolved field name (likely cascading from a copybook parse failure)",
    "unresolved-value-structure-error": "Unresolved VALUE/PICTURE structure error (needs manual review)",
    "unclassified-parse-or-dsl-error": "Unclassified parsing/DSL-generation error (needs manual review)",
    "source-file-not-found": "Referenced source file missing from provided source zip",
    "needs-manual-classification": "No known pattern matched — needs manual/LLM-assisted triage",
}


def load(path):
    with open(path) as f:
        return json.load(f)


def render_finding_line(finding):
    loc = finding.get("resolved_location")
    if loc:
        where = f"`{loc['relPath']}`:{loc['line']}"
        if loc["relPath"] != finding["artifact"]:
            where += f" (via COPY expansion from `{finding['artifact']}`:{finding.get('line_number')})"
    else:
        where = f"`{finding['artifact']}`:{finding.get('line_number')}"
    return where


def build_report(annotated, changelog):
    lines = []
    summary = annotated.get("summary", {}) or {}
    transform = summary.get("transform", {}) if summary else {}
    metrics = transform.get("metrics", {}) if transform else {}
    counts = annotated.get("artifact_counts", {})

    lines.append("# AWS Transform for Mainframe (ATX) Codebase Issue Report")
    lines.append("")
    lines.append("## Run Summary")
    lines.append("")
    if metrics:
        lines.append(f"- Analyzer status: **{transform.get('status', 'unknown')}**")
        lines.append(f"- Artifacts processed: **{metrics.get('nbArtifacts', '?')}**")
        lines.append(f"- Artifacts ignored (unsupported type / fragments): **{metrics.get('nbIgnoredArtifacts', '?')}**")
        lines.append(f"- Artifacts succeeded: **{metrics.get('nbSuccessArtifacts', '?')}**")
        lines.append(f"- Artifacts with warnings: **{metrics.get('nbWarningArtifacts', '?')}**")
        lines.append(f"- Artifacts with errors: **{metrics.get('nbErrorArtifacts', '?')}**")
        lines.append(f"- Fatal artifacts: **{metrics.get('nbFatalArtifacts', '?')}**")
    else:
        lines.append(f"- Artifact status breakdown: {counts}")
    lines.append("")

    findings = annotated.get("findings", [])
    by_category = defaultdict(list)
    for f in findings:
        cat = f.get("classification", {}).get("category", "uncategorized")
        by_category[cat].append(f)

    lines.append("## Findings by Root Cause")
    lines.append("")
    lines.append("| Root cause category | Count | Auto-fixable | Needs manual review |")
    lines.append("|---|---|---|---|")
    fixed_categories = {c["category"] for c in changelog.get("fixed", [])}
    for cat, items in sorted(by_category.items(), key=lambda kv: -len(kv[1])):
        label = CATEGORY_LABELS.get(cat, cat)
        auto = "Yes" if cat in fixed_categories or cat in AUTO_FIX_CATEGORIES else "No"
        is_fp = any(i.get("classification", {}).get("is_false_positive") for i in items)
        manual = "No (benign/cascading)" if is_fp else ("No" if auto == "Yes" else "Yes")
        lines.append(f"| {label} | {len(items)} | {auto} | {manual} |")
    lines.append("")

    lines.append("## Fixes Applied")
    lines.append("")
    fixed = changelog.get("fixed", [])
    if fixed:
        lines.append(f"{len(fixed)} issue(s) were automatically fixed in the target zip.")
        lines.append("")
        lines.append("| File | Line | Category | Original Issue |")
        lines.append("|---|---|---|---|")
        for item in fixed:
            lines.append(f"| `{item['resolved_file']}` | {item['line']} | {CATEGORY_LABELS.get(item['category'], item['category'])} | {item['summary']} |")
    else:
        lines.append("No automated fixes were applied.")
    lines.append("")

    lines.append("## Benign / No-Action-Needed Notes")
    lines.append("")
    notes = changelog.get("unchanged_note", [])
    if notes:
        lines.append(
            f"{len(notes)} finding(s) were classified as false positives or benign analyzer "
            "notes and intentionally left unchanged:"
        )
        lines.append("")
        lines.append("| File | Line | Category | Why no action was taken |")
        lines.append("|---|---|---|---|")
        for item in notes:
            reason = (item.get("reason") or "").replace("\n", " ")
            lines.append(f"| `{item.get('resolved_file') or item['artifact']}` | {item.get('line')} | {CATEGORY_LABELS.get(item['category'], item['category'])} | {reason} |")
    else:
        lines.append("None.")
    lines.append("")

    lines.append("## Needs Manual Review")
    lines.append("")
    skipped = changelog.get("skipped", [])
    if skipped:
        lines.append(f"{len(skipped)} issue(s) could not be safely auto-fixed and require manual review:")
        lines.append("")
        lines.append("| File | Line | Category | Severity | Summary |")
        lines.append("|---|---|---|---|---|")
        for item in skipped:
            lines.append(
                f"| `{item.get('resolved_file') or item['artifact']}` | {item.get('line')} | "
                f"{CATEGORY_LABELS.get(item['category'], item['category'])} | {item.get('severity', '')} | {item.get('summary', '')} |"
            )
    else:
        lines.append("None.")
    lines.append("")

    lines.append("## Files Removed From Target Zip")
    lines.append("")
    removed = changelog.get("removed", [])
    if removed:
        lines.append(
            f"{len(removed)} file(s) still had unresolved errors with no safe automated fix and "
            "were removed from the target zip so they would not block downstream AWS Transform "
            "processing. Each removed file's original, untouched copy remains available in the "
            "source zip for manual remediation."
        )
        lines.append("")
        for item in removed:
            lines.append(f"- `{item['artifact']}` — {item['reason']}")
    else:
        lines.append("None — no files were removed.")
    lines.append("")

    lines.append("## Detailed Findings")
    lines.append("")
    lines.append(
        "Full detail for every finding, grouped by category. Each entry shows the resolved "
        "file/line (after COPY expansion, if applicable), the analyzer's summary, and the "
        "root-cause rationale."
    )
    lines.append("")
    for cat, items in sorted(by_category.items(), key=lambda kv: -len(kv[1])):
        lines.append(f"### {CATEGORY_LABELS.get(cat, cat)} ({len(items)})")
        lines.append("")
        for f in items:
            classification = f.get("classification", {})
            lines.append(f"- **{render_finding_line(f)}** — {f.get('summary')}")
            lines.append(f"  - Severity: {f.get('severity')}, Step: {f.get('step')}, ErrorID: {f.get('error_id') or 'n/a'}")
            lines.append(f"  - Rationale: {classification.get('rationale')}")
        lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--annotated", required=True, type=Path)
    parser.add_argument("--changelog", type=Path, help="Optional; omit if you only want the diagnostic findings without fix results")
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    annotated = load(args.annotated)
    changelog = load(args.changelog) if args.changelog else {"fixed": [], "skipped": [], "removed": [], "unchanged_note": []}

    report = build_report(annotated, changelog)
    args.out.write_text(report)
    print(f"Wrote report to {args.out} ({len(report.splitlines())} lines)")


if __name__ == "__main__":
    main()

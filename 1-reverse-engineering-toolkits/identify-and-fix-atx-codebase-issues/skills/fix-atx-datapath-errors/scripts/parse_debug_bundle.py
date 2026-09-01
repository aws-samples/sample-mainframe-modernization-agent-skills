#!/usr/bin/env python3
"""
parse_debug_bundle.py

Parses an AWS Transform for mainframe (ATX) "bre_transform_debug_*.zip" diagnostic bundle
and produces a normalized, machine- and human-readable findings report.

The bundle is a fixed structure produced by the Bluage/AWS Transform analyzer:

    <bundle>.zip
    ├── <timestamp>_transform.log        # raw analyzer log (verbose, not required for parsing)
    └── status/
        ├── status.json                  # run-level summary (counts, duration, status)
        ├── cbl/<PROGRAM>.cbl.json        # one file per COBOL program
        ├── cpy/<COPYBOOK>.cpy.json       # one file per copybook
        ├── bms/<MAP>.bms.json            # one file per BMS map
        ├── jcl/<JOB>.jcl.json            # one file per JCL member
        └── proc/<PROC>.proc.json         # one file per PROC member

Each per-artifact JSON file has the shape:

    {
      "name": "PROGRAM.cbl",
      "relPath": "cbl/PROGRAM.cbl",
      "nbLines": 12345,
      "language": "COBOL",
      "transform": {
        "status": "SUCCESS" | "WARNING" | "ERROR" | "IGNORED",
        "issues": [
          {
            "lineNumber": 8552,
            "errorID": "BAERR-4010-0000",
            "severity": "Fatal" | "Critical" | "Minor",
            "type": "Gapwalk dsl error" | "Parsing error" | "Other error" | "Unknown field",
            "summary": "...human readable...",
            "message": [...],
            "badLines": [{"lineNumber": "8552", "lineContent": "...", "isMainBadLine": true}, ...],
            "errorCause": ["java stack trace lines..."],
            "stepName": "parsing" | "dsl-generation" | "cfg-generation"
          }, ...
        ],
        "outputs": [...],
        "tags": [...]
      }
    }

This script does NOT hardcode any customer/program names. It walks whatever
files exist in the bundle.

Usage:
    python3 parse_debug_bundle.py --bundle bre_transform_debug_XXXX.zip --out findings.json
    python3 parse_debug_bundle.py --bundle bre_transform_debug_XXXX.zip --out findings.csv --format csv

Output (JSON) shape:
    {
      "summary": { ...run-level metrics from status.json... },
      "artifact_counts": {"SUCCESS": N, "WARNING": N, "ERROR": N, "IGNORED": N},
      "findings": [
        {
          "artifact": "cbl/PROGRAM.cbl",
          "artifact_status": "ERROR",
          "severity": "Critical",
          "type": "Gapwalk dsl error",
          "step": "dsl-generation",
          "error_id": "BAERR-4010-0000",
          "line_number": 8552,
          "summary": "...",
          "main_bad_line": {"lineNumber": "8552", "lineContent": "..."},
          "context_lines": [...],
          "error_cause": [...]
        }, ...
      ]
    }
"""
import argparse
import csv
import json
import sys
import zipfile
from pathlib import Path


def load_bundle(bundle_path: Path):
    """Return (status_json_dict, list_of_(relpath, artifact_dict))."""
    artifacts = []
    status_summary = None

    with zipfile.ZipFile(bundle_path, "r") as zf:
        names = zf.namelist()
        status_candidates = [n for n in names if n.endswith("status/status.json")]
        if status_candidates:
            with zf.open(status_candidates[0]) as f:
                status_summary = json.load(f)

        artifact_files = [
            n for n in names
            if n.endswith(".json")
            and "/status/" in ("/" + n)
            and not n.endswith("status/status.json")
        ]

        for n in artifact_files:
            try:
                with zf.open(n) as f:
                    data = json.load(f)
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                print(f"WARNING: could not parse {n}: {e}", file=sys.stderr)
                continue
            artifacts.append((n, data))

    return status_summary, artifacts


def normalize_findings(status_summary, artifacts):
    artifact_counts = {"SUCCESS": 0, "WARNING": 0, "ERROR": 0, "IGNORED": 0, "OTHER": 0}
    findings = []
    artifact_index = []

    for relname, data in artifacts:
        transform = data.get("transform", {})
        art_status = transform.get("status", "OTHER")
        artifact_counts[art_status] = artifact_counts.get(art_status, 0) + 1

        rel_path = data.get("relPath", relname)
        artifact_index.append({
            "relPath": rel_path,
            "name": data.get("name"),
            "language": data.get("language"),
            "nbLines": data.get("nbLines"),
            "status": art_status,
            "tags": transform.get("tags", []),
            "num_issues": len(transform.get("issues", [])),
        })

        for issue in transform.get("issues", []):
            bad_lines = issue.get("badLines", [])
            main_bad = next((b for b in bad_lines if b.get("isMainBadLine")), None)
            if main_bad is None and bad_lines:
                main_bad = bad_lines[-1]

            findings.append({
                "artifact": rel_path,
                "artifact_status": art_status,
                "severity": issue.get("severity"),
                "type": issue.get("type"),
                "step": issue.get("stepName"),
                "error_id": issue.get("errorID"),
                "line_number": issue.get("lineNumber"),
                "summary": issue.get("summary"),
                "main_bad_line": main_bad,
                "context_lines": bad_lines,
                "error_cause": issue.get("errorCause", []),
            })

    return {
        "summary": status_summary,
        "artifact_counts": artifact_counts,
        "artifact_index": sorted(artifact_index, key=lambda a: (-a["num_issues"], a["relPath"] or "")),
        "findings": findings,
    }


def write_json(result, out_path):
    with open(out_path, "w") as f:
        json.dump(result, f, indent=2)


def write_csv(result, out_path):
    fields = [
        "artifact", "artifact_status", "severity", "type", "step",
        "error_id", "line_number", "summary", "main_bad_line_content",
    ]
    with open(out_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for finding in result["findings"]:
            main_bad = finding.get("main_bad_line") or {}
            writer.writerow({
                "artifact": finding["artifact"],
                "artifact_status": finding["artifact_status"],
                "severity": finding["severity"],
                "type": finding["type"],
                "step": finding["step"],
                "error_id": finding["error_id"],
                "line_number": finding["line_number"],
                "summary": finding["summary"],
                "main_bad_line_content": (main_bad.get("lineContent") or "").strip(),
            })


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--bundle", required=True, type=Path, help="Path to bre_transform_debug_*.zip")
    parser.add_argument("--out", required=True, type=Path, help="Output file path")
    parser.add_argument("--format", choices=["json", "csv"], default="json")
    args = parser.parse_args()

    if not args.bundle.exists():
        print(f"ERROR: bundle not found: {args.bundle}", file=sys.stderr)
        sys.exit(1)

    status_summary, artifacts = load_bundle(args.bundle)
    if status_summary is None:
        print("WARNING: status/status.json not found in bundle; proceeding without run-level summary.", file=sys.stderr)
    if not artifacts:
        print("ERROR: no per-artifact status JSON files found under status/. Is this a valid bre_transform_debug bundle?", file=sys.stderr)
        sys.exit(1)

    result = normalize_findings(status_summary, artifacts)

    if args.format == "json":
        write_json(result, args.out)
    else:
        write_csv(result, args.out)

    total_issues = len(result["findings"])
    print(f"Parsed {len(artifacts)} artifacts.")
    print(f"Artifact status counts: {result['artifact_counts']}")
    print(f"Total issues extracted: {total_issues}")
    print(f"Wrote {args.format.upper()} output to {args.out}")


if __name__ == "__main__":
    main()

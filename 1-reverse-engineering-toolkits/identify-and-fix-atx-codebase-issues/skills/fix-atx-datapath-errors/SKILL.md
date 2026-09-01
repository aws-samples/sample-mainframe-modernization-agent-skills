---
name: fix-atx-datapath-errors
description: >
  Diagnoses and fixes AWS Transform for mainframe (ATX) "Discover data
  paths" extraction errors/warnings for mainframe codebases (COBOL, PL/I,
  and other supported source languages): parses the
  bre_transform_debug_*.zip diagnostic bundle, correlates findings against
  the original source zip, classifies root causes against an extensible
  pattern library, applies safe business-rule-neutral fixes, produces a
  fixed target zip plus a Markdown report, and captures new root-cause/fix
  patterns for reuse.
---

# Fix AWS Transform for Mainframe (ATX) Codebase Issues

## When to use

The AWS Transform job's "Discover data paths" step reports extraction
Errors/Warnings on COBOL/copybook/BMS/JCL artifacts, and you need to find
the root cause, fix what's safe to fix, remove what isn't, and report on
it.

## Required inputs (ask for both if missing)

Expected in the workspace's `input/` folder (see top-level `README.md`):

1. **`bre_transform_debug_*.zip`** — AWS Transform console: job →
   **Artifacts** tab → **`1` → `artifact-slicing`** (numbering may vary).
   Download as-is, do not re-zip or rename internal paths.
2. **The original source zip** submitted to the AWS Transform job (same
   COBOL/copybook/BMS/JCL/PROC tree). Required for full context and to
   write the fixed target zip — do not proceed with only the debug
   bundle.

## Workflow

Scripts are in `scripts/` (Python 3 stdlib only), run from the workspace
root. Write outputs to `output/`. Run in order:

```bash
SKILL=skills/fix-atx-datapath-errors

# 1. Parse the debug bundle
python3 $SKILL/scripts/parse_debug_bundle.py \
  --bundle input/bre_transform_debug_*.zip --out output/findings.json

# 2. Correlate against source (resolves COPY-expanded line numbers to real
#    file/line, then classifies each finding via an extensible pattern
#    library — see references/error_taxonomy.md)
python3 $SKILL/scripts/correlate_with_source.py --findings output/findings.json \
  --source-zip input/full_source.zip --out output/annotated_findings.json

# 3. Apply safe, mechanical-only fixes; write a new target zip
python3 $SKILL/scripts/apply_fixes.py --annotated output/annotated_findings.json \
  --source-zip input/full_source.zip --out-zip output/target_fixed.zip \
  --changelog output/changelog.json --remove-unfixable

# 4. Generate the report
python3 $SKILL/scripts/generate_report.py --annotated output/annotated_findings.json \
  --changelog output/changelog.json --out output/report.md

# 5. After any manual/LLM triage, capture what was learned for reuse
python3 $SKILL/scripts/capture_learnings.py --annotated output/annotated_findings.json \
  --changelog output/changelog.json --list --skeleton-out output/resolutions.skeleton.json
#   ...fill in output/resolutions.json from the skeleton, then:
python3 $SKILL/scripts/capture_learnings.py --annotated output/annotated_findings.json \
  --changelog output/changelog.json --resolutions output/resolutions.json \
  --learnings-log $SKILL/references/learnings.jsonl --out output/learnings_summary.md
```

Deliverables: `output/report.md` + `output/target_fixed.zip` (+
`output/changelog.json` for machine-readable detail). Step 5 is optional
but should be run before closing out an engagement whenever manual triage
happened.

## Read before extending or fixing by hand

`references/error_taxonomy.md` — worked examples of known patterns, the
COPY-expansion line-number gotcha, and how to add new pattern matchers.
Read it before writing a new matcher or hand-editing a finding.

## Guardrails

- AWS Transform line numbers refer to the COPY-expanded source, not the
  raw file — never edit at the raw line number (step 2 resolves this).
- Never "fix" a cascading false positive (e.g. a label that already
  exists, or a note that says "no functional impact"). Fix the real
  upstream issue instead.
- Never guess at business logic. Automated fixes are pure reformats only
  (moving existing characters); anything requiring judgment goes to
  manual review.
- Prefer removing an unfixable file over a risky guess.
- Do not embed customer source, program names, or business data in this
  skill's own files (including `references/learnings.jsonl` — describe
  root causes/fixes in plain, non-identifying language).
- Root causes are open-ended — a large "needs manual review" count is
  normal, not a bug. Don't force-fit findings into existing categories.
- Promoting a learning into `PATTERN_LIBRARY`/`AUTO_FIX_CATEGORIES` is a
  deliberate, reviewed code change, never automatic — and never for a fix
  that changed business logic.

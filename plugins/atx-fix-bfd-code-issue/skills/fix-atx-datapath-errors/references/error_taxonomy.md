# AWS Transform for Mainframe (ATX) Error Pattern Library — Reference

AWS Transform for mainframe's diagnostic bundle can surface an open-ended variety of
parser/DSL/CFG errors depending on COBOL dialect, vendor extensions, and
transcription history. **There is no fixed, closed list of root causes.**
This doc records the patterns currently encoded in
`correlate_with_source.py`'s `PATTERN_LIBRARY` as a starting point, not an
exhaustive taxonomy. Unmatched findings (`needs-manual-classification`)
are expected and normal — not a gap.

## Line numbers may not belong to the file you think

AWS Transform reports `lineNumber` against the **preprocessed** (COPY-
expanded) source. A `lineNumber` beyond the entry file's own `nbLines`
usually points inside an included copybook. `correlate_with_source.py`
resolves this automatically by expanding `COPY` statements and mapping
back to the real file/line — never edit at the raw reported line without
this resolution.

## Two axes to classify any finding

1. **Genuine defect vs. cascading symptom** — one real parse failure can
   corrupt the parser's label/field tables for everything after it in the
   same file, throwing spurious secondary errors. Check whether the
   flagged label/field actually exists before "fixing" it.
2. **Mechanically fixable vs. needs judgment** — pure reformatting
   (moving existing characters, restoring an indicator char) is safe to
   automate. Anything requiring a guessed value, renamed identifier, or
   changed control flow is not — manual review or removal instead.

## Known patterns

| Pattern | Typical cause | Fix |
|---|---|---|
| Non-printable/non-ASCII byte | EBCDIC↔ASCII conversion, binary-mode transfer, terminal copy/paste | Manual — correct replacement char can't be safely inferred |
| Column-72 identification-area overflow | Line's real content (e.g. `VALUE ZEROES.`) extends past col 72 into the ignored id/sequence area (cols 73-80), truncating the statement | **Auto**: move overflow onto a continuation line (`-` in col 7) |
| Code starting at column 1, not Area A | Copybook/program re-typed or exported without the fixed-format seq area (cols 1-6) / indicator (col 7); text starts flush at col 1 | **Auto**: shift line right to col 8, unless that would overflow col 72 (then manual) |
| General column/indicator alignment violation | Tab-expansion drift, partial re-indentation, junk in sequence area — analyzer message itself mentions column/indicator/sequence | Manual — multiple valid realignments possible |
| Cascading "Unknown label"/"Unknown field" | Earlier real failure (unsupported EXEC CICS/SQL, or a col-72 overflow in an included copybook) corrupted label/field resolution | No fix at flagged location — fix the earlier real defect, re-run |
| BMS macro continuation broken | Re-sequencing/manual edit disturbed the macro continuation marker | Manual — verify visually against rendered map layout |
| Benign CFG/aliasing note ("no functional impact") | Analyzer approximates a built-in SQL function's aliasing | No fix — informational only |

See `PATTERN_LIBRARY` in `scripts/correlate_with_source.py` for the exact
matcher implementations and rationale text surfaced per finding.

## Extending the library

1. Gather evidence via the existing COPY-expansion + context resolution —
   don't guess.
2. Classify using the two axes above.
3. Add a `match_*` function to `PATTERN_LIBRARY` (structural evidence
   only, never assumed business intent); register it in the list.
4. If mechanically fixable, add a fixer + entry in `AUTO_FIX_CATEGORIES`/
   `FIXERS` in `apply_fixes.py`.
5. Add a row to the table above.

## Decision tree

```
1. Resolve real (file, line) via COPY expansion.
2. Try each PATTERN_LIBRARY matcher in order; use the first match.
3. Cascading/benign match -> don't edit the flagged location; fix the
   real upstream issue if identifiable, or just note it.
4. Genuine + mechanically fixable match -> apply the fixer, log it.
5. Genuine-but-judgment-required, or no match at all -> manual/LLM
   review using the gathered evidence. If unresolvable in scope,
   candidate for removal from the target zip (document why).
```

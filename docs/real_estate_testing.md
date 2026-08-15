# Real-estate extraction testing

This procedure tests the EDINET rental/investment real-estate extraction without
initializing Firebase or writing company data.

## Test layers

1. `pinned` re-runs the parser against the exact EDINET document IDs in
   `real_estate_baseline.json`. All five records must be `matched` within 0.01
   oku. A value change is a regression.
2. `latest` searches for the latest annual report. If the document ID is still
   the baseline ID, values must match. A newer document is marked
   `review_required` and must not update the baseline automatically.
3. Unit tests cover comparison rules, download-contract failures, output files,
   and the fixed regression set.

Holdout records without a reviewed baseline are observational. A difference
from the legacy extractor is not a regression and is not evidence that either
value is correct. Missing values are reported as `unverified_no_values` rather
than failing the workflow.

The initial regression set is `6396, 9635, 6042, 3123, 9366`.

Two fixed observational sets broaden coverage without changing the reviewed
baseline:

- `holdout-30`: the first 30-company cross-industry set.
- `holdout-b-40`: a disjoint 40-company set covering railways, property,
  retail/hospitality, warehousing, manufacturing, utilities, and telecoms.

The holdout sets must remain disjoint from the regression set and from each
other. Replace delisted codes with currently listed companies before treating
`document_not_found` as an extractor failure.

## Commands

Run unit tests:

```bash
python -m unittest test_real_estate_diagnostics.py
```

Run the pinned regression:

```bash
python real_estate_diagnostics.py \
  --test-set regression-5 \
  --mode pinned \
  --baseline real_estate_baseline.json \
  --output-dir real_estate_diagnostics/pinned \
  --fail-on-regression
```

Run the latest-document monitor:

```bash
python real_estate_diagnostics.py \
  --test-set regression-5 \
  --mode latest \
  --days-back 730 \
  --baseline real_estate_baseline.json \
  --output-dir real_estate_diagnostics/latest \
  --write-candidate-baseline real_estate_diagnostics/candidate_baseline.json \
  --fail-on-regression
```

`EDINET_API_KEY` is required. The GitHub Actions workflow runs both commands and
uploads JSON and Markdown diagnostics. It never writes to Firestore.

Pushes to `real-estate-regression`, `real-estate-holdout`, and
`real-estate-holdout-b` run `regression-5`, `holdout-30`, and `holdout-b-40`
respectively.

## Baseline update rule

Do not replace the baseline just because the latest document changed. Confirm
the period, consolidated/nonconsolidated scope, unit, selected book-value row,
selected market-value row, and hidden-gain calculation manually. Only then
copy the reviewed values and document metadata into the tracked baseline.

Every parser bug should add a small table fixture or another reviewed holdout
case before the extraction logic is changed.

## Publication gate

The batch publishes real-estate book and market values only when the structural
extractor returns `verified`. Verification requires an explicit unit, matching
book and market rows or columns, and a current-period candidate without an
unresolved competing table or excluded reporting entity. `partial`,
`quarantined`, and `not_found` candidates publish zero values and retain their
status and reasons in `不動産_検証状態` and `不動産_検証理由`.

The legacy extractor remains in diagnostics for comparison only. Its value is
not used as ground truth outside the five manually reviewed regression records.

## Outcome classifications

`不動産_取得分類` records why a value was or was not published:

- `extracted_structural`: passed the structural publication gate.
- `current_period_table_missing`: only a prior-period candidate was reliable.
- `competing_tables`: multiple plausible tables disagree.
- `separate_values_not_safely_pairable`: book and market values were found but
  did not meet the strict same-section pairing rules.
- `book_value_only` / `market_value_only`: only one side was found.
- `unit_not_explicit`: values were found without a reliable unit.
- `unsupported_table_structure`: relevant tables were found but not parsed.
- `disclosure_omitted_or_not_applicable`: an omission phrase was found near the
  real-estate disclosure.
- `text_only_or_unsupported_disclosure`: real-estate text was found without a
  usable table.
- `no_relevant_disclosure_detected`: no target disclosure marker was found.

These are parser outcomes, not manual correctness labels. Only the tracked
regression records have been reviewed as ground truth.

## Observed blind-set result (2026-08-16)

Before the second blind-set analysis, the structural extractor safely
published 18 of 40 records. Generic support was then added for:

- current-period book/fair-value column pairs in horizontal IFRS tables;
- book and market tables separated by up to four small tables, only when file,
  explicit unit, and period end all match;
- consecutive annual tables whose prior closing book value equals the next
  opening book value;
- IFRS investment property explicitly carried under a fair-value model, where
  carrying value and fair value are equal.

The final currently-listed `holdout-b-40` run published 26 of 40 records. The
remaining 14 were one nearby omission, one unsupported table structure, and 12
records with no target disclosure marker. They remain unpublished rather than
being filled from weak evidence.

Final verification:

- all 5 reviewed regression records matched both pinned and latest runs;
- all 30 first-holdout records retained their prior status and values;
- all 39 unchanged records in the second holdout reproduced exactly after its
  delisted code was replaced;
- 204 local unit tests passed.

At this set size, an EDINET latest-document run takes roughly ten minutes.
Future 100-company observational sets should be split into multiple workflow
branches so one slow scan does not delay all diagnostics.

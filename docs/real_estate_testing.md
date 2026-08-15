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

The initial regression set is `6396, 9635, 6042, 3123, 9366`.

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

## Baseline update rule

Do not replace the baseline just because the latest document changed. Confirm
the period, consolidated/nonconsolidated scope, unit, selected book-value row,
selected market-value row, and hidden-gain calculation manually. Only then
copy the reviewed values and document metadata into the tracked baseline.

Every parser bug should add a small table fixture or another reviewed holdout
case before the extraction logic is changed.

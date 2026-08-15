import tempfile
import unittest
from pathlib import Path

from real_estate_diagnostics import (
    build_candidate_baseline,
    compare_with_baseline,
    normalize_extraction_result,
    summarize_records,
    write_outputs,
)
from real_estate_test_sets import (
    REAL_ESTATE_REGRESSION_5,
    get_real_estate_test_set_codes,
)


class RealEstateDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.expected = {
            "doc_id": "S100TEST",
            "book_value_oku": 100.0,
            "market_value_oku": 250.0,
            "hidden_gain_oku": 150.0,
        }
        self.record = {
            "code": "6396",
            "doc_id": "S100TEST",
            "mode": "pinned",
            "period_end": "2025-03-31",
            "submitted_at": "",
            "document_description": "Annual report",
            "filer_name": "Example",
            "extraction_status": "extracted",
            "book_value_oku": 100.0,
            "market_value_oku": 250.0,
            "hidden_gain_oku": 150.0,
            "comparison_status": "matched",
            "comparison": {},
        }

    def test_regression_set_is_fixed(self):
        self.assertEqual(
            REAL_ESTATE_REGRESSION_5,
            ("6396", "9635", "6042", "3123", "9366"),
        )
        self.assertEqual(
            get_real_estate_test_set_codes("regression-5"),
            list(REAL_ESTATE_REGRESSION_5),
        )

    def test_same_document_and_values_match(self):
        status, details = compare_with_baseline(
            self.record, self.expected, "pinned", 0.01
        )
        self.assertEqual(status, "matched")
        self.assertEqual(details["differences_oku"]["book_value_oku"], 0)

    def test_changed_latest_document_requires_review(self):
        changed = dict(self.record, doc_id="S100NEW")
        status, details = compare_with_baseline(
            changed, self.expected, "latest", 0.01
        )
        self.assertEqual(status, "review_required")
        self.assertEqual(details["reason"], "latest_document_changed")

    def test_value_change_is_a_regression(self):
        changed = dict(self.record, market_value_oku=250.02)
        status, details = compare_with_baseline(
            changed, self.expected, "pinned", 0.01
        )
        self.assertEqual(status, "regression")
        self.assertEqual(details["reason"], "value_changed")

    def test_failed_download_contract_is_detected(self):
        normalized = normalize_extraction_result({"Book": 0, "Market": 0})
        self.assertEqual(normalized["extraction_status"], "extraction_failed")

    def test_extraction_failure_is_a_regression_without_baseline(self):
        failed = dict(self.record, extraction_status="document_not_found")
        status, details = compare_with_baseline(failed, None, "latest", 0.01)
        self.assertEqual(status, "regression")
        self.assertEqual(details["reason"], "document_not_found")

    def test_summary_and_candidate_baseline(self):
        summary = summarize_records([self.record])
        self.assertEqual(summary["comparison_statuses"], {"matched": 1})
        baseline = build_candidate_baseline([self.record])
        self.assertEqual(
            baseline["records"]["6396"]["market_value_oku"], 250.0
        )

    def test_outputs_are_reproducible(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            candidate = Path(temp_dir) / "candidate.json"
            write_outputs([self.record], temp_dir, "pinned", candidate)
            self.assertTrue(
                (Path(temp_dir) / "real_estate_pinned_6396.json").exists()
            )
            self.assertTrue(
                (Path(temp_dir) / "real_estate_pinned_summary.md").exists()
            )
            self.assertTrue(candidate.exists())


if __name__ == "__main__":
    unittest.main()

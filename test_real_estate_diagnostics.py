import tempfile
import unittest
from pathlib import Path

from bs4 import BeautifulSoup

from real_estate_diagnostics import (
    build_candidate_baseline,
    compare_with_baseline,
    load_baseline,
    normalize_extraction_result,
    summarize_records,
    write_outputs,
)
from real_estate_test_sets import (
    REAL_ESTATE_HOLDOUT_30,
    REAL_ESTATE_HOLDOUT_B_40,
    REAL_ESTATE_REGRESSION_5,
    get_real_estate_test_set_codes,
)
from real_estate_extractor import (
    classify_real_estate_outcome,
    expand_complementary_candidates,
    extract_table_candidate,
    find_nearby_omission_markers,
    publishable_real_estate_values,
    select_real_estate_candidate,
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
            "real_estate_quality": "verified",
            "real_estate_outcome": "extracted_structural",
            "real_estate_reasons": [],
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
        self.assertEqual(len(REAL_ESTATE_HOLDOUT_30), 30)
        self.assertFalse(set(REAL_ESTATE_REGRESSION_5) & set(REAL_ESTATE_HOLDOUT_30))
        self.assertEqual(len(REAL_ESTATE_HOLDOUT_B_40), 40)
        previous_codes = set(REAL_ESTATE_REGRESSION_5) | set(REAL_ESTATE_HOLDOUT_30)
        self.assertFalse(previous_codes & set(REAL_ESTATE_HOLDOUT_B_40))
        self.assertEqual(
            get_real_estate_test_set_codes("holdout-b-40"),
            list(REAL_ESTATE_HOLDOUT_B_40),
        )

    def test_tracked_baseline_covers_the_regression_set(self):
        baseline = load_baseline("real_estate_baseline.json")
        self.assertEqual(
            set(baseline["records"]), set(REAL_ESTATE_REGRESSION_5)
        )
        for record in baseline["records"].values():
            self.assertTrue(record["doc_id"])
            self.assertGreater(record["book_value_oku"], 0)
            self.assertGreater(record["market_value_oku"], 0)
            self.assertAlmostEqual(
                record["hidden_gain_oku"],
                record["market_value_oku"] - record["book_value_oku"],
                places=2,
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

    def test_missing_values_are_neutral_without_baseline(self):
        failed = dict(self.record, extraction_status="document_not_found")
        status, details = compare_with_baseline(failed, None, "latest", 0.01)
        self.assertEqual(status, "source_unavailable")
        self.assertEqual(details, {})

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

    def test_structural_extractor_chooses_current_period(self):
        html = """
        <p>（単位：千円）</p>
        <table>
          <tr><th></th><th>前連結会計年度</th><th>当連結会計年度</th></tr>
          <tr><th>連結貸借対照表計上額 期首残高</th><td>100,000</td><td>110,000</td></tr>
          <tr><th>期中増減額</th><td>10,000</td><td>10,000</td></tr>
          <tr><th>期末残高</th><td>110,000</td><td>120,000</td></tr>
          <tr><th>期末時価</th><td>200,000</td><td>250,000</td></tr>
        </table>
        """
        soup = BeautifulSoup(html, "lxml")
        candidate = extract_table_candidate(
            soup.table,
            "（単位：千円）当該賃貸等不動産の連結貸借対照表計上額及び時価",
        )
        self.assertEqual(candidate["quality_status"], "verified")
        self.assertEqual(candidate["book_value_yen"], 120000000)
        self.assertEqual(candidate["market_value_yen"], 250000000)

    def test_structural_extractor_rejects_profit_table(self):
        html = """
        <table>
          <tr><th></th><th>当連結会計年度</th></tr>
          <tr><th>賃貸収益</th><td>500</td></tr>
          <tr><th>賃貸費用</th><td>200</td></tr>
        </table>
        """
        soup = BeautifulSoup(html, "lxml")
        candidate = extract_table_candidate(
            soup.table, "（単位：百万円）賃貸等不動産に関する損益"
        )
        selection = select_real_estate_candidate([candidate])
        self.assertTrue(candidate["loss_table"])
        self.assertEqual(selection["quality_status"], "not_found")

    def test_structural_extractor_quarantines_unknown_unit(self):
        html = """
        <table>
          <tr><th></th><th>当事業年度</th></tr>
          <tr><th>貸借対照表計上額 期末残高</th><td>120</td></tr>
          <tr><th>期末時価</th><td>250</td></tr>
        </table>
        """
        soup = BeautifulSoup(html, "lxml")
        candidate = extract_table_candidate(soup.table, "賃貸等不動産")
        self.assertEqual(candidate["quality_status"], "quarantined")
        self.assertEqual(candidate["book_value_yen"], 0)

    def test_structural_extractor_sums_horizontal_categories(self):
        html = """
        <table>
          <tr>
            <th>区分</th><th>当連結会計年度期首残高</th>
            <th>当連結会計年度増減額</th><th>当連結会計年度期末残高</th>
            <th>連結決算日における時価</th>
          </tr>
          <tr><th>賃貸等不動産</th><td>100</td><td>10</td><td>110</td><td>200</td></tr>
          <tr><th>賃貸等不動産として使用される部分を含む不動産</th><td>300</td><td>20</td><td>320</td><td>500</td></tr>
        </table>
        """
        soup = BeautifulSoup(html, "lxml")
        candidate = extract_table_candidate(
            soup.table,
            "（単位：百万円）2026年3月期の賃貸等不動産",
        )
        selection = select_real_estate_candidate([candidate])
        self.assertEqual(selection["quality_status"], "verified")
        self.assertEqual(selection["book_value_yen"], 430000000)
        self.assertEqual(selection["market_value_yen"], 700000000)
        self.assertEqual(
            publishable_real_estate_values(selection),
            (430000000, 700000000),
        )

    def test_previous_period_horizontal_table_is_not_promoted_by_context_date(self):
        html = """
        <table>
          <tr>
            <th>区分</th><th>前連結会計年度期中増減額</th>
            <th>前連結会計年度期末残高</th><th>前連結会計年度期末の時価</th>
          </tr>
          <tr><th>賃貸等不動産</th><td>10</td><td>110</td><td>200</td></tr>
        </table>
        """
        soup = BeautifulSoup(html, "lxml")
        candidate = extract_table_candidate(
            soup.table,
            "（単位：百万円）2026年3月期の賃貸等不動産",
        )
        selection = select_real_estate_candidate([candidate])
        self.assertEqual(selection["quality_status"], "partial")
        self.assertIn("current_period_not_explicit", selection["quality_reasons"])
        self.assertEqual(publishable_real_estate_values(selection), (0, 0))

    def test_adjacent_current_period_book_and_market_tables_are_combined(self):
        html = """
        <div>
          <table>
            <tr><th></th><th>前連結会計年度末（百万円）</th><th>当連結会計年度末（百万円）</th></tr>
            <tr><th>帳簿価額</th><td>34,391</td><td>67,231</td></tr>
          </table>
          <table>
            <tr><th></th><th>前連結会計年度末（百万円）</th><th>当連結会計年度末（百万円）</th></tr>
            <tr><th>公正価値</th><td>45,282</td><td>79,875</td></tr>
          </table>
        </div>
        """
        soup = BeautifulSoup(html, "lxml")
        candidates = [
            extract_table_candidate(
                table,
                "13. 投資不動産（単位：百万円）",
                file_name="annual.htm",
                table_index=index,
            )
            for index, table in enumerate(soup.find_all("table"), start=23)
        ]
        expanded = expand_complementary_candidates(candidates)
        selection = select_real_estate_candidate(expanded)
        self.assertEqual(len(expanded), 3)
        self.assertEqual(selection["quality_status"], "verified")
        self.assertEqual(selection["book_value_yen"], 67231000000)
        self.assertEqual(selection["market_value_yen"], 79875000000)
        self.assertEqual(
            classify_real_estate_outcome(expanded, selection)["classification"],
            "extracted_structural",
        )

    def test_no_candidate_outcomes_are_classified_by_scan_evidence(self):
        selection = select_real_estate_candidate([])
        no_disclosure = classify_real_estate_outcome(
            [], selection, {"files_with_real_estate_markers": 0}
        )
        omitted = classify_real_estate_outcome(
            [],
            selection,
            {
                "files_with_real_estate_markers": 1,
                "omission_markers": ["記載を省略"],
            },
        )
        text_only = classify_real_estate_outcome(
            [],
            selection,
            {
                "files_with_real_estate_markers": 1,
                "omission_markers": [],
            },
        )
        self.assertEqual(
            no_disclosure["classification"],
            "no_relevant_disclosure_detected",
        )
        self.assertEqual(
            omitted["classification"],
            "disclosure_omitted_or_not_applicable",
        )
        self.assertEqual(
            text_only["classification"],
            "text_only_or_unsupported_disclosure",
        )

    def test_omission_marker_must_be_near_real_estate_disclosure(self):
        distant = "記載を省略" + ("別の注記" * 300) + "投資不動産"
        nearby = "投資不動産については重要性が乏しいため記載を省略"
        self.assertEqual(find_nearby_omission_markers(distant), [])
        self.assertEqual(
            find_nearby_omission_markers(nearby),
            ["記載を省略", "重要性が乏しい"],
        )


if __name__ == "__main__":
    unittest.main()

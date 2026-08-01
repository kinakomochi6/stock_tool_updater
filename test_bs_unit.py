import unittest

from bs_diagnostics_report import summarize_diagnostics
from bs_test_sets import BS_TEST_SETS, EXPANSION_60, MARKET_100, REGRESSION_40
from firebase_master_test import (
    DISPLAY_ORDER,
    TAG_MAPPING,
    apply_mapped_tag,
    apply_summary_only_fallbacks,
    parse_codes_arg,
    reconcile_receivable_presentation,
    validate_tag_mapping,
)


class MappingTests(unittest.TestCase):
    def test_director_bonus_is_separate_from_employee_bonus(self):
        summary = {key: 0 for key in DISPLAY_ORDER}
        apply_mapped_tag(summary, "ProvisionForBonuses", 1_739_000_000)
        apply_mapped_tag(summary, "ProvisionForDirectorsBonuses", 742_000_000)

        self.assertEqual(summary["流負_賞与引当金"], 1_739_000_000)
        self.assertEqual(summary["流負_役員賞与引当金"], 742_000_000)

    def test_bad_debts_and_allowance_are_both_preserved(self):
        summary = {key: 0 for key in DISPLAY_ORDER}
        apply_mapped_tag(summary, "BadDebts", 405_000_000)
        apply_mapped_tag(summary, "AllowanceForDoubtfulAccountsIOAByGroup", -405_000_000)

        self.assertEqual(summary["投資_破産更生債権等"], 405_000_000)
        self.assertEqual(summary["投資_貸倒引当金"], -405_000_000)

    def test_mapping_targets_are_displayable(self):
        validate_tag_mapping()
        self.assertIn(TAG_MAPPING["ProvisionForDirectorsBonuses"], DISPLAY_ORDER)
        self.assertIn(TAG_MAPPING["BadDebts"], DISPLAY_ORDER)

    def test_clearing_liability_components_are_independent(self):
        summary = {key: 0 for key in DISPLAY_ORDER}
        values = {
            "ClearingBusinessFinancialLiabilitiesCLIFRS": 63_401_208_000_000,
            "DepositsFromClearingParticipantsCLIFRS": 7_716_198_000_000,
            "TradingParticipantSecurityMoneyCLIFRS": 10_827_000_000,
            "LegalGuaranteeFundsCLIFRS": 549_000_000,
        }
        for tag, value in values.items():
            apply_mapped_tag(summary, tag, value)

        total = sum(value for key, value in summary.items() if key.startswith("流負_"))
        self.assertEqual(total, sum(values.values()))

    def test_combined_construction_receivable_removes_contract_asset_detail(self):
        summary = {key: 0 for key in DISPLAY_ORDER}
        summary["流動_受取手形・売掛金(合算)"] = 203_890_000_000
        summary["流動_契約資産"] = 147_727_000_000
        totals = {"CurrentAssets": 3_907_449_000_000}
        raw_tags = {"NotesReceivableAccountsReceivableFromCompletedConstructionContractsAndOtherCNS": 203_890_000_000}

        result = reconcile_receivable_presentation(summary, totals, raw_tags)

        self.assertEqual(result["selected"], "combined")
        self.assertTrue(result["combined_includes_contract_assets"])
        self.assertEqual(summary["流動_契約資産"], 0)

    def test_net_assets_total_is_preserved_when_details_are_missing(self):
        summary = {key: 0 for key in DISPLAY_ORDER}
        totals = {"NetAssets": 2_027_663_000_000}

        fallbacks = apply_summary_only_fallbacks(summary, totals)

        self.assertEqual(summary["純資_内訳未分類"], totals["NetAssets"])
        self.assertEqual(fallbacks[0]["section"], "NetAssets")


class TestSetTests(unittest.TestCase):
    def test_curated_set_sizes_and_overlap(self):
        self.assertEqual(len(REGRESSION_40), 40)
        self.assertEqual(len(EXPANSION_60), 60)
        self.assertFalse(set(REGRESSION_40) & set(EXPANSION_60))
        self.assertEqual(len(MARKET_100), 100)
        self.assertEqual(BS_TEST_SETS["market-100"], MARKET_100)

    def test_empty_explicit_codes_can_be_combined_with_test_set(self):
        requested = sorted(set(parse_codes_arg("") or []) | set(EXPANSION_60))

        self.assertEqual(requested, sorted(EXPANSION_60))


class DiagnosticsReportTests(unittest.TestCase):
    def test_residuals_use_absolute_magnitude_for_ranking(self):
        records = [
            {
                "_path": "debug_bs_1111.json",
                "code": "1111",
                "status": "ok",
                "doc_type": "J-GAAP",
                "selected_context": "CurrentYearInstant",
                "warnings": [],
                "other_gap_delta_oku": {"流動_その他流動資産": -1400.0},
            },
            {
                "_path": "debug_bs_2222.json",
                "code": "2222",
                "status": "ok",
                "doc_type": "IFRS",
                "selected_context": "CurrentYearInstant_NonConsolidatedMember",
                "warnings": ["warning"],
                "other_gap_delta_oku": {"流負_その他流動負債": 10.0},
            },
        ]

        summary = summarize_diagnostics(records)

        self.assertEqual(summary["max_abs_residual_oku"], 1400.0)
        self.assertEqual(summary["rows"][0]["code"], "1111")
        self.assertEqual(summary["threshold_counts"]["over_1000_oku"], 1)
        self.assertEqual(summary["warning_count"], 1)


if __name__ == "__main__":
    unittest.main()

import io
import unittest
import zipfile
from unittest.mock import Mock, patch

from bs_diagnostics_report import summarize_diagnostics
from bs_test_sets import (
    BREADTH_100,
    BS_TEST_SETS,
    EXPANSION_60,
    MARKET_100,
    MARKET_200,
    MARKET_300,
    MARKET_500,
    REGRESSION_40,
    STRESS_100,
    WAVE_A_100,
    WAVE_B_100,
)
from firebase_master_test import (
    DISPLAY_ORDER,
    EdinetSearcher,
    TAG_MAPPING,
    BsAnalysisError,
    apply_mapped_tag,
    apply_summary_only_fallbacks,
    download_edinet_xbrl_package,
    empty_financial_data,
    parse_codes_arg,
    reconcile_bank_presentation,
    reconcile_insurance_presentation,
    reconcile_parent_component_overlaps,
    reconcile_receivable_presentation,
    reconcile_optional_duplicate_categories,
    reconcile_skipped_section_summaries,
    serialize_reconciliation_adjustment,
    should_skip_item_tag,
    validate_tag_mapping,
)


class EdinetDownloadTests(unittest.TestCase):
    @staticmethod
    def make_zip_bytes():
        payload = io.BytesIO()
        with zipfile.ZipFile(payload, "w") as archive:
            archive.writestr("XBRL/PublicDoc/test.xbrl", "<xbrl />")
        return payload.getvalue()

    @patch("firebase_master_test.time.sleep")
    @patch("firebase_master_test.requests.get")
    def test_non_zip_success_response_is_retried(self, mock_get, mock_sleep):
        mock_get.side_effect = [
            Mock(status_code=200, content=b'{"message":"busy"}', headers={"Content-Type": "application/json"}),
            Mock(status_code=200, content=self.make_zip_bytes(), headers={"Content-Type": "application/octet-stream"}),
        ]

        package = download_edinet_xbrl_package("S100TEST", attempts=2)

        self.assertTrue(zipfile.is_zipfile(package))
        self.assertEqual(mock_get.call_count, 2)
        mock_sleep.assert_called_once_with(1)

    @patch("firebase_master_test.time.sleep")
    @patch("firebase_master_test.requests.get")
    def test_repeated_non_zip_responses_raise_download_error(self, mock_get, mock_sleep):
        mock_get.return_value = Mock(
            status_code=200,
            content=b"temporarily unavailable",
            headers={"Content-Type": "text/plain"},
        )

        with self.assertRaises(BsAnalysisError) as caught:
            download_edinet_xbrl_package("S100TEST", attempts=3)

        self.assertEqual(caught.exception.stage, "download")
        self.assertEqual(len(caught.exception.details["attempts"]), 3)
        self.assertEqual(
            caught.exception.details["attempts"][0]["error"],
            "response_is_not_zip",
        )
        self.assertEqual([call.args[0] for call in mock_sleep.call_args_list], [1, 2])


class EdinetSearcherTests(unittest.TestCase):
    @patch("firebase_master_test.time.sleep")
    @patch("firebase_master_test.requests.get")
    def test_bs_only_scan_stops_without_waiting_for_annual_report(self, mock_get, _mock_sleep):
        response = Mock(status_code=200)
        response.json.return_value = {
            "results": [{
                "docTypeCode": "140",
                "secCode": "72030",
                "xbrlFlag": "1",
                "filerName": "Test Company",
                "docID": "S100TEST",
                "docDescription": "Quarterly report",
            }],
        }
        mock_get.return_value = response

        searcher = EdinetSearcher()
        searcher.fetch_list(["7203"], days_back=10, require_real_estate=False)

        self.assertEqual(mock_get.call_count, 1)
        self.assertEqual(len(searcher.df_docs), 1)


class MappingTests(unittest.TestCase):
    def test_third_wave_banking_extensions_preserve_independent_assets(self):
        summary = {key: 0 for key in DISPLAY_ORDER}
        apply_mapped_tag(summary, "SecuritiesForBankingBusinessCA", 1_097_389_000_000)
        apply_mapped_tag(summary, "MoneyHeldInTrustCA", 75_228_000_000)
        apply_mapped_tag(summary, "ReceivablesUnderSecuritiesBorrowingTransactionsAssetsBNK", 570_538_000_000)
        apply_mapped_tag(summary, "CallLoansAndBillsBoughtAssetsBNK", 55_000_000_000)
        apply_mapped_tag(summary, "TangibleLeasedAssets", 40_123_000_000)

        self.assertEqual(summary["流動_銀行業有価証券"], 1_097_389_000_000)
        self.assertEqual(summary["流動_銀行金銭の信託"], 75_228_000_000)
        self.assertEqual(summary["投資_金融債権"], 625_538_000_000)
        self.assertEqual(summary["有形_賃貸用資産"], 40_123_000_000)

    def test_third_wave_ifrs_investment_and_hybrid_capital_extensions(self):
        summary = {key: 0 for key in DISPLAY_ORDER}
        apply_mapped_tag(summary, "InvestmentsInSubsidiariesMeasuredAtFairValueNCAIFRS", 43_037_000_000)
        apply_mapped_tag(summary, "InvestmentPortfolioNCAIFRS", 14_673_000_000)
        apply_mapped_tag(summary, "LoansToSubsidiariesMeasuredAtFairValueNCAIFRS", 390_000_000)
        apply_mapped_tag(summary, "LoansFromSubsidiariesMeasuredAtFairValueCLIFRS", 1_300_000_000)
        apply_mapped_tag(summary, "ConsumptionTaxesPayableCLIFRS", 229_000_000)
        apply_mapped_tag(summary, "HybridCapitalIFRS", 110_777_000_000)

        self.assertEqual(summary["投資_関係会社株式"], 43_037_000_000)
        self.assertEqual(summary["投資_投資有価証券"], 14_673_000_000)
        self.assertEqual(summary["投資_長期貸付金"], 390_000_000)
        self.assertEqual(summary["流負_関係会社短期借入金"], 1_300_000_000)
        self.assertEqual(summary["流負_未払消費税等"], 229_000_000)
        self.assertEqual(summary["純資_その他資本性金融商品"], 110_777_000_000)

    def test_third_wave_railway_construction_and_utility_extensions(self):
        summary = {key: 0 for key in DISPLAY_ORDER}
        apply_mapped_tag(summary, "NewLineConstructionPromotionFundTrustCA", 183_769_000_000)
        apply_mapped_tag(summary, "AccountsReceivableCARWY", 8_817_000_000)
        apply_mapped_tag(summary, "NewLineConstructionPromotionLongTermLoansNCL", 192_120_000_000)
        apply_mapped_tag(summary, "ProvisionForLossOnRemoveNCL", 2_054_000_000)
        apply_mapped_tag(summary, "NotesReceivableAccountsReceivableFromCompletedConstructionContractsAndContractAssetsCA", 39_706_000_000)
        apply_mapped_tag(summary, "CurrentPortionOfNoncurrentLiabilitiesCLGAS", 37_117_000_000)
        apply_mapped_tag(summary, "ProvisionForGasHolderRepairsGAS", 479_000_000)

        self.assertEqual(summary["流動_その他金融資産"], 183_769_000_000)
        self.assertEqual(summary["流動_鉄道運賃未収金"], 8_817_000_000)
        self.assertEqual(summary["固負_長期借入金"], 192_120_000_000)
        self.assertEqual(summary["固負_引当金"], 2_054_000_000)
        self.assertEqual(summary["流動_受取手形・売掛金(合算)"], 39_706_000_000)
        self.assertEqual(summary["流負_1年内返済固定負債"], 37_117_000_000)
        self.assertEqual(summary["固負_修繕引当金"], 479_000_000)

    def test_third_wave_generic_extensions_cover_large_residuals(self):
        summary = {key: 0 for key in DISPLAY_ORDER}
        apply_mapped_tag(summary, "RealEstateForArrangementCA", 58_911_000_000)
        apply_mapped_tag(summary, "OperatingLoansRealEstateBusinessCA", 39_743_000_000)
        apply_mapped_tag(summary, "AccountsPayableForEquipmentCL", 17_985_000_000)
        apply_mapped_tag(summary, "ProvisionForBusinessRestructuringNCL", 12_270_000_000)
        apply_mapped_tag(summary, "BondsWithSubscriptionRightsToSharesNCL", 10_011_000_000)
        apply_mapped_tag(summary, "SuspensePayments", 8_744_000_000)
        apply_mapped_tag(summary, "ProvisionForLitigationLossCL", 8_744_000_000)
        apply_mapped_tag(summary, "BeneficiaryRightsOnDepositCA", 15_722_000_000)

        self.assertEqual(summary["流動_販売用不動産"], 58_911_000_000)
        self.assertEqual(summary["流動_金融債権"], 39_743_000_000)
        self.assertEqual(summary["流負_未払金"], 17_985_000_000)
        self.assertEqual(summary["固負_引当金"], 12_270_000_000)
        self.assertEqual(summary["固負_転換社債型新株予約権付社債"], 10_011_000_000)
        self.assertEqual(summary["流動_その他未収入金"], 8_744_000_000)
        self.assertEqual(summary["流負_訴訟損失引当金"], 8_744_000_000)
        self.assertEqual(summary["流動_その他金融資産"], 15_722_000_000)

    def test_fourth_wave_finance_and_industry_extensions_cover_large_residuals(self):
        summary = {key: 0 for key in DISPLAY_ORDER}
        values = {
            "AccountsReceivableOperatingLoansCASPF": 1_277_559_000_000,
            "PurchasedReceivablesCA": 10_623_000_000,
            "MiningRightsIA": 615_444_000_000,
            "SalesFinanceReceivablesCAIFRS": 403_581_000_000,
            "SalesFinanceReceivablesNCAIFRS": 395_672_000_000,
            "AccountsReceivableFromCompletedConstructionContractsAndContractAssetsCA": 94_535_000_000,
            "MatureTimberPPE": 44_575_000_000,
            "RestrictedDepositsCAIFRS": 62_721_000_000,
            "NonCurrentFinancialAssetsNCAIFRS": 34_975_000_000,
            "SoftwareInProgressIFRS": 2_333_000_000,
            "LeaseReceivablesAndInvestmentAssetsBNK": 13_667_000_000,
        }
        for tag, value in values.items():
            apply_mapped_tag(summary, tag, value)

        self.assertEqual(summary["流動_営業貸付金"], 1_277_559_000_000)
        self.assertEqual(summary["流動_金融債権"], 414_204_000_000)
        self.assertEqual(summary["投資_金融債権"], 395_672_000_000)
        self.assertEqual(summary["流動_完成工事未収入金・契約資産"], 94_535_000_000)
        self.assertEqual(summary["無形_採掘権"], 615_444_000_000)
        self.assertEqual(summary["有形_立木"], 44_575_000_000)
        self.assertEqual(summary["流動_拘束性預金"], 62_721_000_000)
        self.assertEqual(summary["投資_その他金融資産"], 34_975_000_000)
        self.assertEqual(summary["無形_ソフトウエア仮勘定"], 2_333_000_000)
        self.assertEqual(summary["投資_銀行リース債権"], 13_667_000_000)

    def test_fourth_wave_provisions_and_deferred_items_stay_separate(self):
        summary = {key: 0 for key in DISPLAY_ORDER}
        values = {
            "LongTermDeferredContributionForConstruction": 76_307_000_000,
            "ProvisionForCustomsDuties": 13_624_000_000,
            "ProvisionForAllowanceForLossOnCollectionOfGiftCertificatesOutstndingCL": 4_486_000_000,
            "ProvisionForEnvironmentalMeasuresCL": 343_000_000,
            "AllowanceForCostForCountermeasuresAgainstPotentialFutureDefectsCL": 1_688_000_000,
            "ProvisionForLossContractNCL": 1_273_000_000,
            "ProvisionForApplianceWarrantiesNCL": 1_413_000_000,
            "ProvisionForSafetyMeasuresGAS": 712_000_000,
            "SubordinatedCapitalLoansNCL": 1_800_000_000,
        }
        for tag, value in values.items():
            apply_mapped_tag(summary, tag, value)

        self.assertEqual(summary["固負_長期繰延収益"], 76_307_000_000)
        self.assertEqual(summary["流負_関税引当金"], 13_624_000_000)
        self.assertEqual(summary["流負_商品券回収損失引当金"], 4_486_000_000)
        self.assertEqual(summary["流負_環境対策引当金"], 343_000_000)
        self.assertEqual(summary["流負_将来不具合対策費用引当金"], 1_688_000_000)
        self.assertEqual(summary["固負_契約損失引当金"], 1_273_000_000)
        self.assertEqual(summary["固負_製品保証引当金"], 1_413_000_000)
        self.assertEqual(summary["固負_安全環境対策引当金"], 712_000_000)
        self.assertEqual(summary["固負_劣後特約付借入金"], 1_800_000_000)

    def test_fifth_wave_presentation_lines_stay_in_distinct_categories(self):
        summary = {key: 0 for key in DISPLAY_ORDER}
        values = {
            "AdvancePaymentsTrade": 1_256_000_000,
            "AdvancesPaid": 3_894_000_000,
            "DepositsPaid": 4_189_000_000,
            "TrustBeneficiaryRightIOA": 3_046_000_000,
            "RestrictedDepositsCAIFRS": 62_721_000_000,
            "LeaseAssetsNetPPE": 7_116_800_000,
            "RightOfUseAssetsNetPPE": 2_665_200_000,
            "IntangibleAssetsIA": 2_931_000_000,
            "IntangibleLeasedAssets": 184_000_000,
        }
        for tag, value in values.items():
            apply_mapped_tag(summary, tag, value)

        self.assertEqual(summary["流動_前渡金"], 1_256_000_000)
        self.assertEqual(summary["流動_立替金"], 3_894_000_000)
        self.assertEqual(summary["流動_預け金"], 4_189_000_000)
        self.assertEqual(summary["流動_信託受益権"], 3_046_000_000)
        self.assertEqual(summary["流動_拘束性預金"], 62_721_000_000)
        self.assertEqual(summary["有形_リース資産"], 7_116_800_000)
        self.assertEqual(summary["有形_使用権資産"], 2_665_200_000)
        self.assertEqual(summary["無形_無形資産"], 2_931_000_000)
        self.assertEqual(summary["無形_賃貸資産"], 184_000_000)

    def test_construction_contract_liability_note_is_not_double_counted(self):
        raw_tags = {
            "ContractLiabilities": 320_507_000_000,
            "AdvancesReceivedOfContractLiabilities": 76_823_000_000,
            "AdvancesReceivedOnUncompletedConstructionContractsCNS": 243_683_000_000,
            "AdvancesReceived": 140_055_000_000,
        }

        self.assertEqual(
            should_skip_item_tag("ContractLiabilities", raw_tags),
            "contract_liability_note_skipped_because_reported_advance_lines_exist",
        )

        summary = {key: 0 for key in DISPLAY_ORDER}
        apply_mapped_tag(summary, "AdvancesReceived", raw_tags["AdvancesReceived"])
        apply_mapped_tag(
            summary,
            "AdvancesReceivedOnUncompletedConstructionContractsCNS",
            raw_tags["AdvancesReceivedOnUncompletedConstructionContractsCNS"],
        )
        self.assertEqual(summary["流負_前受金"], 140_055_000_000)
        self.assertEqual(summary["流負_未成工事受入金"], 243_683_000_000)

    def test_sixth_wave_extensions_map_to_reported_sections(self):
        summary = {key: 0 for key in DISPLAY_ORDER}
        values = {
            "NotesAndAccountsRecieavableTradeCA": 4_363_000_000,
            "LandForDevelopmentCA": 710_000_000,
            "CustomerBaseIA": 3_491_000_000,
            "CashPaidForOfferingCASEC": 3_122_000_000,
            "ContractCancellationAdjustmentReserveCL": 2_653_000_000,
            "ProvisionForLossOnLiquidationOfSubsidiariesAndAffiliatesCL": 2_325_000_000,
            "ProvisionForProductCompensationCL": 300_000_000,
            "ProvisionForProductCompensationNCL": 435_000_000,
            "ReserveForReimbursementOfDeposits": 570_000_000,
            "ReserveForReimbursementOfDebentures": 2_778_000_000,
        }
        for tag, value in values.items():
            apply_mapped_tag(summary, tag, value)

        self.assertEqual(summary["流動_受取手形・売掛金(合算)"], 4_363_000_000)
        self.assertEqual(summary["流動_販売用不動産"], 710_000_000)
        self.assertEqual(summary["無形_顧客関連資産"], 3_491_000_000)
        self.assertEqual(summary["流動_募集等払込金"], 3_122_000_000)
        self.assertEqual(summary["流負_契約解約調整引当金"], 2_653_000_000)
        self.assertEqual(summary["流負_関係会社整理損失引当金"], 2_325_000_000)
        self.assertEqual(summary["流負_製品補償引当金"], 300_000_000)
        self.assertEqual(summary["固負_製品補償引当金"], 435_000_000)
        self.assertEqual(summary["固負_銀行預金払戻損失引当金"], 570_000_000)
        self.assertEqual(summary["固負_銀行債券払戻損失引当金"], 2_778_000_000)

    def test_construction_receivables_reconcile_after_face_inventory_lines_are_kept(self):
        summary = {key: 0 for key in DISPLAY_ORDER}
        summary.update({
            "流動_現金及び預金": 434_371_000_000,
            "流動_受取手形・売掛金(合算)": 552_672_000_000,
            "流動_電子記録債権": 14_459_000_000,
            "流動_契約資産": 252_421_000_000,
            "流動_リース債権": 150_722_000_000,
            "流動_金融債権": 39_743_000_000,
            "流動_有価証券": 195_000_000,
            "流動_未成工事支出金": 74_010_000_000,
            "流動_販売用不動産": 3_064_378_000_000,
            "流動_棚卸資産": 41_251_000_000,
            "流動_その他流動資産": 348_538_000_000,
            "流動_貸倒引当金": -3_188_000_000,
        })
        raw_tags = {
            "NotesReceivableAccountsReceivableFromCompletedConstructionContractsAndOtherCNS": 552_672_000_000,
            "ElectronicallyRecordedMonetaryClaims": 14_459_000_000,
            "ContractAssets": 252_421_000_000,
        }

        result = reconcile_receivable_presentation(
            summary,
            {"CurrentAssets": 4_702_696_000_000},
            raw_tags,
        )

        self.assertEqual(result["selected"], "combined")
        self.assertTrue(result["combined_includes_other_claims"])
        self.assertEqual(summary["流動_電子記録債権"], 0)
        self.assertEqual(sum(v for k, v in summary.items() if k.startswith("流動_")), 4_702_692_000_000)

    def test_combined_ifrs_debt_variants_replace_borrowing_and_lease_details(self):
        raw_tags = {
            "BondsBorrowingsAndLeaseLiabilitiesCLIFRS": 443_307_000_000,
            "BorrowingsCLIFRS": 400_000_000_000,
            "LeaseLiabilitiesCLIFRS": 43_307_000_000,
            "OtherFinancialLiabilitiesCLIFRS": 131_952_000_000,
            "BondsBorrowingsAndLeaseLiabilitiesNCLIFRS": 1_516_078_000_000,
            "BorrowingsNCLIFRS": 1_400_000_000_000,
            "LeaseLiabilitiesNCLIFRS": 116_078_000_000,
        }

        self.assertEqual(
            should_skip_item_tag("BorrowingsCLIFRS", raw_tags),
            "debt_detail_skipped_because_combined_current_total_exists",
        )
        self.assertEqual(
            should_skip_item_tag("LeaseLiabilitiesNCLIFRS", raw_tags),
            "debt_detail_skipped_because_combined_noncurrent_total_exists",
        )
        self.assertIsNone(should_skip_item_tag("OtherFinancialLiabilitiesCLIFRS", raw_tags))

    def test_special_finance_equipment_uses_net_value(self):
        raw_tags = {
            "EquipmentPPESPF": 11_124_000_000,
            "EquipmentNetPPESPF": 3_032_000_000,
        }

        self.assertEqual(
            should_skip_item_tag("EquipmentPPESPF", raw_tags),
            "gross_special_finance_equipment_skipped_because_net_exists",
        )

    def test_current_asset_retirement_obligation_is_removed_only_when_it_worsens_fit(self):
        summary = {key: 0 for key in DISPLAY_ORDER}
        summary["流負_支払手形・買掛金"] = 100_000_000_000
        summary["流負_資産除去債務"] = 10_000_000_000
        summary["流負_その他流動負債"] = 100_000_000_000

        adjustments = reconcile_optional_duplicate_categories(
            summary,
            {"CurrentLiabilities": 200_000_000_000},
        )

        self.assertEqual(summary["流負_資産除去債務"], 0)
        self.assertEqual(adjustments[0]["category"], "流負_資産除去債務")

    def test_current_asset_retirement_obligation_does_not_enlarge_a_large_residual(self):
        summary = {key: 0 for key in DISPLAY_ORDER}
        summary["流負_支払手形・買掛金"] = 2_000_000_000_000
        summary["流負_資産除去債務"] = 5_620_000_000
        summary["流負_その他流動負債"] = 500_000_000_000

        adjustments = reconcile_optional_duplicate_categories(
            summary,
            {"CurrentLiabilities": 2_325_174_000_000},
        )

        self.assertEqual(summary["流負_資産除去債務"], 0)
        self.assertEqual(len(adjustments), 1)

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
        self.assertIn(TAG_MAPPING["MarketableSecuritiesCAIFRS"], DISPLAY_ORDER)
        self.assertIn(TAG_MAPPING["LongTermNonRecourseLoansPayableNCL"], DISPLAY_ORDER)
        self.assertEqual(TAG_MAPPING["LongTermLeaseAndGuaranteeDeposited"], "固負_長期預り金")

    def test_independent_financial_loan_books_are_added(self):
        summary = {key: 0 for key in DISPLAY_ORDER}
        apply_mapped_tag(summary, "OperatingLoansCA", 663_896_000_000)
        apply_mapped_tag(summary, "LoansAndBillsDiscountedForBankingBusinessCA", 3_197_412_000_000)
        apply_mapped_tag(summary, "CallLoansAssetsBNK", 1_396_000_000)

        self.assertEqual(summary["流動_金融債権"], 3_862_704_000_000)

    def test_construction_payables_and_electronic_obligations_are_independent(self):
        summary = {key: 0 for key in DISPLAY_ORDER}
        apply_mapped_tag(
            summary,
            "NotesPayableAccountsPayableForConstructionContractsAndOtherCNS",
            594_367_000_000,
        )
        apply_mapped_tag(
            summary,
            "ElectronicallyRecordedObligationsOperatingCL",
            87_635_000_000,
        )

        self.assertEqual(summary["流負_工事関係支払手形・買掛金"], 594_367_000_000)
        self.assertEqual(summary["流負_電子記録債務"], 87_635_000_000)

    def test_trade_notes_and_related_company_borrowings_are_independent(self):
        summary = {key: 0 for key in DISPLAY_ORDER}
        values = {
            "NotesPayableTrade": 6_245_000_000,
            "AccountsPayableTrade": 34_213_000_000,
            "ShortTermLoansPayable": 69_038_000_000,
            "ShortTermLoansPayableToSubsidiariesAndAffiliates": 181_699_000_000,
        }
        for tag, value in values.items():
            apply_mapped_tag(summary, tag, value)

        self.assertEqual(summary["流負_支払手形"], 6_245_000_000)
        self.assertEqual(summary["流負_支払手形・買掛金"], 34_213_000_000)
        self.assertEqual(summary["流負_短期借入金"], 69_038_000_000)
        self.assertEqual(summary["流負_関係会社短期借入金"], 181_699_000_000)

    def test_trade_payable_details_are_skipped_when_combined_total_exists(self):
        raw_tags = {
            "NotesAndAccountsPayableTrade": 40_458_000_000,
            "NotesPayableTrade": 6_245_000_000,
            "AccountsPayableTrade": 34_213_000_000,
        }

        self.assertEqual(
            should_skip_item_tag("NotesPayableTrade", raw_tags),
            "trade_payable_detail_skipped_because_combined_total_exists",
        )
        self.assertEqual(
            should_skip_item_tag("AccountsPayableTrade", raw_tags),
            "trade_payable_detail_skipped_because_combined_total_exists",
        )
        self.assertIsNone(should_skip_item_tag("OperatingAccountsPayable", raw_tags))

    def test_industry_specific_assets_and_liabilities_are_separate(self):
        summary = {key: 0 for key in DISPLAY_ORDER}
        values = {
            "LandForGeneralUsePPE": 16_038_000_000,
            "LandUsedForMiningOperationsNetPPE": 3_623_000_000,
            "MiningRight": 3_127_000_000,
            "AquacultureConcessionsIA": 21_033_000_000,
            "MachinerysAndEquipmentsNet": 21_890_000_000,
            "LongTermTimeDepositsIOA": 20_220_000_000,
            "ReturnLiabilityCL": 20_625_000_000,
            "WarrantyReservesCL": 8_870_000_000,
            "ProvisionForEmployeeStockOwnershipPlanTrustNCL": 1_635_000_000,
        }
        for tag, value in values.items():
            apply_mapped_tag(summary, tag, value)

        self.assertEqual(summary["有形_土地"], 16_038_000_000)
        self.assertEqual(summary["有形_鉱業用土地"], 3_623_000_000)
        self.assertEqual(summary["無形_採掘権"], 3_127_000_000)
        self.assertEqual(summary["無形_養殖権・水面利用権"], 21_033_000_000)
        self.assertEqual(summary["投資_長期預け金"], 20_220_000_000)
        self.assertEqual(summary["流負_返品負債"], 20_625_000_000)
        self.assertEqual(summary["流負_製品保証引当金"], 8_870_000_000)
        self.assertEqual(summary["固負_従業員持株ESOP引当金"], 1_635_000_000)

    def test_independent_detail_lines_do_not_collapse_into_max_categories(self):
        summary = {key: 0 for key in DISPLAY_ORDER}
        values = {
            "AccountsReceivableOther": 16_841_000_000,
            "OtherAccountsReceivable": 6_178_000_000,
            "Software": 7_627_000_000,
            "SoftwareInProgress": 68_133_000_000,
            "LeaseAndGuaranteeDeposits": 426_906_000_000,
            "DepositsForStoresInPreparation": 4_116_000_000,
            "ProvisionForLossOnStoreClosing": 17_273_000_000,
            "ProvisionForPointCardCertificatesCL": 7_967_000_000,
            "ProvisionForLossOnStoreClosingNCL": 9_149_000_000,
            "ProvisionForLossOnInterestRepaymentNCL": 698_000_000,
        }
        for tag, value in values.items():
            apply_mapped_tag(summary, tag, value)

        self.assertEqual(summary["流動_未収入金"], 16_841_000_000)
        self.assertEqual(summary["流動_その他未収入金"], 6_178_000_000)
        self.assertEqual(summary["無形_ソフトウエア"], 7_627_000_000)
        self.assertEqual(summary["無形_ソフトウエア仮勘定"], 68_133_000_000)
        self.assertEqual(summary["投資_差入保証金"], 426_906_000_000)
        self.assertEqual(summary["投資_店舗開設準備預け金"], 4_116_000_000)
        self.assertEqual(summary["流負_引当金"], 17_273_000_000)
        self.assertEqual(summary["流負_ポイント引当金"], 7_967_000_000)
        self.assertEqual(summary["固負_引当金"], 9_149_000_000)
        self.assertEqual(summary["固負_利息返還損失引当金"], 698_000_000)

    def test_new_current_asset_and_amusement_tags_are_mapped(self):
        summary = {key: 0 for key in DISPLAY_ORDER}
        values = {
            "PrgramsAndWorkInProgress": 15_714_000_000,
            "ShortTermLoansReceivableWithResaleAgreementCA": 14_985_000_000,
            "ShortTermLoansReceivableToSubsidiariesAndAffiliates": 2_901_000_000,
            "AmusementFacilitiesAndMachinesNet": 17_495_000_000,
        }
        for tag, value in values.items():
            apply_mapped_tag(summary, tag, value)

        self.assertEqual(summary["流動_棚卸資産"], 15_714_000_000)
        self.assertEqual(summary["流動_短期貸付金"], 14_985_000_000)
        self.assertEqual(summary["流動_関係会社短期貸付金"], 2_901_000_000)
        self.assertEqual(summary["有形_アミューズメント施設・機械"], 17_495_000_000)

    def test_valuation_parent_total_replaces_its_components(self):
        raw_tags = {
            "ValuationAndTranslationAdjustments": -3_294_000_000,
            "RevaluationReserveForLand": -4_342_000_000,
        }

        self.assertEqual(
            should_skip_item_tag("RevaluationReserveForLand", raw_tags),
            "valuation_adjustment_detail_skipped_because_parent_total_exists",
        )
        self.assertIsNone(
            should_skip_item_tag("ValuationAndTranslationAdjustments", raw_tags)
        )

    def test_gross_amusement_assets_are_skipped_when_net_value_exists(self):
        raw_tags = {
            "AmusementFacilitiesAndMachines": 72_393_000_000,
            "AmusementFacilitiesAndMachinesNet": 17_495_000_000,
        }

        self.assertEqual(
            should_skip_item_tag("AmusementFacilitiesAndMachines", raw_tags),
            "gross_value_skipped_because_net_exists",
        )

    def test_next_residual_detail_lines_use_independent_categories(self):
        summary = {key: 0 for key in DISPLAY_ORDER}
        values = {
            "EmployeeBenefitsAccrualsCLIFRS": 51_585_000_000,
            "ProvisionsCLIFRS": 6_362_000_000,
            "InformationSystemEquipmentIFRS": 5_460_000_000,
            "BuildingsIFRS": 1_177_000_000,
            "UntitledNCLIFRS": 2_190_000_000,
            "VehiclesToolsFurnitureAndFixturesNet": 404_000_000,
            "ValuationDifferenceOnAvailableForSaleSecurities": 7_302_000_000,
        }
        for tag, value in values.items():
            apply_mapped_tag(summary, tag, value)

        self.assertEqual(summary["流負_従業員給付未払金"], 51_585_000_000)
        self.assertEqual(summary["流負_引当金"], 6_362_000_000)
        self.assertEqual(summary["有形_情報システム機器"], 5_460_000_000)
        self.assertEqual(summary["有形_建物・構築物"], 1_177_000_000)
        self.assertEqual(summary["固負_内訳未分類"], 2_190_000_000)
        self.assertEqual(summary["有形_工具器具備品"], 404_000_000)
        self.assertEqual(summary["純資_評価換算差額金"], 7_302_000_000)

    def test_construction_inventory_parent_and_pfi_assets_are_distinct(self):
        raw_tags = {
            "OtherInventories": 12_568_000_000,
            "RawMaterialsAndSupplies": 7_708_000_000,
            "CostsOnOtherBusiness": 4_859_000_000,
            "InventoriesForPFIAndOtherProjectsCA": 1_545_000_000,
            "CostsOnPFIBusiness": 1_545_000_000,
        }

        self.assertEqual(
            should_skip_item_tag("RawMaterialsAndSupplies", raw_tags),
            "inventory_subdetail_skipped_because_other_inventory_total_matches",
        )
        self.assertEqual(
            should_skip_item_tag("CostsOnOtherBusiness", raw_tags),
            "inventory_subdetail_skipped_because_other_inventory_total_matches",
        )

        summary = {key: 0 for key in DISPLAY_ORDER}
        apply_mapped_tag(summary, "InventoriesForPFIAndOtherProjectsCA", 1_545_000_000)
        apply_mapped_tag(summary, "CostsOnPFIBusiness", 1_545_000_000)
        self.assertEqual(summary["流動_PFI等プロジェクト棚卸資産"], 1_545_000_000)

    def test_current_nonrecourse_loan_is_not_lost(self):
        summary = {key: 0 for key in DISPLAY_ORDER}
        apply_mapped_tag(summary, "CurrentPortionOfNonrecourseLoansCL", 8_510_000_000)

        self.assertEqual(summary["流負_短期ノンリコース借入金"], 8_510_000_000)

    def test_bank_statement_lines_close_without_current_noncurrent_split(self):
        summary = {key: 0 for key in DISPLAY_ORDER}
        values = {
            "CashAndDueFromBanksAssetsBNK": 28_188_180_000_000,
            "LoansAndBillsDiscountedAssetsBNK": 67_119_350_000_000,
            "SecuritiesAssetsBNK": 33_652_530_000_000,
            "AllowanceForLoanLossesAssetsBNK": -535_920_000_000,
            "DepositsLiabilitiesBNK": 95_520_500_000_000,
            "BorrowedMoneyLiabilitiesBNK": 10_979_090_000_000,
        }
        for tag, value in values.items():
            apply_mapped_tag(summary, tag, value)
        summary["流動_リース債権"] = 105_308_000_000
        summary["流動_割賦売掛金"] = 1_384_050_000_000

        adjustments = reconcile_bank_presentation(
            summary,
            {"CurrentAssets": 0, "CurrentLiabilities": 0},
            values,
        )

        self.assertEqual(summary["流動_リース債権"], 0)
        self.assertEqual(summary["投資_銀行リース債権"], 105_308_000_000)
        self.assertEqual(summary["流動_割賦売掛金"], 0)
        self.assertEqual(summary["投資_銀行割賦債権"], 1_384_050_000_000)
        self.assertEqual(summary["投資_銀行貸倒引当金"], -535_920_000_000)
        self.assertEqual(adjustments[0]["reason"], "bank_statement_has_no_current_noncurrent_split")
        self.assertEqual(len(adjustments), 2)
        self.assertEqual(
            should_skip_item_tag("CashAndCashEquivalents", values),
            "general_cash_skipped_because_bank_cash_exists",
        )

    def test_bank_unsplit_statement_moves_generic_face_liabilities(self):
        summary = {key: 0 for key in DISPLAY_ORDER}
        raw_tags = {
            "DepositsLiabilitiesBNK": 13_021_673_000_000,
            "ShortTermBondsPayable": 105_500_000_000,
            "ProvisionForBonuses": 12_468_000_000,
            "ProvisionForDirectorsBonuses": 18_000_000,
            "ReserveForReimbursementOfDeposits": 570_000_000,
            "ReserveForReimbursementOfDebentures": 2_778_000_000,
        }
        for tag, value in raw_tags.items():
            apply_mapped_tag(summary, tag, value)

        adjustments = reconcile_bank_presentation(
            summary,
            {"CurrentAssets": 0, "CurrentLiabilities": 0},
            raw_tags,
        )

        self.assertEqual(summary["流負_短期社債"], 0)
        self.assertEqual(summary["固負_銀行短期社債"], 105_500_000_000)
        self.assertEqual(summary["流負_賞与引当金"], 0)
        self.assertEqual(summary["固負_銀行賞与引当金"], 12_468_000_000)
        self.assertEqual(summary["流負_役員賞与引当金"], 0)
        self.assertEqual(summary["固負_銀行役員賞与引当金"], 18_000_000)
        self.assertEqual(summary["固負_銀行預金払戻損失引当金"], 570_000_000)
        self.assertEqual(summary["固負_銀行債券払戻損失引当金"], 2_778_000_000)
        self.assertEqual(len(adjustments), 3)

    def test_leasing_parent_aliases_are_skipped_for_preferred_totals(self):
        raw_tags = {
            "LeasedAssetsPPELEA": 839_102_000_000,
            "PropertyForLeasePPELEA": 836_801_000_000,
            "AdvancesForPurchasesAtLeasedAssetsPPELEA": 2_300_000_000,
            "OtherOperatingAssetsPPE": 153_835_000_000,
            "OtherOperatingAssetsTotalPPE": 153_835_000_000,
        }

        self.assertEqual(
            should_skip_item_tag("LeasedAssetsPPELEA", raw_tags),
            "leasing_parent_or_alias_skipped_because_preferred_total_exists",
        )
        self.assertEqual(
            should_skip_item_tag("OtherOperatingAssetsPPE", raw_tags),
            "leasing_parent_or_alias_skipped_because_preferred_total_exists",
        )

    def test_broad_industry_residual_tags_have_distinct_categories(self):
        summary = {key: 0 for key in DISPLAY_ORDER}
        values = {
            "LandAndBuildingsForSaleCARWY": 220_757_000_000,
            "ProvisionForRepairsNCL": 104_409_000_000,
            "EquityUnderwrittenCA": 76_363_000_000,
            "AircraftAndOtherAssetsForSaleCA": 15_152_000_000,
            "ShortTermGuaranteeDepositsCASEC": 85_489_000_000,
            "ShortTermBondsPayable": 11_290_000_000,
            "CurrentPortionOfBonds": 4_777_000_000,
        }
        for tag, value in values.items():
            apply_mapped_tag(summary, tag, value)

        self.assertEqual(summary["流動_販売用不動産"], 220_757_000_000)
        self.assertEqual(summary["固負_修繕引当金"], 104_409_000_000)
        self.assertEqual(summary["流動_引受出資持分"], 76_363_000_000)
        self.assertEqual(summary["流動_販売用航空機等"], 15_152_000_000)
        self.assertEqual(summary["流動_短期差入保証金"], 85_489_000_000)
        self.assertEqual(summary["流負_短期社債"], 11_290_000_000)
        self.assertEqual(summary["流負_1年内償還社債"], 4_777_000_000)

    def test_empty_financial_data_keeps_bs_batch_contract(self):
        data = empty_financial_data()

        self.assertEqual(data["株価"], 0)
        self.assertEqual(data["ROE_pct"], 0)
        self.assertEqual(data["時価総額_億"], 0)

    def test_bank_tags_follow_reported_current_sections_for_hybrid_company(self):
        summary = {key: 0 for key in DISPLAY_ORDER}
        values = {
            "LoansAndBillsDiscountedAssetsBNK": 7_743_000_000,
            "DepositsLiabilitiesBNK": 9_475_000_000,
        }
        for tag, value in values.items():
            apply_mapped_tag(summary, tag, value)

        adjustments = reconcile_bank_presentation(
            summary,
            {"CurrentAssets": 20_000_000_000, "CurrentLiabilities": 15_000_000_000},
            values,
        )

        self.assertEqual(summary["投資_銀行貸出金"], 0)
        self.assertEqual(summary["流動_銀行貸出金"], 7_743_000_000)
        self.assertEqual(summary["固負_銀行預金"], 0)
        self.assertEqual(summary["流負_銀行預金"], 9_475_000_000)
        self.assertEqual(len(adjustments), 2)

    def test_insurance_statement_moves_unsplit_cash_and_current_liabilities(self):
        summary = {key: 0 for key in DISPLAY_ORDER}
        summary["流動_現金及び預金"] = 1_752_984_000_000
        summary["投資_保険現金預金"] = 1_752_984_000_000
        summary["流負_役員賞与引当金"] = 248_000_000
        raw_tags = {
            "CashAndDepositsAssetsINS": 1_752_984_000_000,
            "PolicyReserveLiabilitiesINS": 46_653_326_000_000,
        }

        adjustments = reconcile_insurance_presentation(
            summary,
            {"CurrentAssets": 0, "CurrentLiabilities": 0},
            raw_tags,
        )

        self.assertEqual(summary["流動_現金及び預金"], 0)
        self.assertEqual(summary["投資_保険現金預金"], 1_752_984_000_000)
        self.assertEqual(summary["流負_役員賞与引当金"], 0)
        self.assertEqual(summary["固負_保険その他負債"], 248_000_000)
        self.assertEqual(len(adjustments), 2)

    def test_category_move_adjustment_can_be_serialized_without_section_deltas(self):
        result = serialize_reconciliation_adjustment({
            "category": "流動_リース債権",
            "moved_to": "投資_銀行リース債権",
            "value": 105_308_000_000,
            "reason": "bank_statement_has_no_current_noncurrent_split",
        })

        self.assertEqual(result["value_oku"], 1053.08)
        self.assertEqual(result["delta_before_oku"], 0)
        self.assertEqual(result["delta_after_oku"], 0)

    def test_second_breadth_wave_maps_airline_shipping_and_crypto_lines(self):
        summary = {key: 0 for key in DISPLAY_ORDER}
        values = {
            "AircraftPartsNetPPE": 10_016_000_000,
            "ProvisionForReserveForScheduledMaintenanceCostsNCL": 19_260_000_000,
            "DerivativesCA": 4_443_000_000,
            "ForwardExchangeContractsCA": 1_823_000_000,
            "DerivativesIOA": 1_295_000_000,
            "ForwardExchangeContractsIOA": 724_000_000,
            "TradeReceivablesAndContractAssetsCA": 32_132_000_000,
            "LendingCryptoAssetsCA": 14_970_000_000,
            "OwnedCryptoassetsCA": 771_000_000,
            "LongTermUnearnedRevenue": 13_523_500_000,
            "RightToReimbursementCA": 6_539_700_000,
        }
        for tag, value in values.items():
            apply_mapped_tag(summary, tag, value)

        self.assertEqual(summary["有形_航空機部品"], 10_016_000_000)
        self.assertEqual(summary["固負_定期整備引当金"], 19_260_000_000)
        self.assertEqual(summary["流動_デリバティブ資産"], 4_443_000_000)
        self.assertEqual(summary["流動_為替予約資産"], 1_823_000_000)
        self.assertEqual(summary["投資_デリバティブ資産"], 1_295_000_000)
        self.assertEqual(summary["投資_為替予約資産"], 724_000_000)
        self.assertEqual(summary["流動_受取手形・売掛金(合算)"], 32_132_000_000)
        self.assertEqual(summary["流動_貸借暗号資産"], 14_970_000_000)
        self.assertEqual(summary["流動_自己保有暗号資産"], 771_000_000)
        self.assertEqual(summary["固負_長期前受収益"], 13_523_500_000)
        self.assertEqual(summary["流動_補填請求権"], 6_539_700_000)

    def test_section_total_selects_contract_detail_over_parent_total(self):
        summary = {key: 0 for key in DISPLAY_ORDER}
        summary["流負_支払手形・買掛金"] = 1_009_275_000_000
        summary["流負_前受金"] = 299_979_000_000
        summary["流負_契約負債"] = 307_016_000_000
        summary["流負_短期ノンリコース借入金"] = 8_510_000_000
        summary["流負_その他流動負債"] = 111_757_000_000
        totals = {"CurrentLiabilities": 1_429_526_000_000}

        adjustments = reconcile_optional_duplicate_categories(summary, totals)

        self.assertEqual(summary["流負_前受金"], 299_979_000_000)
        self.assertEqual(summary["流負_契約負債"], 0)
        self.assertEqual(adjustments[0]["category"], "流負_契約負債")
        self.assertEqual(adjustments[0]["delta_after"], 5_000_000)

    def test_machinery_vehicles_and_special_repairs_use_correct_sections(self):
        summary = {key: 0 for key in DISPLAY_ORDER}
        apply_mapped_tag(summary, "MachineryAndEquipmentNet", 17_659_000_000)
        apply_mapped_tag(summary, "VehiclesNet", 21_871_000_000)
        apply_mapped_tag(summary, "ProvisionForSpecialRepairs", 7_626_000_000)

        self.assertEqual(summary["有形_機械・運搬具"], 17_659_000_000)
        self.assertEqual(summary["有形_車両運搬具"], 21_871_000_000)
        self.assertEqual(summary["固負_特別修繕引当金"], 7_626_000_000)

    def test_gross_mining_land_is_skipped_when_net_value_exists(self):
        raw_tags = {
            "LandUsedForMiningOperationsPPE": 10_746_000_000,
            "LandUsedForMiningOperationsNetPPE": 3_623_000_000,
        }

        self.assertEqual(
            should_skip_item_tag("LandUsedForMiningOperationsPPE", raw_tags),
            "gross_mining_land_skipped_because_net_exists",
        )

    def test_warranty_mapping_allows_duplicate_contract_liability_removal(self):
        summary = {key: 0 for key in DISPLAY_ORDER}
        summary["流負_支払手形・買掛金"] = 46_262_000_000
        summary["流負_未払法人税等"] = 25_694_000_000
        summary["流負_その他流動負債"] = 98_631_000_000
        summary["流負_契約負債"] = 35_173_000_000
        apply_mapped_tag(summary, "WarrantyReservesCL", 8_870_000_000)
        totals = {"CurrentLiabilities": 179_457_000_000}

        adjustments = reconcile_optional_duplicate_categories(summary, totals)

        self.assertEqual(summary["流負_契約負債"], 0)
        self.assertEqual(adjustments[0]["category"], "流負_契約負債")

    def test_construction_payable_allows_duplicate_contract_liability_removal(self):
        summary = {key: 0 for key in DISPLAY_ORDER}
        summary["流負_短期借入金"] = 20_995_000_000
        summary["流負_未払法人税等"] = 7_171_000_000
        summary["流負_前受金"] = 31_657_000_000
        summary["流負_預り金"] = 49_400_000_000
        summary["流負_完成工事補償引当金"] = 1_746_000_000
        summary["流負_賞与引当金"] = 3_990_000_000
        summary["流負_工事損失引当金"] = 605_000_000
        summary["流負_その他流動負債"] = 11_049_000_000
        summary["流負_契約負債"] = 34_659_000_000
        apply_mapped_tag(
            summary,
            "AccountsPayableForConstructionContractsAndOtherCL",
            59_764_000_000,
        )
        totals = {"CurrentLiabilities": 186_382_000_000}

        adjustments = reconcile_optional_duplicate_categories(summary, totals)

        self.assertEqual(summary["流負_契約負債"], 0)
        self.assertEqual(summary["流負_前受金"], 31_657_000_000)
        self.assertEqual(adjustments[0]["category"], "流負_契約負債")

    def test_machinery_group_enables_aggregate_depreciation_reconciliation(self):
        summary = {key: 0 for key in DISPLAY_ORDER}
        summary["有形_建物・構築物"] = 10_000_000_000
        summary["投資_投資有価証券"] = 50_000_000_000
        apply_mapped_tag(
            summary,
            "MachineryVehiclesToolsFurnitureAndFixtures",
            17_315_000_000,
        )
        totals = {"NonCurrentAssets": 48_223_000_000}
        raw_tags = {"AccumulatedDepreciationPPEByGroup": -29_092_000_000}

        adjustments = reconcile_skipped_section_summaries(summary, totals, raw_tags)

        self.assertEqual(summary["有形_減価償却累計額"], -29_092_000_000)
        self.assertEqual(adjustments[0]["tag"], "AccumulatedDepreciationPPEByGroup")

    def test_ifrs_independent_asset_components_do_not_collide(self):
        summary = {key: 0 for key in DISPLAY_ORDER}
        values = {
            "CapitalizedDevelopmentCostsIFRS": 488_048_000_000,
            "OtherComponentsOfIntangibleAssetsIFRS": 58_343_000_000,
            "BiologicalAssetsNCAIFRS": 32_274_000_000,
            "CallLoanAndBillsBoughtCAIFRS": 33_372_000_000,
            "AccountsReceivableOperationCA": 43_732_000_000,
        }
        for tag, value in values.items():
            apply_mapped_tag(summary, tag, value)

        self.assertEqual(summary["無形_開発資産"], 488_048_000_000)
        self.assertEqual(summary["無形_その他無形固定資産"], 58_343_000_000)
        self.assertEqual(summary["投資_生物資産"], 32_274_000_000)
        self.assertEqual(summary["流動_コールローン"], 33_372_000_000)
        self.assertEqual(summary["流動_営業未収入金"], 43_732_000_000)

    def test_negative_other_capital_reserve_is_preserved_separately(self):
        summary = {key: 0 for key in DISPLAY_ORDER}
        apply_mapped_tag(summary, "CapitalSurplusIFRS", 15_899_000_000)
        apply_mapped_tag(summary, "OtherCapitalReservesEquityIFRS", -39_061_000_000)

        self.assertEqual(summary["純資_資本剰余金"], 15_899_000_000)
        self.assertEqual(summary["純資_その他資本剰余金"], -39_061_000_000)

    def test_development_cost_is_skipped_only_when_other_intangible_total_exists(self):
        with_other_total = {
            "OtherIntangibleAssetsIFRS": 1_215_731_000_000,
            "CapitalizedDevelopmentCosts2IFRS": 147_444_000_000,
        }
        independent_components = {
            "OtherComponentsOfIntangibleAssetsIFRS": 58_343_000_000,
            "CapitalizedDevelopmentCostsIFRS": 488_048_000_000,
        }

        self.assertEqual(
            should_skip_item_tag("CapitalizedDevelopmentCosts2IFRS", with_other_total),
            "intangible_component_skipped_because_other_intangible_total_exists",
        )
        self.assertIsNone(
            should_skip_item_tag("CapitalizedDevelopmentCostsIFRS", independent_components)
        )

    def test_negative_equity_component_is_not_replaced_with_zero(self):
        summary = {key: 0 for key in DISPLAY_ORDER}
        apply_mapped_tag(summary, "CapitalSurplusIFRS", -459_335_000_000)

        self.assertEqual(summary["純資_資本剰余金"], -459_335_000_000)

    def test_skipped_ppe_summary_is_restored_when_it_closes_section_total(self):
        summary = {key: 0 for key in DISPLAY_ORDER}
        summary["有形_リース資産"] = 21_854_000_000
        summary["無形_その他無形固定資産"] = 59_277_000_000
        summary["投資_繰延税金資産"] = 84_689_000_000
        summary["投資_退職給付資産"] = 26_693_000_000
        summary["投資_その他固定資産"] = 71_590_000_000
        totals = {"NonCurrentAssets": 745_725_000_000}
        raw_tags = {"PropertyPlantAndEquipmentIFRS": 481_623_000_000}

        adjustments = reconcile_skipped_section_summaries(summary, totals, raw_tags)

        self.assertEqual(summary["有形_その他有形固定資産"], 481_623_000_000)
        self.assertEqual(adjustments[0]["tag"], "PropertyPlantAndEquipmentIFRS")

    def test_skipped_ppe_summary_stays_skipped_when_details_already_cover_it(self):
        summary = {key: 0 for key in DISPLAY_ORDER}
        summary["有形_建物・構築物"] = 1_194_791_000_000
        summary["有形_機械・運搬具"] = 445_126_000_000
        summary["有形_土地"] = 424_871_000_000
        summary["有形_その他有形固定資産"] = 39_477_000_000
        totals = {"NonCurrentAssets": 10_462_730_000_000}
        raw_tags = {"PropertyPlantAndEquipmentIFRS": 2_416_885_000_000}

        adjustments = reconcile_skipped_section_summaries(summary, totals, raw_tags)

        self.assertEqual(summary["有形_その他有形固定資産"], 39_477_000_000)
        self.assertEqual(adjustments, [])

    def test_ifrs_parent_summaries_add_only_unrepresented_remainders(self):
        summary = {key: 0 for key in DISPLAY_ORDER}
        summary["有形_建物・構築物"] = 131_420_000_000
        summary["有形_土地"] = 73_970_000_000
        summary["有形_建設仮勘定"] = 12_850_000_000
        summary["無形_のれん"] = 170_110_000_000
        summary["無形_ソフトウエア"] = 38_770_000_000
        summary["無形_その他無形固定資産"] = 2_780_000_000
        totals = {"NonCurrentAssets": 1_099_930_000_000}
        raw_tags = {
            "PropertyPlantAndEquipmentIFRS": 596_770_000_000,
            "IntangibleAssetsIFRS": 333_050_000_000,
        }

        adjustments = reconcile_skipped_section_summaries(summary, totals, raw_tags)

        self.assertEqual(summary["有形_その他有形固定資産"], 378_530_000_000)
        self.assertEqual(summary["無形_その他無形固定資産"], 294_280_000_000)
        self.assertEqual(len(adjustments), 2)
        self.assertEqual(
            {item["reason"] for item in adjustments},
            {"section_total_supports_skipped_summary_remainder"},
        )

    def test_jgaap_investments_parent_fills_an_unrepresented_section(self):
        summary = {key: 0 for key in DISPLAY_ORDER}
        summary["有形_建物・構築物"] = 3_252_560_000
        summary["有形_土地"] = 2_646_555_000
        summary["有形_その他有形固定資産"] = 89_460_000
        summary["無形_その他無形固定資産"] = 729_204_000
        totals = {"NonCurrentAssets": 9_243_512_000}
        raw_tags = {
            "PropertyPlantAndEquipment": 5_988_575_000,
            "InvestmentsAndOtherAssets": 2_525_733_000,
        }

        adjustments = reconcile_skipped_section_summaries(summary, totals, raw_tags)

        self.assertEqual(summary["投資_その他固定資産"], 2_525_733_000)
        self.assertEqual(len(adjustments), 1)
        self.assertEqual(adjustments[0]["tag"], "InvestmentsAndOtherAssets")

    def test_new_industry_specific_tags_use_independent_categories(self):
        summary = {key: 0 for key in DISPLAY_ORDER}
        apply_mapped_tag(summary, "AccountsReceivableLeaseCALEA", 50_390_000_000)
        apply_mapped_tag(summary, "RetainedEarningsCumulativeTranslationIFRS", -34_300_000_000)
        apply_mapped_tag(summary, "MarketingRelatedAssetsIA", 107_310_000_000)

        self.assertEqual(summary["流動_リース売掛金"], 50_390_000_000)
        self.assertEqual(summary["純資_累積換算調整額"], -34_300_000_000)
        self.assertEqual(summary["無形_マーケティング関連資産"], 107_310_000_000)

    def test_expanded_provisions_remain_independent(self):
        summary = {key: 0 for key in DISPLAY_ORDER}
        apply_mapped_tag(summary, "AccruedLongServiceRewardsForEmployeesNCL", 1_117_000_000)
        apply_mapped_tag(summary, "ProvisionForEnvironmentalMeasuresNCL", 650_000_000)
        apply_mapped_tag(
            summary,
            "ProvisionForPreventingEnvironmentalPollutionInMineralMiningAndOtherOperationsNCL",
            850_000_000,
        )
        apply_mapped_tag(summary, "ProvisionForLossOnOrderReceivedCL", 1_503_000_000)

        self.assertEqual(summary["固負_長期勤続報奨引当金"], 1_117_000_000)
        self.assertEqual(summary["固負_環境対策引当金"], 650_000_000)
        self.assertEqual(summary["固負_鉱害防止引当金"], 850_000_000)
        self.assertEqual(summary["流負_受注損失引当金"], 1_503_000_000)

    def test_specialized_assets_map_to_their_natural_sections(self):
        summary = {key: 0 for key in DISPLAY_ORDER}
        apply_mapped_tag(summary, "TreesPPE", 1_108_000_000)
        apply_mapped_tag(summary, "RightOfUsingElectricSupplyFacilities", 726_000_000)
        apply_mapped_tag(summary, "IndustrialPropertyIFRS", 1_464_000_000)
        apply_mapped_tag(summary, "RawMaterialsAndSuppliesCNS", 1_335_000_000)
        apply_mapped_tag(summary, "LongTermInvestments", 449_524_000_000)

        self.assertEqual(summary["有形_立木"], 1_108_000_000)
        self.assertEqual(summary["有形_施設利用権"], 726_000_000)
        self.assertEqual(summary["無形_産業財産権"], 1_464_000_000)
        self.assertEqual(summary["流動_棚卸資産"], 1_335_000_000)
        self.assertEqual(summary["投資_投資有価証券"], 449_524_000_000)

    def test_construction_materials_are_kept_separate_from_contract_costs(self):
        reason = should_skip_item_tag(
            "RawMaterialsAndSuppliesCNS",
            {
                "RawMaterialsAndSuppliesCNS": 33_000_000,
                "CostsOnUncompletedConstructionContractsCNS": 240_000_000,
            },
        )

        self.assertIsNone(reason)

    def test_construction_contract_costs_are_skipped_when_inventory_total_exists(self):
        reason = should_skip_item_tag(
            "CostsOnUncompletedConstructionContractsCNS",
            {
                "Inventories": 23_283_500_000,
                "CostsOnUncompletedConstructionContractsCNS": 362_300_000,
            },
        )

        self.assertEqual(reason, "inventory_detail_skipped_because_total_exists")

    def test_aggregate_accumulated_depreciation_is_used_when_it_reconciles_assets(self):
        summary = {key: 0 for key in DISPLAY_ORDER}
        summary["有形_建物・構築物"] = 130_000_000_000
        totals = {"NonCurrentAssets": 100_000_000_000}
        raw_tags = {"AccumulatedDepreciationPPEByGroup": -30_000_000_000}

        adjustments = reconcile_skipped_section_summaries(summary, totals, raw_tags)

        self.assertEqual(summary["有形_減価償却累計額"], -30_000_000_000)
        self.assertEqual(adjustments[0]["tag"], "AccumulatedDepreciationPPEByGroup")

    def test_ppe_parent_total_removes_a_duplicated_component(self):
        summary = {key: 0 for key in DISPLAY_ORDER}
        summary["有形_航空機"] = 1_041_696_000_000
        summary["有形_建設仮勘定"] = 115_612_000_000
        summary["有形_その他有形固定資産"] = 102_221_000_000
        summary["有形_建物・構築物"] = 35_585_000_000
        totals = {"NonCurrentAssets": 1_259_530_000_000}
        raw_tags = {"PropertyPlantAndEquipmentIFRS": 1_259_530_000_000}

        adjustments = reconcile_parent_component_overlaps(summary, totals, raw_tags)

        self.assertEqual(summary["有形_建物・構築物"], 0)
        self.assertEqual(adjustments[0]["reason"], "parent_total_indicates_duplicate_component")

    def test_ppe_component_is_kept_when_section_total_would_get_worse(self):
        summary = {key: 0 for key in DISPLAY_ORDER}
        summary["有形_建物・構築物"] = 100_000_000_000
        summary["有形_リース資産"] = 50_000_000_000
        totals = {"NonCurrentAssets": 150_000_000_000}
        raw_tags = {"PropertyPlantAndEquipmentIFRS": 100_000_000_000}

        adjustments = reconcile_parent_component_overlaps(summary, totals, raw_tags)

        self.assertEqual(summary["有形_リース資産"], 50_000_000_000)
        self.assertEqual(adjustments, [])

    def test_duplicate_contract_liability_alias_is_skipped(self):
        reason = should_skip_item_tag(
            "ContractLiabilitiesCL",
            {"ContractLiabilities": 112_142_000_000},
        )

        self.assertEqual(reason, "duplicate_contract_liability_alias")

    def test_noncurrent_contract_liability_can_be_removed_when_included_in_other(self):
        summary = {key: 0 for key in DISPLAY_ORDER}
        summary["固負_契約負債"] = 32_414_000_000
        summary["固負_その他固定負債"] = 69_726_000_000
        summary["固負_長期借入金"] = 10_000_000_000
        totals = {"NonCurrentLiabilities": 79_726_000_000}

        adjustments = reconcile_optional_duplicate_categories(summary, totals)

        self.assertEqual(summary["固負_契約負債"], 0)
        self.assertEqual(adjustments[0]["category"], "固負_契約負債")

    def test_current_contract_liability_is_removed_when_advances_are_the_presentation(self):
        summary = {key: 0 for key in DISPLAY_ORDER}
        summary["流負_支払手形・買掛金"] = 4_000_000_000
        summary["流負_前受金"] = 3_000_000_000
        summary["流負_契約負債"] = 2_000_000_000
        summary["流負_その他流動負債"] = 1_000_000_000
        totals = {"CurrentLiabilities": 8_000_000_000}

        adjustments = reconcile_optional_duplicate_categories(summary, totals)

        self.assertEqual(summary["流負_前受金"], 3_000_000_000)
        self.assertEqual(summary["流負_契約負債"], 0)
        self.assertEqual(adjustments[0]["category"], "流負_契約負債")

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
        summary["流動_電子記録債権"] = 10_979_000_000
        totals = {"CurrentAssets": 203_890_000_000}
        raw_tags = {"NotesReceivableAccountsReceivableFromCompletedConstructionContractsAndOtherCNS": 203_890_000_000}

        result = reconcile_receivable_presentation(summary, totals, raw_tags)

        self.assertEqual(result["selected"], "combined")
        self.assertTrue(result["combined_includes_contract_assets"])
        self.assertEqual(summary["流動_契約資産"], 0)
        self.assertEqual(summary["流動_電子記録債権"], 0)
        self.assertTrue(result["combined_includes_other_claims"])

    def test_combined_construction_receivable_keeps_independent_electronic_claims(self):
        summary = {key: 0 for key in DISPLAY_ORDER}
        summary["流動_受取手形・売掛金(合算)"] = 203_890_000_000
        summary["流動_電子記録債権"] = 10_979_000_000
        totals = {"CurrentAssets": 214_869_000_000}
        raw_tags = {
            "NotesReceivableAccountsReceivableFromCompletedConstructionContractsAndOtherCNS": 203_890_000_000
        }

        result = reconcile_receivable_presentation(summary, totals, raw_tags)

        self.assertEqual(result["selected"], "combined")
        self.assertEqual(summary["流動_電子記録債権"], 10_979_000_000)
        self.assertFalse(result["combined_includes_other_claims"])

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
        self.assertEqual(len(BREADTH_100), 100)
        self.assertFalse(set(MARKET_100) & set(BREADTH_100))
        self.assertEqual(len(MARKET_100), 100)
        self.assertEqual(len(MARKET_200), 200)
        self.assertEqual(len(STRESS_100), 100)
        self.assertFalse(set(MARKET_200) & set(STRESS_100))
        self.assertEqual(len(MARKET_300), 300)
        self.assertEqual(len(WAVE_A_100), 100)
        self.assertEqual(len(WAVE_B_100), 100)
        self.assertFalse(set(MARKET_300) & set(WAVE_A_100))
        self.assertFalse(set(MARKET_300) & set(WAVE_B_100))
        self.assertFalse(set(WAVE_A_100) & set(WAVE_B_100))
        self.assertEqual(len(MARKET_500), 500)
        self.assertEqual(BS_TEST_SETS["breadth-100"], BREADTH_100)
        self.assertEqual(BS_TEST_SETS["stress-100"], STRESS_100)
        self.assertEqual(BS_TEST_SETS["market-100"], MARKET_100)
        self.assertEqual(BS_TEST_SETS["market-200"], MARKET_200)
        self.assertEqual(BS_TEST_SETS["market-300"], MARKET_300)
        self.assertEqual(BS_TEST_SETS["wave-a-100"], WAVE_A_100)
        self.assertEqual(BS_TEST_SETS["wave-b-100"], WAVE_B_100)
        self.assertEqual(BS_TEST_SETS["market-500"], MARKET_500)

    def test_alphanumeric_security_codes_are_accepted(self):
        self.assertEqual(parse_codes_arg("456a, 442A, 9366"), ["442A", "456A", "9366"])

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
                "mapping_candidate_unmapped_tags_over_1oku": [
                    {"tag": "SpecialAsset", "value_oku": -120.0},
                ],
            },
            {
                "_path": "debug_bs_2222.json",
                "code": "2222",
                "status": "ok",
                "doc_type": "IFRS",
                "selected_context": "CurrentYearInstant_NonConsolidatedMember",
                "warnings": ["warning"],
                "other_gap_delta_oku": {"流負_その他流動負債": 10.0},
                "mapping_candidate_unmapped_tags_over_1oku": [
                    {"tag": "SpecialAsset", "value_oku": 80.0},
                ],
            },
        ]

        summary = summarize_diagnostics(records)

        self.assertEqual(summary["max_abs_residual_oku"], 1400.0)
        self.assertEqual(summary["rows"][0]["code"], "1111")
        self.assertEqual(summary["threshold_counts"]["over_1000_oku"], 1)
        self.assertEqual(summary["warning_count"], 1)
        self.assertEqual(summary["candidate_unmapped_tags"][0]["tag"], "SpecialAsset")
        self.assertEqual(summary["candidate_unmapped_tags"][0]["company_count"], 2)
        self.assertEqual(summary["candidate_unmapped_tags"][0]["total_abs_value_oku"], 200.0)


if __name__ == "__main__":
    unittest.main()

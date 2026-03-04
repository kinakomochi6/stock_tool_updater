"""
B/S データ精度テストスクリプト
- J-GAAP: 7974(任天堂), 6501(日立), 9366(サンリツ)
- IFRS: 7203(トヨタ), 6758(ソニー), 3402(東レ)
- US GAAP: 8591(オリックス)
"""
import sys, os, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from firebase_master_test import EdinetSearcher, analyze_bs_xbrl, DISPLAY_ORDER, TAG_MAPPING

# J-GAAP と IFRS・US GAAP 混在でテスト
TEST_CODES = ['7974', '6501', '7203', '6758', '8591']

searcher = EdinetSearcher()
searcher.fetch_list(TEST_CODES, days_back=365)

def check_balance(code, summary, totals, doc_type):
    """貸借対照表の整合性チェック"""
    print(f"\n{'='*60}")
    print(f"  {code}  DocType: {doc_type}")
    print(f"  総資産: {totals['Assets']/1e8:,.1f}億  流動資産: {totals['CurrentAssets']/1e8:,.1f}億  非流動: {totals['NonCurrentAssets']/1e8:,.1f}億")
    print(f"  負債合計: {totals['Liabilities']/1e8:,.1f}億  純資産: {totals['NetAssets']/1e8:,.1f}億")
    print(f"{'='*60}")

    # 「その他」系の異常マイナス検出（自己株式・貸倒引当金を除く）
    ok = True
    for k, v in summary.items():
        if v < -500_000_000 and "自己株式" not in k and "貸倒引当" not in k:
            print(f"  ❌ 大きなマイナス: {k}: {v/1e8:,.2f}億")
            ok = False

    # 有価証券の取得確認
    sec_val = summary.get("流動_有価証券", 0)
    inv_sec_val = summary.get("投資_投資有価証券", 0)
    print(f"  流動_有価証券: {sec_val/1e8:,.2f}億  投資_投資有価証券: {inv_sec_val/1e8:,.2f}億")

    # 流動資産合算チェック
    ca_sum = sum(summary[k] for k in summary if k.startswith("流動_"))
    ca_diff = abs(ca_sum - totals['CurrentAssets'])
    print(f"  流動資産合計(計算): {ca_sum/1e8:,.1f}億  (XBRL合計): {totals['CurrentAssets']/1e8:,.1f}億  差: {ca_diff/1e8:,.1f}億")

    # 純資産チェック
    ne_sum = sum(summary[k] for k in summary if k.startswith("純資_"))
    ne_diff = abs(ne_sum - totals['NetAssets'])
    print(f"  純資産合計(計算): {ne_sum/1e8:,.1f}億  (XBRL合計): {totals['NetAssets']/1e8:,.1f}億  差: {ne_diff/1e8:,.1f}億")

    if ok:
        print(f"  ✅ 異常マイナスなし")

    # 取得済みの主要項目一覧（0円でないもの）
    print(f"\n  --- 取得値一覧 ---")
    for k in DISPLAY_ORDER:
        v = summary.get(k, 0)
        if v != 0:
            print(f"    {k}: {v/1e8:,.2f}億")


for code in TEST_CODES:
    doc_id, doc_desc, filer_name = searcher.find_best_bs_doc(code)
    print(f"\n>>> {code} {filer_name}  書類: {doc_desc}  DocID: {doc_id}")
    if not doc_id:
        print("  ❌ 書類なし")
        continue
    ret = analyze_bs_xbrl(doc_id)
    if not ret:
        print("  ❌ 解析失敗")
        continue
    summary, totals, doc_type, raw_tags = ret
    check_balance(code, summary, totals, doc_type)

    # TAG_MAPPING未カバーのXBRLタグで値が取れているものを表示（情報収集）
    unmapped = {t: v for t, v in raw_tags.items()
                if t not in TAG_MAPPING and abs(v) > 100_000_000
                and t not in ["Assets","Liabilities","NetAssets","CurrentAssets","NoncurrentAssets",
                               "CurrentLiabilities","NoncurrentLiabilities","AssetsIFRS","EquityIFRS",
                               "LiabilitiesIFRS","CurrentAssetsIFRS","NonCurrentAssetsIFRS",
                               "CurrentLiabilitiesIFRS","NonCurrentLiabilitiesIFRS","TotalCurrentAssetsIFRS",
                               "TotalNonCurrentAssetsIFRS","TotalCurrentLiabilitiesIFRS",
                               "TotalNonCurrentLiabilitiesIFRS","TotalAssetsIFRSSummaryOfBusinessResults",
                               "TotalLiabilitiesIFRSSummaryOfBusinessResults","TotalEquityIFRSSummaryOfBusinessResults",
                               "TotalAssetsUSGAAPSummaryOfBusinessResults","TotalLiabilitiesUSGAAPSummaryOfBusinessResults"]}
    if unmapped:
        print(f"\n  ⚠️ TAG_MAPPING未登録で億円超の値があるタグ:")
        for t, v in sorted(unmapped.items(), key=lambda x: -abs(x[1])):
            print(f"    {t}: {v/1e8:,.2f}億")

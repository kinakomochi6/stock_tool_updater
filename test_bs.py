import sys
import os
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from firebase_master_test import EdinetSearcher, analyze_bs_xbrl

codes = ['9366', '6734', '3123']
searcher = EdinetSearcher()
searcher.fetch_list(codes, days_back=365)

for code in codes:
    doc_id, doc_desc, filer_name = searcher.find_best_bs_doc(code)
    print(f"\n--- {code} {filer_name} ({doc_desc}) DocID: {doc_id} ---")
    if not doc_id: continue
    
    summary, totals, doc_type, raw_tags = analyze_bs_xbrl(doc_id)
    print(f"DocType: {doc_type}")
    print(f"Totals: {totals}")
    
    has_negative = False
    for k, v in summary.items():
        if v < -1000000000: # 10億円以上の大きなマイナスのみ報告(自己株式のぞく)
            if "自己株式" not in k and "貸倒引当" not in k:
                print(f"  NEGATIVE: {k}: {v:,}")
                has_negative = True
        elif v < 0: # 10億円未満
             if "自己株式" not in k and "貸倒引当" not in k:
                print(f"  minor NEGATIVE: {k}: {v:,}")
                has_negative = True
                
    if not has_negative:
        print("  => OK (No abnormal negative values)")
        
    for k in ["流動_その他流動資産", "投資_その他固定資産", "流負_その他流動負債", "固負_その他固定負債", "純資_その他純資産"]:
        if summary[k] != 0:
            print(f"  {k}: {summary[k]:,}")

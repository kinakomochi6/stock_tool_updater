import sys
import os
sys.path.append(os.getcwd())
from firebase_master_test import EdinetSearcher, analyze_bs_xbrl

searcher = EdinetSearcher()
searcher.fetch_list([7203], 365)
did, desc, name = searcher.find_best_bs_doc(7203)
print("DOC:", did, desc)
ret = analyze_bs_xbrl(did)
print("EXTRACTED TOTALS:", ret[1])

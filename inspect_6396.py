import requests
import zipfile
import io
from bs4 import BeautifulSoup
import re

EDINET_API_KEY = '4fa7200f623d43b0b9fd815cc4a2c0bf'
doc_id = "S100W3TZ"
url = f"https://disclosure.edinet-fsa.go.jp/api/v2/documents/{doc_id}"
params = {"type": 1, "Subscription-Key": EDINET_API_KEY}
res = requests.get(url, params=params)
z_data = io.BytesIO(res.content)
with zipfile.ZipFile(z_data) as z:
    xbrl_file = next((n for n in z.namelist() if n.endswith(".xbrl") and "PublicDoc" in n), None)
    with z.open(xbrl_file) as f:
        soup = BeautifulSoup(f, 'lxml-xml')
        for el in soup.find_all():
            tag = el.name.split(':')[-1]
            if tag in ['Assets', 'CashAndDeposits', 'CurrentAssets']:
                print(f"Tag: {el.name}, Value: {el.text.strip()}, Context: {el.get('contextRef')}")

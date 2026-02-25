import requests
import zipfile
import io
from bs4 import BeautifulSoup
import unicodedata

EDINET_API_KEY = '4fa7200f623d43b0b9fd815cc4a2c0bf'

def main():
    doc_id = "S100W4I2"
    url = f"https://disclosure.edinet-fsa.go.jp/api/v2/documents/{doc_id}"
    params = {"type": 1, "Subscription-Key": EDINET_API_KEY}
    res = requests.get(url, params=params, timeout=10)
    z_data = io.BytesIO(res.content)
    with zipfile.ZipFile(z_data) as z:
        html_files = [n for n in z.namelist() if n.endswith(".htm") and "PublicDoc" in n]
        for h_file in html_files:
            with z.open(h_file) as f:
                content = f.read()
                try:
                    content_str = content.decode('utf-8-sig')
                except:
                    content_str = content.decode('cp932', errors='replace')
                if "取得原価" in content_str or "取得価額" in content_str or "z" in content_str:
                    print(f"File: {h_file}")
                    soup = BeautifulSoup(content_str, 'lxml')
                    for tbl in soup.find_all('table'):
                        if "取得" in tbl.get_text() or "z" in tbl.get_text():
                             print("--- TABLE START ---")
                             print(tbl.get_text().encode('cp932', 'replace').decode('cp932')[:1000])
                             print("--- TABLE END ---")

if __name__ == "__main__":
    main()

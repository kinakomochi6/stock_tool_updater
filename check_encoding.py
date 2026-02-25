import requests
import zipfile
import io

EDINET_API_KEY = '4fa7200f623d43b0b9fd815cc4a2c0bf'
doc_id = "S100W4I2"
url = f"https://disclosure.edinet-fsa.go.jp/api/v2/documents/{doc_id}"
params = {"type": 1, "Subscription-Key": EDINET_API_KEY}
res = requests.get(url, params=params)
z_data = io.BytesIO(res.content)
with zipfile.ZipFile(z_data) as z:
    html_files = [n for n in z.namelist() if n.endswith(".htm") and "PublicDoc" in n]
    for h_file in html_files:
        with z.open(h_file) as f:
            content = f.read()
            # '取得' in UTF-8
            if b'\xe5\x8f\x96\xe5\xbe\x97' in content or b'\x8e\xe6\x93\xde' in content: 
                print(f"File: {h_file}")
                print(f"Sample raw: {content[:200]}")
                # Try to decode
                try: 
                    print("Decoded UTF-8: " + content[:200].decode('utf-8'))
                except:
                    try:
                        print("Decoded CP932: " + content[:200].decode('cp932'))
                    except:
                        pass
                break

import requests
import datetime
EDINET_API_KEY = '4fa7200f623d43b0b9fd815cc4a2c0bf'
code = '6396'
url = "https://disclosure.edinet-fsa.go.jp/api/v2/documents.json"
start_date = datetime.date(2025, 7, 1)
for i in range(30):
    target_date = start_date - datetime.timedelta(days=i)
    params = {"date": target_date.strftime('%Y-%m-%d'), "type": 2, "Subscription-Key": EDINET_API_KEY}
    res = requests.get(url, params=params)
    if res.status_code == 200:
        js = res.json()
        for item in js.get("results", []):
            if str(item.get('secCode', ''))[:4] == code:
                print(f"Date: {target_date}, DocID: {item['docID']}, Type: {item['docTypeCode']}, Desc: {item['docDescription']}")

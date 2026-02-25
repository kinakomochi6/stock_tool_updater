import pandas as pd
import requests
import io

url = "https://www.jpx.co.jp/markets/statistics-equities/misc/tvdivq0000001vg2-att/data_j.xls"
res = requests.get(url)
df = pd.read_excel(io.BytesIO(res.content))

with open("jpx_cols.txt", "w", encoding="utf-8") as f:
    for col in df.columns:
        f.write(f"Col: {col}\n")
    for cat in df['市場・商品区分'].unique():
        f.write(f"Cat: {cat}\n")
    f.write("\nSample:\n")
    for i, row in df.head(10).iterrows():
        f.write(f"{row['コード']} - {row['銘柄名']} - {row['市場・商品区分']}\n")

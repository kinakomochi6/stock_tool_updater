import pandas as pd
import firebase_admin
from firebase_admin import credentials, firestore

# ==========================================
# ★設定エリア
# ==========================================
# ダウンロードしたFirebaseのJSONキーのファイル名を指定
FIREBASE_KEY = 'firebase_key.json' 
# ==========================================

def initialize_firebase():
    """Firebaseの初期化"""
    print("Firebaseに接続中...")
    # すでに初期化されている場合は再初期化しない（Jupyter等のエラー防止）
    if not firebase_admin._apps:
        cred = credentials.Certificate(FIREBASE_KEY)
        firebase_admin.initialize_app(cred)
    return firestore.client()

def fetch_jpx_stock_list():
    """JPX公式から上場銘柄リストを取得"""
    print("JPX公式から銘柄リストを取得中...")
    url = "https://www.jpx.co.jp/markets/statistics-equities/misc/tvdivq0000001vg2-att/data_j.xls"
    
    # ★修正箇所：コード列を最初から「文字列(str)」として読み込む
    df = pd.read_excel(url, dtype={'コード': str})
    
    # プライム・スタンダード・グロース市場の普通株式のみを抽出
    df = df[df['市場・商品区分'].str.contains('プライム|スタンダード|グロース', na=False)]
    
    stock_list = []
    for index, row in df.iterrows():
        stock_list.append({
            'code': row['コード'].strip(), # そのまま文字列として扱う
            'name': row['銘柄名'],
            'market': row['市場・商品区分'],
            'industry': row['33業種区分']
        })
    
    print(f"取得完了: {len(stock_list)}件の上場企業が見つかりました。")
    return stock_list

def main():
    # 1. Firebase接続
    db = initialize_firebase()
    
    # 2. 銘柄リスト取得
    stock_list = fetch_jpx_stock_list()
    
    # 3. Firebaseへ保存（テストとして最初の10件のみ）
    test_target = stock_list[:10]
    print(f"\nテストとして最初の {len(test_target)} 件をFirestoreに保存します...")
    
    # 'companies' というコレクション（フォルダ）に保存
    collection_ref = db.collection('companies')
    
    for stock in test_target:
        code = stock['code']
        # Firebaseに保存するデータの中身
        data = {
            "企業名": stock['name'],
            "市場": stock['market'],
            "業種": stock['industry'],
            "更新日時": firestore.SERVER_TIMESTAMP # 保存した時刻を自動記録
        }
        
        # ドキュメントIDを「銘柄コード」にしてデータをセット（上書き保存）
        collection_ref.document(code).set(data, merge=True)
        print(f"[{code}] {stock['name']} のデータを保存しました。")
        
    print("\nすべての保存が完了しました！Firebaseコンソールを確認してみてください。")

if __name__ == "__main__":
    main()
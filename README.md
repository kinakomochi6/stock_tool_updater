# stock_tool_updater

Firestore の `companies` コレクションを更新する株価・財務データ取得バッチです。

## 主な処理

- JPX 公式Excelから上場銘柄一覧を取得
- EDINET APIから有価証券報告書・四半期報告書を検索
- XBRLからB/S項目を抽出
- 有価証券報告書HTMLから不動産・有価証券の含み益を抽出
- yfinance、みんかぶ、Yahoo Finance Japanから株価・指標を補完
- Firestore `companies/{証券コード}` に保存

## 必要な環境変数

```bash
EDINET_API_KEY=...
FIREBASE_CREDENTIALS='{"type":"service_account",...}'
```

ローカルでは `FIREBASE_CREDENTIALS` の代わりに `firebase_key.json` を置くこともできます。
別パスを使う場合は `FIREBASE_KEY_PATH` を指定してください。

```bash
FIREBASE_KEY_PATH=path/to/firebase_key.json
```

## セットアップ

```bash
python -m pip install -r requirements.txt
```

## 実行方法

全銘柄を1プロセスで更新:

```bash
python firebase_master_test.py
```

GitHub Actionsと同じ8分割更新:

```bash
python firebase_master_test.py --total-shards 8 --shard-index 0
```

特定銘柄だけ更新:

```bash
python firebase_master_test.py --codes 7203
python firebase_master_test.py --codes 7203,6758
```

EDINETの検索日数を短くする:

```bash
python firebase_master_test.py --codes 7203 --days-back 90
```

B/S抽出の診断JSONを出力する:

```bash
python firebase_master_test.py --codes 7203 --debug-bs --debug-dir diagnostics
```

Firestoreへ保存せずに診断だけ実行する:

```bash
python firebase_master_test.py --codes 9366,3123 --debug-bs --debug-dir diagnostics --dry-run
```

診断JSONには、採用されたcontext、contextごとのスコア、重複タグ、採用タグ、除外タグ、合計との差額、その他タグとの差額、1億円以上の未マッピング数値タグ、B/S警告が出力されます。

## GitHub Actions

`.github/workflows/update_stock_data.yml` が毎日 15:00 UTC、日本時間の深夜0時に8分割で実行します。
手動実行も可能です。`codes` を空にすると通常の8分割更新、`9366,3123` のように指定すると指定銘柄だけを実行します。
精度確認では `debug_bs=true`、`dry_run=true` にするとFirestoreへ保存せず、B/S診断JSONをartifactからダウンロードできます。

Actions画面で9366/3123を診断する場合は、各入力欄に以下のように入れてください。

```text
codes      9366,3123
days_back  365
debug_bs   true
dry_run    true
```

GitHub Secretsには以下を設定してください。

- `EDINET_API_KEY`
- `FIREBASE_CREDENTIALS`

## 注意

`firebase_key.json`、`.env`、ログ、デバッグファイルはGitに入れないでください。
Vercel版アプリは、このバッチが保存したFirestoreデータを読み込んで表示します。

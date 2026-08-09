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

診断JSONには、採用されたcontext、contextごとのスコア、重複タグ、採用タグ、除外タグ、合計との差額、その他タグとの差額、1億円以上の未マッピング数値タグ、B/S警告、品質判定が出力されます。

未知の企業拡張タグについては、XBRLパッケージ内のPresentation Linkbase（表示上の親子関係）とCalculation Linkbase（加減算関係）を解析します。既知の親科目から分類候補を作り、選択contextの連結・単体区分と一致し、かつB/S区分合計の残差を大きく改善する場合だけ補完分類として採用します。辞書に明示されたタグは常に構造推論より優先されます。

## B/Sの保存安全策

B/S解析結果は次の3段階で判定します。

- `verified`: 未分類残差が1億円以下で、主要合計にも大きな不整合がない
- `partial`: 未分類残差が1億円超10億円以下など、利用可能だが注意が必要
- `quarantined`: 未分類残差が10億円超、比率10%超、主要合計の欠落、または大きな貸借不一致がある

明示的な「その他」タグがない場合、1億円以下の端数だけを「その他」に自動補完します。それを超える差額は `B/S_未分類残差_億` に分離します。`quarantined` の解析結果はB/S項目をFirestoreへ書き込まず、直前の正常値を保持します。判定状態、理由、検証書類、未分類残差、検証日時は別フィールドへ保存されます。

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

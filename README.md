# CLEAR

**C**ashflow, **L**oans, **E**xpenses, **A**ssets & **R**epayment

借入の返済と毎月の家計の見通しを管理するデスクトップアプリです。
Payback Management 3.x（Personal Finance Manager Pro）の後継版です。

- 版: 4.0.0
- 開発: Yu ZHU
- ライセンス: Apache License 2.0
- English summary: [below](#english)

## できること

- **返済の記録（台帳）**: 支払った額と日付を記録し、利息と元金に分けて残高を更新します。記録はあとから取り消せます。
- **月次締め**: 月が変わったら、先月の支払いの確認 → 貯蓄の繰り越し → 確定、の3ステップで締めます。未払いの借入には、その月の利息を残高に加えます。締める前に自動でバックアップを作り、取り消しもできます。
- **完済の見通し**: 借入ごとに完済予定の年月と残りの利息を表示します。返済額が利息以下（利息割れ）の借入は警告します。
- **ホーム**: 総負債・今月の支払い・今月の残り・完済予定の4つの数字、期日順の「今月の支払い」チェックリスト、注意すべきこと、負債と貯蓄の推移グラフ。
- **4通貨**: JPY・USD・CNY・SGD。表示通貨はヘッダーで切り替え、すべての画面に効きます。為替レートは起動時に1日1回、自動で更新します（手入力も可）。
- **データを安全に**: データファイルはアプリのフォルダの外に置き、起動時（1日1回）・月次締めの前・復元の前に自動でバックアップを作ります（直近30個）。
- **表示**: ライト・ダーク・システムに合わせる、のテーマ。日本語と英語。

## 動作環境

- Python 3.10 以上（3.10 と 3.13 で動作を確認）
- macOS または Windows
- ライブラリ: PyQt6、qtawesome、requests

## 起動のしかた

```bash
cd "<このフォルダ>"
python3 -m pip install -r requirements.txt   # 初回だけ
python3 launch.py
```

Windows では `python3` を `py` に読み替えてください。

Homebrew の Python などで `externally-managed-environment` と表示されて入れられない場合は、
Google ドライブの外に仮想環境を作ってください（ドライブの中に作ると大量のファイルが同期されます）。

```bash
python3 -m venv ~/.venvs/clear
~/.venvs/clear/bin/python -m pip install -r requirements.txt
~/.venvs/clear/bin/python launch.py
```

## 初めて起動したとき

「CLEAR へようこそ」の画面で、次の2つを決めます。

1. **データの保存場所**: アプリを `App Development` フォルダの中から起動した場合、初期値は
   `App Development/AppData/CLEAR` です。それ以外の場所では `書類（Documents）/CLEAR` になります。
   あとから「データ・設定」で変更できます（今のファイルを新しい場所にコピーするかも選べます）。
2. **使うデータ**: 旧版（Payback Management 3.x）の `save` フォルダにある .db が見つかれば一覧に出ます。
   チェックしたファイルは保存場所に**コピーして**取り込みます。元のファイルは変更しません。
   旧版のデータがなければ、新しいデータファイルを作ります。

旧版のデータを取り込むと、旧版で最後に使っていた月より後の月は「締めが必要な月」になります。
画面上部の案内から月次締めを行ってください。

## 毎月の使い方

1. 支払ったら記録する
   - 借入: 「借入・カード」で行を選び「支払を記録」。支払額と日付、うち利息を確認して記録します。
   - 生活費: 「毎月の収支」の生活費の表で「今月」にチェック。
   - ホームの「今月の支払い」チェックリストからも記録できます。
2. 月が変わったら締める
   - ヘッダーの「月次締め」から始めます。チェックした支払いを記録し、チェックしなかった借入には利息を加え、
     月末の貯蓄残高を確定します（銀行の残高がわかればその金額に直せます）。
   - 試算用のファイルなどは「残高を変えずにまとめて締める」も選べます。
   - 締めは「データ・設定」の「直前の締めを取り消す」で戻せます。
3. 見通しを確認する
   - 「計画」で、最大24か月先までの収入・返済・生活費・貯蓄・負債残高を月ごとに確認できます。

## データの置き場所

```
<データの保存場所>/
├── *.db                    データファイル（目的別に複数持てます）
├── backups/<ファイル名>/    自動バックアップ（ファイルごとに直近30個）
└── logs/clear.log          ログ
```

- アプリの設定（テーマ・言語・表示通貨・前回のファイルなど）は、パソコンごとの設定フォルダに保存します。
  macOS: `~/Library/Application Support/CLEAR/config.json`、Windows: `%LOCALAPPDATA%\CLEAR\config.json`
- データファイルの形式は SQLite です。形式の版をファイルの中に記録しており、旧版の形式は取り込むときに新しい形式へ移行します。
  旧版のファイルを直接開こうとした場合も、取り込み（コピー）を案内します。
- 為替レートは [ExchangeRate-API](https://www.exchangerate-api.com/) から取得します（通信するのはこれだけです）。

## 開発

```bash
python3 -m pip install -r requirements-dev.txt
python3 -m pytest
```

| 場所 | 役割 |
| --- | --- |
| `launch.py` | 起動スクリプト |
| `clear/engine.py` | 計算エンジン（返済予定・完済・月次締め・見通し）。画面に依存せず、テストで検算します |
| `clear/db.py`, `clear/repo.py` | SQLite の読み書き、旧版からの移行 |
| `clear/store.py` | 画面とデータの橋渡し（ファイル・為替・バックアップ） |
| `clear/page_*.py` | 5つの画面（ホーム・借入とカード・毎月の収支・計画・データと設定） |
| `clear/dialogs.py`, `clear/close_wizard.py`, `clear/welcome.py` | 入力画面・月次締め・初回起動 |
| `clear/i18n.py`, `clear/theme.py` | 表示の文言（日本語・英語）、テーマ |
| `tests/` | pytest（架空のデータだけを使います） |

個人のデータ（.db、バックアップ、ログ）はリポジトリに含めません（`.gitignore` で除外）。

## これからの予定

- **4.1**: 残高合わせ、借入とカードの紐づけ、年会費、期限通知（土日祝の補正）、生活費の頻度、表の並べ替え・検索、ショートカットと取り消し
- **4.2**: 返済戦略の比較、シナリオ（試算）モード、最大120か月の試算、収入の年間予定、資金繰りカレンダー、CSV・Excel 書き出し、ワンクリック起動、起動ロック

変更の記録は [CHANGELOG.md](CHANGELOG.md) にあります。

---

## English

CLEAR is a desktop app (PyQt6) for tracking loan repayments and the monthly household budget.
It succeeds Payback Management 3.x.

- **Payment ledger** – record what you paid; each payment is split into interest and principal.
- **Month-end close** – a three-step wizard confirms last month's payments, adds a month's interest to
  unpaid debts and carries savings over. A backup is taken first and the close can be undone.
- **Payoff outlook** per debt, with a warning when a payment does not cover the interest.
- **Home** with four key figures, this month's checklist, alerts and a debt/savings trend chart.
- **Four currencies** (JPY, USD, CNY, SGD) with one display currency for all pages; daily rate updates.
- **Safe data** – data files live outside the app folder; automatic backups (latest 30 per file).
- Light / dark / system theme; Japanese and English.

Requires Python 3.10+. Install with `python3 -m pip install -r requirements.txt` and start with
`python3 launch.py`. On first start, choose a data folder and optionally import Payback Management 3.x
files (they are copied; the originals are never changed). Run the tests with `python3 -m pytest`.

Licensed under the Apache License 2.0.

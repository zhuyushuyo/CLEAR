# CLEAR

**C**ashflow, **L**oans, **E**xpenses, **A**ssets & **R**epayment

借入の返済、毎月の家計、投資を合わせて、純資産の見通しを管理するデスクトップアプリです。
Payback Management 3.x（Personal Finance Manager Pro）の後継版です。

- 版: 4.1.1
- 開発: Yu ZHU
- ライセンス: Apache License 2.0
- English summary: [below](#english)

## できること

- **返済の記録（台帳）**: 支払った額と日付を記録し、利息と元金に分けて残高を更新します。記録はあとから取り消せます。
- **自動引き落とし**: 借入・生活費ごとに口座引き落としかどうかを設定できます。引き落とし日を過ぎた項目は赤い「超過」ではなく
  「記録待ち」と表示し、起動時にまとめて確認・記録できます。支払日が土日祝や年末年始なら、翌営業日を期日として数えます。
- **月次締め**: 月が変わったら、先月の支払いの確認 → 貯蓄の繰り越し → 確定、の3ステップで締めます。未払いの借入には、その月の利息を残高に加えます。締める前に自動でバックアップを作り、取り消しもできます。
- **完済の見通し**: 借入ごとに完済予定の年月と残りの利息を表示します。返済額が利息以下（利息割れ）の借入は警告します。
- **カードの年会費**: 請求月と支払った年月を記録し、「11,000 ✓ 支払済 2026年3月」のように一目で分かる形で表示します。次の請求月に自動で「未払い」に戻り、計画の見通しにも入ります。
- **投資**: 株・ETF、仮想通貨、貴金属（金・銀・プラチナ・パラジウム）、手入力の資産（投資信託・外貨預金など）を登録し、
  時価から評価額・損益・前日比を計算します。資産配分（種類別・口座別・通貨別）、売買と配当の記録（移動平均の取得単価）、
  毎月の積立、NISA の枠（今年の残り枠と生涯投資枠）も扱います。
- **純資産**: 貯蓄＋投資の評価額−負債を、ホームと計画に表示します。計画では積立と期待利回りから投資の評価額を月ごとに見通し、
  月次締めのたびに実績を記録して、見通しとの差をグラフで確かめられます。
- **ホーム**: 総負債・今月の支払い・今月の残り・純資産・完済予定の5つの数字、期日順の「今月の支払い」チェックリスト（年会費・積立を含む）、
  注意すべきこと、負債・貯蓄・投資の見通しと純資産の実績のグラフ。
- **4通貨**: JPY・USD・CNY・SGD。表示通貨はヘッダーで切り替え、すべての画面に効きます。
- **データを安全に**: データファイルはアプリのフォルダの外に置き、起動時（1日1回）・月次締めの前・復元の前・形式の移行の前に自動でバックアップを作ります（直近30個）。
- **表示**: ライト・ダーク・システムに合わせる、のテーマ。日本語と英語。専用のアイコン（ウィンドウ・Dock・タスクバー）。

## 動作環境

- Python 3.10 以上（3.10 と 3.13 で動作を確認）
- macOS または Windows
- ライブラリ: PyQt6、qtawesome、requests、yfinance、jpholiday

yfinance がなくてもアプリは動きます。その場合は、株・貴金属・為替の価格を Yahoo Finance から直接取得します。
jpholiday がない場合は、土日と年末年始だけを銀行の休業日として数えます。

## 起動のしかた

```bash
cd "<このフォルダ>"
python3 -m pip install -r requirements.txt   # 初回と、版を上げたとき
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

## 4.0.0 からの更新

- 4.1.0 で 4.0.0 のデータファイルを初めて開くと、**バックアップを作ってから**新しい形式に移行します（理由「形式の移行前」）。
  移行したファイルは 4.0.0 では開けません。4.0.0 に戻すときは、「データ・設定」のバックアップから移行前の状態を復元してください。
- 借入は、「個人からの借入」以外を口座引き落としとして引き継ぎます。編集画面でいつでも変えられます。
- 4.0.0 で年会費を支払済にしていたカードは「2026年に支払済」として引き継ぎます。各カードの編集画面で、年会費の請求月を一度入れてください。
- 表の列の表示と幅の設定は、新しい列の並びに合わせて引き継ぎます。

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
     編集画面で残高を減らした場合は、その差を今月の支払として記録するか聞きます（利息と元金は自動で分け、二重に引きません）。
   - 自動引き落とし: 引き落とし日を過ぎると、起動時と画面上部の案内から「確認して記録」でまとめて記録できます。
   - 生活費: 「毎月の収支」の生活費の表で「今月」にチェック。
   - 年会費・積立: 請求月・積立日には、ホームの「今月の支払い」に並びます。チェックで支払済・積立済になります。
   - ホームの「今月の支払い」チェックリストからも記録できます。
2. 月が変わったら締める
   - ヘッダーの「月次締め」から始めます。チェックした支払いを記録し、チェックしなかった借入には利息を加え、
     月末の貯蓄残高を確定します（銀行の残高がわかればその金額に直せます）。締めた月の純資産も記録します。
   - 試算用のファイルなどは「残高を変えずにまとめて締める」も選べます。
   - 締めは「データ・設定」の「直前の締めを取り消す」で戻せます。
3. 見通しを確認する
   - 「計画」で、最大24か月先までの収入・返済・生活費・積立・貯蓄・投資の評価額・負債・純資産を月ごとに確認できます。
   - 「投資」の「設定」で、種類ごとの期待利回り（年率、初期値 0%）を変えられます。

## 投資のページ

| 種類 | 登録のしかた | 価格の取得元（取れないときは右へ） |
| --- | --- | --- |
| 株・ETF | 日本株は `7203`（自動で `7203.T` に）、米国株・ETF は `AAPL` や `VOO`。「検索」で名前からも探せます。数量は株数（整数） | yfinance → Yahoo Finance を直接 |
| 仮想通貨 | `bitcoin` のような CoinGecko の ID。`BTC` のようなティッカーでも登録できます。数量は小数点以下8桁まで | CoinGecko → Coinbase → bitFlyer（任意で bitFlyer だけも可） |
| 貴金属 | 金・銀・プラチナ・パラジウムを、グラム・トロイオンス・キログラムで | ニューヨーク先物（yfinance → Yahoo Finance を直接）。店頭価格との差は補正率（%）で調整 |
| 手入力の資産 | 投資信託・外貨預金など。今の評価額を手で入れます | 手入力 |

- 為替は Yahoo Finance から取り、取れないときは ExchangeRate-API を使います。
- 価格と為替は、起動時と「価格を更新」でまとめて取得します（間隔は最短15分）。取れなかったときは最後に取れた値を使い、7日より古ければ注意に出します。
  取れなかった理由（回数制限・接続できない・見つからない銘柄）は、銘柄名つきで表示します。
- 価格はどれもリアルタイムではなく、参考値です。yfinance は Yahoo Finance の非公式ライブラリで、データは個人利用が前提です。
- CoinGecko はキーなしで使えます。取得が不安定なときは、無料の Demo キーを「設定」に入れてください。
- 積立は銘柄ごとに「毎月◯円・◯日・口座から／カード払い」を設定します。積立を記録すると、最新の価格で買える数量を計算します（株は1株単位で、積立額で買える分だけ）。

## データの置き場所

```
<データの保存場所>/
├── *.db                    データファイル（目的別に複数持てます）
├── backups/<ファイル名>/    自動バックアップ（ファイルごとに直近30個）
└── logs/clear.log          ログ
```

- アプリの設定（テーマ・言語・表示通貨・前回のファイル・表の列など）は、パソコンごとの設定フォルダに保存します。
  macOS: `~/Library/Application Support/CLEAR/config.json`、Windows: `%LOCALAPPDATA%\CLEAR\config.json`
- データファイルの形式は SQLite です。形式の版をファイルの中に記録しており、古い形式は開くときに新しい形式へ移行します。
  旧版（Payback Management）のファイルを直接開こうとした場合は、取り込み（コピー）を案内します。
- 通信するのは次の取得元だけです: 為替は Yahoo Finance と [ExchangeRate-API](https://www.exchangerate-api.com/)（予備）、
  株・貴金属は Yahoo Finance、仮想通貨は [CoinGecko](https://www.coingecko.com/)、[Coinbase](https://www.coinbase.com/)（予備）、
  [bitFlyer](https://bitflyer.com/)（予備、または選んだ場合）。送るのは銘柄のコードだけで、残高などの個人のデータは送りません。

## 開発

```bash
python3 -m pip install -r requirements-dev.txt
python3 -m pytest
```

| 場所 | 役割 |
| --- | --- |
| `launch.py` | 起動スクリプト |
| `clear/engine.py` | 計算エンジン（返済予定・完済・年会費・期日・月次締め・見通し）。画面に依存せず、テストで検算します |
| `clear/invest.py` | 投資の評価・売買・NISA の枠 |
| `clear/market.py` | 価格と為替の取得（取得元ごとの予備つき: yfinance・Yahoo Finance・ExchangeRate-API・CoinGecko・Coinbase・bitFlyer） |
| `clear/jpcal.py` | 銀行の営業日（土日祝・年末年始） |
| `clear/db.py`, `clear/repo.py` | SQLite の読み書き、旧版からの移行 |
| `clear/store.py` | 画面とデータの橋渡し（ファイル・為替・価格・バックアップ） |
| `clear/page_*.py` | 6つの画面（ホーム・借入とカード・毎月の収支・投資・計画・データと設定） |
| `clear/dialogs.py`, `clear/dialogs_invest.py`, `clear/close_wizard.py`, `clear/welcome.py` | 入力画面・月次締め・初回起動 |
| `clear/i18n.py`, `clear/theme.py` | 表示の文言（日本語・英語）、テーマ |
| `clear/assets/` | アイコン（SVG が元。`scripts/make_icons.py` で PNG・ICO・ICNS を作ります） |
| `tests/` | pytest（架空のデータだけを使い、通信もしません） |

個人のデータ（.db、バックアップ、ログ）はリポジトリに含めません（`.gitignore` で除外）。

## これからの予定

- **4.2**: 残高合わせ、借入とカードの紐づけ、生活費の頻度、表の並べ替え・検索、ショートカットと取り消し、
  配当を収入に、生活防衛資金の目安、借入の金利と投資の利回りの比較、証券口座の CSV 取り込み、大きな値動きの注意
- **4.3**: 返済戦略の比較、シナリオ（試算）モード、最大120か月の試算、収入の年間予定、資金繰りカレンダー、CSV・Excel 書き出し、ワンクリック起動、起動ロック

変更の記録は [CHANGELOG.md](CHANGELOG.md) にあります。

---

## English

CLEAR is a desktop app (PyQt6) for tracking loan repayments, the monthly household budget and investments,
with one net-worth outlook. It succeeds Payback Management 3.x.

- **Payment ledger** – record what you paid; each payment is split into interest and principal.
- **Automatic debits** – debts and living costs can be marked as taken from the bank. Past their date they show as
  "to record" (not overdue) and can be recorded in one go; dates falling on Japanese bank holidays move to the next business day.
- **Month-end close** – a three-step wizard confirms last month's payments, adds a month's interest to
  unpaid debts and carries savings over. A backup is taken first and the close can be undone.
- **Annual card fees** with a billing month; the paid mark resets every year and the fee is part of the plan.
- **Investments** – shares and ETFs, crypto-assets, precious metals and hand-valued assets, valued at market prices.
  Every kind of price has fallbacks: yfinance → Yahoo Finance directly (→ ExchangeRate-API for exchange rates);
  CoinGecko → Coinbase → bitFlyer. Allocation, trades with moving-average cost, monthly contributions and NISA limits.
- **Net worth** (savings + investments − debts) on Home and in the plan; the actual figure is recorded at each close.
- **Four currencies** (JPY, USD, CNY, SGD) with one display currency for all pages.
- **Safe data** – data files live outside the app folder; automatic backups (latest 30 per file).
- Light / dark / system theme; Japanese and English.

Requires Python 3.10+. Install with `python3 -m pip install -r requirements.txt` and start with
`python3 launch.py`. A CLEAR 4.0 data file is backed up and then upgraded the first time 4.1 opens it
(4.0 cannot open the upgraded file; restore the backup to go back). Prices are for reference only;
yfinance is unofficial and Yahoo Finance data is meant for personal use. Run the tests with `python3 -m pytest`.

Licensed under the Apache License 2.0.

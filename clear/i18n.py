"""Japanese / English text (U7). Japanese is the default.

Every visible string goes through ``t(key, **params)``. A test checks that each
key used in the source exists in both languages.
"""

from __future__ import annotations

from datetime import date, datetime

from .models import CATEGORY_KEYS
from .money import fmt_money
from .periods import Period

LANGUAGES = {"ja": "日本語", "en": "English"}
_lang = "ja"

_MONTHS_EN = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_WEEKDAYS_JA = "月火水木金土日"

S: dict[str, tuple[str, str]] = {
    # ---- shell ------------------------------------------------------------------------
    "brand.sub": ("返済と家計の見通し", "Debt & cash-flow planner"),
    "nav.home": ("ホーム", "Home"),
    "nav.debts": ("借入・カード", "Debts & cards"),
    "nav.monthly": ("毎月の収支", "Monthly"),
    "nav.plan": ("計画", "Plan"),
    "nav.data": ("データ・設定", "Data & settings"),
    "header.currency": ("表示通貨", "Currency"),
    "header.no_file": ("ファイルなし", "No file"),
    "header.open_other": ("ほかのファイルを開く…", "Open another file…"),
    "header.saved": ("保存済み {time}", "Saved {time}"),
    "header.close": ("月次締め", "Close month"),
    "header.close_tip_none": ("次の締めは {date} から行えます", "The next close is available from {date}"),
    "header.close_tip_due": ("{period} の締めが済んでいません", "{period} has not been closed"),
    "banner.close_due": ("{period} の締めがまだです。支払の記録と貯蓄の繰り越しをして、月を確定しましょう。",
                         "{period} is not closed yet. Record the payments and carry over your savings."),
    "banner.close_due_many": ("{first}〜{last} の {n} か月分の締めがまだです。古い月から順に締めます。",
                              "{n} months ({first}–{last}) are not closed yet. They are closed oldest first."),
    "banner.close_start": ("月次締めを始める", "Start month-end close"),
    "banner.no_db": ("データファイルが開かれていません。", "No data file is open."),
    "banner.no_db_action": ("ファイルを開く", "Open a file"),

    # ---- common ---------------------------------------------------------------------------
    "common.add": ("追加", "Add"),
    "common.edit": ("編集", "Edit"),
    "common.delete": ("削除", "Delete"),
    "common.cancel": ("キャンセル", "Cancel"),
    "common.save": ("保存", "Save"),
    "common.close": ("閉じる", "Close"),
    "common.back": ("戻る", "Back"),
    "common.next": ("次へ", "Next"),
    "common.ok": ("OK", "OK"),
    "common.error": ("エラー", "Error"),
    "common.confirm": ("確認", "Confirm"),
    "common.done": ("完了", "Done"),
    "common.select_row": ("先に行を選んでください", "Select a row first"),
    "common.paid": ("支払済", "Paid"),
    "common.unpaid": ("未払い", "Unpaid"),
    "common.today": ("今日", "today"),
    "common.in_days": ("あと{n}日", "in {n} d"),
    "common.overdue_days": ("{n}日超過", "{n} d overdue"),
    "common.yes": ("はい", "Yes"),
    "common.no": ("いいえ", "No"),
    "due.cell": ("{day}日 ・{rel}", "{day} · {rel}"),
    "due.cell_day": ("{day}日", "{day}"),

    # ---- codes ------------------------------------------------------------------------------
    "bt.card_loan": ("カードローン", "Card loan"),
    "bt.shopping revolving": ("ショッピングリボ", "Shopping revolving"),
    "bt.cash revolving": ("キャッシングリボ", "Cash revolving"),
    "bt.shopping credit": ("ショッピング一括", "Card bill (lump sum)"),
    "bt.other_loan": ("その他のローン", "Other loan"),
    "bt.borrow_from_people": ("個人からの借入", "Borrowed from people"),
    "bt.__cards__": ("カード（借入一覧外）", "Cards (not in debts)"),
    "pm.Cash": ("現金・口座", "Cash / bank"),
    "pm.Credit Card": ("クレジットカード", "Credit card"),
    "cat.Rent/Mortgage": ("家賃・住宅ローン", "Rent / mortgage"),
    "cat.Utilities": ("水道光熱費", "Utilities"),
    "cat.Food/Groceries": ("食費", "Food & groceries"),
    "cat.Transportation": ("交通費", "Transportation"),
    "cat.Communication": ("通信費", "Phone & internet"),
    "cat.Subscriptions": ("サブスクリプション", "Subscriptions"),
    "cat.Insurance": ("保険", "Insurance"),
    "cat.Healthcare": ("医療", "Healthcare"),
    "cat.Childcare": ("育児", "Childcare"),
    "cat.Education": ("教育", "Education"),
    "cat.Entertainment": ("娯楽", "Entertainment"),
    "cat.Clothing": ("衣類", "Clothing"),
    "cat.Personal Care": ("日用品・美容", "Personal care"),
    "cat.Household Supplies": ("家庭用品", "Household supplies"),
    "cat.Pet Care": ("ペット", "Pet care"),
    "cat.Car - Monthly Parking": ("車・駐車場", "Car – parking"),
    "cat.Car - Gasoline/Fuel": ("車・ガソリン", "Car – fuel"),
    "cat.Car - Maintenance/Taxes": ("車・整備と税", "Car – maintenance & tax"),
    "cat.Car - Insurance": ("車・保険", "Car – insurance"),
    "cat.Car - Loan Payment": ("車・ローン", "Car – loan"),
    "cat.Miscellaneous": ("その他", "Miscellaneous"),
    "reason.startup": ("起動時", "Start-up"),
    "reason.close": ("月次締めの前", "Before close"),
    "reason.manual": ("手動", "Manual"),
    "reason.import": ("取り込み時", "Import"),
    "reason.restore": ("復元の前", "Before restore"),
    "reason.undo-close": ("締めの取り消し前", "Before undo"),

    # ---- home -------------------------------------------------------------------------------------
    "home.kpi.debt": ("総負債", "Total debt"),
    "home.kpi.debt_sub": ("借入 {n}件", "Debts: {n}"),
    "home.kpi.debt_sub_cards": ("借入 {n}件 ・カード {cards}", "Debts: {n} · cards {cards}"),
    "home.kpi.month": ("今月の支払い", "Due this month"),
    "home.kpi.month_sub": ("支払済 {paid} ・残り {left}", "Paid {paid} · left {left}"),
    "home.kpi.left": ("今月の残り（見込み）", "Left this month (est.)"),
    "home.kpi.left_sub": ("貯蓄 {s} ＋ 収入 {i} − 支出 {o}", "Savings {s} + income {i} − out {o}"),
    "home.kpi.payoff": ("完済予定", "Debt-free"),
    "home.kpi.payoff_sub": ("あと{n}か月 ・残り利息 {interest}", "{n} months · interest left {interest}"),
    "home.kpi.payoff_never": ("見込みなし", "Not in sight"),
    "home.kpi.payoff_never_sub": ("利息割れの借入が {n}件あります", "Payment below interest: {n}"),
    "home.kpi.payoff_none": ("借入なし", "No debts"),
    "home.kpi.payoff_noplan": ("未定", "Not planned"),
    "home.kpi.payoff_noplan_sub": ("返済額が未設定の借入 {n}件", "No monthly payment: {n}"),
    "home.month.title": ("今月の支払い", "This month's payments"),
    "home.month.sub": ("{period} ・チェックを入れると支払を記録します", "{period} · tick to record a payment"),
    "home.month.col.date": ("日付", "Date"),
    "home.month.col.item": ("項目", "Item"),
    "home.month.col.kind": ("種類", "Type"),
    "home.month.col.amount": ("金額", "Amount"),
    "home.month.col.status": ("状態", "Status"),
    "home.month.payday": ("給料日", "Payday"),
    "home.month.income": ("収入", "Income"),
    "home.month.empty": ("今月の支払いはありません", "Nothing to pay this month"),
    "home.alerts.title": ("注意", "Attention"),
    "home.alerts.none": ("気をつけることはありません", "All clear"),
    "home.breakdown.title": ("負債の内訳", "Debt by type"),
    "home.breakdown.empty": ("借入はありません", "No debts"),
    "home.trend.title": ("負債と貯蓄の見通し", "Debt and savings outlook"),
    "home.trend.sub_ok": ("{period} に完済見込み（あと{n}か月）", "Debt-free by {period} ({n} months)"),
    "home.trend.sub_never": ("今の返済額では完済の見込みが立たない借入があります",
                             "Some debts are never repaid at the current payments"),
    "home.trend.sub_none": ("借入はありません", "No debts"),
    "home.trend.debt": ("負債残高", "Debt"),
    "home.trend.savings": ("貯蓄残高", "Savings"),
    "home.trend.payoff": ("完済", "Debt-free"),
    "home.trend.empty": ("借入や収入を入力すると、見通しが表示されます", "Add debts or income to see the outlook"),

    # ---- alerts -----------------------------------------------------------------------------------
    "alert.close_due": ("{period} の締めがまだです", "{period} has not been closed"),
    "alert.underwater": ("「{name}」は毎月の返済額 {payment} が利息 {interest} 以下のため、残高が減りません",
                         "\"{name}\": the payment {payment} does not cover the interest {interest}"),
    "alert.overdue": ("「{name}」の支払日を{days}日過ぎています（{amount}・未払い）",
                      "\"{name}\" is overdue by {days} d ({amount}, unpaid)"),
    "alert.due_soon": ("「{name}」の支払日まであと{days}日です（{amount}）", "\"{name}\" is due in {days} d ({amount})"),
    "alert.due_today": ("「{name}」は今日が支払日です（{amount}）", "\"{name}\" is due today ({amount})"),
    "alert.negative_month": ("今月は {amount} 足りなくなる見込みです", "This month is expected to end {amount} short"),
    "alert.card_util": ("「{name}」の利用率が {pct}% です", "\"{name}\" is {pct}% used"),
    "alert.no_plan": ("「{name}」は毎月の返済額が決まっていません", "\"{name}\" has no monthly payment"),
    "alert.rates_stale": ("為替レートが {days} 日前のままです", "Exchange rates were last updated {days} d ago"),

    # ---- debts page ---------------------------------------------------------------------------------
    "debts.tab.bills": ("借入", "Debts"),
    "debts.tab.cards": ("カード", "Cards"),
    "debts.add_bill": ("借入を追加", "Add debt"),
    "debts.record": ("支払を記録", "Record payment"),
    "debts.drag_hint": ("行をドラッグして並べ替えられます", "Drag rows to reorder"),
    "debts.col.name": ("名前", "Name"),
    "debts.col.type": ("種類", "Type"),
    "debts.col.lender": ("借入先", "Lender"),
    "debts.col.borrower": ("名義", "Borrower"),
    "debts.col.balance": ("残高", "Balance"),
    "debts.col.currency": ("通貨", "Currency"),
    "debts.col.rate": ("年利", "Rate"),
    "debts.col.monthly": ("毎月の返済", "Monthly"),
    "debts.col.this_month": ("今月の支払い", "This month"),
    "debts.col.due_day": ("支払日", "Due day"),
    "debts.col.due_in": ("期日まで", "Due in"),
    "debts.col.status": ("今月", "Status"),
    "debts.col.payoff": ("完済予定", "Paid off"),
    "debts.col.interest_left": ("残り利息", "Interest left"),
    "debts.col.created": ("登録日", "Added"),
    "debts.payoff_never": ("完済できない", "Never"),
    "debts.payoff_noplan": ("未定", "No plan"),
    "debts.payoff_done": ("完済", "Paid off"),
    "debts.footer": ("合計（{cur}換算）  残高 {balance} ・今月の支払い {month} ・毎月の返済 {monthly}",
                     "Total in {cur}  balance {balance} · this month {month} · monthly {monthly}"),
    "debts.confirm_delete": ("「{name}」を削除しますか？\n支払の記録も削除されます（バックアップから戻せます）。",
                             "Delete \"{name}\"?\nIts payment records are deleted too (restorable from a backup)."),
    "debts.add_card": ("カードを追加", "Add card"),
    "cards.col.issuer": ("発行会社", "Issuer"),
    "cards.col.name": ("カード名", "Card"),
    "cards.col.due_day": ("支払日", "Due day"),
    "cards.col.limit": ("利用枠", "Limit"),
    "cards.col.used": ("利用額", "Used"),
    "cards.col.available": ("利用可能額", "Available"),
    "cards.col.util": ("利用率", "Used %"),
    "cards.col.lump": ("一括", "Lump sum"),
    "cards.col.shop_rev": ("ショッピングリボ", "Shopping rev."),
    "cards.col.cash_rev": ("キャッシングリボ", "Cash rev."),
    "cards.col.fee": ("年会費", "Annual fee"),
    "cards.col.fee_paid": ("今年の年会費", "Fee this year"),
    "cards.col.currency": ("通貨", "Currency"),
    "cards.col.managed": ("借入一覧で管理", "In debts list"),
    "cards.col.updated": ("更新日", "Updated"),
    "cards.footer": ("合計（{cur}換算）  利用枠 {limit} ・利用額 {used} ・利用可能額 {avail}",
                     "Total in {cur}  limit {limit} · used {used} · available {avail}"),
    "cards.confirm_delete": ("カード「{name}」を削除しますか？", "Delete the card \"{name}\"?"),

    # ---- monthly page -------------------------------------------------------------------------------
    "monthly.income.title": ("収入と貯蓄", "Income & savings"),
    "monthly.income.sub": ("今月の見込みと、来月以降の計画に使います", "Used for this month and for the plan"),
    "monthly.f.savings": ("先月末の貯蓄残高", "Savings at the end of last month"),
    "monthly.f.savings_hint": ("月次締めで自動的に更新されます", "Updated by the month-end close"),
    "monthly.f.income": ("今月の収入", "Income this month"),
    "monthly.f.other": ("その他の収入（今月）", "Other income this month"),
    "monthly.f.other_type": ("内容（例: 賞与）", "What (e.g. bonus)"),
    "monthly.f.expected": ("来月以降の収入（毎月）", "Income from next month"),
    "monthly.f.extra": ("追加の収入（毎月）", "Extra income (monthly)"),
    "monthly.f.payday": ("給料日", "Payday"),
    "monthly.saved": ("保存しました", "Saved"),
    "monthly.unsaved": ("未保存の変更があります", "Unsaved changes"),
    "monthly.living.title": ("生活費", "Living costs"),
    "monthly.living.sub": ("毎月の支出 ・「今月」にチェックで支払済", "Monthly spending · tick when paid"),
    "monthly.add_living": ("生活費を追加", "Add living cost"),
    "living.col.category": ("カテゴリ", "Category"),
    "living.col.name": ("名前", "Name"),
    "living.col.detail": ("詳細", "Details"),
    "living.col.amount": ("金額", "Amount"),
    "living.col.currency": ("通貨", "Currency"),
    "living.col.method": ("支払方法", "Paid by"),
    "living.col.due_day": ("支払日", "Due day"),
    "living.col.due_in": ("期日まで", "Due in"),
    "living.col.paid": ("今月", "This month"),
    "living.col.created": ("登録日", "Added"),
    "living.col.updated": ("更新日", "Updated"),
    "living.footer": ("合計（{cur}換算）  毎月 {total}（現金・口座 {cash} ・カード {card}）",
                      "Total in {cur}  {total} a month (cash {cash} · card {card})"),
    "living.confirm_delete": ("「{name}」を削除しますか？", "Delete \"{name}\"?"),

    # ---- plan page ------------------------------------------------------------------------------------
    "plan.title": ("毎月の見通し", "Monthly outlook"),
    "plan.sub": ("{cur} 換算 ・1か月目は今月の記録と予定、2か月目以降は収入の見込みと毎月の返済額で計算",
                 "In {cur} · month 1 uses this month's records and plans; later months use expected income"),
    "plan.months": ("期間", "Months"),
    "plan.months_n": ("{n}か月", "{n} months"),
    "plan.col.month": ("月", "Month"),
    "plan.col.income": ("収入", "Income"),
    "plan.col.debt": ("借入の返済", "Debt payments"),
    "plan.col.living": ("生活費", "Living costs"),
    "plan.col.net": ("収支", "Net"),
    "plan.col.savings": ("貯蓄残高", "Savings"),
    "plan.col.balance": ("負債残高", "Debt"),
    "plan.col.worth": ("純資産", "Net worth"),
    "plan.this_month": ("{period}（今月）", "{period} (now)"),
    "plan.note_cards": ("借入一覧で管理していないカードの利用額（{amount}）は含みません。",
                        "Card balances not in the debts list ({amount}) are not included."),
    "plan.note_card_living": ("カード払いの生活費は、翌月の支払いとして数えています。",
                              "Living costs paid by card are counted in the following month."),

    # ---- data page -----------------------------------------------------------------------------------
    "data.location.title": ("データの保存場所", "Data folder"),
    "data.location.sub": ("データファイル・バックアップ・ログをここに置きます", "Data files, backups and logs live here"),
    "data.location.change": ("変更…", "Change…"),
    "data.location.open": ("フォルダを開く", "Open folder"),
    "data.location.copy_q": ("今のデータファイル（{n}個）を新しい場所にコピーしますか？\n元のファイルはそのまま残ります。",
                             "Copy the current data files ({n}) to the new folder?\nThe originals stay where they are."),
    "data.location.copy": ("コピーする", "Copy"),
    "data.location.no_copy": ("コピーしない", "Don't copy"),
    "data.location.changed": ("保存場所を変更しました", "The data folder was changed"),
    "data.file.title": ("データファイル", "Data file"),
    "data.file.none": ("開いていません", "None"),
    "data.file.new": ("新規作成…", "New…"),
    "data.file.open": ("開く…", "Open…"),
    "data.file.import": ("旧版から取り込む…", "Import from 3.x…"),
    "data.file.new_name_q": ("新しいファイルの名前", "Name of the new file"),
    "data.file.exists": ("同じ名前のファイルがあります", "A file with this name already exists"),
    "data.backup.title": ("バックアップ", "Backups"),
    "data.backup.sub": ("起動時（1日1回）・月次締めと復元の前に自動で作り、直近{n}個を残します",
                        "Made at start-up (daily), before a close and before a restore; the latest {n} are kept"),
    "data.backup.col.when": ("日時", "When"),
    "data.backup.col.reason": ("理由", "Reason"),
    "data.backup.col.size": ("サイズ", "Size"),
    "data.backup.now": ("今すぐバックアップ", "Back up now"),
    "data.backup.restore": ("選んだ時点に戻す", "Restore selected"),
    "data.backup.restore_q": ("{when} の状態に戻しますか？\n今の状態もバックアップしてから戻します。",
                              "Restore the state of {when}?\nThe current state is backed up first."),
    "data.backup.restored": ("{when} の状態に戻しました", "Restored the state of {when}"),
    "data.backup.done": ("バックアップを作りました", "Backup created"),
    "data.backup.empty": ("まだバックアップはありません", "No backups yet"),
    "data.close.title": ("月次締め", "Month-end close"),
    "data.close.last": ("最後に締めた月: {period}", "Last closed: {period}"),
    "data.close.due": ("締めが必要な月: {periods}", "To close: {periods}"),
    "data.close.up_to_date": ("締めは済んでいます", "Up to date"),
    "data.close.start": ("月次締めを始める", "Start close"),
    "data.close.undo": ("直前の締めを取り消す", "Undo last close"),
    "data.close.undo_q": ("{period} の締めを取り消して、締める前の状態に戻しますか？\n締めた後に入力した内容も元に戻ります。",
                          "Undo the close of {period}?\nAnything entered after the close is undone as well."),
    "data.close.undo_missing": ("締める前のバックアップが見つかりません", "The backup made before the close was not found"),
    "data.close.undone": ("{period} の締めを取り消しました", "The close of {period} was undone"),
    "data.close.skipped": ("（変更なしで締めた月）", "(closed without changes)"),
    "data.rates.title": ("為替レート", "Exchange rates"),
    "data.rates.sub": ("1 米ドルあたりの各通貨", "Units per 1 US dollar"),
    "data.rates.updated": ("更新: {when}（{source}）", "Updated {when} ({source})"),
    "data.rates.never": ("まだ取得していません", "Not fetched yet"),
    "data.rates.src.auto": ("自動", "auto"),
    "data.rates.src.manual": ("手入力", "manual"),
    "data.rates.fetch": ("今すぐ取得", "Fetch now"),
    "data.rates.fetching": ("取得中…", "Fetching…"),
    "data.rates.auto": ("起動時に自動で更新する（1日1回）", "Update automatically at start-up (daily)"),
    "data.rates.fetched": ("為替レートを更新しました", "Exchange rates updated"),
    "data.rates.failed": ("為替レートを取得できませんでした（前の値を使います）\n{error}",
                          "Could not fetch exchange rates (keeping the previous ones)\n{error}"),
    "data.rates.saved": ("為替レートを保存しました", "Exchange rates saved"),
    "data.view.title": ("表示", "Display"),
    "data.view.theme": ("テーマ", "Theme"),
    "theme.system": ("システムに合わせる", "Match system"),
    "theme.light": ("ライト", "Light"),
    "theme.dark": ("ダーク", "Dark"),
    "data.view.lang": ("言語", "Language"),
    "data.view.columns": ("表の列を選ぶ…", "Choose table columns…"),
    "data.about.title": ("このアプリについて", "About"),
    "data.about.desc": ("返済と家計の見通しを管理するアプリ（旧 Payback Management）",
                        "Debt and household cash-flow planner (formerly Payback Management)"),
    "data.about.dev": ("開発: {author}", "Developer: {author}"),
    "data.about.libs": ("使用ライブラリ: PyQt6, qtawesome, requests", "Libraries: PyQt6, qtawesome, requests"),
    "data.about.logs": ("ログを開く", "Open log folder"),

    # ---- dialogs ---------------------------------------------------------------------------------------
    "bill.title_add": ("借入を追加", "Add debt"),
    "bill.title_edit": ("借入を編集", "Edit debt"),
    "bill.f.name": ("名前", "Name"),
    "bill.f.name_ph": ("例: ○○カード リボ払い", "e.g. Card revolving"),
    "bill.f.type": ("種類", "Type"),
    "bill.f.lender": ("借入先", "Lender"),
    "bill.f.borrower": ("名義（誰の借入か）", "Borrower"),
    "bill.f.balance": ("今の残高", "Current balance"),
    "bill.f.currency": ("通貨", "Currency"),
    "bill.f.rate": ("年利（%）", "Annual rate (%)"),
    "bill.f.monthly": ("毎月の返済額", "Monthly payment"),
    "bill.f.this_month": ("今月だけ違う金額", "This month only"),
    "bill.f.this_month_hint": ("0 なら毎月の返済額を使います", "0 = use the monthly payment"),
    "bill.f.due_day": ("支払日（毎月）", "Due day (monthly)"),
    "bill.f.created": ("登録日", "Added on"),
    "bill.lump_hint": ("ショッピング一括は、支払日に残高を全額支払います。", "A card bill is paid in full on its due date."),
    "bill.people_hint": ("返済額が決まっていなければ 0 のままで構いません。", "Leave the payment at 0 if there is no fixed plan."),
    "bill.preview.ok": ("完済予定: {period}（あと{n}か月）・残り利息 {interest}",
                        "Paid off by {period} ({n} months) · interest left {interest}"),
    "bill.preview.never": ("毎月の返済額が利息 {interest} 以下のため、完済できません",
                           "The payment does not cover the interest of {interest}: never paid off"),
    "bill.preview.noplan": ("毎月の返済額が未設定のため、完済予定は出せません", "No monthly payment, so no payoff date"),
    "bill.preview.none": ("残高はありません", "No balance"),
    "bill.err.name": ("名前を入力してください", "Enter a name"),
    "bill.err.monthly": ("毎月の返済額を入力してください", "Enter the monthly payment"),
    "living.title_add": ("生活費を追加", "Add living cost"),
    "living.title_edit": ("生活費を編集", "Edit living cost"),
    "living.f.category": ("カテゴリ", "Category"),
    "living.f.name": ("名前", "Name"),
    "living.f.name_ph": ("例: 家賃、電気代", "e.g. rent, electricity"),
    "living.f.detail": ("詳細", "Details"),
    "living.f.amount": ("金額（毎月）", "Amount (monthly)"),
    "living.f.currency": ("通貨", "Currency"),
    "living.f.due_day": ("支払日", "Due day"),
    "living.f.method": ("支払方法", "Paid by"),
    "living.f.dates": ("登録 {created} ・更新 {updated}", "Added {created} · updated {updated}"),
    "living.err.name": ("名前を入力してください", "Enter a name"),
    "living.err.amount": ("金額を入力してください", "Enter an amount"),
    "card.title_add": ("カードを追加", "Add card"),
    "card.title_edit": ("カードを編集", "Edit card"),
    "card.f.issuer": ("発行会社", "Issuer"),
    "card.f.issuer_ph": ("例: ○○カード", "e.g. card company"),
    "card.f.name": ("カード名", "Card name"),
    "card.f.due_day": ("支払日", "Due day"),
    "card.f.currency": ("通貨", "Currency"),
    "card.f.limit": ("利用枠", "Credit limit"),
    "card.f.lump": ("一括払いの利用額", "Lump-sum balance"),
    "card.f.shop_rev": ("ショッピングリボの残高", "Shopping revolving"),
    "card.f.cash_rev": ("キャッシングリボの残高", "Cash revolving"),
    "card.f.used": ("利用額の合計", "Total used"),
    "card.f.used_auto": ("内訳の合計を使う", "Use the sum of the parts"),
    "card.f.fee": ("年会費", "Annual fee"),
    "card.f.fee_paid": ("今年の年会費は支払済", "This year's fee is paid"),
    "card.f.managed": ("この利用額は借入一覧にも入力している（総負債に二重に数えない）",
                       "These balances are also entered as debts (don't count them twice)"),
    "card.err.name": ("カード名を入力してください", "Enter the card name"),
    "pay.title": ("支払を記録 — {name}", "Record payment — {name}"),
    "pay.info": ("残高 {balance} ・年利 {rate}% ・今月の予定 {planned}", "Balance {balance} · {rate}% · planned {planned}"),
    "pay.f.date": ("支払日", "Paid on"),
    "pay.f.amount": ("支払額", "Amount"),
    "pay.f.interest": ("うち利息", "Of which interest"),
    "pay.f.note": ("メモ", "Note"),
    "pay.preview": ("元金 {principal} → 支払後の残高 {after}", "Principal {principal} → balance after {after}"),
    "pay.warn_under": ("支払額が利息より少ないため、残高が {diff} 増えます", "Less than the interest: the balance grows by {diff}"),
    "pay.interest_once": ("今月の利息は記録済みです。追加の支払いは全額が元金になります。",
                          "This month's interest is already recorded; an extra payment goes fully to principal."),
    "pay.ok": ("記録する", "Record"),
    "pay.undo_q": ("「{name}」の今月の支払記録（{amount}）を取り消しますか？",
                   "Undo this month's payment for \"{name}\" ({amount})?"),
    "pay.undo": ("取り消す", "Undo"),
    "cols.title": ("表の列", "Table columns"),
    "cols.table": ("表", "Table"),
    "cols.t.bills": ("借入", "Debts"),
    "cols.t.cards": ("カード", "Cards"),
    "cols.t.living": ("生活費", "Living costs"),
    "cols.t.plan": ("毎月の見通し", "Monthly outlook"),
    "cols.reset": ("初期設定に戻す", "Reset"),

    # ---- month-end close --------------------------------------------------------------------------------
    "close.title": ("月次締め — {period}", "Month-end close — {period}"),
    "close.mode.record": ("支払を確認して締める（おすすめ）", "Check the payments and close (recommended)"),
    "close.mode.record_hint": ("チェックした支払いを記録し、未払いの借入には利息を加え、貯蓄残高を繰り越します。",
                               "Ticked payments are recorded, unpaid debts get the month's interest, savings carry over."),
    "close.mode.skip": ("残高を変えずに {until} までまとめて締める", "Close up to {until} without changing anything"),
    "close.mode.skip_hint": ("試算用のファイルや、残高をあとで直接直す場合に使います。",
                             "For planning files, or when you will correct the balances by hand."),
    "close.step1": ("支払いの確認", "Payments"),
    "close.step2": ("貯蓄の繰り越し", "Savings"),
    "close.step3": ("確認", "Confirm"),
    "close.items.hint": ("チェックした項目を、表の金額で支払済にします。チェックを外した借入は未払いとして、その月の利息を残高に加えます。",
                         "Ticked items are recorded as paid with the amount shown. Unticked debts stay unpaid and the month's interest is added."),
    "close.col.item": ("項目", "Item"),
    "close.col.kind": ("種類", "Type"),
    "close.col.planned": ("予定額", "Planned"),
    "close.col.amount": ("支払額", "Amount"),
    "close.col.note": ("備考", "Note"),
    "close.recorded": ("記録済み", "Recorded"),
    "close.accrue": ("未払い → 利息 {interest} を加算", "Unpaid → interest {interest} added"),
    "close.carry": ("未払い（残高を繰り越し）", "Unpaid (carried over)"),
    "close.card_living": ("カード払い（翌月の請求）", "By card (next month's bill)"),
    "close.savings.title": ("{period} 末の貯蓄残高", "Savings at the end of {period}"),
    "close.savings.start": ("先月末の貯蓄", "Savings at the start"),
    "close.savings.income": ("＋ 収入", "+ Income"),
    "close.savings.out": ("− 支払い（借入・現金の生活費）", "− Payments (debts, cash living costs)"),
    "close.savings.calc": ("＝ 計算上の残高", "= Calculated"),
    "close.savings.actual": ("締め後の貯蓄残高", "Savings after the close"),
    "close.savings.actual_hint": ("銀行の残高がわかれば、その金額に直してください", "If you know the bank balance, enter it"),
    "close.savings.reset_other": ("その他の収入（{what} {amount}）を 0 に戻す", "Reset the other income ({what} {amount}) to 0"),
    "close.confirm.payments": ("記録する支払い: {n}件（{amount}）", "Payments to record: {n} ({amount})"),
    "close.confirm.accruals": ("利息を加える借入: {n}件（{amount}）", "Debts with interest added: {n} ({amount})"),
    "close.confirm.living": ("支払済にする生活費: {n}件", "Living costs marked paid: {n}"),
    "close.confirm.savings": ("貯蓄残高: {before} → {after}", "Savings: {before} → {after}"),
    "close.confirm.backup": ("締める前にバックアップを作ります。「データ・設定」からいつでも取り消せます。",
                             "A backup is made first; you can undo the close in Data & settings."),
    "close.confirm.skip": ("{first}〜{until} の {n} か月を、残高を変えずに締めます。",
                           "{n} months ({first}–{until}) are closed without changing any amount."),
    "close.do": ("締める", "Close month"),
    "close.done": ("{period} を締めました", "{period} is closed"),
    "close.more_q": ("続けて {period} も締めますか？", "Close {period} as well?"),

    # ---- welcome / import ------------------------------------------------------------------------------------
    "welcome.title": ("CLEAR へようこそ", "Welcome to CLEAR"),
    "welcome.intro": ("Payback Management の後継アプリです。最初に、データの保存場所と使うデータを決めます。",
                      "CLEAR replaces Payback Management. First choose where your data lives and which data to use."),
    "welcome.location": ("データの保存場所", "Data folder"),
    "welcome.import": ("旧版（Payback Management）のデータを取り込む", "Import data from Payback Management"),
    "welcome.import_hint": ("選んだファイルを保存場所にコピーして取り込みます。元のファイルは変更しません。",
                            "Selected files are copied into the data folder; the originals are not changed."),
    "welcome.none_found": ("旧版のデータは見つかりませんでした", "No Payback Management data was found"),
    "welcome.browse": ("ほかのファイルを選ぶ…", "Choose another file…"),
    "welcome.new": ("新しいデータファイルを作る", "Create a new data file"),
    "welcome.new_name": ("ファイル名", "File name"),
    "welcome.start": ("始める", "Start"),
    "welcome.later": ("あとで", "Later"),
    "welcome.modified": ("更新 {date}", "modified {date}"),
    "import.done_title": ("取り込みが完了しました", "Import finished"),
    "import.line": ("{name}: 借入 {bills}件 ・生活費 {living}件 ・カード {cards}枚（{period} 時点）",
                    "{name}: {bills} debts · {living} living costs · {cards} cards (as of {period})"),
    "import.converted": ("「今月支払済」だった {n} 件を支払の記録に変えました。", "{n} \"paid this month\" ticks became payment records."),
    "import.originals": ("元のファイルは変更していません。", "The original files were not changed."),
    "import.close_hint": ("{period} からの月次締めがまだです。画面上部の案内から締めてください。",
                          "Months from {period} are not closed yet; use the banner at the top."),
    "import.legacy_q": ("「{name}」は旧版のファイルです。\nデータフォルダにコピーして取り込みますか？（元のファイルは変更しません）",
                        "\"{name}\" is a Payback Management file.\nCopy it into the data folder and import it? (The original is not changed.)"),
    "import.failed": ("「{name}」を取り込めませんでした: {error}", "Could not import \"{name}\": {error}"),

    # ---- errors ------------------------------------------------------------------------------------------------
    "err.newer": ("このファイルは新しいバージョンの CLEAR で作られています。アプリを更新してください。",
                  "This file was made by a newer CLEAR. Please update the app."),
    "err.not_db": ("CLEAR のデータファイルではありません", "Not a CLEAR data file"),
    "err.open": ("ファイルを開けませんでした: {error}", "Could not open the file: {error}"),
    "err.unexpected": ("予期しないエラーが起きました。内容はログに記録しました。\n{error}",
                       "An unexpected error occurred. Details were written to the log.\n{error}"),
    "err.data_dir": ("データの保存場所 {path} を使えません。別の場所を選んでください。",
                     "The data folder {path} cannot be used. Please choose another one."),
    "err.no_db": ("先にデータファイルを開いてください", "Open a data file first"),
    "dlg.choose_folder": ("フォルダを選ぶ", "Choose folder"),
    "dlg.db_filter": ("データファイル (*.db)", "Data files (*.db)"),
}


def set_language(lang: str) -> None:
    global _lang
    _lang = lang if lang in LANGUAGES else "ja"


def lang() -> str:
    return _lang


def t(key: str, **params: object) -> str:
    pair = S.get(key)
    if pair is None:
        return key
    text = pair[0] if _lang == "ja" else pair[1]
    if params:
        try:
            return text.format(**params)
        except (KeyError, IndexError, ValueError):
            return text
    return text


def has(key: str) -> bool:
    return key in S


# ---- formatting helpers ------------------------------------------------------------------
def money(value: float, currency: str) -> str:
    return fmt_money(value, currency, _lang)


def fmt_period(p: Period | None) -> str:
    if p is None:
        return "—"
    if _lang == "ja":
        return f"{p.year}年{p.month}月"
    return f"{_MONTHS_EN[p.month - 1]} {p.year}"


def fmt_month_short(p: Period, with_year: bool = False) -> str:
    if _lang == "ja":
        return f"{p.year % 100}年{p.month}月" if with_year else f"{p.month}月"
    return f"{_MONTHS_EN[p.month - 1]} '{p.year % 100:02d}" if with_year else _MONTHS_EN[p.month - 1]


def fmt_date(d: date | None) -> str:
    if d is None:
        return "—"
    if _lang == "ja":
        return f"{d.year}/{d.month}/{d.day}"
    return f"{_MONTHS_EN[d.month - 1]} {d.day}, {d.year}"


def fmt_md(d: date) -> str:
    if _lang == "ja":
        return f"{d.month}/{d.day}（{_WEEKDAYS_JA[d.weekday()]}）"
    return f"{_MONTHS_EN[d.month - 1]} {d.day}"


def fmt_datetime(dt: datetime | None) -> str:
    if dt is None:
        return "—"
    return f"{fmt_date(dt.date())} {dt:%H:%M}"


def due_text(days: int) -> str:
    if days < 0:
        return t("common.overdue_days", n=-days)
    if days == 0:
        return t("common.today")
    return t("common.in_days", n=days)


def bill_type_label(code: str) -> str:
    key = f"bt.{code}"
    return t(key) if key in S else code


def category_label(value: str) -> str:
    key = f"cat.{value}"
    return t(key) if value in CATEGORY_KEYS else value


def category_from_label(text: str) -> str:
    """Map a translated label back to its stored key (custom text is kept as typed)."""
    text = (text or "").strip()
    for key in CATEGORY_KEYS:
        if text in (S[f"cat.{key}"][0], S[f"cat.{key}"][1], key):
            return key
    return text


def method_label(code: str) -> str:
    key = f"pm.{code}"
    return t(key) if key in S else code


def reason_label(code: str) -> str:
    key = f"reason.{code}"
    return t(key) if key in S else code

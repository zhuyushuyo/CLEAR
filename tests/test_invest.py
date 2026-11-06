"""4.1 investments (I1-I6, P2): valuation, trades and undo, NISA limits, the plan, price parsing.

Synthetic data only; nothing here touches the network.
"""

from datetime import date, datetime, timedelta

import pytest

from clear import engine, invest, market
from clear.engine import State
from clear.models import CreditCard, Holding, LivingCost, Price, Profile, Trade, price_key
from clear.periods import Period
from clear.repo import ClosePlan, ContribBuy, Repository

RATES = {"USD": 1.0, "JPY": 150.0, "CNY": 7.0, "SGD": 1.3}
NOW = datetime(2026, 11, 6, 21, 30)
TODAY = date(2026, 11, 6)


def prices(*items: Price) -> dict[str, Price]:
    return {p.key: p for p in items}


def stamp(days_ago: float = 0) -> str:
    return (NOW - timedelta(days=days_ago)).isoformat()


# ---- valuation --------------------------------------------------------------------------
def test_share_quoted_in_another_currency():
    h = Holding(id=1, kind="stock", symbol="VOO", quantity=12, avg_cost=420, currency="USD", quote_currency="USD")
    hv = invest.value_holding(h, prices(Price("yahoo", "VOO", 560.0, "USD", 557.0, stamp())), RATES, "JPY", NOW)
    assert hv.status == "ok" and hv.unit_price == 560.0
    assert hv.value == 12 * 560 and hv.value_t == pytest.approx(12 * 560 * 150)
    assert hv.gain == pytest.approx(12 * 140) and hv.gain_pct == pytest.approx(140 / 420)
    assert hv.day_change == pytest.approx(12 * 3)
    # the same share with a cost kept in yen: the price is converted
    h_jpy = Holding(id=2, kind="stock", symbol="VOO", quantity=1, avg_cost=60000, currency="JPY", quote_currency="USD")
    assert invest.value_holding(h_jpy, prices(Price("yahoo", "VOO", 560.0, "USD")), RATES, "JPY", NOW).value \
        == pytest.approx(84000)


@pytest.mark.parametrize("unit, qty, ounces", [("g", 120, 120 / invest.TROY_OUNCE_G), ("oz", 2, 2.0),
                                               ("kg", 1, 1000 / invest.TROY_OUNCE_G)])
def test_metal_units_and_local_premium(unit, qty, ounces):
    h = Holding(id=1, kind="metal", symbol="gold", unit=unit, quantity=qty, avg_cost=0, currency="JPY",
                adjust_pct=3.0)
    assert invest.quote_ref(h) == ("yahoo", "GC=F")
    hv = invest.value_holding(h, prices(Price("yahoo", "GC=F", 2650.0, "USD", 2640.0, stamp())), RATES, "JPY", NOW)
    assert hv.value == pytest.approx(ounces * 2650 * 1.03 * 150)
    assert hv.gain is None                                                       # no cost: no gain shown


def test_crypto_and_manual_assets():
    btc = Holding(id=1, kind="crypto", symbol="bitcoin", quantity=0.052, avg_cost=9_000_000, currency="JPY",
                  price_source="coingecko")
    assert invest.quote_ref(btc) == ("coingecko", "bitcoin@jpy")
    fund = Holding(id=2, kind="manual", name="Fund", quantity=1, avg_cost=1_000_000, manual_price=1_280_000,
                   currency="JPY", price_source="manual")
    folio = invest.summarize([btc, fund], prices(Price("coingecko", "bitcoin@jpy", 15_200_000, "JPY", 15_500_000,
                                                      stamp())), RATES, "JPY", NOW)
    assert folio.value == pytest.approx(0.052 * 15_200_000 + 1_280_000)
    assert folio.cost == pytest.approx(0.052 * 9_000_000 + 1_000_000)
    assert folio.by_kind == pytest.approx({"crypto": 790_400, "manual": 1_280_000})
    assert folio.day_change == pytest.approx(0.052 * -300_000) and folio.has_day_change


def test_missing_stale_and_unknown_currency():
    a = Holding(id=1, kind="stock", symbol="AAA", name="No price", quantity=1, currency="USD")
    b = Holding(id=2, kind="stock", symbol="BBB", name="Old price", quantity=1, currency="USD")
    c = Holding(id=3, kind="stock", symbol="CCC", name="Odd currency", quantity=1, currency="USD",
                quote_currency="EUR")
    folio = invest.summarize([a, b, c], prices(Price("yahoo", "BBB", 10.0, "USD", None, stamp(days_ago=8)),
                                              Price("yahoo", "CCC", 10.0, "EUR", None, stamp())), RATES, "USD", NOW)
    status = {hv.holding.name: hv.status for hv in folio.rows}
    assert status == {"No price": "missing", "Old price": "stale", "Odd currency": "no_fx"}
    assert folio.missing == ["No price", "Odd currency"] and folio.stale == ["Old price"]
    assert folio.value == 10.0


# ---- trades -----------------------------------------------------------------------------
def test_moving_average_cost():
    r = invest.apply_trade(10, 100, "buy", quantity=10, price=120, fee=10)
    assert (r.qty_after, r.avg_after, r.amount) == (20, 110.5, 1210)
    r = invest.apply_trade(20, 110.5, "sell", quantity=5, price=150, fee=5)
    assert (r.qty_after, r.avg_after, r.amount) == (15, 110.5, 745)
    assert r.realized == pytest.approx(192.5)
    r = invest.apply_trade(15, 110.5, "sell", quantity=99, price=100)
    assert (r.qty_after, r.avg_after) == (0, 0.0)                                # cannot sell more than held
    r = invest.apply_trade(15, 110.5, "dividend", amount=500)
    assert (r.qty_after, r.avg_after, r.amount) == (15, 110.5, 500)


@pytest.fixture
def repo(tmp_path) -> Repository:
    return Repository.create(tmp_path / "test.db", TODAY)


def test_trades_update_the_holding_and_undo_exactly(repo):
    h = repo.add_holding(Holding(kind="stock", symbol="7203.T", name="Toyota", quantity=100, avg_cost=2450,
                                 currency="JPY", quote_currency="JPY"))
    repo.record_trade(h.id, "buy", TODAY, quantity=50, price=2900, fee=500)
    after_buy = next(x for x in repo.holdings() if x.id == h.id)
    assert after_buy.quantity == 150 and after_buy.avg_cost == pytest.approx((245000 + 145000 + 500) / 150)
    sell = repo.record_trade(h.id, "sell", TODAY, quantity=30, price=3000)
    assert sell.realized == pytest.approx(30 * (3000 - after_buy.avg_cost)) and sell.cash == 90000
    assert repo.undo_last_trade(h.id).kind == "sell"
    restored = next(x for x in repo.holdings() if x.id == h.id)
    assert (restored.quantity, restored.avg_cost) == (after_buy.quantity, after_buy.avg_cost)
    assert repo.undo_last_trade(h.id).kind == "buy"
    original = next(x for x in repo.holdings() if x.id == h.id)
    assert (original.quantity, original.avg_cost) == (100, 2450)
    assert repo.undo_last_trade(h.id) is None
    with pytest.raises(ValueError):
        repo.record_trade(h.id, "buy", TODAY, quantity=0, price=2900)          # no units: nothing written
    assert repo.trades(h.id) == []


def test_manual_asset_money_in_and_out(repo):
    h = repo.add_holding(Holding(kind="manual", name="Fund", quantity=1, avg_cost=900_000, manual_price=1_000_000,
                                 currency="JPY", price_source="manual"))
    repo.record_trade(h.id, "buy", TODAY, amount=50_000)
    x = next(x for x in repo.holdings() if x.id == h.id)
    assert (x.manual_price, x.avg_cost) == (1_050_000, 950_000)
    out = repo.record_trade(h.id, "sell", TODAY, amount=105_000)
    x = next(x for x in repo.holdings() if x.id == h.id)
    assert (x.manual_price, x.avg_cost) == (945_000, pytest.approx(855_000))
    assert out.realized == pytest.approx(10_000)
    repo.undo_last_trade(h.id)
    repo.undo_last_trade(h.id)
    x = next(x for x in repo.holdings() if x.id == h.id)
    assert (x.manual_price, x.avg_cost) == (1_000_000, 900_000)


def test_contribution_undo_is_limited_to_the_month(repo):
    h = repo.add_holding(Holding(kind="manual", name="Fund", quantity=1, avg_cost=0, manual_price=0,
                                 currency="JPY", price_source="manual", contrib_amount=50_000, contrib_day=27))
    repo.record_trade(h.id, "buy", date(2026, 10, 27), amount=50_000, is_contrib=True)
    assert repo.undo_last_trade(h.id, Period(2026, 11)) is None                 # October's: kept
    repo.record_trade(h.id, "buy", date(2026, 11, 27), amount=50_000, is_contrib=True)
    assert repo.undo_last_trade(h.id, Period(2026, 11)).period == "2026-11"
    assert len(repo.trades(h.id)) == 1


def test_close_writes_fees_and_contributions(repo):
    card = repo.add_card(CreditCard(issuer="Card Co", name="Gold", annual_fee=11000, fee_month=10, due_day=27))
    fund = repo.add_holding(Holding(kind="manual", name="Fund", quantity=1, manual_price=100_000, avg_cost=100_000,
                                    currency="JPY", price_source="manual", contrib_amount=50_000, contrib_day=27))
    plan = ClosePlan(Period(2026, 10), fee_paid_card_ids=[card.id],
                     contrib_buys=[ContribBuy(fund.id, 50_000, 0.0, 0.0, date(2026, 10, 27), True)])
    repo.close_month(plan)
    c = next(x for x in repo.cards() if x.id == card.id)
    assert c.fee_paid_period == "2026-10"
    assert engine.fee_status(c, TODAY).state == "paid"
    tr = repo.trades(fund.id)
    assert len(tr) == 1 and tr[0].is_contrib and tr[0].period == "2026-10" and tr[0].amount == 50_000


# ---- NISA (P2) ----------------------------------------------------------------------------
def nisa_holdings() -> list[Holding]:
    return [Holding(id=1, kind="stock", symbol="VOO", account="nisa_growth", quantity=12, avg_cost=420, currency="USD"),
            Holding(id=2, kind="manual", name="Index", account="nisa_tsumitate", quantity=1, avg_cost=1_000_000,
                    manual_price=1_200_000, currency="JPY"),
            Holding(id=3, kind="stock", symbol="7203.T", account="taxable", quantity=100, avg_cost=2450,
                    currency="JPY")]


def trade(holding_id, account, when, kind="buy", **kw) -> Trade:
    return Trade(holding_id=holding_id, account=account, trade_date=when, kind=kind, **kw)


def test_nisa_usage_per_frame_and_lifetime():
    trades = [trade(1, "nisa_growth", date(2026, 5, 12), quantity=2, price=520.0, currency="USD"),
              *[trade(2, "nisa_tsumitate", date(2026, m, 27), amount=50_000, currency="JPY", is_contrib=True)
                for m in range(1, 11)],
              trade(2, "nisa_tsumitate", date(2025, 12, 27), amount=50_000, currency="JPY"),     # last year
              trade(1, "nisa_growth", date(2026, 6, 1), kind="sell", quantity=1, price=500.0, currency="USD"),
              trade(3, "taxable", date(2026, 6, 1), quantity=10, price=2800.0, currency="JPY")]
    u = invest.nisa_usage(nisa_holdings(), trades, 2026, RATES)
    assert u.year_used == pytest.approx({"nisa_growth": 2 * 520 * 150, "nisa_tsumitate": 500_000})
    assert u.lifetime_used == pytest.approx(12 * 420 * 150 + 1_000_000)
    assert u.lifetime_growth == pytest.approx(12 * 420 * 150)
    assert u.over == [] and u.year_left("nisa_tsumitate") == pytest.approx(700_000)
    big = [trade(2, "nisa_tsumitate", date(2026, 1, 5), amount=1_300_000, currency="JPY")]
    assert invest.nisa_usage(nisa_holdings(), big, 2026, RATES).over == ["nisa_tsumitate"]
    assert invest.uses_nisa(nisa_holdings()) and not invest.uses_nisa(nisa_holdings()[2:])


# ---- the plan with investments ------------------------------------------------------------------
def invest_state(**kw) -> State:
    voo = Holding(id=1, kind="stock", symbol="VOO", quantity=10, avg_cost=400, currency="USD", quote_currency="USD",
                  contrib_amount=30_000, contrib_currency="JPY", contrib_day=10, contrib_method="bank")
    base = dict(profile=Profile(cumulative_savings=100_000, monthly_income=300_000, expected_income=280_000,
                                payday=25),
                living=[LivingCost(id=1, name="Rent", amount=80_000, monthly_due_day=27)],
                holdings=[voo], prices=prices(Price("yahoo", "VOO", 500.0, "USD", None, stamp())),
                returns={"stock": 12.0, "crypto": 0.0, "metal": 0.0, "manual": 0.0},
                today=TODAY, last_closed=Period(2026, 10))
    base.update(kw)
    return State(**base)


def test_plan_grows_investments_and_pays_contributions():
    rows = engine.simulate(invest_state(), 3, RATES, "JPY")
    m1, m2 = rows[0], rows[1]
    assert m1.contrib == 30_000 and m1.invest == pytest.approx(750_000 + 30_000)
    assert m1.savings == 100_000 + 300_000 - 80_000 - 30_000
    assert m2.invest == pytest.approx(780_000 * 1.01 + 30_000)                    # 12 % a year = 1 % a month
    assert m2.savings == m1.savings + 280_000 - 80_000 - 30_000
    assert m2.net_worth == pytest.approx(m2.savings + m2.invest - m2.debt)


def test_plan_counts_an_executed_contribution_once():
    done = Trade(holding_id=1, kind="buy", trade_date=date(2026, 11, 10), quantity=0.4, price=500.0, amount=200.0,
                 currency="USD", period="2026-11", is_contrib=True, cash_effect=True)
    st = invest_state(trades_month=[done])
    m1 = engine.simulate(st, 1, RATES, "JPY")[0]
    assert m1.contrib == pytest.approx(30_000) and m1.invest == pytest.approx(750_000)
    items = [i for i in engine.month_items(st, RATES, "JPY") if i.kind == "contrib"]
    assert len(items) == 1 and items[0].paid


def test_plan_pays_card_contributions_and_fees_a_month_later():
    st = invest_state(cards=[CreditCard(id=1, name="Gold", annual_fee=11_000, fee_month=12, due_day=27)])
    st.holdings[0].contrib_method = "card"
    m1, m2 = engine.simulate(st, 2, RATES, "JPY")
    assert m1.contrib == 0 and m1.invest == pytest.approx(780_000)               # bought now, paid next month
    assert m2.contrib == 30_000 and m2.living == 80_000 + 11_000                 # December: the annual fee


def test_sales_and_purchases_of_the_month_move_savings():
    sale = Trade(holding_id=1, kind="sell", trade_date=date(2026, 11, 2), quantity=2, price=500.0, amount=1000.0,
                 currency="USD", period="2026-11", cash_effect=True)
    m1 = engine.simulate(invest_state(trades_month=[sale]), 1, RATES, "JPY")[0]
    assert m1.trade_cash == pytest.approx(150_000)
    assert m1.savings == pytest.approx(100_000 + 300_000 - 80_000 - 30_000 + 150_000)


# ---- price sources (no network: fake responses) ----------------------------------------------------
class FakeResponse:
    def __init__(self, data):
        self.data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self.data


class FakeSession:
    def __init__(self, data):
        self.data = data
        self.calls = []

    def get(self, url, **kw):
        self.calls.append((url, kw))
        return FakeResponse(self.data(url, kw) if callable(self.data) else self.data)


def test_coingecko_prices_and_previous_day():
    s = FakeSession({"bitcoin": {"jpy": 15_000_000, "jpy_24h_change": -2.0, "usd": 100_000, "usd_24h_change": 0.0},
                     "ethereum": {"jpy": 500_000}})
    out = market.fetch_coingecko({"jpy": {"bitcoin", "ethereum"}, "usd": {"bitcoin"}}, "demo-key", session=s)
    assert out[("bitcoin", "jpy")] == pytest.approx((15_000_000, 15_000_000 / 0.98))
    assert out[("bitcoin", "usd")] == (100_000, 100_000)
    assert out[("ethereum", "jpy")] == (500_000, None)
    url, kw = s.calls[0]
    assert url.endswith("/simple/price") and kw["headers"] == {"x-cg-demo-api-key": "demo-key"}
    assert kw["params"]["ids"] == "bitcoin,ethereum" and kw["params"]["vs_currencies"] == "jpy,usd"
    found = market.search_coingecko("btc", session=FakeSession({"coins": [{"id": "bitcoin", "name": "Bitcoin",
                                                                           "symbol": "btc"}]}))
    assert found == [{"symbol": "bitcoin", "name": "Bitcoin (BTC)", "exchange": "CoinGecko", "kind": "crypto"}]


def test_bitflyer_and_sub_unit_currencies():
    s = FakeSession(lambda url, kw: {"ltp": 15_200_000 if kw["params"]["product_code"] == "BTC_JPY" else None})
    assert market.fetch_bitflyer(["btc_jpy", "XRP_JPY"], session=s) == {"BTC_JPY": 15_200_000.0}
    assert market.normalize_currency("GBp") == ("GBP", 100.0)
    assert market.normalize_currency("usd") == ("USD", 1.0)


def test_refresh_keeps_what_arrived(monkeypatch):
    monkeypatch.setattr(market, "yfinance_available", lambda: False)
    monkeypatch.setattr(market, "fetch_coingecko",
                        lambda by_vs, key="", timeout=10.0: {("bitcoin", "jpy"): (15_000_000.0, None)})
    req = market.MarketRequest(yahoo={"VOO": "USD"}, fx=["JPY"], coingecko={"jpy": {"bitcoin", "dogecoin"}})
    res = market.refresh(req)
    assert "yfinance" in res.errors and "VOO" in res.missing and "dogecoin" in res.missing
    assert [(p.key, p.price) for p in res.prices] == [(price_key("coingecko", "bitcoin@jpy"), 15_000_000.0)]


def test_yahoo_frames_in_both_layouts():
    pd = pytest.importorskip("pandas")
    idx = pd.to_datetime(["2026-11-04", "2026-11-05", "2026-11-06"])
    nan = float("nan")
    by_field = pd.DataFrame({("Close", "VOO"): [550.0, 557.0, 560.0], ("Close", "7203.T"): [2850.0, 2860.0, nan],
                             ("Open", "VOO"): [1.0, 1.0, 1.0]}, index=idx)
    by_field.columns = pd.MultiIndex.from_tuples(by_field.columns)
    out = market.fetch_yahoo(["VOO", "7203.T", "NONE"], downloader=lambda *a, **k: by_field)
    assert out == {"VOO": (560.0, 557.0), "7203.T": (2860.0, 2850.0)}
    by_ticker = by_field.swaplevel(axis=1)
    assert market.fetch_yahoo(["VOO"], downloader=lambda *a, **k: by_ticker)["VOO"] == (560.0, 557.0)
    single = pd.DataFrame({"Close": [10.0, 11.0]}, index=idx[:2])
    assert market.fetch_yahoo(["GC=F"], downloader=lambda *a, **k: single) == {"GC=F": (11.0, 10.0)}
    assert market.fetch_yahoo(["VOO"], downloader=lambda *a, **k: pd.DataFrame()) == {}

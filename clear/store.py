"""Application state shared by all pages: config, the open data file, rates and backups.

Every write goes through the Store, which then emits ``changed`` so the visible
page redraws from fresh data (no page edits another page's widgets).
"""

from __future__ import annotations

import logging
import os
import shutil
from datetime import date, datetime
from pathlib import Path

from PyQt6.QtCore import QObject, QThread, pyqtSignal

from . import backup, db, engine, invest, logsetup, market, paths, rates
from .config import AppConfig, save_config
from .models import Bill, CreditCard, Holding, LivingCost, NetWorthPoint, Profile
from .money import CURRENCIES, convert
from .periods import Period
from .repo import ClosePlan, ContribBuy, Repository

log = logging.getLogger(__name__)


class RateWorker(QThread):
    ok = pyqtSignal(dict)
    failed = pyqtSignal(str)

    def run(self) -> None:  # runs in a worker thread: never touches widgets
        try:
            self.ok.emit(rates.fetch_rates())
        except Exception as exc:  # network down, timeout, bad JSON …
            self.failed.emit(str(exc))


class MarketWorker(QThread):
    done = pyqtSignal(object)       # market.MarketResult

    def __init__(self, request: market.MarketRequest, parent=None):
        super().__init__(parent)
        self.request = request

    def run(self) -> None:  # worker thread: never touches widgets
        try:
            result = market.refresh(self.request)
        except Exception as exc:  # pragma: no cover - refresh() already guards each source
            result = market.MarketResult(fetched_at=market.now_text())
            result.errors.append(str(exc))
        self.done.emit(result)


class TaskWorker(QThread):
    """Runs one blocking call (a search, a lookup) off the UI thread."""

    ok = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self.fn = fn

    def run(self) -> None:
        try:
            self.ok.emit(self.fn())
        except Exception as exc:
            self.failed.emit(str(exc))


class Store(QObject):
    changed = pyqtSignal()          # data in the open file changed (or another file was opened)
    view_changed = pyqtSignal()     # display currency / rates changed
    rates_status = pyqtSignal(bool, str)  # (success, message) after a fetch
    market_status = pyqtSignal(bool, str, bool)  # (all prices arrived, message, quiet) after a refresh

    def __init__(self, cfg: AppConfig, cfg_path: Path):
        super().__init__()
        self.cfg = cfg
        self.cfg_path = Path(cfg_path)
        self.repo: Repository | None = None
        self.last_saved: datetime | None = None
        self._state: engine.State | None = None
        self._worker: RateWorker | None = None
        self._market_worker: MarketWorker | None = None
        self._market_started: datetime | None = None
        self.data_dir = Path(cfg.data_dir) if cfg.data_dir else paths.default_data_dir()

    # ---- config ------------------------------------------------------------------------------
    def save_config(self) -> None:
        try:
            save_config(self.cfg, self.cfg_path)
        except OSError as exc:
            log.warning("could not save settings: %s", exc)

    @property
    def currency(self) -> str:
        return self.cfg.display_currency

    def set_currency(self, cur: str) -> None:
        if cur != self.cfg.display_currency:
            self.cfg.display_currency = cur
            self.save_config()
            self.view_changed.emit()

    @property
    def rates(self) -> dict:
        return self.cfg.rates

    def rates_updated_at(self) -> datetime | None:
        return rates.parse_ts(self.cfg.rates_updated_at)

    def rates_age_days(self) -> int | None:
        return rates.age_days(self.rates_updated_at())

    def set_rates(self, new_rates: dict, source: str) -> None:
        self.cfg.rates = {**self.cfg.rates, **new_rates, "USD": 1.0}
        self.cfg.rates_updated_at = datetime.now().replace(microsecond=0).isoformat()
        self.cfg.rates_source = source
        self.save_config()
        self.view_changed.emit()

    def fetch_rates(self, quiet: bool = False) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        self._worker = RateWorker(self)

        def ok(values: dict) -> None:
            self.set_rates(values, "auto")
            log.info("rates updated: %s", values)
            self.rates_status.emit(True, "")

        def failed(msg: str) -> None:
            log.warning("rates update failed: %s", msg)
            if not quiet:
                self.rates_status.emit(False, msg)

        self._worker.ok.connect(ok)
        self._worker.failed.connect(failed)
        self._worker.start()

    def auto_update_rates(self) -> None:
        if self.cfg.auto_update_rates and rates.due_for_update(self.rates_updated_at()):
            self.fetch_rates(quiet=True)

    def wait_for_rates(self, ms: int = 3000) -> None:
        if self._worker is not None:
            self._worker.wait(ms)
        if self._market_worker is not None:
            self._market_worker.wait(ms)

    # ---- market prices (I2) ------------------------------------------------------------------
    def market_request(self) -> market.MarketRequest:
        req = market.MarketRequest(coingecko_key=self.cfg.coingecko_key.strip())
        extra: set[str] = set()
        for h in self.state().holdings:
            ref = invest.quote_ref(h)
            if ref is None:
                continue
            source, symbol = ref
            if source == "yahoo":
                quote_cur = "USD" if h.kind == "metal" else (h.quote_currency or h.currency)
                req.yahoo[symbol] = quote_cur
                code, _div = market.normalize_currency(quote_cur)
                if code and code not in CURRENCIES:
                    extra.add(code)
            elif source == "coingecko":
                req.coingecko.setdefault(h.currency.lower(), set()).add(h.symbol)
            elif source == "bitflyer":
                req.bitflyer.append(symbol)
            if h.currency not in CURRENCIES:
                extra.add(h.currency)
        if not req.empty:
            req.fx = [c for c in CURRENCIES if c != "USD"] + sorted(extra)
        return req

    @property
    def market_busy(self) -> bool:
        return self._market_worker is not None and self._market_worker.isRunning()

    def refresh_market(self, force: bool = False, quiet: bool = True) -> bool:
        """Fetch prices in the background. Returns False when nothing was started."""
        if self.repo is None or self.market_busy:
            return False
        if not force and self._market_started is not None and \
                (datetime.now() - self._market_started).total_seconds() < market.MIN_INTERVAL_MINUTES * 60:
            return False
        req = self.market_request()
        if req.empty:
            return False
        self._market_started = datetime.now()
        worker = MarketWorker(req, self)
        worker.done.connect(lambda result: self._market_done(result, quiet))
        self._market_worker = worker
        worker.start()
        return True

    def _market_done(self, result: market.MarketResult, quiet: bool) -> None:
        if self.repo is not None and result.prices:
            try:
                self.repo.save_prices(result.prices)
            except Exception as exc:
                log.warning("could not store prices: %s", exc)
        if result.fx:
            self.cfg.rates = {**self.cfg.rates, **result.fx, "USD": 1.0}
            self.cfg.rates_updated_at = datetime.now().replace(microsecond=0).isoformat()
            self.cfg.rates_source = "yahoo"
            self.save_config()
        elif self.cfg.auto_update_rates and rates.due_for_update(self.rates_updated_at()):
            self.fetch_rates(quiet=True)
        log.info("market refresh: %d prices, fx %s, missing %s, errors %s", len(result.prices), sorted(result.fx),
                 result.missing, result.errors)
        ok = not result.errors and not result.missing
        message = "\n".join(result.errors + ([", ".join(sorted(set(result.missing)))] if result.missing else []))
        self._touch(saved=False)
        if not quiet or not ok:
            self.market_status.emit(ok, message, quiet)

    def prices_fetched_at(self) -> datetime | None:
        stamps = [invest.parse_time(p.fetched_at) for p in self.state().prices.values()]
        stamps = [s for s in stamps if s is not None]
        return max(stamps) if stamps else None

    # ---- data folder ---------------------------------------------------------------------------------
    def ensure_data_dir(self) -> bool:
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            probe = self.data_dir / ".clear-write-test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
        except OSError as exc:
            log.warning("data folder not usable %s: %s", self.data_dir, exc)
            return False
        logsetup.setup_logging(self.data_dir / "logs", paths.config_dir() / "logs")
        return True

    def set_data_dir(self, folder: Path, copy_files: bool = False) -> list[Path]:
        folder = Path(folder)
        copied: list[Path] = []
        old = self.data_dir
        self.data_dir = folder
        if not self.ensure_data_dir():
            self.data_dir = old
            raise OSError(str(folder))
        mapping: dict[Path, Path] = {}
        if copy_files and old.is_dir() and old.resolve() != folder.resolve():
            for src in sorted(old.glob("*.db")):
                dest = paths.unique_path(folder, src.name)
                shutil.copy2(src, dest)
                copied.append(dest)
                mapping[src.resolve()] = dest
        self.cfg.data_dir = str(folder)
        if self.repo is not None and self.repo.path.resolve() in mapping:
            self.repo = Repository(mapping[self.repo.path.resolve()])
        if self.repo is not None:
            self._remember(self.repo.path)
        self.save_config()
        log.info("data folder set to %s (copied %d files)", folder, len(copied))
        self._touch(saved=False)
        return copied

    @property
    def backups_root(self) -> Path:
        return self.data_dir / "backups"

    def list_db_files(self) -> list[Path]:
        try:
            files = sorted(self.data_dir.glob("*.db"), key=lambda p: p.name.casefold())
        except OSError:
            files = []
        if self.repo is not None and self.repo.path not in files:
            files.append(self.repo.path)
        return files

    def last_db_path(self) -> Path | None:
        if not self.cfg.last_db:
            return None
        p = Path(self.cfg.last_db)
        return p if p.is_absolute() else self.data_dir / p

    # ---- files ------------------------------------------------------------------------------------------
    @property
    def has_db(self) -> bool:
        return self.repo is not None

    @property
    def db_path(self) -> Path | None:
        return self.repo.path if self.repo else None

    def _remember(self, path: Path) -> None:
        try:
            rel = path.resolve().relative_to(self.data_dir.resolve())
            self.cfg.last_db = str(rel)
        except ValueError:
            self.cfg.last_db = str(path)
        self.save_config()

    def open_db(self, path: Path) -> db.MigrationReport:
        """Open a CLEAR file (legacy files must go through import_legacy).

        A file written by an earlier CLEAR is backed up first, then brought to the
        current layout (the backup opens with that earlier version if needed)."""
        path = Path(path)
        kind = db.classify(path)
        if kind == "legacy":
            raise LegacyFileError(str(path))
        if kind == "older":
            backup.make_backup(path, self.backups_root, "upgrade")
        repo, report = Repository.open(path, self.today())
        self.repo = repo
        self._remember(path)
        self.startup_backup()
        log.info("opened %s", path)
        self._touch(saved=False)
        return report

    def create_db(self, name: str, open_it: bool = True) -> Path:
        name = name.strip() or "CLEAR"
        if not name.lower().endswith(".db"):
            name += ".db"
        path = self.data_dir / name
        Repository.create(path, self.today())
        log.info("created %s", path)
        if open_it:
            self.repo = Repository(path)
            self._remember(path)
        self._touch(saved=False)
        return path

    def import_legacy(self, src: Path, open_it: bool = True) -> tuple[Path, db.MigrationReport]:
        """Copy a Payback Management file into the data folder and migrate the copy."""
        src = Path(src)
        dest = paths.unique_path(self.data_dir, src.name)
        shutil.copy2(src, dest)
        try:
            backup.make_backup(dest, self.backups_root, "import")
            repo, report = Repository.open(dest, self.today())
        except Exception:
            try:
                dest.rename(dest.with_suffix(".failed"))
            except OSError:
                pass
            raise
        log.info("imported %s -> %s", src, dest)
        if open_it:
            self.repo = repo
            self._remember(dest)
            self._touch(saved=False)
        return dest, report

    def startup_backup(self) -> None:
        if self.repo is None:
            return
        try:
            if not backup.has_backup_today(self.repo.path, self.backups_root, "startup"):
                backup.make_backup(self.repo.path, self.backups_root, "startup")
        except Exception as exc:
            log.warning("startup backup failed: %s", exc)

    # ---- state ------------------------------------------------------------------------------------------
    @staticmethod
    def today() -> date:
        override = os.environ.get("CLEAR_TODAY")
        if override:
            try:
                return date.fromisoformat(override)
            except ValueError:
                pass
        return date.today()

    def state(self) -> engine.State:
        if self._state is None:
            if self.repo is None:
                today = self.today()
                self._state = engine.State(today=today, last_closed=Period.from_date(today).add(-1))
            else:
                self._state = self.repo.load_state(self.today())
        return self._state

    def _touch(self, saved: bool = True) -> None:
        self._state = None
        if saved:
            self.last_saved = datetime.now()
        self.changed.emit()

    def _need(self) -> Repository:
        if self.repo is None:
            raise NoDatabaseError()
        return self.repo

    # ---- edits -------------------------------------------------------------------------------------------
    def add_bill(self, bill: Bill) -> None:
        self._need().add_bill(bill)
        self._touch()

    def update_bill(self, bill: Bill) -> None:
        self._need().update_bill(bill)
        self._touch()

    def delete_bill(self, bill_id: int) -> None:
        self._need().delete_bill(bill_id)
        self._touch()

    def reorder_bills(self, ids: list[int]) -> None:
        self._need().reorder_bills(ids)
        self._touch()

    def add_living(self, lc: LivingCost) -> None:
        self._need().add_living(lc)
        self._touch()

    def update_living(self, lc: LivingCost) -> None:
        self._need().update_living(lc)
        self._touch()

    def delete_living(self, lc_id: int) -> None:
        self._need().delete_living(lc_id)
        self._touch()

    def add_card(self, card: CreditCard) -> None:
        self._need().add_card(card)
        self._touch()

    def update_card(self, card: CreditCard) -> None:
        self._need().update_card(card)
        self._touch()

    def delete_card(self, card_id: int) -> None:
        self._need().delete_card(card_id)
        self._touch()

    def save_profile(self, profile: Profile) -> None:
        self._need().save_profile(profile)
        self._touch()

    def record_bill_payment(self, bill_id: int, paid_date: date, amount: float, interest: float | None,
                            note: str = "") -> None:
        self._need().record_bill_payment(bill_id, self.state().current, paid_date, amount, interest, note)
        self._touch()

    def record_living_payment(self, lc: LivingCost, paid_date: date | None = None,
                              amount: float | None = None) -> None:
        cur = self.state().current
        self._need().record_living_payment(lc.id, cur, paid_date or self.today(),
                                           lc.amount if amount is None else amount, lc.currency)
        self._touch()

    def update_bill_with_payment(self, bill: Bill, old_balance: float, paid_date: date, amount: float,
                                 note: str = "") -> None:
        """Save an edited debt whose balance went down as a payment of `amount` (B2).

        The interest part is what the payment covers beyond the drop in balance, so the
        balance ends exactly where the user put it and nothing is subtracted twice."""
        repo = self._need()
        new_balance = bill.amount
        drop = max(0.0, old_balance - new_balance)
        bill.amount = old_balance
        repo.update_bill(bill)
        repo.record_bill_payment(bill.id, self.state().current, paid_date, amount, max(0.0, amount - drop),
                                 note or "balance edit")
        self._touch()

    def pending_debits(self) -> list[engine.DueItem]:
        if self.repo is None:
            return []
        return engine.pending_debits(self.state(), self.rates, self.currency)

    def record_debits(self, rows: list[tuple[engine.DueItem, float]]) -> int:
        """Record automatic debits on their (business-day) dates. rows: (item, amount)."""
        repo = self._need()
        st = self.state()
        living = {lc.id: lc for lc in st.living}
        n = 0
        for it, amount in rows:
            if amount <= 0:
                continue
            if it.kind == "bill":
                repo.record_bill_payment(it.target_id, st.current, it.due, amount, None, "auto debit")
            elif it.kind == "living" and it.target_id in living:
                lc = living[it.target_id]
                repo.record_living_payment(lc.id, st.current, it.due, amount, lc.currency, "auto debit")
            else:
                continue
            n += 1
        self._touch()
        return n

    def set_fee_paid(self, card_id: int, paid: bool) -> None:
        self._need().set_fee_paid(card_id, self.state().current if paid else None)
        self._touch()

    # ---- investments ------------------------------------------------------------------------------------
    def add_holding(self, h: Holding) -> Holding:
        h = self._need().add_holding(h)
        self._touch()
        return h

    def update_holding(self, h: Holding) -> None:
        self._need().update_holding(h)
        self._touch()

    def delete_holding(self, holding_id: int) -> None:
        self._need().delete_holding(holding_id)
        self._touch()

    def reorder_holdings(self, ids: list[int]) -> None:
        self._need().reorder_holdings(ids)
        self._touch()

    def record_trade(self, holding_id: int, kind: str, trade_date: date, **kw) -> None:
        self._need().record_trade(holding_id, kind, trade_date, **kw)
        self._touch()

    def undo_last_trade(self, holding_id: int) -> bool:
        done = self._need().undo_last_trade(holding_id) is not None
        self._touch()
        return done

    def contribution_buy(self, h: Holding, trade_date: date) -> ContribBuy:
        """What a contribution buys at the latest price (quantity 0 when there is no price yet)."""
        st = self.state()
        amount = invest.contribution_in_holding_currency(h, self.rates)
        hv = invest.value_holding(h, st.prices, self.rates, h.currency)
        qty = 0.0
        price = 0.0
        if h.kind != "manual" and hv.unit_price:
            price = hv.unit_price
            qty = invest.round_qty(h.kind, amount / price)
        return ContribBuy(h.id, amount, qty, price, trade_date, h.contrib_method == "bank")

    def record_contribution(self, h: Holding, trade_date: date | None = None) -> ContribBuy | None:
        """Record this month's contribution at the latest price. None (nothing recorded) when a priced
        holding has no price yet, since the quantity bought cannot be worked out."""
        buy = self.contribution_buy(h, trade_date or self.today())
        if h.kind != "manual" and buy.quantity <= 0:
            return None
        self._need().record_trade(h.id, "buy", buy.trade_date, quantity=buy.quantity, price=buy.price,
                                  amount=buy.amount, is_contrib=True, cash_effect=buy.cash_effect,
                                  note="contribution")
        self._touch()
        return buy

    def undo_contribution(self, holding_id: int) -> bool:
        done = self._need().undo_last_trade(holding_id, self.state().current) is not None
        self._touch()
        return done

    def returns(self) -> dict[str, float]:
        return self.state().returns

    def save_returns(self, values: dict[str, float]) -> None:
        self._need().save_returns(values)
        self._touch()

    def net_worth_history(self) -> list[NetWorthPoint]:
        return self.repo.net_worth_history() if self.repo else []

    def _record_net_worth(self, period: Period) -> None:
        """P1: keep the net worth at the end of a closed month (approximately: today's prices)."""
        st = self.state()
        target, rts = self.currency, self.rates
        prof = st.profile
        savings = convert(prof.cumulative_savings, prof.cumulative_savings_currency, target, rts)
        debts = sum(convert(b.amount, b.currency, target, rts) for b in st.bills if b.amount > 0)
        debts += sum(convert(c.used_amount, c.currency, target, rts) for c in st.cards
                     if not c.managed_in_bills and c.used_amount > 0)
        value = invest.summarize(st.holdings, st.prices, rts, target).value
        projected = None
        if period.add(1) == st.current:
            rows = engine.simulate(st, 1, rts, target)
            projected = rows[0].net_worth if rows else None
        self._need().save_net_worth(NetWorthPoint(str(period), target, savings, value, debts,
                                                  savings + value - debts, projected, rates=dict(rts)))

    def undo_payment(self, target_type: str, target_id: int) -> bool:
        done = self._need().undo_last_payment(target_type, target_id, self.state().current)
        self._touch()
        return done

    # ---- month-end close --------------------------------------------------------------------------------
    def due_close_periods(self) -> list[Period]:
        return self.state().due_close_periods() if self.repo else []

    def close_month(self, plan: ClosePlan) -> dict:
        repo = self._need()
        snap = backup.make_backup(repo.path, self.backups_root, "close")
        summary = repo.close_month(plan, snap.name)
        log.info("closed %s: %s", plan.period, summary)
        self._state = None
        try:
            self._record_net_worth(plan.period)
        except Exception as exc:  # the close itself is done; the history is a bonus
            log.warning("net worth not recorded: %s", exc)
        self._touch()
        return summary

    def skip_close(self, until: Period) -> int:
        repo = self._need()
        snap = backup.make_backup(repo.path, self.backups_root, "close")
        n = repo.skip_close(until, snap.name)
        log.info("closed without changes up to %s (%d months)", until, n)
        self._touch()
        return n

    def latest_close(self) -> dict | None:
        return self.repo.latest_close() if self.repo else None

    def undo_last_close(self) -> str | None:
        """Restore the backup taken right before the latest close. Returns the period, or None."""
        repo = self._need()
        last = repo.latest_close()
        if not last or not last.get("backup_file"):
            return None
        snap = backup.backup_dir(self.backups_root, repo.path) / last["backup_file"]
        if not snap.exists():
            return None
        backup.restore(snap, repo.path, self.backups_root)
        log.info("undid close of %s", last["period"])
        self._touch()
        return last["period"]

    # ---- backups ----------------------------------------------------------------------------------------
    def backups(self) -> list[backup.BackupInfo]:
        if self.repo is None:
            return []
        return backup.list_backups(self.repo.path, self.backups_root)

    def make_backup(self) -> Path:
        return backup.make_backup(self._need().path, self.backups_root, "manual")

    def restore_backup(self, path: Path) -> None:
        backup.restore(path, self._need().path, self.backups_root)
        self._touch()


class LegacyFileError(Exception):
    """The chosen file is a Payback Management file: import it instead of opening it in place."""


class NoDatabaseError(Exception):
    """An edit was attempted while no data file is open."""

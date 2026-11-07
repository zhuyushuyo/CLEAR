"""Per-computer settings (JSON in the user's config folder, never inside the app folder)."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from .info import APP_VERSION
from .money import CURRENCIES, DEFAULT_RATES

log = logging.getLogger(__name__)

# Columns hidden until the user changes them (index per table).
DEFAULT_HIDDEN = {"bills": [13], "cards": [13], "living": [8, 9], "plan": [], "invest": [11, 12, 13]}

# Version of the table column layouts. 1 = 4.0, 2 = 4.1 (cards: one annual-fee column;
# plan: contributions and investments), 3 = 4.1.2 (plan: savings minus debt before net worth).
# Saved hidden columns and widths are moved to the new positions once, one step at a time.
COLUMNS_VERSION = 3
_CARDS_1_TO_2 = {**{i: i for i in range(11)}, 12: 11, 13: 12, 14: 13}       # old 11 (fee status) is merged
_PLAN_1_TO_2 = {0: 0, 1: 1, 2: 2, 3: 3, 4: 5, 5: 6, 6: 8, 7: 9}
_PLAN_2_TO_3 = {**{i: i for i in range(9)}, 9: 10}


@dataclass
class AppConfig:
    data_dir: str = ""
    last_db: str = ""
    theme: str = "system"          # system | light | dark
    language: str = "ja"           # ja | en
    display_currency: str = "JPY"
    rates: dict = field(default_factory=lambda: dict(DEFAULT_RATES))
    rates_updated_at: str = ""
    rates_source: str = ""         # auto | manual
    auto_update_rates: bool = True
    hidden_columns: dict = field(default_factory=lambda: {k: list(v) for k, v in DEFAULT_HIDDEN.items()})
    column_widths: dict = field(default_factory=dict)
    window: dict = field(default_factory=dict)
    welcome_done: bool = False
    auto_refresh_prices: bool = True   # fetch market prices at start-up (at most every 15 minutes)
    coingecko_key: str = ""            # optional free "Demo" key
    debit_prompt_date: str = ""        # last day the "record automatic debits" dialog was shown
    columns_version: int = COLUMNS_VERSION
    version: str = APP_VERSION

    def hidden(self, table: str) -> set[int]:
        return set(self.hidden_columns.get(table, DEFAULT_HIDDEN.get(table, [])))


def load_config(path: Path) -> AppConfig:
    cfg = AppConfig()
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return cfg
    except (OSError, ValueError) as exc:
        log.warning("config unreadable (%s); using defaults", exc)
        try:
            Path(path).rename(Path(path).with_suffix(".broken.json"))
        except OSError:
            pass
        return cfg
    defaults = asdict(cfg)
    for f in fields(AppConfig):
        if f.name in data and isinstance(data[f.name], type(defaults[f.name])):
            setattr(cfg, f.name, data[f.name])
    if "columns_version" not in data:  # written by 4.0
        cfg.columns_version = 1
    _migrate_columns(cfg)
    if cfg.theme not in ("system", "light", "dark"):
        cfg.theme = "system"
    if cfg.language not in ("ja", "en"):
        cfg.language = "ja"
    if cfg.display_currency not in CURRENCIES:
        cfg.display_currency = "JPY"
    rates = dict(DEFAULT_RATES)
    for k, v in (cfg.rates or {}).items():
        try:
            # the four display currencies, plus any other currency an investment is quoted in
            if (k in CURRENCIES or (len(k) == 3 and k.isalpha() and k.isupper())) and float(v) > 0:
                rates[k] = float(v)
        except (TypeError, ValueError):
            pass
    rates["USD"] = 1.0
    cfg.rates = rates
    return cfg


def _remap(indexes, mapping: dict[int, int]) -> list[int]:
    out = []
    for i in indexes or []:
        if isinstance(i, int) and i in mapping:
            out.append(mapping[i])
    return sorted(set(out))


def _remap_widths(widths, mapping: dict[int, int], size: int) -> list[int]:
    if not isinstance(widths, list) or not widths:
        return []
    new = [0] * size
    for old, w in enumerate(widths):
        if old in mapping and isinstance(w, (int, float)):
            new[mapping[old]] = int(w)
    return new


def _migrate_columns(cfg: AppConfig) -> None:
    """Move saved hidden columns and widths to the current column positions (once per version)."""
    if cfg.columns_version >= COLUMNS_VERSION:
        return
    hidden = dict(cfg.hidden_columns or {})
    widths = dict(cfg.column_widths or {})
    if cfg.columns_version < 2:  # 4.0 -> 4.1
        if "cards" in hidden:
            hidden["cards"] = _remap(hidden["cards"], _CARDS_1_TO_2)
        if "plan" in hidden:
            hidden["plan"] = _remap(hidden["plan"], _PLAN_1_TO_2)
        if widths.get("cards"):
            new = _remap_widths(widths["cards"], _CARDS_1_TO_2, 14)
            new[10] = max(new[10], 210)  # the annual-fee column now carries the status as well
            widths["cards"] = new
        if widths.get("plan"):
            widths["plan"] = _remap_widths(widths["plan"], _PLAN_1_TO_2, 10)
        hidden.setdefault("invest", list(DEFAULT_HIDDEN["invest"]))
    if cfg.columns_version < 3:  # 4.1 -> 4.1.2
        if "plan" in hidden:
            hidden["plan"] = _remap(hidden["plan"], _PLAN_2_TO_3)
        if widths.get("plan"):
            widths["plan"] = _remap_widths(widths["plan"], _PLAN_2_TO_3, 11)
    cfg.hidden_columns = hidden
    cfg.column_widths = widths
    cfg.columns_version = COLUMNS_VERSION


def save_config(cfg: AppConfig, path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    cfg.version = APP_VERSION
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(asdict(cfg), ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)

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
DEFAULT_HIDDEN = {"bills": [13], "cards": [11, 14], "living": [8, 9], "plan": []}


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
    if cfg.theme not in ("system", "light", "dark"):
        cfg.theme = "system"
    if cfg.language not in ("ja", "en"):
        cfg.language = "ja"
    if cfg.display_currency not in CURRENCIES:
        cfg.display_currency = "JPY"
    rates = dict(DEFAULT_RATES)
    for k, v in (cfg.rates or {}).items():
        try:
            if k in CURRENCIES and float(v) > 0:
                rates[k] = float(v)
        except (TypeError, ValueError):
            pass
    rates["USD"] = 1.0
    cfg.rates = rates
    return cfg


def save_config(cfg: AppConfig, path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    cfg.version = APP_VERSION
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(asdict(cfg), ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)

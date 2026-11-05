"""Where things live (R12 / F16).

* Settings: the user's config folder (per computer).
* Data (.db files, backups, logs): a folder chosen by the user. By default
  ``<App Development>/AppData/CLEAR`` when the app runs from inside the
  "App Development" Drive folder, otherwise ``~/Documents/CLEAR``.
"""

from __future__ import annotations

import os
import sys
import unicodedata
from pathlib import Path

from .info import APP_NAME, LEGACY_APP_NAME

ROOT_FOLDER_NAME = "App Development"
DATA_FOLDER_NAME = "AppData"


def app_dir() -> Path:
    """The folder that contains launch.py."""
    return Path(__file__).resolve().parent.parent


def config_dir() -> Path:
    override = os.environ.get("CLEAR_CONFIG_DIR")
    if override:
        return Path(override)
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / APP_NAME


def _norm(name: str) -> str:
    return unicodedata.normalize("NFC", name).casefold()


def find_root(start: Path | None = None) -> Path | None:
    """The nearest parent folder named "App Development"."""
    start = (start or app_dir()).resolve()
    for p in (start, *start.parents):
        if _norm(p.name) == _norm(ROOT_FOLDER_NAME):
            return p
    return None


def default_data_dir(start: Path | None = None) -> Path:
    root = find_root(start)
    if root is not None:
        return root / DATA_FOLDER_NAME / APP_NAME
    return Path.home() / "Documents" / APP_NAME


def display_path(path: Path | str) -> str:
    return unicodedata.normalize("NFC", str(path))


def find_legacy_databases(start: Path | None = None, limit: int = 40) -> list[Path]:
    """Payback Management 3.x data files (…/Payback Management/**/save/*.db), newest first.

    When the same file name exists in several version folders, only the newest copy is kept.
    """
    root = find_root(start)
    if root is None:
        return []
    found: dict[str, Path] = {}
    patterns = (f"*/*/*/{LEGACY_APP_NAME}", f"*/*/{LEGACY_APP_NAME}")
    for pattern in patterns:
        for base in root.glob(pattern):
            try:
                for db in base.rglob("save/*.db"):
                    key = _norm(db.name)
                    try:
                        mtime = db.stat().st_mtime
                    except OSError:
                        continue
                    if key not in found or mtime > found[key].stat().st_mtime:
                        found[key] = db
            except OSError:
                continue
    result = sorted(found.values(), key=lambda p: p.stat().st_mtime, reverse=True)
    return result[:limit]


def unique_path(folder: Path, name: str) -> Path:
    """folder/name, or folder/'name (2).db' … when it already exists."""
    candidate = folder / name
    stem, suffix = candidate.stem, candidate.suffix or ".db"
    n = 2
    while candidate.exists():
        candidate = folder / f"{stem} ({n}){suffix}"
        n += 1
    return candidate

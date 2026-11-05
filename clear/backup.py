"""Automatic backups (F15): dated copies made with SQLite's online-backup API."""

from __future__ import annotations

import logging
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

log = logging.getLogger(__name__)

KEEP = 30
SEP = "__"
REASONS = ("startup", "close", "manual", "import", "restore", "undo-close")


@dataclass
class BackupInfo:
    path: Path
    created: datetime
    reason: str
    size: int


def backup_dir(backups_root: Path, db_path: Path) -> Path:
    return Path(backups_root) / Path(db_path).stem


def _copy_db(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_suffix(".tmp")
    if tmp.exists():
        tmp.unlink()
    with closing(sqlite3.connect(str(src), timeout=15)) as s, closing(sqlite3.connect(str(tmp))) as d:
        s.backup(d)
    tmp.replace(dst)


def make_backup(db_path: Path, backups_root: Path, reason: str = "manual", keep: int = KEEP,
                now: datetime | None = None) -> Path:
    db_path = Path(db_path)
    now = now or datetime.now()
    folder = backup_dir(backups_root, db_path)
    name = f"{db_path.stem}{SEP}{now:%Y%m%d-%H%M%S}{SEP}{reason}.db"
    dest = folder / name
    n = 1
    while dest.exists():
        n += 1
        dest = folder / f"{db_path.stem}{SEP}{now:%Y%m%d-%H%M%S}-{n}{SEP}{reason}.db"
    _copy_db(db_path, dest)
    prune(folder, keep)
    log.info("backup %s (%s)", dest.name, reason)
    return dest


def parse_name(path: Path) -> tuple[datetime, str] | None:
    parts = path.stem.rsplit(SEP, 2)
    if len(parts) != 3:
        return None
    try:
        created = datetime.strptime(parts[1][:15], "%Y%m%d-%H%M%S")
    except ValueError:
        return None
    return created, parts[2]


def list_backups(db_path: Path, backups_root: Path) -> list[BackupInfo]:
    folder = backup_dir(backups_root, db_path)
    if not folder.is_dir():
        return []
    out = []
    for p in folder.glob("*.db"):
        parsed = parse_name(p)
        if parsed is None:
            continue
        try:
            size = p.stat().st_size
        except OSError:
            size = 0
        out.append(BackupInfo(p, parsed[0], parsed[1], size))
    out.sort(key=lambda b: (b.created, b.path.name), reverse=True)
    return out


def prune(folder: Path, keep: int = KEEP) -> None:
    files = [p for p in folder.glob("*.db") if parse_name(p)]
    files.sort(key=lambda p: (parse_name(p)[0], p.name), reverse=True)
    for old in files[keep:]:
        try:
            old.unlink()
        except OSError as exc:  # pragma: no cover - file locked by sync
            log.warning("could not remove old backup %s: %s", old, exc)


def has_backup_today(db_path: Path, backups_root: Path, reason: str, now: datetime | None = None) -> bool:
    today = (now or datetime.now()).date()
    return any(b.reason == reason and b.created.date() == today for b in list_backups(db_path, backups_root))


def restore(backup_path: Path, db_path: Path, backups_root: Path) -> Path:
    """Replace the database with a backup. The current state is saved first."""
    safety = make_backup(db_path, backups_root, "restore")
    _copy_db(Path(backup_path), Path(db_path))
    log.info("restored %s from %s", Path(db_path).name, Path(backup_path).name)
    return safety

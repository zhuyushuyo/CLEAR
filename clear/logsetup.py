"""Logging (O3): rotating file in the data folder, INFO level, no print()."""

from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path

FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
_handler: logging.Handler | None = None


def setup_logging(log_dir: Path, fallback_dir: Path | None = None) -> Path | None:
    """(Re)point the log file to `log_dir`. Returns the log file path, or None if no folder is writable."""
    global _handler
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for folder in (log_dir, fallback_dir):
        if folder is None:
            continue
        try:
            Path(folder).mkdir(parents=True, exist_ok=True)
            path = Path(folder) / "clear.log"
            handler = logging.handlers.RotatingFileHandler(path, maxBytes=512_000, backupCount=3,
                                                           encoding="utf-8")
        except OSError:
            continue
        handler.setFormatter(logging.Formatter(FORMAT))
        if _handler is not None:
            root.removeHandler(_handler)
            _handler.close()
        root.addHandler(handler)
        _handler = handler
        logging.getLogger("urllib3").setLevel(logging.WARNING)
        return path
    if not any(isinstance(h, logging.StreamHandler) for h in root.handlers):
        root.addHandler(logging.StreamHandler(sys.stderr))
    return None


def current_log_file() -> Path | None:
    if isinstance(_handler, logging.FileHandler):
        return Path(_handler.baseFilename)
    return None

"""Application entry point."""

from __future__ import annotations

import logging
import sys
import traceback

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication

from . import i18n, paths, theme
from .config import load_config
from .info import APP_NAME, APP_VERSION
from .logsetup import setup_logging

log = logging.getLogger("clear")


def _install_excepthook(get_window) -> None:
    def hook(exc_type, exc, tb):
        log.error("uncaught error:\n%s", "".join(traceback.format_exception(exc_type, exc, tb)))
        window = get_window()
        if window is not None:
            from .widgets import error
            try:
                error(window, i18n.t("err.unexpected", error=exc))
            except Exception:
                pass

    sys.excepthook = hook


def main(argv: list[str] | None = None) -> int:
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setStyle("Fusion")

    cfg_path = paths.config_dir() / "config.json"
    cfg = load_config(cfg_path)
    setup_logging(paths.config_dir() / "logs")  # moved into the data folder once it is known
    i18n.set_language(cfg.language)
    theme.apply(app, cfg.theme)

    from .main_window import MainWindow
    from .store import Store

    store = Store(cfg, cfg_path)
    store.ensure_data_dir()
    log.info("%s %s starting (Python %s)", APP_NAME, APP_VERSION, sys.version.split()[0])
    window = MainWindow(store)
    _install_excepthook(lambda: window)
    window.show()
    QTimer.singleShot(0, window.startup)
    code = app.exec()
    log.info("exit %s", code)
    return code

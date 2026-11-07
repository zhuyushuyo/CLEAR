"""Data & settings: data folder (F16), files, backups (F15), month-end close, rates (F14), display, about."""

from __future__ import annotations

import platform
import sys

from PyQt6.QtCore import PYQT_VERSION_STR, QT_VERSION_STR, Qt
from PyQt6.QtGui import QKeySequence
from PyQt6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QFormLayout, QGridLayout, QHBoxLayout,
                             QHeaderView, QTableWidget, QVBoxLayout)

from . import backup, logsetup, paths
from .i18n import LANGUAGES, fmt_datetime, fmt_period, reason_label, t
from .info import APP_AUTHOR, APP_FULL_NAME, APP_NAME, APP_VERSION, REPO_URL
from .money import CURRENCIES
from .shell import Page
from .widgets import RIGHT, Card, MoneySpin, button, item, label


class DataPage(Page):
    key = "data"
    title_key = "nav.data"
    icon_name = "fa5s.cog"

    def __init__(self, store, window):
        super().__init__(store, window)
        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(16)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        self.body.addLayout(grid)
        left = QVBoxLayout()
        left.setSpacing(16)
        right = QVBoxLayout()
        right.setSpacing(16)
        grid.addLayout(left, 0, 0)
        grid.addLayout(right, 0, 1)

        # -- data folder
        c = Card(t("data.location.title"), t("data.location.sub"))
        self.dir_label = label("", "Muted", wrap=True)
        self.dir_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        c.body.addWidget(self.dir_label)
        row = QHBoxLayout()
        row.addWidget(button(t("data.location.change"), None, "fa5s.folder", window.change_data_dir))
        row.addWidget(button(t("data.location.open"), None, "fa5s.folder-open",
                             lambda: window.open_folder(store.data_dir)))
        row.addStretch(1)
        c.body.addLayout(row)
        left.addWidget(c)

        # -- data file
        c = Card(t("data.file.title"))
        self.file_label = label("", None, wrap=True)
        self.file_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        c.body.addWidget(self.file_label)
        row = QHBoxLayout()
        row.addWidget(button(t("data.file.new"), None, "fa5s.plus", window.new_file))
        row.addWidget(button(t("data.file.open"), None, "fa5s.folder-open", window.open_file_dialog))
        self.save_as_btn = button(t("data.file.save_as"), None, "fa5s.copy", window.save_as)
        keys = QKeySequence("Ctrl+Shift+S").toString(QKeySequence.SequenceFormat.NativeText)
        self.save_as_btn.setToolTip(t("data.file.save_as_tip", keys=keys))
        row.addWidget(self.save_as_btn)
        row.addStretch(1)
        c.body.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(button(t("data.file.import"), None, "fa5s.file-import", window.import_dialog))
        row.addStretch(1)
        c.body.addLayout(row)
        left.addWidget(c)

        # -- backups
        c = Card(t("data.backup.title"), t("data.backup.sub", n=backup.KEEP))
        self.backups = QTableWidget(0, 3)
        self.backups.setHorizontalHeaderLabels([t("data.backup.col.when"), t("data.backup.col.reason"),
                                                t("data.backup.col.size")])
        self.backups.verticalHeader().setVisible(False)
        self.backups.verticalHeader().setDefaultSectionSize(30)
        self.backups.setShowGrid(False)
        self.backups.setAlternatingRowColors(True)
        self.backups.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.backups.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.backups.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.backups.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.backups.setColumnWidth(1, 140)
        self.backups.setColumnWidth(2, 80)
        self.backups.setMinimumHeight(220)
        c.body.addWidget(self.backups)
        row = QHBoxLayout()
        row.addWidget(button(t("data.backup.now"), None, "fa5s.save", window.backup_now))
        row.addWidget(button(t("data.backup.restore"), None, "fa5s.history", self._restore))
        row.addStretch(1)
        row.addWidget(button(t("data.location.open"), "ghost", None,
                             lambda: window.open_folder(store.backups_root)))
        c.body.addLayout(row)
        left.addWidget(c)
        left.addStretch(1)

        # -- month-end close
        c = Card(t("data.close.title"))
        self.close_info = label("", None, wrap=True)
        c.body.addWidget(self.close_info)
        row = QHBoxLayout()
        self.close_btn = button(t("data.close.start"), "primary", "fa5s.calendar-check", window.start_close)
        self.undo_btn = button(t("data.close.undo"), None, "fa5s.undo", window.undo_close)
        row.addWidget(self.close_btn)
        row.addWidget(self.undo_btn)
        row.addStretch(1)
        c.body.addLayout(row)
        right.addWidget(c)

        # -- exchange rates
        c = Card(t("data.rates.title"), t("data.rates.sub"))
        form = QFormLayout()
        form.setHorizontalSpacing(14)
        self.rate_spins: dict[str, MoneySpin] = {}
        for cur in CURRENCIES:
            if cur == "USD":
                continue
            spin = MoneySpin("USD")
            spin.setDecimals(4)
            spin.setRange(0.0001, 100000)
            spin.setMaximumWidth(180)
            self.rate_spins[cur] = spin
            form.addRow(f"1 USD = … {cur}", spin)
        c.body.addLayout(form)
        self.rates_when = label("", "Hint")
        c.body.addWidget(self.rates_when)
        self.auto_rates = QCheckBox(t("data.rates.auto"))
        self.auto_rates.toggled.connect(self._auto_toggled)
        c.body.addWidget(self.auto_rates)
        row = QHBoxLayout()
        self.fetch_btn = button(t("data.rates.fetch"), None, "fa5s.sync-alt", self._fetch)
        row.addWidget(self.fetch_btn)
        row.addWidget(button(t("common.save"), "primary", None, self._save_rates))
        row.addStretch(1)
        c.body.addLayout(row)
        right.addWidget(c)
        store.rates_status.connect(self._fetched)

        # -- display
        c = Card(t("data.view.title"))
        form = QFormLayout()
        form.setHorizontalSpacing(14)
        self.theme_combo = QComboBox()
        for code in ("system", "light", "dark"):
            self.theme_combo.addItem(t(f"theme.{code}"), code)
        self.lang_combo = QComboBox()
        for code, name in LANGUAGES.items():
            self.lang_combo.addItem(name, code)
        form.addRow(t("data.view.theme"), self.theme_combo)
        form.addRow(t("data.view.lang"), self.lang_combo)
        c.body.addLayout(form)
        row = QHBoxLayout()
        row.addWidget(button(t("data.view.columns"), None, "fa5s.columns", window.choose_columns))
        row.addStretch(1)
        c.body.addLayout(row)
        self.theme_combo.currentIndexChanged.connect(
            lambda: window.set_theme(self.theme_combo.currentData()))
        self.lang_combo.currentIndexChanged.connect(
            lambda: window.set_language(self.lang_combo.currentData()))
        right.addWidget(c)

        # -- about
        c = Card(t("data.about.title"))
        c.body.addWidget(label(f"{APP_NAME} {APP_VERSION}", "SectionTitle"))
        c.body.addWidget(label(APP_FULL_NAME, "Muted"))
        c.body.addWidget(label(t("data.about.desc"), "Muted", wrap=True))
        c.body.addWidget(label(t("data.about.dev", author=APP_AUTHOR), "Muted"))
        py = platform.python_version()
        c.body.addWidget(label(f"Python {py} · Qt {QT_VERSION_STR} · PyQt {PYQT_VERSION_STR} · {sys.platform}",
                               "Hint"))
        c.body.addWidget(label(t("data.about.libs"), "Hint"))
        row = QHBoxLayout()
        row.addWidget(button(t("data.about.logs"), None, "fa5s.file-alt", self._open_logs))
        row.addWidget(button("GitHub", "ghost", None, lambda: window.open_url(REPO_URL)))
        row.addStretch(1)
        c.body.addLayout(row)
        right.addWidget(c)
        right.addStretch(1)
        self._backup_paths: list = []

    # ---- refresh -----------------------------------------------------------------------------------------
    def refresh(self) -> None:
        store = self.store
        self.dir_label.setText(paths.display_path(store.data_dir))
        if store.db_path:
            self.file_label.setText(paths.display_path(store.db_path))
            self.file_label.setProperty("tone", "")
        else:
            self.file_label.setText(t("data.file.none"))
        self.save_as_btn.setEnabled(store.has_db)

        items = store.backups()
        self._backup_paths = [b.path for b in items]
        self.backups.setRowCount(max(1, len(items)))
        if not items:
            self.backups.setSpan(0, 0, 1, 3)
            self.backups.setItem(0, 0, item(t("data.backup.empty"), Qt.AlignmentFlag.AlignCenter, tone="text_muted"))
        else:
            self.backups.clearSpans()
            for r, b in enumerate(items):
                self.backups.setItem(r, 0, item(fmt_datetime(b.created), data=r))
                self.backups.setItem(r, 1, item(reason_label(b.reason), tone="text_muted"))
                self.backups.setItem(r, 2, item(f"{max(1, b.size // 1024)} KB", RIGHT, tone="text_muted"))

        st = store.state()
        due = store.due_close_periods()
        lines = [t("data.close.last", period=fmt_period(st.last_closed))]
        last = store.latest_close()
        if last and last.get("summary", {}).get("skipped"):
            lines[0] += " " + t("data.close.skipped")
        lines.append(t("data.close.due", periods=", ".join(fmt_period(p) for p in due)) if due
                     else t("data.close.up_to_date"))
        self.close_info.setText("\n".join(lines))
        self.close_btn.setEnabled(bool(due))
        self.undo_btn.setEnabled(bool(last and last.get("backup_file")))

        for cur, spin in self.rate_spins.items():
            spin.setValue(float(store.rates.get(cur, 1.0)))
        when = store.rates_updated_at()
        if when:
            src = t({"manual": "data.rates.src.manual", "yahoo": "data.rates.src.yahoo"}.get(
                store.cfg.rates_source, "data.rates.src.auto"))
            self.rates_when.setText(t("data.rates.updated", when=fmt_datetime(when), source=src))
        else:
            self.rates_when.setText(t("data.rates.never"))
        self.auto_rates.blockSignals(True)
        self.auto_rates.setChecked(store.cfg.auto_update_rates)
        self.auto_rates.blockSignals(False)

        for combo, value in ((self.theme_combo, store.cfg.theme), (self.lang_combo, store.cfg.language)):
            combo.blockSignals(True)
            combo.setCurrentIndex(max(0, combo.findData(value)))
            combo.blockSignals(False)

    # ---- actions --------------------------------------------------------------------------------------------
    def _restore(self) -> None:
        rows = self.backups.selectionModel().selectedRows()
        if not rows or not self._backup_paths:
            self.win.notify(t("common.select_row"))
            return
        r = rows[0].row()
        if r >= len(self._backup_paths):
            return
        self.win.restore_backup(self._backup_paths[r])

    def _fetch(self) -> None:
        self.fetch_btn.setEnabled(False)
        self.fetch_btn.setText(t("data.rates.fetching"))
        self.store.fetch_rates(quiet=False)

    def _fetched(self, ok: bool, msg: str) -> None:
        self.fetch_btn.setEnabled(True)
        self.fetch_btn.setText(t("data.rates.fetch"))
        if not self.isVisible():
            return
        if ok:
            self.win.notify(t("data.rates.fetched"))
        else:
            self.win.notify(t("data.rates.failed", error=msg), is_error=True)

    def _save_rates(self) -> None:
        self.store.set_rates({cur: spin.value() for cur, spin in self.rate_spins.items()}, "manual")
        self.win.notify(t("data.rates.saved"))

    def _auto_toggled(self, on: bool) -> None:
        self.store.cfg.auto_update_rates = on
        self.store.save_config()

    def _open_logs(self) -> None:
        log_file = logsetup.current_log_file()
        self.win.open_folder(log_file.parent if log_file else self.store.data_dir)

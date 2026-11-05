"""First start (F16): choose the data folder and bring in the Payback Management files."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QCheckBox, QDialog, QFileDialog, QHBoxLayout, QLineEdit, QListWidget,
                             QListWidgetItem, QVBoxLayout, QWidget)

from . import paths
from .i18n import fmt_date, t
from .widgets import button, divider, label


class WelcomeDialog(QDialog):
    def __init__(self, parent: QWidget | None, data_dir: Path, candidates: list[Path]):
        super().__init__(parent)
        self.setWindowTitle(t("welcome.title"))
        self.setMinimumSize(640, 560)
        self.data_dir = Path(data_dir)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(26, 24, 26, 20)
        lay.setSpacing(12)
        lay.addWidget(label(t("welcome.title"), "DialogTitle"))
        lay.addWidget(label(t("welcome.intro"), "Muted", wrap=True))
        lay.addWidget(divider())

        lay.addWidget(label(t("welcome.location"), "SectionTitle"))
        row = QHBoxLayout()
        self.dir_label = label(paths.display_path(self.data_dir), "Muted", wrap=True)
        self.dir_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        row.addWidget(self.dir_label, 1)
        row.addWidget(button(t("data.location.change"), slot=self._choose_dir))
        lay.addLayout(row)
        lay.addWidget(divider())

        lay.addWidget(label(t("welcome.import"), "SectionTitle"))
        lay.addWidget(label(t("welcome.import_hint"), "Hint", wrap=True))
        self.list = QListWidget()
        self.list.setMinimumHeight(150)
        root = paths.find_root()
        for p in candidates:
            self._add(p, root, checked=True)
        if not candidates:
            empty = QListWidgetItem(t("welcome.none_found"))
            empty.setFlags(Qt.ItemFlag.NoItemFlags)
            self.list.addItem(empty)
        lay.addWidget(self.list, 1)
        browse = QHBoxLayout()
        browse.addWidget(button(t("welcome.browse"), slot=self._browse))
        browse.addStretch(1)
        lay.addLayout(browse)
        lay.addWidget(divider())

        self.new_check = QCheckBox(t("welcome.new"))
        self.new_check.setChecked(not candidates)
        self.new_name = QLineEdit("CLEAR.db")
        self.new_name.setMaximumWidth(260)
        new_row = QHBoxLayout()
        new_row.addWidget(self.new_check)
        new_row.addWidget(label(t("welcome.new_name"), "Muted"))
        new_row.addWidget(self.new_name)
        new_row.addStretch(1)
        lay.addLayout(new_row)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(button(t("welcome.later"), slot=self.reject))
        buttons.addWidget(button(t("welcome.start"), "primary", slot=self.accept))
        lay.addLayout(buttons)

    def _add(self, p: Path, root: Path | None, checked: bool) -> None:
        try:
            shown = p.relative_to(root) if root else p
        except ValueError:
            shown = p
        try:
            when = fmt_date(datetime.fromtimestamp(p.stat().st_mtime).date())
        except OSError:
            when = "—"
        text = f"{p.name}\n{paths.display_path(shown.parent)}  ·  {t('welcome.modified', date=when)}"
        it = QListWidgetItem(text)
        it.setData(Qt.ItemDataRole.UserRole, str(p))
        it.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
        it.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        self.list.addItem(it)

    def _choose_dir(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, t("dlg.choose_folder"), str(self.data_dir.parent))
        if folder:
            self.data_dir = Path(folder)
            self.dir_label.setText(paths.display_path(self.data_dir))

    def _browse(self) -> None:
        start = str(paths.find_root() or Path.home())
        files, _ = QFileDialog.getOpenFileNames(self, t("welcome.browse"), start, t("dlg.db_filter"))
        if files and self.list.count() == 1 and not self.list.item(0).data(Qt.ItemDataRole.UserRole):
            self.list.clear()
        for f in files:
            self._add(Path(f), paths.find_root(), checked=True)

    def selected_imports(self) -> list[Path]:
        out = []
        for i in range(self.list.count()):
            it = self.list.item(i)
            value = it.data(Qt.ItemDataRole.UserRole)
            if value and it.checkState() == Qt.CheckState.Checked:
                out.append(Path(value))
        return out

    def new_file_name(self) -> str | None:
        return self.new_name.text().strip() or "CLEAR.db" if self.new_check.isChecked() else None

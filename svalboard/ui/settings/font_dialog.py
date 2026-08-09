# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 白い熊
"""The font picker: every candidate rendered in its own glyphs.

Listing font names in a uniform face tells you nothing about what you are choosing,
so each row is drawn in the face it names. External faces are imported by copying the
file into the application's own font directory, which is what the family's keyboard
does, rather than enumerating the system's fonts.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont, QFontDatabase
from PyQt6.QtWidgets import (
    QDialog,
    QFileDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..theme import FONT_SAMPLE, Theme
from ..widgets.house import button_row, themed_font

SYSTEM = ""
ACCEPTED = (".ttf", ".otf")


def font_directory() -> Path:
    directory = Path.home() / ".local" / "share" / "shiroikuma-svalboard" / "fonts"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def load_imported_fonts() -> list[str]:
    """Register every imported face with Qt. Returns the family names."""
    families: list[str] = []
    for path in sorted(font_directory().iterdir(), key=lambda p: p.name.lower()):
        if path.suffix.lower() not in ACCEPTED:
            continue
        identifier = QFontDatabase.addApplicationFont(str(path))
        if identifier >= 0:
            families.extend(QFontDatabase.applicationFontFamilies(identifier))
    # A file that fails to load is skipped rather than fatal; a broken font should
    # not stop the program starting.
    return sorted(set(families))


class FontDialog(QDialog):
    def __init__(
        self,
        theme: Theme,
        current: str,
        *,
        title: str,
        on_change: Callable[[str], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._theme = theme
        self._on_change = on_change
        self._initial = current
        self.setWindowTitle(title)
        self.setModal(True)
        self.resize(520, 560)

        column = QVBoxLayout(self)
        padding = int(theme["dialog.padding"])
        column.setContentsMargins(padding, padding, padding, padding)
        column.setSpacing(12)

        heading = QLabel(title)
        heading.setFont(
            themed_font(
                str(theme["dialog.title.font"]),
                int(theme["dialog.title.weight"]),
                int(theme["dialog.title.size"]),
            )
        )
        heading.setStyleSheet(f"color: {theme.css('dialog.title.colour')};")
        column.addWidget(heading)

        self.list = QListWidget()
        self.list.currentItemChanged.connect(self._on_selection)
        column.addWidget(self.list, 1)

        self.sample = QLabel(FONT_SAMPLE)
        self.sample.setWordWrap(True)
        self.sample.setMinimumHeight(64)
        column.addWidget(self.sample)

        column.addWidget(
            button_row(
                theme,
                ("Cancel", self._cancel),
                [("Import font…", self._import), ("OK", self.accept)],
            )
        )
        self.setStyleSheet(
            f"QDialog {{"
            f"background: {theme.css('dialog.background')};"
            f"border: {theme['dialog.border_width']}px solid {theme.css('dialog.border')};"
            f"}}"
        )
        self._populate(current)

    def _populate(self, current: str) -> None:
        self.list.clear()
        families = [SYSTEM, "Monospace", *load_imported_fonts()]
        for family in families:
            label = "System default" if family == SYSTEM else family
            item = QListWidgetItem(("✓  " if family == current else "") + label)
            item.setData(Qt.ItemDataRole.UserRole, family)
            font = themed_font(family, 400, 14)
            item.setFont(font)
            self.list.addItem(item)
            if family == current:
                self.list.setCurrentItem(item)

    def _on_selection(self, item: QListWidgetItem | None, _previous) -> None:
        if item is None:
            return
        family = str(item.data(Qt.ItemDataRole.UserRole))
        self.sample.setFont(themed_font(family, 400, 15))
        self.sample.setStyleSheet(f"color: {self._theme.css('window.text')};")
        self._on_change(family)

    def value(self) -> str:
        item = self.list.currentItem()
        return str(item.data(Qt.ItemDataRole.UserRole)) if item else self._initial

    def _import(self) -> None:
        chosen, _filter = QFileDialog.getOpenFileName(
            self, "Import a font", str(Path.home()), "Fonts (*.ttf *.otf)"
        )
        if not chosen:
            return
        source = Path(chosen)
        if source.suffix.lower() not in ACCEPTED:
            return
        shutil.copy2(source, font_directory() / source.name)
        self._populate(self.value())

    def _cancel(self) -> None:
        self._on_change(self._initial)
        self.reject()

    def reject(self) -> None:
        self._on_change(self._initial)
        super().reject()

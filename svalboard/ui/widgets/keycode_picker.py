# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 白い熊
"""Choosing a keycode: categories, and a search box across all of them.

The web configurator spreads roughly 1,600 keycodes over a dozen tabs with no search,
so finding one means already knowing which tab it lives in. Here the search runs
across every name, label and description at once, and it is the first thing focused.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFontMetricsF
from PyQt6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ...protocol.keycodes import KeycodeInfo, KeycodeSet
from ..theme import Theme
from .house import themed_font
from .keyboard_canvas import KIND_TINTS


class KeycodeButton(QWidget):
    """One pickable keycode, drawn like a key so the picker reads as a keyboard."""

    chosen = pyqtSignal(object)

    def __init__(self, info: KeycodeInfo, theme: Theme, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._info = info
        self._theme = theme
        self._hovered = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(
            f"{info.name}\n{info.tooltip}" if info.tooltip != info.name else info.name
        )
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        theme.changed.connect(self._resize_to_theme)
        self._resize_to_theme()

    def info(self) -> KeycodeInfo:
        return self._info

    def _resize_to_theme(self) -> None:
        unit = int(self._theme["picker.unit"])
        self.setFixedSize(unit, unit)
        self.update()

    def enterEvent(self, event) -> None:  # noqa: N802  (Qt naming)
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.chosen.emit(self._info)
        super().mouseReleaseEvent(event)

    def paintEvent(self, _event) -> None:  # noqa: N802
        from PyQt6.QtGui import QPainter, QPainterPath, QPen
        from PyQt6.QtCore import QRectF

        theme = self._theme
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        radius = float(theme["key.corner"])
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        painter.fillPath(path, theme.colour("key.background"))

        border = theme.colour(KIND_TINTS.get(self._info.kind, "key.border"))
        width = float(theme["key.border_width"]) * (1.8 if self._hovered else 1.0)
        painter.setPen(QPen(border, width))
        painter.drawPath(path)

        text = self._info.label or self._info.name.removeprefix("KC_")
        size = float(theme["key.label.size"])
        font = themed_font(str(theme["key.label.font"]), int(theme["key.label.weight"]), size)
        for _ in range(8):
            font.setPointSizeF(size)
            widest = max(
                (QFontMetricsF(font).horizontalAdvance(line) for line in text.split("\n")),
                default=0.0,
            )
            if widest <= rect.width() - 4 or size <= 5.0:
                break
            size -= 1.0
        painter.setFont(font)
        painter.setPen(theme.colour("key.label.colour"))
        painter.drawText(
            rect, int(Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap), text
        )


class KeycodePicker(QWidget):
    """A search box, a category chooser, and a grid of keycodes."""

    keycodeChosen = pyqtSignal(object)

    #: Tabs built from the connected keyboard rather than the static table.
    RUNTIME_CATEGORIES = ("Svalboard", "Layers", "Macros", "Tap dances")

    def __init__(self, theme: Theme, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._theme = theme
        self._keycodes: KeycodeSet | None = None

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search every keycode — name, label or description")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._refresh)

        self.category = QComboBox()
        self.category.currentIndexChanged.connect(lambda _index: self._refresh())

        self.status = QLabel()
        self.status.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(8)
        controls.addWidget(self.search, 1)
        controls.addWidget(self.category)
        controls.addWidget(self.status)

        self._grid_host = QWidget()
        self._grid = QGridLayout(self._grid_host)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._grid_host)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        column = QVBoxLayout(self)
        column.setContentsMargins(8, 8, 8, 8)
        column.setSpacing(6)
        column.addLayout(controls)
        column.addWidget(scroll, 1)

        theme.changed.connect(self._refresh)

    # -- data --------------------------------------------------------------------

    def set_keycodes(self, keycodes: KeycodeSet, custom_names: list[str]) -> None:
        self._keycodes = keycodes
        self._custom_names = custom_names

        blocked = self.category.blockSignals(True)
        self.category.clear()
        self.category.addItems([*self.RUNTIME_CATEGORIES, *keycodes.categories()])
        # Basic is where a keymap edit almost always starts.
        index = self.category.findText("basic")
        self.category.setCurrentIndex(index if index >= 0 else 0)
        self.category.blockSignals(blocked)
        self._refresh()

    def focus_search(self) -> None:
        self.search.setFocus()
        self.search.selectAll()

    # -- contents ----------------------------------------------------------------

    def _entries(self) -> list[KeycodeInfo]:
        if self._keycodes is None:
            return []
        query = self.search.text().strip()
        if query:
            # Search deliberately ignores the category: not knowing which tab a
            # keycode lives in is the whole reason to search.
            return self._keycodes.search(query, limit=240)

        name = self.category.currentText()
        if name == "Svalboard":
            return [
                self._keycodes.info(self._keycodes.parse(qmk_id))
                for qmk_id in self._custom_names
            ]
        if name == "Layers":
            return [
                self._keycodes.info(self._keycodes.parse(f"{prefix}({layer})"))
                for prefix in ("MO", "TO", "DF", "TG", "OSL", "TT")
                for layer in range(self._keycodes.layers)
            ]
        if name == "Macros":
            return [
                self._keycodes.info(self._keycodes.parse(f"M{index}"))
                for index in range(self._keycodes.macros)
            ]
        if name == "Tap dances":
            return [
                self._keycodes.info(self._keycodes.parse(f"TD({index})"))
                for index in range(self._keycodes.tap_dances)
            ]
        return self._keycodes.category(name)

    def _refresh(self) -> None:
        while (item := self._grid.takeAt(0)) is not None:
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        entries = self._entries()
        columns = max(1, int(self._theme["picker.columns"]))
        spacing = int(self._theme["picker.spacing"])
        self._grid.setHorizontalSpacing(spacing)
        self._grid.setVerticalSpacing(spacing)

        for position, info in enumerate(entries):
            button = KeycodeButton(info, self._theme)
            button.chosen.connect(self.keycodeChosen)
            self._grid.addWidget(button, position // columns, position % columns)

        query = self.search.text().strip()
        if query and not entries:
            self.status.setText("nothing found")
        elif query:
            self.status.setText(f"{len(entries)} found")
        else:
            self.status.setText(f"{len(entries)}")

# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 白い熊
"""The row of layer buttons above the board."""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QWidget

from ..theme import Theme
from .house import themed_font


class LayerButton(QLabel):
    clicked = pyqtSignal(int)
    renameRequested = pyqtSignal(int)

    def __init__(self, index: int, theme: Theme, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.index = index
        self._theme = theme
        self._active = False
        self._used = True
        self._changed = False
        self._name = ""
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(
            lambda _pos: self.renameRequested.emit(self.index)
        )
        theme.changed.connect(self.restyle)
        self.restyle()

    def set_state(self, *, active: bool, used: bool, changed: bool, name: str = "") -> None:
        self._active, self._used, self._changed, self._name = active, used, changed, name
        self.restyle()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802  (Qt naming)
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.index)
        super().mouseReleaseEvent(event)

    def restyle(self) -> None:
        theme = self._theme
        label = self._name or str(self.index)
        # An edited layer is marked in the strip so a pending change on a layer you
        # are not looking at is still visible.
        self.setText(f"{label} •" if self._changed else label)

        if self._active:
            colour = theme.css("layer.active")
        elif not self._used:
            colour = theme.css("layer.empty")
        else:
            colour = theme.css("layer.inactive")

        self.setFont(
            themed_font(
                str(theme["layer.label.font"]),
                int(theme["layer.label.weight"]),
                int(theme["layer.label.size"]),
            )
        )
        width = 2 if self._active else 1
        self.setStyleSheet(
            f"color: {colour};"
            f"border: {width}px solid {colour};"
            f"border-radius: 4px;"
            f"padding: 3px 10px;"
        )


class LayerStrip(QWidget):
    """Click to switch layer, right-click to rename it."""

    layerSelected = pyqtSignal(int)
    renameRequested = pyqtSignal(int)

    def __init__(self, theme: Theme, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._theme = theme
        self._buttons: list[LayerButton] = []
        self._current = 0

        self._row = QHBoxLayout(self)
        self._row.setContentsMargins(8, 6, 8, 6)
        self._row.addStretch(1)
        theme.changed.connect(self._respace)
        self._respace()

    def _respace(self) -> None:
        self._row.setSpacing(int(self._theme["layer.spacing"]))

    def build(self, layers: int) -> None:
        for button in self._buttons:
            button.deleteLater()
        self._buttons.clear()
        while self._row.count():
            self._row.takeAt(0)

        for index in range(layers):
            button = LayerButton(index, self._theme)
            button.clicked.connect(self._on_click)
            button.renameRequested.connect(self.renameRequested)
            self._buttons.append(button)
            self._row.addWidget(button)
        self._row.addStretch(1)
        self._respace()

    def _on_click(self, index: int) -> None:
        self._current = index
        self.layerSelected.emit(index)

    def current(self) -> int:
        return self._current

    def set_current(self, index: int) -> None:
        self._current = index

    def refresh(
        self,
        *,
        used: set[int],
        changed: set[int],
        names: dict[int, str] | None = None,
    ) -> None:
        names = names or {}
        for button in self._buttons:
            button.set_state(
                active=button.index == self._current,
                used=button.index in used,
                changed=button.index in changed,
                name=names.get(button.index, ""),
            )

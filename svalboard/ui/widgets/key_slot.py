# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 白い熊
"""A keycode field: click it, then pick a keycode from the picker below.

Every editor binds through one of these, so there is a single picker at the bottom of
the window serving the board and all four entry editors. Selecting a slot arms it; the
next keycode chosen lands in it.
"""

from __future__ import annotations

from PyQt6.QtCore import QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QFontMetricsF, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QSizePolicy, QWidget

from ...protocol.keycodes import KeycodeSet
from ..theme import Theme
from .house import themed_font
from .keyboard_canvas import KIND_TINTS


class KeySlot(QWidget):
    """Shows one keycode and asks to be filled when clicked."""

    armed = pyqtSignal(object)
    cleared = pyqtSignal(object)

    def __init__(
        self,
        theme: Theme,
        keycodes: KeycodeSet,
        *,
        code: int = 0,
        width: int = 92,
        height: int = 40,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._theme = theme
        self._keycodes = keycodes
        self._code = code
        self._active = False
        self._changed = False
        self.setFixedSize(width, height)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(lambda _p: self.cleared.emit(self))
        theme.changed.connect(self.update)
        self._refresh_tooltip()

    # -- state -------------------------------------------------------------------

    def code(self) -> int:
        return self._code

    def set_code(self, code: int) -> None:
        self._code = code & 0xFFFF
        self._refresh_tooltip()
        self.update()

    def set_active(self, active: bool) -> None:
        if active != self._active:
            self._active = active
            self.update()

    def set_changed(self, changed: bool) -> None:
        if changed != self._changed:
            self._changed = changed
            self.update()

    def _refresh_tooltip(self) -> None:
        info = self._keycodes.info(self._code)
        detail = info.tooltip if info.tooltip != info.name else ""
        self.setToolTip(
            f"{info.name}\n{detail}\n\nClick to set, right-click to clear."
            if detail
            else f"{info.name}\n\nClick to set, right-click to clear."
        )

    # -- events ------------------------------------------------------------------

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802  (Qt naming)
        if event.button() == Qt.MouseButton.LeftButton:
            self.armed.emit(self)
        super().mouseReleaseEvent(event)

    # -- painting ----------------------------------------------------------------

    def paintEvent(self, _event) -> None:  # noqa: N802
        theme = self._theme
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        radius = float(theme["key.corner"])
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        painter.fillPath(path, theme.colour("key.background"))

        info = self._keycodes.info(self._code)
        border = theme.colour("key.border")
        width = float(theme["key.border_width"])
        if info.is_empty:
            border = theme.colour("state.empty")
        elif info.kind in KIND_TINTS:
            border = theme.colour(KIND_TINTS[info.kind])
        if self._changed:
            border = theme.colour("state.changed")
        if self._active:
            border, width = theme.colour("state.selected"), width * 2.5
        painter.setPen(QPen(border, width))
        painter.drawPath(path)

        if info.is_empty:
            return

        text = (info.label or info.name.removeprefix("KC_")).replace("\n", " ")
        size = float(theme["key.label.size"])
        font = themed_font(str(theme["key.label.font"]), int(theme["key.label.weight"]), size)
        for _ in range(8):
            font.setPointSizeF(size)
            if QFontMetricsF(font).horizontalAdvance(text) <= rect.width() - 8 or size <= 5.0:
                break
            size -= 1.0
        painter.setFont(font)
        painter.setPen(theme.colour("key.label.colour"))
        painter.drawText(rect, int(Qt.AlignmentFlag.AlignCenter), text)

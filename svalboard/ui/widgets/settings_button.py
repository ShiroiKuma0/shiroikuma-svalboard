# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 白い熊
"""The settings cog: tap for settings, press and hold for the 白い熊 UI page.

The gesture is the family's, translated. On Android a long press on the cog jumps
straight past ordinary settings into the UI page; here that is a timer started on
press and cancelled on release or movement. When it fires, the press is consumed so
no ordinary click follows — the same thing the Android handlers achieve by returning
true.

Right-click does the same thing, because Qt already routes both a right-click and a
touchscreen long press through ``customContextMenuRequested``, and on a desktop the
right-click is the discoverable half.
"""

from __future__ import annotations

from PyQt6.QtCore import QPoint, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QIcon, QMouseEvent
from PyQt6.QtWidgets import QToolButton, QWidget

from ..theme import Theme

#: How long a press has to be held. Matches the platform's own long-press feel
#: rather than inventing a number.
LONG_PRESS_MS = 500

#: Movement beyond this cancels the hold, so a drag is not read as a long press.
MOVE_TOLERANCE = 8


class SettingsButton(QToolButton):
    uiPageRequested = pyqtSignal()

    def __init__(self, theme: Theme, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._theme = theme
        self._press_origin = QPoint()
        self._fired = False

        self.setText("⚙")
        self.setIcon(QIcon.fromTheme("configure"))
        self.setToolButtonStyle(
            Qt.ToolButtonStyle.ToolButtonIconOnly
            if not QIcon.fromTheme("configure").isNull()
            else Qt.ToolButtonStyle.ToolButtonTextOnly
        )
        self.setToolTip(
            "Settings.\nPress and hold, or right-click, for 白い熊 Svalboard UI."
        )
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(lambda _pos: self.uiPageRequested.emit())

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(LONG_PRESS_MS)
        self._timer.timeout.connect(self._on_hold)

    def _on_hold(self) -> None:
        self._fired = True
        self.setDown(False)
        self.uiPageRequested.emit()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802  (Qt naming)
        if event.button() == Qt.MouseButton.LeftButton:
            self._fired = False
            self._press_origin = event.pos()
            self._timer.start()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._timer.isActive():
            moved = (event.pos() - self._press_origin).manhattanLength()
            if moved > MOVE_TOLERANCE:
                self._timer.stop()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self._timer.stop()
        if self._fired:
            # The hold already acted; swallow the release so no click follows it.
            self._fired = False
            event.accept()
            return
        super().mouseReleaseEvent(event)

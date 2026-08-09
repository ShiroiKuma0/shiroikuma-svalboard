# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 白い熊
"""The key tester: watch the switch matrix directly.

This polls the keyboard for which switches are closed rather than listening for key
events, which matters twice over. On Wayland a program cannot see key events sent to
another window at all, and even where it could, the key being tested is mapped to
whatever the keymap says — so a broken switch and a mis-mapped one would look alike.
Reading the matrix sidesteps both.

Two states are drawn. **Held** is what is closed at this instant; **seen** is what has
been closed at any point since the test began, which is what makes this useful for
proving every switch on a board works without having to watch continuously.
"""

from __future__ import annotations

from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from ...protocol.kle import KeyPosition, Layout
from ..theme import Theme
from ..widgets.house import Heading, PillButton

#: How often to ask. The web configurator polls every 10 ms, which is far more often
#: than a switch can be pressed and released; 25 ms misses nothing a finger can do and
#: leaves the keyboard alone the rest of the time.
POLL_MS = 25


class MatrixCanvas(QWidget):
    """The board, drawn as held / seen / untouched."""

    def __init__(self, theme: Theme, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._theme = theme
        self._layout: Layout | None = None
        self._held: set[tuple[int, int]] = set()
        self._seen: set[tuple[int, int]] = set()
        self.setMinimumSize(360, 200)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        theme.changed.connect(self.update)

    def set_board(self, layout: Layout) -> None:
        self._layout = layout
        self._held.clear()
        self._seen.clear()
        self.update()

    def set_held(self, held: set[tuple[int, int]]) -> None:
        self._held = held
        self._seen |= held
        self.update()

    def reset_seen(self) -> None:
        self._seen.clear()
        self.update()

    @property
    def seen(self) -> set[tuple[int, int]]:
        return set(self._seen)

    def paintEvent(self, _event) -> None:  # noqa: N802  (Qt naming)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        theme = self._theme
        painter.fillRect(self.rect(), theme.colour("board.background"))
        if self._layout is None or not self._layout.keys:
            return

        min_x, min_y, max_x, max_y = self._layout.bounds
        unit = float(theme["board.unit"])
        width = max(1e-6, (max_x - min_x) * unit)
        height = max(1e-6, (max_y - min_y) * unit)
        scale = min((self.width() - 24) / width, (self.height() - 24) / height, 1.0)
        origin = QPointF(
            (self.width() - width * scale) / 2 - min_x * unit * scale,
            (self.height() - height * scale) / 2 - min_y * unit * scale,
        )
        gap = float(theme["board.gap_h"]) * scale
        radius = float(theme["key.corner"]) * scale

        for key in self._layout.keys:
            if not key.is_key:
                continue
            rect = QRectF(
                origin.x() + key.x * unit * scale + gap / 2,
                origin.y() + key.y * unit * scale + gap / 2,
                key.width * unit * scale - gap,
                key.height * unit * scale - gap,
            )
            path = QPainterPath()
            path.addRoundedRect(rect, radius, radius)

            position = (key.row, key.col)
            if position in self._held:
                painter.fillPath(path, theme.colour("state.selected"))
                border = theme.colour("state.selected")
            else:
                painter.fillPath(path, theme.colour("key.background"))
                border = (
                    theme.colour("layer.inactive")
                    if position in self._seen
                    else theme.colour("state.empty")
                )
            painter.setPen(QPen(border, max(1.0, float(theme["key.border_width"]) * scale)))
            painter.drawPath(path)


class TesterPage(QWidget):
    """Poll the matrix, and offer the same reading as a way to bind keys."""

    #: Emitted with (row, col) when a key is pressed while binding is armed.
    keyPressed = pyqtSignal(int, int)
    pollingChanged = pyqtSignal(bool)

    def __init__(self, theme: Theme, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._theme = theme
        self._read = None
        self._rows = 0
        self._cols = 0
        self._previous: set[tuple[int, int]] = set()

        self.canvas = MatrixCanvas(theme)
        self.summary = QLabel()
        self.summary.setContentsMargins(int(theme["row.indent"]), 0, 16, 4)

        self.toggle = PillButton("Start testing", theme)
        self.toggle.clicked.connect(self.toggle_polling)
        self.reset = PillButton("Forget what has been seen", theme)
        self.reset.clicked.connect(self._reset_seen)

        controls = QHBoxLayout()
        controls.setContentsMargins(int(theme["row.indent"]), 0, 16, 6)
        controls.setSpacing(8)
        controls.addWidget(self.toggle)
        controls.addWidget(self.reset)
        controls.addStretch(1)

        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        column.addWidget(Heading("Key tester", theme, level=0))
        column.addWidget(self.summary)
        column.addLayout(controls)
        column.addWidget(self.canvas, 1)

        self._timer = QTimer(self)
        self._timer.setInterval(POLL_MS)
        self._timer.timeout.connect(self._poll)

        theme.changed.connect(self._restyle)
        self._restyle()
        self._describe()

    def _restyle(self) -> None:
        self.summary.setStyleSheet(f"color: {self._theme.css('row.description.colour')};")

    # -- data --------------------------------------------------------------------

    def bind(self, layout: Layout, read, *, rows: int, cols: int) -> None:
        """``read`` is a callable returning the matrix; the page never touches HID."""
        self._read = read
        self._rows, self._cols = rows, cols
        self.canvas.set_board(layout)
        self._describe()

    @property
    def polling(self) -> bool:
        return self._timer.isActive()

    def toggle_polling(self) -> None:
        self.set_polling(not self.polling)

    def set_polling(self, polling: bool) -> None:
        if polling and self._read is None:
            return
        if polling:
            self._previous = set()
            self._timer.start()
        else:
            self._timer.stop()
        self.toggle.setText("Stop testing" if polling else "Start testing")
        self._describe()
        self.pollingChanged.emit(polling)

    def _reset_seen(self) -> None:
        self.canvas.reset_seen()
        self._describe()

    def _describe(self) -> None:
        total = sum(
            1
            for key in (self.canvas._layout.keys if self.canvas._layout else ())
            if key.is_key
        )
        seen = len(self.canvas.seen)
        state = "polling" if self.polling else "stopped"
        self.summary.setText(
            f"{seen} of {total} switches seen · {state}. Reads the switch matrix "
            f"directly, so a key is tested whatever it is mapped to — and this works "
            f"on Wayland, where key events cannot be observed."
        )

    def _poll(self) -> None:
        if self._read is None:
            return
        try:
            matrix = self._read(self._rows, self._cols)
        except Exception:
            # A keyboard unplugged mid-test should stop the test, not raise into
            # the timer over and over.
            self.set_polling(False)
            return

        held = {
            (row, col)
            for row, values in enumerate(matrix)
            for col, value in enumerate(values)
            if value
        }
        for position in held - self._previous:
            self.keyPressed.emit(*position)
        self._previous = held
        self.canvas.set_held(held)
        self._describe()

    def hideEvent(self, event) -> None:  # noqa: N802
        # Polling a keyboard nobody is watching is pure noise on the wire.
        self.set_polling(False)
        super().hideEvent(event)

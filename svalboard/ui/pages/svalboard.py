# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 白い熊
"""The Svalboard panel: its own keycodes, its layer colours, and its live state.

Three things sit here because all three are Svalboard-specific and all three are
limited by firmware rather than by this program:

* The ``SV_*`` keycodes are ordinary bindable keys, and the panel says where each one
  is currently bound so a setting can be found rather than hunted for.
* Layer colours need the ``0xEE`` extension. Without it the section explains itself
  instead of disappearing.
* Live pointing state is not on the wire at all and can only be read by pressing
  ``SV_OUTPUT_STATUS`` while listening to the QMK console.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ...protocol.keycodes import KeycodeSet
from ..theme import Theme
from ..widgets.house import Heading, PillButton, Row

#: Cluster and direction names, so a binding can be described the way the keyboard is
#: physically laid out rather than as a matrix position.
CLUSTERS = {0: "left thumb", 5: "right thumb"}
DIRECTIONS = ("south", "east", "centre", "north", "west", "super-south")


def describe_position(layer: int, row: int, col: int) -> str:
    cluster = CLUSTERS.get(row, f"cluster {row}")
    direction = DIRECTIONS[col] if col < len(DIRECTIONS) else str(col)
    return f"layer {layer}, {cluster} {direction}"


class SvalboardPage(QWidget):
    """Svalboard keycodes, layer colours and live status."""

    statusRequested = pyqtSignal()

    def __init__(self, theme: Theme, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._theme = theme
        self._keycodes: KeycodeSet | None = None

        self.body = QWidget()
        self.rows = QVBoxLayout(self.body)
        self.rows.setContentsMargins(0, 0, 0, 16)
        self.rows.setSpacing(int(theme["row.spacing"]))
        self.rows.setAlignment(Qt.AlignmentFlag.AlignTop)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.body)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)

        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        column.addWidget(Heading("Svalboard", theme, level=0))
        column.addWidget(scroll, 1)

        self._status_label: QLabel | None = None

    def bind(
        self,
        keycodes: KeycodeSet,
        *,
        custom_names: list[str],
        bindings: dict[str, list[tuple[int, int, int]]],
        has_extension: bool,
        console_available: bool,
    ) -> None:
        self._keycodes = keycodes
        while (item := self.rows.takeAt(0)) is not None:
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        self._add_status(console_available)
        self._add_colours(has_extension)
        self._add_keycodes(custom_names, bindings)

    # -- sections ----------------------------------------------------------------

    def _note(self, text: str, *, warning: bool = False) -> QLabel:
        label = QLabel(text)
        label.setWordWrap(True)
        label.setContentsMargins(int(self._theme["row.indent"]), 0, 16, 4)
        colour = "window.warning" if warning else "row.description.colour"
        label.setStyleSheet(f"color: {self._theme.css(colour)};")
        return label

    def _add_status(self, console_available: bool) -> None:
        self.rows.addWidget(Heading("Live state", self._theme, level=1))
        self.rows.addWidget(
            self._note(
                "DPI, scroll side, auto-mouse and the mouse timer are not readable "
                "over the wire — the firmware keeps them but exposes only layer "
                "colours. They can be read by pressing the Output Status key while "
                "this listens to the keyboard's debug console."
            )
        )
        if not console_available:
            self.rows.addWidget(
                self._note("No console interface on this keyboard.", warning=True)
            )
            return

        row = Row("Read the current state", self._theme, level=2,
                  description="Asks you to press the Output Status key.")
        button = PillButton("Read", self._theme)
        button.clicked.connect(self.statusRequested)
        row.add_control(button)
        self.rows.addWidget(row)

        self._status_label = self._note("Not read yet.")
        self.rows.addWidget(self._status_label)

    def _add_colours(self, has_extension: bool) -> None:
        self.rows.addWidget(Heading("Layer colours", self._theme, level=1))
        if has_extension:
            self.rows.addWidget(
                self._note("Per-layer colours are available on this firmware.")
            )
        else:
            self.rows.addWidget(
                self._note(
                    "This firmware has no Svalboard extension, so layer colours "
                    "cannot be read or set. Every 0xEE command is answered the way "
                    "an unknown command is. A vial-qmk build carrying the extension "
                    "(protocol 3 or later) is needed.",
                    warning=True,
                )
            )

    def _add_keycodes(
        self, custom_names: list[str], bindings: dict[str, list[tuple[int, int, int]]]
    ) -> None:
        assert self._keycodes is not None
        self.rows.addWidget(Heading("Svalboard keys", self._theme, level=1))
        self.rows.addWidget(
            self._note(
                "These are ordinary keycodes: bind them from the picker like any "
                "other. Where each is already bound is shown beside it."
            )
        )
        for name in custom_names:
            try:
                info = self._keycodes.info(self._keycodes.parse(name))
            except ValueError:
                continue
            where = bindings.get(name) or []
            if where:
                description = "; ".join(
                    describe_position(*position) for position in where[:3]
                )
                if len(where) > 3:
                    description += f"; and {len(where) - 3} more"
            else:
                description = "not bound anywhere"
            row = Row(
                info.tooltip if info.tooltip != info.name else info.name,
                self._theme,
                level=2,
                description=f"{info.name} — {description}",
            )
            self.rows.addWidget(row)

    # -- status ------------------------------------------------------------------

    def show_status(self, text: str, *, warning: bool = False) -> None:
        if self._status_label is None:
            return
        self._status_label.setText(text)
        colour = "window.warning" if warning else "window.text"
        self._status_label.setStyleSheet(f"color: {self._theme.css(colour)};")

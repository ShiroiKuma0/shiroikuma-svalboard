# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 白い熊
"""QMK's own settings, grouped as the schema groups them.

Settings the connected firmware does not carry are shown greyed with the reason rather
than hidden, because "this firmware was not built with Chordal Hold" is more useful
than the option silently not existing. The web configurator asks the keyboard which
settings it supports and then ignores the answer, offering all of them regardless.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QLabel,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ...model.entries import SettingsChanges
from ...protocol.qmk_settings import Field, fields, read_bit, write_bit
from ..theme import Theme
from ..widgets.house import Heading, Row


class QmkSettingsPage(QWidget):
    """One scrolling page, a heading per tab in the schema."""

    resetRequested = pyqtSignal()

    def __init__(self, theme: Theme, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._theme = theme
        self._changes: SettingsChanges | None = None

        self.heading = Heading("QMK settings", theme, level=0)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.summary.setContentsMargins(int(theme["row.indent"]), 0, 16, 6)

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
        column.addWidget(self.heading)
        column.addWidget(self.summary)
        column.addWidget(scroll, 1)

        theme.changed.connect(self._restyle)
        self._restyle()

    def _restyle(self) -> None:
        self.summary.setStyleSheet(f"color: {self._theme.css('row.description.colour')};")
        self.rows.setSpacing(int(self._theme["row.spacing"]))

    def bind(self, changes: SettingsChanges) -> None:
        self._changes = changes
        self.rebuild()

    def rebuild(self) -> None:
        if self._changes is None:
            return
        while (item := self.rows.takeAt(0)) is not None:
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        changes = self._changes
        every = fields()
        available = [field for field in every if field.qsid in changes.supported]
        self.summary.setText(
            f"{len(available)} of {len(every)} settings are built into this firmware. "
            f"Greyed rows are absent from the build, not merely switched off."
        )

        current_tab = None
        for field in every:
            if field.tab != current_tab:
                current_tab = field.tab
                self.rows.addWidget(Heading(field.tab, self._theme, level=1))
            self.rows.addWidget(self._row(field))

    def _row(self, field: Field) -> QWidget:
        assert self._changes is not None
        changes = self._changes
        supported = field.qsid in changes.supported

        title = field.title
        description = "" if supported else "not built into this firmware"
        row = Row(title, self._theme, level=2, description=description)

        if not supported:
            row.setEnabled(False)
            return row

        if field.is_boolean and field.bit is not None:
            box = QCheckBox()
            box.setChecked(read_bit(changes.get(field.qsid), field.bit))

            def toggle(value: bool, f=field) -> None:
                changes.set(
                    f.qsid, write_bit(changes.get(f.qsid), f.bit, value)
                )

            box.toggled.connect(toggle)
            row.add_control(box)
        else:
            spin = QSpinBox()
            maximum = field.maximum or (1 << (8 * field.width)) - 1
            spin.setRange(field.minimum, min(maximum, 2_000_000_000))
            spin.setValue(changes.get(field.qsid))
            spin.setFixedWidth(120)

            def change(value: int, f=field) -> None:
                changes.set(f.qsid, value)

            spin.valueChanged.connect(change)
            row.add_control(spin)

        if changes.is_changed(field.qsid):
            row.title.setStyleSheet(f"color: {self._theme.css('state.changed')};")
        return row

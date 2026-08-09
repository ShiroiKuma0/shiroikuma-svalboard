# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 白い熊
"""The house colour picker: recent swatches, a live preview, and four RGBA sliders.

Every movement applies immediately, so the change is visible on the page behind the
dialog rather than only after confirming. Cancel restores the colour the dialog opened
with; only OK remembers it in the swatch row.
"""

from __future__ import annotations

from collections.abc import Callable

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from ..theme import Theme
from ..theme.theme import css_colour
from ..widgets.house import PillButton, Swatch, button_row, themed_font

CHANNELS = ("A", "R", "G", "B")


class ColourDialog(QDialog):
    def __init__(
        self,
        theme: Theme,
        colour: str,
        *,
        title: str,
        on_change: Callable[[str], None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._theme = theme
        self._on_change = on_change
        self._initial = colour
        self._colour = QColor(colour)
        if not self._colour.isValid():
            self._colour = QColor("#FFFFFF00")

        self.setWindowTitle(title)
        self.setModal(True)

        column = QVBoxLayout(self)
        padding = int(theme["dialog.padding"])
        column.setContentsMargins(padding, padding, padding, padding)
        column.setSpacing(14)

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

        self._swatch_row = QHBoxLayout()
        self._swatch_row.setSpacing(6)
        self._swatch_row.addStretch(1)
        column.addLayout(self._swatch_row)
        self._build_swatches()

        self.preview = QLabel()
        self.preview.setMinimumHeight(52)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        column.addWidget(self.preview)

        self._sliders: dict[str, QSlider] = {}
        for channel in CHANNELS:
            row = QHBoxLayout()
            row.setSpacing(8)
            label = QLabel(channel)
            label.setFixedWidth(16)
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(0, 255)
            slider.setValue(self._channel(channel))
            slider.valueChanged.connect(
                lambda value, name=channel: self._set_channel(name, value)
            )
            readout = QLabel()
            readout.setFixedWidth(34)
            readout.setAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            slider.valueChanged.connect(lambda value, l=readout: l.setText(str(value)))
            readout.setText(str(slider.value()))
            row.addWidget(label)
            row.addWidget(slider, 1)
            row.addWidget(readout)
            column.addLayout(row)
            self._sliders[channel] = slider

        column.addWidget(
            button_row(
                theme,
                ("Cancel", self._cancel),
                [("OK", self._accept)],
            )
        )

        self.setStyleSheet(
            f"QDialog {{"
            f"background: {theme.css('dialog.background')};"
            f"border: {theme['dialog.border_width']}px solid {theme.css('dialog.border')};"
            f"}}"
        )
        self._refresh(apply=False)

    # -- swatches ----------------------------------------------------------------

    def _build_swatches(self) -> None:
        while self._swatch_row.count() > 1:
            item = self._swatch_row.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for index, colour in enumerate(self._theme.swatches()):
            chip = Swatch(self._theme, colour)
            chip.clicked.connect(lambda c=colour: self._adopt(c))
            self._swatch_row.insertWidget(index, chip)

    def _adopt(self, colour: str) -> None:
        self._colour = QColor(colour)
        for channel in CHANNELS:
            slider = self._sliders[channel]
            blocked = slider.blockSignals(True)
            slider.setValue(self._channel(channel))
            slider.blockSignals(blocked)
        self._refresh(apply=True)

    # -- channels ----------------------------------------------------------------

    def _channel(self, name: str) -> int:
        return {
            "A": self._colour.alpha(),
            "R": self._colour.red(),
            "G": self._colour.green(),
            "B": self._colour.blue(),
        }[name]

    def _set_channel(self, name: str, value: int) -> None:
        setter = {
            "A": self._colour.setAlpha,
            "R": self._colour.setRed,
            "G": self._colour.setGreen,
            "B": self._colour.setBlue,
        }[name]
        setter(value)
        self._refresh(apply=True)

    def value(self) -> str:
        return self._colour.name(QColor.NameFormat.HexArgb).upper()

    def _refresh(self, *, apply: bool) -> None:
        colour = self._colour
        # White on anything dark or largely transparent, black otherwise — a plain
        # luminance test, so the hex stays readable over its own colour.
        luminance = 0.299 * colour.red() + 0.587 * colour.green() + 0.114 * colour.blue()
        text = "#FFFFFF" if luminance < 128 or colour.alpha() < 128 else "#000000"
        self.preview.setText(self.value())
        self.preview.setStyleSheet(
            f"background: {css_colour(self.value())}; color: {text};"
        )
        if apply:
            self._on_change(self.value())

    # -- outcome -----------------------------------------------------------------

    def _accept(self) -> None:
        self._theme.remember_swatch(self.value())
        self.accept()

    def _cancel(self) -> None:
        self._on_change(self._initial)
        self.reject()

    def reject(self) -> None:
        # Closing by Escape or the window button must revert too, not keep the
        # live-applied colour.
        self._on_change(self._initial)
        super().reject()

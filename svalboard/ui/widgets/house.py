# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 白い熊
"""The building blocks of the 白い熊 settings page, in Qt Widgets.

Two details carry the house look and are easy to get subtly wrong:

* **The underline is as wide as the words, not the window.** In the Android apps a
  ``wrap_content`` column makes a ``match_parent`` rule resolve to the text width. The
  equivalent here is to measure the label and give the rule that exact width, which is
  what :class:`Heading` does — and it must be re-measured whenever the font changes.
* **Rows are tight because they have no minimum height.** Android's 48 dp preference
  minimum is what makes stock settings pages airy; Qt has its own version of that in
  layout spacing and widget size hints, so both are cleared explicitly. Five pixels of
  padding is the whole vertical rhythm.
"""

from __future__ import annotations

from collections.abc import Callable

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont, QFontMetrics
from PyQt6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from ..theme import Theme


def themed_font(family: str, weight: int, size_pt: float) -> QFont:
    """Build a face from the theme's Font / Weight / Size triple.

    An empty family means "the system font". ``QFont("")`` does not mean that — it
    asks for a family literally named "", and Qt's substitution picks whatever it
    likes, which is how the board first came out in a handwriting face. Starting from
    the application font gets the intended default.
    """
    from PyQt6.QtWidgets import QApplication

    font = QFont(family) if family else QFont(QApplication.font())
    font.setPointSizeF(max(1.0, float(size_pt)))
    font.setWeight(QFont.Weight(max(1, min(1000, int(weight)))))
    return font


def apply_font(widget: QWidget, family: str, weight: int, size_pt: int) -> None:
    """Set a face from the theme's Font / Weight / Size triple."""
    widget.setFont(themed_font(family, weight, size_pt))


class Hairline(QFrame):
    """The full-width rule that marks the boundary between top-level groups."""

    def __init__(self, theme: Theme, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._theme = theme
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        theme.changed.connect(self.restyle)
        self.restyle()

    def restyle(self) -> None:
        thickness = max(1, int(self._theme["heading.section.hairline"]))
        self.setFixedHeight(thickness)
        self.setStyleSheet(f"background: {self._theme.css('heading.section.colour')};")


class Heading(QWidget):
    """A heading with an underline exactly as wide as its text."""

    def __init__(
        self,
        text: str,
        theme: Theme,
        *,
        level: int = 0,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._theme = theme
        self._level = level
        self._prefix = "heading.section" if level == 0 else "heading.subgroup"

        self.label = QLabel(text)
        self.rule = QFrame()
        self.rule.setFrameShape(QFrame.Shape.NoFrame)

        column = QVBoxLayout()
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(2)
        column.addWidget(self.label)
        column.addWidget(self.rule)

        # The stretch is what keeps the column at its natural width, so the rule
        # underlines the words rather than the window.
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.addLayout(column)
        row.addStretch(1)

        theme.changed.connect(self.restyle)
        self.restyle()

    def restyle(self) -> None:
        theme = self._theme
        apply_font(
            self.label,
            str(theme[f"{self._prefix}.font"]),
            int(theme[f"{self._prefix}.weight"]),
            int(theme[f"{self._prefix}.size"]),
        )
        self.label.setStyleSheet(f"color: {theme.css(f'{self._prefix}.colour')};")

        thickness = max(1, int(theme[f"{self._prefix}.rule"]))
        width = QFontMetrics(self.label.font()).horizontalAdvance(self.label.text())
        self.rule.setFixedHeight(thickness)
        self.rule.setFixedWidth(max(1, width))
        self.rule.setStyleSheet(f"background: {theme.css(f'{self._prefix}.colour')};")

        indent = int(theme[f"{self._prefix}.indent"])
        top = 10 if self._level else 14
        self.setContentsMargins(indent, top, 0, 2)


class Row(QWidget):
    """One tight settings row: title and optional description on the left, control right."""

    def __init__(
        self,
        title: str,
        theme: Theme,
        *,
        level: int = 1,
        description: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._theme = theme
        self._level = level

        self.title = QLabel(title)
        self.description = QLabel(description)
        self.description.setVisible(bool(description))
        self.description.setWordWrap(True)

        text = QVBoxLayout()
        text.setContentsMargins(0, 0, 0, 0)
        text.setSpacing(0)
        text.addWidget(self.title)
        text.addWidget(self.description)

        self._row = QHBoxLayout(self)
        self._row.setSpacing(10)
        self._row.addLayout(text, 1)

        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        theme.changed.connect(self.restyle)
        self.restyle()

    def add_control(self, widget: QWidget, stretch: int = 0) -> None:
        self._row.addWidget(widget, stretch)

    def restyle(self) -> None:
        theme = self._theme
        apply_font(
            self.title,
            str(theme["row.title.font"]),
            int(theme["row.title.weight"]),
            int(theme["row.title.size"]),
        )
        self.title.setStyleSheet(f"color: {theme.css('row.title.colour')};")
        apply_font(
            self.description,
            str(theme["row.description.font"]),
            int(theme["row.description.weight"]),
            int(theme["row.description.size"]),
        )
        self.description.setStyleSheet(
            f"color: {theme.css('row.description.colour')};"
        )

        indent = int(theme["row.indent"]) + (self._level - 1) * int(
            theme["row.indent_step"]
        )
        padding = int(theme["row.padding"])
        self._row.setContentsMargins(indent, padding, 16, padding)
        # Without this the platform style imposes a comfortable minimum, which is
        # exactly the airiness the house style removes.
        self.setMinimumHeight(0)


class SliderRow(Row):
    """A slider with its value shown to the right, updating continuously."""

    valueChanged = pyqtSignal(int)

    def __init__(
        self,
        title: str,
        theme: Theme,
        *,
        minimum: int,
        maximum: int,
        value: int,
        unit: str = "",
        level: int = 1,
        description: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(title, theme, level=level, description=description, parent=parent)
        self._unit = unit

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setMinimum(minimum)
        self.slider.setMaximum(maximum)
        self.slider.setValue(value)
        self.slider.setSingleStep(1)
        self.slider.setPageStep(max(1, (maximum - minimum) // 10))
        self.slider.setMinimumWidth(160)

        self.readout = QLabel()
        self.readout.setMinimumWidth(52)
        self.readout.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )

        self.add_control(self.slider, 1)
        self.add_control(self.readout)

        self.slider.valueChanged.connect(self._on_change)
        self._show_value(value)

    def _on_change(self, value: int) -> None:
        self._show_value(value)
        self.valueChanged.emit(value)

    def _show_value(self, value: int) -> None:
        self.readout.setText(str(value))

    def setValue(self, value: int) -> None:
        blocked = self.slider.blockSignals(True)
        self.slider.setValue(value)
        self.slider.blockSignals(blocked)
        self._show_value(value)


class ToggleRow(Row):
    """A row whose control is a checkbox."""

    toggled = pyqtSignal(bool)

    def __init__(
        self,
        title: str,
        theme: Theme,
        *,
        checked: bool,
        level: int = 1,
        description: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(title, theme, level=level, description=description, parent=parent)
        self.checkbox = QCheckBox()
        self.checkbox.setChecked(checked)
        self.checkbox.toggled.connect(self.toggled)
        self.add_control(self.checkbox)


class Swatch(QFrame):
    """A colour chip: the fill, with a thin accent border."""

    clicked = pyqtSignal()

    def __init__(
        self,
        theme: Theme,
        colour: str,
        *,
        size: int = 32,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._theme = theme
        self._colour = colour
        self.setFixedSize(size, size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        theme.changed.connect(self.restyle)
        self.restyle()

    def colour(self) -> str:
        return self._colour

    def set_colour(self, colour: str) -> None:
        self._colour = colour
        self.restyle()

    def restyle(self) -> None:
        from ..theme.theme import css_colour

        self.setStyleSheet(
            f"background: {css_colour(self._colour)};"
            f"border: 2px solid {self._theme.css('key.border')};"
            f"border-radius: 4px;"
        )

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802  (Qt naming)
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class PillButton(QPushButton):
    """The family's dialog action button: a rounded outline, sentence case."""

    def __init__(self, text: str, theme: Theme, parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self._theme = theme
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        theme.changed.connect(self.restyle)
        self.restyle()

    def restyle(self) -> None:
        theme = self._theme
        pad_v = int(theme["button.padding_v"])
        pad_h = int(theme["button.padding_h"])
        height = QFontMetrics(self.font()).height() + pad_v * 2
        # A radius of half the height is what actually makes a pill; the family's
        # Android code writes an absurdly large radius to the same effect.
        radius = min(int(theme["button.corner"]), height // 2)
        self.setStyleSheet(
            f"QPushButton {{"
            f"background: {theme.css('button.background')};"
            f"color: {theme.css('button.text')};"
            f"border: {theme['button.border_width']}px solid {theme.css('button.border')};"
            f"border-radius: {radius}px;"
            f"padding: {pad_v}px {pad_h}px;"
            f"}}"
            f"QPushButton:hover {{ background: rgba(255, 255, 0, 0.12); }}"
            f"QPushButton:pressed {{ background: rgba(255, 255, 0, 0.20); }}"
            f"QPushButton:disabled {{"
            f"color: {theme.css('button.disabled')};"
            f"border-color: {theme.css('button.disabled')};"
            f"}}"
        )


def button_row(
    theme: Theme,
    cancel: tuple[str, Callable[[], None]] | None,
    actions: list[tuple[str, Callable[[], None]]],
) -> QWidget:
    """Cancel alone on the left, the actions grouped on the right.

    Qt's own :class:`QDialogButtonBox` orders buttons to the platform's taste and will
    not reliably put Cancel far left, so the layout is explicit — which is what the
    family's Android code does too, for the same reason.
    """
    container = QWidget()
    row = QHBoxLayout(container)
    row.setContentsMargins(0, 14, 0, 0)
    row.setSpacing(8)

    if cancel is not None:
        text, handler = cancel
        button = PillButton(text, theme)
        button.clicked.connect(handler)
        row.addWidget(button)

    row.addStretch(1)
    for text, handler in actions:
        button = PillButton(text, theme)
        button.clicked.connect(handler)
        row.addWidget(button)
    return container

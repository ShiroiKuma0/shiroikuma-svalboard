# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 白い熊
"""The board, drawn from the keyboard's own geometry.

Nothing about the Svalboard's shape is hard-coded: the positions come from the KLE
layout inside the definition the keyboard hands over, so a firmware with a different
matrix simply draws differently. The canvas scales to fit whatever it is given, which
also means it copes with the thumb clusters' 2u keys and with rotated clusters on other
Vial boards without special-casing them.
"""

from __future__ import annotations

import math

from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QFont,
    QFontMetricsF,
    QMouseEvent,
    QPainter,
    QPainterPath,
    QPaintEvent,
    QPen,
)
from PyQt6.QtWidgets import QSizePolicy, QWidget

from ...protocol.keycodes import (
    KIND_CUSTOM,
    KIND_LAYER,
    KIND_MACRO,
    KIND_MASKED,
    KIND_TAP_DANCE,
    KIND_UNSET,
    KeycodeSet,
)
from ...protocol.kle import KeyPosition, Layout
from ..theme import Theme
from .house import themed_font

#: Which state colour tints a key of each kind. Plain keycodes are untinted.
KIND_TINTS = {
    KIND_LAYER: "state.layer",
    KIND_MASKED: "state.modtap",
    KIND_MACRO: "state.macro",
    KIND_TAP_DANCE: "state.tapdance",
    KIND_CUSTOM: "state.custom",
    KIND_UNSET: "state.unset",
}


class KeyboardCanvas(QWidget):
    """Draws one layer of the keymap and reports which key was clicked."""

    keySelected = pyqtSignal(int)
    keyActivated = pyqtSignal(int)

    def __init__(
        self,
        theme: Theme,
        *,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._theme = theme
        self._layout: Layout | None = None
        self._keycodes: KeycodeSet | None = None
        self._codes: list[int] = []
        self._baseline: list[int] = []
        self._selected = -1
        self._hovered = -1
        self._scale = 1.0
        self._origin = QPointF(0, 0)

        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(360, 200)
        theme.changed.connect(self.update)

    # -- data --------------------------------------------------------------------

    def set_board(self, layout: Layout, keycodes: KeycodeSet) -> None:
        self._layout = layout
        self._keycodes = keycodes
        self._selected = -1
        self.updateGeometry()
        self.update()

    def set_layer(self, codes: list[int], baseline: list[int] | None = None) -> None:
        """``codes`` is one layer, flat and row-major; ``baseline`` is what the
        keyboard currently holds, so changed keys can be marked."""
        self._codes = list(codes)
        self._baseline = list(baseline) if baseline is not None else list(codes)
        self.update()

    def selected(self) -> int:
        return self._selected

    def select(self, kmid: int) -> None:
        if kmid != self._selected:
            self._selected = kmid
            self.keySelected.emit(kmid)
            self.update()

    # -- geometry ----------------------------------------------------------------

    def _unit(self) -> float:
        return float(self._theme["board.unit"])

    def _compute_scale(self) -> None:
        if self._layout is None or not self._layout.keys:
            self._scale, self._origin = 1.0, QPointF(0, 0)
            return
        min_x, min_y, max_x, max_y = self._layout.bounds
        unit = self._unit()
        width = max(1e-6, (max_x - min_x) * unit)
        height = max(1e-6, (max_y - min_y) * unit)
        margin = 12.0
        available_w = max(1.0, self.width() - margin * 2)
        available_h = max(1.0, self.height() - margin * 2)
        self._scale = min(available_w / width, available_h / height, 1.0)
        drawn_w, drawn_h = width * self._scale, height * self._scale
        self._origin = QPointF(
            (self.width() - drawn_w) / 2 - min_x * unit * self._scale,
            (self.height() - drawn_h) / 2 - min_y * unit * self._scale,
        )

    def _key_path(self, key: KeyPosition) -> QPainterPath:
        unit = self._unit() * self._scale
        gap_h = float(self._theme["board.gap_h"]) * self._scale
        gap_v = float(self._theme["board.gap_v"]) * self._scale
        radius = float(self._theme["key.corner"]) * self._scale

        rect = QRectF(
            self._origin.x() + key.x * unit + gap_h / 2,
            self._origin.y() + key.y * unit + gap_v / 2,
            key.width * unit - gap_h,
            key.height * unit - gap_v,
        )
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)

        if key.is_l_shaped:
            secondary = QRectF(
                self._origin.x() + (key.x + key.x2) * unit + gap_h / 2,
                self._origin.y() + (key.y + key.y2) * unit + gap_v / 2,
                key.width2 * unit - gap_h,
                key.height2 * unit - gap_v,
            )
            extra = QPainterPath()
            extra.addRoundedRect(secondary, radius, radius)
            path = path.united(extra)

        if key.rotation_angle:
            pivot = QPointF(
                self._origin.x() + key.rotation_x * unit,
                self._origin.y() + key.rotation_y * unit,
            )
            path = _rotate_path(path, pivot, key.rotation_angle)
        return path

    def _key_at(self, point: QPointF) -> int:
        if self._layout is None:
            return -1
        for key in self._layout.keys:
            if not key.is_key:
                continue
            if self._key_path(key).contains(point):
                return key.kmid(self._layout.cols)
        return -1

    # -- events ------------------------------------------------------------------

    def resizeEvent(self, event) -> None:  # noqa: N802  (Qt naming)
        super().resizeEvent(event)
        self._compute_scale()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        hovered = self._key_at(event.position())
        if hovered != self._hovered:
            self._hovered = hovered
            self.setCursor(
                Qt.CursorShape.PointingHandCursor
                if hovered >= 0
                else Qt.CursorShape.ArrowCursor
            )
            self.setToolTip(self._tooltip(hovered))
            self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            kmid = self._key_at(event.position())
            if kmid >= 0:
                self.select(kmid)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        kmid = self._key_at(event.position())
        if kmid >= 0:
            self.keyActivated.emit(kmid)

    def _tooltip(self, kmid: int) -> str:
        if kmid < 0 or self._keycodes is None or kmid >= len(self._codes):
            return ""
        info = self._keycodes.info(self._codes[kmid])
        return f"{info.name}\n{info.tooltip}" if info.tooltip != info.name else info.name

    # -- painting ----------------------------------------------------------------

    def paintEvent(self, _event: QPaintEvent) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        theme = self._theme
        painter.fillRect(self.rect(), theme.colour("board.background"))

        if self._layout is None or self._keycodes is None:
            painter.setPen(theme.colour("window.dim"))
            painter.drawText(
                self.rect(), Qt.AlignmentFlag.AlignCenter, "No keyboard connected."
            )
            return

        self._compute_scale()
        border_width = max(1.0, float(theme["key.border_width"]) * self._scale)

        for key in self._layout.keys:
            if not key.is_key:
                continue
            kmid = key.kmid(self._layout.cols)
            code = self._codes[kmid] if kmid < len(self._codes) else 0
            info = self._keycodes.info(code)
            path = self._key_path(key)

            fill = theme.colour("key.background")
            if info.is_empty:
                fill = theme.colour("state.empty")
            elif info.is_transparent:
                fill = theme.colour("state.transparent")
            elif info.kind in KIND_TINTS:
                fill = _tinted(theme.colour(KIND_TINTS[info.kind]))

            changed = kmid < len(self._baseline) and self._baseline[kmid] != code
            if changed:
                fill = theme.colour("state.changed")

            border = theme.colour("key.border")
            width = border_width
            if kmid == self._selected:
                border = theme.colour("state.selected")
                width = border_width * 2
            elif kmid == self._hovered:
                border = theme.colour("state.selected")

            painter.fillPath(path, fill)
            painter.setPen(QPen(border, width))
            painter.drawPath(path)

            self._draw_label(painter, key, info)

    def _draw_label(self, painter: QPainter, key: KeyPosition, info) -> None:
        theme = self._theme
        unit = self._unit() * self._scale
        gap_h = float(theme["board.gap_h"]) * self._scale
        rect = QRectF(
            self._origin.x() + key.x * unit + gap_h / 2,
            self._origin.y() + key.y * unit,
            key.width * unit - gap_h,
            key.height * unit,
        )
        if key.rotation_angle:
            painter.save()
            pivot = QPointF(
                self._origin.x() + key.rotation_x * unit,
                self._origin.y() + key.rotation_y * unit,
            )
            painter.translate(pivot)
            painter.rotate(key.rotation_angle)
            painter.translate(-pivot)

        text = info.label or ""
        size = max(5.0, float(theme["key.label.size"]) * self._scale)
        font = themed_font(
            str(theme["key.label.font"]), int(theme["key.label.weight"]), size
        )
        # Shrink rather than clip: several Svalboard labels are three stacked words.
        for _ in range(6):
            font.setPointSizeF(size)
            metrics = QFontMetricsF(font)
            widest = max(
                (metrics.horizontalAdvance(line) for line in text.split("\n")), default=0.0
            )
            if widest <= rect.width() - 6 or size <= 5.0:
                break
            size -= 1.0

        painter.setFont(font)
        painter.setPen(theme.colour("key.label.colour"))
        painter.drawText(
            rect,
            int(Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap),
            text,
        )
        if key.rotation_angle:
            painter.restore()


def _tinted(colour: QColor, alpha: int = 70) -> QColor:
    """A state colour used as a wash rather than a fill."""
    faded = QColor(colour)
    faded.setAlpha(alpha)
    return faded


def _rotate_path(path: QPainterPath, pivot: QPointF, degrees: float) -> QPainterPath:
    from PyQt6.QtGui import QTransform

    transform = QTransform()
    transform.translate(pivot.x(), pivot.y())
    transform.rotate(degrees)
    transform.translate(-pivot.x(), -pivot.y())
    return transform.map(path)


def rotated_bounds(key: KeyPosition) -> tuple[float, float]:
    """Convenience for tests: the key's rotated centre."""
    angle = math.radians(key.rotation_angle)
    cx, cy = key.x + key.width / 2, key.y + key.height / 2
    if not key.rotation_angle:
        return cx, cy
    dx, dy = cx - key.rotation_x, cy - key.rotation_y
    return (
        key.rotation_x + dx * math.cos(angle) - dy * math.sin(angle),
        key.rotation_y + dx * math.sin(angle) + dy * math.cos(angle),
    )

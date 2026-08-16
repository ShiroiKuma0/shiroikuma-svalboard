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
import re

from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import (
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
    KIND_TEMPLATE,
    KIND_UNSET,
    KeycodeSet,
    modifier_label,
    modifier_mask,
)
from ...protocol.kle import KeyPosition, Layout
from ..theme import Theme
from .house import themed_font

#: Which state colour tints a key of each kind. Plain keycodes are untinted.
KIND_TINTS = {
    KIND_LAYER: "state.layer",
    KIND_MASKED: "state.modtap",
    # A template only ever appears in the picker, tinted like the composed keycode
    # it is on its way to becoming.
    KIND_TEMPLATE: "state.modtap",
    KIND_MACRO: "state.macro",
    KIND_TAP_DANCE: "state.tapdance",
    KIND_CUSTOM: "state.custom",
    KIND_UNSET: "state.unset",
}


class KeyboardCanvas(QWidget):
    """Draws one layer of the keymap and reports which key was clicked."""

    keySelected = pyqtSignal(int)
    keyActivated = pyqtSignal(int)
    #: Emitted with the effective scale as a percentage whenever the zoom changes.
    zoomChanged = pyqtSignal(float)

    #: How far a single wheel notch moves the zoom, and the limits it may reach.
    ZOOM_STEP = 1.1
    ZOOM_MIN = 0.2
    ZOOM_MAX = 4.0

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
        # None means "fit the board to the window", which is the default and what
        # resizing keeps doing. A number means the user has chosen a scale with
        # Ctrl+wheel, and it is then held regardless of the window size.
        self._zoom: float | None = None

        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(360, 200)
        theme.changed.connect(self.update)

    # -- data --------------------------------------------------------------------

    def set_board(self, layout: Layout, keycodes: KeycodeSet) -> None:
        self._layout = layout
        self._keycodes = keycodes
        self._selected = -1
        self._apply_zoom_size()
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

    def _board_size(self) -> tuple[float, float]:
        if self._layout is None or not self._layout.keys:
            return (1.0, 1.0)
        min_x, min_y, max_x, max_y = self._layout.bounds
        unit = self._unit()
        return (max(1e-6, (max_x - min_x) * unit), max(1e-6, (max_y - min_y) * unit))

    def natural_size(self) -> tuple[int, int]:
        """How much room the board wants in order to need no scrollbars.

        At the current zoom, or at 1:1 in fit mode — fit mode shrinks to whatever it
        is given, so its "natural" size is the one where nothing is shrunk. Returns
        ``(0, 0)`` before the keyboard's layout has arrived.
        """
        if self._layout is None or not self._layout.keys:
            return (0, 0)
        width, height = self._board_size()
        scale = self._zoom if self._zoom is not None else 1.0
        return (int(width * scale) + 24, int(height * scale) + 24)

    def _fit_scale(self) -> float:
        width, height = self._board_size()
        margin = 12.0
        available_w = max(1.0, self.width() - margin * 2)
        available_h = max(1.0, self.height() - margin * 2)
        return min(available_w / width, available_h / height, 1.0)

    def _compute_scale(self) -> None:
        if self._layout is None or not self._layout.keys:
            self._scale, self._origin = 1.0, QPointF(0, 0)
            return
        min_x, min_y, _max_x, _max_y = self._layout.bounds
        unit = self._unit()
        width, height = self._board_size()

        self._scale = self._zoom if self._zoom is not None else self._fit_scale()
        drawn_w, drawn_h = width * self._scale, height * self._scale
        # Centre whatever room is left over, so a board smaller than the window sits
        # in the middle and one larger than it starts at the edge.
        self._origin = QPointF(
            max(0.0, (self.width() - drawn_w) / 2) - min_x * unit * self._scale,
            max(0.0, (self.height() - drawn_h) / 2) - min_y * unit * self._scale,
        )

    # -- zoom --------------------------------------------------------------------

    def zoom(self) -> float | None:
        return self._zoom

    def effective_scale(self) -> float:
        return self._zoom if self._zoom is not None else self._fit_scale()

    def set_zoom(self, zoom: float | None) -> None:
        if zoom is not None:
            zoom = max(self.ZOOM_MIN, min(self.ZOOM_MAX, zoom))
        self._zoom = zoom
        self._apply_zoom_size()
        self.update()
        self.zoomChanged.emit(self.effective_scale())

    def zoom_to_fit(self) -> None:
        self.set_zoom(None)

    def _apply_zoom_size(self) -> None:
        """Ask for room when zoomed in, so the scroll area grows scrollbars.

        In fit mode the widget stays deliberately small so it follows the window
        instead of forcing it wider.
        """
        if self._zoom is None:
            self.setMinimumSize(360, 200)
            return
        width, height = self._board_size()
        self.setMinimumSize(
            int(width * self._zoom) + 24, int(height * self._zoom) + 24
        )

    def wheelEvent(self, event) -> None:  # noqa: N802  (Qt naming)
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            notches = event.angleDelta().y() / 120.0
            if notches:
                # Starting from the current effective scale means the first notch
                # continues from what is on screen rather than jumping.
                current = self.effective_scale()
                self.set_zoom(current * (self.ZOOM_STEP**notches))
            event.accept()
            return
        # Anything else belongs to the scroll area this sits in.
        event.ignore()

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
            changed = kmid < len(self._baseline) and self._baseline[kmid] != code

            # Every key keeps the board's own background and the label keeps the
            # label colour. State is carried by the border and a corner marker
            # instead, because a filled key means yellow text on a coloured wash,
            # and that is unreadable at any size.
            painter.fillPath(path, theme.colour("key.background"))

            border = theme.colour("key.border")
            width = border_width
            if info.is_empty:
                border = theme.colour("state.empty")
            elif info.is_unset:
                border = theme.colour("state.unset")
            elif info.kind in KIND_TINTS:
                border = theme.colour(KIND_TINTS[info.kind])
            if changed:
                border = theme.colour("state.changed")
            if kmid == self._selected:
                border, width = theme.colour("state.selected"), border_width * 2.5
            elif kmid == self._hovered:
                width = border_width * 1.8

            painter.setPen(QPen(border, width))
            painter.drawPath(path)

            if changed:
                self._draw_change_marker(painter, key)
            self._draw_label(painter, key, info)

    def _key_rect(self, key: KeyPosition) -> QRectF:
        unit = self._unit() * self._scale
        gap_h = float(self._theme["board.gap_h"]) * self._scale
        gap_v = float(self._theme["board.gap_v"]) * self._scale
        return QRectF(
            self._origin.x() + key.x * unit + gap_h / 2,
            self._origin.y() + key.y * unit + gap_v / 2,
            key.width * unit - gap_h,
            key.height * unit - gap_v,
        )

    def _begin_rotation(self, painter: QPainter, key: KeyPosition) -> bool:
        if not key.rotation_angle:
            return False
        unit = self._unit() * self._scale
        pivot = QPointF(
            self._origin.x() + key.rotation_x * unit,
            self._origin.y() + key.rotation_y * unit,
        )
        painter.save()
        painter.translate(pivot)
        painter.rotate(key.rotation_angle)
        painter.translate(-pivot)
        return True

    def _draw_change_marker(self, painter: QPainter, key: KeyPosition) -> None:
        """A small filled corner wedge — an edit is visible without tinting the key."""
        rotated = self._begin_rotation(painter, key)
        rect = self._key_rect(key)
        size = max(5.0, min(rect.width(), rect.height()) * 0.26)
        wedge = QPainterPath()
        wedge.moveTo(rect.right(), rect.top())
        wedge.lineTo(rect.right() - size, rect.top())
        wedge.lineTo(rect.right(), rect.top() + size)
        wedge.closeSubpath()
        painter.fillPath(wedge, self._theme.colour("state.changed"))
        if rotated:
            painter.restore()

    def _draw_label(self, painter: QPainter, key: KeyPosition, info) -> None:
        theme = self._theme
        rotated = self._begin_rotation(painter, key)
        rect = self._key_rect(key)

        strip, text = split_label(info)

        # A transparent key is only its glyph. Anything heavier turns a fall-through
        # layer into a wall of colour, which is what layer 3 looked like.
        if info.is_transparent:
            painter.setFont(
                themed_font(
                    str(theme["key.label.font"]),
                    int(theme["key.label.weight"]),
                    max(6.0, float(theme["key.label.size"]) * self._scale),
                )
            )
            painter.setPen(theme.colour("state.transparent"))
            painter.drawText(rect, int(Qt.AlignmentFlag.AlignCenter), "▽")
            if rotated:
                painter.restore()
            return

        if info.is_empty or info.is_unset:
            if rotated:
                painter.restore()
            return

        body = rect
        if strip:
            strip_size = max(5.0, float(theme["key.sublabel.size"]) * self._scale)
            strip_font = themed_font(
                str(theme["key.sublabel.font"]),
                int(theme["key.sublabel.weight"]),
                strip_size,
            )
            painter.setFont(strip_font)
            strip_height = QFontMetricsF(strip_font).height()
            strip_rect = QRectF(
                rect.left() + 2, rect.top() + 1, rect.width() - 4, strip_height
            )
            painter.setPen(
                theme.colour(KIND_TINTS.get(info.kind, "key.sublabel.colour"))
            )
            painter.drawText(
                strip_rect,
                int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop),
                strip,
            )
            body = QRectF(
                rect.left(),
                rect.top() + strip_height,
                rect.width(),
                rect.height() - strip_height,
            )

        size = max(5.0, float(theme["key.label.size"]) * self._scale)
        font = themed_font(
            str(theme["key.label.font"]), int(theme["key.label.weight"]), size
        )
        # Shrink rather than clip: several Svalboard labels are three stacked words.
        for _ in range(8):
            font.setPointSizeF(size)
            metrics = QFontMetricsF(font)
            widest = max(
                (metrics.horizontalAdvance(line) for line in text.split("\n")),
                default=0.0,
            )
            if widest <= body.width() - 6 or size <= 5.0:
                break
            size -= 1.0

        painter.setFont(font)
        painter.setPen(theme.colour("key.label.colour"))
        painter.drawText(
            body,
            int(Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap),
            text,
        )
        if rotated:
            painter.restore()


_COMPOSITE = re.compile(r"^([A-Za-z0-9_]+)\((.+)\)$")


def split_label(info) -> tuple[str, str]:
    """Separate a composite keycode into a corner strip and the key's own label.

    ``LCTL_T(KC_ENTER)`` is two facts — hold for Control, tap for Enter — and showing
    only "Enter" hides half of it. The held half goes in a small strip above the
    label. Layer operations already read as two lines and are left alone, and so is
    a template, whose label already says which half is missing.
    """
    if info.kind in (KIND_LAYER, KIND_TEMPLATE):
        return "", info.label
    match = _COMPOSITE.match(info.name)
    if match is not None:
        outer, label = match.group(1), info.label
        # A few labels already open with the outer name — OSM(MOD_LSFT) is labelled
        # "OSM\nLSft". Putting it in the strip as well says it twice and makes the
        # key a line too tall for its own body.
        head, _, rest = label.partition("\n")
        return outer, rest if rest and head == outer else label
    # A modifier combination Vial cannot name falls back to hex, which says nothing.
    # Its bits still do.
    if info.kind == KIND_MASKED and (mask := modifier_mask(info.code)):
        return modifier_label(mask), info.label
    return "", info.label


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

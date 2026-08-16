# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 白い熊
"""Choosing a keycode: categories, and a search box across all of them.

The web configurator spreads roughly 1,600 keycodes over a dozen tabs with no search,
so finding one means already knowing which tab it lives in. Here the search runs
across every name, label and description at once, and it is the first thing focused.
"""

from __future__ import annotations

from PyQt6.QtCore import QEvent, QObject, Qt, pyqtSignal
from PyQt6.QtGui import QFontMetricsF
from PyQt6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ...protocol.keycodes import KIND_TEMPLATE, KeycodeInfo, KeycodeSet
from ..theme import Theme
from .house import PillButton, themed_font
from .keyboard_canvas import KIND_TINTS, split_label


class KeycodeButton(QWidget):
    """One pickable keycode, drawn like a key so the picker reads as a keyboard."""

    chosen = pyqtSignal(object)

    def __init__(
        self,
        info: KeycodeInfo,
        theme: Theme,
        *,
        unit: int,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._info = info
        self._theme = theme
        self._unit = unit
        self._hovered = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(
            f"{info.name}\n{info.tooltip}" if info.tooltip != info.name else info.name
        )
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setFixedSize(unit, unit)

    def info(self) -> KeycodeInfo:
        return self._info

    def label_scale(self) -> float:
        """How far the key has been scaled, so its label follows."""
        return self._unit / max(1.0, float(self._theme["picker.unit"]))

    def enterEvent(self, event) -> None:  # noqa: N802  (Qt naming)
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.chosen.emit(self._info)
        super().mouseReleaseEvent(event)

    def paintEvent(self, _event) -> None:  # noqa: N802
        from PyQt6.QtGui import QPainter, QPainterPath, QPen
        from PyQt6.QtCore import QRectF

        theme = self._theme
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        radius = float(theme["key.corner"])
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        painter.fillPath(path, theme.colour("key.background"))

        border = theme.colour(KIND_TINTS.get(self._info.kind, "key.border"))
        width = float(theme["key.border_width"]) * (1.8 if self._hovered else 1.0)
        painter.setPen(QPen(border, width))
        painter.drawPath(path)

        # The held half goes in a strip above the label, exactly as the board draws
        # it — otherwise LGUI(KC_1) and a plain 1 are the same button to look at.
        strip, text = split_label(self._info)
        body = rect
        if strip:
            strip_size = max(
                5.0, float(theme["key.sublabel.size"]) * self.label_scale()
            )
            strip_font = themed_font(
                str(theme["key.sublabel.font"]),
                int(theme["key.sublabel.weight"]),
                strip_size,
            )
            painter.setFont(strip_font)
            strip_height = QFontMetricsF(strip_font).height()
            painter.setPen(
                theme.colour(KIND_TINTS.get(self._info.kind, "key.sublabel.colour"))
            )
            painter.drawText(
                QRectF(rect.left() + 2, rect.top() + 1, rect.width() - 4, strip_height),
                int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop),
                strip,
            )
            body = QRectF(
                rect.left(),
                rect.top() + strip_height,
                rect.width(),
                rect.height() - strip_height,
            )

        text = text or self._info.name.removeprefix("KC_")
        size = max(5.0, float(theme["key.label.size"]) * self.label_scale())
        font = themed_font(str(theme["key.label.font"]), int(theme["key.label.weight"]), size)
        for _ in range(8):
            font.setPointSizeF(size)
            widest = max(
                (QFontMetricsF(font).horizontalAdvance(line) for line in text.split("\n")),
                default=0.0,
            )
            if widest <= body.width() - 4 or size <= 5.0:
                break
            size -= 1.0
        painter.setFont(font)
        painter.setPen(theme.colour("key.label.colour"))
        painter.drawText(
            body, int(Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap), text
        )


class KeycodePicker(QWidget):
    """A search box, a category chooser, and a grid of keycodes."""

    keycodeChosen = pyqtSignal(object)
    #: Emitted with the xkb layout code, or "" for none.
    layoutChanged = pyqtSignal(str)
    #: Emitted with the zoom factor whenever Ctrl+wheel changes it.
    zoomChanged = pyqtSignal(float)

    #: Tabs built from the connected keyboard rather than the static table.
    RUNTIME_CATEGORIES = ("Svalboard", "Layers", "Macros", "Tap dances")

    ZOOM_STEP = 1.1
    ZOOM_MIN = 0.4
    ZOOM_MAX = 3.0

    def __init__(self, theme: Theme, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._theme = theme
        self._keycodes: KeycodeSet | None = None
        self._custom_names: list[str] = []
        self._zoom = 1.0
        # Rebuilding 240 buttons on every resize would be wasteful, so the grid is
        # only rebuilt when the shape it would take actually changes.
        self._built: tuple[int, int, int] | None = None
        #: The template awaiting its inner keycode, and where to go back to once it
        #: has one. Composing is deliberately modal: the next click means something
        #: different, and the banner is there to say so.
        self._pending: KeycodeInfo | None = None
        self._resume: tuple[str, str] | None = None

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search every keycode — name, label or description")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._refresh)
        # Escape has to reach the picker even while the search box has the focus,
        # which it otherwise would not.
        self.search.installEventFilter(self)

        self.category = QComboBox()
        self.category.currentIndexChanged.connect(lambda _index: self._refresh())

        self.layout_box = QComboBox()
        self.layout_box.setToolTip(
            "Label keys by what they type on this computer's keyboard layout. "
            "Only the labels change; the keycodes written to the keyboard do not."
        )
        self.layout_box.currentIndexChanged.connect(self._on_layout_changed)

        self.status = QLabel()
        self.status.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(8)
        controls.addWidget(self.search, 1)
        controls.addWidget(self.category)
        controls.addWidget(self.layout_box)
        controls.addWidget(self.status)

        # Only visible while a template is waiting for its inner keycode.
        self.compose_label = QLabel()
        self.compose_label.setWordWrap(True)
        self.compose_cancel = PillButton("Cancel", theme, compact=True)
        self.compose_cancel.clicked.connect(self.cancel_compose)
        self.compose_bar = QWidget()
        banner = QHBoxLayout(self.compose_bar)
        banner.setContentsMargins(0, 0, 0, 0)
        banner.setSpacing(8)
        banner.addWidget(self.compose_label, 1)
        banner.addWidget(self.compose_cancel)
        self.compose_bar.hide()

        self._grid_host = QWidget()
        self._grid = QGridLayout(self._grid_host)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)

        self._scroll = QScrollArea()
        scroll = self._scroll
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._grid_host)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        column = QVBoxLayout(self)
        column.setContentsMargins(8, 8, 8, 8)
        column.setSpacing(6)
        column.addLayout(controls)
        column.addWidget(self.compose_bar)
        column.addWidget(scroll, 1)

        theme.changed.connect(self._refresh)

    # -- data --------------------------------------------------------------------

    def set_keycodes(self, keycodes: KeycodeSet, custom_names: list[str]) -> None:
        self._keycodes = keycodes
        self._custom_names = custom_names
        # A reconnect replaces the whole keycode set; a template left over from the
        # old one would compose against stale numbering.
        self._pending = None
        self._resume = None
        self.compose_bar.hide()

        blocked = self.category.blockSignals(True)
        self.category.clear()
        # Sorted without regard to case, so that the four built from the keyboard —
        # which are capitalised — take their alphabetical place instead of being
        # herded to the top by their capitals.
        self.category.addItems(
            sorted(
                [*self.RUNTIME_CATEGORIES, *keycodes.categories()], key=str.casefold
            )
        )
        # Basic is where a keymap edit almost always starts.
        index = self.category.findText("basic")
        self.category.setCurrentIndex(index if index >= 0 else 0)
        self.category.blockSignals(blocked)
        self._refresh()

    def populate_layouts(self, current: str = "") -> None:
        from ...protocol.layouts import available

        blocked = self.layout_box.blockSignals(True)
        self.layout_box.clear()
        self.layout_box.addItem("US labels", "")
        for code, name in available():
            self.layout_box.addItem(name, code)
        index = self.layout_box.findData(current)
        self.layout_box.setCurrentIndex(index if index >= 0 else 0)
        self.layout_box.blockSignals(blocked)

    def _on_layout_changed(self, _index: int) -> None:
        self.layoutChanged.emit(str(self.layout_box.currentData() or ""))

    def refresh_labels(self) -> None:
        """Rebuild after the labels beneath the grid have changed."""
        self._built = None
        self._refresh()

    def focus_search(self) -> None:
        self.search.setFocus()
        self.search.selectAll()

    # -- composing a keycode out of two clicks -----------------------------------

    def composing(self) -> KeycodeInfo | None:
        """The template waiting for its inner keycode, if any."""
        return self._pending

    def _begin_compose(self, template: KeycodeInfo) -> None:
        """Ask for the inner keycode that completes ``template``."""
        outer = template.name.removesuffix("(kc)")
        self._pending = template
        # Remember where they were, so finishing or cancelling puts them back rather
        # than stranding them in the basic tab.
        self._resume = (self.category.currentText(), self.search.text())
        self.compose_label.setText(f"{outer} — now choose the key it holds down.")
        if outer.startswith("LT") and outer[2:].isdigit():
            self.compose_label.setText(
                f"{outer} — now choose the key it types when tapped."
            )
        self.compose_bar.show()

        # Basic is where the inner keycode almost always comes from, and the search
        # box would otherwise still be filtering to the template itself.
        blocked = self.category.blockSignals(True)
        index = self.category.findText("basic")
        if index >= 0:
            self.category.setCurrentIndex(index)
        self.category.blockSignals(blocked)
        blocked = self.search.blockSignals(True)
        self.search.clear()
        self.search.blockSignals(blocked)
        self._refresh()

    def cancel_compose(self) -> None:
        """Abandon a half-built keycode and put the picker back where it was."""
        if self._pending is None:
            return
        self._pending = None
        self.compose_bar.hide()
        self._restore_after_compose()
        self.status.setText("cancelled")

    def _restore_after_compose(self) -> None:
        resume, self._resume = self._resume, None
        if resume is None:
            self._refresh()
            return
        category, query = resume
        blocked = self.category.blockSignals(True)
        index = self.category.findText(category)
        if index >= 0:
            self.category.setCurrentIndex(index)
        self.category.blockSignals(blocked)
        blocked = self.search.blockSignals(True)
        self.search.setText(query)
        self.search.blockSignals(blocked)
        self._refresh()

    def _on_chosen(self, info: KeycodeInfo) -> None:
        """One key in the grid was clicked — which may mean three different things."""
        pending = self._pending
        if pending is not None:
            if info.kind == KIND_TEMPLATE:
                # Two halves cannot both be outer: LGUI(LT2(kc)) is not a keycode.
                self.status.setText("needs a plain key")
                return
            if self._keycodes is None or not self._keycodes.composable(info.code):
                self.status.setText("cannot go inside")
                return
            code = self._keycodes.compose(pending.code, info.code)
            self._pending = None
            self.compose_bar.hide()
            self._restore_after_compose()
            self.keycodeChosen.emit(self._keycodes.info(code))
            return

        if info.kind == KIND_TEMPLATE:
            self._begin_compose(info)
            return

        self.keycodeChosen.emit(info)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
        if (
            event.type() == QEvent.Type.KeyPress
            and self._pending is not None
            and event.key() == Qt.Key.Key_Escape
        ):
            self.cancel_compose()
            return True
        return super().eventFilter(watched, event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape and self._pending is not None:
            self.cancel_compose()
            event.accept()
            return
        super().keyPressEvent(event)

    # -- contents ----------------------------------------------------------------

    def _entries(self) -> list[KeycodeInfo]:
        if self._keycodes is None:
            return []
        query = self.search.text().strip()
        if query:
            # Search deliberately ignores the category: not knowing which tab a
            # keycode lives in is the whole reason to search.
            return self._keycodes.search(query, limit=240)

        name = self.category.currentText()
        if name == "Svalboard":
            return [
                self._keycodes.info(self._keycodes.parse(qmk_id))
                for qmk_id in self._custom_names
            ]
        if name == "Layers":
            # LT comes last because it is the only one of the seven that asks a
            # second question, and because the plain operations are the common case.
            return [
                self._keycodes.info(self._keycodes.parse(f"{prefix}({layer})"))
                for prefix in ("MO", "TO", "DF", "TG", "OSL", "TT")
                for layer in range(self._keycodes.layers)
            ] + self._keycodes.layer_taps()
        if name == "Macros":
            return [
                self._keycodes.info(self._keycodes.parse(f"M{index}"))
                for index in range(self._keycodes.macros)
            ]
        if name == "Tap dances":
            return [
                self._keycodes.info(self._keycodes.parse(f"TD({index})"))
                for index in range(self._keycodes.tap_dances)
            ]
        return self._keycodes.category(name)

    # -- zoom --------------------------------------------------------------------

    def zoom(self) -> float:
        return self._zoom

    def set_zoom(self, zoom: float) -> None:
        zoom = max(self.ZOOM_MIN, min(self.ZOOM_MAX, zoom))
        if abs(zoom - self._zoom) < 1e-6:
            return
        self._zoom = zoom
        self._refresh()
        self.zoomChanged.emit(self._zoom)

    def _unit(self) -> int:
        return max(12, int(int(self._theme["picker.unit"]) * self._zoom))

    #: However tall the window is allowed to grow for the picker's sake. Some tabs
    #: run to hundreds of keycodes and no window is going to show them all at once.
    MAX_IDEAL_ROWS = 8

    def ideal_height(self, rows: int | None = None, *, width: int | None = None) -> int:
        """How tall the picker wants to be to show its keys unscrolled.

        With no row count, it asks for as many rows as the category it is showing
        actually needs — capped, and worked out at ``width`` rather than at the
        current width, because the window sizing this asks before it has resized.
        """
        unit = self._unit()
        spacing = int(self._theme["picker.spacing"])
        margins = self.layout().contentsMargins()

        if rows is None:
            room = width if width is not None else self._scroll.viewport().width()
            room = max(1, room - margins.left() - margins.right())
            fits = max(1, (room + spacing) // (unit + spacing))
            columns = max(1, min(fits, int(self._theme["picker.columns"])))
            rows = -(-len(self._entries()) // columns)
        rows = max(1, min(rows, self.MAX_IDEAL_ROWS))

        controls = max(
            self.search.sizeHint().height(), self.category.sizeHint().height()
        )
        return (
            margins.top()
            + margins.bottom()
            + controls
            + self.layout().spacing()
            + rows * unit
            + (rows - 1) * spacing
        )

    def _columns(self, count: int) -> int:
        """As many keys per row as the width allows, up to the declared maximum."""
        spacing = int(self._theme["picker.spacing"])
        available = max(1, self._scroll.viewport().width())
        fits = max(1, (available + spacing) // (self._unit() + spacing))
        return max(1, min(fits, int(self._theme["picker.columns"]), max(1, count)))

    def wheelEvent(self, event) -> None:  # noqa: N802  (Qt naming)
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            notches = event.angleDelta().y() / 120.0
            if notches:
                self.set_zoom(self._zoom * (self.ZOOM_STEP**notches))
            event.accept()
            return
        super().wheelEvent(event)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._refresh()

    # -- contents ----------------------------------------------------------------

    def _refresh(self) -> None:
        entries = self._entries()
        unit = self._unit()
        spacing = int(self._theme["picker.spacing"])
        columns = self._columns(len(entries))

        query = self.search.text().strip()
        if query and not entries:
            self.status.setText("nothing found")
        elif query:
            self.status.setText(f"{len(entries)} found")
        else:
            self.status.setText(f"{len(entries)}")

        # The signature has to cover *which* keycodes are shown, not just how many:
        # two categories of equal size are a different grid.
        shape = (hash(tuple(info.code for info in entries)), columns, unit)
        if shape == self._built:
            # Same grid, but a colour or font may have moved under it.
            for button in self._grid_host.findChildren(KeycodeButton):
                button.update()
            return
        self._built = shape

        while (item := self._grid.takeAt(0)) is not None:
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        self._grid.setHorizontalSpacing(spacing)
        self._grid.setVerticalSpacing(spacing)
        for position, info in enumerate(entries):
            button = KeycodeButton(info, self._theme, unit=unit)
            button.chosen.connect(self._on_chosen)
            self._grid.addWidget(button, position // columns, position % columns)

# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 白い熊
"""Editors for tap dances, combos and key overrides.

All three are lists of fixed slots, so they share a shape: a scrolling column of rows,
one per slot, each row's keycode fields being :class:`KeySlot` widgets that arm
themselves for the picker at the bottom of the window.

Unused slots are shown rather than hidden. The keyboard has a fixed number of them and
knowing how many are left is part of deciding what to do, which is why the header says
so.
"""

from __future__ import annotations

from collections.abc import Callable

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ...model.entries import EntryChanges
from ...protocol.dynamic import (
    MOD_LABELS,
    OPTION_LABELS,
    Combo,
    KeyOverride,
    TapDance,
)
from ...protocol.keycodes import KeycodeSet
from ..theme import Theme
from ..widgets.house import Heading, Row, themed_font
from ..widgets.key_slot import KeySlot


class EntryPage(QWidget):
    """Common scaffolding: a heading that counts used slots, and a scrolling body."""

    slotArmed = pyqtSignal(object, object)  # (KeySlot, setter)

    def __init__(self, title: str, theme: Theme, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._theme = theme
        self._keycodes: KeycodeSet | None = None
        self._slots: list[KeySlot] = []

        self.heading = Heading(title, theme, level=0)
        self.summary = QLabel()
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

    def _clear_rows(self) -> None:
        self._slots.clear()
        while (item := self.rows.takeAt(0)) is not None:
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _new_slot(self, code: int, setter: Callable[[int], None], width: int = 92) -> KeySlot:
        assert self._keycodes is not None
        slot = KeySlot(self._theme, self._keycodes, code=code, width=width)
        slot.armed.connect(lambda s, fn=setter: self.slotArmed.emit(s, fn))
        slot.cleared.connect(lambda s, fn=setter: fn(0))
        self._slots.append(slot)
        return slot

    def clear_arming(self) -> None:
        for slot in self._slots:
            slot.set_active(False)

    def _index_label(self, index: int, changed: bool) -> QLabel:
        label = QLabel(f"{index}" + (" •" if changed else ""))
        label.setFixedWidth(38)
        label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        label.setStyleSheet(
            f"color: {self._theme.css('state.changed' if changed else 'window.dim')};"
        )
        return label


class TapDancePage(EntryPage):
    """Tap, hold, double-tap, tap-then-hold, and the term that separates them."""

    COLUMNS = ("Tap", "Hold", "Double tap", "Tap then hold")

    def __init__(self, theme: Theme, parent: QWidget | None = None) -> None:
        super().__init__("Tap dances", theme, parent)
        self._changes: EntryChanges[TapDance] | None = None

    def bind(self, changes: EntryChanges[TapDance], keycodes: KeycodeSet) -> None:
        self._changes = changes
        self._keycodes = keycodes
        self.rebuild()

    def rebuild(self) -> None:
        if self._changes is None or self._keycodes is None:
            return
        self._clear_rows()
        changes = self._changes
        used = sum(1 for entry in changes.working if not entry.is_empty)
        self.summary.setText(
            f"{used} of {len(changes)} used. A tapping term of 0 means the keyboard's "
            f"own default."
        )

        header = QWidget()
        head = QHBoxLayout(header)
        head.setContentsMargins(int(self._theme["row.indent"]), 0, 16, 2)
        head.setSpacing(8)
        head.addWidget(self._index_label(0, False).__class__(""), 0)
        for name in self.COLUMNS:
            label = QLabel(name)
            label.setFixedWidth(92)
            label.setStyleSheet(f"color: {self._theme.css('row.description.colour')};")
            head.addWidget(label)
        term = QLabel("Term")
        term.setStyleSheet(f"color: {self._theme.css('row.description.colour')};")
        head.addWidget(term)
        head.addStretch(1)
        self.rows.addWidget(header)

        for index in range(len(changes)):
            self.rows.addWidget(self._row(index))

    def _row(self, index: int) -> QWidget:
        assert self._changes is not None
        changes = self._changes
        entry = changes[index]

        widget = QWidget()
        row = QHBoxLayout(widget)
        row.setContentsMargins(int(self._theme["row.indent"]), 2, 16, 2)
        row.setSpacing(8)
        row.addWidget(self._index_label(index, changes.is_changed(index)))

        fields = ("on_tap", "on_hold", "on_double_tap", "on_tap_hold")
        for name in fields:
            def setter(code: int, field=name, i=index) -> None:
                from dataclasses import replace

                changes.set(i, replace(changes[i], **{field: code}))
                self.rebuild()

            row.addWidget(self._new_slot(getattr(entry, name), setter))

        term = QSpinBox()
        term.setRange(0, 5000)
        term.setSingleStep(10)
        term.setSuffix(" ms")
        term.setValue(entry.tapping_term)
        term.setFixedWidth(96)

        def set_term(value: int, i=index) -> None:
            from dataclasses import replace

            changes.set(i, replace(changes[i], tapping_term=value))

        term.valueChanged.connect(set_term)
        row.addWidget(term)
        row.addStretch(1)
        return widget


class ComboPage(EntryPage):
    """Up to four keys pressed together, producing one."""

    def __init__(self, theme: Theme, parent: QWidget | None = None) -> None:
        super().__init__("Combos", theme, parent)
        self._changes: EntryChanges[Combo] | None = None

    def bind(self, changes: EntryChanges[Combo], keycodes: KeycodeSet) -> None:
        self._changes = changes
        self._keycodes = keycodes
        self.rebuild()

    def rebuild(self) -> None:
        if self._changes is None or self._keycodes is None:
            return
        self._clear_rows()
        changes = self._changes
        used = sum(1 for entry in changes.working if not entry.is_empty)
        self.summary.setText(
            f"{used} of {len(changes)} used. Leave a trigger empty to use fewer than "
            f"four keys."
        )
        for index in range(len(changes)):
            self.rows.addWidget(self._row(index))

    def _row(self, index: int) -> QWidget:
        assert self._changes is not None
        changes = self._changes
        entry = changes[index]

        widget = QWidget()
        row = QHBoxLayout(widget)
        row.setContentsMargins(int(self._theme["row.indent"]), 2, 16, 2)
        row.setSpacing(8)
        row.addWidget(self._index_label(index, changes.is_changed(index)))

        for position in range(4):
            def setter(code: int, slot=position, i=index) -> None:
                from dataclasses import replace

                keys = list(changes[i].keys)
                keys[slot] = code
                changes.set(i, replace(changes[i], keys=tuple(keys)))
                self.rebuild()

            row.addWidget(self._new_slot(entry.keys[position], setter))
            if position < 3:
                plus = QLabel("+")
                plus.setStyleSheet(f"color: {self._theme.css('window.dim')};")
                row.addWidget(plus)

        equals = QLabel("=")
        equals.setStyleSheet(f"color: {self._theme.css('window.text')};")
        row.addWidget(equals)

        def set_output(code: int, i=index) -> None:
            from dataclasses import replace

            changes.set(i, replace(changes[i], output=code))
            self.rebuild()

        row.addWidget(self._new_slot(entry.output, set_output))
        row.addStretch(1)
        return widget


class KeyOverridePage(EntryPage):
    """One key replaced by another while given modifiers and layers apply."""

    def __init__(self, theme: Theme, parent: QWidget | None = None) -> None:
        super().__init__("Key overrides", theme, parent)
        self._changes: EntryChanges[KeyOverride] | None = None
        self._layers = 16

    def bind(
        self, changes: EntryChanges[KeyOverride], keycodes: KeycodeSet, *, layers: int
    ) -> None:
        self._changes = changes
        self._keycodes = keycodes
        self._layers = layers
        self.rebuild()

    def rebuild(self) -> None:
        if self._changes is None or self._keycodes is None:
            return
        self._clear_rows()
        changes = self._changes
        used = sum(1 for entry in changes.working if not entry.is_empty)
        self.summary.setText(
            f"{used} of {len(changes)} used. An override does nothing until it is "
            f"enabled."
        )
        for index in range(len(changes)):
            if changes[index].is_empty and index > used + 2:
                # The tail of an override list is long and each row is tall; showing
                # a few spare slots is useful, showing thirty is noise.
                continue
            self.rows.addWidget(self._row(index))

    def _row(self, index: int) -> QWidget:
        from dataclasses import replace

        assert self._changes is not None
        changes = self._changes
        entry = changes[index]

        widget = QWidget()
        grid = QGridLayout(widget)
        grid.setContentsMargins(int(self._theme["row.indent"]), 4, 16, 8)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(3)

        grid.addWidget(self._index_label(index, changes.is_changed(index)), 0, 0)

        enabled = QCheckBox("Enabled")
        enabled.setChecked(entry.enabled)
        enabled.toggled.connect(
            lambda value, i=index: changes.set(i, changes[i].with_enabled(value))
        )
        grid.addWidget(enabled, 0, 1)

        def set_trigger(code: int, i=index) -> None:
            changes.set(i, replace(changes[i], trigger=code))
            self.rebuild()

        def set_replacement(code: int, i=index) -> None:
            changes.set(i, replace(changes[i], replacement=code))
            self.rebuild()

        grid.addWidget(self._new_slot(entry.trigger, set_trigger), 0, 2)
        arrow = QLabel("→")
        arrow.setStyleSheet(f"color: {self._theme.css('window.text')};")
        grid.addWidget(arrow, 0, 3)
        grid.addWidget(self._new_slot(entry.replacement, set_replacement), 0, 4)

        masks = (
            ("Trigger modifiers", "trigger_mods"),
            ("Blocked by", "negative_mod_mask"),
            ("Suppressed", "suppressed_mods"),
        )
        for offset, (title, field) in enumerate(masks):
            grid.addWidget(self._caption(title), 1 + offset, 1)
            grid.addLayout(self._mask_row(index, field), 1 + offset, 2, 1, 6)

        grid.addWidget(self._caption("Layers"), 4, 1)
        grid.addLayout(self._layer_row(index), 4, 2, 1, 6)

        grid.addWidget(self._caption("Options"), 5, 1)
        grid.addLayout(self._option_row(index), 5, 2, 1, 6)

        grid.setColumnStretch(6, 1)
        return widget

    def _caption(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet(f"color: {self._theme.css('row.description.colour')};")
        label.setFont(
            themed_font(
                str(self._theme["row.description.font"]),
                int(self._theme["row.description.weight"]),
                int(self._theme["row.description.size"]),
            )
        )
        return label

    def _mask_row(self, index: int, field: str) -> QHBoxLayout:
        from dataclasses import replace

        assert self._changes is not None
        changes = self._changes
        row = QHBoxLayout()
        row.setSpacing(6)
        current = getattr(changes[index], field)
        for bit, name in MOD_LABELS:
            box = QCheckBox(name)
            box.setChecked(bool(current & bit))

            def toggle(value: bool, b=bit, f=field, i=index) -> None:
                mask = getattr(changes[i], f)
                mask = mask | b if value else mask & ~b
                changes.set(i, replace(changes[i], **{f: mask & 0xFF}))

            box.toggled.connect(toggle)
            row.addWidget(box)
        row.addStretch(1)
        return row

    def _layer_row(self, index: int) -> QHBoxLayout:
        from dataclasses import replace

        assert self._changes is not None
        changes = self._changes
        row = QHBoxLayout()
        row.setSpacing(4)
        for layer in range(self._layers):
            box = QCheckBox(str(layer))
            box.setChecked(changes[index].applies_to_layer(layer))

            def toggle(value: bool, bit=1 << layer, i=index) -> None:
                mask = changes[i].layers
                mask = mask | bit if value else mask & ~bit
                changes.set(i, replace(changes[i], layers=mask & 0xFFFF))

            box.toggled.connect(toggle)
            row.addWidget(box)
        row.addStretch(1)
        return row

    def _option_row(self, index: int) -> QVBoxLayout:
        from dataclasses import replace

        assert self._changes is not None
        changes = self._changes
        column = QVBoxLayout()
        column.setSpacing(1)
        for bit, name in OPTION_LABELS:
            box = QCheckBox(name)
            box.setChecked(bool(changes[index].options & bit))

            def toggle(value: bool, b=bit, i=index) -> None:
                options = changes[i].options
                options = options | b if value else options & ~b
                changes.set(i, replace(changes[i], options=options & 0xFF))

            box.toggled.connect(toggle)
            column.addWidget(box)
        return column

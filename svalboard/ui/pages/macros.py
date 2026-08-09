# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 白い熊
"""The macro editor: a list of macros on the left, one macro's actions on the right.

Unlike the other entry editors, a macro is an ordered sequence rather than a fixed set
of fields, so each action is a row that can be moved, edited or removed. The header
carries the shared buffer's remaining space, because macros compete for it — one long
macro can leave no room for the rest, and that is worth seeing before writing.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ...model.entries import MacroChanges
from ...protocol.keycodes import KeycodeSet
from ...protocol.macros import Action, Macro
from ..theme import Theme
from ..widgets.house import Heading, PillButton
from ..widgets.key_slot import KeySlot

ACTION_KINDS = (("Text", "text"), ("Tap", "tap"), ("Hold", "down"), ("Release", "up"),
                ("Delay", "delay"))


class MacroPage(QWidget):
    slotArmed = pyqtSignal(object, object)

    def __init__(self, theme: Theme, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._theme = theme
        self._changes: MacroChanges | None = None
        self._keycodes: KeycodeSet | None = None
        self._current = 0
        self._slots: list[KeySlot] = []

        self.heading = Heading("Macros", theme, level=0)
        self.summary = QLabel()
        self.summary.setContentsMargins(int(theme["row.indent"]), 0, 16, 6)

        self.list = QListWidget()
        self.list.setFixedWidth(190)
        self.list.currentRowChanged.connect(self._select)

        self.actions_host = QWidget()
        self.actions = QVBoxLayout(self.actions_host)
        self.actions.setContentsMargins(0, 0, 8, 8)
        self.actions.setSpacing(3)
        self.actions.setAlignment(Qt.AlignmentFlag.AlignTop)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.actions_host)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)

        add_row = QHBoxLayout()
        add_row.setSpacing(6)
        add_row.addWidget(QLabel("Add:"))
        for title, kind in ACTION_KINDS:
            button = PillButton(title, theme)
            button.clicked.connect(lambda _checked=False, k=kind: self._add(k))
            add_row.addWidget(button)
        add_row.addStretch(1)
        self.clear_button = PillButton("Clear macro", theme)
        self.clear_button.clicked.connect(self._clear)
        add_row.addWidget(self.clear_button)

        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(6)
        right.addLayout(add_row)
        right.addWidget(scroll, 1)

        split = QHBoxLayout()
        split.setContentsMargins(int(theme["row.indent"]), 0, 16, 8)
        split.setSpacing(12)
        split.addWidget(self.list)
        split.addLayout(right, 1)

        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        column.addWidget(self.heading)
        column.addWidget(self.summary)
        column.addLayout(split, 1)

        theme.changed.connect(self._restyle)
        self._restyle()

    def _restyle(self) -> None:
        self.summary.setStyleSheet(f"color: {self._theme.css('row.description.colour')};")

    # -- data --------------------------------------------------------------------

    def bind(self, changes: MacroChanges, keycodes: KeycodeSet) -> None:
        self._changes = changes
        self._keycodes = keycodes
        self._current = 0
        self.rebuild()

    def current_index(self) -> int:
        return self._current

    def show_macro(self, index: int) -> None:
        self._current = index
        self.list.setCurrentRow(index)
        self.rebuild()

    def clear_arming(self) -> None:
        for slot in self._slots:
            slot.set_active(False)

    def rebuild(self) -> None:
        if self._changes is None or self._keycodes is None:
            return
        changes = self._changes
        used = sum(1 for macro in changes.working if not macro.is_empty)
        room = changes.size
        needed = changes.bytes_used()
        warning = "" if changes.fits() else "  — over capacity, cannot be written"
        self.summary.setText(
            f"{used} of {len(changes)} used · {needed} of {room} bytes{warning}"
        )

        blocked = self.list.blockSignals(True)
        self.list.clear()
        for index, macro in enumerate(changes.working):
            preview = macro.text_preview()
            if not preview and not macro.is_empty:
                preview = f"{len(macro.actions)} actions"
            marker = " •" if changes.is_changed(index) else ""
            item = QListWidgetItem(f"M{index}{marker}" + (f"   {preview}" if preview else ""))
            self.list.addItem(item)
        self.list.setCurrentRow(self._current)
        self.list.blockSignals(blocked)

        self._rebuild_actions()

    def _select(self, index: int) -> None:
        if index >= 0:
            self._current = index
            self._rebuild_actions()

    # -- the action list ---------------------------------------------------------

    def _rebuild_actions(self) -> None:
        if self._changes is None or self._keycodes is None:
            return
        self._slots.clear()
        while (item := self.actions.takeAt(0)) is not None:
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        macro = self._changes[self._current]
        if not macro.actions:
            empty = QLabel("No actions yet. Add one above.")
            empty.setStyleSheet(f"color: {self._theme.css('window.dim')};")
            self.actions.addWidget(empty)
            return
        for position, action in enumerate(macro.actions):
            self.actions.addWidget(self._action_row(position, action))

    def _action_row(self, position: int, action: Action) -> QWidget:
        widget = QWidget()
        row = QHBoxLayout(widget)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)

        for label, delta in (("↑", -1), ("↓", +1)):
            button = PillButton(label, self._theme, compact=True)
            button.setFixedWidth(34)
            button.clicked.connect(lambda _c=False, p=position, d=delta: self._move(p, d))
            row.addWidget(button)

        kind = QLabel({"text": "Text", "tap": "Tap", "down": "Hold",
                       "up": "Release", "delay": "Delay"}[action.kind])
        kind.setFixedWidth(64)
        row.addWidget(kind)

        if action.is_text:
            field = QLineEdit(action.text)
            field.setMinimumWidth(240)
            field.textChanged.connect(
                lambda value, p=position: self._replace(p, Action("text", text=value))
            )
            row.addWidget(field, 1)
        elif action.is_delay:
            spin = QSpinBox()
            spin.setRange(1, 64000)
            spin.setSuffix(" ms")
            spin.setValue(max(1, action.delay))
            spin.setFixedWidth(110)
            spin.valueChanged.connect(
                lambda value, p=position: self._replace(p, Action("delay", delay=value))
            )
            row.addWidget(spin)
            note = QLabel("a delay cannot be zero")
            note.setStyleSheet(f"color: {self._theme.css('window.dim')};")
            row.addWidget(note)
            row.addStretch(1)
        else:
            assert self._keycodes is not None
            slot = KeySlot(self._theme, self._keycodes, code=action.keycode)
            slot.armed.connect(
                lambda s, p=position, k=action.kind: self.slotArmed.emit(
                    s, lambda code: self._replace(p, Action(k, keycode=code))
                )
            )
            slot.cleared.connect(
                lambda _s, p=position, k=action.kind: self._replace(p, Action(k, keycode=0))
            )
            self._slots.append(slot)
            row.addWidget(slot)
            row.addStretch(1)

        remove = PillButton("Remove", self._theme, compact=True)
        remove.clicked.connect(lambda _c=False, p=position: self._remove(p))
        row.addWidget(remove)
        return widget

    # -- editing -----------------------------------------------------------------

    def _write(self, actions: list[Action]) -> None:
        assert self._changes is not None
        self._changes.set(self._current, Macro(actions))
        self.rebuild()

    def _add(self, kind: str) -> None:
        if self._changes is None:
            return
        actions = list(self._changes[self._current].actions)
        if kind == "text":
            actions.append(Action("text", text=""))
        elif kind == "delay":
            actions.append(Action("delay", delay=100))
        else:
            actions.append(Action(kind, keycode=0))
        self._write(actions)

    def _replace(self, position: int, action: Action) -> None:
        if self._changes is None:
            return
        actions = list(self._changes[self._current].actions)
        if position >= len(actions) or actions[position] == action:
            return
        actions[position] = action
        # Text and delay edits come from a field the user is still typing in, so the
        # list is not rebuilt underneath them; only the summary needs refreshing.
        self._changes.set(self._current, Macro(actions))
        if action.is_text or action.is_delay:
            self.rebuild_summary_only()
        else:
            self.rebuild()

    def rebuild_summary_only(self) -> None:
        if self._changes is None:
            return
        changes = self._changes
        used = sum(1 for macro in changes.working if not macro.is_empty)
        warning = "" if changes.fits() else "  — over capacity, cannot be written"
        self.summary.setText(
            f"{used} of {len(changes)} used · {changes.bytes_used()} of "
            f"{changes.size} bytes{warning}"
        )

    def _move(self, position: int, delta: int) -> None:
        if self._changes is None:
            return
        actions = list(self._changes[self._current].actions)
        target = position + delta
        if not 0 <= target < len(actions):
            return
        actions[position], actions[target] = actions[target], actions[position]
        self._write(actions)

    def _remove(self, position: int) -> None:
        if self._changes is None:
            return
        actions = list(self._changes[self._current].actions)
        if position < len(actions):
            actions.pop(position)
            self._write(actions)

    def _clear(self) -> None:
        if self._changes is not None:
            self._changes.clear(self._current)
            self.rebuild()

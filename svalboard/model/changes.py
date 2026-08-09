# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 白い熊
"""What the keyboard holds, what it should hold, and the difference between them.

Two states are kept: the **baseline**, which is what was last read from or written to
the hardware, and the **working** copy, which is what the interface has been editing.
Everything the user sees as "changed" is the difference, and committing is replaying
that difference onto the keyboard.

This deliberately knows nothing about Qt, so it can be tested without a display, and
nothing about the protocol, so it can be reasoned about without a keyboard.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class KeyEdit:
    """One key assignment, remembered so it can be undone."""

    layer: int
    kmid: int
    before: int
    after: int


@dataclass(frozen=True)
class PendingWrite:
    """One write to send, addressed the way the protocol wants it."""

    layer: int
    row: int
    col: int
    code: int


class KeymapChanges:
    """The edit buffer for a keymap, with undo, redo and a pending-write list."""

    def __init__(self, *, rows: int, cols: int, layers: int) -> None:
        self.rows = rows
        self.cols = cols
        self.layers = layers
        self.keys_per_layer = rows * cols

        self._baseline: list[int] = []
        self._working: list[int] = []
        self._undo: list[KeyEdit] = []
        self._redo: list[KeyEdit] = []
        self._listeners: list[Callable[[], None]] = []

    # -- observation -------------------------------------------------------------

    def subscribe(self, listener: Callable[[], None]) -> None:
        self._listeners.append(listener)

    def _notify(self) -> None:
        for listener in self._listeners:
            listener()

    # -- loading -----------------------------------------------------------------

    def load(self, keymap: Iterable[int]) -> None:
        """Adopt what the keyboard holds, discarding any edit history."""
        self._baseline = list(keymap)
        self._working = list(self._baseline)
        self._undo.clear()
        self._redo.clear()
        self._notify()

    @property
    def loaded(self) -> bool:
        return bool(self._baseline)

    # -- reading -----------------------------------------------------------------

    def code(self, layer: int, kmid: int) -> int:
        return self._working[self._index(layer, kmid)]

    def baseline_code(self, layer: int, kmid: int) -> int:
        return self._baseline[self._index(layer, kmid)]

    def layer(self, index: int) -> list[int]:
        start = index * self.keys_per_layer
        return self._working[start : start + self.keys_per_layer]

    def baseline_layer(self, index: int) -> list[int]:
        start = index * self.keys_per_layer
        return self._baseline[start : start + self.keys_per_layer]

    @property
    def working(self) -> list[int]:
        return list(self._working)

    @property
    def baseline(self) -> list[int]:
        return list(self._baseline)

    def is_changed(self, layer: int, kmid: int) -> bool:
        index = self._index(layer, kmid)
        return self._working[index] != self._baseline[index]

    def changed_layers(self) -> set[int]:
        return {
            index // self.keys_per_layer
            for index, (working, baseline) in enumerate(
                zip(self._working, self._baseline, strict=True)
            )
            if working != baseline
        }

    @property
    def is_dirty(self) -> bool:
        return self._working != self._baseline

    def pending(self) -> list[PendingWrite]:
        """Every write needed to make the keyboard match the working copy."""
        writes: list[PendingWrite] = []
        for index, (working, baseline) in enumerate(
            zip(self._working, self._baseline, strict=True)
        ):
            if working == baseline:
                continue
            layer, rest = divmod(index, self.keys_per_layer)
            row, col = divmod(rest, self.cols)
            writes.append(PendingWrite(layer, row, col, working))
        return writes

    # -- editing -----------------------------------------------------------------

    def set_key(self, layer: int, kmid: int, code: int) -> KeyEdit | None:
        """Assign a key. Returns the edit, or ``None`` when nothing changed."""
        index = self._index(layer, kmid)
        before = self._working[index]
        if before == code:
            return None

        edit = KeyEdit(layer=layer, kmid=kmid, before=before, after=code)
        self._working[index] = code
        self._undo.append(edit)
        # A fresh edit abandons any redone-away future, as everywhere else.
        self._redo.clear()
        self._notify()
        return edit

    def revert_key(self, layer: int, kmid: int) -> KeyEdit | None:
        """Put one key back to what the keyboard holds."""
        return self.set_key(layer, kmid, self.baseline_code(layer, kmid))

    def revert_all(self) -> None:
        if not self.is_dirty:
            return
        self._working = list(self._baseline)
        self._undo.clear()
        self._redo.clear()
        self._notify()

    def fill_layer(self, layer: int, code: int, *, only_empty: bool = False) -> int:
        """Assign every position on a layer. Returns how many changed."""
        changed = 0
        for kmid in range(self.keys_per_layer):
            if only_empty and self.code(layer, kmid) != 0x0000:
                continue
            if self.set_key(layer, kmid, code) is not None:
                changed += 1
        return changed

    # -- undo and redo -----------------------------------------------------------

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    def undo(self) -> KeyEdit | None:
        if not self._undo:
            return None
        edit = self._undo.pop()
        self._working[self._index(edit.layer, edit.kmid)] = edit.before
        self._redo.append(edit)
        self._notify()
        return edit

    def redo(self) -> KeyEdit | None:
        if not self._redo:
            return None
        edit = self._redo.pop()
        self._working[self._index(edit.layer, edit.kmid)] = edit.after
        self._undo.append(edit)
        self._notify()
        return edit

    # -- committing --------------------------------------------------------------

    def mark_written(self, writes: Iterable[PendingWrite] | None = None) -> None:
        """Fold successful writes into the baseline.

        Passing the writes that actually succeeded means a partial commit — a
        keyboard unplugged halfway through — leaves the rest still showing as
        pending rather than silently pretending they landed.
        """
        if writes is None:
            self._baseline = list(self._working)
        else:
            for write in writes:
                index = (
                    write.layer * self.keys_per_layer + write.row * self.cols + write.col
                )
                self._baseline[index] = write.code
        self._undo.clear()
        self._redo.clear()
        self._notify()

    # -- internals ---------------------------------------------------------------

    def _index(self, layer: int, kmid: int) -> int:
        if not 0 <= layer < self.layers:
            raise IndexError(f"No layer {layer}; the keyboard has {self.layers}.")
        if not 0 <= kmid < self.keys_per_layer:
            raise IndexError(
                f"No position {kmid}; a layer has {self.keys_per_layer} of them."
            )
        return layer * self.keys_per_layer + kmid

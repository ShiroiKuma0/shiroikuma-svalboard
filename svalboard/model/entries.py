# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 白い熊
"""Edit buffers for the things that are lists of slots rather than a keymap.

Tap dances, combos and key overrides are fixed-length arrays of independent entries, so
one buffer serves all three. Macros need their own, because they are not independent:
they share a byte buffer, so any change rewrites all of them and the interesting
question is whether the whole set still fits.

Both follow the keymap buffer's shape — a baseline of what the hardware holds beside a
working copy, undo and redo, and a pending list — so the interface treats every kind of
change the same way.
"""

from __future__ import annotations

import copy
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Generic, TypeVar

from ..protocol.macros import Macro, serialize_buffer

Entry = TypeVar("Entry")


@dataclass(frozen=True)
class EntryEdit(Generic[Entry]):
    index: int
    before: Entry
    after: Entry


class EntryChanges(Generic[Entry]):
    """A fixed-length list of independent entries, with undo."""

    def __init__(self, *, empty: Callable[[], Entry]) -> None:
        self._empty = empty
        self._baseline: list[Entry] = []
        self._working: list[Entry] = []
        self._undo: list[EntryEdit[Entry]] = []
        self._redo: list[EntryEdit[Entry]] = []
        self._listeners: list[Callable[[], None]] = []

    # -- observation -------------------------------------------------------------

    def subscribe(self, listener: Callable[[], None]) -> None:
        self._listeners.append(listener)

    def _notify(self) -> None:
        for listener in self._listeners:
            listener()

    # -- loading -----------------------------------------------------------------

    def load(self, entries: Iterable[Entry]) -> None:
        self._baseline = list(entries)
        self._working = list(self._baseline)
        self._undo.clear()
        self._redo.clear()
        self._notify()

    def __len__(self) -> int:
        return len(self._working)

    def __getitem__(self, index: int) -> Entry:
        return self._working[index]

    @property
    def working(self) -> list[Entry]:
        return list(self._working)

    def baseline(self, index: int) -> Entry:
        return self._baseline[index]

    def is_changed(self, index: int) -> bool:
        return self._working[index] != self._baseline[index]

    @property
    def is_dirty(self) -> bool:
        return self._working != self._baseline

    def changed_indices(self) -> list[int]:
        return [
            index
            for index, (working, baseline) in enumerate(
                zip(self._working, self._baseline, strict=True)
            )
            if working != baseline
        ]

    def first_empty(self, is_empty: Callable[[Entry], bool]) -> int | None:
        """The lowest unused slot, for "assign and edit" to claim.

        The working copy is searched, not the baseline, so two of these in a row do
        not both land on the same slot.
        """
        for index, entry in enumerate(self._working):
            if is_empty(entry):
                return index
        return None

    # -- editing -----------------------------------------------------------------

    def set(self, index: int, entry: Entry) -> EntryEdit[Entry] | None:
        before = self._working[index]
        if before == entry:
            return None
        edit = EntryEdit(index=index, before=before, after=entry)
        self._working[index] = entry
        self._undo.append(edit)
        self._redo.clear()
        self._notify()
        return edit

    def clear(self, index: int) -> EntryEdit[Entry] | None:
        return self.set(index, self._empty())

    def revert(self, index: int) -> EntryEdit[Entry] | None:
        return self.set(index, self._baseline[index])

    def revert_all(self) -> None:
        if not self.is_dirty:
            return
        self._working = list(self._baseline)
        self._undo.clear()
        self._redo.clear()
        self._notify()

    # -- undo and redo -----------------------------------------------------------

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    def undo(self) -> EntryEdit[Entry] | None:
        if not self._undo:
            return None
        edit = self._undo.pop()
        self._working[edit.index] = edit.before
        self._redo.append(edit)
        self._notify()
        return edit

    def redo(self) -> EntryEdit[Entry] | None:
        if not self._redo:
            return None
        edit = self._redo.pop()
        self._working[edit.index] = edit.after
        self._undo.append(edit)
        self._notify()
        return edit

    # -- committing --------------------------------------------------------------

    def pending(self) -> list[tuple[int, Entry]]:
        return [(index, self._working[index]) for index in self.changed_indices()]

    def mark_written(self, indices: Iterable[int] | None = None) -> None:
        if indices is None:
            self._baseline = list(self._working)
        else:
            for index in indices:
                self._baseline[index] = self._working[index]
        self._undo.clear()
        self._redo.clear()
        self._notify()


class MacroChanges:
    """The macro set, which is one shared buffer rather than independent slots."""

    def __init__(self, *, size: int = 0) -> None:
        self.size = size
        self._baseline: list[Macro] = []
        self._working: list[Macro] = []
        self._undo: list[tuple[int, Macro, Macro]] = []
        self._redo: list[tuple[int, Macro, Macro]] = []
        self._listeners: list[Callable[[], None]] = []

    def subscribe(self, listener: Callable[[], None]) -> None:
        self._listeners.append(listener)

    def _notify(self) -> None:
        for listener in self._listeners:
            listener()

    def load(self, macros: Iterable[Macro], *, size: int) -> None:
        self.size = size
        self._baseline = [copy.deepcopy(macro) for macro in macros]
        self._working = [copy.deepcopy(macro) for macro in self._baseline]
        self._undo.clear()
        self._redo.clear()
        self._notify()

    def __len__(self) -> int:
        return len(self._working)

    def __getitem__(self, index: int) -> Macro:
        return self._working[index]

    @property
    def working(self) -> list[Macro]:
        return self._working

    def is_changed(self, index: int) -> bool:
        return self._working[index] != self._baseline[index]

    @property
    def is_dirty(self) -> bool:
        return self._working != self._baseline

    def first_empty(self) -> int | None:
        for index, macro in enumerate(self._working):
            if macro.is_empty:
                return index
        return None

    def set(self, index: int, macro: Macro) -> None:
        before = self._working[index]
        if before == macro:
            return
        self._undo.append((index, copy.deepcopy(before), copy.deepcopy(macro)))
        self._redo.clear()
        self._working[index] = copy.deepcopy(macro)
        self._notify()

    def clear(self, index: int) -> None:
        self.set(index, Macro([]))

    def revert(self, index: int) -> None:
        self.set(index, copy.deepcopy(self._baseline[index]))

    def revert_all(self) -> None:
        if not self.is_dirty:
            return
        self._working = [copy.deepcopy(macro) for macro in self._baseline]
        self._undo.clear()
        self._redo.clear()
        self._notify()

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    def undo(self) -> int | None:
        if not self._undo:
            return None
        index, before, after = self._undo.pop()
        self._working[index] = copy.deepcopy(before)
        self._redo.append((index, before, after))
        self._notify()
        return index

    def redo(self) -> int | None:
        if not self._redo:
            return None
        index, before, after = self._redo.pop()
        self._working[index] = copy.deepcopy(after)
        self._undo.append((index, before, after))
        self._notify()
        return index

    def mark_written(self) -> None:
        self._baseline = [copy.deepcopy(macro) for macro in self._working]
        self._undo.clear()
        self._redo.clear()
        self._notify()

    # -- capacity ----------------------------------------------------------------

    def bytes_used(self) -> int:
        """How much of the shared buffer the working set needs, padding included."""
        try:
            rendered = serialize_buffer(self._working, self.size)
        except ValueError:
            # Over capacity: report the true requirement so the interface can say
            # by how much rather than merely that it does not fit.
            return sum(len(_render(macro)) + 1 for macro in self._working)
        return len(rendered.rstrip(b"\x00")) + 1 if any(
            not macro.is_empty for macro in self._working
        ) else 0

    def fits(self) -> bool:
        try:
            serialize_buffer(self._working, self.size)
        except ValueError:
            return False
        return True


def _render(macro: Macro) -> bytes:
    from ..protocol.macros import serialize_macro

    return serialize_macro(macro)


class SettingsChanges:
    """QMK settings, keyed by QSID rather than by field.

    Several booleans share one QSID, so the unit of change is the QSID: setting one
    bit rewrites the whole value. Keeping the buffer keyed that way means the pending
    list is exactly the set of writes to perform.
    """

    def __init__(self) -> None:
        self._baseline: dict[int, int] = {}
        self._working: dict[int, int] = {}
        self._undo: list[tuple[int, int, int]] = []
        self._redo: list[tuple[int, int, int]] = []
        self._listeners: list[Callable[[], None]] = []
        self.supported: set[int] = set()

    def subscribe(self, listener: Callable[[], None]) -> None:
        self._listeners.append(listener)

    def _notify(self) -> None:
        for listener in self._listeners:
            listener()

    def load(self, values: dict[int, int], supported: set[int]) -> None:
        self._baseline = dict(values)
        self._working = dict(values)
        self.supported = set(supported)
        self._undo.clear()
        self._redo.clear()
        self._notify()

    def __len__(self) -> int:
        return len(self._working)

    def get(self, qsid: int) -> int:
        return self._working.get(qsid, 0)

    def is_changed(self, qsid: int) -> bool:
        return self._working.get(qsid) != self._baseline.get(qsid)

    @property
    def is_dirty(self) -> bool:
        return self._working != self._baseline

    def set(self, qsid: int, value: int) -> None:
        before = self._working.get(qsid, 0)
        if before == value:
            return
        self._undo.append((qsid, before, value))
        self._redo.clear()
        self._working[qsid] = value
        self._notify()

    def pending(self) -> list[tuple[int, int]]:
        return [
            (qsid, value)
            for qsid, value in sorted(self._working.items())
            if self._baseline.get(qsid) != value
        ]

    def revert_all(self) -> None:
        if not self.is_dirty:
            return
        self._working = dict(self._baseline)
        self._undo.clear()
        self._redo.clear()
        self._notify()

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    def undo(self):
        if not self._undo:
            return None
        qsid, before, after = self._undo.pop()
        self._working[qsid] = before
        self._redo.append((qsid, before, after))
        self._notify()
        return qsid

    def redo(self):
        if not self._redo:
            return None
        qsid, before, after = self._redo.pop()
        self._working[qsid] = after
        self._undo.append((qsid, before, after))
        self._notify()
        return qsid

    def mark_written(self, qsids=None) -> None:
        if qsids is None:
            self._baseline = dict(self._working)
        else:
            for qsid in qsids:
                self._baseline[qsid] = self._working[qsid]
        self._undo.clear()
        self._redo.clear()
        self._notify()

# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 白い熊
"""Notes on macros: what each one is for, kept on this computer.

The keyboard stores a macro's actions and nothing else, so a macro that types U+201C
shows up as "201c" at best. A note says what it does — “ — in words the owner chose.
Notes are not on the wire and never mark anything unwritten: they persist the moment
they are typed, per keyboard, under that keyboard's Vial ID, so two boards keep two
sets. They also travel in backups and exports, beside the macros they describe.
"""

from __future__ import annotations

from PyQt6.QtCore import QSettings

GROUP = "macro-notes"


class MacroNotes:
    """The notes for one keyboard, indexed by macro number."""

    def __init__(self, settings: QSettings, keyboard_id: int) -> None:
        self._settings = settings
        self._group = f"{GROUP}/{keyboard_id:016X}"
        self._notes: dict[int, str] = {}
        settings.beginGroup(self._group)
        for key in settings.childKeys():
            if key.isdigit():
                text = str(settings.value(key) or "")
                if text:
                    self._notes[int(key)] = text
        settings.endGroup()

    def get(self, index: int) -> str:
        return self._notes.get(index, "")

    def set(self, index: int, text: str) -> None:
        if text == self.get(index):
            return
        if text:
            self._notes[index] = text
            self._settings.setValue(f"{self._group}/{index}", text)
        else:
            self._notes.pop(index, None)
            self._settings.remove(f"{self._group}/{index}")

    def all(self) -> dict[int, str]:
        return dict(sorted(self._notes.items()))

    def update(self, notes: dict[int, str]) -> int:
        for index, text in notes.items():
            self.set(index, text)
        return len(notes)


def headline(note: str) -> str:
    """The note's first non-empty line, for the macro list."""
    return next((line.strip() for line in note.splitlines() if line.strip()), "")

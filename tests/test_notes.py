# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 白い熊
"""Macro notes: per keyboard, persisted as typed."""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QSettings

from svalboard.model.notes import MacroNotes, headline


def _settings(tmp_path: Path) -> QSettings:
    return QSettings(str(tmp_path / "notes.ini"), QSettings.Format.IniFormat)


def test_notes_persist_per_keyboard(tmp_path: Path) -> None:
    notes = MacroNotes(_settings(tmp_path), 0x4829F621F27D181B)
    notes.set(0, "“")
    notes.set(1, "”")
    notes.set(1, "")
    assert MacroNotes(_settings(tmp_path), 0x4829F621F27D181B).all() == {0: "“"}
    assert MacroNotes(_settings(tmp_path), 7).all() == {}


def test_headline_is_the_first_non_empty_line() -> None:
    assert headline("\n  “ left quote \nmore") == "“ left quote"
    assert headline("") == ""

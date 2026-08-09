# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 白い熊
"""Keyboard backups: writing, reading, and refusing what cannot be read."""

from __future__ import annotations

import json

import pytest

from svalboard.model.files import (
    Backup,
    FileFormatError,
    build_backup,
    check_fits,
    load,
    save_kbi,
    to_kbi,
)
from svalboard.protocol.keycodes import KeycodeSet

ROWS, COLS, LAYERS = 10, 6, 4
PER_LAYER = ROWS * COLS


@pytest.fixture
def keycodes() -> KeycodeSet:
    return KeycodeSet(layers=16, macros=50, tap_dances=50)


@pytest.fixture
def backup(keycodes: KeycodeSet) -> Backup:
    codes = [0x0000] * (PER_LAYER * LAYERS)
    codes[0] = keycodes.parse("KC_A")
    codes[1] = keycodes.parse("LCTL_T(KC_ENTER)")
    codes[PER_LAYER] = keycodes.parse("TO(3)")
    return build_backup(
        keyboard_id=0x4829F621F27D181B,
        layers=LAYERS,
        rows=ROWS,
        cols=COLS,
        codes=codes,
        keycodes=keycodes,
        layer_names={0: "base", 3: "settings"},
    )


def test_keymap_is_stored_as_names(backup: Backup) -> None:
    """Names rather than numbers, so a backup survives renumbered firmware."""
    assert backup.keymap[0][0] == "KC_A"
    assert backup.keymap[0][1] == "LCTL_T(KC_ENTER)"
    assert backup.keymap[1][0] == "TO(3)"


def test_keyboard_id_is_written_as_a_string(backup: Backup) -> None:
    """A 64-bit identifier loses digits as a JSON number."""
    payload = to_kbi(backup)
    assert payload["kbid"] == str(0x4829F621F27D181B)
    assert isinstance(payload["kbid"], str)


def test_layer_names_land_in_cosmetic(backup: Backup) -> None:
    payload = to_kbi(backup)
    assert payload["cosmetic"]["layer"] == {"0": "base", "3": "settings"}


def test_round_trip_through_a_file(tmp_path, backup: Backup, keycodes: KeycodeSet) -> None:
    path = tmp_path / "board.kbi"
    save_kbi(path, backup)
    loaded = load(path)

    assert loaded.keyboard_id == backup.keyboard_id
    assert loaded.keymap == backup.keymap
    assert loaded.layer_names == backup.layer_names
    assert loaded.codes(keycodes)[:2] == [
        keycodes.parse("KC_A"),
        keycodes.parse("LCTL_T(KC_ENTER)"),
    ]


def test_unmodelled_sections_survive_a_round_trip(tmp_path, keycodes: KeycodeSet) -> None:
    """Macros and the rest arrive later; re-saving must not discard them."""
    original = {
        "kbid": "12345",
        "layers": 1,
        "rows": 1,
        "cols": 2,
        "keymap": [["KC_A", "KC_B"]],
        "macros": [{"mid": 0, "actions": [["text", "hello"]]}],
        "combos": [["KC_A", "KC_B", "KC_NO", "KC_NO", "KC_C"]],
        "settings": {"7": 200},
    }
    path = tmp_path / "full.kbi"
    path.write_text(json.dumps(original), encoding="utf-8")

    loaded = load(path)
    again = tmp_path / "again.kbi"
    save_kbi(again, loaded)
    rewritten = json.loads(again.read_text(encoding="utf-8"))

    assert rewritten["macros"] == original["macros"]
    assert rewritten["combos"] == original["combos"]
    assert rewritten["settings"] == original["settings"]


def test_format_is_chosen_by_content_not_extension(tmp_path) -> None:
    path = tmp_path / "misnamed.json"
    path.write_text(
        json.dumps({"kbid": "1", "layers": 1, "rows": 1, "cols": 1, "keymap": [["KC_A"]]}),
        encoding="utf-8",
    )
    assert load(path).keyboard_id == 1


def test_a_vil_file_is_refused_with_an_explanation(tmp_path) -> None:
    path = tmp_path / "layout.vil"
    path.write_text(json.dumps({"uid": 1, "layout": []}), encoding="utf-8")
    with pytest.raises(FileFormatError, match="Vial .vil"):
        load(path)


def test_something_else_entirely_is_refused(tmp_path) -> None:
    path = tmp_path / "notes.json"
    path.write_text(json.dumps({"hello": "world"}), encoding="utf-8")
    with pytest.raises(FileFormatError, match="neither kbid nor uid"):
        load(path)


def test_a_broken_keymap_shape_is_refused(tmp_path) -> None:
    path = tmp_path / "wrong.kbi"
    path.write_text(
        json.dumps({"kbid": "1", "rows": 10, "cols": 6, "keymap": [["KC_A"]]}),
        encoding="utf-8",
    )
    with pytest.raises(FileFormatError, match="stores 1 positions"):
        load(path)


def test_unknown_keycode_names_do_not_abort_a_restore(keycodes: KeycodeSet) -> None:
    backup = Backup(layers=1, rows=1, cols=2, keymap=[["KC_A", "KC_NONSENSE"]])
    assert backup.codes(keycodes) == [keycodes.parse("KC_A"), 0x0000]


def test_fit_warnings_are_advice_not_refusal() -> None:
    backup = Backup(layers=8, rows=5, cols=4)
    warnings = check_fits(backup, layers=16, rows=10, cols=6)
    assert any("5×4" in warning for warning in warnings)
    assert any("only 8" in warning for warning in warnings)
    assert check_fits(Backup(layers=16, rows=10, cols=6), layers=16, rows=10, cols=6) == []

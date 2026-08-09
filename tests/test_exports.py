# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 白い熊
"""Vial's .vil, and the QMK keymap header."""

from __future__ import annotations

import json

import pytest

from svalboard.model.exports import from_vil, to_keymap_header, to_vil
from svalboard.protocol.keycodes import KeycodeSet

ROWS, COLS, LAYERS = 10, 6, 2
KEYBOARD_ID = 0x4829F621F27D181B


@pytest.fixture
def keycodes() -> KeycodeSet:
    return KeycodeSet(layers=16, macros=50, tap_dances=50)


@pytest.fixture
def codes(keycodes: KeycodeSet) -> list[int]:
    flat = [0] * (ROWS * COLS * LAYERS)
    flat[0] = keycodes.parse("KC_A")
    flat[3] = keycodes.parse("LCTL_T(KC_ENTER)")
    flat[ROWS * COLS] = keycodes.parse("TO(1)")
    return flat


def render(keycodes, codes) -> dict:
    return json.loads(
        to_vil(
            keyboard_id=KEYBOARD_ID, layers=LAYERS, rows=ROWS, cols=COLS,
            codes=codes, keycodes=keycodes,
        )
    )


def test_vil_nests_the_layout_by_row(keycodes, codes) -> None:
    """Vial stores [layer][row][col]; .kbi stores one flat list per layer."""
    document = render(keycodes, codes)
    assert len(document["layout"]) == LAYERS
    assert len(document["layout"][0]) == ROWS
    assert len(document["layout"][0][0]) == COLS
    assert document["layout"][0][0][0] == "KC_A"
    assert document["layout"][0][0][3] == "LCTL_T(KC_ENTER)"
    assert document["layout"][1][0][0] == "TO(1)"


def test_the_uid_survives_as_a_number(keycodes, codes) -> None:
    """A 64-bit identifier written as a JSON number loses its last digits."""
    document = render(keycodes, codes)
    assert document["uid"] == KEYBOARD_ID
    assert isinstance(document["uid"], int)


def test_vil_declares_the_protocols_vial_expects(keycodes, codes) -> None:
    document = render(keycodes, codes)
    assert document["version"] == 1
    assert document["via_protocol"] == 9
    assert document["vial_protocol"] == 6
    assert len(document["encoder_layout"]) == LAYERS


def test_vil_round_trips_through_from_vil(keycodes, codes) -> None:
    document = render(keycodes, codes)
    fields = from_vil(document, rows=ROWS, cols=COLS)
    assert fields["keyboard_id"] == KEYBOARD_ID
    assert fields["layers"] == LAYERS
    assert fields["keymap"][0][0] == "KC_A"
    assert fields["keymap"][0][3] == "LCTL_T(KC_ENTER)"
    assert fields["keymap"][1][0] == "TO(1)"
    assert len(fields["keymap"][0]) == ROWS * COLS


def test_a_short_vil_row_is_padded_rather_than_shifting_everything(keycodes) -> None:
    """A ragged file must not slide every later key one position along."""
    fields = from_vil({"uid": 1, "layout": [[["KC_A"]]]}, rows=ROWS, cols=COLS)
    assert fields["keymap"][0][0] == "KC_A"
    assert fields["keymap"][0][1] == "KC_NO"
    assert len(fields["keymap"][0]) == ROWS * COLS


def test_the_header_is_plausible_c(keycodes, codes) -> None:
    header = to_keymap_header(
        layers=LAYERS, rows=ROWS, cols=COLS, codes=codes, keycodes=keycodes
    )
    assert "const uint16_t PROGMEM keymaps[][MATRIX_ROWS][MATRIX_COLS]" in header
    assert "[0] = LAYOUT(" in header
    assert "[1] = LAYOUT(" in header
    assert header.count("LAYOUT(") == LAYERS
    assert "KC_A" in header
    assert header.rstrip().endswith(".")  # the trailing column-order note


def test_the_header_names_the_clusters(keycodes, codes) -> None:
    """A matrix dump is unreadable; the Svalboard's own names are not."""
    header = to_keymap_header(
        layers=LAYERS, rows=ROWS, cols=COLS, codes=codes, keycodes=keycodes
    )
    assert "// left thumb" in header
    assert "// right thumb" in header
    assert "centre" in header


def test_an_empty_layer_says_so(keycodes) -> None:
    header = to_keymap_header(
        layers=1, rows=ROWS, cols=COLS, codes=[0] * (ROWS * COLS), keycodes=keycodes
    )
    assert "layer 0 is empty" in header

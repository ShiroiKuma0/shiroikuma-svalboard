# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 白い熊
"""Keycode naming and parsing.

The expected values here were read off 白い熊's Svalboard, so they are what the
firmware actually stores rather than what it ought to.
"""

from __future__ import annotations

import pytest

from svalboard.protocol.keycodes import (
    KIND_BASIC,
    KIND_CUSTOM,
    KIND_LAYER,
    KIND_MACRO,
    KIND_MASKED,
    KIND_TAP_DANCE,
    KIND_UNSET,
    UNSET,
    KeycodeSet,
)

#: A slice of the Svalboard's own definition, enough to name the SV_* keys.
SVALBOARD_CUSTOM = [
    {"name": "SV_LEFT_DPI_INC", "shortName": "Left\nDPI +", "title": "Increase left DPI"},
    {"name": "SV_LEFT_DPI_DEC", "shortName": "Left\nDPI -", "title": "Decrease left DPI"},
    {"name": "SV_RIGHT_DPI_INC", "shortName": "Right\nDPI +", "title": "Increase right DPI"},
    {"name": "SV_RIGHT_DPI_DEC", "shortName": "Right\nDPI -", "title": "Decrease right DPI"},
]


@pytest.fixture
def keycodes() -> KeycodeSet:
    return KeycodeSet(
        layers=16, macros=50, tap_dances=50, custom_keycodes=SVALBOARD_CUSTOM
    )


@pytest.mark.parametrize(
    ("code", "name"),
    [
        (0x0000, "KC_NO"),
        (0x0004, "KC_A"),
        (0x0028, "KC_ENTER"),
        (0x00E1, "KC_LSHIFT"),
        (0x2128, "LCTL_T(KC_ENTER)"),  # left thumb north, layer 0
        (0x2429, "LALT_T(KC_ESCAPE)"),  # left thumb west, layer 0
        (0x4128, "LT1(KC_ENTER)"),  # right thumb west, layer 0
        (0x5203, "TO(3)"),  # left thumb super-south, layer 0
        (0x7700, "M0"),
        (0x7703, "M3"),
        (0x7E00, "SV_LEFT_DPI_INC"),
        (0x7E03, "SV_RIGHT_DPI_DEC"),
    ],
)
def test_names_match_the_hardware(keycodes: KeycodeSet, code: int, name: str) -> None:
    assert keycodes.name(code) == name


@pytest.mark.parametrize(
    ("code", "kind"),
    [
        (0x0004, KIND_BASIC),
        (0x0104, KIND_MASKED),
        (0x2128, KIND_MASKED),
        (0x5203, KIND_LAYER),
        (0x7703, KIND_MACRO),
        (0x5700, KIND_TAP_DANCE),
        (0x7E00, KIND_CUSTOM),
        (UNSET, KIND_UNSET),
    ],
)
def test_kinds(keycodes: KeycodeSet, code: int, kind: str) -> None:
    assert keycodes.kind(code) == kind


def test_every_named_code_round_trips(keycodes: KeycodeSet) -> None:
    """Naming a code and parsing the name back must return the same code.

    This is the property that matters: a break here writes the wrong key to the
    keyboard, silently.
    """
    for code in keycodes.iter_codes():
        assert keycodes.parse(keycodes.name(code)) == code, hex(code)


def test_masked_composition_is_symmetric(keycodes: KeycodeSet) -> None:
    assert keycodes.parse("LCTL(KC_A)") == 0x0104
    assert keycodes.name(0x0104) == "LCTL(KC_A)"
    assert keycodes.parse("LSFT(KC_1)") == 0x021E


def test_aliases_resolve(keycodes: KeycodeSet) -> None:
    assert keycodes.parse("KC_BSPC") == keycodes.parse("KC_BSPACE")
    assert keycodes.parse("KC_ESC") == keycodes.parse("KC_ESCAPE")


def test_positional_custom_spelling_still_works(keycodes: KeycodeSet) -> None:
    """A file written against USER00 must load on a board that renames it."""
    assert keycodes.parse("USER00") == keycodes.parse("SV_LEFT_DPI_INC")


def test_hex_and_decimal(keycodes: KeycodeSet) -> None:
    assert keycodes.parse("0x0104") == 0x0104
    assert keycodes.parse("260") == 0x0104
    with pytest.raises(ValueError):
        keycodes.parse("not a key")


def test_unset_is_not_reported_as_broken(keycodes: KeycodeSet) -> None:
    """0xFFFF is erased flash, not a corrupt keycode."""
    info = keycodes.info(UNSET)
    assert info.is_unset
    assert "Never set" in info.tooltip


def test_search_finds_by_name_label_and_description(keycodes: KeycodeSet) -> None:
    names = {info.name for info in keycodes.search("escape")}
    assert "KC_ESCAPE" in names

    assert keycodes.search("KC_A")[0].name == "KC_A"
    assert {info.name for info in keycodes.search("dpi")} >= {"SV_LEFT_DPI_INC"}
    assert keycodes.search("") == []


def test_custom_keycodes_carry_their_own_labels(keycodes: KeycodeSet) -> None:
    info = keycodes.info(0x7E00)
    assert info.name == "SV_LEFT_DPI_INC"
    assert info.label == "Left\nDPI +"
    assert info.tooltip == "Increase left DPI"

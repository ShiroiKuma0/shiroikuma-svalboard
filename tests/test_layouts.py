# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 白い熊
"""Reading the computer's installed keyboard layouts.

These read the real xkb data on the machine, so they skip rather than fail where it
is absent — a build machine need not have X11 data installed for the rest to be
meaningful.
"""

from __future__ import annotations

import pytest

from svalboard.protocol.keycodes import KeycodeSet
from svalboard.protocol.layouts import (
    KEY_POSITIONS,
    available,
    differs_from_us,
    keysym_to_character,
    load,
)

pytestmark = pytest.mark.skipif(
    not available(), reason="no xkb layout data installed"
)


def test_keysyms_resolve_to_characters() -> None:
    assert keysym_to_character("ccaron") == "č"
    assert keysym_to_character("uring") == "ů"
    assert keysym_to_character("adiaeresis") == "ä"
    assert keysym_to_character("y") == "y"


def test_dead_keys_and_nonsense_yield_nothing() -> None:
    """There is no character to show for a dead key, and none should be invented."""
    assert keysym_to_character("dead_tilde") == ""
    assert keysym_to_character("NoSymbol") == ""
    assert keysym_to_character("") == ""


def test_the_positions_cover_a_full_alphanumeric_block() -> None:
    assert KEY_POSITIONS["AD01"] == "KC_Q"
    assert KEY_POSITIONS["AC01"] == "KC_A"
    assert KEY_POSITIONS["AB01"] == "KC_Z"
    assert len(KEY_POSITIONS) >= 47


def test_us_is_the_baseline() -> None:
    american = load("us")
    assert american is not None
    assert american.glyphs["KC_Y"] == ("y", "Y")
    assert differs_from_us(american) == {}


def test_czech_is_qwertz_with_its_own_diacritics() -> None:
    czech = load("cz")
    assert czech is not None
    # The defining feature: Y and Z are swapped relative to US.
    assert czech.glyphs["KC_Y"][0] == "z"
    assert czech.glyphs["KC_Z"][0] == "y"
    assert czech.glyphs["KC_SCOLON"][0] == "ů"
    assert czech.glyphs["KC_LBRACKET"][0] == "ú"
    assert 10 < len(differs_from_us(czech)) < 40


def test_french_is_azerty() -> None:
    french = load("fr")
    assert french is not None
    assert french.glyphs["KC_Q"][0] == "a"
    assert french.glyphs["KC_A"][0] == "q"


def test_an_unknown_layout_is_none_rather_than_an_error() -> None:
    assert load("not-a-layout") is None


def test_relabelling_moves_labels_but_not_keycodes() -> None:
    """The keycode is a position; only what it is called changes."""
    keycodes = KeycodeSet(layers=16)
    czech = load("cz")
    assert czech is not None

    assert keycodes.info(keycodes.parse("KC_Y")).label == "Y"
    keycodes.apply_layout(czech.glyphs)

    assert keycodes.info(keycodes.parse("KC_Y")).label == "z"
    assert keycodes.parse("KC_Y") == 0x001C
    assert keycodes.name(0x001C) == "KC_Y"
    assert keycodes.search("KC_Y")[0].name == "KC_Y"


def test_relabelling_can_be_undone() -> None:
    keycodes = KeycodeSet(layers=16)
    czech = load("cz")
    keycodes.apply_layout(czech.glyphs)
    keycodes.apply_layout(None)
    assert keycodes.info(keycodes.parse("KC_Y")).label == "Y"
    assert keycodes.layout_glyphs == {}

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
    KIND_TEMPLATE,
    KIND_UNSET,
    MODIFIER_RIGHT,
    UNSET,
    KeycodeSet,
    modifiable,
    modifier_mask,
    with_modifiers,
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


# -- composed keycodes -----------------------------------------------------------


def test_layer_taps_are_offered_one_per_layer(keycodes: KeycodeSet) -> None:
    """LT is a template, not a keycode: it needs the key it types when tapped."""
    templates = keycodes.layer_taps()
    assert [info.name for info in templates] == [f"LT{n}(kc)" for n in range(16)]
    assert {info.kind for info in templates} == {KIND_TEMPLATE}
    assert "layer 2" in templates[2].tooltip


def test_layer_taps_stop_at_sixteen() -> None:
    """The keycode has four bits for the layer however many the board has."""
    assert len(KeycodeSet(layers=32).layer_taps()) == 16


def test_modifier_tab_offers_its_templates(keycodes: KeycodeSet) -> None:
    """LGUI(kc) used to be filtered out of the tab, unreachable except by typing."""
    names = {info.name for info in keycodes.category("modifiers")}
    assert {"LGUI(kc)", "LCTL_T(kc)", "HYPR(kc)"} <= names


def test_composing_fills_the_hole(keycodes: KeycodeSet) -> None:
    outer = keycodes.parse("LT2(kc)")
    assert keycodes.compose(outer, keycodes.parse("KC_SPACE")) == 0x422C
    assert keycodes.name(0x422C) == "LT2(KC_SPACE)"

    assert keycodes.compose(keycodes.parse("LGUI(kc)"), 0x1E) == 0x081E
    assert keycodes.name(0x081E) == "LGUI(KC_1)"


def test_only_a_basic_keycode_fits_inside_a_template(keycodes: KeycodeSet) -> None:
    assert keycodes.composable(keycodes.parse("KC_SPACE"))
    assert not keycodes.composable(keycodes.parse("MO(2)"))
    assert not keycodes.composable(keycodes.parse("M0"))


# -- editing the modifiers on an existing key ------------------------------------


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        (0x001E, True),   # KC_1
        (0x081E, True),   # LGUI(KC_1) — already modified
        (0x2200, True),   # LSFT_T(KC_NO) — a mod-tap wears the same bits
        (0x422C, False),  # LT2(KC_SPACE) — those bits are the layer
        (0x5222, False),  # MO(2)
        (0x7700, False),  # M0
    ],
)
def test_which_keys_can_take_modifiers(code: int, expected: bool) -> None:
    assert modifiable(code) is expected


def test_adding_and_removing_modifiers(keycodes: KeycodeSet) -> None:
    """Super+1 without knowing it is spelled LGUI(KC_1)."""
    code = with_modifiers(0x001E, 0x0800)
    assert keycodes.name(code) == "LGUI(KC_1)"
    assert modifier_mask(code) == 0x0800

    both = with_modifiers(code, 0x0800 | MODIFIER_RIGHT)
    assert keycodes.name(both) == "RGUI(KC_1)"

    assert with_modifiers(both, 0) == 0x001E


def test_unnameable_modifier_combinations_still_read_correctly(
    keycodes: KeycodeSet,
) -> None:
    """Vial names 18 of the 30 combinations; the rest are not broken keycodes."""
    code = with_modifiers(0x001E, 0x1700)  # right Ctrl+Shift+Alt
    info = keycodes.info(code)
    assert info.name == "0x171E"
    assert info.kind == KIND_MASKED
    assert info.label == keycodes.info(0x001E).label
    assert "RCtl+RSft+RAlt" in info.tooltip
    # And it survives a round trip through a file, which stores the name.
    assert keycodes.parse(info.name) == code

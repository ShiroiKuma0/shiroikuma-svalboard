# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 白い熊
"""The macro buffer, and the dynamic entries.

The macro cases use bytes read off 白い熊's Svalboard, which encode the Linux
Ctrl+Shift+U sequence for “ ” — and –.
"""

from __future__ import annotations

import pytest

from svalboard.protocol.dynamic import (
    OPTION_ENABLED,
    Combo,
    KeyOverride,
    TapDance,
    describe_mods,
)
from svalboard.protocol.macros import (
    MAX_DELAY,
    Action,
    Macro,
    decode_delay,
    decode_keycode,
    deserialize_buffer,
    deserialize_macro,
    encode_delay,
    serialize_buffer,
    serialize_macro,
)

#: M0 from the hardware: Ctrl+Shift+U, "201c", Enter — a left double quotation mark.
REAL_MACRO = bytes(
    [
        0x01, 0x02, 0xE0,        # down LCtrl
        0x01, 0x02, 0xE1,        # down LShift
        0x01, 0x01, 0x18,        # tap U
        0x01, 0x03, 0xE1,        # up LShift
        0x01, 0x03, 0xE0,        # up LCtrl
        0x32, 0x30, 0x31, 0x63,  # "201c"
        0x01, 0x01, 0x28,        # tap Enter
    ]
)


# -- macros ----------------------------------------------------------------------


def test_a_real_macro_decodes() -> None:
    macro = deserialize_macro(REAL_MACRO)
    kinds = [action.kind for action in macro.actions]
    assert kinds == ["down", "down", "tap", "up", "up", "text", "tap"]
    assert macro.actions[5].text == "201c"
    assert macro.actions[2].keycode == 0x18  # KC_U


def test_a_real_macro_re_encodes_byte_for_byte() -> None:
    """Symmetry is the property that matters: a rewrite must not corrupt the buffer."""
    assert serialize_macro(deserialize_macro(REAL_MACRO)) == REAL_MACRO


def test_text_runs_are_merged() -> None:
    macro = deserialize_macro(b"hello")
    assert len(macro.actions) == 1
    assert macro.actions[0].text == "hello"


def test_delay_is_biased_by_one_in_each_byte() -> None:
    """A zero byte would end the macro, so neither half may be zero."""
    low, high = encode_delay(100)
    assert (low, high) == (101, 1)
    assert decode_delay(low, high) == 100

    for milliseconds in (1, 254, 255, 256, 1000, MAX_DELAY):
        low, high = encode_delay(milliseconds)
        assert low > 0 and high > 0
        assert decode_delay(low, high) == milliseconds


def test_a_zero_delay_cannot_be_represented_and_becomes_one() -> None:
    assert decode_delay(*encode_delay(0)) == 1


def test_delay_round_trips_through_the_buffer() -> None:
    macro = Macro([Action("delay", delay=250)])
    assert deserialize_macro(serialize_macro(macro)).actions[0].delay == 250


def test_two_byte_keycodes_use_the_extended_actions() -> None:
    macro = Macro([Action("tap", keycode=0x0104)])
    encoded = serialize_macro(macro)
    assert encoded[1] == 0x05  # EXT_TAP
    assert deserialize_macro(encoded).actions[0].keycode == 0x0104


def test_qmk_folds_a_keycode_that_lost_its_low_byte() -> None:
    assert decode_keycode(0xFF12) == 0x1200
    assert decode_keycode(0x0104) == 0x0104


def test_zero_bytes_are_stripped_from_text() -> None:
    """A zero would terminate the macro, taking everything after it."""
    encoded = serialize_macro(Macro([Action("text", text="a\x00b")]))
    assert b"\x00" not in encoded


def test_the_buffer_splits_into_the_declared_number_of_macros() -> None:
    buffer = REAL_MACRO + b"\x00" + b"hi" + b"\x00"
    macros = deserialize_buffer(buffer, 4)
    assert len(macros) == 4
    assert macros[1].actions[0].text == "hi"
    assert macros[2].is_empty and macros[3].is_empty


def test_the_whole_buffer_round_trips() -> None:
    macros = deserialize_buffer(REAL_MACRO + b"\x00", 8)
    rendered = serialize_buffer(macros, 256)
    assert len(rendered) == 256
    assert deserialize_buffer(rendered, 8)[0].actions == macros[0].actions


def test_macros_that_no_longer_fit_are_refused_not_truncated() -> None:
    macros = [Macro([Action("text", text="x" * 40)]) for _ in range(4)]
    with pytest.raises(ValueError, match="room for"):
        serialize_buffer(macros, 32)


def test_a_malformed_action_does_not_discard_the_rest() -> None:
    macro = deserialize_macro(bytes([0x01, 0x7F, 0x01, 0x01, 0x04]))
    assert any(action.kind == "tap" for action in macro.actions)


def test_text_preview_prefers_typed_text() -> None:
    assert Macro([Action("text", text=" hi ")]).text_preview() == "hi"
    assert Macro([Action("tap", keycode=4)]).text_preview() == ""


# -- dynamic entries -------------------------------------------------------------


def test_tap_dance_round_trips() -> None:
    entry = TapDance(on_tap=0x0004, on_hold=0x00E0, on_double_tap=0x0005,
                     on_tap_hold=0x0006, tapping_term=200)
    assert TapDance.unpack(entry.pack()) == entry
    assert len(entry.pack()) == 10


def test_an_empty_tap_dance_is_recognised() -> None:
    assert TapDance().is_empty
    assert not TapDance(on_tap=0x0004).is_empty
    # A tapping term alone is not a definition.
    assert TapDance(tapping_term=200).is_empty


def test_combo_round_trips() -> None:
    entry = Combo(keys=(0x0004, 0x0005, 0, 0), output=0x0006)
    assert Combo.unpack(entry.pack()) == entry
    assert entry.trigger_count == 2
    assert not entry.is_empty
    assert Combo().is_empty


def test_key_override_round_trips() -> None:
    entry = KeyOverride(
        trigger=0x7701, replacement=0x7700, layers=0xFFFF,
        trigger_mods=0x22, negative_mod_mask=0, suppressed_mods=0, options=0x07,
    )
    assert KeyOverride.unpack(entry.pack()) == entry
    assert len(entry.pack()) == 10


def test_key_override_enabled_lives_in_the_top_bit() -> None:
    entry = KeyOverride(trigger=1, replacement=2)
    assert not entry.enabled
    enabled = entry.with_enabled(True)
    assert enabled.enabled
    assert enabled.options & OPTION_ENABLED
    assert not enabled.with_enabled(False).enabled


def test_key_override_layer_membership() -> None:
    entry = KeyOverride(layers=0b1010)
    assert entry.applies_to_layer(1)
    assert entry.applies_to_layer(3)
    assert not entry.applies_to_layer(0)


def test_modifier_masks_are_described() -> None:
    assert describe_mods(0x22) == "LShift+RShift"
    assert describe_mods(0x00) == "none"

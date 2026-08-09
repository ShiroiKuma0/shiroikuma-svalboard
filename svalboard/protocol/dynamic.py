# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 白い熊
#
# The wire layouts here are Vial's, as implemented by vial-qmk and read by vial-gui
# (both GPL-2.0-or-later). They are interface facts.
"""Tap dances, combos and key overrides — Vial's "dynamic entries".

All three are fetched one at a time through the same command, differing only in
sub-command and in how the twelve payload bytes are laid out. The reply's first byte
is a status, and the entry follows it — an off-by-one there yields keycodes shifted by
a byte, which decode into plausible-looking nonsense rather than failing, so the offset
is stated once here and nowhere else.

Everything on this side of the boundary is a keycode *number*. Naming is the keycode
module's job.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field, replace

# Layouts, little-endian throughout — unlike the keymap, whose keycodes are big-endian.
TAP_DANCE_FORMAT = "<HHHHH"
COMBO_FORMAT = "<HHHHH"
KEY_OVERRIDE_FORMAT = "<HHHBBBB"

#: The status byte that precedes every entry in a reply.
ENTRY_OFFSET = 1


class DynamicEntryError(Exception):
    """The keyboard refused to hand over an entry."""


@dataclass(frozen=True)
class TapDance:
    """What one key does when tapped, held, double-tapped, or tapped then held."""

    on_tap: int = 0
    on_hold: int = 0
    on_double_tap: int = 0
    on_tap_hold: int = 0
    tapping_term: int = 0

    @property
    def is_empty(self) -> bool:
        return not any(
            (self.on_tap, self.on_hold, self.on_double_tap, self.on_tap_hold)
        )

    def pack(self) -> bytes:
        return struct.pack(
            TAP_DANCE_FORMAT,
            self.on_tap,
            self.on_hold,
            self.on_double_tap,
            self.on_tap_hold,
            self.tapping_term,
        )

    @classmethod
    def unpack(cls, data: bytes) -> TapDance:
        return cls(*struct.unpack(TAP_DANCE_FORMAT, data[: struct.calcsize(TAP_DANCE_FORMAT)]))


@dataclass(frozen=True)
class Combo:
    """Up to four keys pressed together, producing one."""

    keys: tuple[int, int, int, int] = (0, 0, 0, 0)
    output: int = 0

    @property
    def is_empty(self) -> bool:
        return not any(self.keys) and not self.output

    @property
    def trigger_count(self) -> int:
        return sum(1 for key in self.keys if key)

    def pack(self) -> bytes:
        return struct.pack(COMBO_FORMAT, *self.keys, self.output)

    @classmethod
    def unpack(cls, data: bytes) -> Combo:
        values = struct.unpack(COMBO_FORMAT, data[: struct.calcsize(COMBO_FORMAT)])
        return cls(keys=values[0:4], output=values[4])


#: Bit positions in a key override's option byte.
OPTION_TRIGGER_DOWN = 1 << 0
OPTION_REQUIRED_MOD_DOWN = 1 << 1
OPTION_NEGATIVE_MOD_UP = 1 << 2
OPTION_ONE_MOD = 1 << 3
OPTION_NO_REREGISTER_TRIGGER = 1 << 4
OPTION_NO_UNREGISTER_ON_OTHER_KEY_DOWN = 1 << 5
#: Bit 6 is unused; enabled deliberately lives in the top bit.
OPTION_ENABLED = 1 << 7

OPTION_LABELS = (
    (OPTION_TRIGGER_DOWN, "Activate on trigger press"),
    (OPTION_REQUIRED_MOD_DOWN, "Activate on modifier press"),
    (OPTION_NEGATIVE_MOD_UP, "Activate on negative modifier release"),
    (OPTION_ONE_MOD, "Any one trigger modifier activates"),
    (OPTION_NO_REREGISTER_TRIGGER, "Do not re-register the trigger on release"),
    (OPTION_NO_UNREGISTER_ON_OTHER_KEY_DOWN, "Do not cancel when another key is pressed"),
)

#: Modifier bits, as used by trigger_mods, negative_mod_mask and suppressed_mods.
MOD_LABELS = (
    (0x01, "LCtrl"),
    (0x02, "LShift"),
    (0x04, "LAlt"),
    (0x08, "LGui"),
    (0x10, "RCtrl"),
    (0x20, "RShift"),
    (0x40, "RAlt"),
    (0x80, "RGui"),
)


@dataclass(frozen=True)
class KeyOverride:
    """One key, replaced by another while given modifiers and layers apply."""

    trigger: int = 0
    replacement: int = 0
    layers: int = 0
    trigger_mods: int = 0
    negative_mod_mask: int = 0
    suppressed_mods: int = 0
    options: int = 0

    @property
    def is_empty(self) -> bool:
        return not self.trigger and not self.replacement

    @property
    def enabled(self) -> bool:
        return bool(self.options & OPTION_ENABLED)

    def with_enabled(self, enabled: bool) -> KeyOverride:
        options = self.options | OPTION_ENABLED if enabled else self.options & ~OPTION_ENABLED
        return replace(self, options=options & 0xFF)

    def applies_to_layer(self, layer: int) -> bool:
        return bool(self.layers & (1 << layer))

    def pack(self) -> bytes:
        return struct.pack(
            KEY_OVERRIDE_FORMAT,
            self.trigger,
            self.replacement,
            self.layers,
            self.trigger_mods,
            self.negative_mod_mask,
            self.suppressed_mods,
            self.options,
        )

    @classmethod
    def unpack(cls, data: bytes) -> KeyOverride:
        return cls(
            *struct.unpack(KEY_OVERRIDE_FORMAT, data[: struct.calcsize(KEY_OVERRIDE_FORMAT)])
        )


def describe_mods(mask: int) -> str:
    """``0x05`` becomes ``LCtrl+LAlt``; an empty mask becomes ``none``."""
    names = [label for bit, label in MOD_LABELS if mask & bit]
    return "+".join(names) if names else "none"

# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 白い熊
#
# The query, get, set and reset commands are Vial's, as implemented by vial-qmk and
# read by vial-gui (both GPL-2.0-or-later). They are interface facts.
"""QMK's own settings — tapping term, auto shift, mouse keys and the rest.

The keyboard is asked which settings it actually supports rather than assumed to
support all of them, because a firmware built without a feature simply does not carry
its QSID. The web configurator performs that query and then ignores the result,
fetching every QSID in its table regardless; here the answer is honoured, which is why
this can say "not built into this firmware" instead of showing a control that does
nothing.

A QSID holds either one integer or a set of booleans packed into its bits, and it is
one, two or four bytes wide depending on which. Writing the wrong width writes the
wrong bytes, so the width always comes from the schema.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from .constants import Vial
from .qmk_settings_table import TABS, WIDTHS

#: The query returns QSIDs until this appears.
END_OF_LIST = 0xFFFF

#: How many QSIDs one query reply can carry, after the status byte.
QUERY_STRIDE = 15


class SettingsError(Exception):
    """The keyboard refused a settings operation."""


@dataclass(frozen=True)
class Field:
    """One control on the settings page."""

    tab: str
    title: str
    qsid: int
    kind: str
    bit: int | None = None
    minimum: int = 0
    maximum: int = 0

    @property
    def is_boolean(self) -> bool:
        return self.kind == "boolean"

    @property
    def width(self) -> int:
        return WIDTHS.get(self.qsid, 1)


def fields() -> list[Field]:
    """Every field in the schema, in the order the tabs declare them."""
    out: list[Field] = []
    for tab, entries in TABS:
        for entry in entries:
            out.append(
                Field(
                    tab=tab,
                    title=entry["title"],
                    qsid=entry["qsid"],
                    kind=entry["type"],
                    bit=entry.get("bit"),
                    minimum=entry.get("min", 0),
                    maximum=entry.get("max", 0),
                )
            )
    return out


def tabs() -> list[str]:
    return [tab for tab, _entries in TABS]


def pack(qsid: int, value: int) -> bytes:
    """The value, in the width this QSID actually occupies."""
    width = WIDTHS.get(qsid, 1)
    return int(value).to_bytes(width, "little", signed=False)


def unpack(qsid: int, data: bytes) -> int:
    width = WIDTHS.get(qsid, 1)
    return int.from_bytes(data[:width], "little", signed=False)


def read_bit(raw: int, bit: int) -> bool:
    return bool(raw & (1 << bit))


def write_bit(raw: int, bit: int, value: bool) -> int:
    return raw | (1 << bit) if value else raw & ~(1 << bit)


class QmkSettings:
    """Reads and writes QMK settings for one keyboard.

    Values are held per QSID rather than per field, because several booleans share
    one QSID and writing a field means rewriting the whole thing.
    """

    def __init__(self, exchange) -> None:
        #: A callable taking the payload bytes and returning the 32-byte reply.
        self._exchange = exchange
        self.supported: set[int] = set()
        self.values: dict[int, int] = {}

    # -- reading -----------------------------------------------------------------

    def query_supported(self) -> set[int]:
        """Ask the keyboard which QSIDs it carries."""
        found: set[int] = set()
        greater_than = 0
        # Bounded rather than "until the sentinel": a firmware that never sends one
        # would otherwise spin here forever.
        for _round in range(64):
            reply = self._exchange(
                struct.pack("<BBH", 0xFE, Vial.QMK_SETTINGS_QUERY, greater_than)
            )
            batch = struct.unpack_from(f"<{QUERY_STRIDE}H", reply, 0)
            done = False
            for qsid in batch:
                if qsid == END_OF_LIST:
                    done = True
                    break
                found.add(qsid)
                greater_than = max(greater_than, qsid)
            if done:
                break
        self.supported = found
        return found

    def read_all(self) -> dict[int, int]:
        """Fetch every supported QSID. Unsupported ones are not asked for."""
        values: dict[int, int] = {}
        for qsid in sorted(self.supported):
            reply = self._exchange(
                struct.pack("<BBH", 0xFE, Vial.QMK_SETTINGS_GET, qsid)
            )
            if reply[0] != 0:
                # The keyboard listed it but will not produce it; skip rather than
                # abort, so one odd setting does not cost the whole page.
                continue
            values[qsid] = unpack(qsid, reply[1:])
        self.values = values
        return values

    # -- writing -----------------------------------------------------------------

    def write(self, qsid: int, value: int) -> None:
        reply = self._exchange(
            struct.pack("<BBH", 0xFE, Vial.QMK_SETTINGS_SET, qsid) + pack(qsid, value)
        )
        if reply[0] != 0:
            raise SettingsError(f"The keyboard refused QMK setting {qsid}.")
        self.values[qsid] = value

    def reset(self) -> None:
        """Return every QMK setting to the firmware's defaults.

        Defined by the protocol but never wired up by the web configurator, which is
        why a board can end up with settings no interface offers to undo.
        """
        self._exchange(bytes([0xFE, Vial.QMK_SETTINGS_RESET]))

    # -- field access ------------------------------------------------------------

    def available(self, field: Field) -> bool:
        return field.qsid in self.supported

    def get(self, field: Field) -> int | bool:
        raw = self.values.get(field.qsid, 0)
        if field.is_boolean and field.bit is not None:
            return read_bit(raw, field.bit)
        return raw

    def set(self, field: Field, value: int | bool) -> None:
        if field.is_boolean and field.bit is not None:
            raw = write_bit(self.values.get(field.qsid, 0), field.bit, bool(value))
        else:
            raw = int(value)
        self.write(field.qsid, raw)

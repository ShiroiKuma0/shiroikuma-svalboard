# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 白い熊
#
# The command sequences here follow vial-gui (GPL-2.0-or-later) and vial-qmk's
# own implementation. They are interface facts.
"""One connected keyboard, and everything the interface asks of it.

This is the only place that speaks the protocol. Everything above it deals in Python
objects, so the interface never has to know that keycodes go out big-endian while the
keyboard identifier comes back little-endian, or that buffers chunk at 28 bytes.

Reads are eager and happen once on connect: the definition, the capacities and the
whole keymap. That is around eighty round trips, which is fast enough to be invisible
and much simpler than fetching a layer at a time.
"""

from __future__ import annotations

import json
import lzma
import struct
from dataclasses import dataclass, field

from ..hid.enumerate import HidInterface, find_raw_hid
from ..hid.transport import RawHidTransport, TransportError
from .constants import (
    BUFFER_CHUNK,
    DEFINITION_BLOCK,
    SUPPORTED_VIAL_PROTOCOL,
    SVAL_MAGIC,
    Dynamic,
    Sval,
    Via,
    Vial,
)
from .keycodes import KeycodeSet
from .kle import Layout, from_definition


class ProtocolError(Exception):
    """The keyboard answered, but not with something usable."""


@dataclass
class Capacities:
    layers: int = 0
    macros: int = 0
    macro_bytes: int = 0
    tap_dances: int = 0
    combos: int = 0
    key_overrides: int = 0


@dataclass
class Identity:
    via_protocol: int = -1
    vial_protocol: int = -1
    keyboard_id: int = 0
    unlocked: bool = True
    unlock_in_progress: bool = False

    #: Present only on firmware carrying the Svalboard 0xEE extension. 白い熊's board
    #: does not have it: every 0xEE command is answered the way a junk command is.
    sval_protocol: int | None = None
    sval_firmware: str = ""

    @property
    def has_svalboard_extension(self) -> bool:
        return self.sval_protocol is not None

    @property
    def keyboard_id_hex(self) -> str:
        return " ".join(f"{b:02X}" for b in struct.pack("<Q", self.keyboard_id))


@dataclass
class KeyboardState:
    """Everything read from the keyboard, as plain data."""

    identity: Identity = field(default_factory=Identity)
    capacities: Capacities = field(default_factory=Capacities)
    definition: dict = field(default_factory=dict)
    layout: Layout = field(default_factory=Layout)
    keymap: list[int] = field(default_factory=list)
    layer_colours: list[tuple[int, int, int]] = field(default_factory=list)

    @property
    def rows(self) -> int:
        return self.layout.rows

    @property
    def cols(self) -> int:
        return self.layout.cols

    @property
    def keys_per_layer(self) -> int:
        return self.rows * self.cols

    @property
    def name(self) -> str:
        return str(self.definition.get("name") or "Keyboard")

    def layer(self, index: int) -> list[int]:
        start = index * self.keys_per_layer
        return self.keymap[start : start + self.keys_per_layer]

    def keycode_set(self) -> KeycodeSet:
        return KeycodeSet(
            layers=self.capacities.layers,
            macros=self.capacities.macros,
            tap_dances=self.capacities.tap_dances,
            custom_keycodes=self.definition.get("customKeycodes") or [],
        )


class Keyboard:
    """Reads and writes one keyboard over raw HID."""

    def __init__(self, transport: RawHidTransport) -> None:
        self.transport = transport
        self.state = KeyboardState()

    # -- connecting --------------------------------------------------------------

    @classmethod
    def open(cls, interface: HidInterface | None = None, **kwargs) -> Keyboard:
        if interface is None:
            found = find_raw_hid()
            if not found:
                raise TransportError(
                    "No Vial keyboard found. Check that the Svalboard is plugged in."
                )
            interface = found[0]
        transport = RawHidTransport(interface, **kwargs)
        transport.open()
        return cls(transport)

    def close(self) -> None:
        self.transport.close()

    def __enter__(self) -> Keyboard:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # -- raw helpers -------------------------------------------------------------

    def _via(self, *payload: int) -> bytes:
        return self.transport.exchange(bytes(payload))

    def _vial(self, command: int, *rest: int) -> bytes:
        return self.transport.exchange(bytes([Via.VIAL_PREFIX, command, *rest]))

    def _sval(self, command: int, *rest: int) -> bytes:
        return self.transport.exchange(bytes([Sval.PREFIX, command, *rest]))

    # -- reading -----------------------------------------------------------------

    def load(self) -> KeyboardState:
        """Read the whole keyboard. Call once on connect."""
        state = KeyboardState()
        state.identity = self.read_identity()
        state.capacities = self.read_capacities()
        state.definition = self.read_definition()
        state.layout = from_definition(state.definition)
        state.keymap = self.read_keymap(
            state.capacities.layers, state.layout.rows, state.layout.cols
        )
        if state.identity.has_svalboard_extension:
            state.layer_colours = self.read_layer_colours(state.capacities.layers)
        self.state = state
        return state

    def read_identity(self) -> Identity:
        identity = Identity()
        identity.via_protocol = struct.unpack(
            ">H", self._via(Via.GET_PROTOCOL_VERSION)[1:3]
        )[0]

        reply = self._vial(Vial.GET_KEYBOARD_ID)
        identity.vial_protocol, identity.keyboard_id = struct.unpack("<IQ", reply[0:12])
        if identity.vial_protocol not in SUPPORTED_VIAL_PROTOCOL:
            raise ProtocolError(
                f"Vial protocol {identity.vial_protocol} is not supported; this "
                f"program understands {SUPPORTED_VIAL_PROTOCOL}."
            )

        unlock = self._vial(Vial.GET_UNLOCK_STATUS)
        identity.unlocked = bool(unlock[0])
        identity.unlock_in_progress = bool(unlock[1])

        probe = self._sval(Sval.GET_PROTOCOL_VERSION)
        if probe[0:4] == SVAL_MAGIC:
            identity.sval_protocol = struct.unpack("<I", probe[4:8])[0]
            firmware = self._sval(Sval.GET_FIRMWARE_VERSION)
            identity.sval_firmware = firmware.split(b"\x00")[0].decode("utf-8", "replace")
        return identity

    def read_capacities(self) -> Capacities:
        capacities = Capacities()
        capacities.layers = self._via(Via.GET_LAYER_COUNT)[1]
        entries = self._vial(Vial.DYNAMIC_ENTRY_OP, Dynamic.GET_NUMBER_OF_ENTRIES)
        capacities.tap_dances, capacities.combos, capacities.key_overrides = entries[0:3]
        capacities.macros = self._via(Via.MACRO_GET_COUNT)[1]
        capacities.macro_bytes = struct.unpack(
            ">H", self._via(Via.MACRO_GET_BUFFER_SIZE)[1:3]
        )[0]
        return capacities

    def read_definition(self) -> dict:
        size = struct.unpack("<I", self._vial(Vial.GET_SIZE)[0:4])[0]
        if not 0 < size <= 1 << 20:
            raise ProtocolError(f"Implausible definition size: {size} bytes.")

        blob, block = b"", 0
        while len(blob) < size:
            blob += self._vial(Vial.GET_DEFINITION, *struct.pack("<I", block))
            block += 1
            if block * DEFINITION_BLOCK > size + DEFINITION_BLOCK:
                raise ProtocolError("The keyboard stopped sending its definition.")
        try:
            return json.loads(lzma.decompress(blob[:size]))
        except (lzma.LZMAError, json.JSONDecodeError) as exc:
            raise ProtocolError(f"The keyboard definition is unreadable: {exc}") from exc

    def read_keymap(self, layers: int, rows: int, cols: int) -> list[int]:
        total = layers * rows * cols * 2
        buffer, offset = b"", 0
        while offset < total:
            length = min(BUFFER_CHUNK, total - offset)
            reply = self._via(
                *struct.pack(">BHB", Via.KEYMAP_GET_BUFFER, offset, length)
            )
            buffer += reply[4 : 4 + length]
            offset += length
        if len(buffer) != total:
            raise ProtocolError(
                f"Short keymap: expected {total} bytes, received {len(buffer)}."
            )
        return list(struct.unpack(f">{layers * rows * cols}H", buffer))

    def read_layer_colours(self, layers: int) -> list[tuple[int, int, int]]:
        if not self.state.identity.has_svalboard_extension:
            return []
        colours = []
        for layer in range(layers):
            reply = self._sval(Sval.LAYER_COLOR_GET, layer)
            colours.append((reply[0], reply[1], reply[2]))
        return colours

    # -- writing -----------------------------------------------------------------

    def write_key(self, layer: int, row: int, col: int, code: int) -> None:
        """Set one key. The keycode goes out big-endian, unlike most of the protocol."""
        self._via(*struct.pack(">BBBBH", Via.SET_KEYCODE, layer, row, col, code & 0xFFFF))

    def write_keys(self, changes: list[tuple[int, int, int, int]]) -> None:
        """Apply many single-key writes, in order."""
        for layer, row, col, code in changes:
            self.write_key(layer, row, col, code)

    def write_layer_colour(self, layer: int, hue: int, saturation: int, value: int) -> None:
        if not self.state.identity.has_svalboard_extension:
            raise ProtocolError(
                "This firmware has no Svalboard extension, so layer colours cannot "
                "be set. It needs a vial-qmk build carrying the 0xEE commands."
            )
        self._sval(Sval.LAYER_COLOR_SET, layer, hue & 0xFF, saturation & 0xFF, value & 0xFF)

    # -- verification ------------------------------------------------------------

    def verify_round_trip(self) -> bool:
        """Read the keymap, write it back unchanged, and read it again.

        Run before anything destructive. It proves the write path addresses the same
        positions the read path does — a transposed row and column would corrupt a
        keymap silently, and this is the cheapest way to find that out.
        """
        state = self.state
        before = self.read_keymap(state.capacities.layers, state.rows, state.cols)
        for kmid, code in enumerate(before):
            layer, rest = divmod(kmid, state.keys_per_layer)
            row, col = divmod(rest, state.cols)
            self.write_key(layer, row, col, code)
        after = self.read_keymap(state.capacities.layers, state.rows, state.cols)
        return before == after

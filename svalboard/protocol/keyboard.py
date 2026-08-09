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
    ViaValue,
    Vial,
)
from .dynamic import (
    ENTRY_OFFSET,
    Combo,
    DynamicEntryError,
    KeyOverride,
    TapDance,
)
from .keycodes import KeycodeSet
from .kle import Layout, from_definition
from .macros import Macro, deserialize_buffer, serialize_buffer
from .qmk_settings import QmkSettings


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
    macros: list[Macro] = field(default_factory=list)
    tap_dances: list[TapDance] = field(default_factory=list)
    combos: list[Combo] = field(default_factory=list)
    key_overrides: list[KeyOverride] = field(default_factory=list)
    qmk_supported: set[int] = field(default_factory=set)
    qmk_values: dict[int, int] = field(default_factory=dict)

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
        state.macros = self.read_macros(
            state.capacities.macros, state.capacities.macro_bytes
        )
        state.tap_dances = self.read_tap_dances(state.capacities.tap_dances)
        state.combos = self.read_combos(state.capacities.combos)
        state.key_overrides = self.read_key_overrides(state.capacities.key_overrides)
        settings = QmkSettings(self.transport.exchange)
        state.qmk_supported = settings.query_supported()
        state.qmk_values = settings.read_all()
        if state.identity.has_svalboard_extension:
            state.layer_colours = self.read_layer_colours(state.capacities.layers)
        self.state = state
        return state

    # -- dynamic entries ---------------------------------------------------------

    def _read_entries(self, sub_command: int, count: int, size: int) -> list[bytes]:
        entries: list[bytes] = []
        for index in range(count):
            reply = self._vial(Vial.DYNAMIC_ENTRY_OP, sub_command, index)
            if reply[0] != 0:
                raise DynamicEntryError(
                    f"The keyboard refused entry {index} of dynamic set "
                    f"{sub_command:#04x}."
                )
            entries.append(reply[ENTRY_OFFSET : ENTRY_OFFSET + size])
        return entries

    def read_tap_dances(self, count: int) -> list[TapDance]:
        return [
            TapDance.unpack(data)
            for data in self._read_entries(Dynamic.TAP_DANCE_GET, count, 10)
        ]

    def read_combos(self, count: int) -> list[Combo]:
        return [
            Combo.unpack(data)
            for data in self._read_entries(Dynamic.COMBO_GET, count, 10)
        ]

    def read_key_overrides(self, count: int) -> list[KeyOverride]:
        return [
            KeyOverride.unpack(data)
            for data in self._read_entries(Dynamic.KEY_OVERRIDE_GET, count, 10)
        ]

    def write_tap_dance(self, index: int, entry: TapDance) -> None:
        self._vial(Vial.DYNAMIC_ENTRY_OP, Dynamic.TAP_DANCE_SET, index, *entry.pack())

    def write_combo(self, index: int, entry: Combo) -> None:
        self._vial(Vial.DYNAMIC_ENTRY_OP, Dynamic.COMBO_SET, index, *entry.pack())

    def write_key_override(self, index: int, entry: KeyOverride) -> None:
        self._vial(
            Vial.DYNAMIC_ENTRY_OP, Dynamic.KEY_OVERRIDE_SET, index, *entry.pack()
        )

    # -- the switch matrix -------------------------------------------------------

    def read_matrix(self, rows: int, cols: int) -> list[list[bool]]:
        """Which switches are closed right now.

        The reply carries two bytes of VIA header and then one bit per column,
        packed into ceil(cols / 8) bytes per row. This is the only way to see a
        physical press without going through the operating system's input stack —
        which matters on Wayland, where a program cannot observe keys sent to
        another window, and matters here regardless because the key being pressed
        may currently be mapped to something unhelpful.
        """
        reply = self._via(Via.GET_KEYBOARD_VALUE, ViaValue.SWITCH_MATRIX_STATE)
        stride = (cols + 7) // 8
        state: list[list[bool]] = []
        for row in range(rows):
            offset = 2 + row * stride
            chunk = reply[offset : offset + stride]
            state.append(
                [
                    bool(chunk[col // 8] & (1 << (col % 8))) if col // 8 < len(chunk) else False
                    for col in range(cols)
                ]
            )
        return state

    # -- macros ------------------------------------------------------------------

    def read_macro_buffer(self, size: int) -> bytes:
        buffer, offset = b"", 0
        while offset < size:
            length = min(BUFFER_CHUNK, size - offset)
            reply = self._via(
                *struct.pack(">BHB", Via.MACRO_GET_BUFFER, offset, length)
            )
            buffer += reply[4 : 4 + length]
            offset += length
        return buffer

    def read_macros(self, count: int, size: int) -> list[Macro]:
        if not count or not size:
            return []
        return deserialize_buffer(self.read_macro_buffer(size), count)

    def write_macros(self, macros: list[Macro], size: int) -> None:
        """Rewrite the whole buffer.

        There is no way to write one macro: they share a buffer, so a macro that
        grows moves every later one. Anything that changes a macro rewrites all.
        """
        buffer = serialize_buffer(macros, size)
        offset = 0
        while offset < size:
            length = min(BUFFER_CHUNK, size - offset)
            self._via(
                *struct.pack(">BHB", Via.MACRO_SET_BUFFER, offset, length),
                *buffer[offset : offset + length],
            )
            offset += length

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

    def qmk_settings(self) -> QmkSettings:
        settings = QmkSettings(self.transport.exchange)
        settings.supported = set(self.state.qmk_supported)
        settings.values = dict(self.state.qmk_values)
        return settings

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

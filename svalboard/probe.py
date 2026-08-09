# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 白い熊
"""Read-only diagnostic: what is attached, and what does it support?

Run it with ``python3 -m svalboard.probe``. Everything here only reads — no command
that writes to the keyboard is issued — so it is safe to run at any time, and it is
the first thing to reach for when the application misbehaves.
"""

from __future__ import annotations

import argparse
import json
import lzma
import struct
import sys

from .hid.enumerate import access_problem, find_console, find_raw_hid, iter_interfaces
from .hid.transport import RawHidTransport, TransportError
from .protocol.constants import (
    BUFFER_CHUNK,
    DEFINITION_BLOCK,
    SVAL_MAGIC,
    Dynamic,
    Sval,
    Via,
    Vial,
)


def _heading(text: str) -> None:
    print(f"\n{text}\n{'─' * len(text)}")


def _interfaces() -> None:
    _heading("HID interfaces")
    for interface in iter_interfaces():
        mark = "  "
        if interface.is_raw_hid and interface.is_vial:
            mark = "→ "
        elif interface.is_console and interface.is_vial:
            mark = "· "
        print(f"{mark}{interface.describe()}")

    for interface in find_raw_hid() + find_console():
        problem = access_problem(interface)
        if problem:
            print(f"\n  {interface.node}: {problem}")


def _identity(kb: RawHidTransport) -> dict[str, object]:
    _heading("Identity")
    facts: dict[str, object] = {}

    via_proto = struct.unpack(">H", kb.exchange([Via.GET_PROTOCOL_VERSION])[1:3])[0]
    vial_proto, keyboard_id = struct.unpack(
        "<IQ", kb.exchange([Via.VIAL_PREFIX, Vial.GET_KEYBOARD_ID])[0:12]
    )
    facts["via_protocol"] = via_proto
    facts["vial_protocol"] = vial_proto
    facts["keyboard_id"] = keyboard_id

    print(f"  VIA protocol   : {via_proto}")
    print(f"  Vial protocol  : {vial_proto}")
    print(f"  keyboard ID    : {' '.join(f'{b:02X}' for b in struct.pack('<Q', keyboard_id))}")

    unlock = kb.exchange([Via.VIAL_PREFIX, Vial.GET_UNLOCK_STATUS])
    facts["unlocked"] = bool(unlock[0])
    print(f"  unlocked       : {bool(unlock[0])} (in progress: {bool(unlock[1])})")
    if not unlock[0]:
        keys = [
            (unlock[2 + i * 2], unlock[3 + i * 2])
            for i in range(15)
            if unlock[2 + i * 2] != 0xFF or unlock[3 + i * 2] != 0xFF
        ]
        print(f"  unlock combo   : {keys}")

    return facts


def _svalboard(kb: RawHidTransport) -> bool:
    _heading("Svalboard extension (0xEE)")
    reply = kb.exchange([Sval.PREFIX, Sval.GET_PROTOCOL_VERSION])
    if reply[0:4] == SVAL_MAGIC:
        version = struct.unpack("<I", reply[4:8])[0]
        firmware = kb.exchange([Sval.PREFIX, Sval.GET_FIRMWARE_VERSION])
        name = firmware.split(b"\x00")[0].decode("utf-8", "replace")
        print(f"  present        : yes, protocol {version}")
        print(f"  firmware       : {name}")
        return True

    unhandled = reply[0] == 0xFF
    print(f"  present        : no — reply {reply[:4].hex(' ')}"
          f"{' (id_unhandled)' if unhandled else ''}")
    print("  Layer colours and the firmware version string need this extension;")
    print("  a build without it answers every 0xEE command the way it answers junk.")
    return False


def _capabilities(kb: RawHidTransport) -> dict[str, int]:
    _heading("Capacities")
    layers = kb.exchange([Via.GET_LAYER_COUNT])[1]
    tap_dance, combo, key_override = kb.exchange(
        [Via.VIAL_PREFIX, Vial.DYNAMIC_ENTRY_OP, Dynamic.GET_NUMBER_OF_ENTRIES]
    )[0:3]
    macros = kb.exchange([Via.MACRO_GET_COUNT])[1]
    macro_bytes = struct.unpack(">H", kb.exchange([Via.MACRO_GET_BUFFER_SIZE])[1:3])[0]

    print(f"  layers         : {layers}")
    print(f"  macros         : {macros} in {macro_bytes} bytes")
    print(f"  tap dances     : {tap_dance}")
    print(f"  combos         : {combo}")
    print(f"  key overrides  : {key_override}")
    return {"layers": layers, "macros": macros}


def _definition(kb: RawHidTransport, dump: str | None) -> dict[str, object]:
    _heading("Keyboard definition")
    size = struct.unpack("<I", kb.exchange([Via.VIAL_PREFIX, Vial.GET_SIZE])[0:4])[0]
    blob, block = b"", 0
    while len(blob) < size:
        blob += kb.exchange(
            [Via.VIAL_PREFIX, Vial.GET_DEFINITION, *struct.pack("<I", block)]
        )
        block += 1
    blob = blob[:size]
    payload = json.loads(lzma.decompress(blob))

    matrix = payload.get("matrix", {})
    custom = payload.get("customKeycodes") or []
    print(f"  compressed     : {size} bytes in {block} blocks of {DEFINITION_BLOCK}")
    print(f"  name           : {payload.get('name')}")
    print(f"  matrix         : {matrix.get('rows')} rows × {matrix.get('cols')} cols")
    print(f"  lighting       : {payload.get('lighting')}")
    print(f"  custom keycodes: {len(custom)}")
    for index, keycode in enumerate(custom):
        label = " ".join(str(keycode.get("shortName", "")).split())
        print(f"      USER{index:02d} {keycode.get('name'):<24} {label}")

    if dump:
        with open(dump, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
        print(f"  written to     : {dump}")
    return payload


def _keymap(kb: RawHidTransport, layers: int, rows: int, cols: int) -> None:
    _heading("Keymap")
    total = layers * rows * cols * 2
    buffer, offset = b"", 0
    while offset < total:
        length = min(BUFFER_CHUNK, total - offset)
        reply = kb.exchange(struct.pack(">BHB", Via.KEYMAP_GET_BUFFER, offset, length))
        buffer += reply[4 : 4 + length]
        offset += length

    codes = struct.unpack(f">{layers * rows * cols}H", buffer)
    print(f"  read           : {len(buffer)} bytes")
    for layer in range(layers):
        window = codes[layer * rows * cols : (layer + 1) * rows * cols]
        used = sum(1 for code in window if code)
        bar = "█" * round(used / len(window) * 24)
        print(f"  layer {layer:<2}       {used:2d}/{len(window)} {bar}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--dump-definition",
        metavar="FILE",
        help="write the decompressed keyboard definition to FILE",
    )
    parser.add_argument(
        "--skip-keymap", action="store_true", help="skip the keymap read (69 round trips)"
    )
    args = parser.parse_args(argv)

    _interfaces()

    interfaces = find_raw_hid()
    if not interfaces:
        print("\nNo Vial keyboard found.")
        return 1

    try:
        with RawHidTransport(interfaces[0]) as kb:
            _identity(kb)
            _svalboard(kb)
            capacities = _capabilities(kb)
            payload = _definition(kb, args.dump_definition)
            if not args.skip_keymap:
                matrix = payload.get("matrix", {})
                _keymap(
                    kb,
                    capacities["layers"],
                    int(matrix.get("rows", 0)),
                    int(matrix.get("cols", 0)),
                )
    except TransportError as exc:
        print(f"\n{exc}")
        return 1

    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())

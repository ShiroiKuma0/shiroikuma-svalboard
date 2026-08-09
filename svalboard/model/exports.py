# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 白い熊
"""Writing the other two formats: Vial's ``.vil`` and QMK's ``keymap_all.h``.

``.vil`` is what Vial itself reads, so it is the format to hand someone who does not
use this program. It stores the keymap as a nested ``[layer][row][col]`` structure
rather than the flat one ``.kbi`` uses, and it carries no keyboard definition, which
is why loading one requires a keyboard attached to say what shape it is.

``keymap_all.h`` is C, for baking a layout into firmware so it survives a chip erase.
It is write-only by nature: nothing reads a header back.
"""

from __future__ import annotations

import json
from typing import Any

from ..protocol.dynamic import Combo, KeyOverride, TapDance
from ..protocol.keycodes import KeycodeSet
from ..protocol.macros import Macro

#: Vial's own protocol numbers, written so its GUI accepts the file.
VIL_VERSION = 1
VIL_VIA_PROTOCOL = 9
VIL_VIAL_PROTOCOL = 6

#: A 64-bit identifier cannot survive JSON as a number, so it is written through a
#: placeholder and substituted afterwards. Vial does the same, for the same reason.
_UID_PLACEHOLDER = "@@KEYBOARD_UID@@"


def to_vil(
    *,
    keyboard_id: int,
    layers: int,
    rows: int,
    cols: int,
    codes: list[int],
    keycodes: KeycodeSet,
    macros: list[Macro] | None = None,
    tap_dances: list[TapDance] | None = None,
    combos: list[Combo] | None = None,
    key_overrides: list[KeyOverride] | None = None,
    qmk_settings: dict[int, int] | None = None,
) -> str:
    """Render a ``.vil`` document."""
    per_layer = rows * cols
    layout = [
        [
            [
                keycodes.name(codes[layer * per_layer + row * cols + col])
                for col in range(cols)
            ]
            for row in range(rows)
        ]
        for layer in range(layers)
    ]

    document: dict[str, Any] = {
        "version": VIL_VERSION,
        "uid": _UID_PLACEHOLDER,
        "via_protocol": VIL_VIA_PROTOCOL,
        "vial_protocol": VIL_VIAL_PROTOCOL,
        "layout": layout,
        "layout_options": -1,
        # Encoders are not configured by this program, but the field is required and
        # Vial expects one entry per layer.
        "encoder_layout": [[] for _ in range(layers)],
        "macro": [
            [
                ["text", action.text]
                if action.is_text
                else ["delay", action.delay]
                if action.is_delay
                else [action.kind, keycodes.name(action.keycode)]
                for action in macro.actions
            ]
            for macro in (macros or [])
        ],
        "tap_dance": [
            [
                keycodes.name(entry.on_tap),
                keycodes.name(entry.on_hold),
                keycodes.name(entry.on_double_tap),
                keycodes.name(entry.on_tap_hold),
                entry.tapping_term,
            ]
            for entry in (tap_dances or [])
        ],
        "combo": [
            [keycodes.name(key) for key in entry.keys] + [keycodes.name(entry.output)]
            for entry in (combos or [])
        ],
        "key_override": [
            {
                "trigger": keycodes.name(entry.trigger),
                "replacement": keycodes.name(entry.replacement),
                "layers": entry.layers,
                "trigger_mods": entry.trigger_mods,
                "negative_mod_mask": entry.negative_mod_mask,
                "suppressed_mods": entry.suppressed_mods,
                "options": entry.options,
            }
            for entry in (key_overrides or [])
        ],
        "settings": {str(qsid): value for qsid, value in sorted((qmk_settings or {}).items())},
    }

    rendered = json.dumps(document, indent=2, ensure_ascii=False)
    return rendered.replace(f'"{_UID_PLACEHOLDER}"', str(keyboard_id))


def from_vil(document: dict[str, Any], *, rows: int, cols: int) -> dict[str, Any]:
    """Read a ``.vil`` document into the same shape a ``.kbi`` backup uses.

    The shape has to be supplied: a ``.vil`` carries no keyboard definition, so it
    cannot say how wide its own rows are.
    """
    layout = document.get("layout") or []
    keymap: list[list[str]] = []
    for layer in layout:
        flat: list[str] = []
        for row in range(rows):
            values = layer[row] if row < len(layer) else []
            for col in range(cols):
                flat.append(str(values[col]) if col < len(values) else "KC_NO")
        keymap.append(flat)

    return {
        "keyboard_id": int(document.get("uid") or 0),
        "layers": len(keymap),
        "keymap": keymap,
        "macros": list(document.get("macro") or []),
        "tap_dances": [
            {
                "tap": entry[0] if len(entry) > 0 else "KC_NO",
                "hold": entry[1] if len(entry) > 1 else "KC_NO",
                "doubletap": entry[2] if len(entry) > 2 else "KC_NO",
                "taphold": entry[3] if len(entry) > 3 else "KC_NO",
                "tapms": entry[4] if len(entry) > 4 else 0,
            }
            for entry in (document.get("tap_dance") or [])
        ],
        "combos": list(document.get("combo") or []),
        "key_overrides": list(document.get("key_override") or []),
    }


#: Svalboard cluster names, so the generated header reads like the keyboard rather
#: than like a matrix dump.
_CLUSTERS = {0: "left thumb", 5: "right thumb"}
_DIRECTIONS = ("south", "east", "centre", "north", "west", "super-south")


def to_keymap_header(
    *,
    layers: int,
    rows: int,
    cols: int,
    codes: list[int],
    keycodes: KeycodeSet,
    board: str = "svalboard",
) -> str:
    """Render ``keymap_all.h``: the keymap as C, for baking into firmware.

    A keymap held only in the keyboard's EEPROM is lost to a chip erase or a
    reflash that clears it. Compiling it in makes it the default the board returns
    to, which is the reason to want this at all.
    """
    per_layer = rows * cols
    lines = [
        "// AUTO-GENERATED by 白い熊 Svalboard — do not edit by hand.",
        "//",
        f"// {board}: {layers} layers of {rows} x {cols}.",
        "// Drop this into the keymap directory and include it from keymap.c.",
        "",
        "#pragma once",
        "",
        "const uint16_t PROGMEM keymaps[][MATRIX_ROWS][MATRIX_COLS] = {",
    ]

    for layer in range(layers):
        window = codes[layer * per_layer : (layer + 1) * per_layer]
        if not any(window):
            lines.append(f"    // layer {layer} is empty")
        lines.append(f"    [{layer}] = LAYOUT(")
        for row in range(rows):
            cluster = _CLUSTERS.get(row, f"cluster {row}")
            names = []
            for col in range(cols):
                name = keycodes.name(window[row * cols + col])
                # A generated header must compile: an unnamed code becomes its
                # literal value rather than an identifier the compiler cannot find.
                names.append(name if not name.startswith("0x") else name)
            trailing = "," if row < rows - 1 else ""
            lines.append(
                f"        {', '.join(names)}{trailing}  // {cluster}"
            )
        lines.append("    )," if layer < layers - 1 else "    )")
    lines.append("};")
    lines.append("")
    lines.append(f"// Column order within a cluster: {', '.join(_DIRECTIONS[:cols])}.")
    lines.append("")
    return "\n".join(lines)

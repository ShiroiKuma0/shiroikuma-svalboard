# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 白い熊
"""Reading and writing keyboard backups.

The ``.kbi`` format is the web configurator's, and is a fact about files 白い熊 may
already have rather than anything invented here — a JSON object holding the whole
keyboard, with the keymap stored as keycode *names* per layer rather than numbers, so
a backup survives a firmware whose numbering has shifted.

A file is identified by its contents, not its extension: ``kbid`` means ``.kbi`` and
``uid`` means Vial's own ``.vil``. That is what the web configurator does, and files
in the wild are named inconsistently.

Only what this program can currently produce is written — the keymap, macros, tap
dances, combos and key overrides. QMK settings and layer colours arrive later; until
then they are carried through unchanged when a file is re-saved, so loading and saving
a complete backup never silently discards the parts not yet understood. A backup that
uses none of a feature omits its section entirely rather than writing an empty one.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..protocol.dynamic import Combo, KeyOverride, TapDance
from ..protocol.keycodes import KeycodeSet
from ..protocol.macros import Action, Macro

#: What this program writes into a file so a later version knows what made it.
WRITER = "shiroikuma-svalboard"
KBI_VERSION = 1


class FileFormatError(Exception):
    """The file is not a keyboard backup this program can read."""


@dataclass
class Backup:
    """A keyboard backup, as far as this program understands it."""

    keyboard_id: int = 0
    layers: int = 0
    rows: int = 0
    cols: int = 0

    #: One list of keycode names per layer.
    keymap: list[list[str]] = field(default_factory=list)

    layer_names: dict[int, str] = field(default_factory=dict)

    #: Keycodes in these are names, exactly as in the keymap.
    macros: list[list[list]] = field(default_factory=list)
    tap_dances: list[dict] = field(default_factory=list)
    combos: list[list[str]] = field(default_factory=list)
    key_overrides: list[dict] = field(default_factory=list)

    #: Everything from the source file this version does not model, kept verbatim so
    #: re-saving does not throw it away.
    passthrough: dict[str, Any] = field(default_factory=dict)

    source: str = ""

    @property
    def keys_per_layer(self) -> int:
        return self.rows * self.cols

    def codes(self, keycodes: KeycodeSet) -> list[int]:
        """The keymap as a flat list of numbers, ready for the edit buffer."""
        flat: list[int] = []
        for layer in self.keymap:
            for name in layer:
                try:
                    flat.append(keycodes.parse(name))
                except ValueError:
                    # An unreadable name becomes "disabled" rather than aborting the
                    # whole restore; the position is visible as empty afterwards.
                    flat.append(0x0000)
        return flat

    def describe(self) -> str:
        parts = [f"{len(self.keymap)} layers × {self.keys_per_layer} positions"]
        for count, name in (
            (sum(1 for macro in self.macros if macro), "macros"),
            (sum(1 for entry in self.tap_dances if _any_key(entry.values())), "tap dances"),
            (sum(1 for entry in self.combos if any(entry)), "combos"),
            (sum(1 for entry in self.key_overrides if _any_key(entry.values())), "overrides"),
        ):
            if count:
                parts.append(f"{count} {name}")
        if self.layer_names:
            parts.append(f"{len(self.layer_names)} named layers")
        return ", ".join(parts)

    def macro_objects(self, keycodes: KeycodeSet) -> list[Macro]:
        """Rebuild macros, resolving keycode names."""
        macros: list[Macro] = []
        for entry in self.macros:
            actions: list[Action] = []
            for item in entry:
                if not isinstance(item, list) or not item:
                    continue
                kind = str(item[0])
                value = item[1] if len(item) > 1 else ""
                if kind == "text":
                    actions.append(Action("text", text=str(value)))
                elif kind == "delay":
                    actions.append(Action("delay", delay=int(value or 0)))
                elif kind in ("tap", "down", "up"):
                    actions.append(Action(kind, keycode=_parse(keycodes, value)))
            macros.append(Macro(actions))
        return macros

    def tap_dance_objects(self, keycodes: KeycodeSet) -> list[TapDance]:
        return [
            TapDance(
                on_tap=_parse(keycodes, entry.get("tap")),
                on_hold=_parse(keycodes, entry.get("hold")),
                on_double_tap=_parse(keycodes, entry.get("doubletap")),
                on_tap_hold=_parse(keycodes, entry.get("taphold")),
                tapping_term=int(entry.get("tapms") or 0),
            )
            for entry in self.tap_dances
        ]

    def combo_objects(self, keycodes: KeycodeSet) -> list[Combo]:
        out = []
        for entry in self.combos:
            names = list(entry) + [""] * (5 - len(entry))
            out.append(
                Combo(
                    keys=tuple(_parse(keycodes, name) for name in names[:4]),
                    output=_parse(keycodes, names[4]),
                )
            )
        return out

    def key_override_objects(self, keycodes: KeycodeSet) -> list[KeyOverride]:
        return [
            KeyOverride(
                trigger=_parse(keycodes, entry.get("trigger")),
                replacement=_parse(keycodes, entry.get("replacement")),
                layers=int(entry.get("layers") or 0),
                trigger_mods=int(entry.get("trigger_mods") or 0),
                negative_mod_mask=int(entry.get("negative_mod_mask") or 0),
                suppressed_mods=int(entry.get("suppressed_mods") or 0),
                options=int(entry.get("options") or 0),
            )
            for entry in self.key_overrides
        ]


def _any_key(values) -> bool:
    return any(value not in ("", "KC_NO", 0, None) for value in values)


def _parse(keycodes: KeycodeSet, name) -> int:
    """Resolve a stored keycode name, treating anything unreadable as disabled."""
    if name in (None, ""):
        return 0
    try:
        return keycodes.parse(name)
    except ValueError:
        return 0


def build_backup(
    *,
    keyboard_id: int,
    layers: int,
    rows: int,
    cols: int,
    codes: list[int],
    keycodes: KeycodeSet,
    layer_names: dict[int, str] | None = None,
    passthrough: dict[str, Any] | None = None,
    macros: list[Macro] | None = None,
    tap_dances: list[TapDance] | None = None,
    combos: list[Combo] | None = None,
    key_overrides: list[KeyOverride] | None = None,
) -> Backup:
    per_layer = rows * cols
    name = keycodes.name
    return Backup(
        keyboard_id=keyboard_id,
        layers=layers,
        rows=rows,
        cols=cols,
        keymap=[
            [keycodes.name(code) for code in codes[index * per_layer : (index + 1) * per_layer]]
            for index in range(layers)
        ],
        layer_names=dict(layer_names or {}),
        passthrough=dict(passthrough or {}),
        macros=[
            [
                ["text", action.text]
                if action.is_text
                else ["delay", action.delay]
                if action.is_delay
                else [action.kind, name(action.keycode)]
                for action in macro.actions
            ]
            for macro in (macros or [])
        ],
        tap_dances=[
            {
                "tdid": index,
                "tap": name(entry.on_tap),
                "hold": name(entry.on_hold),
                "doubletap": name(entry.on_double_tap),
                "taphold": name(entry.on_tap_hold),
                "tapms": entry.tapping_term,
            }
            for index, entry in enumerate(tap_dances or [])
        ],
        combos=[
            [name(key) for key in entry.keys] + [name(entry.output)]
            for entry in (combos or [])
        ],
        key_overrides=[
            {
                "koid": index,
                "trigger": name(entry.trigger),
                "replacement": name(entry.replacement),
                "layers": entry.layers,
                "trigger_mods": entry.trigger_mods,
                "negative_mod_mask": entry.negative_mod_mask,
                "suppressed_mods": entry.suppressed_mods,
                "options": entry.options,
            }
            for index, entry in enumerate(key_overrides or [])
        ],
    )


# -- writing ---------------------------------------------------------------------


def to_kbi(backup: Backup) -> dict[str, Any]:
    """Render a backup as ``.kbi``, preserving anything carried through."""
    payload: dict[str, Any] = dict(backup.passthrough)
    payload.update(
        {
            # The web configurator stores this as a decimal string, because
            # JavaScript cannot hold a 64-bit integer without losing digits.
            "kbid": str(backup.keyboard_id),
            "layers": backup.layers,
            "rows": backup.rows,
            "cols": backup.cols,
            "keymap": backup.keymap,
        }
    )
    for key, value in (
        ("macros", backup.macros),
        ("tapdances", backup.tap_dances),
        ("combos", backup.combos),
        ("key_overrides", backup.key_overrides),
    ):
        # Written only when present, so a keymap-only backup stays a keymap-only
        # file rather than gaining four empty sections.
        if value:
            payload[key] = value
    cosmetic = dict(payload.get("cosmetic") or {})
    if backup.layer_names:
        cosmetic["layer"] = {str(k): v for k, v in sorted(backup.layer_names.items())}
    elif "layer" in cosmetic:
        cosmetic.pop("layer")
    if cosmetic:
        payload["cosmetic"] = cosmetic

    payload["writer"] = WRITER
    payload["writer_version"] = KBI_VERSION
    return payload


def save_kbi(path: Path, backup: Backup) -> None:
    path.write_text(
        json.dumps(to_kbi(backup), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


# -- reading ---------------------------------------------------------------------


def load(path: Path) -> Backup:
    """Read a backup, choosing the format by content rather than by name."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FileFormatError(f"{path.name} could not be read: {exc}") from exc
    if not isinstance(payload, dict):
        raise FileFormatError(f"{path.name} is not a keyboard backup.")

    if "kbid" in payload:
        return from_kbi(payload)
    if "uid" in payload:
        raise FileFormatError(
            f"{path.name} is a Vial .vil file. Support for those arrives with the "
            f"macro and tap-dance work; .kbi files load today."
        )
    raise FileFormatError(
        f"{path.name} carries neither kbid nor uid, so it is not a keyboard backup."
    )


def from_kbi(payload: dict[str, Any]) -> Backup:
    try:
        keyboard_id = int(str(payload.get("kbid") or 0))
    except ValueError:
        keyboard_id = 0

    keymap = payload.get("keymap") or []
    if not isinstance(keymap, list) or not all(isinstance(row, list) for row in keymap):
        raise FileFormatError("The keymap in this file is not a list of layers.")

    rows = int(payload.get("rows") or 0)
    cols = int(payload.get("cols") or 0)
    layers = int(payload.get("layers") or len(keymap))
    if rows and cols and keymap and len(keymap[0]) != rows * cols:
        raise FileFormatError(
            f"This file says {rows}×{cols} but stores {len(keymap[0])} positions "
            f"per layer."
        )

    cosmetic = payload.get("cosmetic") or {}
    names: dict[int, str] = {}
    for key, value in (cosmetic.get("layer") or {}).items():
        try:
            names[int(key)] = str(value)
        except ValueError:
            continue

    known = {
        "kbid", "layers", "rows", "cols", "keymap", "writer", "writer_version",
        "macros", "tapdances", "combos", "key_overrides",
    }
    passthrough = {k: v for k, v in payload.items() if k not in known}

    return Backup(
        keyboard_id=keyboard_id,
        layers=layers,
        rows=rows,
        cols=cols,
        keymap=[[str(name) for name in layer] for layer in keymap],
        layer_names=names,
        passthrough=passthrough,
        source=str(payload.get("writer") or "keybard"),
        macros=list(payload.get("macros") or []),
        tap_dances=list(payload.get("tapdances") or []),
        combos=list(payload.get("combos") or []),
        key_overrides=list(payload.get("key_overrides") or []),
    )


def check_fits(backup: Backup, *, layers: int, rows: int, cols: int) -> list[str]:
    """Warnings about restoring this backup onto the attached keyboard.

    Returned rather than raised: a mismatch is usually still worth restoring, and
    refusing outright would make a backup from a differently-configured board
    useless. The caller decides.
    """
    warnings: list[str] = []
    if backup.rows and backup.cols and (backup.rows, backup.cols) != (rows, cols):
        warnings.append(
            f"The file is for a {backup.rows}×{backup.cols} matrix; this keyboard is "
            f"{rows}×{cols}. Positions will not line up."
        )
    if backup.layers > layers:
        warnings.append(
            f"The file has {backup.layers} layers; this keyboard has {layers}. "
            f"The extra layers will be ignored."
        )
    elif backup.layers and backup.layers < layers:
        warnings.append(
            f"The file has only {backup.layers} of this keyboard's {layers} layers. "
            f"The rest are left alone."
        )
    return warnings

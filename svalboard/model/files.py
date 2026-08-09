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

Only what this program can currently produce is written. Macros, tap dances, combos,
key overrides and QMK settings arrive in later milestones; until then they are carried
through unchanged when a file is re-saved, so loading and saving a complete backup
never silently discards the parts not yet understood.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..protocol.keycodes import KeycodeSet

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
        return (
            f"{len(self.keymap)} layers × {self.keys_per_layer} positions"
            + (f", {len(self.layer_names)} named" if self.layer_names else "")
        )


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
) -> Backup:
    per_layer = rows * cols
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

    known = {"kbid", "layers", "rows", "cols", "keymap", "writer", "writer_version"}
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

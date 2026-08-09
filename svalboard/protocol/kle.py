# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 白い熊
#
# The deserialisation rules implemented here are the Keyboard Layout Editor format as
# consumed by vial-gui (GPL-2.0-or-later) and vial-qmk. They are interface facts.
"""Turning a keyboard definition's ``layouts.keymap`` into physical key positions.

Keyboard Layout Editor stores a board as rows of alternating control objects and label
strings. A control object mutates the cursor — move it, resize the next key, rotate the
cluster — and a string emits a key at the cursor and advances it. Nothing is absolute:
every position is the accumulation of everything before it, which is why this has to be
a small state machine rather than a comprehension.

Vial overloads the labels. The first one carries ``"row,col"``, which is what ties a
drawn key to a position in the keymap buffer; the fifth marks encoders; the ninth
carries layout options. On the Svalboard the geometry that comes out is ten clusters —
eight for fingers, two for thumbs — and it is read from the keyboard rather than
assumed, so a firmware with a different shape simply draws differently.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Any

#: KLE's unit square. One key of width 1 is this many units across.
UNIT = 1.0


@dataclass(frozen=True)
class KeyPosition:
    """One drawn key, in KLE units, with the matrix position it maps to."""

    x: float
    y: float
    width: float = 1.0
    height: float = 1.0

    #: Secondary rectangle, for L-shaped keys such as an ISO enter. Zero width means
    #: the key is a plain rectangle.
    x2: float = 0.0
    y2: float = 0.0
    width2: float = 0.0
    height2: float = 0.0

    rotation_angle: float = 0.0
    rotation_x: float = 0.0
    rotation_y: float = 0.0

    row: int = -1
    col: int = -1

    #: Encoder index and direction, when this position is an encoder rather than a key.
    encoder_index: int = -1
    encoder_direction: int = -1

    #: Which layout variant this key belongs to, for boards with optional blockers.
    layout_index: int = -1
    layout_option: int = -1

    decal: bool = False
    ghost: bool = False
    stepped: bool = False

    labels: tuple[str, ...] = ()

    @property
    def is_key(self) -> bool:
        """Whether this position addresses the keymap at all."""
        return self.row >= 0 and self.col >= 0 and not self.decal

    @property
    def is_encoder(self) -> bool:
        return self.encoder_index >= 0

    @property
    def is_l_shaped(self) -> bool:
        return self.width2 > 0 and self.height2 > 0 and (
            self.x2 != 0 or self.y2 != 0 or self.width2 != self.width
            or self.height2 != self.height
        )

    def kmid(self, cols: int) -> int:
        """Index into a flat, row-major keymap of ``cols`` columns."""
        return self.row * cols + self.col

    def centre(self) -> tuple[float, float]:
        """Centre point in KLE units, with any cluster rotation applied."""
        cx, cy = self.x + self.width / 2, self.y + self.height / 2
        if not self.rotation_angle:
            return cx, cy
        angle = math.radians(self.rotation_angle)
        dx, dy = cx - self.rotation_x, cy - self.rotation_y
        return (
            self.rotation_x + dx * math.cos(angle) - dy * math.sin(angle),
            self.rotation_y + dx * math.sin(angle) + dy * math.cos(angle),
        )


@dataclass
class _Cursor:
    """Mutable deserialisation state — KLE's "current key" properties."""

    x: float = 0.0
    y: float = 0.0
    width: float = 1.0
    height: float = 1.0
    x2: float = 0.0
    y2: float = 0.0
    width2: float = 0.0
    height2: float = 0.0
    rotation_angle: float = 0.0
    rotation_x: float = 0.0
    rotation_y: float = 0.0
    decal: bool = False
    ghost: bool = False
    stepped: bool = False


@dataclass(frozen=True)
class Layout:
    """A whole board's geometry, plus the bounds needed to lay it out."""

    keys: tuple[KeyPosition, ...] = ()
    rows: int = 0
    cols: int = 0

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        """``(min_x, min_y, max_x, max_y)`` in KLE units, rotation included."""
        if not self.keys:
            return (0.0, 0.0, 0.0, 0.0)
        xs: list[float] = []
        ys: list[float] = []
        for key in self.keys:
            for corner in _corners(key):
                xs.append(corner[0])
                ys.append(corner[1])
        return (min(xs), min(ys), max(xs), max(ys))

    @property
    def size(self) -> tuple[float, float]:
        min_x, min_y, max_x, max_y = self.bounds
        return (max_x - min_x, max_y - min_y)

    def by_matrix(self) -> dict[tuple[int, int], KeyPosition]:
        return {(key.row, key.col): key for key in self.keys if key.is_key}

    def keys_for_option(self, options: dict[int, int] | None = None) -> list[KeyPosition]:
        """The keys visible for a given set of layout choices."""
        chosen = options or {}
        return [
            key
            for key in self.keys
            if key.is_key
            and (
                key.layout_index < 0
                or chosen.get(key.layout_index, 0) == key.layout_option
            )
        ]


def _corners(key: KeyPosition) -> list[tuple[float, float]]:
    points = [
        (key.x, key.y),
        (key.x + key.width, key.y),
        (key.x + key.width, key.y + key.height),
        (key.x, key.y + key.height),
    ]
    if key.width2 and key.height2:
        points += [
            (key.x + key.x2, key.y + key.y2),
            (key.x + key.x2 + key.width2, key.y + key.y2),
            (key.x + key.x2 + key.width2, key.y + key.y2 + key.height2),
            (key.x + key.x2, key.y + key.y2 + key.height2),
        ]
    if not key.rotation_angle:
        return points
    angle = math.radians(key.rotation_angle)
    cos, sin = math.cos(angle), math.sin(angle)
    rotated = []
    for px, py in points:
        dx, dy = px - key.rotation_x, py - key.rotation_y
        rotated.append(
            (key.rotation_x + dx * cos - dy * sin, key.rotation_y + dx * sin + dy * cos)
        )
    return rotated


def _pair(text: str) -> tuple[int, int] | None:
    """Parse ``"3,4"`` into ``(3, 4)``, or ``None`` when it is not a pair."""
    head, sep, tail = text.partition(",")
    if not sep:
        return None
    try:
        return int(head.strip()), int(tail.strip())
    except ValueError:
        return None


def deserialize(rows: list[Any]) -> Layout:
    """Turn ``layouts.keymap`` into positioned keys.

    Malformed control objects are ignored rather than fatal: a keyboard whose
    definition carries a property this does not model should still draw.
    """
    cursor = _Cursor()
    keys: list[KeyPosition] = []

    for row in rows:
        if not isinstance(row, list):
            # KLE puts board-level metadata in a leading object; it holds no geometry.
            continue

        emitted = 0
        for item in row:
            if isinstance(item, str):
                keys.append(_emit(cursor, item))
                cursor.x += cursor.width
                # Sizing and shape apply to one key only; position carries forward.
                cursor.width = cursor.height = 1.0
                cursor.x2 = cursor.y2 = cursor.width2 = cursor.height2 = 0.0
                cursor.decal = cursor.ghost = cursor.stepped = False
                emitted += 1
            elif isinstance(item, dict):
                _apply(cursor, item)

        cursor.y += 1.0
        # A new row starts at the cluster's left edge, which rotation may have moved.
        cursor.x = cursor.rotation_x

    max_row = max((key.row for key in keys if key.is_key), default=-1)
    max_col = max((key.col for key in keys if key.is_key), default=-1)
    return Layout(keys=tuple(keys), rows=max_row + 1, cols=max_col + 1)


def _apply(cursor: _Cursor, item: dict[str, Any]) -> None:
    def number(key: str) -> float | None:
        value = item.get(key)
        return float(value) if isinstance(value, (int, float)) else None

    # rx and ry move the origin, and KLE resets the cursor onto it.
    moved = False
    if (rx := number("rx")) is not None:
        cursor.rotation_x = rx
        moved = True
    if (ry := number("ry")) is not None:
        cursor.rotation_y = ry
        moved = True
    if moved:
        cursor.x, cursor.y = cursor.rotation_x, cursor.rotation_y

    if (r := number("r")) is not None:
        cursor.rotation_angle = r

    # x and y are relative steps, unlike everything else here.
    if (y := number("y")) is not None:
        cursor.y += y
    if (x := number("x")) is not None:
        cursor.x += x

    for name, attribute in (
        ("w", "width"),
        ("h", "height"),
        ("x2", "x2"),
        ("y2", "y2"),
        ("w2", "width2"),
        ("h2", "height2"),
    ):
        if (value := number(name)) is not None:
            setattr(cursor, attribute, value)

    for name, attribute in (("d", "decal"), ("g", "ghost"), ("l", "stepped")):
        if name in item:
            setattr(cursor, attribute, bool(item[name]))


def _emit(cursor: _Cursor, text: str) -> KeyPosition:
    labels = text.split("\n")

    row = col = -1
    if (pair := _pair(labels[0])) is not None:
        row, col = pair

    encoder_index = encoder_direction = -1
    if len(labels) > 4 and labels[4] == "e":
        # An encoder reuses the first label for "index,direction" rather than a matrix
        # position, so the matrix pair read above is not one.
        if (pair := _pair(labels[0])) is not None:
            encoder_index, encoder_direction = pair
            row = col = -1

    layout_index = layout_option = -1
    if len(labels) > 8 and (pair := _pair(labels[8])) is not None:
        layout_index, layout_option = pair

    return KeyPosition(
        x=cursor.x,
        y=cursor.y,
        width=cursor.width,
        height=cursor.height,
        x2=cursor.x2,
        y2=cursor.y2,
        width2=cursor.width2 or cursor.width,
        height2=cursor.height2 or cursor.height,
        rotation_angle=cursor.rotation_angle,
        rotation_x=cursor.rotation_x,
        rotation_y=cursor.rotation_y,
        row=row,
        col=col,
        encoder_index=encoder_index,
        encoder_direction=encoder_direction,
        layout_index=layout_index,
        layout_option=layout_option,
        decal=cursor.decal,
        ghost=cursor.ghost,
        stepped=cursor.stepped,
        labels=tuple(labels),
    )


def from_definition(payload: dict[str, Any]) -> Layout:
    """Deserialise straight from a decompressed Vial keyboard definition."""
    layouts = payload.get("layouts") or {}
    keymap = layouts.get("keymap") or []
    layout = deserialize(keymap)

    # The matrix block is authoritative — the drawing may legitimately omit positions.
    matrix = payload.get("matrix") or {}
    rows = int(matrix.get("rows") or layout.rows)
    cols = int(matrix.get("cols") or layout.cols)
    return replace(layout, rows=rows, cols=cols)

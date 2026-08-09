# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 白い熊
"""Every settable attribute of the interface, declared once.

This is the 白い熊 house style as data. The 白い熊 Svalboard UI page is generated
from this registry rather than hand-built, so adding a setting means adding a line
here and nothing else — the page, its live preview, and its export/import all follow.

The structure mirrors the family's settings pages: a **group** carries a big bold
heading with a text-wide underline and a full-width hairline above it, a **subgroup**
carries a smaller one, and every element gets the same repeating block of Font,
Weight, Size and Colour, plus Background, Border and Corner where it has a body.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

# -- the palette -----------------------------------------------------------------

BLACK = "#FF000000"
YELLOW = "#FFFFFF00"
YELLOW_DIM = "#FFC8C800"
WHITE = "#FFFFFFFF"

#: Warning, and "no directory set". The family uses this exact red for it, which is
#: not the same as any of its error reds elsewhere.
WARN_RED = "#FFFF5252"

#: The family defines no disabled tone at all, so this one is ours: the accent at
#: 40% alpha, which reads as unavailable without introducing a new hue.
DISABLED = "#66FFFF00"

#: Seeded into the colour picker's recent swatches so the row is never empty.
SWATCH_SEEDS = (BLACK, YELLOW, WHITE, YELLOW_DIM)

#: Shown in the font picker, rendered in each candidate face.
FONT_SAMPLE = "AaIiMmOoQqWw 012 白い熊相撲道 áÁčČďĎéÉěĚíÍňŇóÓřŘšŠťŤúÚůŮýÝžŽ"


class Kind(Enum):
    COLOUR = "colour"
    DIMEN = "dimen"
    FONT = "font"
    WEIGHT = "weight"
    SIZE = "size"
    TOGGLE = "toggle"


@dataclass(frozen=True)
class Setting:
    """One row on the settings page."""

    key: str
    title: str
    kind: Kind
    default: object
    minimum: int = 0
    maximum: int = 100
    unit: str = ""
    description: str = ""

    @property
    def is_slider(self) -> bool:
        return self.kind in (Kind.DIMEN, Kind.WEIGHT, Kind.SIZE)


@dataclass(frozen=True)
class Subgroup:
    title: str
    settings: tuple[Setting, ...] = ()


@dataclass(frozen=True)
class Group:
    """A top-level section: hairline above, big underlined heading, then its rows."""

    title: str
    settings: tuple[Setting, ...] = ()
    subgroups: tuple[Subgroup, ...] = ()
    description: str = ""


# -- shorthand -------------------------------------------------------------------


def colour(key: str, title: str, default: str, description: str = "") -> Setting:
    return Setting(key, title, Kind.COLOUR, default, description=description)


def dimen(
    key: str, title: str, default: int, maximum: int, minimum: int = 0, unit: str = "px"
) -> Setting:
    return Setting(key, title, Kind.DIMEN, default, minimum, maximum, unit)


def font(key: str, title: str = "Font") -> Setting:
    return Setting(key, title, Kind.FONT, "")


def weight(key: str, default: int = 400, title: str = "Weight") -> Setting:
    return Setting(key, title, Kind.WEIGHT, default, 100, 900)


def size(key: str, default: int, title: str = "Size", maximum: int = 48) -> Setting:
    return Setting(key, title, Kind.SIZE, default, 6, maximum, "pt")


def toggle(key: str, title: str, default: bool, description: str = "") -> Setting:
    return Setting(key, title, Kind.TOGGLE, default, description=description)


def _face(prefix: str, title: str, *, default_size: int, default_weight: int = 400,
          default_colour: str = YELLOW) -> Subgroup:
    """The repeating Font / Weight / Size / Colour block."""
    return Subgroup(
        title,
        (
            font(f"{prefix}.font"),
            weight(f"{prefix}.weight", default_weight),
            size(f"{prefix}.size", default_size),
            colour(f"{prefix}.colour", "Colour", default_colour),
        ),
    )


# -- the registry ----------------------------------------------------------------

GROUPS: tuple[Group, ...] = (
    Group(
        "Window",
        settings=(
            colour("window.background", "Background", BLACK),
            colour("window.text", "Text", YELLOW),
            colour("window.dim", "Secondary text", YELLOW_DIM),
            colour("window.warning", "Warning", WARN_RED,
                   "Used for a missing backup directory, and for failures."),
            colour("window.disabled", "Disabled", DISABLED),
        ),
        subgroups=(_face("window.base", "Base text", default_size=11),),
    ),
    Group(
        "Headings",
        description="The section and subgroup headings on pages like this one.",
        subgroups=(
            Subgroup(
                "Section",
                (
                    font("heading.section.font"),
                    weight("heading.section.weight", 700),
                    size("heading.section.size", 20),
                    colour("heading.section.colour", "Colour", YELLOW),
                    dimen("heading.section.rule", "Underline thickness", 3, 12),
                    dimen("heading.section.indent", "Indent", 36, 200),
                    dimen("heading.section.hairline", "Hairline above group", 1, 12),
                ),
            ),
            Subgroup(
                "Subgroup",
                (
                    font("heading.subgroup.font"),
                    weight("heading.subgroup.weight", 700),
                    size("heading.subgroup.size", 17),
                    colour("heading.subgroup.colour", "Colour", YELLOW),
                    dimen("heading.subgroup.rule", "Underline thickness", 2, 12),
                    dimen("heading.subgroup.indent", "Indent", 54, 200),
                ),
            ),
        ),
    ),
    Group(
        "Rows",
        settings=(
            dimen("row.indent", "Indent under a section", 72, 240),
            dimen("row.indent_step", "Extra indent per level", 18, 96),
            dimen("row.padding", "Vertical padding", 5, 40),
            dimen("row.spacing", "Space between rows", 0, 40),
        ),
        subgroups=(
            _face("row.title", "Title", default_size=11),
            _face("row.description", "Description", default_size=9,
                  default_colour=YELLOW_DIM),
        ),
    ),
    Group(
        "Keyboard",
        description="The board drawn on the keymap page.",
        settings=(
            colour("board.background", "Board background", BLACK),
            dimen("board.gap_h", "Horizontal gap between keys", 4, 40),
            dimen("board.gap_v", "Vertical gap between keys", 4, 40),
            dimen("board.unit", "Key size", 56, 160, 16),
        ),
        subgroups=(
            Subgroup(
                "Key body",
                (
                    colour("key.background", "Background", BLACK),
                    colour("key.border", "Border", YELLOW),
                    dimen("key.border_width", "Border width", 2, 8),
                    dimen("key.corner", "Corner radius", 6, 24),
                ),
            ),
            _face("key.label", "Primary label", default_size=11),
            _face("key.sublabel", "Secondary label", default_size=8,
                  default_colour=YELLOW_DIM),
        ),
    ),
    Group(
        "Key states",
        description="Key borders and markers. Keys are never filled with these — a "
        "filled key means text on a coloured wash, which is unreadable.",
        settings=(
            colour("state.selected", "Selected", "#FFFFFF00"),
            colour("state.changed", "Changed, not yet written", "#FF8A8A00"),
            colour("state.empty", "Disabled (KC_NO)", "#FF6A6A00"),
            colour("state.transparent", "Transparent glyph (KC_TRNS)", "#FF8A8A00"),
            colour("state.unset", "Never written", WARN_RED),
            colour("state.layer", "Layer key", "#FF00E5FF"),
            colour("state.modtap", "Mod-tap or layer-tap", "#FF7CFF6B"),
            colour("state.macro", "Macro", "#FFFF9E6B"),
            colour("state.tapdance", "Tap dance", "#FFC28CFF"),
            colour("state.custom", "Svalboard key", "#FFFF6BD6"),
        ),
    ),
    Group(
        "Layer strip",
        settings=(
            colour("layer.active", "Active layer", YELLOW),
            colour("layer.inactive", "Inactive layer", YELLOW_DIM),
            colour("layer.empty", "Empty layer", DISABLED),
            dimen("layer.spacing", "Spacing", 4, 40),
        ),
        subgroups=(_face("layer.label", "Label", default_size=11, default_weight=700),),
    ),
    Group(
        "Keycode picker",
        description="Ctrl and the mouse wheel zoom the picker; the board zooms "
        "separately.",
        settings=(
            dimen("picker.unit", "Key size", 46, 120, 16),
            dimen("picker.spacing", "Spacing", 3, 24),
            dimen("picker.columns", "Maximum keys per row", 24, 40, 4, ""),
        ),
    ),
    Group(
        "Lists and tables",
        settings=(
            colour("list.separator", "Separator", YELLOW),
            dimen("list.separator_thickness", "Separator thickness", 1, 8),
            dimen("list.row_spacing", "Row spacing", 3, 24),
            dimen("list.indent", "Indent", 48, 96),
        ),
    ),
    Group(
        "Dialogs",
        settings=(
            colour("dialog.background", "Background", BLACK),
            colour("dialog.border", "Border", YELLOW),
            dimen("dialog.border_width", "Border width", 2, 8),
            dimen("dialog.corner", "Corner radius", 16, 40),
            dimen("dialog.padding", "Padding", 20, 60),
        ),
        subgroups=(
            _face("dialog.title", "Title", default_size=14, default_weight=700),
            _face("dialog.body", "Body", default_size=11),
        ),
    ),
    Group(
        "Buttons",
        settings=(
            colour("button.background", "Background", BLACK),
            colour("button.border", "Border", YELLOW),
            colour("button.text", "Text", YELLOW),
            colour("button.disabled", "Disabled", DISABLED),
            dimen("button.border_width", "Border width", 2, 8),
            dimen("button.corner", "Corner radius", 999, 999,
                  0, "px — 999 is a pill"),
            dimen("button.padding_h", "Horizontal padding", 20, 60),
            dimen("button.padding_v", "Vertical padding", 7, 40),
        ),
    ),
)


def all_settings() -> dict[str, Setting]:
    """Every setting, keyed. Used for defaults, validation and export."""
    found: dict[str, Setting] = {}
    for group in GROUPS:
        for setting in group.settings:
            found[setting.key] = setting
        for subgroup in group.subgroups:
            for setting in subgroup.settings:
                found[setting.key] = setting
    return found


DEFAULTS: dict[str, object] = {
    key: setting.default for key, setting in all_settings().items()
}

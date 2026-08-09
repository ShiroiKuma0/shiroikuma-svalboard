# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 白い熊
"""The 白い熊 house style: what is settable, and the live values of it."""

from .spec import (
    BLACK,
    DEFAULTS,
    DISABLED,
    FONT_SAMPLE,
    GROUPS,
    SWATCH_SEEDS,
    WARN_RED,
    WHITE,
    YELLOW,
    YELLOW_DIM,
    Group,
    Kind,
    Setting,
    Subgroup,
    all_settings,
)
from .theme import Theme, css_colour

__all__ = [
    "BLACK", "DEFAULTS", "DISABLED", "FONT_SAMPLE", "GROUPS", "SWATCH_SEEDS",
    "WARN_RED", "WHITE", "YELLOW", "YELLOW_DIM", "Group", "Kind", "Setting",
    "Subgroup", "Theme", "all_settings", "css_colour",
]

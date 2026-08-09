# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 白い熊
"""What the keys actually type, for people not on a US layout.

A keycode names a *position*, not a character: ``KC_Y`` is the sixth key of the top
row, and on a Czech or German layout that position types ``z``. So a picker labelled
from the keycode names is only correct for one layout in the world, and everyone else
has to translate in their head.

Rather than transcribe a table of layouts, this reads the ones already installed —
``/usr/share/X11/xkb`` is where every layout on the machine is defined, including
whichever one 白い熊 actually types on — and resolves keysym names through
libxkbcommon, the same library Qt uses. That means the list is whatever the system
has, not whatever was thought worth including, and it stays correct as the system's
data is updated.

Everything here degrades to "no relabelling" rather than failing: a machine without
xkb data, or without libxkbcommon, simply shows the US labels.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

XKB_ROOT = Path("/usr/share/X11/xkb")
SYMBOLS = XKB_ROOT / "symbols"
RULES = XKB_ROOT / "rules" / "evdev.lst"

#: xkb names its keys by physical position; QMK names them by what US layout puts
#: there. This is the correspondence, and it is what lets one be read as the other.
KEY_POSITIONS: dict[str, str] = {
    "TLDE": "KC_GRAVE",
    **{f"AE{index:02d}": name for index, name in enumerate(
        ["KC_1", "KC_2", "KC_3", "KC_4", "KC_5", "KC_6", "KC_7", "KC_8", "KC_9",
         "KC_0", "KC_MINUS", "KC_EQUAL"], start=1)},
    **{f"AD{index:02d}": name for index, name in enumerate(
        ["KC_Q", "KC_W", "KC_E", "KC_R", "KC_T", "KC_Y", "KC_U", "KC_I", "KC_O",
         "KC_P", "KC_LBRACKET", "KC_RBRACKET"], start=1)},
    **{f"AC{index:02d}": name for index, name in enumerate(
        ["KC_A", "KC_S", "KC_D", "KC_F", "KC_G", "KC_H", "KC_J", "KC_K", "KC_L",
         "KC_SCOLON", "KC_QUOTE"], start=1)},
    **{f"AB{index:02d}": name for index, name in enumerate(
        ["KC_Z", "KC_X", "KC_C", "KC_V", "KC_B", "KC_N", "KC_M", "KC_COMMA",
         "KC_DOT", "KC_SLASH"], start=1)},
    "BKSL": "KC_BSLASH",
    "LSGT": "KC_NONUS_BSLASH",
    "SPCE": "KC_SPACE",
}

_KEY_LINE = re.compile(
    r"key\s*<(?P<name>[A-Z0-9]+)>\s*\{(?P<body>[^}]*)\}\s*;", re.S
)
_GROUP = re.compile(r"\[(?P<syms>[^\]]*)\]")
_SECTION = re.compile(r'xkb_symbols\s+"(?P<name>[^"]+)"\s*\{', re.S)
_INCLUDE = re.compile(r'include\s+"(?P<target>[^"]+)"')


@dataclass(frozen=True)
class KeyboardLayout:
    """One installed layout, and what each position types on it."""

    code: str
    name: str
    variant: str = ""

    #: ``KC_Y`` → ``("z", "Z")`` — unshifted and shifted.
    glyphs: dict[str, tuple[str, str]] = None  # type: ignore[assignment]

    @property
    def identifier(self) -> str:
        return f"{self.code}({self.variant})" if self.variant else self.code

    def label(self, keycode_name: str, *, shifted: bool = False) -> str | None:
        """What this layout types for a keycode, or ``None`` if it is unchanged."""
        pair = (self.glyphs or {}).get(keycode_name)
        if not pair:
            return None
        return pair[1] if shifted else pair[0]


# -- keysym resolution -----------------------------------------------------------


@lru_cache(maxsize=1)
def _xkbcommon():
    """libxkbcommon, or ``None``. Qt already depends on it, so it is normally there."""
    path = ctypes.util.find_library("xkbcommon")
    if path is None:
        return None
    try:
        library = ctypes.CDLL(path)
    except OSError:
        return None
    library.xkb_keysym_from_name.restype = ctypes.c_uint32
    library.xkb_keysym_from_name.argtypes = [ctypes.c_char_p, ctypes.c_int]
    library.xkb_keysym_to_utf32.restype = ctypes.c_uint32
    library.xkb_keysym_to_utf32.argtypes = [ctypes.c_uint32]
    return library


@lru_cache(maxsize=4096)
def keysym_to_character(name: str) -> str:
    """Turn a keysym name such as ``ccaron`` into ``č``.

    Dead keys and non-printing symbols come back empty, which is correct: there is
    no character to show for them.
    """
    library = _xkbcommon()
    if library is None or not name:
        return ""
    keysym = library.xkb_keysym_from_name(name.encode("utf-8"), 0)
    if keysym == 0:  # XKB_KEY_NoSymbol
        return ""
    codepoint = library.xkb_keysym_to_utf32(keysym)
    if not codepoint or codepoint < 0x20:
        return ""
    return chr(codepoint)


# -- reading the installed layouts -----------------------------------------------


@lru_cache(maxsize=1)
def available() -> list[tuple[str, str]]:
    """Installed layouts as ``(code, human name)``, alphabetically by name."""
    if not RULES.exists():
        return []
    found: list[tuple[str, str]] = []
    inside = False
    for line in RULES.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("!"):
            inside = line.strip().startswith("! layout")
            continue
        if not inside or not line.strip():
            continue
        code, _, name = line.strip().partition(" ")
        if code and (SYMBOLS / code).exists():
            found.append((code, name.strip()))
    return sorted(found, key=lambda pair: pair[1].lower())


def _section(text: str, wanted: str) -> str | None:
    """The body of one ``xkb_symbols`` section, brace-matched."""
    for match in _SECTION.finditer(text):
        if match.group("name") != wanted:
            continue
        depth, start = 1, match.end()
        for index in range(start, len(text)):
            if text[index] == "{":
                depth += 1
            elif text[index] == "}":
                depth -= 1
                if depth == 0:
                    return text[start:index]
        return text[start:]
    return None


def _read(code: str, variant: str, *, seen: set[str] | None = None) -> dict[str, tuple[str, str]]:
    """Read one layout, following includes.

    Layouts are built by inclusion — a national layout typically pulls in a Latin
    base and overrides a dozen keys — so a parser that ignored includes would report
    almost nothing for most of them.
    """
    seen = seen if seen is not None else set()
    key = f"{code}({variant})"
    if key in seen or len(seen) > 12:
        return {}
    seen.add(key)

    path = SYMBOLS / code
    if not path.exists():
        return {}
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}

    body = _section(text, variant) or _section(text, "basic")
    if body is None:
        return {}

    glyphs: dict[str, tuple[str, str]] = {}
    # Includes first, so the file's own definitions override what it inherits.
    for include in _INCLUDE.finditer(body):
        target = include.group("target")
        base, _, sub = target.partition("(")
        glyphs.update(_read(base.strip(), sub.rstrip(")").strip() or "basic", seen=seen))

    for match in _KEY_LINE.finditer(body):
        keycode = KEY_POSITIONS.get(match.group("name"))
        if keycode is None:
            continue
        groups = _GROUP.findall(match.group("body"))
        if not groups:
            continue
        symbols = [symbol.strip() for symbol in groups[0].split(",")]
        unshifted = keysym_to_character(symbols[0]) if symbols else ""
        shifted = keysym_to_character(symbols[1]) if len(symbols) > 1 else ""
        if unshifted or shifted:
            glyphs[keycode] = (unshifted, shifted or unshifted.upper())
    return glyphs


def load(code: str, variant: str = "") -> KeyboardLayout | None:
    """Read an installed layout, or ``None`` if it cannot be read."""
    glyphs = _read(code, variant or "basic")
    if not glyphs:
        return None
    name = dict(available()).get(code, code)
    return KeyboardLayout(code=code, name=name, variant=variant, glyphs=glyphs)


def differs_from_us(layout: KeyboardLayout) -> dict[str, tuple[str, str]]:
    """Only the positions this layout types differently from a US one.

    Relabelling every key would hide the keycode names for no benefit; the point is
    to show where the two disagree.
    """
    american = load("us")
    if american is None:
        return dict(layout.glyphs or {})
    return {
        keycode: pair
        for keycode, pair in (layout.glyphs or {}).items()
        if american.glyphs.get(keycode) != pair
    }

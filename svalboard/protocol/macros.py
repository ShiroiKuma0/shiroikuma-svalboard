# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 白い熊
#
# The buffer encoding here is QMK's and Vial's, as implemented by vial-qmk and read by
# vial-gui (both GPL-2.0-or-later). It is an interface fact.
"""Macros: a list of actions, stored as one flat buffer of bytes.

Every macro on the keyboard lives in a single buffer, one after another, separated by
zero bytes. So there is no such thing as writing one macro — changing any of them
means rewriting the whole buffer, and a macro that grows pushes every later one along.

Within a macro, a byte of ``0x01`` introduces an action and anything else is literal
text. Two details are worth stating because they look like bugs otherwise:

* **The delay encoding is not a plain number.** A delay is stored as two bytes, each
  biased by one — ``(ms % 255) + 1`` and ``(ms // 255) + 1`` — because a zero byte
  would terminate the macro. It therefore cannot represent a zero delay.
* **Two-byte keycodes are folded.** QMK's own decoder treats a stored value above
  ``0xFF00`` as a high byte that lost its low half, so the same rule is applied here.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Introduces an action. Any other byte is a character of text.
PREFIX = 0x01

TAP = 0x01
DOWN = 0x02
UP = 0x03
DELAY = 0x04
#: Vial's extensions, carrying a two-byte keycode rather than one.
EXT_TAP = 0x05
EXT_DOWN = 0x06
EXT_UP = 0x07

_EXTENDED = {EXT_TAP: TAP, EXT_DOWN: DOWN, EXT_UP: UP}
_KIND_NAMES = {TAP: "tap", DOWN: "down", UP: "up"}

#: A delay is two bytes each biased by one, so this is as long as one can be.
MAX_DELAY = 254 + 254 * 255


@dataclass(frozen=True)
class Action:
    """One step of a macro."""

    #: ``"text"``, ``"tap"``, ``"down"``, ``"up"`` or ``"delay"``.
    kind: str
    #: Set for ``text``.
    text: str = ""
    #: Set for ``tap``, ``down`` and ``up``.
    keycode: int = 0
    #: Set for ``delay``, in milliseconds.
    delay: int = 0

    @property
    def is_text(self) -> bool:
        return self.kind == "text"

    @property
    def is_delay(self) -> bool:
        return self.kind == "delay"


@dataclass
class Macro:
    """One macro: an ordered list of actions."""

    actions: list[Action]

    @property
    def is_empty(self) -> bool:
        return not self.actions

    def text_preview(self) -> str:
        """What to show on a key bound to this macro.

        Its text if it types any, otherwise the keys it presses, otherwise nothing —
        which the caller renders as ``M<n>``.
        """
        text = "".join(action.text for action in self.actions if action.is_text)
        return text.strip()


def encode_delay(milliseconds: int) -> tuple[int, int]:
    value = max(1, min(MAX_DELAY, milliseconds))
    return (value % 255) + 1, (value // 255) + 1


def decode_delay(low: int, high: int) -> int:
    return (low - 1) + (high - 1) * 255


def decode_keycode(value: int) -> int:
    """Undo QMK's folding of a two-byte keycode whose low byte was dropped."""
    if value > 0xFF00:
        return (value & 0xFF) << 8
    return value


def deserialize_macro(data: bytes) -> Macro:
    """Decode one macro's bytes. Malformed input yields what could be read."""
    actions: list[Action] = []
    text: list[str] = []
    index = 0

    def flush_text() -> None:
        if text:
            actions.append(Action("text", text="".join(text)))
            text.clear()

    while index < len(data):
        byte = data[index]
        if byte != PREFIX:
            text.append(chr(byte))
            index += 1
            continue

        if index + 1 >= len(data):
            break
        action = data[index + 1]

        if action in (TAP, DOWN, UP):
            if index + 2 >= len(data):
                break
            flush_text()
            actions.append(Action(_KIND_NAMES[action], keycode=data[index + 2]))
            index += 3
        elif action in _EXTENDED:
            if index + 3 >= len(data):
                break
            flush_text()
            raw = data[index + 2] | (data[index + 3] << 8)
            actions.append(
                Action(_KIND_NAMES[_EXTENDED[action]], keycode=decode_keycode(raw))
            )
            index += 4
        elif action == DELAY:
            if index + 3 >= len(data):
                break
            flush_text()
            actions.append(
                Action("delay", delay=decode_delay(data[index + 2], data[index + 3]))
            )
            index += 4
        else:
            # Not something this understands. Skipping the pair and carrying on
            # recovers the rest of the macro rather than discarding all of it.
            index += 2

    flush_text()
    return Macro(actions)


def serialize_macro(macro: Macro) -> bytes:
    """Encode one macro. Keycodes above a byte use Vial's extended actions."""
    out = bytearray()
    for action in macro.actions:
        if action.is_text:
            # A zero byte would end the macro, so it can never appear in text.
            out.extend(byte for byte in action.text.encode("utf-8") if byte)
        elif action.is_delay:
            low, high = encode_delay(action.delay)
            out.extend((PREFIX, DELAY, low, high))
        else:
            kind = {"tap": (TAP, EXT_TAP), "down": (DOWN, EXT_DOWN), "up": (UP, EXT_UP)}
            basic, extended = kind[action.kind]
            code = action.keycode & 0xFFFF
            if code <= 0xFF:
                out.extend((PREFIX, basic, code))
            else:
                out.extend((PREFIX, extended, code & 0xFF, (code >> 8) & 0xFF))
    return bytes(out)


def deserialize_buffer(data: bytes, count: int) -> list[Macro]:
    """Split the whole buffer into macros, padding to ``count``."""
    macros: list[Macro] = []
    for chunk in data.split(b"\x00"):
        if len(macros) >= count:
            break
        macros.append(deserialize_macro(chunk))
    while len(macros) < count:
        macros.append(Macro([]))
    return macros[:count]


def serialize_buffer(macros: list[Macro], size: int) -> bytes:
    """Render every macro back into one buffer, zero-padded to ``size``.

    Raises when the macros no longer fit, because silently truncating would drop the
    tail of somebody's configuration.
    """
    out = bytearray()
    for macro in macros:
        out.extend(serialize_macro(macro))
        out.append(0x00)
    if len(out) > size:
        raise ValueError(
            f"The macros need {len(out)} bytes but the keyboard has room for {size}."
        )
    return bytes(out).ljust(size, b"\x00")

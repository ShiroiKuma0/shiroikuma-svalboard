# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 白い熊
#
# The command identifiers and wire layouts below are the VIA and Vial protocols as
# implemented by vial-qmk (GPL-2.0-or-later) and as read by vial-gui
# (GPL-2.0-or-later, https://github.com/vial-kb/vial-gui). They are interface facts.
"""Command identifiers and wire layouts for VIA, Vial and the Svalboard extension.

Three things about this protocol repeatedly catch people out, so they are stated here
rather than rediscovered at each call site:

* **Endianness is inconsistent.** Keycodes and buffer offsets are big-endian; the
  keyboard ID, the definition size and every QMK-settings value are little-endian.
* **Buffer transfers chunk at 28 bytes, not 32.** Four bytes of each reply are the
  echoed command, offset and length.
* **Unknown commands are echoed back unchanged.** That is not a quirk to work around —
  it is the documented way to probe for the Svalboard extension.
"""

from __future__ import annotations

from enum import IntEnum

#: Bytes of payload in a buffer-transfer reply, after the 4-byte echoed header.
BUFFER_CHUNK = 28

#: Bytes per block of the compressed keyboard definition.
DEFINITION_BLOCK = 32


class Via(IntEnum):
    """VIA commands, sent as byte 0."""

    GET_PROTOCOL_VERSION = 0x01
    GET_KEYBOARD_VALUE = 0x02
    SET_KEYBOARD_VALUE = 0x03
    GET_KEYCODE = 0x04
    SET_KEYCODE = 0x05
    LIGHTING_SET_VALUE = 0x07
    LIGHTING_GET_VALUE = 0x08
    LIGHTING_SAVE = 0x09
    MACRO_GET_COUNT = 0x0C
    MACRO_GET_BUFFER_SIZE = 0x0D
    MACRO_GET_BUFFER = 0x0E
    MACRO_SET_BUFFER = 0x0F
    GET_LAYER_COUNT = 0x11
    KEYMAP_GET_BUFFER = 0x12
    VIAL_PREFIX = 0xFE


class ViaValue(IntEnum):
    """Sub-identifiers of :attr:`Via.GET_KEYBOARD_VALUE` / ``SET_KEYBOARD_VALUE``."""

    LAYOUT_OPTIONS = 0x02
    SWITCH_MATRIX_STATE = 0x03


class Vial(IntEnum):
    """Vial commands, sent as byte 1 behind the ``0xFE`` prefix."""

    GET_KEYBOARD_ID = 0x00
    GET_SIZE = 0x01
    GET_DEFINITION = 0x02
    GET_ENCODER = 0x03
    SET_ENCODER = 0x04
    GET_UNLOCK_STATUS = 0x05
    UNLOCK_START = 0x06
    UNLOCK_POLL = 0x07
    LOCK = 0x08
    QMK_SETTINGS_QUERY = 0x09
    QMK_SETTINGS_GET = 0x0A
    QMK_SETTINGS_SET = 0x0B
    QMK_SETTINGS_RESET = 0x0C
    DYNAMIC_ENTRY_OP = 0x0D


class Dynamic(IntEnum):
    """Sub-commands of :attr:`Vial.DYNAMIC_ENTRY_OP`, sent as byte 2."""

    GET_NUMBER_OF_ENTRIES = 0x00
    TAP_DANCE_GET = 0x01
    TAP_DANCE_SET = 0x02
    COMBO_GET = 0x03
    COMBO_SET = 0x04
    KEY_OVERRIDE_GET = 0x05
    KEY_OVERRIDE_SET = 0x06
    ALT_REPEAT_KEY_GET = 0x07
    ALT_REPEAT_KEY_SET = 0x08


class Sval(IntEnum):
    """The Svalboard extension, sent as byte 1 behind the ``0xEE`` prefix.

    Four commands is the whole of it. In particular the pointing-device settings —
    DPI, scroll mode, auto-mouse, the Manna-Harbour timer — are *not* here: they live
    in the firmware's persisted struct but are reachable only by pressing ``SV_*``
    keycodes. Their current values can be read back by triggering ``SV_OUTPUT_STATUS``
    and parsing the QMK console, which is what :mod:`svalboard.hid.console` is for.
    """

    PREFIX = 0xEE
    GET_PROTOCOL_VERSION = 0x01
    GET_FIRMWARE_VERSION = 0x02
    LAYER_COLOR_GET = 0x10
    LAYER_COLOR_SET = 0x11


#: Byte 0 of a reply to :attr:`Sval.GET_PROTOCOL_VERSION` on a Svalboard. A board that
#: does not implement the extension echoes the request back instead, so this is the
#: identity check.
SVAL_MAGIC = b"sval"

#: Protocol versions this implementation understands. ``-1`` stands for a board that
#: predates version reporting.
SUPPORTED_VIA_PROTOCOL = (-1, 9)
SUPPORTED_VIAL_PROTOCOL = (-1, 0, 1, 2, 3, 4, 5, 6)

#: Vial protocol versions at which each feature appeared.
VIAL_PROTOCOL_ADVANCED_MACROS = 2
VIAL_PROTOCOL_MATRIX_TESTER = 3
VIAL_PROTOCOL_DYNAMIC = 4
VIAL_PROTOCOL_QMK_SETTINGS = 4
VIAL_PROTOCOL_EXT_MACROS = 5
VIAL_PROTOCOL_KEY_OVERRIDE = 5

# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 白い熊
"""Discovery of the keyboard's HID interfaces, straight from sysfs.

A Vial keyboard presents several HID interfaces and only one of them — QMK's raw HID,
usage page 0xFF60 / usage 0x61 — accepts protocol commands. The Svalboard also exposes
QMK's console on 0xFF31 / 0x74, which is the only way to read back its pointing-device
state. Neither has a stable ``/dev/hidraw*`` number, so both are resolved by usage page
every time rather than remembered.

Everything here reads sysfs only, so it works without the udev rule and without opening
the device. That matters: it lets the application tell "no keyboard attached" apart from
"keyboard attached but not permitted", which are very different things to report.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

HIDRAW_CLASS = Path("/sys/class/hidraw")

RAW_HID_USAGE_PAGE = 0xFF60
RAW_HID_USAGE = 0x61

CONSOLE_USAGE_PAGE = 0xFF31
CONSOLE_USAGE = 0x74

#: Vial brands its keyboards by USB serial rather than by product ID, so that
#: self-built and variant firmware is still recognised. Matching this instead of
#: 0x303A/0x4044 is deliberate.
VIAL_SERIAL_MAGIC = "vial:f64c2b3c"


@dataclass(frozen=True)
class HidInterface:
    """One ``/dev/hidraw*`` node and the facts sysfs knows about it."""

    node: Path
    sysfs: Path
    bus: int
    vendor_id: int
    product_id: int
    serial: str
    name: str
    usage_page: int | None
    usage: int | None

    @property
    def is_raw_hid(self) -> bool:
        return self.usage_page == RAW_HID_USAGE_PAGE and self.usage == RAW_HID_USAGE

    @property
    def is_console(self) -> bool:
        return self.usage_page == CONSOLE_USAGE_PAGE and self.usage == CONSOLE_USAGE

    @property
    def is_vial(self) -> bool:
        return VIAL_SERIAL_MAGIC in self.serial

    def describe(self) -> str:
        page = "?" if self.usage_page is None else f"0x{self.usage_page:04X}"
        usage = "?" if self.usage is None else f"0x{self.usage:02X}"
        return (
            f"{self.node} {self.vendor_id:04x}:{self.product_id:04x} "
            f"usage {page}/{usage} — {self.name}"
        )


def _parse_uevent(text: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in text.splitlines():
        key, _, value = line.partition("=")
        if value:
            fields[key] = value
    return fields


def _first_usage(descriptor: bytes) -> tuple[int | None, int | None]:
    """Return the usage page and usage that open a HID report descriptor.

    Walks short items until the first Main item (the application collection), tracking
    the last Global Usage Page and Local Usage seen. That is enough to classify an
    interface, and it is more honest than matching the descriptor's leading bytes —
    a firmware is free to emit the same items in a different order.
    """
    usage_page: int | None = None
    usage: int | None = None
    offset = 0
    size_of = (0, 1, 2, 4)

    while offset < len(descriptor):
        prefix = descriptor[offset]
        if prefix == 0xFE:  # long item: 0xFE, bDataSize, bLongItemTag, data…
            if offset + 1 >= len(descriptor):
                break
            offset += 3 + descriptor[offset + 1]
            continue

        length = size_of[prefix & 0x03]
        tag, item_type = prefix >> 4, (prefix >> 2) & 0x03
        data = descriptor[offset + 1 : offset + 1 + length]
        if len(data) < length:
            break
        value = int.from_bytes(data, "little") if data else 0

        if item_type == 1 and tag == 0x0:  # Global / Usage Page
            usage_page = value
        elif item_type == 2 and tag == 0x0:  # Local / Usage
            usage = value
        elif item_type == 0:  # Main — the collection opens, locals are consumed
            break

        offset += 1 + length

    return usage_page, usage


def _read_interface(entry: Path) -> HidInterface | None:
    device = entry / "device"
    try:
        uevent = _parse_uevent((device / "uevent").read_text())
        descriptor = (device / "report_descriptor").read_bytes()
    except OSError:
        # Races with unplug, and interfaces the kernel has not finished setting up.
        return None

    hid_id = uevent.get("HID_ID", "")
    try:
        bus_s, vendor_s, product_s = hid_id.split(":")
        bus, vendor_id, product_id = int(bus_s, 16), int(vendor_s, 16), int(product_s, 16)
    except ValueError:
        return None

    usage_page, usage = _first_usage(descriptor)
    return HidInterface(
        node=Path("/dev") / entry.name,
        sysfs=entry.resolve(),
        bus=bus,
        vendor_id=vendor_id & 0xFFFF,
        product_id=product_id & 0xFFFF,
        serial=uevent.get("HID_UNIQ", ""),
        name=uevent.get("HID_NAME", ""),
        usage_page=usage_page,
        usage=usage,
    )


def iter_interfaces() -> list[HidInterface]:
    """Every HID interface the kernel currently exposes, in node order."""
    if not HIDRAW_CLASS.is_dir():
        return []
    found = [
        interface
        for entry in sorted(HIDRAW_CLASS.iterdir(), key=lambda p: p.name)
        if (interface := _read_interface(entry)) is not None
    ]
    return found


def find_raw_hid(serial_magic: str = VIAL_SERIAL_MAGIC) -> list[HidInterface]:
    """Vial raw-HID interfaces, newest kernel node last.

    Passing an empty ``serial_magic`` accepts any QMK raw-HID device, which is useful
    when talking to a board running self-built firmware with a different serial.
    """
    return [
        interface
        for interface in iter_interfaces()
        if interface.is_raw_hid and serial_magic in interface.serial
    ]


def find_console(serial_magic: str = VIAL_SERIAL_MAGIC) -> list[HidInterface]:
    """QMK console interfaces, used to read the Svalboard's pointing-device status."""
    return [
        interface
        for interface in iter_interfaces()
        if interface.is_console and serial_magic in interface.serial
    ]


def access_problem(interface: HidInterface) -> str | None:
    """Why the node cannot be opened, or ``None`` if it can.

    Kept separate from opening so the UI can explain a missing udev rule instead of
    reporting a bare permission error, which is the single most common way a native
    Vial tool fails on a fresh system.
    """
    node = interface.node
    if not node.exists():
        return f"{node} has gone away."
    if os.access(node, os.R_OK | os.W_OK):
        return None
    return (
        f"No permission to open {node}. The udev rule is probably missing — install "
        f"packaging/59-svalboard.rules into /etc/udev/rules.d/ and replug the keyboard."
    )

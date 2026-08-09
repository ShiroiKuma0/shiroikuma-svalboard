# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 白い熊
"""Reading the QMK console, which is how the Svalboard's live state can be seen.

The pointing-device settings — DPI, which side scrolls, the auto-mouse layer and its
timer — are not on the wire. They live in the firmware's persisted structure but only
the layer colours are exposed over the ``0xEE`` channel, so no host program can query
them. What the firmware *does* offer is ``SV_OUTPUT_STATUS``, a keycode that prints the
current state to QMK's debug console on a separate HID interface.

So this reads that interface. It is passive: the host cannot make the firmware print,
because only a physical key press executes a keycode. The application finds where
``SV_OUTPUT_STATUS`` is bound and asks for it to be pressed.

Nothing else reads this today — neither the web configurator nor Vial — which makes it
the one place a Svalboard's live pointing state can be seen at all.
"""

from __future__ import annotations

import errno
import os
import re
import select
from dataclasses import dataclass, field

from .enumerate import HidInterface, find_console

#: The console reports one line at a time in 32-byte reports, zero-padded.
REPORT_LENGTH = 32


@dataclass
class Status:
    """Whatever could be parsed out of a status dump."""

    left_dpi: int | None = None
    right_dpi: int | None = None
    left_scroll: bool | None = None
    right_scroll: bool | None = None
    auto_mouse: bool | None = None
    mouse_timer: int | None = None
    achordion: bool | None = None
    raw: list[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not self.raw

    def summary(self) -> str:
        parts = []
        if self.left_dpi is not None:
            parts.append(f"left DPI {self.left_dpi}")
        if self.right_dpi is not None:
            parts.append(f"right DPI {self.right_dpi}")
        for value, name in ((self.left_scroll, "left scroll"),
                            (self.right_scroll, "right scroll")):
            if value is not None:
                parts.append(f"{name} {'on' if value else 'off'}")
        if self.auto_mouse is not None:
            parts.append(f"auto-mouse {'on' if self.auto_mouse else 'off'}")
        if self.mouse_timer is not None:
            parts.append(f"mouse timer {self.mouse_timer}")
        if self.achordion is not None:
            parts.append(f"achordion {'on' if self.achordion else 'off'}")
        return ", ".join(parts)


#: Patterns are deliberately loose. The firmware's wording is not a stable interface,
#: so anything unrecognised is kept as raw text rather than discarded.
_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("left_dpi", re.compile(r"left[^0-9]*dpi[^0-9]*(\d+)", re.I)),
    ("right_dpi", re.compile(r"right[^0-9]*dpi[^0-9]*(\d+)", re.I)),
    ("mouse_timer", re.compile(r"(?:mh|mouse)[^0-9]*tim\w*[^0-9]*(\d+)", re.I)),
)

_FLAGS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("left_scroll", re.compile(r"left[ _]*scroll\D*([01]|true|false|on|off)", re.I)),
    ("right_scroll", re.compile(r"right[ _]*scroll\D*([01]|true|false|on|off)", re.I)),
    ("auto_mouse", re.compile(r"auto[ _]*mouse\D*([01]|true|false|on|off)", re.I)),
    ("achordion", re.compile(r"achordion\D*([01]|true|false|on|off)", re.I)),
)


def _truthy(text: str) -> bool:
    return text.strip().lower() in ("1", "true", "on", "yes")


def parse(lines: list[str]) -> Status:
    status = Status(raw=list(lines))
    joined = "\n".join(lines)
    for name, pattern in _PATTERNS:
        match = pattern.search(joined)
        if match:
            setattr(status, name, int(match.group(1)))
    for name, pattern in _FLAGS:
        match = pattern.search(joined)
        if match:
            setattr(status, name, _truthy(match.group(1)))
    return status


class ConsoleReader:
    """Collects console output for a while, then parses it."""

    def __init__(self, interface: HidInterface | None = None) -> None:
        if interface is None:
            found = find_console()
            interface = found[0] if found else None
        self.interface = interface
        self._fd: int | None = None

    @property
    def available(self) -> bool:
        return self.interface is not None

    def open(self) -> None:
        if self.interface is None:
            raise OSError("This keyboard exposes no QMK console interface.")
        if self._fd is None:
            self._fd = os.open(self.interface.node, os.O_RDONLY | os.O_NONBLOCK)

    def close(self) -> None:
        if self._fd is not None:
            try:
                os.close(self._fd)
            finally:
                self._fd = None

    def __enter__(self) -> ConsoleReader:
        self.open()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def drain(self) -> None:
        """Discard anything already buffered, so a read reflects this moment."""
        while self._read_report(0.0) is not None:
            pass

    def _read_report(self, timeout: float) -> bytes | None:
        if self._fd is None:
            return None
        poller = select.poll()
        poller.register(self._fd, select.POLLIN)
        if not poller.poll(timeout * 1000.0):
            return None
        try:
            return os.read(self._fd, REPORT_LENGTH)
        except OSError as exc:
            if exc.errno in (errno.EAGAIN, errno.EWOULDBLOCK):
                return None
            raise

    def collect(self, *, seconds: float = 3.0, quiet: float = 0.4) -> list[str]:
        """Gather console text, stopping once it has been quiet for a moment."""
        import time

        text = ""
        deadline = time.monotonic() + seconds
        last = None
        while time.monotonic() < deadline:
            report = self._read_report(0.1)
            if report:
                text += report.split(b"\x00")[0].decode("utf-8", "replace")
                last = time.monotonic()
            elif last is not None and time.monotonic() - last > quiet:
                break
        return [line for line in text.splitlines() if line.strip()]

    def read_status(self, *, seconds: float = 3.0) -> Status:
        return parse(self.collect(seconds=seconds))

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

    #: The firmware's own identity line, e.g.
    #: ``svalboard/trackball/pmw3389/right:vial @ v24.10.24``.
    board: str | None = None
    firmware: str | None = None

    #: The firmware calls these CPI, though the keycodes that change them are named
    #: SV_LEFT_DPI_INC and so on. Its wording wins here.
    left_cpi: int | None = None
    right_cpi: int | None = None
    left_scroll: bool | None = None
    right_scroll: bool | None = None
    achordion: bool | None = None
    mh_timer: int | None = None

    #: Console lines that are not key-logger chatter. A live keyboard produces a
    #: great deal of that, and showing it back as "what was read" is useless.
    raw: list[str] = field(default_factory=list)
    #: How many key-logger lines were discarded, which is worth reporting: it shows
    #: the console is alive even when no status arrived.
    keylog_lines: int = 0

    @property
    def is_empty(self) -> bool:
        return not self.raw

    @property
    def recognised(self) -> bool:
        """Whether anything beyond raw text was understood."""
        return any(
            value is not None
            for value in (
                self.board, self.firmware, self.left_cpi, self.right_cpi,
                self.left_scroll, self.right_scroll, self.achordion, self.mh_timer,
            )
        )

    def summary(self) -> str:
        parts = []
        if self.firmware:
            parts.append(f"firmware {self.firmware}")
        for cpi, scroll, side in (
            (self.left_cpi, self.left_scroll, "left"),
            (self.right_cpi, self.right_scroll, "right"),
        ):
            bits = []
            if cpi is not None:
                bits.append(f"{cpi} CPI")
            if scroll is not None:
                bits.append("scrolling" if scroll else "pointing")
            if bits:
                parts.append(f"{side} {', '.join(bits)}")
        if self.achordion is not None:
            parts.append(f"achordion {'on' if self.achordion else 'off'}")
        if self.mh_timer is not None:
            parts.append(f"mouse-key timer {self.mh_timer} ms")
        return " · ".join(parts)


#: QMK's key logger shares the console and chatters whenever a key moves. It is not
#: part of a status dump and would otherwise be mistaken for one arriving.
_KEYLOG = re.compile(r"^KL:\s", re.I)

_IDENTITY = re.compile(r"^(\S+)\s+@\s+(\S+)\s*$")
_SCROLL = re.compile(r"scroll\s*:?\s*(yes|no|on|off|true|false|[01])", re.I)
_CPI = re.compile(r"cpi\s*:?\s*(\d+)", re.I)
_ACHORDION = re.compile(r"achordion\s*:?\s*(yes|no|on|off|true|false|[01])", re.I)
_MH_TIMER = re.compile(r"m[hH]\s*keys?\s*timer\s*:?\s*(\d+)", re.I)


def _truthy(text: str) -> bool:
    return text.strip().lower() in ("1", "true", "on", "yes")


def is_keylog(line: str) -> bool:
    return bool(_KEYLOG.match(line.strip()))


def parse(lines: list[str]) -> Status:
    """Read a status dump.

    The wording is the firmware's, taken from a real dump rather than guessed::

        svalboard/trackball/pmw3389/right:vial @ v24.10.24
        Left Ptr: Scroll yes, cpi: 2400, Right Ptr: Scroll no, cpi: 1600
        Achordion: no, MH Keys Timer: 500

    Both pointers share a line, so it is split on "Right Ptr" before the scroll and
    CPI values are read — otherwise the first match would claim both.
    """
    kept = [line for line in lines if not is_keylog(line)]
    status = Status(raw=kept, keylog_lines=len(lines) - len(kept))
    for line in kept:

        identity = _IDENTITY.match(line.strip())
        if identity and "/" in identity.group(1):
            status.board = identity.group(1)
            status.firmware = identity.group(2)
            continue

        if re.search(r"ptr", line, re.I):
            left, _, right = line.partition("Right Ptr")
            for segment, cpi_name, scroll_name in (
                (left, "left_cpi", "left_scroll"),
                (right, "right_cpi", "right_scroll"),
            ):
                if not segment:
                    continue
                cpi = _CPI.search(segment)
                if cpi:
                    setattr(status, cpi_name, int(cpi.group(1)))
                scroll = _SCROLL.search(segment)
                if scroll:
                    setattr(status, scroll_name, _truthy(scroll.group(1)))

        achordion = _ACHORDION.search(line)
        if achordion:
            status.achordion = _truthy(achordion.group(1))
        timer = _MH_TIMER.search(line)
        if timer:
            status.mh_timer = int(timer.group(1))

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

    def collect(self, *, seconds: float = 20.0, quiet: float = 1.0) -> list[str]:
        """Gather console text until a status dump arrives or the window closes.

        Stopping at the first quiet gap does not work here: QMK's key logger shares
        this console and chatters as soon as a key moves, so the first thing to
        arrive is the press itself. Waiting for quiet after *that* ended the capture
        before the status had been printed. So the window only closes early once
        something recognisable has actually been read.
        """
        import time

        text = ""
        deadline = time.monotonic() + seconds
        settled = None
        while time.monotonic() < deadline:
            report = self._read_report(0.1)
            if report:
                text += report.split(b"\x00")[0].decode("utf-8", "replace")
                settled = None
                continue
            lines = [line for line in text.splitlines() if line.strip()]
            if parse(lines).recognised:
                if settled is None:
                    settled = time.monotonic()
                elif time.monotonic() - settled > quiet:
                    break
        return [line for line in text.splitlines() if line.strip()]

    def read_status(self, *, seconds: float = 20.0) -> Status:
        return parse(self.collect(seconds=seconds))

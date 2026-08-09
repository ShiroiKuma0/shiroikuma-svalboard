# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 白い熊
"""Raw-HID transport: one 32-byte request, one 32-byte reply, one at a time.

The VIA/Vial protocol carries no sequence numbers — a reply is simply the next report
that arrives. The only way to keep that honest is to allow exactly one exchange in
flight, so every method here funnels through a single lock. KeyBard does not do this,
and a dropped report deadlocks it; a timeout here surfaces as an exception instead.

On Linux, hidraw wants the report ID as the first byte of every write even when the
device declares no numbered reports, so a request goes out as 33 bytes: ``0x00`` and
then the 32-byte payload. Replies come back as the bare 32 bytes.
"""

from __future__ import annotations

import errno
import os
import select
import threading
import time
from collections.abc import Callable, Iterable

from .enumerate import HidInterface, access_problem, find_raw_hid

#: Every raw-HID report is exactly this long, in both directions. The firmware drops
#: anything else on the floor: ``if (length != VIAL_RAW_EPSIZE) return;``
REPORT_LENGTH = 32

DEFAULT_TIMEOUT = 0.5
DEFAULT_RETRIES = 3

#: Called with (request, response) after every completed exchange. Used to record
#: transcripts so the interface can be developed and tested with no keyboard attached.
ExchangeHook = Callable[[bytes, bytes], None]

#: Decides whether an arriving report answers the request, for the rare commands that
#: share the interface with chatter. Returning False makes the transport keep reading
#: until the deadline rather than accepting the wrong report.
Validator = Callable[[bytes], bool]


class TransportError(Exception):
    """Any failure to exchange a report with the keyboard."""


class DeviceNotPermitted(TransportError):
    """The node exists but cannot be opened — almost always a missing udev rule."""


class DeviceGone(TransportError):
    """The keyboard was unplugged, or the node vanished mid-exchange."""


class ExchangeTimeout(TransportError):
    """The keyboard did not answer within the deadline, after every retry."""


class RawHidTransport:
    """A single open raw-HID interface.

    Use it as a context manager, or call :meth:`open` and :meth:`close` explicitly.
    Instances are safe to share between threads; exchanges serialise.
    """

    def __init__(
        self,
        interface: HidInterface,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        retries: int = DEFAULT_RETRIES,
        on_exchange: ExchangeHook | None = None,
    ) -> None:
        self.interface = interface
        self.timeout = timeout
        self.retries = retries
        self.on_exchange = on_exchange
        self._fd: int | None = None
        self._lock = threading.RLock()

    # -- lifecycle ---------------------------------------------------------------

    @property
    def is_open(self) -> bool:
        return self._fd is not None

    def open(self) -> None:
        with self._lock:
            if self._fd is not None:
                return
            problem = access_problem(self.interface)
            if problem is not None:
                if self.interface.node.exists():
                    raise DeviceNotPermitted(problem)
                raise DeviceGone(problem)
            try:
                self._fd = os.open(self.interface.node, os.O_RDWR | os.O_NONBLOCK)
            except OSError as exc:
                raise self._translate(exc, "open") from exc

    def close(self) -> None:
        with self._lock:
            if self._fd is None:
                return
            try:
                os.close(self._fd)
            except OSError:
                pass  # Closing a vanished node is not a failure worth reporting.
            finally:
                self._fd = None

    def __enter__(self) -> RawHidTransport:
        self.open()
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()

    # -- exchange ----------------------------------------------------------------

    def exchange(
        self,
        payload: Iterable[int] | bytes,
        *,
        validate: Validator | None = None,
        timeout: float | None = None,
        retries: int | None = None,
    ) -> bytes:
        """Send one report and return the reply, padding the request to 32 bytes."""
        request = self._frame(payload)
        deadline = self.timeout if timeout is None else timeout
        attempts = (self.retries if retries is None else retries) + 1

        with self._lock:
            if self._fd is None:
                self.open()

            last: TransportError | None = None
            for attempt in range(attempts):
                try:
                    self._write(request)
                    response = self._read_matching(validate, deadline)
                except (ExchangeTimeout, DeviceGone) as exc:
                    # The RP2040 stalls while it commits EEPROM, so a lost round trip
                    # is expected rather than exceptional. Retry before giving up.
                    last = exc
                    if isinstance(exc, DeviceGone) or attempt == attempts - 1:
                        raise
                    continue
                if self.on_exchange is not None:
                    self.on_exchange(request, response)
                return response

            raise last if last is not None else ExchangeTimeout("No attempt was made.")

    # -- internals ---------------------------------------------------------------

    @staticmethod
    def _frame(payload: Iterable[int] | bytes) -> bytes:
        data = bytes(payload)
        if len(data) > REPORT_LENGTH:
            raise ValueError(
                f"A raw-HID request is at most {REPORT_LENGTH} bytes; got {len(data)}."
            )
        return data.ljust(REPORT_LENGTH, b"\x00")

    def _write(self, request: bytes) -> None:
        assert self._fd is not None
        # The leading 0x00 is the report ID hidraw insists on, and is stripped before
        # the bytes reach the wire.
        framed = b"\x00" + request
        try:
            written = os.write(self._fd, framed)
        except OSError as exc:
            raise self._translate(exc, "write") from exc
        if written != len(framed):
            raise TransportError(
                f"Short write to {self.interface.node}: {written} of {len(framed)} bytes."
            )

    def _read_matching(self, validate: Validator | None, deadline: float) -> bytes:
        assert self._fd is not None
        poller = select.poll()
        poller.register(self._fd, select.POLLIN)
        remaining = deadline

        while remaining > 0:
            started = time.monotonic()
            if not poller.poll(remaining * 1000.0):
                break
            remaining -= time.monotonic() - started

            try:
                response = os.read(self._fd, REPORT_LENGTH)
            except OSError as exc:
                if exc.errno in (errno.EAGAIN, errno.EWOULDBLOCK):
                    continue
                raise self._translate(exc, "read") from exc

            if not response:
                continue
            response = response.ljust(REPORT_LENGTH, b"\x00")
            if validate is None or validate(response):
                return response
            # Not ours — keep waiting rather than returning someone else's report.

        raise ExchangeTimeout(
            f"{self.interface.node} did not answer within {deadline:.2f} s."
        )

    def _translate(self, exc: OSError, action: str) -> TransportError:
        node = self.interface.node
        if exc.errno in (errno.ENODEV, errno.ENOENT, errno.ENXIO, errno.EIO):
            return DeviceGone(f"The keyboard was disconnected during {action} ({node}).")
        if exc.errno in (errno.EACCES, errno.EPERM):
            return DeviceNotPermitted(
                f"No permission to {action} {node}. The udev rule is probably missing — "
                f"install packaging/59-svalboard.rules into /etc/udev/rules.d/ and "
                f"replug the keyboard."
            )
        return TransportError(f"Failed to {action} {node}: {exc.strerror}.")


def open_keyboard(
    *,
    timeout: float = DEFAULT_TIMEOUT,
    retries: int = DEFAULT_RETRIES,
    on_exchange: ExchangeHook | None = None,
) -> RawHidTransport:
    """Open the one attached Svalboard, or explain precisely why that is not possible."""
    interfaces = find_raw_hid()
    if not interfaces:
        raise DeviceGone(
            "No Vial keyboard found. Check that the Svalboard is plugged in and that "
            "its raw-HID interface (usage page 0xFF60) is present."
        )
    if len(interfaces) > 1:
        nodes = ", ".join(str(i.node) for i in interfaces)
        raise TransportError(f"More than one Vial keyboard is attached: {nodes}.")
    transport = RawHidTransport(
        interfaces[0], timeout=timeout, retries=retries, on_exchange=on_exchange
    )
    transport.open()
    return transport

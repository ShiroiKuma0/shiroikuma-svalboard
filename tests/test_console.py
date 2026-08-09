# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 白い熊
"""Parsing the Svalboard's console status dump.

Every line here is verbatim from 白い熊's keyboard. The first attempt at this parser
was written against a guess at the wording and matched none of it — the firmware says
"cpi" rather than "dpi", answers "yes"/"no" rather than 0/1, and puts both pointers on
one line — so these cases exist to keep it honest.
"""

from __future__ import annotations

from svalboard.hid.console import is_keylog, parse

REAL_DUMP = [
    "svalboard/trackball/pmw3389/right:vial @ v24.10.24",
    "Left Ptr: Scroll yes, cpi: 2400, Right Ptr: Scroll no, cpi: 1600",
    "Achordion: no, MH Keys Timer: 500",
]

KEYLOG = "KL: kc: 0x5200, col:  4, row:  0, pressed: 1, time: 22857, int: 0, count: 0"


def test_the_real_dump_parses() -> None:
    status = parse(REAL_DUMP)
    assert status.board == "svalboard/trackball/pmw3389/right:vial"
    assert status.firmware == "v24.10.24"
    assert status.left_cpi == 2400
    assert status.right_cpi == 1600
    assert status.left_scroll is True
    assert status.right_scroll is False
    assert status.achordion is False
    assert status.mh_timer == 500
    assert status.recognised


def test_the_two_pointers_do_not_bleed_into_each_other() -> None:
    """Both share one line, so the first match must not claim both."""
    status = parse(["Left Ptr: Scroll yes, cpi: 2400, Right Ptr: Scroll no, cpi: 1600"])
    assert (status.left_cpi, status.right_cpi) == (2400, 1600)
    assert (status.left_scroll, status.right_scroll) == (True, False)


def test_the_key_logger_is_not_a_status_dump() -> None:
    """QMK's key logger shares this console and chatters on every press."""
    assert is_keylog(KEYLOG)
    assert not parse([KEYLOG]).recognised


def test_a_dump_amongst_key_logger_noise_still_parses() -> None:
    status = parse([KEYLOG, *REAL_DUMP, KEYLOG])
    assert status.left_cpi == 2400
    assert status.firmware == "v24.10.24"


def test_yes_and_no_are_understood() -> None:
    assert parse(["Achordion: yes"]).achordion is True
    assert parse(["Achordion: no"]).achordion is False


def test_nothing_recognisable_is_reported_as_such() -> None:
    status = parse(["some unrelated firmware chatter"])
    assert not status.recognised
    assert status.raw == ["some unrelated firmware chatter"]


def test_the_summary_reads_as_prose() -> None:
    summary = parse(REAL_DUMP).summary()
    assert "2400 CPI" in summary
    assert "scrolling" in summary and "pointing" in summary
    assert "500 ms" in summary


def test_key_logger_chatter_is_separated_from_the_dump() -> None:
    """A live keyboard floods this console; it must not be reported as content."""
    status = parse([KEYLOG] * 95)
    assert status.raw == []
    assert status.keylog_lines == 95
    assert not status.recognised


def test_a_dump_is_kept_and_the_chatter_counted() -> None:
    status = parse([KEYLOG, *REAL_DUMP, KEYLOG, KEYLOG])
    assert status.raw == REAL_DUMP
    assert status.keylog_lines == 3
    assert status.recognised

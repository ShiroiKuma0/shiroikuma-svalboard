# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 白い熊
"""Ctrl+wheel zoom, on the board and on the picker separately."""

from __future__ import annotations

import os
import tempfile

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

QtCore = pytest.importorskip("PyQt6.QtCore")
QtGui = pytest.importorskip("PyQt6.QtGui")
QtWidgets = pytest.importorskip("PyQt6.QtWidgets")

from PyQt6.QtCore import QPoint, QSettings, Qt  # noqa: E402
from PyQt6.QtGui import QWheelEvent  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from svalboard.protocol.keycodes import KeycodeSet  # noqa: E402
from svalboard.protocol.kle import from_definition  # noqa: E402
from svalboard.ui.theme import Theme  # noqa: E402
from svalboard.ui.widgets.keyboard_canvas import KeyboardCanvas  # noqa: E402
from svalboard.ui.widgets.keycode_picker import KeycodePicker  # noqa: E402

DEFINITION = {
    "matrix": {"rows": 2, "cols": 3},
    "layouts": {"keymap": [["0,0", "0,1", "0,2"], ["1,0", "1,1", "1,2"]]},
}


@pytest.fixture(scope="session")
def application() -> QApplication:
    return QApplication.instance() or QApplication([])


@pytest.fixture
def theme(application: QApplication) -> Theme:
    return Theme(QSettings(tempfile.mktemp(suffix=".ini"), QSettings.Format.IniFormat))


def spin(widget, notches: float, *, ctrl: bool = True) -> None:
    """Send one Ctrl+wheel gesture at the widget's centre."""
    centre = widget.rect().center().toPointF()
    event = QWheelEvent(
        centre,
        centre,
        QPoint(0, 0),
        QPoint(0, int(120 * notches)),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.ControlModifier if ctrl else Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    QApplication.sendEvent(widget, event)


# -- the board -------------------------------------------------------------------


@pytest.fixture
def canvas(theme: Theme) -> KeyboardCanvas:
    widget = KeyboardCanvas(theme)
    widget.resize(800, 400)
    widget.set_board(from_definition(DEFINITION), KeycodeSet(layers=4))
    widget.set_layer([0] * 6)
    return widget


def test_the_board_starts_fitted(canvas: KeyboardCanvas) -> None:
    assert canvas.zoom() is None


def test_ctrl_wheel_zooms_the_board(canvas: KeyboardCanvas) -> None:
    spin(canvas, +1)
    assert canvas.zoom() is not None
    assert canvas.zoom() > 0


def test_zooming_continues_from_what_is_on_screen(canvas: KeyboardCanvas) -> None:
    """The first notch must not jump; it starts from the fitted scale."""
    fitted = canvas.effective_scale()
    spin(canvas, +1)
    assert canvas.zoom() == pytest.approx(fitted * canvas.ZOOM_STEP, rel=1e-6)


def test_the_board_zoom_is_clamped(canvas: KeyboardCanvas) -> None:
    spin(canvas, +200)
    assert canvas.zoom() == pytest.approx(canvas.ZOOM_MAX)
    spin(canvas, -400)
    assert canvas.zoom() == pytest.approx(canvas.ZOOM_MIN)


def test_a_plain_wheel_does_not_zoom_the_board(canvas: KeyboardCanvas) -> None:
    """Without Ctrl the gesture belongs to the scroll area, not the canvas."""
    spin(canvas, +3, ctrl=False)
    assert canvas.zoom() is None


def test_fit_returns_to_following_the_window(canvas: KeyboardCanvas) -> None:
    spin(canvas, +2)
    assert canvas.zoom() is not None
    canvas.zoom_to_fit()
    assert canvas.zoom() is None


def test_zooming_in_asks_for_room_so_the_view_can_pan(canvas: KeyboardCanvas) -> None:
    fitted_minimum = canvas.minimumSize().width()
    canvas.set_zoom(4.0)
    assert canvas.minimumSize().width() > fitted_minimum


# -- the picker ------------------------------------------------------------------


@pytest.fixture
def picker(theme: Theme) -> KeycodePicker:
    widget = KeycodePicker(theme)
    widget.resize(900, 400)
    widget.set_keycodes(KeycodeSet(layers=4, macros=4, tap_dances=4), [])
    return widget


def test_the_picker_starts_unzoomed(picker: KeycodePicker) -> None:
    assert picker.zoom() == pytest.approx(1.0)


def test_ctrl_wheel_zooms_the_picker(picker: KeycodePicker) -> None:
    spin(picker, +2)
    assert picker.zoom() > 1.0


def test_the_picker_zoom_is_clamped(picker: KeycodePicker) -> None:
    spin(picker, +200)
    assert picker.zoom() == pytest.approx(picker.ZOOM_MAX)
    spin(picker, -400)
    assert picker.zoom() == pytest.approx(picker.ZOOM_MIN)


def test_a_plain_wheel_does_not_zoom_the_picker(picker: KeycodePicker) -> None:
    spin(picker, +3, ctrl=False)
    assert picker.zoom() == pytest.approx(1.0)


def test_zooming_the_picker_changes_the_key_size(picker: KeycodePicker) -> None:
    before = picker._unit()
    picker.set_zoom(2.0)
    assert picker._unit() > before


def test_the_two_zooms_are_independent(
    canvas: KeyboardCanvas, picker: KeycodePicker
) -> None:
    canvas.set_zoom(2.0)
    assert picker.zoom() == pytest.approx(1.0)
    picker.set_zoom(1.5)
    assert canvas.zoom() == pytest.approx(2.0)

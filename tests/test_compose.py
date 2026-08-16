# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 白い熊
"""Building a composed keycode out of two clicks.

``LT2(KC_SPACE)`` and ``LGUI(KC_1)`` cannot be single buttons — each has a hole in it
where a basic keycode goes. The picker offers the outer half and then asks for the
inner one, which is the only route to these keycodes that does not involve typing
their spelling from memory.
"""

from __future__ import annotations

import os
import tempfile

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PyQt6.QtWidgets")

from PyQt6.QtCore import QSettings, Qt  # noqa: E402
from PyQt6.QtGui import QKeyEvent  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from svalboard.protocol.keycodes import KIND_TEMPLATE, KeycodeSet  # noqa: E402
from svalboard.ui.theme import Theme  # noqa: E402
from svalboard.ui.widgets.keycode_picker import KeycodePicker  # noqa: E402


@pytest.fixture(scope="session")
def application() -> QApplication:
    return QApplication.instance() or QApplication([])


@pytest.fixture
def picker(application: QApplication) -> KeycodePicker:
    theme = Theme(QSettings(tempfile.mktemp(suffix=".ini"), QSettings.Format.IniFormat))
    widget = KeycodePicker(theme)
    widget.set_keycodes(KeycodeSet(layers=16, macros=50, tap_dances=50), [])
    return widget


def chosen(picker: KeycodePicker) -> list:
    """Collect whatever the picker finally hands over."""
    caught: list = []
    picker.keycodeChosen.connect(caught.append)
    return caught


def entry(picker: KeycodePicker, category: str, name: str):
    picker.category.setCurrentIndex(picker.category.findText(category))
    for info in picker._entries():
        if info.name == name:
            return info
    raise AssertionError(f"{name} is not in the {category} tab")


def test_layers_tab_offers_layer_taps(picker: KeycodePicker) -> None:
    picker.category.setCurrentIndex(picker.category.findText("Layers"))
    names = [info.name for info in picker._entries()]
    assert "MO(2)" in names
    assert "LT2(kc)" in names
    # The plain operations come first: they are the common case and need no second
    # click.
    assert names.index("MO(2)") < names.index("LT2(kc)")


def test_a_template_asks_for_its_inner_keycode(picker: KeycodePicker) -> None:
    caught = chosen(picker)
    template = entry(picker, "Layers", "LT2(kc)")
    assert template.kind == KIND_TEMPLATE

    picker._on_chosen(template)
    assert caught == []  # nothing assignable yet
    assert picker.composing() is template
    assert picker.compose_bar.isVisibleTo(picker)
    assert "tapped" in picker.compose_label.text()
    # The inner keycode nearly always comes from the basic tab, so it is shown.
    assert picker.category.currentText() == "basic"

    picker._on_chosen(picker._keycodes.info(picker._keycodes.parse("KC_SPACE")))
    assert [info.name for info in caught] == ["LT2(KC_SPACE)"]
    assert caught[0].code == 0x422C
    assert picker.composing() is None
    # And it puts you back where you were, ready for the next one.
    assert picker.category.currentText() == "Layers"


def test_modifier_wrapper_composes_the_same_way(picker: KeycodePicker) -> None:
    caught = chosen(picker)
    picker._on_chosen(entry(picker, "modifiers", "LGUI(kc)"))
    picker._on_chosen(picker._keycodes.info(picker._keycodes.parse("KC_1")))

    assert [info.name for info in caught] == ["LGUI(KC_1)"]
    assert caught[0].code == 0x081E


def test_a_template_refuses_what_cannot_fit_inside(picker: KeycodePicker) -> None:
    caught = chosen(picker)
    picker._on_chosen(entry(picker, "Layers", "LT2(kc)"))

    # A layer operation already occupies the byte the outer half needs.
    picker._on_chosen(picker._keycodes.info(picker._keycodes.parse("MO(3)")))
    assert caught == []
    assert picker.composing() is not None  # still waiting, not silently wrong

    # Nor can two outer halves be stacked.
    picker._on_chosen(picker._keycodes.template("LGUI(kc)"))
    assert caught == []
    assert picker.composing() is not None

    picker._on_chosen(picker._keycodes.info(picker._keycodes.parse("KC_A")))
    assert [info.name for info in caught] == ["LT2(KC_A)"]


def test_escape_abandons_a_half_built_keycode(picker: KeycodePicker) -> None:
    caught = chosen(picker)
    picker._on_chosen(entry(picker, "Layers", "LT2(kc)"))
    assert picker.category.currentText() == "basic"

    picker.keyPressEvent(
        QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
    )
    assert picker.composing() is None
    assert not picker.compose_bar.isVisibleTo(picker)
    assert picker.category.currentText() == "Layers"

    # And an ordinary keycode is assignable again straight away.
    picker._on_chosen(picker._keycodes.info(picker._keycodes.parse("KC_B")))
    assert [info.name for info in caught] == ["KC_B"]


def test_an_ordinary_keycode_still_takes_one_click(picker: KeycodePicker) -> None:
    caught = chosen(picker)
    picker._on_chosen(entry(picker, "basic", "KC_ENTER"))
    assert [info.name for info in caught] == ["KC_ENTER"]
    assert picker.composing() is None


# -- opening at a size that fits ---------------------------------------------------


def test_the_picker_asks_for_room_for_whole_rows(picker: KeycodePicker) -> None:
    """The window sizes itself from this, so it has to grow with the rows asked for."""
    four = picker.ideal_height(4)
    two = picker.ideal_height(2)
    assert four > two > 0
    # Two more rows means two more units plus the gaps between them.
    unit = picker._unit()
    assert four - two >= 2 * unit


# -- how a composed keycode reads on a key ----------------------------------------


@pytest.mark.parametrize(
    ("name", "strip", "label"),
    [
        ("KC_A", "", "A"),
        ("MO(2)", "", "MO\n2"),            # a layer op already reads as two lines
        ("LGUI(KC_1)", "LGUI", "!\n1"),
        ("LT2(KC_SPACE)", "LT2", "Space"),
        ("LCTL_T(KC_ENTER)", "LCTL_T", "Enter"),
        ("OSM(MOD_LSFT)", "OSM", "LSft"),  # not "OSM" twice, once in each place
    ],
)
def test_the_held_half_goes_in_the_strip(name: str, strip: str, label: str) -> None:
    from svalboard.ui.widgets.keyboard_canvas import split_label

    keycodes = KeycodeSet(layers=16)
    assert split_label(keycodes.info(keycodes.parse(name))) == (strip, label)


def test_a_template_keeps_its_whole_label() -> None:
    """It says what is missing; a strip would only repeat half of it."""
    from svalboard.ui.widgets.keyboard_canvas import split_label

    keycodes = KeycodeSet(layers=16)
    assert split_label(keycodes.template("LGUI(kc)")) == ("", "LGui\n…")


def test_categories_are_sorted_regardless_of_case(picker: KeycodePicker) -> None:
    """The capitalised runtime tabs used to be herded to the top by their capitals."""
    names = [picker.category.itemText(i) for i in range(picker.category.count())]
    assert names == sorted(names, key=str.casefold)
    assert {"Layers", "Svalboard", "basic", "modifiers"} <= set(names)
    # And basic is still what the picker opens on, wherever it lands in the list.
    assert picker.category.currentText() == "basic"

# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 白い熊
"""KLE deserialisation.

The Svalboard cases use the real ``layouts.keymap`` out of the keyboard's own
definition, so they assert what the firmware ships rather than a reconstruction.
"""

from __future__ import annotations

import math

import pytest

from svalboard.protocol.kle import Layout, deserialize, from_definition

#: The left thumb cluster and one finger cluster, verbatim from the Svalboard
#: definition read off the hardware.
SVALBOARD_ROWS = [
    [{"x": 3.5}, "3,3", {"x": 2.5}, "2,3", {"x": 9}, "7,3", {"x": 2.5}, "8,3"],
    [
        {"x": 2.5}, "3,4", "3,2", "3,1",
        {"x": 0.5}, "2,4", "2,2", "2,1",
        {"x": 7}, "7,4", "7,2", "7,1",
        {"x": 0.5}, "8,4", "8,2", "8,1",
    ],
    [{"y": -0.5, "x": 1}, "4,3", {"x": 7.5}, "1,3", {"x": 4}, "6,3", {"x": 7.5}, "9,3"],
    [{"y": -0.5, "x": 3.5}, "3,0", {"x": 2.5}, "2,0", {"x": 9}, "7,0", {"x": 2.5}, "8,0"],
    [
        {"y": -0.5}, "4,4", "4,2", "4,1",
        {"x": 5.5}, "1,4", "1,2", "1,1",
        {"x": 2}, "6,4", "6,2", "6,1",
        {"x": 5.5}, "9,4", "9,2", "9,1",
    ],
    [{"x": 1}, "4,0", {"x": 7.5}, "1,0", {"x": 4}, "6,0", {"x": 7.5}, "9,0"],
    [
        {"y": 0.5, "x": 7.9, "w": 1.5}, "0,3",
        {"x": 0.1}, "0,5",
        {"x": 0.1, "w": 1.5}, "0,1",
        {"x": 0.8, "w": 1.5}, "5,1",
        {"x": 0.1}, "5,5",
        {"x": 0.1, "w": 1.5}, "5,3",
    ],
    [
        {"x": 7.4, "w": 2}, "0,4",
        {"x": 0.1}, "0,2",
        {"x": 0.1, "w": 1.5}, "0,0",
        {"x": 0.8, "w": 1.5}, "5,0",
        {"x": 0.1}, "5,2",
        {"x": 0.1, "w": 2}, "5,4",
    ],
]


@pytest.fixture
def svalboard() -> Layout:
    return from_definition(
        {"matrix": {"rows": 10, "cols": 6}, "layouts": {"keymap": SVALBOARD_ROWS}}
    )


# -- the format itself -----------------------------------------------------------


def test_keys_advance_by_their_own_width() -> None:
    layout = deserialize([["0,0", "0,1", "0,2"]])
    assert [key.x for key in layout.keys] == [0.0, 1.0, 2.0]
    assert all(key.y == 0.0 for key in layout.keys)


def test_x_and_y_are_relative_steps() -> None:
    layout = deserialize([[{"x": 2}, "0,0", {"x": 0.5}, "0,1"]])
    assert [key.x for key in layout.keys] == [2.0, 3.5]


def test_a_row_returns_to_the_left_margin() -> None:
    layout = deserialize([["0,0", "0,1"], ["1,0"]])
    assert layout.keys[2].x == 0.0
    assert layout.keys[2].y == 1.0


def test_width_applies_to_one_key_then_resets() -> None:
    layout = deserialize([[{"w": 2}, "0,0", "0,1"]])
    assert layout.keys[0].width == 2.0
    assert layout.keys[1].width == 1.0
    assert layout.keys[1].x == 2.0


def test_rotation_origin_moves_the_cursor() -> None:
    """Setting rx/ry places the cursor on the new origin, as KLE specifies."""
    layout = deserialize([[{"r": 30, "rx": 4, "ry": 2}, "0,0"]])
    key = layout.keys[0]
    assert (key.x, key.y) == (4.0, 2.0)
    assert key.rotation_angle == 30.0
    assert (key.rotation_x, key.rotation_y) == (4.0, 2.0)


def test_rotated_centre_is_rotated_about_the_origin() -> None:
    layout = deserialize([[{"r": 90, "rx": 0, "ry": 0}, "0,0"]])
    cx, cy = layout.keys[0].centre()
    assert math.isclose(cx, -0.5, abs_tol=1e-9)
    assert math.isclose(cy, 0.5, abs_tol=1e-9)


def test_decal_keys_are_not_keys() -> None:
    layout = deserialize([[{"d": True}, "0,0", "0,1"]])
    assert layout.keys[0].decal
    assert not layout.keys[0].is_key
    assert layout.keys[1].is_key


def test_encoders_are_distinguished_from_matrix_positions() -> None:
    layout = deserialize([["0,1\n\n\n\ne"]])
    key = layout.keys[0]
    assert key.is_encoder
    assert (key.encoder_index, key.encoder_direction) == (0, 1)
    assert not key.is_key


def test_layout_options_are_read() -> None:
    layout = deserialize([["0,0\n\n\n\n\n\n\n\n1,2"]])
    assert (layout.keys[0].layout_index, layout.keys[0].layout_option) == (1, 2)
    assert layout.keys_for_option({1: 2}) == [layout.keys[0]]
    assert layout.keys_for_option({1: 0}) == []


def test_board_metadata_object_is_ignored() -> None:
    layout = deserialize([{"name": "a board"}, ["0,0"]])
    assert len(layout.keys) == 1


def test_unknown_properties_do_not_break_the_parse() -> None:
    layout = deserialize([[{"c": "#ff0000", "t": "#000000", "a": 7, "f": 3}, "0,0"]])
    assert layout.keys[0].is_key


# -- the actual keyboard ---------------------------------------------------------


def test_svalboard_matrix_comes_from_the_matrix_block(svalboard: Layout) -> None:
    assert (svalboard.rows, svalboard.cols) == (10, 6)


def test_svalboard_draws_fifty_two_of_sixty_positions(svalboard: Layout) -> None:
    """Eight matrix positions exist but are not drawn.

    They are the super-south slot of each of the eight finger clusters, and they are
    exactly the positions that read back as never-written on the hardware. The thumb
    clusters do use their sixth position.
    """
    drawn = {(key.row, key.col) for key in svalboard.keys if key.is_key}
    assert len(drawn) == 52

    everything = {(r, c) for r in range(10) for c in range(6)}
    assert sorted(everything - drawn) == [
        (1, 5), (2, 5), (3, 5), (4, 5), (6, 5), (7, 5), (8, 5), (9, 5)
    ]


def test_svalboard_thumb_clusters_are_wider_keys(svalboard: Layout) -> None:
    thumbs = [key for key in svalboard.keys if key.row in (0, 5) and key.is_key]
    assert len(thumbs) == 12
    assert max(key.width for key in thumbs) == 2.0


def test_svalboard_has_no_duplicate_positions(svalboard: Layout) -> None:
    keys = [key for key in svalboard.keys if key.is_key]
    assert len(keys) == len({(key.row, key.col) for key in keys})


def test_kmid_indexes_a_flat_keymap(svalboard: Layout) -> None:
    by_matrix = svalboard.by_matrix()
    assert by_matrix[(3, 4)].kmid(svalboard.cols) == 3 * 6 + 4


def test_bounds_cover_the_whole_board(svalboard: Layout) -> None:
    min_x, min_y, max_x, max_y = svalboard.bounds
    assert (min_x, min_y) == (0.0, 0.0)
    assert (max_x, max_y) == (25.0, 7.0)

# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 白い熊
"""The edit buffer: baseline versus working, undo, redo and pending writes."""

from __future__ import annotations

import pytest

from svalboard.model.changes import KeymapChanges, PendingWrite

ROWS, COLS, LAYERS = 10, 6, 16
PER_LAYER = ROWS * COLS


@pytest.fixture
def changes() -> KeymapChanges:
    buffer = KeymapChanges(rows=ROWS, cols=COLS, layers=LAYERS)
    buffer.load([0x0000] * (PER_LAYER * LAYERS))
    return buffer


def test_a_fresh_buffer_is_clean(changes: KeymapChanges) -> None:
    assert changes.loaded
    assert not changes.is_dirty
    assert changes.pending() == []
    assert not changes.can_undo
    assert not changes.can_redo


def test_setting_a_key_marks_it_changed(changes: KeymapChanges) -> None:
    changes.set_key(0, 14, 0x0004)
    assert changes.code(0, 14) == 0x0004
    assert changes.baseline_code(0, 14) == 0x0000
    assert changes.is_changed(0, 14)
    assert changes.is_dirty


def test_setting_a_key_to_its_current_value_is_not_an_edit(changes: KeymapChanges) -> None:
    assert changes.set_key(0, 14, 0x0000) is None
    assert not changes.is_dirty
    assert not changes.can_undo


def test_pending_writes_carry_matrix_coordinates(changes: KeymapChanges) -> None:
    changes.set_key(3, 2 * COLS + 4, 0x0004)
    assert changes.pending() == [PendingWrite(layer=3, row=2, col=4, code=0x0004)]


def test_pending_covers_every_layer(changes: KeymapChanges) -> None:
    changes.set_key(0, 0, 0x0004)
    changes.set_key(15, 59, 0x0005)
    assert {write.layer for write in changes.pending()} == {0, 15}


def test_undo_and_redo(changes: KeymapChanges) -> None:
    changes.set_key(0, 5, 0x0004)
    changes.set_key(0, 6, 0x0005)

    changes.undo()
    assert changes.code(0, 6) == 0x0000
    assert changes.code(0, 5) == 0x0004
    assert changes.can_redo

    changes.redo()
    assert changes.code(0, 6) == 0x0005

    changes.undo()
    changes.undo()
    assert not changes.is_dirty
    assert not changes.can_undo


def test_a_new_edit_discards_the_redo_future(changes: KeymapChanges) -> None:
    changes.set_key(0, 5, 0x0004)
    changes.undo()
    assert changes.can_redo
    changes.set_key(0, 7, 0x0006)
    assert not changes.can_redo


def test_revert_one_key(changes: KeymapChanges) -> None:
    changes.set_key(0, 5, 0x0004)
    changes.revert_key(0, 5)
    assert not changes.is_changed(0, 5)


def test_revert_all(changes: KeymapChanges) -> None:
    changes.set_key(0, 5, 0x0004)
    changes.set_key(1, 6, 0x0005)
    changes.revert_all()
    assert not changes.is_dirty
    assert not changes.can_undo


def test_changed_layers(changes: KeymapChanges) -> None:
    changes.set_key(2, 0, 0x0004)
    changes.set_key(9, 0, 0x0004)
    assert changes.changed_layers() == {2, 9}


def test_fill_layer(changes: KeymapChanges) -> None:
    filled = changes.fill_layer(4, 0x0001)
    assert filled == PER_LAYER
    assert changes.layer(4) == [0x0001] * PER_LAYER
    assert changes.layer(5) == [0x0000] * PER_LAYER


def test_fill_layer_only_empty_leaves_assignments_alone(changes: KeymapChanges) -> None:
    changes.set_key(4, 0, 0x0004)
    changes.fill_layer(4, 0x0001, only_empty=True)
    assert changes.code(4, 0) == 0x0004
    assert changes.code(4, 1) == 0x0001


def test_mark_written_adopts_the_working_copy(changes: KeymapChanges) -> None:
    changes.set_key(0, 5, 0x0004)
    changes.mark_written()
    assert not changes.is_dirty
    assert changes.baseline_code(0, 5) == 0x0004
    assert not changes.can_undo


def test_a_partial_commit_leaves_the_rest_pending(changes: KeymapChanges) -> None:
    """An unplug halfway through must not pretend the remaining writes landed."""
    changes.set_key(0, 5, 0x0004)
    changes.set_key(0, 6, 0x0005)
    written = changes.pending()[:1]

    changes.mark_written(written)
    assert changes.is_dirty
    assert changes.pending() == [PendingWrite(layer=0, row=1, col=0, code=0x0005)]


def test_listeners_are_told(changes: KeymapChanges) -> None:
    seen = []
    changes.subscribe(lambda: seen.append(True))
    changes.set_key(0, 1, 0x0004)
    changes.undo()
    assert len(seen) == 2


def test_out_of_range_is_refused(changes: KeymapChanges) -> None:
    with pytest.raises(IndexError):
        changes.code(99, 0)
    with pytest.raises(IndexError):
        changes.code(0, 999)

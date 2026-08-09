# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 白い熊
"""Export and import: the archive, the naming convention, and typed settings."""

from __future__ import annotations

import json
import zipfile
from datetime import datetime
from pathlib import Path

import pytest

from svalboard.model.eximport import (
    Archive,
    Category,
    ExportError,
    ImportError_,
    export_filename,
    is_export,
    latest_export,
    tag_all,
    untag_all,
)


@pytest.fixture
def archive() -> tuple[Archive, dict]:
    applied: dict = {}

    def apply_ui(payload):
        applied["ui"] = payload
        return len(payload)

    def apply_keymap(payload):
        applied["keymap"] = payload
        return len(payload.get("keymap", []))

    categories = [
        Category("ui", "白い熊 Svalboard UI", lambda: {"key.corner": {"t": "i", "v": 9}}, apply_ui),
        Category("keymap", "Keymap and layers", lambda: {"keymap": [["KC_A"]]}, apply_keymap),
        Category("macros", "Macros", unavailable="Arrives with the macro editor."),
    ]
    return Archive(categories), applied


# -- naming ----------------------------------------------------------------------


def test_filename_follows_the_family_convention() -> None:
    name = export_filename(datetime(2026, 8, 9, 14, 32, 7))
    assert name == "shiroikuma-svalboard_2026-08-09_14-32-07.zip"
    assert is_export(name)


def test_foreign_names_are_not_ours() -> None:
    assert not is_export("shiroikuma-kojiki_2026-08-09_14-32-07.zip")
    assert not is_export("backup.zip")


def test_latest_export_picks_the_newest(tmp_path: Path) -> None:
    older = tmp_path / export_filename(datetime(2026, 1, 1, 0, 0, 0))
    newer = tmp_path / export_filename(datetime(2026, 8, 1, 0, 0, 0))
    for index, path in enumerate((older, newer)):
        path.write_bytes(b"x")
        import os
        os.utime(path, (1000 + index * 1000, 1000 + index * 1000))
    (tmp_path / "unrelated.zip").write_bytes(b"x")

    assert latest_export(tmp_path) == newer


def test_latest_export_is_tolerant(tmp_path: Path) -> None:
    """It runs whenever the page opens, so it must never raise there."""
    assert latest_export(None) is None
    assert latest_export(tmp_path / "missing") is None
    assert latest_export(tmp_path) is None


# -- typed settings --------------------------------------------------------------


def test_types_survive_a_round_trip() -> None:
    values = {"a": True, "b": 7, "c": 1.5, "d": "text", "e": ["x", "y"]}
    assert untag_all(tag_all(values)) == values


def test_booleans_are_not_tagged_as_integers() -> None:
    """bool is a subclass of int, so order matters and a slip is silent."""
    assert tag_all({"flag": True})["flag"]["t"] == "b"
    assert untag_all({"flag": {"t": "b", "v": "true"}}) == {"flag": True}


# -- export ----------------------------------------------------------------------


def test_export_writes_a_manifest_and_a_file_per_category(tmp_path, archive) -> None:
    engine, _ = archive
    outcome = engine.export(tmp_path, ["ui", "keymap"], now=datetime(2026, 8, 9, 1, 2, 3))

    assert outcome.path is not None and outcome.path.exists()
    with zipfile.ZipFile(outcome.path) as zipped:
        names = set(zipped.namelist())
        assert names == {"manifest.json", "ui.json", "keymap.json"}
        manifest = json.loads(zipped.read("manifest.json"))
    assert manifest["format"] == "svalboard-export"
    assert manifest["categories"] == ["ui", "keymap"]
    assert "白い熊 Svalboard UI: 1 settings" in outcome.summary()


def test_export_with_nothing_selected_uses_the_family_wording(tmp_path, archive) -> None:
    engine, _ = archive
    with pytest.raises(ExportError, match="Select at least one category."):
        engine.export(tmp_path, [])


def test_unavailable_categories_cannot_be_exported(tmp_path, archive) -> None:
    engine, _ = archive
    with pytest.raises(ExportError):
        engine.export(tmp_path, ["macros"])


def test_extra_files_are_carried(tmp_path, archive) -> None:
    engine, _ = archive
    font = tmp_path / "Some.ttf"
    font.write_bytes(b"not really a font")
    outcome = engine.export(tmp_path, ["ui"], extra_files={"fonts/Some.ttf": font})
    with zipfile.ZipFile(outcome.path) as zipped:
        assert "fonts/Some.ttf" in zipped.namelist()


# -- import ----------------------------------------------------------------------


def test_import_applies_the_chosen_categories(tmp_path, archive) -> None:
    engine, applied = archive
    outcome = engine.export(tmp_path, ["ui", "keymap"])
    result = engine.import_(outcome.path, ["ui", "keymap"])

    assert applied["ui"] == {"key.corner": {"t": "i", "v": 9}}
    assert "Keymap and layers: 1" in result.summary()


def test_import_skips_categories_the_file_does_not_have(tmp_path, archive) -> None:
    """A backup written before a feature existed must still load afterwards."""
    engine, applied = archive
    outcome = engine.export(tmp_path, ["ui"])
    engine.import_(outcome.path, ["ui", "keymap"])
    assert "keymap" not in applied


def test_a_foreign_archive_is_refused(tmp_path, archive) -> None:
    engine, _ = archive
    path = tmp_path / "other.zip"
    with zipfile.ZipFile(path, "w") as zipped:
        zipped.writestr("manifest.json", json.dumps({"format": "kojiki-export"}))
    with pytest.raises(ImportError_, match="not a 白い熊 Svalboard export"):
        engine.import_(path, ["ui"])


def test_a_file_that_is_not_a_zip_is_refused(tmp_path, archive) -> None:
    engine, _ = archive
    path = tmp_path / "notes.txt"
    path.write_text("hello", encoding="utf-8")
    with pytest.raises(ImportError_):
        engine.import_(path, ["ui"])


def test_one_failing_category_does_not_abort_the_rest(tmp_path) -> None:
    def explode(_payload):
        raise RuntimeError("nope")

    engine = Archive(
        [
            Category("bad", "Bad", lambda: {"a": 1}, explode),
            Category("good", "Good", lambda: {"b": 2}, lambda payload: len(payload)),
        ]
    )
    outcome = engine.export(tmp_path, ["bad", "good"])
    result = engine.import_(outcome.path, ["bad", "good"])
    assert "Bad: failed — nope" in result.summary()
    assert "Good: 1" in result.summary()

# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 白い熊
"""Export and import, in the 白い熊 family format.

One ZIP of plain JSON — a manifest plus a file per category, and any imported fonts as
real files under ``fonts/``. No binary blobs and no pickled objects, so a backup can be
read and repaired with a text editor years later.

The format is future-proof by construction: import walks the categories the *user*
chose, skips any the file does not contain, and tolerates keys it does not recognise.
That is what lets a backup written today load into a version that has grown macros and
tap dances, and a backup written then load into this one.

Categories not yet implemented are declared as unavailable rather than omitted, so the
panel can show them greyed with a reason instead of pretending they do not exist.
"""

from __future__ import annotations

import json
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

FORMAT = "svalboard-export"
VERSION = 1
APPLICATION = "shiroikuma-svalboard"

#: `<english-dash-separated-app-name>_<yyyy-MM-dd_HH-mm-ss>.zip`, the family
#: convention, so every sister app's backups sort together in one directory.
PREFIX = "shiroikuma-svalboard_"
STAMP = "%Y-%m-%d_%H-%M-%S"

MANIFEST = "manifest.json"


class ExportError(Exception):
    """The export could not be written."""


class ImportError_(Exception):
    """The file is not a backup this program can read."""


@dataclass
class Category:
    """One independently exportable part of the configuration."""

    key: str
    title: str
    collect: Callable[[], Any] | None = None
    apply: Callable[[Any], int] | None = None
    unavailable: str = ""

    @property
    def available(self) -> bool:
        return not self.unavailable and self.collect is not None


@dataclass
class Outcome:
    path: Path | None = None
    lines: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return "\n".join(self.lines)


def export_filename(now: datetime | None = None) -> str:
    return PREFIX + (now or datetime.now()).strftime(STAMP) + ".zip"


def is_export(name: str) -> bool:
    return name.startswith(PREFIX) and name.endswith(".zip")


def latest_export(directory: Path | None) -> Path | None:
    """The newest backup in ``directory``, or ``None``.

    Deliberately tolerant: an unreadable or vanished directory is simply "nothing
    found", because this runs every time the page opens and must never raise there.
    """
    if directory is None:
        return None
    try:
        candidates = [
            entry
            for entry in directory.iterdir()
            if entry.is_file() and is_export(entry.name)
        ]
    except OSError:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime, default=None)


# -- typed settings --------------------------------------------------------------

#: QSettings on Linux writes INI, which loses every type. Values are therefore tagged
#: on the way out so a boolean comes back a boolean rather than the string "true".
_TAGS = {bool: "b", int: "i", float: "f", str: "s"}


def tag(value: Any) -> dict[str, Any]:
    for python_type, letter in _TAGS.items():
        # bool before int: bool is a subclass of int and would otherwise be tagged "i".
        if isinstance(value, python_type):
            return {"t": letter, "v": value}
    if isinstance(value, (list, tuple)):
        return {"t": "ss", "v": [str(item) for item in value]}
    return {"t": "s", "v": str(value)}


def untag(entry: Any) -> Any:
    if not isinstance(entry, dict) or "v" not in entry:
        return entry
    letter, value = entry.get("t", "s"), entry["v"]
    try:
        if letter == "b":
            return bool(value) if isinstance(value, bool) else str(value).lower() in ("true", "1")
        if letter == "i":
            return int(value)
        if letter == "f":
            return float(value)
        if letter == "ss":
            return [str(item) for item in value]
    except (TypeError, ValueError):
        return value
    return str(value)


def tag_all(values: dict[str, Any]) -> dict[str, Any]:
    return {key: tag(value) for key, value in values.items()}


def untag_all(values: dict[str, Any]) -> dict[str, Any]:
    return {key: untag(entry) for key, entry in values.items()}


# -- the archive -----------------------------------------------------------------


class Archive:
    """Exports and imports a set of categories."""

    def __init__(self, categories: list[Category], *, app_version: str = "0.1.0") -> None:
        self.categories = categories
        self.app_version = app_version

    def by_key(self, key: str) -> Category | None:
        return next((c for c in self.categories if c.key == key), None)

    # -- export ------------------------------------------------------------------

    def export(
        self,
        directory: Path,
        keys: list[str],
        *,
        extra_files: dict[str, Path] | None = None,
        now: datetime | None = None,
    ) -> Outcome:
        chosen = [c for c in self.categories if c.key in keys and c.available]
        if not chosen:
            raise ExportError("Select at least one category.")

        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ExportError(f"{directory} cannot be created: {exc}") from exc

        path = directory / export_filename(now)
        outcome = Outcome(path=path)
        try:
            with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
                manifest = {
                    "format": FORMAT,
                    "version": VERSION,
                    "app": APPLICATION,
                    "appVersion": self.app_version,
                    "createdTs": int((now or datetime.now()).timestamp() * 1000),
                    "categories": [category.key for category in chosen],
                }
                archive.writestr(MANIFEST, json.dumps(manifest, indent=2))

                for category in chosen:
                    assert category.collect is not None
                    payload = category.collect()
                    archive.writestr(
                        f"{category.key}.json",
                        json.dumps(payload, indent=2, ensure_ascii=False),
                    )
                    outcome.lines.append(f"{category.title}: {_count(payload)}")

                for name, source in (extra_files or {}).items():
                    if source.is_file():
                        archive.write(source, name)
        except OSError as exc:
            path.unlink(missing_ok=True)
            raise ExportError(f"Export failed: {exc}") from exc
        return outcome

    # -- import ------------------------------------------------------------------

    def categories_in(self, path: Path) -> list[str]:
        """Which categories a file offers. Empty means it is not one of ours."""
        try:
            with zipfile.ZipFile(path) as archive:
                try:
                    manifest = json.loads(archive.read(MANIFEST))
                except KeyError:
                    return []
                if manifest.get("format") != FORMAT:
                    # Unlike the family's other apps, a foreign format is refused
                    # rather than half-applied.
                    return []
                declared = [str(key) for key in manifest.get("categories") or []]
                present = set(archive.namelist())
                return [key for key in declared if f"{key}.json" in present]
        except (OSError, zipfile.BadZipFile, json.JSONDecodeError):
            return []

    def import_(self, path: Path, keys: list[str]) -> Outcome:
        available = self.categories_in(path)
        if not available:
            raise ImportError_(
                f"{path.name} is not a 白い熊 Svalboard export."
            )
        chosen = [
            category
            for category in self.categories
            if category.key in keys and category.key in available and category.apply
        ]
        if not chosen:
            raise ImportError_("Select at least one category.")

        outcome = Outcome(path=path)
        with zipfile.ZipFile(path) as archive:
            for category in chosen:
                assert category.apply is not None
                try:
                    payload = json.loads(archive.read(f"{category.key}.json"))
                    applied = category.apply(payload)
                except Exception as exc:  # noqa: BLE001 - one bad category must not
                    # abort the rest; the failure is reported in the summary instead.
                    outcome.lines.append(f"{category.title}: failed — {exc}")
                    continue
                outcome.lines.append(f"{category.title}: {applied}")
        return outcome


def _count(payload: Any) -> str:
    if isinstance(payload, dict):
        return f"{len(payload)} settings"
    if isinstance(payload, list):
        return f"{len(payload)} entries"
    return "written"

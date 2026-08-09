# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 白い熊
"""The Export / Import panel — the first section of the UI settings page.

Behaviour follows the family: the backup directory is probed for the newest export
whenever the panel opens, an unset directory is stated in red, categories are a flat
checklist with a Select-all master, and the buttons are pills with Cancel alone on the
left.

On success the whole chain unwinds — the information dialog, this panel, and the UI
settings page behind it. On failure nothing closes, so the selection survives and the
problem can be corrected without starting again.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QObject, QRunnable, Qt, QThreadPool, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QFrame,
    QLabel,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from ...model.eximport import (
    Archive,
    ExportError,
    ImportError_,
    latest_export,
)
from ..theme import Theme
from ..widgets.house import Heading, button_row, themed_font

#: Kept apart from the theme, and never exported: where a backup lives is a fact
#: about this machine, not a setting worth carrying to another one.
DIRECTORY_KEY = "backup/directory"

NO_DIRECTORY = "Not set — choose a directory"
NO_DIRECTORY_HINT = "No directory set yet — pick one to enable one-tap export."
NO_EXPORT_YET = "No export in this directory yet."


class _ProbeSignals(QObject):
    finished = pyqtSignal(object)


class _Probe(QRunnable):
    """Finds the newest export without blocking the interface.

    A local directory answers instantly, but the backup directory can perfectly well
    be a network mount, and this runs every time the panel opens.
    """

    def __init__(self, directory: Path | None) -> None:
        super().__init__()
        self.directory = directory
        self.signals = _ProbeSignals()

    @pyqtSlot()
    def run(self) -> None:
        self.signals.finished.emit(latest_export(self.directory))


class ExportImportPanel(QDialog):
    """Choose a directory and categories, then export or import."""

    #: Emitted when the caller should close too — success unwinds the whole chain.
    chainFinished = pyqtSignal()

    def __init__(
        self,
        theme: Theme,
        archive: Archive,
        *,
        extra_files: dict[str, Path] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._theme = theme
        self._archive = archive
        self._extra_files = extra_files or {}
        self._boxes: dict[str, QCheckBox] = {}

        self.setWindowTitle("Export / Import")
        self.setModal(True)
        self.resize(560, 620)

        column = QVBoxLayout(self)
        padding = int(theme["dialog.padding"])
        column.setContentsMargins(padding, padding, padding, padding)
        column.setSpacing(10)

        column.addWidget(Heading("Export / Import", theme, level=0))

        self.folder_box = QFrame()
        folder_column = QVBoxLayout(self.folder_box)
        folder_column.setContentsMargins(12, 10, 12, 10)
        folder_column.setSpacing(2)
        caption = QLabel("Backup directory (click to choose)")
        self.folder_value = QLabel()
        folder_column.addWidget(caption)
        folder_column.addWidget(self.folder_value)
        self.folder_box.setCursor(Qt.CursorShape.PointingHandCursor)
        self.folder_box.mouseReleaseEvent = lambda _event: self._choose_directory()
        column.addWidget(self.folder_box)

        self.status = QLabel()
        self.status.setWordWrap(True)
        column.addWidget(self.status)

        self.select_all = QCheckBox("Select all")
        self.select_all.setChecked(True)
        self.select_all.toggled.connect(self._toggle_all)
        column.addWidget(self.select_all)

        for category in archive.categories:
            box = QCheckBox(category.title)
            if category.available:
                box.setChecked(True)
            else:
                box.setEnabled(False)
                box.setChecked(False)
                box.setToolTip(category.unavailable)
                box.setText(f"{category.title} — {category.unavailable}")
            self._boxes[category.key] = box
            column.addWidget(box)

        column.addStretch(1)
        column.addWidget(
            button_row(
                theme,
                ("Cancel", self.reject),
                [("Import", self._import), ("Export", self._export)],
            )
        )

        self._restyle()
        theme.changed.connect(self._restyle)
        self.refresh()

    # -- appearance --------------------------------------------------------------

    def _restyle(self) -> None:
        theme = self._theme
        self.setStyleSheet(
            f"QDialog {{"
            f"background: {theme.css('dialog.background')};"
            f"border: {theme['dialog.border_width']}px solid {theme.css('dialog.border')};"
            f"}}"
        )
        self.folder_box.setStyleSheet(
            f"QFrame {{"
            f"background: {theme.css('dialog.background')};"
            f"border: 2px solid {theme.css('dialog.border')};"
            f"border-radius: 10px;"
            f"}}"
            f"QLabel {{ border: none; }}"
        )
        self._paint_state()

    def _paint_state(self) -> None:
        theme = self._theme
        directory = self.directory()
        colour = theme.css("window.text") if directory else theme.css("window.warning")
        self.folder_value.setText(str(directory) if directory else NO_DIRECTORY)
        self.folder_value.setFont(
            themed_font(str(theme["row.title.font"]), 700, int(theme["row.title.size"]))
        )
        self.folder_value.setStyleSheet(f"color: {colour}; border: none;")

    # -- directory ---------------------------------------------------------------

    def directory(self) -> Path | None:
        stored = self._theme.settings.value(DIRECTORY_KEY, "", type=str)
        return Path(str(stored)) if stored else None

    def _choose_directory(self) -> None:
        start = self.directory() or Path.home()
        chosen = QFileDialog.getExistingDirectory(
            self, "Choose a backup directory", str(start)
        )
        if not chosen:
            return
        self._theme.settings.setValue(DIRECTORY_KEY, chosen)
        self.refresh()

    def refresh(self) -> None:
        """Probe the directory for the newest export, off the interface thread."""
        self._paint_state()
        directory = self.directory()
        if directory is None:
            self._show_status(NO_DIRECTORY_HINT, warning=True)
            return
        probe = _Probe(directory)
        probe.signals.finished.connect(self._on_probe)
        QThreadPool.globalInstance().start(probe)

    def _on_probe(self, newest: object) -> None:
        if newest is None:
            self._show_status(NO_EXPORT_YET, warning=True)
            return
        path = Path(str(newest))
        from datetime import datetime

        when = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        self._show_status(f"Last export: {when}", warning=False)

    def _show_status(self, text: str, *, warning: bool) -> None:
        theme = self._theme
        self.status.setText(text)
        colour = theme.css("window.warning") if warning else theme.css("window.text")
        self.status.setStyleSheet(f"color: {colour};")

    # -- selection ---------------------------------------------------------------

    def _toggle_all(self, checked: bool) -> None:
        for key, box in self._boxes.items():
            category = self._archive.by_key(key)
            if category is not None and category.available:
                box.setChecked(checked)

    def _selected(self) -> list[str]:
        return [key for key, box in self._boxes.items() if box.isChecked()]

    # -- actions -----------------------------------------------------------------

    def _export(self) -> None:
        directory = self.directory()
        if directory is None:
            self._failure("Export failed", NO_DIRECTORY_HINT)
            return
        try:
            outcome = self._archive.export(
                directory, self._selected(), extra_files=self._extra_files
            )
        except ExportError as exc:
            self._failure("Export failed", str(exc))
            return

        assert outcome.path is not None
        self.refresh()
        self._success(
            "✓ Export complete",
            f"Exported: {outcome.path.name}\n\n{outcome.summary()}",
            [("OK", self._finish_chain)],
        )

    def _import(self) -> None:
        start = self.directory() or Path.home()
        chosen, _filter = QFileDialog.getOpenFileName(
            self, "Choose a backup to import", str(start), "Backups (*.zip)"
        )
        if not chosen:
            return
        try:
            outcome = self._archive.import_(Path(chosen), self._selected())
        except ImportError_ as exc:
            self._failure("Import failed", str(exc))
            return

        self._success(
            "✓ Import complete",
            f"Restored:\n\n{outcome.summary()}\n\nRestart to apply everything.",
            [("Later", self._finish_chain), ("Restart now", self._restart)],
        )

    def _finish_chain(self) -> None:
        """Close this panel and tell the page above to close as well."""
        self.accept()
        self.chainFinished.emit()

    def _restart(self) -> None:
        import sys

        from PyQt6.QtCore import QProcess
        from PyQt6.QtWidgets import QApplication

        # Settings are written through on every change, so there is nothing to flush;
        # the detached copy re-reads them as it starts.
        QProcess.startDetached(sys.executable, sys.argv)
        QApplication.quit()

    # -- outcome dialogs ---------------------------------------------------------

    def _dialog(self, title: str, body: str) -> QDialog:
        theme = self._theme
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.setModal(True)
        column = QVBoxLayout(dialog)
        padding = int(theme["dialog.padding"])
        column.setContentsMargins(padding, padding, padding, padding)
        column.setSpacing(10)

        heading = QLabel(title)
        heading.setFont(
            themed_font(
                str(theme["dialog.title.font"]),
                int(theme["dialog.title.weight"]),
                int(theme["dialog.title.size"]),
            )
        )
        heading.setStyleSheet(f"color: {theme.css('dialog.title.colour')}; border: none;")
        message = QLabel(body)
        message.setWordWrap(True)
        message.setStyleSheet(f"color: {theme.css('dialog.body.colour')}; border: none;")

        column.addWidget(heading)
        column.addWidget(message)
        dialog.setStyleSheet(
            f"QDialog {{"
            f"background: {theme.css('dialog.background')};"
            f"border: {theme['dialog.border_width']}px solid {theme.css('dialog.border')};"
            f"}}"
        )
        return dialog

    def _success(self, title: str, body: str, actions) -> None:
        dialog = self._dialog(title, body)
        layout = dialog.layout()

        def wrap(handler):
            def run() -> None:
                dialog.accept()
                handler()

            return run

        layout.addWidget(
            button_row(self._theme, None, [(text, wrap(handler)) for text, handler in actions])
        )
        dialog.exec()

    def _failure(self, title: str, body: str) -> None:
        """Failures leave this panel open so the selection is not lost."""
        dialog = self._dialog(title, body)
        dialog.layout().addWidget(
            button_row(self._theme, None, [("OK", dialog.accept)])
        )
        dialog.exec()

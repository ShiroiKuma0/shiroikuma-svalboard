# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 白い熊
"""白い熊 Svalboard — the application."""

from __future__ import annotations

import sys

from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtGui import QAction, QIcon, QKeySequence
from PyQt6.QtWidgets import (
    QApplication,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QScrollArea,
    QSplitter,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from .hid.transport import DeviceNotPermitted, TransportError
from .model.changes import KeymapChanges
from .protocol.keyboard import Keyboard, ProtocolError
from .ui.theme import Theme
from .ui.widgets.keyboard_canvas import KeyboardCanvas
from .ui.widgets.keycode_picker import KeycodePicker
from .ui.widgets.layer_strip import LayerStrip
from .ui.widgets.settings_button import SettingsButton

APPLICATION_NAME = "白い熊 Svalboard"


class MainWindow(QMainWindow):
    def __init__(self, theme: Theme) -> None:
        super().__init__()
        self._theme = theme
        self._keyboard: Keyboard | None = None
        self._changes: KeymapChanges | None = None
        self._keycodes = None
        self._layer_names: dict[int, str] = {}

        self.setWindowTitle(APPLICATION_NAME)
        self.resize(1500, 900)

        self.canvas = KeyboardCanvas(theme)
        self.canvas.keySelected.connect(self._on_key_selected)

        self.layers = LayerStrip(theme)
        self.layers.layerSelected.connect(self._on_layer_selected)
        self.layers.renameRequested.connect(self._rename_layer)

        self.picker = KeycodePicker(theme)
        self.picker.keycodeChosen.connect(self._assign)
        self.picker.zoomChanged.connect(self._on_picker_zoom)

        # The board lives in a scroll area so that zooming past the window can pan
        # rather than clip. In fit mode the canvas stays small and no bars appear.
        self.board_scroll = QScrollArea()
        self.board_scroll.setWidgetResizable(True)
        self.board_scroll.setWidget(self.canvas)
        self.board_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.canvas.zoomChanged.connect(self._on_board_zoom)

        board = QWidget()
        column = QVBoxLayout(board)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)
        column.addWidget(self.layers)
        column.addWidget(self.board_scroll, 1)

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(board)
        splitter.addWidget(self.picker)
        splitter.setSizes([520, 380])
        self.setCentralWidget(splitter)

        self._build_toolbar()
        self.statusBar().showMessage("Not connected.")
        theme.changed.connect(lambda: self.setStyleSheet(theme.stylesheet()))
        self.setStyleSheet(theme.stylesheet())

        self._restore_zooms()
        QTimer.singleShot(0, self.connect_keyboard)

    # -- chrome ------------------------------------------------------------------

    def _build_toolbar(self) -> None:
        bar = QToolBar("Main")
        bar.setMovable(False)
        self.addToolBar(bar)

        self.action_connect = QAction("Connect", self)
        self.action_connect.triggered.connect(self.connect_keyboard)
        bar.addAction(self.action_connect)
        bar.addSeparator()

        self.action_undo = QAction("Undo", self)
        self.action_undo.setShortcut(QKeySequence.StandardKey.Undo)
        self.action_undo.triggered.connect(self._undo)
        bar.addAction(self.action_undo)

        self.action_redo = QAction("Redo", self)
        self.action_redo.setShortcut(QKeySequence.StandardKey.Redo)
        self.action_redo.triggered.connect(self._redo)
        bar.addAction(self.action_redo)

        self.action_revert = QAction("Revert all", self)
        self.action_revert.triggered.connect(self._revert_all)
        bar.addAction(self.action_revert)

        self.action_commit = QAction("Write to keyboard", self)
        self.action_commit.triggered.connect(self._commit)
        bar.addAction(self.action_commit)
        bar.addSeparator()

        search = QAction("Find keycode", self)
        search.setShortcut(QKeySequence.StandardKey.Find)
        search.triggered.connect(self.picker.focus_search)
        bar.addAction(search)
        bar.addSeparator()

        fit = QAction("Fit board", self)
        fit.setShortcut(QKeySequence("Ctrl+0"))
        fit.setToolTip("Fit the board to the window (Ctrl+0). Ctrl+wheel zooms.")
        fit.triggered.connect(self._fit_board)
        bar.addAction(fit)

        spacer = QWidget()
        spacer.setSizePolicy(spacer.sizePolicy().horizontalPolicy().Expanding,
                             spacer.sizePolicy().verticalPolicy().Preferred)
        bar.addWidget(spacer)

        self.settings_button = SettingsButton(self._theme)
        self.settings_button.clicked.connect(self._open_settings)
        self.settings_button.uiPageRequested.connect(self._open_ui_settings)
        bar.addWidget(self.settings_button)

        self._update_actions()

    # -- zoom --------------------------------------------------------------------

    #: Where the two zooms are remembered. Kept out of the theme: how close you are
    #: looking is a property of this window, not of the appearance.
    BOARD_ZOOM_KEY = "view/board_zoom"
    PICKER_ZOOM_KEY = "view/picker_zoom"

    def _restore_zooms(self) -> None:
        settings = self._theme.settings
        board = settings.value(self.BOARD_ZOOM_KEY, "", type=str)
        if board:
            try:
                self.canvas.set_zoom(float(board))
            except ValueError:
                pass
        picker = settings.value(self.PICKER_ZOOM_KEY, 1.0, type=float)
        self.picker.set_zoom(float(picker))

    def _fit_board(self) -> None:
        self.canvas.zoom_to_fit()
        self._theme.settings.remove(self.BOARD_ZOOM_KEY)
        self.statusBar().showMessage("Board fitted to the window.", 2000)

    def _on_board_zoom(self, scale: float) -> None:
        if self.canvas.zoom() is None:
            return
        self._theme.settings.setValue(self.BOARD_ZOOM_KEY, f"{scale:.4f}")
        self.statusBar().showMessage(f"Board {scale * 100:.0f}%", 1500)

    def _on_picker_zoom(self, zoom: float) -> None:
        self._theme.settings.setValue(self.PICKER_ZOOM_KEY, zoom)
        self.statusBar().showMessage(f"Keycodes {zoom * 100:.0f}%", 1500)

    def _update_actions(self) -> None:
        changes = self._changes
        dirty = bool(changes and changes.is_dirty)
        self.action_undo.setEnabled(bool(changes and changes.can_undo))
        self.action_redo.setEnabled(bool(changes and changes.can_redo))
        self.action_revert.setEnabled(dirty)
        self.action_commit.setEnabled(dirty)
        if dirty and changes is not None:
            self.action_commit.setText(
                f"Write {len(changes.pending())} change"
                f"{'' if len(changes.pending()) == 1 else 's'} to keyboard"
            )
        else:
            self.action_commit.setText("Write to keyboard")

    # -- connecting --------------------------------------------------------------

    def connect_keyboard(self) -> None:
        if self._keyboard is not None:
            self._keyboard.close()
            self._keyboard = None
        try:
            keyboard = Keyboard.open()
            state = keyboard.load()
        except DeviceNotPermitted as exc:
            self._problem("Cannot open the keyboard", str(exc))
            return
        except (TransportError, ProtocolError) as exc:
            self._problem("Cannot talk to the keyboard", str(exc))
            return

        self._keyboard = keyboard
        self._keycodes = state.keycode_set()
        self._changes = KeymapChanges(
            rows=state.rows, cols=state.cols, layers=state.capacities.layers
        )
        self._changes.load(state.keymap)
        self._changes.subscribe(self._on_changes)

        self.canvas.set_board(state.layout, self._keycodes)
        self.layers.build(state.capacities.layers)
        self.layers.set_current(0)
        self.picker.set_keycodes(
            self._keycodes,
            [entry.get("name", "") for entry in state.definition.get("customKeycodes") or []],
        )
        self._show_layer(0)

        identity = state.identity
        extension = (
            f"Svalboard extension {identity.sval_protocol}"
            if identity.has_svalboard_extension
            else "no Svalboard extension (layer colours unavailable)"
        )
        self.statusBar().showMessage(
            f"{state.name} — Vial {identity.vial_protocol}, VIA {identity.via_protocol}, "
            f"{state.capacities.layers} layers, {extension}."
        )

    def _problem(self, title: str, detail: str) -> None:
        self.statusBar().showMessage(detail)
        box = QMessageBox(self)
        box.setWindowTitle(title)
        box.setText(detail)
        box.setIcon(QMessageBox.Icon.Warning)
        box.exec()

    # -- editing -----------------------------------------------------------------

    def _current_layer(self) -> int:
        return self.layers.current()

    def _show_layer(self, index: int) -> None:
        if self._changes is None:
            return
        self.canvas.set_layer(
            self._changes.layer(index), baseline=self._changes.baseline_layer(index)
        )
        self._refresh_layer_strip()

    def _refresh_layer_strip(self) -> None:
        if self._changes is None:
            return
        used = {
            index
            for index in range(self._changes.layers)
            if any(code for code in self._changes.layer(index))
        }
        self.layers.refresh(
            used=used, changed=self._changes.changed_layers(), names=self._layer_names
        )

    def _on_layer_selected(self, index: int) -> None:
        self._show_layer(index)

    def _on_key_selected(self, _kmid: int) -> None:
        # Choosing a key is what the picker acts on; nothing else to do yet.
        pass

    def _assign(self, info) -> None:
        if self._changes is None:
            return
        kmid = self.canvas.selected()
        if kmid < 0:
            self.statusBar().showMessage("Choose a key on the board first.")
            return
        self._changes.set_key(self._current_layer(), kmid, info.code)

    def _on_changes(self) -> None:
        self._show_layer(self._current_layer())
        self._update_actions()

    def _undo(self) -> None:
        if self._changes and (edit := self._changes.undo()):
            self.layers.set_current(edit.layer)
            self._show_layer(edit.layer)

    def _redo(self) -> None:
        if self._changes and (edit := self._changes.redo()):
            self.layers.set_current(edit.layer)
            self._show_layer(edit.layer)

    def _revert_all(self) -> None:
        if self._changes is None or not self._changes.is_dirty:
            return
        if self._confirm(
            "Discard every change?",
            f"{len(self._changes.pending())} unwritten changes will be discarded. "
            "The keyboard itself is untouched.",
            "Discard",
        ):
            self._changes.revert_all()

    def _commit(self) -> None:
        if self._keyboard is None or self._changes is None:
            return
        pending = self._changes.pending()
        if not pending:
            return
        if not self._confirm(
            "Write to the keyboard?",
            f"{len(pending)} key{'' if len(pending) == 1 else 's'} will be written to "
            "the keyboard. This takes effect immediately.",
            "Write",
        ):
            return

        written = []
        try:
            for write in pending:
                self._keyboard.write_key(write.layer, write.row, write.col, write.code)
                written.append(write)
        except TransportError as exc:
            # Whatever did land is folded in, so the rest stays visibly pending
            # rather than being silently assumed written.
            self._changes.mark_written(written)
            self._problem(
                "The write was interrupted",
                f"{len(written)} of {len(pending)} changes were written before the "
                f"keyboard stopped answering.\n\n{exc}",
            )
            return

        self._changes.mark_written()
        self.statusBar().showMessage(
            f"Wrote {len(written)} change{'' if len(written) == 1 else 's'}."
        )

    def _confirm(self, title: str, detail: str, accept: str) -> bool:
        box = QMessageBox(self)
        box.setWindowTitle(title)
        box.setText(title)
        box.setInformativeText(detail)
        yes = box.addButton(accept, QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        return box.clickedButton() is yes

    def _rename_layer(self, index: int) -> None:
        name, accepted = QInputDialog.getText(
            self,
            "Rename layer",
            f"Name for layer {index} (leave empty to clear):",
            text=self._layer_names.get(index, ""),
        )
        if not accepted:
            return
        name = name.strip()
        if name:
            self._layer_names[index] = name
        else:
            self._layer_names.pop(index, None)
        self._refresh_layer_strip()

    # -- settings ----------------------------------------------------------------

    def _open_settings(self) -> None:
        self._open_ui_settings()

    def _open_ui_settings(self) -> None:
        from .ui.settings.ui_page import UiSettingsWindow

        window = UiSettingsWindow(self._theme, self)
        window.show()

    def closeEvent(self, event) -> None:  # noqa: N802  (Qt naming)
        if self._changes is not None and self._changes.is_dirty:
            if not self._confirm(
                "Quit with unwritten changes?",
                f"{len(self._changes.pending())} changes have not been written to the "
                "keyboard and will be lost.",
                "Quit anyway",
            ):
                event.ignore()
                return
        if self._keyboard is not None:
            self._keyboard.close()
        super().closeEvent(event)


def main(argv: list[str] | None = None) -> int:
    application = QApplication(argv if argv is not None else sys.argv)
    application.setApplicationName(APPLICATION_NAME)
    application.setApplicationDisplayName(APPLICATION_NAME)
    application.setDesktopFileName("shiroikuma-svalboard")
    application.setWindowIcon(QIcon.fromTheme("shiroikuma-svalboard"))

    theme = Theme()
    window = MainWindow(theme)
    window.show()
    return application.exec()


if __name__ == "__main__":
    sys.exit(main())

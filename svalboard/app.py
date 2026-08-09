# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 白い熊
"""白い熊 Svalboard — the application."""

from __future__ import annotations

import sys
from pathlib import Path

from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtGui import QAction, QIcon, QKeySequence
from PyQt6.QtWidgets import (
    QApplication,
    QFileDialog,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QScrollArea,
    QSplitter,
    QTabWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from .hid.transport import DeviceNotPermitted, TransportError
from .model.changes import KeymapChanges
from .model.entries import EntryChanges, MacroChanges, SettingsChanges
from .model.files import FileFormatError, build_backup, check_fits, load, save_kbi
from .protocol.dynamic import Combo, KeyOverride, TapDance
from .protocol.keyboard import Keyboard, ProtocolError
from .ui.pages.entries import ComboPage, KeyOverridePage, TapDancePage
from .ui.pages.macros import MacroPage
from .ui.pages.qmk import QmkSettingsPage
from .ui.pages.svalboard import SvalboardPage
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
        self._macros: MacroChanges | None = None
        self._tapdances: EntryChanges | None = None
        self._combos: EntryChanges | None = None
        self._overrides: EntryChanges | None = None
        self._qmk: SettingsChanges | None = None
        self._armed = None
        self._keycodes = None
        self._layer_names: dict[int, str] = {}

        self.setWindowTitle(APPLICATION_NAME)
        self.resize(1500, 900)

        self.canvas = KeyboardCanvas(theme)
        self.canvas.keySelected.connect(self._on_key_selected)
        self.canvas.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.canvas.customContextMenuRequested.connect(self._board_menu)

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

        # One picker at the bottom serves the board and every entry editor: whatever
        # is armed receives the next keycode chosen.
        self.macro_page = MacroPage(theme)
        self.tapdance_page = TapDancePage(theme)
        self.combo_page = ComboPage(theme)
        self.override_page = KeyOverridePage(theme)
        for page in (self.macro_page, self.tapdance_page, self.combo_page,
                     self.override_page):
            page.slotArmed.connect(self._arm_slot)
        self.qmk_page = QmkSettingsPage(theme)
        self.sval_page = SvalboardPage(theme)
        self.sval_page.statusRequested.connect(self._read_status)

        self.tabs = QTabWidget()
        self.tabs.addTab(board, "Keymap")
        self.tabs.addTab(self.macro_page, "Macros")
        self.tabs.addTab(self.tapdance_page, "Tap dances")
        self.tabs.addTab(self.combo_page, "Combos")
        self.tabs.addTab(self.override_page, "Key overrides")
        self.tabs.addTab(self.qmk_page, "QMK settings")
        self.tabs.addTab(self.sval_page, "Svalboard")
        self.tabs.currentChanged.connect(lambda _i: self._disarm())

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self.tabs)
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

        self.action_save = QAction("Save backup…", self)
        self.action_save.setShortcut(QKeySequence.StandardKey.Save)
        self.action_save.triggered.connect(self._save_backup)
        bar.addAction(self.action_save)

        self.action_load = QAction("Load backup…", self)
        self.action_load.setShortcut(QKeySequence.StandardKey.Open)
        self.action_load.triggered.connect(self._load_backup)
        bar.addAction(self.action_load)
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

    def _buffers(self) -> list:
        """Every edit buffer, so undo and commit treat them uniformly."""
        return [
            buffer
            for buffer in (
                self._changes, self._macros, self._tapdances,
                self._combos, self._overrides, self._qmk,
            )
            if buffer is not None
        ]

    def _pending_count(self) -> int:
        total = len(self._changes.pending()) if self._changes else 0
        for buffer in (self._tapdances, self._combos, self._overrides):
            if buffer is not None:
                total += len(buffer.pending())
        if self._macros is not None and self._macros.is_dirty:
            # The macro buffer is written whole, so it counts as one change however
            # many macros were touched.
            total += 1
        if self._qmk is not None:
            total += len(self._qmk.pending())
        return total

    def _update_actions(self) -> None:
        buffers = self._buffers()
        dirty = any(buffer.is_dirty for buffer in buffers)
        self.action_undo.setEnabled(any(buffer.can_undo for buffer in buffers))
        self.action_redo.setEnabled(any(buffer.can_redo for buffer in buffers))
        self.action_revert.setEnabled(dirty)

        blocked = self._macros is not None and not self._macros.fits()
        self.action_commit.setEnabled(dirty and not blocked)
        if blocked:
            self.action_commit.setText("Macros do not fit — cannot write")
        elif dirty:
            count = self._pending_count()
            self.action_commit.setText(
                f"Write {count} change{'' if count == 1 else 's'} to keyboard"
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

        self._macros = MacroChanges()
        self._macros.load(state.macros, size=state.capacities.macro_bytes)
        self._macros.subscribe(self._on_changes)
        self._tapdances = EntryChanges(empty=TapDance)
        self._tapdances.load(state.tap_dances)
        self._tapdances.subscribe(self._on_changes)
        self._combos = EntryChanges(empty=Combo)
        self._combos.load(state.combos)
        self._combos.subscribe(self._on_changes)
        self._overrides = EntryChanges(empty=KeyOverride)
        self._overrides.load(state.key_overrides)
        self._overrides.subscribe(self._on_changes)

        self._qmk = SettingsChanges()
        self._qmk.load(state.qmk_values, state.qmk_supported)
        self._qmk.subscribe(self._on_changes)

        self.macro_page.bind(self._macros, self._keycodes)
        self.qmk_page.bind(self._qmk)
        self._bind_svalboard_page(state)
        self.tapdance_page.bind(self._tapdances, self._keycodes)
        self.combo_page.bind(self._combos, self._keycodes)
        self.override_page.bind(
            self._overrides, self._keycodes, layers=state.capacities.layers
        )

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
        # Choosing a key on the board disarms any editor field, so the picker
        # cannot fill something the user has stopped looking at.
        self._disarm()

    def _board_menu(self, position) -> None:
        if self._changes is None or self.canvas.selected() < 0:
            return
        menu = QMenu(self)
        menu.addAction("Clear (disable)").triggered.connect(
            lambda: self._set_selected("KC_NO")
        )
        menu.addAction("Make transparent").triggered.connect(
            lambda: self._set_selected("KC_TRNS")
        )
        menu.addSeparator()
        menu.addAction("Assign and edit a macro").triggered.connect(
            self._assign_macro_here
        )
        menu.addAction("Assign and edit a tap dance").triggered.connect(
            self._assign_tapdance_here
        )
        menu.addSeparator()
        revert = menu.addAction("Revert this key")
        revert.setEnabled(
            self._changes.is_changed(self._current_layer(), self.canvas.selected())
        )
        revert.triggered.connect(
            lambda: self._changes.revert_key(
                self._current_layer(), self.canvas.selected()
            )
        )
        menu.exec(self.canvas.mapToGlobal(position))

    def _set_selected(self, name: str) -> None:
        if self._changes is None or self._keycodes is None:
            return
        kmid = self.canvas.selected()
        if kmid >= 0:
            self._changes.set_key(
                self._current_layer(), kmid, self._keycodes.parse(name)
            )

    # -- binding a keycode into whatever is armed ---------------------------------

    def _arm_slot(self, slot, setter) -> None:
        """A field in an entry editor asked for the next keycode chosen."""
        self._disarm()
        self._armed = (slot, setter)
        slot.set_active(True)
        self.statusBar().showMessage("Now choose a keycode below.", 4000)

    def _disarm(self) -> None:
        armed = getattr(self, "_armed", None)
        if armed is not None:
            armed[0].set_active(False)
        self._armed = None
        for page in (self.macro_page, self.tapdance_page, self.combo_page,
                     self.override_page):
            page.clear_arming()

    def _assign(self, info) -> None:
        armed = getattr(self, "_armed", None)
        if armed is not None:
            _slot, setter = armed
            self._armed = None
            setter(info.code)
            self._disarm()
            return

        if self._changes is None:
            return
        if self.tabs.currentIndex() != 0:
            self.statusBar().showMessage("Choose a field to fill first.", 4000)
            return
        kmid = self.canvas.selected()
        if kmid < 0:
            self.statusBar().showMessage("Choose a key on the board first.")
            return
        self._changes.set_key(self._current_layer(), kmid, info.code)

    # -- assign and edit ---------------------------------------------------------

    def _assign_macro_here(self) -> None:
        self._assign_into_first_empty("macro")

    def _assign_tapdance_here(self) -> None:
        self._assign_into_first_empty("tapdance")

    def _assign_into_first_empty(self, kind: str) -> None:
        """Bind the first unused macro or tap dance to the selected key, then edit it.

        Claiming a slot and jumping straight to its editor is the one interaction the
        web configurator gets conspicuously right, and it is worth keeping.
        """
        if self._changes is None or self._keycodes is None:
            return
        kmid = self.canvas.selected()
        if kmid < 0:
            self.statusBar().showMessage("Choose a key on the board first.")
            return

        if kind == "macro":
            index = self._macros.first_empty() if self._macros else None
            what, page = "macro", 1
        else:
            index = (
                self._tapdances.first_empty(lambda entry: entry.is_empty)
                if self._tapdances
                else None
            )
            what, page = "tap dance", 2

        if index is None:
            self._problem(
                f"No free {what}",
                f"Every {what} slot on this keyboard is in use. Clear one first.",
            )
            return

        name = f"M{index}" if kind == "macro" else f"TD({index})"
        self._changes.set_key(self._current_layer(), kmid, self._keycodes.parse(name))
        self.tabs.setCurrentIndex(page)
        if kind == "macro":
            self.macro_page.show_macro(index)
        self.statusBar().showMessage(f"Bound {name} to the selected key.", 4000)

    def _on_changes(self) -> None:
        self._show_layer(self._current_layer())
        self._update_actions()

    def _undo(self) -> None:
        # Undo applies to the buffer belonging to the visible tab, so it never
        # rewinds something the user cannot see.
        buffer = self._buffer_for_tab()
        if buffer is None or not buffer.can_undo:
            return
        edit = buffer.undo()
        if buffer is self._changes and edit is not None:
            self.layers.set_current(edit.layer)
            self._show_layer(edit.layer)
        self._rebuild_pages()

    def _redo(self) -> None:
        buffer = self._buffer_for_tab()
        if buffer is None or not buffer.can_redo:
            return
        edit = buffer.redo()
        if buffer is self._changes and edit is not None:
            self.layers.set_current(edit.layer)
            self._show_layer(edit.layer)
        self._rebuild_pages()

    def _buffer_for_tab(self):
        return {
            0: self._changes, 1: self._macros, 2: self._tapdances,
            3: self._combos, 4: self._overrides, 5: self._qmk,
        }.get(self.tabs.currentIndex())

    def _rebuild_pages(self) -> None:
        for page in (self.macro_page, self.tapdance_page, self.combo_page,
                     self.override_page, self.qmk_page):
            page.rebuild()

    def _revert_all(self) -> None:
        buffers = [buffer for buffer in self._buffers() if buffer.is_dirty]
        if not buffers:
            return
        if self._confirm(
            "Discard every change?",
            f"{self._pending_count()} unwritten changes will be discarded, across "
            "the keymap and every editor. The keyboard itself is untouched.",
            "Discard",
        ):
            for buffer in buffers:
                buffer.revert_all()
            self._rebuild_pages()

    def _commit(self) -> None:
        if self._keyboard is None:
            return
        count = self._pending_count()
        if not count:
            return
        if self._macros is not None and not self._macros.fits():
            self._problem(
                "The macros do not fit",
                "The macro set needs more room than the keyboard has. Shorten or "
                "clear a macro before writing.",
            )
            return
        if not self._confirm(
            "Write to the keyboard?",
            f"{count} change{'' if count == 1 else 's'} will be written to the "
            "keyboard. This takes effect immediately.",
            "Write",
        ):
            return

        written = 0
        try:
            if self._changes is not None:
                done = []
                for write in self._changes.pending():
                    self._keyboard.write_key(
                        write.layer, write.row, write.col, write.code
                    )
                    done.append(write)
                    written += 1
                self._changes.mark_written()

            for buffer, writer in (
                (self._tapdances, self._keyboard.write_tap_dance),
                (self._combos, self._keyboard.write_combo),
                (self._overrides, self._keyboard.write_key_override),
            ):
                if buffer is None:
                    continue
                applied = []
                for index, entry in buffer.pending():
                    writer(index, entry)
                    applied.append(index)
                    written += 1
                if applied:
                    buffer.mark_written(applied)

            if self._qmk is not None:
                applied = []
                for qsid, value in self._qmk.pending():
                    self._keyboard.qmk_settings().write(qsid, value)
                    applied.append(qsid)
                    written += 1
                if applied:
                    self._qmk.mark_written(applied)

            # Macros go last and go whole: they share one buffer, so there is no
            # partial state to leave behind if this is the step that fails.
            if self._macros is not None and self._macros.is_dirty:
                self._keyboard.write_macros(self._macros.working, self._macros.size)
                self._macros.mark_written()
                written += 1
        except TransportError as exc:
            self._rebuild_pages()
            self._problem(
                "The write was interrupted",
                f"{written} of {count} changes were written before the keyboard "
                f"stopped answering. The rest are still pending.\n\n{exc}",
            )
            return

        self._rebuild_pages()
        self.statusBar().showMessage(
            f"Wrote {written} change{'' if written == 1 else 's'}."
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

    # -- the Svalboard panel -----------------------------------------------------

    def _bind_svalboard_page(self, state) -> None:
        from .hid.console import ConsoleReader

        names = [
            str(entry.get("name") or "")
            for entry in state.definition.get("customKeycodes") or []
        ]
        bindings: dict[str, list[tuple[int, int, int]]] = {}
        per_layer = state.keys_per_layer
        for index, code in enumerate(state.keymap):
            name = self._keycodes.name(code)
            if name in names:
                layer, rest = divmod(index, per_layer)
                row, col = divmod(rest, state.cols)
                bindings.setdefault(name, []).append((layer, row, col))

        self.sval_page.bind(
            self._keycodes,
            custom_names=names,
            bindings=bindings,
            has_extension=state.identity.has_svalboard_extension,
            console_available=ConsoleReader().available,
        )

    def _read_status(self) -> None:
        """Listen to the console while 白い熊 presses the Output Status key.

        The host cannot trigger a keycode — only a physical press executes one — so
        this says which key to press rather than pretending to do it.
        """
        from .hid.console import ConsoleReader
        from .ui.pages.svalboard import describe_position

        if self._keyboard is None or self._keycodes is None:
            return
        state = self._keyboard.state
        try:
            target = self._keycodes.parse("SV_OUTPUT_STATUS")
        except ValueError:
            self.sval_page.show_status(
                "This keyboard has no Output Status keycode.", warning=True
            )
            return

        where = []
        per_layer = state.keys_per_layer
        for index, code in enumerate(state.keymap):
            if code == target:
                layer, rest = divmod(index, per_layer)
                row, col = divmod(rest, state.cols)
                where.append(describe_position(layer, row, col))

        if not where:
            self.sval_page.show_status(
                "Output Status is not bound to any key. Bind it from the picker "
                "first, write, and then read again.",
                warning=True,
            )
            return

        reader = ConsoleReader()
        if not reader.available:
            self.sval_page.show_status("No console interface.", warning=True)
            return

        self.sval_page.show_status(f"Press Output Status now — {where[0]}.")
        QApplication.processEvents()
        try:
            with reader:
                reader.drain()
                status = reader.read_status(seconds=6.0)
        except OSError as exc:
            self.sval_page.show_status(f"Could not read the console: {exc}", warning=True)
            return

        if status.is_empty:
            self.sval_page.show_status(
                "Nothing arrived on the console. The key may not have been pressed, "
                "or this firmware may not print its status.",
                warning=True,
            )
            return
        summary = status.summary()
        self.sval_page.show_status(
            summary or "Read, but nothing recognised:\n" + "\n".join(status.raw),
            warning=not summary,
        )

    # -- backups -----------------------------------------------------------------

    def _current_backup(self):
        assert self._keyboard is not None and self._changes is not None
        state = self._keyboard.state
        return build_backup(
            keyboard_id=state.identity.keyboard_id,
            layers=state.capacities.layers,
            rows=state.rows,
            cols=state.cols,
            codes=self._changes.working,
            keycodes=self._keycodes,
            layer_names=self._layer_names,
            macros=self._macros.working if self._macros else None,
            tap_dances=self._tapdances.working if self._tapdances else None,
            combos=self._combos.working if self._combos else None,
            key_overrides=self._overrides.working if self._overrides else None,
        )

    def _save_backup(self) -> None:
        if self._keyboard is None or self._changes is None:
            return
        default = str(Path.home() / "svalboard.kbi")
        chosen, _filter = QFileDialog.getSaveFileName(
            self, "Save a backup", default, "Keyboard backups (*.kbi);;All files (*)"
        )
        if not chosen:
            return
        path = Path(chosen)
        if not path.suffix:
            path = path.with_suffix(".kbi")
        try:
            backup = self._current_backup()
            save_kbi(path, backup)
        except OSError as exc:
            self._problem("Could not save", str(exc))
            return
        # What is saved is the working copy, unwritten edits included, which is worth
        # saying rather than leaving to be discovered.
        pending = self._pending_count()
        note = f" (including {pending} unwritten change{'' if pending == 1 else 's'})" if pending else ""
        self.statusBar().showMessage(f"Saved {path.name}{note}: {backup.describe()}.")

    def _load_backup(self) -> None:
        if self._keyboard is None or self._changes is None:
            self._problem("Not connected", "Connect a keyboard before loading a backup.")
            return
        chosen, _filter = QFileDialog.getOpenFileName(
            self, "Load a backup", str(Path.home()),
            "Keyboard backups (*.kbi *.json);;All files (*)",
        )
        if not chosen:
            return
        try:
            backup = load(Path(chosen))
        except FileFormatError as exc:
            self._problem("Could not load", str(exc))
            return

        state = self._keyboard.state
        warnings = check_fits(
            backup, layers=state.capacities.layers, rows=state.rows, cols=state.cols
        )
        detail = backup.describe()
        if warnings:
            detail += "\n\n" + "\n".join(warnings)
        if not self._confirm(
            "Load this backup?",
            f"{detail}\n\nIt is loaded as unwritten changes, so nothing reaches the "
            "keyboard until you write.",
            "Load",
        ):
            return

        self._apply_backup(backup)

    def _apply_backup(self, backup) -> None:
        assert self._changes is not None and self._keycodes is not None
        codes = backup.codes(self._keycodes)
        working = list(self._changes.working)
        for index, code in enumerate(codes[: len(working)]):
            layer, kmid = divmod(index, self._changes.keys_per_layer)
            self._changes.set_key(layer, kmid, code)

        if backup.macros and self._macros is not None:
            for index, macro in enumerate(backup.macro_objects(self._keycodes)):
                if index < len(self._macros):
                    self._macros.set(index, macro)
        for entries, buffer in (
            (backup.tap_dance_objects(self._keycodes) if backup.tap_dances else [], self._tapdances),
            (backup.combo_objects(self._keycodes) if backup.combos else [], self._combos),
            (backup.key_override_objects(self._keycodes) if backup.key_overrides else [], self._overrides),
        ):
            if buffer is None:
                continue
            for index, entry in enumerate(entries):
                if index < len(buffer):
                    buffer.set(index, entry)

        if backup.layer_names:
            self._layer_names.update(backup.layer_names)
        self._rebuild_pages()
        self._show_layer(self._current_layer())
        self.statusBar().showMessage(
            f"Loaded {backup.describe()}. Nothing has been written yet."
        )

    # -- export and import -------------------------------------------------------

    def export_categories(self) -> list:
        """The categories the Export / Import panel offers, given what is connected."""
        from .model.eximport import Category, tag_all, untag_all

        categories = [
            Category(
                "ui",
                "白い熊 Svalboard UI (colours · fonts · sizes)",
                collect=lambda: tag_all(self._theme.to_payload()),
                apply=lambda payload: self._theme.from_payload(untag_all(payload)),
            )
        ]
        if self._keyboard is None or self._changes is None:
            for key, title in (
                ("keymap", "Keymap and layers"), ("macros", "Macros"),
                ("tapdances", "Tap dances"), ("combos", "Combos"),
                ("overrides", "Key overrides"),
            ):
                categories.append(
                    Category(key, title, unavailable="no keyboard connected")
                )
        else:
            categories += [
                Category(
                    "keymap", "Keymap and layers",
                    collect=lambda: {
                        "keymap": self._current_backup().keymap,
                        "cosmetic": {str(k): v for k, v in self._layer_names.items()},
                    },
                    apply=self._apply_keymap_payload,
                ),
                Category("macros", "Macros",
                         collect=lambda: self._current_backup().macros,
                         apply=self._apply_macros_payload),
                Category("tapdances", "Tap dances",
                         collect=lambda: self._current_backup().tap_dances,
                         apply=self._apply_tapdances_payload),
                Category("combos", "Combos",
                         collect=lambda: self._current_backup().combos,
                         apply=self._apply_combos_payload),
                Category("overrides", "Key overrides",
                         collect=lambda: self._current_backup().key_overrides,
                         apply=self._apply_overrides_payload),
            ]
        categories.append(
            Category("layercolours", "Layer colours",
                     unavailable="needs firmware with the Svalboard 0xEE extension")
        )
        return categories

    def _restore(self, **fields) -> int:
        from .model.files import Backup

        backup = Backup(rows=self._changes.rows, cols=self._changes.cols, **fields)
        self._apply_backup(backup)
        # Only the collections are worth counting; `layers` is a number, not a
        # payload, and taking its length is what this used to do.
        return sum(
            len(value) for value in fields.values() if isinstance(value, (list, dict))
        )

    def _apply_keymap_payload(self, payload) -> int:
        keymap = payload.get("keymap") or []
        names = {int(k): v for k, v in (payload.get("cosmetic") or {}).items() if str(k).isdigit()}
        self._restore(keymap=keymap, layer_names=names, layers=len(keymap))
        return len(keymap)

    def _apply_macros_payload(self, payload) -> int:
        return self._restore(macros=list(payload))

    def _apply_tapdances_payload(self, payload) -> int:
        return self._restore(tap_dances=list(payload))

    def _apply_combos_payload(self, payload) -> int:
        return self._restore(combos=list(payload))

    def _apply_overrides_payload(self, payload) -> int:
        return self._restore(key_overrides=list(payload))

    # -- settings ----------------------------------------------------------------

    def _open_settings(self) -> None:
        self._open_ui_settings()

    def _open_ui_settings(self) -> None:
        from .ui.settings.ui_page import UiSettingsWindow

        window = UiSettingsWindow(self._theme, self, categories=self.export_categories)
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

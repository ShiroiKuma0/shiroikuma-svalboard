# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 白い熊
"""白い熊 Svalboard UI — the settings page, generated from the registry.

Nothing here enumerates settings by hand: the page walks
:data:`svalboard.ui.theme.spec.GROUPS` and builds a row per entry, so a new setting
appears simply by being declared. The page also styles itself from the same theme it
edits, which is what makes it its own live preview — move a slider and the heading,
the indents and the row spacing on this very page follow it.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QLabel,
    QMainWindow,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..theme import GROUPS, Group, Kind, Setting, Subgroup, Theme
from ..widgets.house import (
    Hairline,
    Heading,
    PillButton,
    Row,
    SliderRow,
    Swatch,
    ToggleRow,
    button_row,
)
from .colour_dialog import ColourDialog
from .font_dialog import FontDialog

TITLE = "白い熊 Svalboard UI"


class ColourRow(Row):
    """A colour setting: chip and hex on the right, picker on click."""

    def __init__(self, setting: Setting, theme: Theme, *, level: int) -> None:
        super().__init__(
            setting.title, theme, level=level, description=setting.description
        )
        self._setting = setting
        self._theme = theme

        self.hex = QLabel()
        # Deliberately smaller than the family's 38 dp chip: at that size the chip
        # sets the row height and colour rows stand a third taller than slider rows,
        # which breaks the tight rhythm the page depends on.
        self.chip = Swatch(theme, str(theme[setting.key]), size=24)
        self.chip.clicked.connect(self._open)
        self.add_control(self.hex)
        self.add_control(self.chip)

        theme.setting_changed.connect(self._on_setting_changed)
        self._sync()

    def _on_setting_changed(self, key: str) -> None:
        if key == self._setting.key:
            self._sync()

    def _sync(self) -> None:
        value = str(self._theme[self._setting.key])
        self.hex.setText(value)
        self.hex.setStyleSheet(f"color: {self._theme.css('row.description.colour')};")
        self.chip.set_colour(value)

    def _open(self) -> None:
        dialog = ColourDialog(
            self._theme,
            str(self._theme[self._setting.key]),
            title=self._setting.title,
            on_change=lambda value: self._theme.set(self._setting.key, value),
            parent=self.window(),
        )
        dialog.exec()


class FontRow(Row):
    """A font setting: the family name rendered in its own face."""

    def __init__(self, setting: Setting, theme: Theme, *, level: int) -> None:
        super().__init__(
            setting.title, theme, level=level, description=setting.description
        )
        self._setting = setting
        self._theme = theme

        self.value = PillButton("", theme)
        self.value.clicked.connect(self._open)
        self.add_control(self.value)

        theme.setting_changed.connect(self._on_setting_changed)
        self._sync()

    def _on_setting_changed(self, key: str) -> None:
        if key == self._setting.key:
            self._sync()

    def _sync(self) -> None:
        from ..widgets.house import themed_font

        family = str(self._theme[self._setting.key])
        self.value.setText(family or "System default")
        self.value.setFont(themed_font(family, 400, int(self._theme["row.title.size"])))

    def _open(self) -> None:
        dialog = FontDialog(
            self._theme,
            str(self._theme[self._setting.key]),
            title=self._setting.title,
            on_change=lambda value: self._theme.set(self._setting.key, value),
            parent=self.window(),
        )
        if dialog.exec():
            self._theme.set(self._setting.key, dialog.value())


class UiSettingsPage(QWidget):
    """The scrollable body of the page."""

    #: Asked to open the Export / Import panel.
    eximportRequested = pyqtSignal()

    def __init__(self, theme: Theme, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._theme = theme

        self._column = QVBoxLayout(self)
        self._column.setContentsMargins(0, 0, 0, 24)
        self._column.setAlignment(Qt.AlignmentFlag.AlignTop)

        self._add_eximport()
        for group in GROUPS:
            self._add_group(group, first=False)
        self._column.addStretch(1)

        theme.changed.connect(self._respace)
        self._respace()

    def _add_eximport(self) -> None:
        """The first section, ahead of appearance, as in the family's other apps."""
        self._column.addWidget(Heading("Export / Import", self._theme, level=0))
        row = Row(
            "Export / Import",
            self._theme,
            level=1,
            description="Save every setting to a backup, or restore one.",
        )
        self.eximport_status = QLabel()
        self.eximport_status.setWordWrap(True)
        open_button = PillButton("Open…", self._theme)
        open_button.clicked.connect(self.eximportRequested)
        row.add_control(open_button)
        self._column.addWidget(row)

        self.eximport_status.setContentsMargins(int(self._theme["row.indent"]), 0, 16, 4)
        self._column.addWidget(self.eximport_status)
        self.refresh_eximport_status()

    def refresh_eximport_status(self) -> None:
        """Mirror the backup state onto the page, red when no directory is set."""
        from .eximport_panel import (
            DIRECTORY_KEY,
            NO_DIRECTORY_HINT,
            NO_EXPORT_YET,
        )
        from ...model.eximport import latest_export

        stored = self._theme.settings.value(DIRECTORY_KEY, "", type=str)
        if not stored:
            text, warning = NO_DIRECTORY_HINT, True
        else:
            newest = latest_export(Path(str(stored)))
            if newest is None:
                text, warning = NO_EXPORT_YET, True
            else:
                when = datetime.fromtimestamp(newest.stat().st_mtime)
                text = f"Last export: {when:%Y-%m-%d %H:%M:%S}"
                warning = False
        colour = (
            self._theme.css("window.warning") if warning else self._theme.css("window.text")
        )
        self.eximport_status.setText(text)
        self.eximport_status.setStyleSheet(f"color: {colour};")

    def _respace(self) -> None:
        self._column.setSpacing(int(self._theme["row.spacing"]))

    def _add_group(self, group: Group, *, first: bool) -> None:
        # The hairline marks the boundary with the group above, so the first group
        # does not get one — there is nothing above it.
        if not first:
            self._column.addWidget(Hairline(self._theme))
        self._column.addWidget(Heading(group.title, self._theme, level=0))

        if group.description:
            note = QLabel(group.description)
            note.setWordWrap(True)
            note.setContentsMargins(int(self._theme["row.indent"]), 0, 16, 4)
            note.setStyleSheet(f"color: {self._theme.css('row.description.colour')};")
            self._column.addWidget(note)

        for setting in group.settings:
            self._column.addWidget(self._row(setting, level=1))
        for subgroup in group.subgroups:
            self._add_subgroup(subgroup)

    def _add_subgroup(self, subgroup: Subgroup) -> None:
        self._column.addWidget(Heading(subgroup.title, self._theme, level=1))
        for setting in subgroup.settings:
            self._column.addWidget(self._row(setting, level=2))

    def _row(self, setting: Setting, *, level: int) -> QWidget:
        theme = self._theme
        if setting.kind is Kind.COLOUR:
            return ColourRow(setting, theme, level=level)
        if setting.kind is Kind.FONT:
            return FontRow(setting, theme, level=level)
        if setting.kind is Kind.TOGGLE:
            row = ToggleRow(
                setting.title,
                theme,
                checked=bool(theme[setting.key]),
                level=level,
                description=setting.description,
            )
            row.toggled.connect(lambda value: theme.set(setting.key, value))
            return row

        title = f"{setting.title} ({setting.unit})" if setting.unit else setting.title
        row = SliderRow(
            title,
            theme,
            minimum=setting.minimum,
            maximum=setting.maximum,
            value=int(theme[setting.key]),
            unit=setting.unit,
            level=level,
            description=setting.description,
        )
        row.valueChanged.connect(lambda value: theme.set(setting.key, value))
        return row


class UiSettingsWindow(QMainWindow):
    """The page in its own window, so the board stays visible behind it."""

    def __init__(self, theme: Theme, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._theme = theme
        self.setWindowTitle(TITLE)
        self.resize(760, 940)

        body = QWidget()
        column = QVBoxLayout(body)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(0)

        title = Heading(TITLE, theme, level=0)
        column.addWidget(title)

        self.page = UiSettingsPage(theme)
        self.page.eximportRequested.connect(self._open_eximport)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.page)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        column.addWidget(scroll, 1)

        footer = button_row(
            theme,
            ("Close", self.close),
            [("Reset everything", self._reset)],
        )
        footer.setContentsMargins(16, 0, 16, 12)
        column.addWidget(footer)

        self.setCentralWidget(body)
        theme.changed.connect(lambda: self.setStyleSheet(theme.stylesheet()))
        self.setStyleSheet(theme.stylesheet())

    def _open_eximport(self) -> None:
        from ...model.eximport import Archive, Category, tag_all, untag_all
        from .eximport_panel import ExportImportPanel
        from .font_dialog import font_directory

        categories = [
            Category(
                "ui",
                "白い熊 Svalboard UI (colours · fonts · sizes)",
                collect=lambda: tag_all(self._theme.to_payload()),
                apply=lambda payload: self._theme.from_payload(untag_all(payload)),
            ),
            # The rest exist as declared-but-unavailable so the panel can say why,
            # rather than quietly omitting them and looking complete.
            Category("keymap", "Keymap and layers",
                     unavailable="exported from the board with Save backup"),
            Category("macros", "Macros", unavailable="arrives with the macro editor"),
            Category("tapdances", "Tap dances", unavailable="arrives with the tap-dance editor"),
            Category("combos", "Combos", unavailable="arrives with the combo editor"),
            Category("overrides", "Key overrides", unavailable="arrives with the override editor"),
            Category("qmk", "QMK settings", unavailable="arrives with the QMK settings page"),
            Category("layercolours", "Layer colours",
                     unavailable="needs firmware with the Svalboard 0xEE extension"),
        ]
        fonts = {
            f"fonts/{path.name}": path
            for path in font_directory().iterdir()
            if path.is_file() and path.suffix.lower() in (".ttf", ".otf")
        }

        panel = ExportImportPanel(
            self._theme, Archive(categories), extra_files=fonts, parent=self
        )
        panel.chainFinished.connect(self.close)
        panel.exec()
        self.page.refresh_eximport_status()

    def _reset(self) -> None:
        from PyQt6.QtWidgets import QMessageBox

        box = QMessageBox(self)
        box.setWindowTitle("Reset every appearance setting?")
        box.setText("Reset every appearance setting?")
        box.setInformativeText(
            "Every colour, font and size returns to the 白い熊 defaults. Your keymap "
            "is not affected."
        )
        reset = box.addButton("Reset", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is reset:
            self._theme.reset_all()

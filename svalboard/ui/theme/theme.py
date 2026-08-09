# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 白い熊
"""The live theme: current values, persistence, and the stylesheet built from them.

Every widget styles itself from here, and every change re-emits :attr:`Theme.changed`,
so the whole interface repaints as a slider moves. That is what makes the settings page
its own preview — the page being adjusted is drawn with the values being adjusted.

Values are stored only when they differ from the default, so a fresh profile is an
empty file and a later change to a default reaches anyone who never overrode it.
"""

from __future__ import annotations

from typing import Any

from PyQt6.QtCore import QObject, QSettings, pyqtSignal
from PyQt6.QtGui import QColor

from .spec import DEFAULTS, GROUPS, SWATCH_SEEDS, Kind, Setting, all_settings

ORGANISATION = "shiroikuma"
APPLICATION = "svalboard"

#: The recent-colour list lives apart from the theme itself: it is a scratchpad, not a
#: setting, and it must never travel in an export.
SWATCH_GROUP = "colour-picker"
MAX_SWATCHES = 8


def _to_qcolour(value: object) -> QColor:
    colour = QColor(str(value))
    return colour if colour.isValid() else QColor("#FFFF00")


def css_colour(value: object) -> str:
    """``#AARRGGBB`` as the ``rgba()`` form Qt stylesheets understand."""
    colour = _to_qcolour(value)
    return (
        f"rgba({colour.red()}, {colour.green()}, {colour.blue()}, "
        f"{colour.alpha() / 255:.3f})"
    )


class Theme(QObject):
    """Current values for every declared setting."""

    changed = pyqtSignal()
    #: Emitted with the key whenever one setting changes, for targeted repaints.
    setting_changed = pyqtSignal(str)

    def __init__(self, settings: QSettings | None = None) -> None:
        super().__init__()
        self._settings = settings or QSettings(ORGANISATION, APPLICATION)
        self._spec = all_settings()
        self._values: dict[str, Any] = {}
        self.reload()

    # -- values ------------------------------------------------------------------

    def reload(self) -> None:
        self._values.clear()
        self._settings.beginGroup("theme")
        for key, setting in self._spec.items():
            if not self._settings.contains(key):
                continue
            stored = self._settings.value(key)
            self._values[key] = _coerce(setting, stored)
        self._settings.endGroup()
        self.changed.emit()

    def __getitem__(self, key: str) -> Any:
        return self._values.get(key, DEFAULTS[key])

    def get(self, key: str, fallback: Any = None) -> Any:
        if key in self._spec:
            return self[key]
        return fallback

    def is_default(self, key: str) -> bool:
        return key not in self._values

    def set(self, key: str, value: Any, *, persist: bool = True) -> None:
        setting = self._spec.get(key)
        if setting is None:
            raise KeyError(f"No such setting: {key}")
        value = _coerce(setting, value)

        if value == DEFAULTS[key]:
            self._values.pop(key, None)
            if persist:
                self._settings.remove(f"theme/{key}")
        else:
            if self._values.get(key) == value:
                return
            self._values[key] = value
            if persist:
                self._settings.setValue(f"theme/{key}", value)

        self.setting_changed.emit(key)
        self.changed.emit()

    def reset(self, key: str) -> None:
        self.set(key, DEFAULTS[key])

    def reset_all(self) -> None:
        self._values.clear()
        self._settings.beginGroup("theme")
        self._settings.remove("")
        self._settings.endGroup()
        self.changed.emit()

    def colour(self, key: str) -> QColor:
        return _to_qcolour(self[key])

    def css(self, key: str) -> str:
        return css_colour(self[key])

    # -- export and import -------------------------------------------------------

    def to_payload(self) -> dict[str, Any]:
        """Only the overrides, so an export stays small and forward-compatible."""
        return dict(sorted(self._values.items()))

    def from_payload(self, payload: dict[str, Any]) -> int:
        """Apply an exported payload, ignoring settings this version dropped."""
        applied = 0
        for key, value in payload.items():
            if key not in self._spec:
                continue
            self.set(key, value)
            applied += 1
        return applied

    # -- the recent-colour scratchpad --------------------------------------------

    def swatches(self) -> list[str]:
        stored = self._settings.value(f"{SWATCH_GROUP}/recent", "", type=str)
        recent = [item for item in str(stored).split(",") if item]
        merged: list[str] = []
        for colour in [*recent, *SWATCH_SEEDS]:
            if colour not in merged:
                merged.append(colour)
        return merged[:MAX_SWATCHES]

    def remember_swatch(self, colour: str) -> None:
        merged = [colour] + [item for item in self.swatches() if item != colour]
        self._settings.setValue(
            f"{SWATCH_GROUP}/recent", ",".join(merged[:MAX_SWATCHES])
        )

    # -- the stylesheet ----------------------------------------------------------

    def stylesheet(self) -> str:
        """The application-wide stylesheet.

        Breeze is replaced rather than extended here. That is the point of the house
        style, but it means every colour a widget uses has to be stated — anything
        left unstated falls back to the platform theme and shows up as a pale patch.
        """
        pad_h, pad_v = self["button.padding_h"], self["button.padding_v"]
        corner = min(int(self["button.corner"]), 999)
        return f"""
        QWidget {{
            background: {self.css('window.background')};
            color: {self.css('window.text')};
            font-family: "{self['window.base.font'] or 'Sans'}";
            font-size: {self['window.base.size']}pt;
            font-weight: {self['window.base.weight']};
        }}
        QWidget:disabled {{ color: {self.css('window.disabled')}; }}

        QScrollArea, QScrollArea > QWidget > QWidget {{ border: none; }}
        QToolTip {{
            background: {self.css('dialog.background')};
            color: {self.css('dialog.body.colour')};
            border: {self['dialog.border_width']}px solid {self.css('dialog.border')};
            padding: 6px;
        }}

        QPushButton {{
            background: {self.css('button.background')};
            color: {self.css('button.text')};
            border: {self['button.border_width']}px solid {self.css('button.border')};
            border-radius: {corner}px;
            padding: {pad_v}px {pad_h}px;
        }}
        QPushButton:hover {{ background: rgba(255, 255, 0, 0.12); }}
        QPushButton:pressed {{ background: rgba(255, 255, 0, 0.20); }}
        QPushButton:disabled {{
            color: {self.css('button.disabled')};
            border-color: {self.css('button.disabled')};
        }}

        QLineEdit, QSpinBox, QComboBox, QPlainTextEdit, QTextEdit {{
            background: {self.css('window.background')};
            color: {self.css('window.text')};
            border: {self['key.border_width']}px solid {self.css('key.border')};
            border-radius: 4px;
            padding: 2px 6px;
            selection-background-color: {self.css('window.text')};
            selection-color: {self.css('window.background')};
        }}
        QComboBox QAbstractItemView {{
            background: {self.css('window.background')};
            color: {self.css('window.text')};
            border: {self['dialog.border_width']}px solid {self.css('dialog.border')};
            selection-background-color: rgba(255, 255, 0, 0.20);
        }}

        QCheckBox, QRadioButton {{ spacing: 8px; }}
        QCheckBox::indicator, QRadioButton::indicator {{
            width: 14px; height: 14px;
            border: 2px solid {self.css('window.text')};
            background: {self.css('window.background')};
        }}
        QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
            background: {self.css('window.text')};
        }}
        QRadioButton::indicator {{ border-radius: 9px; }}

        QSlider::groove:horizontal {{
            height: 2px;
            background: {self.css('window.dim')};
        }}
        QSlider::handle:horizontal {{
            width: 12px; margin: -7px 0;
            background: {self.css('window.text')};
            border-radius: 2px;
        }}

        QScrollBar:vertical, QScrollBar:horizontal {{
            background: {self.css('window.background')};
            width: 10px; height: 10px;
        }}
        QScrollBar::handle {{ background: {self.css('window.dim')}; border-radius: 5px; }}
        QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
        QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

        QToolButton {{
            background: transparent;
            border: none;
            padding: 4px;
        }}
        QToolButton:hover {{ background: rgba(255, 255, 0, 0.12); }}

        QMenu {{
            background: {self.css('dialog.background')};
            border: {self['dialog.border_width']}px solid {self.css('dialog.border')};
        }}
        QMenu::item:selected {{ background: rgba(255, 255, 0, 0.20); }}
        """


def _coerce(setting: Setting, value: Any) -> Any:
    """QSettings on Linux writes INI, which loses types — put them back."""
    if setting.kind is Kind.COLOUR:
        colour = QColor(str(value))
        return colour.name(QColor.NameFormat.HexArgb).upper() if colour.isValid() else setting.default
    if setting.kind is Kind.TOGGLE:
        if isinstance(value, str):
            return value.strip().lower() in ("true", "1", "yes")
        return bool(value)
    if setting.kind is Kind.FONT:
        return str(value)
    try:
        number = int(value)
    except (TypeError, ValueError):
        return setting.default
    return max(setting.minimum, min(setting.maximum, number))


def group_titles() -> list[str]:
    return [group.title for group in GROUPS]

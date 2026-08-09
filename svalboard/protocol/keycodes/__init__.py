# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 白い熊
"""Naming, parsing and describing keycodes.

A keycode is sixteen bits and means one of several quite different things depending on
its range: a plain HID usage, a basic keycode wearing a modifier mask, a mod-tap, a
layer-tap, a layer operation, a macro, a tap dance, or one of the keyboard's own custom
keycodes. :class:`KeycodeSet` resolves all of those, because several of the families
are sized by the connected keyboard — how many layers, macros and tap dances it has,
and what its custom keycodes are called — and so cannot live in a static table.

The static half comes from :mod:`svalboard.protocol.keycodes.table`, which is generated
from vial-gui; see ``tools/generate_keycodes.py``.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from .table import ALIASES, CATEGORIES, KEYCODES, LABELS, MASKED, TOOLTIPS

KIND_BASIC = "basic"
KIND_MASKED = "masked"
KIND_LAYER = "layer"
KIND_MACRO = "macro"
KIND_TAP_DANCE = "tapdance"
KIND_CUSTOM = "custom"
KIND_UNSET = "unset"
KIND_UNKNOWN = "unknown"

#: Erased flash reads back as all ones, so a keymap position the firmware has never
#: written comes across as 0xFFFF. It is not a broken keycode and should not be shown
#: as one — it simply means "never set", and writing anything to it fixes it.
UNSET = 0xFFFF

#: Layer operations, as prefix base and the tooltip that explains them.
LAYER_OPERATIONS = (
    ("MO", "QK_MOMENTARY", "While held, activate layer {n}."),
    ("TO", "QK_TO", "Switch to layer {n}, turning every other layer off."),
    ("DF", "QK_DEF_LAYER", "Make layer {n} the default."),
    ("TG", "QK_TOGGLE_LAYER", "Toggle layer {n} on or off."),
    ("OSL", "QK_ONE_SHOT_LAYER", "Activate layer {n} for one key press."),
    ("TT", "QK_LAYER_TAP_TOGGLE", "Tap to toggle layer {n}, hold for momentary."),
)

_HEX = re.compile(r"^(?:0x)?([0-9a-fA-F]{1,4})$")
_TEMPLATE_CALL = re.compile(r"^([A-Za-z0-9_]+)\((.*)\)$")


@dataclass(frozen=True)
class KeycodeInfo:
    """Everything the interface needs in order to draw and explain one keycode."""

    code: int
    name: str
    label: str
    tooltip: str
    kind: str

    @property
    def is_empty(self) -> bool:
        return self.code == 0x0000

    @property
    def is_transparent(self) -> bool:
        return self.code == 0x0001

    @property
    def is_unset(self) -> bool:
        return self.code == UNSET


def _preference(name: str) -> tuple[int, int, str]:
    """Sort key picking the friendliest of several names for one code.

    ``QK_`` names are the firmware's structural constants and make poor labels, so
    ``MO(0)`` wins over ``QK_MOMENTARY`` and ``LCTL(kc)`` over ``QK_LCTL``.
    """
    return (name.startswith("QK_"), len(name), name)


class KeycodeSet:
    """Keycode naming for one connected keyboard.

    ``custom_keycodes`` is the ``customKeycodes`` array out of the keyboard's own
    definition, so the Svalboard's ``SV_*`` keys name themselves rather than appearing
    as ``USER00``.
    """

    def __init__(
        self,
        *,
        layers: int = 16,
        macros: int = 0,
        tap_dances: int = 0,
        custom_keycodes: Sequence[dict] = (),
    ) -> None:
        self.layers = layers
        self.macros = macros
        self.tap_dances = tap_dances

        self._by_code: dict[int, str] = {}
        self._templates: dict[int, str] = {}
        self._by_name: dict[str, int] = {}
        self._labels: dict[str, str] = dict(LABELS)
        self._tooltips: dict[str, str] = dict(TOOLTIPS)

        for name, code in KEYCODES.items():
            self._by_name[name] = code
            if "(kc)" in name:
                self._templates[code] = name
                continue
            existing = self._by_code.get(code)
            if existing is None or _preference(name) < _preference(existing):
                self._by_code[code] = name
        for alias, canonical in ALIASES.items():
            self._by_name.setdefault(alias, KEYCODES[canonical])

        self._add_layers()
        self._add_macros()
        self._add_tap_dances()
        self._add_custom(custom_keycodes)

    # -- runtime families --------------------------------------------------------

    def _register(self, name: str, code: int, label: str, tooltip: str) -> None:
        self._by_code[code] = name
        self._by_name[name] = code
        self._labels[name] = label
        self._tooltips[name] = tooltip

    def _add_layers(self) -> None:
        for prefix, base_name, tooltip in LAYER_OPERATIONS:
            base = KEYCODES.get(base_name)
            if base is None:
                continue
            for layer in range(self.layers):
                self._register(
                    f"{prefix}({layer})",
                    base + layer,
                    f"{prefix}\n{layer}",
                    tooltip.format(n=layer),
                )

    def _add_macros(self) -> None:
        base = KEYCODES.get("QK_MACRO")
        if base is None:
            return
        for index in range(self.macros):
            self._register(
                f"M{index}", base + index, f"M{index}", f"Run macro {index}."
            )

    def _add_tap_dances(self) -> None:
        base = KEYCODES.get("QK_TAP_DANCE")
        if base is None:
            return
        for index in range(self.tap_dances):
            self._register(
                f"TD({index})",
                base + index,
                f"TD\n{index}",
                f"Run tap dance {index}.",
            )

    def _add_custom(self, custom_keycodes: Sequence[dict]) -> None:
        base = KEYCODES.get("QK_KB")
        if base is None:
            return
        for index, entry in enumerate(custom_keycodes):
            name = str(entry.get("name") or f"USER{index:02d}")
            label = str(entry.get("shortName") or name)
            tooltip = str(entry.get("title") or name)
            code = base + index
            self._register(name, code, label, tooltip)
            # The positional spelling stays valid, so files written against USER07
            # still load on a board that calls it SV_MH_CHANGE_TIMEOUTS.
            self._by_name[f"USER{index:02d}"] = code

    # -- keyboard layout ---------------------------------------------------------

    def apply_layout(self, glyphs: dict[str, tuple[str, str]] | None) -> None:
        """Relabel keys by what they type on a given keyboard layout.

        A keycode names a position, not a character, so on a Czech or German layout
        ``KC_Y`` types ``z``. Only the label changes — the keycode written to the
        keyboard is unaffected, and searching by name still works, because the layout
        is a fact about the computer rather than about the keyboard.
        """
        self._labels = dict(LABELS)
        self._layout_glyphs = dict(glyphs or {})
        if not glyphs:
            return

        shift = KEYCODES.get("QK_LSFT", 0x0200)
        for name, (unshifted, shifted) in glyphs.items():
            code = self._by_name.get(name)
            if code is None:
                continue
            if unshifted:
                self._labels[name] = unshifted
            # The shifted form is its own keycode — KC_EXLM rather than LSFT(KC_1) —
            # so it needs relabelling separately or it keeps the US character.
            if shifted and code <= 0xFF:
                shifted_name = self._by_code.get(shift | code)
                if shifted_name:
                    self._labels[shifted_name] = shifted

    @property
    def layout_glyphs(self) -> dict[str, tuple[str, str]]:
        return dict(getattr(self, "_layout_glyphs", {}))

    # -- naming ------------------------------------------------------------------

    def name(self, code: int) -> str:
        """The canonical spelling of ``code``, or bare hex when nothing claims it."""
        code &= 0xFFFF
        direct = self._by_code.get(code)
        if direct is not None:
            return direct

        outer, inner = code & 0xFF00, code & 0x00FF
        if outer in MASKED:
            template = self._templates.get(outer)
            inner_name = self._by_code.get(inner)
            if template is not None and inner_name is not None:
                return template.replace("(kc)", f"({inner_name})")
        return f"0x{code:04X}"

    def parse(self, text: str | int) -> int:
        """Turn a spelling back into a code. Accepts names, aliases, decimal and hex."""
        if isinstance(text, int):
            return text & 0xFFFF
        value = text.strip()
        if not value:
            return 0

        known = self._by_name.get(value)
        if known is not None:
            return known

        call = _TEMPLATE_CALL.match(value)
        if call is not None:
            outer, inner = call.group(1), call.group(2).strip()
            template = f"{outer}(kc)"
            if template in self._by_name and inner:
                return (self._by_name[template] | (self.parse(inner) & 0x00FF)) & 0xFFFF

        hexed = _HEX.match(value)
        if hexed is not None and (value.lower().startswith("0x") or not value.isdigit()):
            return int(hexed.group(1), 16) & 0xFFFF
        if value.isdigit():
            return int(value) & 0xFFFF
        raise ValueError(f"Not a keycode: {text!r}")

    def kind(self, code: int) -> str:
        code &= 0xFFFF
        if code == UNSET:
            return KIND_UNSET
        name = self.name(code)
        if name.startswith("0x"):
            return KIND_UNKNOWN
        if self.macros and KEYCODES["QK_MACRO"] <= code < KEYCODES["QK_MACRO"] + self.macros:
            return KIND_MACRO
        base = KEYCODES.get("QK_TAP_DANCE", 0)
        if self.tap_dances and base <= code < base + self.tap_dances:
            return KIND_TAP_DANCE
        if any(name.startswith(f"{prefix}(") for prefix, _, _ in LAYER_OPERATIONS):
            return KIND_LAYER
        kb = KEYCODES.get("QK_KB", 0)
        if kb <= code <= kb + 0xFF and name != f"0x{code:04X}":
            return KIND_CUSTOM
        if (code & 0xFF00) in MASKED:
            return KIND_MASKED
        return KIND_BASIC

    def info(self, code: int) -> KeycodeInfo:
        code &= 0xFFFF
        if code == UNSET:
            return KeycodeInfo(
                code=code,
                name="KC_NO",
                label="",
                tooltip="Never set — this position has not been written since the "
                "keyboard was flashed. Assigning any key fixes it.",
                kind=KIND_UNSET,
            )
        name = self.name(code)
        label = self._labels.get(name)
        if label is None:
            outer, inner = code & 0xFF00, code & 0x00FF
            if outer in MASKED:
                inner_name = self._by_code.get(inner, "")
                label = self._labels.get(inner_name, inner_name.removeprefix("KC_"))
            else:
                label = name.removeprefix("KC_")
        return KeycodeInfo(
            code=code,
            name=name,
            label=label,
            tooltip=self._tooltips.get(name, name),
            kind=self.kind(code),
        )

    # -- searching ---------------------------------------------------------------

    def search(self, query: str, limit: int = 60) -> list[KeycodeInfo]:
        """Find keycodes by name, alias, label or description.

        The web configurator has no search at all: roughly 1,600 keycodes are spread
        across a dozen tabs and finding one means knowing which tab it lives in.
        """
        needle = query.strip().lower()
        if not needle:
            return []

        try:
            exact = self.parse(query)
        except ValueError:
            exact = None

        scored: list[tuple[tuple[int, int, str], KeycodeInfo]] = []
        seen: set[int] = set()
        for name, code in self._by_name.items():
            if code in seen:
                continue
            info = self.info(code)
            haystacks = (name.lower(), info.label.lower().replace("\n", " "), info.tooltip.lower())
            if needle == name.lower():
                rank = 0
            elif any(h.startswith(needle) for h in haystacks):
                rank = 1
            elif any(needle in h for h in haystacks):
                rank = 2
            else:
                continue
            seen.add(code)
            scored.append(((rank, len(name), name), info))

        scored.sort(key=lambda pair: pair[0])
        results = [info for _, info in scored[:limit]]
        if exact is not None and exact not in seen:
            results.insert(0, self.info(exact))
        return results

    def category(self, name: str) -> list[KeycodeInfo]:
        """One picker tab's contents, skipping anything this board cannot use."""
        return [
            self.info(KEYCODES[qmk_id])
            for qmk_id in CATEGORIES.get(name, ())
            if qmk_id in KEYCODES and "(kc)" not in qmk_id
        ]

    def categories(self) -> list[str]:
        return list(CATEGORIES)

    def iter_codes(self) -> Iterable[int]:
        return iter(sorted(set(self._by_name.values())))

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
#: Not a keycode but the outer half of one — ``LGUI(kc)``, ``LT2(kc)``. It cannot be
#: assigned as it stands; picking one asks for the inner keycode that completes it.
KIND_TEMPLATE = "template"

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

#: The four modifier bits a basic keycode can wear, in the order they are offered.
#: "Super" is what the GUI modifier is called on this desktop; QMK spells it GUI.
MODIFIERS = (
    (0x0100, "Ctrl"),
    (0x0200, "Shift"),
    (0x0400, "Alt"),
    (0x0800, "Super"),
)

#: Set alongside the four bits above, this selects the right-hand modifiers instead
#: of the left. It is one flag for all four — QMK cannot mix left Ctrl with right Alt
#: in a single keycode.
MODIFIER_RIGHT = 0x1000

#: Where the modifier bits live. The same five bits serve plain modified keycodes and
#: mod-taps, which is why one implementation covers both.
MODIFIER_MASK = 0x1F00

#: Modified basic keycodes occupy 0x0000–0x1FFF and mod-taps 0x2000–0x3FFF; from
#: 0x4000 up the same bits mean a layer, so modifiers cannot be added there.
MODIFIABLE_LIMIT = 0x4000

_HEX = re.compile(r"^(?:0x)?([0-9a-fA-F]{1,4})$")
_TEMPLATE_CALL = re.compile(r"^([A-Za-z0-9_]+)\((.*)\)$")


def modifiable(code: int) -> bool:
    """Whether modifiers can be added to or removed from ``code``.

    True for a plain basic keycode and for anything already wearing modifiers,
    including a mod-tap. False for layer operations, layer-taps, macros, tap dances
    and the keyboard's own keycodes, none of which have room for the bits.
    """
    return 0 <= (code & 0xFFFF) < MODIFIABLE_LIMIT


def modifier_mask(code: int) -> int:
    """The modifier bits ``code`` currently carries."""
    return code & MODIFIER_MASK if modifiable(code) else 0


def with_modifiers(code: int, mask: int) -> int:
    """``code`` rewritten to carry exactly the modifiers in ``mask``."""
    return (code & ~MODIFIER_MASK & 0xFFFF) | (mask & MODIFIER_MASK)


#: How each modifier is abbreviated in a key's corner strip, matching the table's own
#: spelling of the combinations it does name (``LCtl``, ``RSft``).
_MODIFIER_SHORT = {0x0100: "Ctl", 0x0200: "Sft", 0x0400: "Alt", 0x0800: "Gui"}


def modifier_label(mask: int) -> str:
    """The modifiers in ``mask``, spelled for a corner strip: ``RCtl+RSft``."""
    side = "R" if mask & MODIFIER_RIGHT else "L"
    return "+".join(
        f"{side}{_MODIFIER_SHORT[bit]}" for bit, _ in MODIFIERS if mask & bit
    )


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

        # Twelve of the thirty modifier combinations have no Vial spelling — the
        # right-hand pairs above all, and two of the left triples. They are perfectly
        # good QMK keycodes and the right-click menu can produce them, so they are
        # described from their bits rather than shown as the bare hex they fall back
        # to. The name stays hex, because that is what round-trips through a ``.vil``.
        if name.startswith("0x") and (mask := modifier_mask(code)):
            inner_name = self._by_code.get(code & 0x00FF)
            if inner_name is not None:
                held = modifier_label(mask)
                return KeycodeInfo(
                    code=code,
                    name=name,
                    label=self._labels.get(
                        inner_name, inner_name.removeprefix("KC_")
                    ),
                    tooltip=(
                        f"{held} held down together with {inner_name}. Vial has no "
                        f"name for this combination, so it is stored as {name}."
                    ),
                    kind=KIND_MASKED,
                )

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

    # -- composed keycodes -------------------------------------------------------

    @staticmethod
    def _template_tooltip(outer: str) -> str:
        if outer.startswith("LT") and outer[2:].isdigit():
            return (
                f"Hold for layer {outer[2:]}, tap for the key you pick next. "
                "Click to pick it."
            )
        if outer.endswith("_T"):
            return (
                f"Hold for {outer[:-2]}, tap for the key you pick next. "
                "Click to pick it."
            )
        return f"{outer} held down together with the key you pick next. Click to pick it."

    def template(self, name: str) -> KeycodeInfo | None:
        """The outer half of a composed keycode, as something the picker can show.

        ``LGUI(kc)`` and ``LT2(kc)`` are not keycodes — each has a hole in it where a
        basic keycode goes. They are offered anyway, because a hole the interface can
        fill is far better than a keycode the interface cannot reach at all.
        """
        code = self._by_name.get(name)
        if code is None or "(kc)" not in name:
            return None
        outer = name.removesuffix("(kc)")
        label = self._labels.get(name)
        label = label.replace("(kc)", "…") if label else f"{outer}\n…"
        return KeycodeInfo(
            code=code,
            name=name,
            label=label.strip(),
            tooltip=self._template_tooltip(outer),
            kind=KIND_TEMPLATE,
        )

    def layer_taps(self) -> list[KeycodeInfo]:
        """The ``LT`` templates, one per layer.

        Layer-tap has only four bits for the layer number, so a keyboard with more
        than sixteen layers still stops at fifteen.
        """
        return [
            info
            for layer in range(min(self.layers, 16))
            if (info := self.template(f"LT{layer}(kc)")) is not None
        ]

    @staticmethod
    def composable(inner: int) -> bool:
        """Whether ``inner`` fits the low byte a template leaves for it.

        Only a basic keycode does. A layer operation, a macro or a second template
        is already using the high byte the outer half needs.
        """
        return 0 <= inner <= 0xFF

    def compose(self, template_code: int, inner: int) -> int:
        """Fill a template's hole with ``inner``, giving a real keycode."""
        return ((template_code & 0xFF00) | (inner & 0x00FF)) & 0xFFFF

    def category(self, name: str) -> list[KeycodeInfo]:
        """One picker tab's contents, in the table's own order.

        A template keeps its place in that order rather than being dropped. It is
        pickable like anything else; it just asks for a second click.
        """
        entries: list[KeycodeInfo] = []
        for qmk_id in CATEGORIES.get(name, ()):
            if qmk_id not in KEYCODES:
                continue
            if "(kc)" in qmk_id:
                stub = self.template(qmk_id)
                if stub is not None:
                    entries.append(stub)
                continue
            entries.append(self.info(KEYCODES[qmk_id]))
        return entries

    def categories(self) -> list[str]:
        return list(CATEGORIES)

    def iter_codes(self) -> Iterable[int]:
        return iter(sorted(set(self._by_name.values())))

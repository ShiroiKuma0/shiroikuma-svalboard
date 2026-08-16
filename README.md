<div align="center">

<img src="resources/icons/shiroikuma-svalboard.svg" width="120" alt="白い熊 Svalboard">

# 白い熊 Svalboard

**A native GNU/Linux configurator for the [Svalboard](https://svalboard.com).**

It talks to the keyboard directly over `hidraw` — no browser, no WebHID, no Chrome window
open on another machine just to move a key. Built for KDE Plasma on Wayland.

**📥 Latest release: [`1.0.1+005`](https://github.com/ShiroiKuma0/shiroikuma-svalboard/releases/latest)** — [all releases »](https://github.com/ShiroiKuma0/shiroikuma-svalboard/releases)

</div>

---

The Svalboard is configured through [KeyBard](https://captdeaf.github.io/keybard/), a WebHID
single-page app that runs only in Chromium-family browsers. This program replaces it with a
desktop application that speaks the same Vial protocol to the same hardware, and adds the things
a native program can do that a web page cannot.

## ⌨️ The board draws itself

The layout comes from the keyboard's own definition — the compressed KLE geometry it hands over
on connect — so nothing about the Svalboard's eight finger clusters and two thumb clusters is
hard-coded. A firmware with a different matrix simply draws differently.

Keys are never filled with colour: every key stays black with a yellow label, and state lives in
the border and a corner marker. A composite keycode shows its held half above its tapped one, so
`LCTL_T(KC_ENTER)` reads as both facts rather than as a key called “Enter”.

The window opens at the size the board actually needs, measured from the geometry the keyboard
reported, so neither the board nor the keycode grid starts out scrolled and — where the screen
allows it — no scrollbars appear at all.

## 🔍 Search across every keycode

Roughly 1,600 keycodes sit in a dozen categories. Search ignores the selected category on
purpose — not knowing which one a keycode lives in is the entire reason to search. The keycode
table is generated from vial-gui rather than transcribed, because one wrong value silently writes
the wrong key.

## 🧱 Keycodes built from two clicks

Layer-taps, mod-taps and modifier wrappers are not keycodes but *templates* — `LT2(kc)`,
`LGUI(kc)` — each with a hole in it where a basic keycode goes. Fifty-two of them exist, and a
picker that only shows finished keycodes cannot show any of them: reaching Super+`1` means
already knowing it is spelled `LGUI(KC_1)`.

They are offered here regardless. Pick the outer half, and the picker asks for the inner one —
“`LT2` — now choose the key it types when tapped” — then completes it on your next click. It
refuses what cannot fit inside, rather than composing something wrong.

Modifiers can also be edited on a key already assigned: right-click, and Ctrl, Shift, Alt and
Super are checkboxes on the key as it stands, with a switch for the right-hand side. Vial names
only 18 of the 30 combinations; the other 12 are real QMK keycodes that other tools show as bare
hex, and here they are described from their bits.

## 🧩 Macros, tap dances, combos, key overrides

All four, with the web configurator's best idea kept: “assign and edit” claims the first free
slot, binds it to the selected key, and opens its editor.

Macros are accounted for honestly. They share one 62 KB buffer, so the editor shows how much of
it the whole set needs, any change counts as one write rather than many, and writing is **refused**
when the set no longer fits — silently truncating would drop the tail of a configuration.

## ⚙️ QMK settings that tell the truth

The keyboard is asked which settings it carries, and the answer is honoured. A firmware built
without a feature shows that setting greyed with the reason, instead of offering a control that
would do nothing.

## 🖱️ The Svalboard panel

Each `SV_*` keycode is listed with where it is currently bound, described by cluster and
direction rather than as matrix coordinates.

Live pointing state — DPI, which side scrolls, the auto-mouse timer — is **not on the wire at
all**; the firmware keeps it but exposes only layer colours. It can be read by pressing the
Output Status key while the application listens to the QMK console, which nothing else does.

## 🔬 A key tester that works on Wayland

It reads the switch matrix directly rather than listening for key events. That matters twice
over: on Wayland a program cannot see keys sent to another window, and even where it could, the
key under test is mapped to whatever the keymap says — so a dead switch and a mis-mapped one
would look identical. The same reading powers “type to assign”.

## 🌍 Labelled for your own keyboard layout

A keycode names a *position*, not a character: on a Czech or German layout `KC_Y` types `z`. Keys
can be labelled by any layout installed on the computer, read from the system's own xkb data —
which is every layout the machine has, not a hand-picked dozen. Labels only; what gets written to
the keyboard is unchanged.

## 💾 Backups that survive

`.kbi` for whole-keyboard backups, `.vil` for Vial, and `keymap_all.h` for baking a layout into
firmware so it survives a chip erase. Keycodes are stored as names, so a backup survives firmware
whose numbering has shifted, and sections this version does not model are carried through
untouched rather than dropped. Layers can also be written to a printable sheet.

## 🐻 白い熊 Svalboard UI

The house black-and-yellow style, with the family's settings page: 96 attributes across ten
groups, generated from a registry, styling itself from the theme it edits — move the indent
slider and the page's own indents follow. RGBA colour picker with recent swatches, external font
import with each face rendered in its own glyphs, and Export / Import in the family's
ZIP-of-JSON format.

---

## Installing

```
sudo dpkg -i shiroikuma-svalboard_1.0.1+005_all.deb
```

The package installs a `udev` rule and applies it, so the keyboard does not need replugging.

The rule is named `59-svalboard.rules`, and the prefix is load-bearing:
`/usr/lib/udev/rules.d/73-seat-late.rules` is what applies the `uaccess` ACL, so a rule sorting
after `73-` sets the tag too late and is silently ineffective — the keyboard then appears
connected but refuses to open.

To run from a checkout instead: `python3 -m svalboard.app`. To see what is attached and what it
supports, without writing anything: `python3 -m svalboard.probe`.

Requires Python 3.12 and PyQt6, both present in Tuxedo OS and Ubuntu 24.04.

## Known limits — firmware, not omissions

- **Layer colours** need a `vial-qmk` build carrying the Svalboard `0xEE` extension. Firmware
  `v24.10.24` predates it, and answers every `0xEE` command exactly as it answers an unknown one.
- **Writing** DPI, scroll side and auto-mouse would need a firmware patch. Those values live in
  the firmware's persisted structure and are not exposed on the wire; they can be read, but only
  through the console.

## Licence

GPL-3.0-or-later.

The Vial and VIA protocol work derives from [vial-gui](https://github.com/vial-kb/vial-gui) and
[vial-qmk](https://github.com/svalboard/vial-qmk), both GPL-2.0-or-later; `NOTICE` records what
came from where. KeyBard carries no licence file, so no code from it is used here — it was read
as a description of observable behaviour and wire formats, which are facts about the hardware.

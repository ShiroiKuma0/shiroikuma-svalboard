# shiroikuma-svalboard — working notes

A native GNU/Linux (KDE Plasma 6 / Wayland) configurator for the Svalboard, replacing the KeyBard
web app. Python 3.12 + PyQt6 (Qt Widgets). Packaged as a `.deb` for Tuxedo OS.

## Hard rules

- **No KeyBard code, ever.** `captdeaf/keybard` and `svalboard/keybard-ng` have no LICENSE file and
  are therefore all-rights-reserved. They may be read as a description of behaviour and wire
  formats; nothing may be copied. Protocol code derives from `vial-kb/vial-gui` (GPL-2.0-or-later,
  SPDX-tagged) and `svalboard/vial-qmk`.
- **The project is GPL-3.0-or-later.** Adapted files keep their original SPDX headers.
- **Never material yellow `#FFEB3B`.** The house yellow is pure `#FFFF00`.
- **Never hard-code the keyboard geometry.** It comes from the device's own KLE definition.
- **Never hard-code `/dev/hidraw4`.** Resolve the node by usage page `0xFF60` / usage `0x61`; the
  number is not stable across replugs.

## Hardware facts (verified on 白い熊's board)

- USB VID `0x303A`, PID `0x4044`, iProduct `lightly`, iSerial `vial:f64c2b3c`.
- Four HID interfaces: boot keyboard, **QMK raw HID (`0xFF60`/`0x61`)**, mouse/NKRO, and
  **QMK console (`0xFF31`/`0x74`)**.
- Raw HID: 32-byte reports, **no report IDs**. On Linux write **33 bytes** (`0x00` report-ID prefix
  + 32 payload) and read 32.
- Matrix `10 rows × 6 cols` = 60 positions, all used. The 10 "rows" are **clusters**: 8 finger
  clusters (Centre/North/East/South/West/Super-south) and 2 thumb clusters
  (down/in/up/upper-outer/lower-outer/double-down).
- 16 layers. 50 tap dances, 50 combos, 30 key overrides, 50 macros.
- `VIAL_KEYBOARD_UID` = `1B 18 7D F2 21 F6 29 48`. Vial protocol 6, VIA protocol 9,
  `SVAL_PROTO_VERSION` 3.
- Stock firmware ships `VIAL_INSECURE ?= yes`, so the board reports unlocked immediately. Implement
  the unlock flow anyway — `?=` means a self-built firmware can be locked.

## Protocol

Requests are 32 bytes; the firmware overwrites the buffer in place and **echoes unknown commands
back unchanged** (which is how Svalboard detection works). Buffer transfers chunk at **28 bytes**.

- **VIA**: `0x01` protocol version (`>H`) · `0x02`/`0x03` get/set keyboard value (sub-id `0x02`
  layout options, `0x03` switch-matrix state) · `0x04`/`0x05` get/set keycode (`>BBBBH`,
  **big-endian** keycode) · `0x0C` macro count · `0x0D` macro buffer size · `0x0E`/`0x0F` macro
  buffer · `0x11` layer count · `0x12` keymap buffer.
- **Vial** (prefix `0xFE`): `0x00` keyboard ID (`<IQ`) · `0x01` definition size (`<I`) · `0x02`
  definition block (32-byte blocks, **LZMA/xz-compressed JSON**) · `0x03`/`0x04` encoders ·
  `0x05`–`0x08` unlock status/start/poll/lock · `0x09`–`0x0C` QMK settings query/get/set/reset ·
  `0x0D` dynamic entry op (`0x01`–`0x08`: tap dance, combos, key overrides, alt-repeat).
- **Svalboard** (prefix `0xEE`): `0x01` protocol version → ASCII `sval` + `<I` · `0x02` firmware
  version string · `0x10`/`0x11` get/set per-layer HSV. **That is the entire extension.**

**DPI, scroll mode, auto-mouse and the Manna-Harbour timer are not on the wire.** They live in the
firmware's persisted struct but only `layer_colors` is exposed over `0xEE`; they change solely by
pressing `SV_*` keycodes. Current state can be *read* by triggering `SV_OUTPUT_STATUS` and parsing
the QMK console output on the `0xFF31` interface. Write support needs a firmware patch.

## Transport discipline

The protocol has no sequence numbers, so: **one request in flight at a time**, correlated
request↔response, 500 ms read timeout, bounded retries (the RP2040 stalls during EEPROM writes),
explicit `EACCES` detection reporting "udev rule missing", hotplug reconnect via `pyudev` +
`QSocketNotifier` on the GUI thread. All protocol I/O on a worker thread; the GUI never blocks.

## The shiroikuma house style

Documented across the family as "the kxkb settings house style". There is **no shared library** —
every app re-implements it. Closest references: `~/git/shiroikuma-mahojutan`
(`Flying Carpet/src/customize.{js,css}` — the only complete *desktop* port),
`~/git/shiroikuma-nekokan` (`SkUiActivity.kt`, `SkColorPickerDialog.kt` — Views, maps 1:1 to Qt),
`~/git/shiroikuma-yosuga` (the family's only Qt app; `res/memento.svg` is the icon template).

### Palette

| Role | Value |
|---|---|
| Background | `#000000` |
| Text / accent / border | `#FFFF00` |
| Dim / secondary | `#C8C800` |
| Warning, "not set" | `#FF5252` |
| Disabled (ours — the family defines none) | `#66FFFF00` |
| Pressed | accent at ~20 % alpha |

### Structure

| | Indent | Size | Rule |
|---|---|---|---|
| Section heading | 36 px | 20 pt bold | **2.5 px text-wide** underline, preceded by a **1 px full-width hairline** (omitted on the first group) |
| Subgroup heading | 54 px | 17 pt bold | **1.5 px text-wide** underline, no hairline |
| Row under a section | 72 px | title 16 pt, description 13 pt dim | — |
| Row under a subgroup | 90 px | same | — |

An 18 px ladder. Rows are **5 px vertical padding** (4 px for sliders) and — the load-bearing part —
**no minimum row height**. Breathing space exists only above headings.

**Text-wide underline in Qt**: heading `QLabel` + a `QFrame` rule in a `QVBoxLayout` inside a
container followed by `addStretch(1)`, the rule's width fixed to
`QFontMetrics.horizontalAdvance(text)`.

### Controls

- **Colour**: 38 px swatch chip (1.5 px yellow stroke, 4 px radius) + `#AARRGGBB` summary. Dialog is
  **swatch row → preview → four A/R/G/B sliders** (0–255, step 1). Preview shows the hex, text white
  when `0.299R+0.587G+0.114B < 128` or `A < 128`, else black. **Applies live on every drag**; Cancel
  reverts to the opening colour; OK commits and remembers. Swatches 32 px square, 6 px gap, 1.5 px
  yellow stroke, 4 px radius, **one global MRU of 8**, newest first, seeded with black / yellow /
  white / dim-yellow. Stored in a `QSettings` group that is never exported.
- **Font**: System, Monospace, then imported faces sorted case-insensitively, **each rendered in its
  own typeface**, current prefixed `✓`. Import copies `.ttf`/`.otf` into
  `~/.local/share/shiroikuma-svalboard/fonts/`. Weight is a **separate 100–900 slider**, never a
  bold checkbox.
- **Sliders** for every size, weight, thickness and roundness. Integer step 1, readout right-aligned
  at ~44 px, unit named in the title not the readout, continuous update. **Border width, corner
  radius and separator thickness all start at 0.**

Family font sample string:
`AaIiMmOoQqWw 012 白い熊相撲道 áÁčČďĎéÉěĚíÍňŇóÓřŘšŠťŤúÚůŮýÝžŽ`

### The repeating idiom

Every visual element gets **Font · Weight · Size · Colour** under its own subgroup, plus
Background / Border / Corner where it has a body.

### Entry points

The page is titled **`白い熊 Svalboard UI`**. Reachable three ways, matching the family's
redundancy: a row in ordinary Settings; **long-press on the Settings cog** (`QToolButton` subclass,
~500 ms timer from `mousePressEvent`, cancelled on release or move, suppressing the following
`clicked`); and a right-click context action on the same cog.

### Export / Import

First section of the UI page. Kōjiki's panel with **Arcanechat's dialog behaviour**.

- Directory box bordered 2 px yellow, 10 px radius. Unset → `#FF5252`.
- **Last-export probe on page open**, off the GUI thread: newest `shiroikuma-svalboard_*.zip` by
  mtime → "Last export: yyyy-MM-dd HH:mm:ss".
- Flat checkbox list with a bold "Select all" master.
- One ZIP of plain JSON: `manifest.json` + one file per category + `fonts/`. Filename
  **`shiroikuma-svalboard_yyyy-MM-dd_HH-mm-ss.zip`** — family convention. Settings round-trip per
  key with a type tag `{"t":"b|i|l|f|s|ss","v":…}`.
- Button row: `QHBoxLayout` → Cancel, `addStretch(1)`, Import, Export. Pills: black fill, 1.5 px
  yellow border, radius = half the height, 20 px horizontal padding, 8 px gap, **sentence case**.
- Dialogs: black fill, **2 px yellow border**, 16 px radius, title 19 pt bold, body 14 pt, not
  cancelable. `✓ Export complete` / `✓ Import complete`.
- **Dismissal cascade**: success → OK closes info dialog → panel → UI settings page. Import "Later"
  and "Restart now" both close the chain. **Failures leave the panel open.** Mechanism: give the
  panel's buttons a null handler and re-bind after `show()` so they do not auto-dismiss.
- Wording is the family's: **"Select at least one category."**

## The icon

Black field, one motif traced as a `#FFFF00` outline, `stroke-linecap`/`stroke-linejoin` round,
glyph at ~60–65 % of the canvas, **no frame ring**, fill black or transparent — never yellow.
`viewBox="0 0 512 512"`, `<rect width="512" height="512" rx="96" fill="#000000"/>`,
`stroke-width="21"` (≈4 % of width; 17 vanishes at 16 px, 26 closes the counters).

## Style

- Prose in commits, comments and UI strings follows 白い熊's typographic conventions: curly quotes
  and apostrophes, en dashes for ranges, em dashes for breaks, terminal punctuation on every
  sentence. Code, paths and machine-parsed text stay literal.
- **No `Co-Authored-By: Claude` trailer and no Anthropic attribution line in commits or PR bodies.**

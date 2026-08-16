# Changelog

## 1.0.1+005 — 2026-08-16

### Composed keycodes are reachable at last

Fifty-two keycodes existed in the table but appeared in no tab: every layer-tap, every mod-tap
and every modifier wrapper. Each is a *template* — `LT2(kc)`, `LGUI(kc)` — with a hole in it
where a basic keycode goes, and the tabs dropped anything with a hole. The only way to reach
`LGUI(KC_1)` was to know it was spelled that way and type it into the search box.

- **`LT0`–`LT15` now appear in the Layers tab**, after the plain operations.
- **The modifier wrappers and mod-taps appear in the modifiers tab**, in the table's own order.
- Picking one starts a **two-step compose**: a banner names the half already chosen, the tab
  switches to `basic`, and the next click completes the keycode. Escape or Cancel abandons it,
  and either way the picker returns to the tab and search you started from.
- A template refuses what cannot fit inside it — a layer operation, a macro, a second template —
  and says so rather than composing something wrong.

### Modifiers on a key already assigned

- **Right-click → Modifiers** adds or removes Ctrl, Shift, Alt and Super on the key as it
  stands, with a switch for the right-hand side and "Remove all modifiers". Adding Super to `1`
  no longer means knowing the result is called `LGUI(KC_1)` and finding it in the picker.
- Disabled, with the reason in the title, for keys that have no room for the bits: layer
  operations, layer-taps, macros, tap dances and the Svalboard's own keycodes.
- Vial names only 18 of the 30 modifier combinations. The other 12 — most of the right-hand
  pairs, and two left triples — are valid QMK keycodes that used to read as bare hex. They are
  now described from their bits (`RCtl+RSft+RAlt held down together with KC_1`) and tinted as
  what they are. The stored name stays hex, because that is what round-trips through a `.vil`.

### Presentation

- The keycode picker draws the held half of a composed keycode in a corner strip, as the board
  has always done. `LGUI(KC_1)` and a plain `1` were previously the same button to look at.
- A label that already opens with its own outer name — `OSM(MOD_LSFT)` is labelled `OSM\nLSft` —
  no longer says it twice, once in the strip and once in the body.
- The category list is sorted without regard to case. The four tabs built from the keyboard are
  capitalised, and capitals used to herd them to the top of the list ahead of every other tab;
  they now take their alphabetical place. `basic` remains what the picker opens on.

### The window opens at a size that fits

- The window now sizes itself to the board the keyboard actually reports, so neither the board
  nor the picker opens scrolled, and no scrollbars appear at all where the screen allows it.
  Clamped to the screen; on a monitor too small, the shortfall comes out of the picker, which
  scrolls gracefully, rather than out of the board, which does not.
- The picker asks for as many rows as the tab it opens on needs, up to eight.
- Loading the keyboard blocks the GUI thread for a couple of seconds and the compositor's
  configure events queue up behind it, so the new size is applied, verified a beat later, and
  applied again if a stale configure overwrote it.

## 1.0.0+003 — 2026-08-09

The first release: a complete native configurator, built and verified against 白い熊's Svalboard
throughout. Every capability below was exercised against the real hardware rather than assumed.

### The keyboard

- Talks to the board directly over `hidraw`, with no browser and no WebHID. The raw-HID
  interface is found by usage page (`0xFF60`/`0x61`) rather than by device node, because the
  node number is not stable across replugs.
- One request in flight at a time, with correlated replies, a read timeout and bounded retries.
  The protocol carries no sequence numbers, and the RP2040 stalls while committing EEPROM.
- A missing udev rule is reported as such rather than as a bare permission error. The packaged
  rule is named `59-` deliberately: `73-seat-late.rules` applies the `uaccess` ACL, so anything
  sorting after it is silently ineffective.
- `python3 -m svalboard.probe` — a read-only diagnostic that issues no command that writes.

### Editing

- Keymap editor drawn from the keyboard's own KLE geometry, so the cluster shape is never
  hard-coded and a different firmware simply draws differently.
- Keycode search across roughly 1,600 codes, ignoring the selected category — not knowing which
  category a keycode lives in is the whole reason to search.
- Macros, tap dances, combos and key overrides, with "assign and edit into the first free slot".
- QMK settings, honouring the keyboard's supported-QSID answer instead of offering every setting
  regardless.
- Undo and redo per editor, and nothing reaches the keyboard until an explicit, confirmed write.
- Ctrl and the mouse wheel zoom the board and the keycode picker independently.
- Keys can be labelled by any keyboard layout installed on the computer, read from the system's
  own xkb data — 99 layouts here rather than a hand-written dozen. Labels only: a keycode names a
  position, not a character.

### Testing and files

- Key tester reading the switch matrix directly, so a key is tested whatever it is mapped to —
  and so it works on Wayland, where key events cannot be observed.
- Type-to-assign, built on the same reading for the same reasons.
- `.kbi` backups covering keymap, macros, tap dances, combos and key overrides, with keycodes
  stored as names so a backup survives renumbered firmware. Sections this version does not model
  are carried through untouched.
- `.vil` for Vial, and `keymap_all.h` for baking a layout into firmware.
- Printable layer sheets — deliberately black on white, not the house style.

### Appearance

- The 白い熊 house style: black, `#FFFF00`, text-wide underlined headings, the 36/54/72/90 indent
  ladder, tight rows.
- 白い熊 Svalboard UI page generated from a settings registry of 96 attributes, styling itself
  from the theme it edits, with the family's RGBA colour picker and font importer.
- Export / Import in the family's ZIP-of-JSON format, with the dismissal cascade and the
  red-when-unset directory.

### Limited by firmware, not unfinished

- **Layer colours** need a vial-qmk build carrying the Svalboard `0xEE` extension. 白い熊's board
  runs `v24.10.24`, which predates it; every `0xEE` command is answered the way a junk command is.
- **Writing** DPI, scroll side and auto-mouse would need a firmware patch — they live in the
  firmware's persisted structure and are not exposed on the wire. They can be *read* by pressing
  `SV_OUTPUT_STATUS` and parsing the QMK console, which nothing else does.

# Changelog

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

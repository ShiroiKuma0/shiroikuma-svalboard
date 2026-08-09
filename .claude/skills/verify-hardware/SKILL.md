---
name: verify-hardware
description: Check shiroikuma-svalboard against the real Svalboard safely — read-only diagnostics first, then prove write addressing on an unused layer before anything destructive. Use before trusting any protocol change, after touching svalboard/protocol or svalboard/hid, and whenever a keyboard problem needs telling apart from an application problem.
---

# Verify against the actual keyboard

This program writes to hardware 白い熊 types on every day. A wrong keycode is annoying; a wrong
*address* silently rewrites the wrong key and is discovered later, by feel. So verification runs
in a fixed order, and the read-only half is where almost every real bug has been caught.

## Everything touching the keyboard runs unsandboxed

The sandbox **hides `/dev/hidraw*` entirely** — `stat` returns ENOENT, not a permission error, so
the failure looks like "no keyboard attached" rather than "not permitted". Pass
`dangerouslyDisableSandbox: true` for anything that enumerates, opens or reads those nodes.
Do not waste a sandboxed attempt first.

Writes to `~/git/...` are also blocked by the sandbox ("read-only file system"); `~/tmp` is not.

## 1. The diagnostic, always first

```bash
python3 -m svalboard.probe
```

Read-only by construction: it issues no command that writes. It reports the HID interfaces and
which is which, the identity and unlock state, the Svalboard `0xEE` extension, the capacities,
the decompressed definition with its custom keycodes, and a per-layer keymap summary.

Reach for this **before** blaming the application. On 白い熊's board it establishes:

| | |
|---|---|
| Raw HID | usage page `0xFF60` / usage `0x61` — currently `/dev/hidraw4`, but resolve it every time |
| QMK console | `0xFF31` / `0x74` — currently `/dev/hidraw6` |
| Protocols | VIA 9, Vial 6, keyboard ID `1B 18 7D F2 21 F6 29 48` |
| Capacities | 16 layers × 60 positions, 50 macros / 50 tap dances / 50 combos / 30 key overrides |
| Svalboard `0xEE` | **absent** on firmware `v24.10.24` — every `0xEE` command answers like a junk one |

If access fails, the message says so in plain language: the udev rule is missing. Confirm with
`getfacl /dev/hidraw4` — a working setup shows `user:shiroikuma:rw-`.

## 2. Prove write addressing before writing anything that matters

Read and write must agree on which position is which. A transposed row and column still
*succeeds*; it just corrupts the keymap. Prove it on a layer that is empty, and restore:

```python
kb = Keyboard.open(); state = kb.load()
backup = list(state.keymap)                  # keep this
LAYER, ROW, COL = 6, 1, 5                    # layer 6 is unused on this board; (1,5) is undrawn
assert all(c == 0 for c in state.layer(LAYER)), "not empty — pick another layer"
index = LAYER * state.keys_per_layer + ROW * state.cols + COL

kb.write_key(LAYER, ROW, COL, 0x0004)        # KC_A as a marker
after = kb.read_keymap(state.capacities.layers, state.rows, state.cols)
assert [i for i, (a, b) in enumerate(zip(backup, after)) if a != b] == [index]

kb.write_key(LAYER, ROW, COL, backup[index]) # restore
assert kb.read_keymap(state.capacities.layers, state.rows, state.cols) == backup
```

**Exactly one position must differ, and it must be the expected one.** Anything else means the
addressing is wrong — stop and fix it before touching a used layer.

Save a real backup first when the change is at all risky:
`python3 -c "..."` → `save_kbi(Path.home()/"tmp"/"svalboard-backup.kbi", backup)`.

## 3. Things that look like faults and are not

- **`0xFFFF` in the keymap** is erased flash — a position never written since the board was
  flashed. On this board that is the super-south slot of each of the eight finger clusters,
  which the definition also does not draw. Not corruption; the geometry and the flash agree.
- **Sixty matrix positions, fifty-two drawn.** The definition omits those same eight.
- **Every `0xEE` command answering `0xFF`** is `id_unhandled`, identical to how a junk command is
  answered. The firmware simply lacks the extension; the request is not malformed.
- **QSIDs 22–27 missing** from QMK settings is a firmware built without those features, which is
  why the supported-QSID query is honoured rather than ignored.

## 4. Reading the console status

DPI, scroll side, auto-mouse and the Manna-Harbour timer are **not on the wire at all**. The only
way to see them is `SV_OUTPUT_STATUS`, which prints to the QMK console.

**The host cannot trigger it.** Only a physical press executes a keycode, so ask 白い熊 to press
it and say which key — on this board it is bound at layer 3 cluster 1 centre, and layer 15
cluster 3 centre. Two things learned the hard way:

- QMK's **key logger shares this console** and chatters on every press, so a capture that stops
  at the first quiet moment ends on the keypress, before the status is printed.
- "Something arrived" is therefore not evidence the status did — ninety-five `KL:` lines is a
  live console with no answer, which is a different problem from silence.

The real wording, verbatim, is what the parser is tested against:

```
svalboard/trackball/pmw3389/right:vial @ v24.10.24
Left Ptr: Scroll yes, cpi: 2400, Right Ptr: Scroll no, cpi: 1600
Achordion: no, MH Keys Timer: 500
```

Note `cpi`, not `dpi` — even though the keycodes that change it are named `SV_LEFT_DPI_INC`.

## 5. Never write on 白い熊's behalf without asking

The application asks for confirmation before writing, and so should any script. Reading is free;
writing is not. When a check needs a write, use an unused layer, restore it, and say what was
done.

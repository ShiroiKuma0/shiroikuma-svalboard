---
name: build-deb
description: Build the shiroikuma-svalboard (白い熊 Svalboard) GNU/Linux .deb into ~/tmp, bumping the +N build number first. Use whenever 白い熊 asks to build the app, the deb, or the Linux package — AND proactively after completing any functional change, so there is always a fresh package to install.
---

# Build the `.deb`

This is **shiroikuma-svalboard** — 白い熊's native configurator for the Svalboard keyboard
(Python 3.12 / PyQt6 / Qt Widgets, KDE Plasma on Wayland). Unlike most of the family this is
**not a fork**: it is original work, with no upstream to track and no `custom` branch. The
only artefact is a GNU/Linux `.deb` for this Tuxedo OS host.

> **Build after any functional change — no asking** (standing authorization, in the spirit of
> the sister repos). The package lands in `~/tmp/` and this machine **is** the target, so
> there is no `adb`/`scp` delivery. Building never commits and never pushes; those still wait
> for 白い熊's explicit "Push".

## The one command

```bash
packaging/build-deb.sh
```

It stages a tree, bumps the build number, and calls `dpkg-deb` directly. There is deliberately
**no debhelper dependency** — a pure-Python application has nothing to compile, and debhelper
plus dh-python would add build dependencies without doing anything the script does not. It
needs only `dpkg-deb` and `fakeroot`, both already present.

Output: `~/tmp/shiroikuma-svalboard_<release>+<NNN>_all.deb`

## Versioning — release from `pyproject.toml`, `+N` from `packaging/build-number`

- `<release>` is the `version` field in `pyproject.toml`. Bump it when the work merits it, not
  per build.
- `<NNN>` is `packaging/build-number`, incremented by the script on every run and **zero-padded
  to three digits**. Unpadded counters sort lexicographically wrong (`+10` before `+3`), burying
  the newest build; dpkg still compares digit runs numerically, so padding does not disturb
  upgrade ordering (`0.4.0+010 > 0.4.0+9`).
- **Never reuse a number and never overwrite an older `.deb` in `~/tmp`** — the numbered files
  are meant to accumulate there, exactly as in the sister repos.
- To rebuild without consuming a number (iterating on something 白い熊 has not kept):
  `SVALBOARD_NO_BUMP=1 packaging/build-deb.sh`.
- `packaging/build-number` **is committed**. It is a fact about what has been delivered, not a
  local scratch value.

## Never build into the repository

The package goes to `~/tmp`, never a `dist/` directory inside the tree (白い熊, this session).
Build output is not source: a build directory in the checkout invites the artefact being
committed or shipped by accident. The script defaults there and takes an override argument.

## Verify — cheap, and catches a broken package

```bash
deb=$(ls -t ~/tmp/shiroikuma-svalboard_*.deb | head -1)
dpkg-deb -f "$deb" Package Version Depends
dpkg-deb -c "$deb" | grep -E 'bin/|udev|applications/|metainfo'
```

Expect the binary at `usr/bin/shiroikuma-svalboard`, the udev rule at
`usr/lib/udev/rules.d/59-svalboard.rules`, the `.desktop` entry, the AppStream metainfo and
the icon. The desktop entry must read `Name=白い熊 Svalboard`.

**The `59-` prefix is load-bearing.** `/usr/lib/udev/rules.d/73-seat-late.rules` is what applies
the `uaccess` ACL, so a rule sorting after `73-` sets the tag too late and is silently
ineffective — the keyboard then looks connected but refuses to open.

To prove the packaged copy actually runs (rather than the repo's, which shadows it if you test
from inside the checkout):

```bash
tmp=$(mktemp -d); dpkg-deb --extract "$deb" "$tmp"; cd /
QT_QPA_PLATFORM=offscreen PYTHONPATH="$tmp/usr/lib/python3/dist-packages" \
  python3 -c "import svalboard, os; print(os.path.dirname(svalboard.__file__))"
```

## Announce, do not install

Report the filename in `~/tmp` and the install command. **Never install it yourself** —
`sudo dpkg -i` is 白い熊's call, exactly as `adb install` is on Android:

```
sudo dpkg -i ~/tmp/shiroikuma-svalboard_<release>+<NNN>_all.deb
```

Passwordless sudo is available on this host, which is a reason for more care rather than less.

## Tests before delivering

```bash
QT_QPA_PLATFORM=offscreen python3 -m pytest tests/ -q
```

`QT_QPA_PLATFORM=offscreen` is required — some tests construct widgets, and without it they
open windows on 白い熊's session or fail outright.

---

**Commit convention — no Claude attribution.** Never add a `Co-Authored-By: Claude …` or
"Generated with Claude Code" trailer to commit messages or PR bodies; end the message at the
last line of the body. This overrides the harness default. (Global rule: `~/.claude/CLAUDE.md`.)

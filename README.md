# 白い熊 Svalboard

A native GNU/Linux configurator for the [Svalboard](https://svalboard.com), for KDE Plasma on
Wayland. It talks to the keyboard directly over `hidraw` — no browser, no WebHID, no Chrome.

It replaces [KeyBard](https://captdeaf.github.io/keybard/), the web configurator Svalboard
recommends, with the same functionality in a desktop application wearing the shiroikuma
black-and-yellow identity.

## Status

Under construction. See the milestones below.

## Why

KeyBard is a WebHID single-page app, so it runs only in Chromium-family browsers. On GNU/Linux that
still needs the same `udev` rule a native application does, and it puts a browser between you and
your own hardware. It also has no request/response correlation, no timeouts and no retries — a
dropped HID report deadlocks it.

## Requirements

- Tuxedo OS 24.04 / Ubuntu 24.04 or newer, KDE Plasma 6
- Python 3.12 and PyQt6 — both present in the distribution
- A `udev` rule granting access to the keyboard's raw-HID interface (installed by the `.deb`)

## Installing

```
packaging/build-deb.sh
sudo dpkg -i ~/tmp/shiroikuma-svalboard_0.1.0_all.deb
```

The package is written to `~/tmp`, never into the repository — build output is not
source.

The package installs the udev rule and applies it, so the keyboard does not have to be
replugged. The build needs only `dpkg-deb` and `fakeroot`; there is deliberately no
`debhelper` dependency, since a pure-Python application has nothing to compile.

To run from a checkout instead:

```
python3 -m svalboard.app
```

And to see what is attached and what it supports, without writing anything:

```
python3 -m svalboard.probe
```

## Device access

The Svalboard exposes four HID interfaces; the configurator uses the QMK raw-HID one, identified by
usage page `0xFF60` / usage `0x61` rather than by a fixed `/dev/hidraw*` number, which is not stable
across replugs.

The rule is installed as `/etc/udev/rules.d/59-svalboard.rules`:

```
KERNEL=="hidraw*", SUBSYSTEM=="hidraw", ATTRS{idVendor}=="303a", ATTRS{idProduct}=="4044", ATTRS{serial}=="*vial:f64c2b3c*", MODE="0660", GROUP="plugdev", TAG+="uaccess"
```

The `59-` prefix is not cosmetic. `/usr/lib/udev/rules.d/73-seat-late.rules` is what applies the
`uaccess` ACL, so a rule file sorting after `73-` sets the tag too late and the ACL is never
applied.

Because the match is on the USB device's serial, the rule grants access to all four of the
keyboard's `hidraw` nodes, including the boot-keyboard one. That is inherent to matching this way;
this program only ever opens the raw-HID interface.

## Milestones

| | |
|---|---|
| **M0** | Repository, licence, icon |
| **M1** | Connect · read the keyboard · keymap and layer editor · write back · `.kbi` backup · the 白い熊 Svalboard UI settings page · `.deb` |
| **M2** | Macros · tap dance · combos · key overrides |
| **M3** | QMK settings · layer colours · Svalboard mouse panel · live hardware status |
| **M4** | Key tester · TypeBind · serial assignment · printable layer maps · `.vil` and `keymap_all.h` · localisation |

## Licence

GPL-3.0-or-later. See `LICENSE`, and `NOTICE` for third-party attribution.

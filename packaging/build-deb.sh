#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 白い熊
#
# Build the Debian package.
#
# This stages a tree and calls dpkg-deb directly rather than going through
# debhelper. For a pure-Python application with nothing to compile, debhelper adds a
# build-dependency on debhelper and dh-python without doing anything this script does
# not, and this way the package builds on a machine with only dpkg installed.
#
# The package is written to ~/tmp by default, never into the repository: build output
# is not source, and a dist/ directory inside the tree only invites it being committed
# or shipped by accident.
#
# Usage:  packaging/build-deb.sh [output-directory]

set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(dirname "$here")"
outdir="${1:-$HOME/tmp}"

package="shiroikuma-svalboard"
release="$(sed -n 's/^version = "\(.*\)"/\1/p' "$root/pyproject.toml" | head -1)"
architecture="all"

if [[ -z "$release" ]]; then
    echo "Could not read the version out of pyproject.toml." >&2
    exit 1
fi

# Every delivered build gets its own number, as everywhere else in the family: the
# artefacts accumulate in ~/tmp rather than overwriting each other, and a number is
# never reused. Zero-padded to three digits so the names sort in build order —
# unpadded, +10 sorts before +3 and buries the newest build. dpkg still compares
# digit runs numerically, so padding does not disturb upgrade ordering.
counter_file="$here/build-number"
counter=$(( $(cat "$counter_file" 2>/dev/null || echo 0) + 1 ))
if [[ "${SVALBOARD_NO_BUMP:-}" != "1" ]]; then
    printf '%s\n' "$counter" > "$counter_file"
else
    counter=$(cat "$counter_file")
fi
version="$(printf '%s+%03d' "$release" "$counter")"

stage="$(mktemp -d)"
trap 'rm -rf "$stage"' EXIT

install -d "$stage/DEBIAN"
install -d "$stage/usr/bin"
install -d "$stage/usr/lib/python3/dist-packages"
install -d "$stage/usr/lib/udev/rules.d"
install -d "$stage/usr/share/applications"
install -d "$stage/usr/share/metainfo"
install -d "$stage/usr/share/icons/hicolor/scalable/apps"
install -d "$stage/usr/share/doc/$package"

# The application itself, minus anything that is not shipped.
cp -r "$root/svalboard" "$stage/usr/lib/python3/dist-packages/"
find "$stage/usr/lib/python3/dist-packages/svalboard" \
    -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
# A working tree is group-writable; a shipped file must not be.
find "$stage/usr/lib/python3/dist-packages/svalboard" -type f -exec chmod 0644 {} +
find "$stage/usr/lib/python3/dist-packages/svalboard" -type d -exec chmod 0755 {} +

cat > "$stage/usr/bin/$package" <<'LAUNCHER'
#!/usr/bin/python3
# SPDX-License-Identifier: GPL-3.0-or-later
import sys

from svalboard.app import main

sys.exit(main())
LAUNCHER
chmod 0755 "$stage/usr/bin/$package"

# The 59- prefix matters: 73-seat-late.rules is what applies the uaccess ACL, so a
# rule sorting after it sets the tag too late to have any effect.
install -m 0644 "$here/59-svalboard.rules" "$stage/usr/lib/udev/rules.d/"
install -m 0644 "$here/$package.desktop" "$stage/usr/share/applications/"
install -m 0644 "$here/$package.metainfo.xml" "$stage/usr/share/metainfo/"
install -m 0644 "$root/resources/icons/$package.svg" \
    "$stage/usr/share/icons/hicolor/scalable/apps/"
install -m 0644 "$root/LICENSE" "$stage/usr/share/doc/$package/copyright"
install -m 0644 "$root/NOTICE" "$stage/usr/share/doc/$package/NOTICE"

installed_size="$(du -ks "$stage" | cut -f1)"

cat > "$stage/DEBIAN/control" <<CONTROL
Package: $package
Version: $version
Section: utils
Priority: optional
Architecture: $architecture
Depends: python3 (>= 3.12), python3-pyqt6, udev
Recommends: python3-pyqt6.qtsvg
Installed-Size: $installed_size
Maintainer: 白い熊 <ShiroiKuma@sumo.do>
Homepage: https://github.com/ShiroiKuma0/shiroikuma-svalboard
Description: Native configurator for the Svalboard keyboard
 A configurator for the Svalboard that talks to the keyboard over hidraw, so
 no browser and no WebHID are involved. Built for KDE Plasma on Wayland.
 .
 It reads the board's own definition, so the layout it draws is whatever the
 firmware reports rather than an assumption, and keycodes can be searched
 across every category at once.
 .
 A udev rule granting the logged-in user access to the keyboard is installed
 and applied automatically.
CONTROL

cat > "$stage/DEBIAN/postinst" <<'POSTINST'
#!/bin/sh
set -e

if [ "$1" = "configure" ]; then
    # Apply the rule to the keyboard if it is already plugged in, so the user does
    # not have to replug after installing.
    if command -v udevadm > /dev/null 2>&1; then
        udevadm control --reload-rules || true
        udevadm trigger --subsystem-match=hidraw || true
    fi
fi

exit 0
POSTINST
chmod 0755 "$stage/DEBIAN/postinst"

cat > "$stage/DEBIAN/postrm" <<'POSTRM'
#!/bin/sh
set -e

if [ "$1" = "remove" ] || [ "$1" = "purge" ]; then
    if command -v udevadm > /dev/null 2>&1; then
        udevadm control --reload-rules || true
    fi
fi

exit 0
POSTRM
chmod 0755 "$stage/DEBIAN/postrm"

mkdir -p "$outdir"
deb="$outdir/${package}_${version}_${architecture}.deb"
fakeroot dpkg-deb --build --root-owner-group "$stage" "$deb" > /dev/null

echo "$deb"
dpkg-deb --info "$deb" | sed 's/^/    /'

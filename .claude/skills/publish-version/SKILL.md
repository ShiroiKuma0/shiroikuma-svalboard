---
name: publish-version
description: Publish the latest local .deb build as a GitHub release of shiroikuma-svalboard — refresh the README, write a very specific CHANGELOG entry, tag the bare version, and create the release with the ~/tmp .deb attached. Use when 白い熊 says publish / release / cut a version / ship it to GitHub / "/publish-version".
---

# Publish a version of shiroikuma-svalboard to GitHub

Ship the **latest already-built** `.deb` as a GitHub release, with a polished README and an
exhaustive CHANGELOG.

> **This commits, pushes, tags and publishes.** Only run it when 白い熊 explicitly asks to
> publish.

> **Never rebuild to publish.** Attach the newest `.deb` already in `~/tmp/`. If you think a
> fresh build is needed, that is a separate `build-deb` run 白い熊 drives and tests first — not
> part of publishing.

## How this repo differs from the family's forks

Most sister repos are forks: they publish from `custom`, flip the GitHub default branch away
from an upstream-mirroring `master`, and write a "**a fork of X with major additions**" README.
**None of that applies here.** This is original work:

- The branch is **`main`**, and it is already the default. Do not look for `custom`.
- The remote is named **`upstream`**, not `origin` — 白い熊 asked for that when the repo was
  created. The global `publish-version` skill derives the repo from `origin` and will fail here,
  so derive it from whichever remote exists (below).
- There is no upstream project to credit. The README tells this program's own story; the
  comparison worth drawing is with **KeyBard**, the web configurator it replaces — and see the
  licensing note below before writing a word about that.

## 0. Detect the version

```bash
ls -t ~/tmp/shiroikuma-svalboard_*.deb | head -1
```

The version is the field between the first `_` and `_all.deb` — e.g.
`shiroikuma-svalboard_0.4.0+003_all.deb` → **`0.4.0+003`**. Use it verbatim everywhere: tag,
README latest-release line, release title, changelog heading. If there is no `.deb` in `~/tmp`,
**stop and tell 白い熊 to build first** (`build-deb`) — do not build it yourself.

Check the release part is not stale: `grep '^version' pyproject.toml`. If the work since the
last release clearly outgrows it, say so and let 白い熊 decide the number — do not bump it
silently as part of publishing.

## 1. Derive the repo from the remote that exists

```bash
url=$(git remote get-url upstream 2>/dev/null || git remote get-url origin)
url=${url%.git}
OWNER_REPO=$(printf '%s' "$url" | sed -E 's#^.*[:/]([^/]+/[^/]+)$#\1#')   # ShiroiKuma0/shiroikuma-svalboard
```

Pass `--repo "$OWNER_REPO"` to every `gh` call. `gh` must be authenticated as `ShiroiKuma0`
(`gh auth status`).

## 2. Refresh `README.md`

Keep the family's shape — centered header block, then emoji-headed sections for the features
that matter — but written as an original program rather than a fork:

- **Centered header** (`<div align="center">`): the icon
  (`resources/icons/shiroikuma-svalboard.svg`, width 120), the title **白い熊 Svalboard**, a
  one-line tagline ("A native GNU/Linux configurator for the Svalboard keyboard"), and a
  sentence saying it talks to the keyboard over `hidraw` with no browser involved.
- The **latest-release line**:
  `**📥 Latest release: [\`<version>\`](…/releases/latest)** — [all releases »](…/releases)`.
- **A section per major capability**, in importance order, with real prose. The current set:
  the keymap editor drawn from the board's own geometry; keycode search across ~1,600 codes;
  macros, tap dances, combos and key overrides; QMK settings that honour the supported-QSID
  query; the Svalboard panel and its console status reader; the key tester that reads the
  switch matrix; keyboard-layout relabelling from the system's own xkb data; `.kbi`/`.vil`/
  `keymap_all.h` and printable sheets; the 白い熊 Svalboard UI page.
- **Installing**, including the udev rule and why its `59-` prefix matters.
- Licence: **GPL-3.0-or-later**, and point at `NOTICE`.

**Licensing — do not get this wrong in public.** Neither KeyBard repository carries a licence
file, so no code from either is used and the README must not imply otherwise. It is fair and
accurate to say this program replaces KeyBard and was informed by its observable behaviour and
the wire formats; it is not accurate to call it a port or a fork. The protocol work derives from
`vial-kb/vial-gui` (GPL-2.0-or-later) and `svalboard/vial-qmk`, which `NOTICE` records.

## 3. Update `CHANGELOG.md` — exhaustive and specific

Add a section **above** the previous one:

```
## <version> — <YYYY-MM-DD>
```

List everything built since the last release, grouped with `###` subsections, naming real
capabilities — never "various improvements". Cross-check against
`git log --oneline <lastTag>..main` and the previous section so nothing is missed.

Worth stating plainly where the program is limited by firmware rather than unfinished: layer
colours need a vial-qmk build carrying the `0xEE` extension, and writing DPI / scroll / auto-mouse
would need a firmware patch, because those live in the firmware's persisted structure and are
not on the wire at all.

## 4. Commit, tag, push, release

```bash
git add README.md CHANGELOG.md
git commit -F - <<'MSG'
docs: changelog and README for <version>
MSG
git push upstream main

# Annotated tag = the bare version, NO "v" prefix — the family convention.
git tag -a "<version>" -m "白い熊 Svalboard <version>"
git push upstream "<version>"

# Release notes = this version's CHANGELOG section. Match LITERALLY (index($0,h)==1), not by
# regex: the "+NNN" tail puts a "+" in the version, and "+" is a regex metacharacter, so
# /^## <version>/ would silently fail to match.
mkdir -p .scratch
awk -v h="## <version>" 'index($0,h)==1{p=1;next} /^## /{if(p)exit} p' CHANGELOG.md > .scratch/release-notes.md

gh release create "<version>" \
  --repo "$OWNER_REPO" \
  --title "白い熊 Svalboard <version>" \
  --notes-file .scratch/release-notes.md \
  ~/tmp/shiroikuma-svalboard_<version>_all.deb
```

Verify: `gh release list --repo "$OWNER_REPO"` shows it as **Latest**, and
`gh release view "<version>" --repo "$OWNER_REPO" --json assets` lists the `.deb`. Report the URL.

## Hard rules

- Scratch files go in the gitignored **`.scratch/`**, never `~/tmp` (which is for artefacts).
- `gh`, `git push` and anything touching `/dev/hidraw*` run **unsandboxed**
  (`dangerouslyDisableSandbox: true`) — the sandbox blocks the network and hides the device nodes.
- **No Claude/Anthropic attribution** anywhere: not the commit, the tag, the README, the
  changelog, or the release body. End commit messages at the last line of the body.
- Tag is the **bare version** (e.g. `0.4.0+003`), no `v` prefix.
- The release is cut from **`main`**. There is no `custom` branch in this repo.

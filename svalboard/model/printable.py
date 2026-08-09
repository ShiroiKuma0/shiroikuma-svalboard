# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 白い熊
"""A printable sheet of every layer, as self-contained HTML.

The point of printing a layout is to have it beside the keyboard while learning it, so
this is deliberately ink-light: black on white, one layer per block, empty layers left
out. That is the opposite of the application's own colours, and intentionally — a page
printed in the house style would be a solid black rectangle.

The output is one file with no external references, so it can be opened in a browser,
printed, or kept.
"""

from __future__ import annotations

import html
from datetime import datetime

from ..protocol.keycodes import KeycodeSet
from ..protocol.kle import Layout

#: Pixels per KLE unit on the printed page. Small enough that a 25-unit board fits
#: across a sheet of A4 in landscape.
UNIT = 34


def _key_html(label: str, x: float, y: float, w: float, h: float) -> str:
    style = (
        f"left:{x * UNIT:.1f}px;top:{y * UNIT:.1f}px;"
        f"width:{w * UNIT - 3:.1f}px;height:{h * UNIT - 3:.1f}px"
    )
    return f'<div class="k" style="{style}">{html.escape(label)}</div>'


def to_html(
    *,
    layout: Layout,
    codes: list[int],
    keycodes: KeycodeSet,
    layers: int,
    layer_names: dict[int, str] | None = None,
    board: str = "Svalboard",
    generated: datetime | None = None,
) -> str:
    """Render every non-empty layer."""
    names = layer_names or {}
    per_layer = layout.rows * layout.cols
    min_x, min_y, max_x, max_y = layout.bounds
    width = (max_x - min_x) * UNIT + 8
    height = (max_y - min_y) * UNIT + 8

    blocks: list[str] = []
    for layer in range(layers):
        window = codes[layer * per_layer : (layer + 1) * per_layer]
        # An empty layer prints as a page of nothing, so it is left out entirely.
        if not any(window):
            continue

        keys: list[str] = []
        for key in layout.keys:
            if not key.is_key:
                continue
            index = key.kmid(layout.cols)
            code = window[index] if index < len(window) else 0
            info = keycodes.info(code)
            if info.is_empty:
                label = ""
            elif info.is_transparent:
                label = "▽"
            else:
                label = (info.label or info.name.removeprefix("KC_")).replace("\n", " ")
            keys.append(
                _key_html(label, key.x - min_x, key.y - min_y, key.width, key.height)
            )

        title = names.get(layer)
        heading = f"Layer {layer}" + (f" — {html.escape(title)}" if title else "")
        blocks.append(
            f'<section><h2>{heading}</h2>'
            f'<div class="board" style="width:{width:.0f}px;height:{height:.0f}px">'
            f'{"".join(keys)}</div></section>'
        )

    stamp = (generated or datetime.now()).strftime("%Y-%m-%d %H:%M")
    return f"""<!doctype html>
<html lang="en">
<meta charset="utf-8">
<title>{html.escape(board)} — layers</title>
<style>
  /* Printed on paper, so this is ink-light and deliberately not the house style:
     black on white, thin rules, no fills. */
  body {{ font: 12px/1.4 sans-serif; color: #000; background: #fff; margin: 18px; }}
  h1 {{ font-size: 17px; margin: 0 0 2px; }}
  h1 + p {{ margin: 0 0 18px; color: #555; }}
  h2 {{ font-size: 13px; margin: 0 0 6px; }}
  section {{ margin: 0 0 22px; break-inside: avoid; page-break-inside: avoid; }}
  .board {{ position: relative; }}
  .k {{
    position: absolute; border: 1px solid #000; border-radius: 3px;
    display: flex; align-items: center; justify-content: center;
    text-align: center; font-size: 9px; padding: 1px; overflow: hidden;
    box-sizing: border-box;
  }}
  @media print {{ body {{ margin: 0; }} }}
</style>
<h1>{html.escape(board)}</h1>
<p>{len(blocks)} layers in use · {stamp}</p>
{"".join(blocks)}
</html>
"""

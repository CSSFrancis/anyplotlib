"""
tests/test_interactive/test_edit_chrome_playwright.py
=====================================================

Playwright integration tests for the Report-Builder edit-mode features:

  * ArrowWidget synthetic drag → pointer_up carries final x/y/u/v
  * edit_chrome hover outline appears on a panel cell (DOM style assert)
  * figure-background click emits ``figure_background`` in edit mode (and NOT
    when edit mode is off)
  * figure-marker drag round-trips fractions (figure_markers_json + pointer_up)

Each test opens the standalone HTML (no live kernel) and drives real browser
mouse events, reading back ``event_json`` writes and DOM styles via
``page.evaluate``.

Coordinate system
-----------------
GRID_PAD = 8 (gridDiv padding). The figMarkerCanvas + panel grid both sit at
(8, 8) inside outerDiv, so a figure fraction (fx, fy) maps to page coords
(GRID_PAD + fx*fig_w, GRID_PAD + fy*fig_h). Panel image px map through the
per-panel PAD offsets (see _event_test_utils).
"""
from __future__ import annotations

import json

import numpy as np
import pytest

import anyplotlib as apl
from anyplotlib.tests.test_interactive._event_test_utils import (
    _collect_events, _get_events, GRID_PAD, PAD_L, PAD_T,
)

FIG_W, FIG_H = 400, 300


def _open(interact_page, fig):
    page = interact_page(fig)
    _collect_events(page)
    return page


# JS: the first panel cell's inline outline (the grid is found by computed
# display, since inline-style attribute matching is brittle across browsers).
_CELL_OUTLINE_JS = """() => {
    let grid = null;
    for (const d of document.querySelectorAll('div')) {
        if (getComputedStyle(d).display === 'grid') { grid = d; break; }
    }
    const cell = grid ? grid.firstElementChild : null;
    return cell ? cell.style.outline : null;
}"""


# ═══════════════════════════════════════════════════════════════════════════
# 1. ArrowWidget synthetic drag
# ═══════════════════════════════════════════════════════════════════════════

class TestArrowWidgetDrag:
    # Map image-px (ix,iy) → page coords using the overlay canvas rect + the
    # 'contain' fit (no zoom/pan in these tests), matching figure_esm.js.  The
    # overlay canvas is identified as the single canvas with pointer-events:all.
    _OVERLAY_RECT_JS = """() => {
        for (const cv of document.querySelectorAll('canvas')) {
            if (getComputedStyle(cv).pointerEvents === 'all') {
                const r = cv.getBoundingClientRect();
                return {left:r.left, top:r.top, w:r.width, h:r.height};
            }
        }
        return null;
    }"""

    def _img_to_page(self, page, ix, iy, iw=32, ih=32):
        r = page.evaluate(self._OVERLAY_RECT_JS)
        assert r is not None, "overlay canvas not found"
        s = min(r["w"] / iw, r["h"] / ih)
        ox = (r["w"] - iw * s) / 2.0
        oy = (r["h"] - ih * s) / 2.0
        return r["left"] + ox + ix * s, r["top"] + oy + iy * s

    def test_arrow_body_drag_emits_pointer_up_with_fields(self, interact_page):
        fig, ax = apl.subplots(1, 1, figsize=(FIG_W, FIG_H))
        # 32×32 image; arrow spans the panel so the shaft crosses the centre.
        v = ax.imshow(np.zeros((32, 32), dtype=np.float32))
        v.add_arrow_widget(x=6, y=6, u=20, v=20, color="#ff0000")
        page = _open(interact_page, fig)

        # Grab the tail handle (6,6) and drag the whole arrow.
        tx, ty = self._img_to_page(page, 6, 6)
        page.mouse.move(tx, ty)
        page.mouse.down()
        page.mouse.move(tx + 30, ty + 20, steps=8)
        page.mouse.up()
        page.wait_for_timeout(80)

        ups = _get_events(page, "pointer_up")
        assert ups, "arrow drag should emit a pointer_up"
        last = ups[-1]
        assert "x" in last and "y" in last and "u" in last and "v" in last
        # Body move → x,y increased; u,v (vector) unchanged.
        assert last["x"] > 6.0 and last["y"] > 6.0
        assert last["u"] == pytest.approx(20.0, abs=1e-6)
        assert last["v"] == pytest.approx(20.0, abs=1e-6)

    def test_arrow_head_drag_changes_uv(self, interact_page):
        fig, ax = apl.subplots(1, 1, figsize=(FIG_W, FIG_H))
        v = ax.imshow(np.zeros((32, 32), dtype=np.float32))
        v.add_arrow_widget(x=6, y=6, u=20, v=20, color="#ff0000")
        page = _open(interact_page, fig)

        hx, hy = self._img_to_page(page, 26, 26)   # head = tail + (u,v)
        page.mouse.move(hx, hy)
        page.mouse.down()
        page.mouse.move(hx + 20, hy - 25, steps=8)
        page.mouse.up()
        page.wait_for_timeout(80)

        ups = _get_events(page, "pointer_up")
        assert ups
        last = ups[-1]
        # Tail stays put; head moved right+up → u increases, v decreases.
        assert last["x"] == pytest.approx(6.0, abs=1e-6)
        assert last["u"] > 20.0
        assert last["v"] < 20.0


# ═══════════════════════════════════════════════════════════════════════════
# 2. edit_chrome hover outline (DOM style assert)
# ═══════════════════════════════════════════════════════════════════════════

class TestEditChromeHover:
    def test_hover_outline_appears_in_edit_mode(self, interact_page):
        fig, ax = apl.subplots(1, 1, figsize=(FIG_W, FIG_H))
        ax.imshow(np.zeros((16, 16), dtype=np.float32))
        fig.edit_chrome = True
        page = interact_page(fig)

        # Enter from outside, then move over the panel cell centre.
        page.mouse.move(1, 1)
        page.mouse.move(GRID_PAD + FIG_W / 2, GRID_PAD + FIG_H / 2, steps=5)
        page.wait_for_timeout(60)

        outline = page.evaluate(_CELL_OUTLINE_JS)
        assert outline and "dashed" in outline

    def test_no_hover_outline_when_edit_off(self, interact_page):
        fig, ax = apl.subplots(1, 1, figsize=(FIG_W, FIG_H))
        ax.imshow(np.zeros((16, 16), dtype=np.float32))
        # edit_chrome stays False (default)
        page = interact_page(fig)

        page.mouse.move(1, 1)
        page.mouse.move(GRID_PAD + FIG_W / 2, GRID_PAD + FIG_H / 2, steps=5)
        page.wait_for_timeout(60)

        outline = page.evaluate(_CELL_OUTLINE_JS)
        assert not outline  # '' or null


# ═══════════════════════════════════════════════════════════════════════════
# 3. Figure-background click
# ═══════════════════════════════════════════════════════════════════════════

class TestFigureBackgroundClick:
    def test_background_click_emits_in_edit_mode(self, interact_page):
        fig, ax = apl.subplots(1, 1, figsize=(FIG_W, FIG_H))
        ax.imshow(np.zeros((16, 16), dtype=np.float32))
        fig.edit_chrome = True
        page = _open(interact_page, fig)

        # Click in the gridDiv padding band (top-left 8px margin) — always
        # background, never inside a panel cell.
        page.mouse.move(2, 2)
        page.mouse.down()
        page.mouse.up()
        page.wait_for_timeout(60)

        bg = [e for e in _get_events(page)
              if e.get("figure_background")]
        assert bg, "figure_background should be emitted on a background click"

    def test_background_click_silent_when_edit_off(self, interact_page):
        fig, ax = apl.subplots(1, 1, figsize=(FIG_W, FIG_H))
        ax.imshow(np.zeros((16, 16), dtype=np.float32))
        page = _open(interact_page, fig)

        page.mouse.move(2, 2)
        page.mouse.down()
        page.mouse.up()
        page.wait_for_timeout(60)

        bg = [e for e in _get_events(page) if e.get("figure_background")]
        assert bg == []

    def test_panel_click_not_background(self, interact_page):
        fig, ax = apl.subplots(1, 1, figsize=(FIG_W, FIG_H))
        ax.imshow(np.zeros((16, 16), dtype=np.float32))
        fig.edit_chrome = True
        page = _open(interact_page, fig)

        page.mouse.move(GRID_PAD + FIG_W / 2, GRID_PAD + FIG_H / 2)
        page.mouse.down()
        page.mouse.up()
        page.wait_for_timeout(60)

        bg = [e for e in _get_events(page) if e.get("figure_background")]
        assert bg == [], "a click inside a panel must not fire figure_background"


# ═══════════════════════════════════════════════════════════════════════════
# 4. Figure-marker drag round-trips fractions
# ═══════════════════════════════════════════════════════════════════════════

class TestFigureMarkerDrag:
    def test_marker_drag_updates_fractions(self, interact_page):
        fig, ax = apl.subplots(1, 1, figsize=(FIG_W, FIG_H))
        ax.imshow(np.zeros((16, 16), dtype=np.float32))
        fig.set_figure_markers([
            {"kind": "circle", "x": 0.5, "y": 0.5, "r": 0.08, "id": "c1"}])
        fig.edit_chrome = True
        page = _open(interact_page, fig)

        # Marker centre at fraction (0.5, 0.5) → page coords.
        start_x = GRID_PAD + 0.5 * FIG_W
        start_y = GRID_PAD + 0.5 * FIG_H
        # Drag it by +0.2 fig-width, -0.1 fig-height.
        end_x = GRID_PAD + 0.7 * FIG_W
        end_y = GRID_PAD + 0.4 * FIG_H

        page.mouse.move(start_x, start_y)
        page.mouse.down()
        page.mouse.move(end_x, end_y, steps=10)
        page.mouse.up()
        page.wait_for_timeout(80)

        # (a) pointer_up carries the updated fractions + figure_marker flag.
        ups = [e for e in _get_events(page, "pointer_up")
               if e.get("figure_marker")]
        assert ups, "figure-marker drag should emit a figure_marker pointer_up"
        last = ups[-1]
        assert last["marker_id"] == "c1"
        assert last["x"] == pytest.approx(0.7, abs=0.03)
        assert last["y"] == pytest.approx(0.4, abs=0.03)

        # (b) figure_markers_json written back to the model with the new pos.
        stored = page.evaluate(
            "() => JSON.parse(window._aplModel.get('figure_markers_json'))")
        assert stored[0]["x"] == pytest.approx(0.7, abs=0.03)
        assert stored[0]["y"] == pytest.approx(0.4, abs=0.03)

    def test_marker_not_draggable_when_edit_off(self, interact_page):
        fig, ax = apl.subplots(1, 1, figsize=(FIG_W, FIG_H))
        ax.imshow(np.zeros((16, 16), dtype=np.float32))
        fig.set_figure_markers([
            {"kind": "circle", "x": 0.5, "y": 0.5, "r": 0.08, "id": "c1"}])
        # edit_chrome stays False → figMarkerCanvas pointer-events:none.
        page = _open(interact_page, fig)

        start_x = GRID_PAD + 0.5 * FIG_W
        start_y = GRID_PAD + 0.5 * FIG_H
        page.mouse.move(start_x, start_y)
        page.mouse.down()
        page.mouse.move(start_x + 0.2 * FIG_W, start_y, steps=8)
        page.mouse.up()
        page.wait_for_timeout(60)

        ups = [e for e in _get_events(page, "pointer_up")
               if e.get("figure_marker")]
        assert ups == [], "markers must be inert when edit_chrome is off"
        stored = page.evaluate(
            "() => JSON.parse(window._aplModel.get('figure_markers_json'))")
        assert stored[0]["x"] == pytest.approx(0.5, abs=1e-6)

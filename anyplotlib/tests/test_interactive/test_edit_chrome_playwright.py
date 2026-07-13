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

    def test_arrow_shaft_drag_moves_whole_arrow(self, interact_page):
        fig, ax = apl.subplots(1, 1, figsize=(FIG_W, FIG_H))
        # 32×32 image; arrow spans the panel so the shaft crosses the centre.
        v = ax.imshow(np.zeros((32, 32), dtype=np.float32))
        v.add_arrow_widget(x=6, y=6, u=20, v=20, color="#ff0000")
        page = _open(interact_page, fig)

        # Grab the SHAFT midpoint (16,16) — away from both endpoint nodes — and
        # drag the whole arrow.  Both endpoints translate; u,v (vector) invariant.
        mx, my = self._img_to_page(page, 16, 16)
        page.mouse.move(mx, my)
        page.mouse.down()
        page.mouse.move(mx + 30, my + 20, steps=8)
        page.mouse.up()
        page.wait_for_timeout(80)

        ups = _get_events(page, "pointer_up")
        assert ups, "arrow shaft drag should emit a pointer_up"
        last = ups[-1]
        assert "x" in last and "y" in last and "u" in last and "v" in last
        # Body move → x,y increased; u,v (vector) unchanged.
        assert last["x"] > 6.0 and last["y"] > 6.0
        assert last["u"] == pytest.approx(20.0, abs=1e-6)
        assert last["v"] == pytest.approx(20.0, abs=1e-6)

    def test_arrow_tail_drag_reshapes_head_fixed(self, interact_page):
        fig, ax = apl.subplots(1, 1, figsize=(FIG_W, FIG_H))
        v = ax.imshow(np.zeros((32, 32), dtype=np.float32))
        v.add_arrow_widget(x=6, y=6, u=20, v=20, color="#ff0000")
        page = _open(interact_page, fig)

        # Grab the TAIL node (6,6) and drag it.  New semantics: the tail moves
        # but the HEAD (tail + (u,v) = (26,26)) stays anchored.
        tx, ty = self._img_to_page(page, 6, 6)
        page.mouse.move(tx, ty)
        page.mouse.down()
        page.mouse.move(tx + 24, ty + 16, steps=8)
        page.mouse.up()
        page.wait_for_timeout(80)

        ups = _get_events(page, "pointer_up")
        assert ups, "arrow tail drag should emit a pointer_up"
        last = ups[-1]
        # Tail moved down-right → x,y increased.
        assert last["x"] > 6.0 and last["y"] > 6.0
        # Head = x+u, y+v stays anchored at the original (26, 26).
        assert last["x"] + last["u"] == pytest.approx(26.0, abs=0.6)
        assert last["y"] + last["v"] == pytest.approx(26.0, abs=0.6)

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


# ═══════════════════════════════════════════════════════════════════════════
# 5. Widget resize nodes — circle radius + rectangle corner round-trip
# ═══════════════════════════════════════════════════════════════════════════

# Module-level image-px → page-coord mapper (overlay canvas rect + 'contain'
# fit, no zoom/pan), shared by the resize tests.
_OVERLAY_RECT_JS = """() => {
    for (const cv of document.querySelectorAll('canvas')) {
        if (getComputedStyle(cv).pointerEvents === 'all') {
            const r = cv.getBoundingClientRect();
            return {left:r.left, top:r.top, w:r.width, h:r.height};
        }
    }
    return null;
}"""


def _img_to_page(page, ix, iy, iw=32, ih=32):
    r = page.evaluate(_OVERLAY_RECT_JS)
    assert r is not None, "overlay canvas not found"
    s = min(r["w"] / iw, r["h"] / ih)
    ox = (r["w"] - iw * s) / 2.0
    oy = (r["h"] - ih * s) / 2.0
    return r["left"] + ox + ix * s, r["top"] + oy + iy * s


class TestWidgetResizeNodes:
    def test_circle_radius_node_resizes(self, interact_page):
        fig, ax = apl.subplots(1, 1, figsize=(FIG_W, FIG_H))
        v = ax.imshow(np.zeros((32, 32), dtype=np.float32))
        v.add_circle_widget(cx=16, cy=16, r=6, color="#ff0000")
        page = _open(interact_page, fig)

        # Radius handle sits at the east point (cx+r, cy) = (22, 16).  Drag it
        # OUT to ~(26, 16) → radius grows; centre unchanged.
        hx, hy = _img_to_page(page, 22, 16)
        page.mouse.move(hx, hy)
        page.mouse.down()
        ex, ey = _img_to_page(page, 26, 16)
        page.mouse.move(ex, ey, steps=8)
        page.mouse.up()
        page.wait_for_timeout(80)

        ups = _get_events(page, "pointer_up")
        assert ups, "circle radius drag should emit a pointer_up"
        last = ups[-1]
        assert last["r"] > 6.0
        assert last["cx"] == pytest.approx(16.0, abs=0.5)
        assert last["cy"] == pytest.approx(16.0, abs=0.5)

    def test_circle_centre_node_moves(self, interact_page):
        fig, ax = apl.subplots(1, 1, figsize=(FIG_W, FIG_H))
        v = ax.imshow(np.zeros((32, 32), dtype=np.float32))
        v.add_circle_widget(cx=16, cy=16, r=6, color="#ff0000")
        page = _open(interact_page, fig)

        cx, cy = _img_to_page(page, 16, 16)
        page.mouse.move(cx, cy)
        page.mouse.down()
        ex, ey = _img_to_page(page, 20, 22)
        page.mouse.move(ex, ey, steps=8)
        page.mouse.up()
        page.wait_for_timeout(80)

        last = _get_events(page, "pointer_up")[-1]
        # Centre moved; radius unchanged.
        assert last["cx"] > 16.0 and last["cy"] > 16.0
        assert last["r"] == pytest.approx(6.0, abs=0.5)

    def test_rect_corner_node_resizes(self, interact_page):
        fig, ax = apl.subplots(1, 1, figsize=(FIG_W, FIG_H))
        v = ax.imshow(np.zeros((32, 32), dtype=np.float32))
        # top-left (x,y)=(6,6), size 12×10 → SE corner at (18,16).
        v.add_rectangle_widget(x=6, y=6, w=12, h=10, color="#ff0000")
        page = _open(interact_page, fig)

        # Drag the SE corner further out → w,h grow; x,y (top-left) fixed.
        sx, sy = _img_to_page(page, 18, 16)
        page.mouse.move(sx, sy)
        page.mouse.down()
        ex, ey = _img_to_page(page, 24, 22)
        page.mouse.move(ex, ey, steps=8)
        page.mouse.up()
        page.wait_for_timeout(80)

        last = _get_events(page, "pointer_up")[-1]
        assert last["w"] > 12.0 and last["h"] > 10.0
        assert last["x"] == pytest.approx(6.0, abs=0.5)
        assert last["y"] == pytest.approx(6.0, abs=0.5)

    def test_rect_tl_corner_anchors_opposite(self, interact_page):
        fig, ax = apl.subplots(1, 1, figsize=(FIG_W, FIG_H))
        v = ax.imshow(np.zeros((32, 32), dtype=np.float32))
        v.add_rectangle_widget(x=6, y=6, w=12, h=10, color="#ff0000")
        page = _open(interact_page, fig)

        # Drag the TL corner IN → x,y move, w,h shrink; SE corner (18,16) fixed.
        tx, ty = _img_to_page(page, 6, 6)
        page.mouse.move(tx, ty)
        page.mouse.down()
        ex, ey = _img_to_page(page, 10, 9)
        page.mouse.move(ex, ey, steps=8)
        page.mouse.up()
        page.wait_for_timeout(80)

        last = _get_events(page, "pointer_up")[-1]
        # SE corner = x+w, y+h stays anchored at (18, 16).
        assert last["x"] + last["w"] == pytest.approx(18.0, abs=0.7)
        assert last["y"] + last["h"] == pytest.approx(16.0, abs=0.7)
        assert last["x"] > 6.0 and last["y"] > 6.0


# ═══════════════════════════════════════════════════════════════════════════
# 6. Panel drag-swap grip
# ═══════════════════════════════════════════════════════════════════════════

# Locate a panel cell's move-grip and the cell rect by grid order.
_GRIP_RECT_JS = """(idx) => {
    let grid = null;
    for (const d of document.querySelectorAll('div')) {
        if (getComputedStyle(d).display === 'grid') { grid = d; break; }
    }
    if (!grid) return null;
    const cell = grid.children[idx];
    if (!cell) return null;
    const grip = cell.querySelector('.apl-panel-grip');
    const gr = grip ? grip.getBoundingClientRect() : null;
    const cr = cell.getBoundingClientRect();
    return {
        grip: gr ? {left:gr.left, top:gr.top, w:gr.width, h:gr.height,
                    display: getComputedStyle(grip).display} : null,
        cell: {left:cr.left, top:cr.top, w:cr.width, h:cr.height},
    };
}"""


class TestPanelSwapGrip:
    def _two_panel_fig(self):
        fig = apl.Figure(1, 2, figsize=(FIG_W, FIG_H))
        a0 = fig.add_subplot((0, 0)); a0.imshow(np.zeros((16, 16), dtype=np.float32))
        a1 = fig.add_subplot((0, 1)); a1.imshow(np.zeros((16, 16), dtype=np.float32))
        return fig

    def test_grip_hidden_when_edit_off(self, interact_page):
        fig = self._two_panel_fig()
        page = _open(interact_page, fig)
        page.wait_for_timeout(60)
        info = page.evaluate(_GRIP_RECT_JS, 0)
        # Grip exists (lazily created) but is display:none off-edit.
        assert info["grip"] is None or info["grip"]["display"] == "none"

    def test_grip_visible_in_edit_mode(self, interact_page):
        fig = self._two_panel_fig()
        fig.edit_chrome = True
        page = _open(interact_page, fig)
        page.wait_for_timeout(60)
        info = page.evaluate(_GRIP_RECT_JS, 0)
        assert info["grip"] is not None
        assert info["grip"]["display"] == "flex"

    def test_swap_emits_with_ids(self, interact_page):
        fig = self._two_panel_fig()
        fig.edit_chrome = True
        page = _open(interact_page, fig)
        page.wait_for_timeout(60)

        g0 = page.evaluate(_GRIP_RECT_JS, 0)
        c1 = page.evaluate(_GRIP_RECT_JS, 1)["cell"]
        gx = g0["grip"]["left"] + g0["grip"]["w"] / 2
        gy = g0["grip"]["top"] + g0["grip"]["h"] / 2
        # Drop over the CENTRE of the second panel.
        tx = c1["left"] + c1["w"] / 2
        ty = c1["top"] + c1["h"] / 2

        page.mouse.move(gx, gy)
        page.mouse.down()
        page.mouse.move(tx, ty, steps=10)
        page.mouse.up()
        page.wait_for_timeout(80)

        swaps = [e for e in _get_events(page, "pointer_up") if e.get("panel_swap")]
        assert swaps, "dropping the grip over a different panel should emit panel_swap"
        last = swaps[-1]
        assert last["source_panel_id"] and last["target_panel_id"]
        assert last["source_panel_id"] != last["target_panel_id"]

    def test_swap_silent_on_source_panel(self, interact_page):
        fig = self._two_panel_fig()
        fig.edit_chrome = True
        page = _open(interact_page, fig)
        page.wait_for_timeout(60)

        g0 = page.evaluate(_GRIP_RECT_JS, 0)
        c0 = g0["cell"]
        gx = g0["grip"]["left"] + g0["grip"]["w"] / 2
        gy = g0["grip"]["top"] + g0["grip"]["h"] / 2
        # Drop back inside the SAME (source) panel → no swap.
        tx = c0["left"] + c0["w"] * 0.6
        ty = c0["top"] + c0["h"] * 0.6

        page.mouse.move(gx, gy)
        page.mouse.down()
        page.mouse.move(tx, ty, steps=8)
        page.mouse.up()
        page.wait_for_timeout(80)

        swaps = [e for e in _get_events(page, "pointer_up") if e.get("panel_swap")]
        assert swaps == [], "dropping on the source panel must not emit panel_swap"

    def test_swap_silent_on_empty_space(self, interact_page):
        fig = self._two_panel_fig()
        fig.edit_chrome = True
        page = _open(interact_page, fig)
        page.wait_for_timeout(60)

        g0 = page.evaluate(_GRIP_RECT_JS, 0)
        gx = g0["grip"]["left"] + g0["grip"]["w"] / 2
        gy = g0["grip"]["top"] + g0["grip"]["h"] / 2
        # Drop far outside any panel (top-left figure padding band).
        page.mouse.move(gx, gy)
        page.mouse.down()
        page.mouse.move(1, 1, steps=8)
        page.mouse.up()
        page.wait_for_timeout(80)

        swaps = [e for e in _get_events(page, "pointer_up") if e.get("panel_swap")]
        assert swaps == [], "dropping on empty space must not emit panel_swap"

    def test_grip_inert_when_edit_off(self, interact_page):
        fig = self._two_panel_fig()
        page = _open(interact_page, fig)   # edit_chrome stays False
        page.wait_for_timeout(60)

        # Even if we click where the grip would be, no swap fires.
        c0 = page.evaluate(_GRIP_RECT_JS, 0)["cell"]
        c1 = page.evaluate(_GRIP_RECT_JS, 1)["cell"]
        page.mouse.move(c0["left"] + 8, c0["top"] + 8)
        page.mouse.down()
        page.mouse.move(c1["left"] + c1["w"] / 2, c1["top"] + c1["h"] / 2, steps=8)
        page.mouse.up()
        page.wait_for_timeout(80)

        swaps = [e for e in _get_events(page, "pointer_up") if e.get("panel_swap")]
        assert swaps == [], "grip must be inert when edit_chrome is off"


# ═══════════════════════════════════════════════════════════════════════════
# 7. Selection / hover outline is fully INSET (not clipped at figure edges)
# ═══════════════════════════════════════════════════════════════════════════

class TestOutlineInset:
    def test_selection_outline_offset_is_negative_full_width(self, interact_page):
        fig, ax = apl.subplots(1, 1, figsize=(FIG_W, FIG_H))
        v = ax.imshow(np.zeros((16, 16), dtype=np.float32))
        fig.edit_chrome = True
        fig.selected_panel = v._id
        page = _open(interact_page, fig)
        page.wait_for_timeout(60)

        style = page.evaluate("""() => {
            let grid = null;
            for (const d of document.querySelectorAll('div')) {
                if (getComputedStyle(d).display === 'grid') { grid = d; break; }
            }
            const cell = grid ? grid.firstElementChild : null;
            return cell ? {outline: cell.style.outline,
                           offset: cell.style.outlineOffset} : null;
        }""")
        assert style and "solid" in style["outline"]
        # Fully inset: outline-offset == -2px (= -width) so nothing spills out.
        assert style["offset"] == "-2px"

    def test_hover_outline_offset_is_negative_full_width(self, interact_page):
        fig, ax = apl.subplots(1, 1, figsize=(FIG_W, FIG_H))
        ax.imshow(np.zeros((16, 16), dtype=np.float32))
        fig.edit_chrome = True
        page = interact_page(fig)

        page.mouse.move(1, 1)
        page.mouse.move(GRID_PAD + FIG_W / 2, GRID_PAD + FIG_H / 2, steps=5)
        page.wait_for_timeout(60)

        style = page.evaluate("""() => {
            let grid = null;
            for (const d of document.querySelectorAll('div')) {
                if (getComputedStyle(d).display === 'grid') { grid = d; break; }
            }
            const cell = grid ? grid.firstElementChild : null;
            return cell ? {outline: cell.style.outline,
                           offset: cell.style.outlineOffset} : null;
        }""")
        assert style and "dashed" in style["outline"]
        assert style["offset"] == "-2px"


# ═══════════════════════════════════════════════════════════════════════════
# 8. Container-resize → onResize hook fires (mount() embedding path)
# ═══════════════════════════════════════════════════════════════════════════

# Bare mount() page (Blob-URL ESM import — the proven embedding pattern; a
# file:// ES-module import is blocked, see test_embed_mount.py).  The host DIV
# is sized so we can resize it and observe onResize.
_RESIZE_PAGE = """<!DOCTYPE html>
<html><head><meta charset="utf-8"/>
<style>html,body{margin:0;padding:0;}</style></head>
<body><div id="host" style="width:400px;height:300px;"></div>
<script type="module">
const STATE = __STATE__;
const esmSource = __ESM__;
const blobUrl = URL.createObjectURL(new Blob([esmSource], {type:"text/javascript"}));
window._resizeCalls = [];
import(blobUrl).then(mod => {
  window._handle = mod.mount(document.getElementById("host"), STATE, {
    onResize: (sz) => window._resizeCalls.push(sz),
  });
  window._aplReady = true;
}).catch(err => { document.body.textContent = "mount error: " + err; });
</script></body></html>
"""


class TestContainerResizeHook:
    def test_onresize_fires_on_container_resize(self, _pw_browser):
        import pathlib
        import tempfile
        from anyplotlib.embed import esm_path, figure_state

        fig, ax = apl.subplots(1, 1, figsize=(FIG_W, FIG_H))
        ax.imshow(np.zeros((16, 16), dtype=np.float32))

        html = (_RESIZE_PAGE
                .replace("__STATE__", json.dumps(figure_state(fig)))
                .replace("__ESM__", json.dumps(esm_path().read_text(encoding="utf-8"))))
        with tempfile.NamedTemporaryFile(
                suffix=".html", mode="w", encoding="utf-8", delete=False) as fh:
            fh.write(html)
            tmp = pathlib.Path(fh.name)

        page = _pw_browser.new_page()
        try:
            page.goto(tmp.as_uri())
            page.wait_for_function("() => window._aplReady === true", timeout=15_000)
            page.evaluate("() => new Promise(r => requestAnimationFrame("
                          "() => requestAnimationFrame(r)))")
            # Clear any initial-observe calls, then resize the host container.
            page.evaluate("() => { window._resizeCalls = []; }")
            page.evaluate("""() => {
                const h = document.getElementById('host');
                h.style.width = '520px'; h.style.height = '360px';
            }""")
            page.wait_for_function(
                "() => window._resizeCalls.length > 0", timeout=5_000)
            calls = page.evaluate("() => window._resizeCalls")
            assert calls, "onResize should fire when the root container resizes"
            last = calls[-1]
            assert last["width"] == pytest.approx(520, abs=4)
            assert last["height"] == pytest.approx(360, abs=4)
        finally:
            page.close()
            tmp.unlink(missing_ok=True)


# ═══════════════════════════════════════════════════════════════════════════
# 9. Python-pushed event_json widget update through the Electron/embed
#    "state bridge" (the standalone-HTML `_repr_utils.build_standalone_html`
#    host, which is what SpyDE's report figures actually load via file://,
#    not a bare mount() page).
#
# Regression for: a single inbound `awi_state` push for one key (event_json)
# was re-firing EVERY registered change:* listener in makeModel().
# save_changes(), including every panel's `change:panel_<id>_json` listener —
# which re-parses that panel's OWN (untouched, stale) trait and overwrites
# `p.state` wholesale, silently reverting the just-applied targeted widget
# edit in the same synchronous cascade. `interact_page` (see conftest.py)
# renders through this exact template but only exposes `window._aplModel`
# (not the render() return API), so these tests build the same
# build_standalone_html() page directly and also expose `window._aplApi`
# (render()'s return value — panels / _drawFigureMarkers / figMarkerCanvas)
# so we can read the live in-memory panel state, not just the (never
# rewritten by this path) `panel_<id>_json` trait. A real
# `postMessage({type:'awi_state', ...})` — precisely how SpyDEContext's
# state_update handler talks to the report-figure iframe — exercises the
# real bridge, not a mock.
# ═══════════════════════════════════════════════════════════════════════════

def _open_repr_page(_pw_browser, fig):
    """Open *fig* via build_standalone_html() (the SpyDE report-figure /
    mount-bridge host), exposing window._aplReady + window._aplApi (render()'s
    return value: panels, figMarkerCanvas, _drawFigureMarkers, ...)."""
    import pathlib
    import tempfile
    from anyplotlib._repr_utils import build_standalone_html

    html = build_standalone_html(fig, resizable=False, fig_id="test")
    html = html.replace(
        "renderFn({ model, el });",
        "renderFn({ model, el }); window._aplReady = true;",
    )
    # _aplRenderApi is assigned right after renderFn(...) inside the same
    # import(...).then(mod => { ... }) callback — expose it too.
    html = html.replace(
        "_aplRenderApi = renderFn({ model, el }); window._aplReady = true;",
        "_aplRenderApi = renderFn({ model, el }); window._aplApi = _aplRenderApi; "
        "window._aplReady = true;",
    )
    with tempfile.NamedTemporaryFile(
            suffix=".html", mode="w", encoding="utf-8", delete=False) as fh:
        fh.write(html)
        tmp = pathlib.Path(fh.name)
    page = _pw_browser.new_page()
    page.goto(tmp.as_uri())
    page.wait_for_function("() => window._aplReady === true", timeout=15_000)
    page.evaluate(
        "() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))")
    return page, tmp


def _push_widget_field(page, panel_id, widget_id, **fields):
    """Post an `awi_state` message carrying a Python-sourced event_json patch,
    exactly the shape `Figure._push_widget` (figure/_figure.py) produces and
    exactly the channel SpyDEContext's `state_update` handler relays into a
    report-figure iframe (`postMessage({type:'awi_state', key:'event_json',
    value})`)."""
    payload = {"source": "python", "panel_id": panel_id, "widget_id": widget_id}
    payload.update(fields)
    page.evaluate(
        "(v) => window.postMessage("
        "{type:'awi_state', key:'event_json', value: JSON.stringify(v)}, '*')",
        payload,
    )


def _overlay_pixel_rgb(page, ix, iy, iw=32, ih=32):
    """Sample the overlay canvas at image pixel (ix, iy) → [r, g, b, a]."""
    return page.evaluate("""(args) => {
        const [ix, iy, iw, ih] = args;
        let overlay = null;
        for (const cv of document.querySelectorAll('canvas')) {
            if (getComputedStyle(cv).pointerEvents === 'all') { overlay = cv; break; }
        }
        if (!overlay) return null;
        const r = overlay.getBoundingClientRect();
        const s = Math.min(r.width / iw, r.height / ih);
        const ox = (r.width - iw * s) / 2.0, oy = (r.height - ih * s) / 2.0;
        // Canvas backing store may be DPR-scaled relative to its CSS rect.
        const scaleX = overlay.width / r.width, scaleY = overlay.height / r.height;
        const px = Math.round((ox + ix * s) * scaleX);
        const py = Math.round((oy + iy * s) * scaleY);
        const ctx = overlay.getContext('2d');
        const d = ctx.getImageData(px, py, 1, 1).data;
        return [d[0], d[1], d[2], d[3]];
    }""", [ix, iy, iw, ih])


class TestPythonPushedWidgetUpdate:
    def test_event_json_push_updates_stored_color(self, _pw_browser):
        """Widget.set(color=...) → Figure._push_widget → event_json, relayed
        through the SAME postMessage bridge SpyDE uses, must land in the
        JS-side overlay_widgets state (not just get silently reverted by a
        stale panel_<id>_json re-sync riding the same save_changes() call)."""
        fig, ax = apl.subplots(1, 1, figsize=(FIG_W, FIG_H))
        v = ax.imshow(np.zeros((32, 32), dtype=np.float32))
        w = v.add_circle_widget(cx=16, cy=16, r=6, color="#00e5ff")
        page, tmp = _open_repr_page(_pw_browser, fig)
        try:
            _push_widget_field(page, v._id, w.id, color="#ff00ff")
            page.wait_for_timeout(150)

            widgets = page.evaluate(
                "(pid) => window._aplApi.panels.get(pid).state.overlay_widgets", v._id)
            assert widgets and widgets[0]["id"] == w.id
            assert widgets[0]["color"] == "#ff00ff", (
                "Python-pushed event_json color update did not survive — a stale "
                "panel_<id>_json re-sync riding the same save_changes() cascade "
                "reverted it")
        finally:
            page.close()
            tmp.unlink(missing_ok=True)

    def test_event_json_push_repaints_the_pixel_color(self, _pw_browser):
        """Same push, but assert the actual redrawn pixels changed color —
        the stored-state check alone wouldn't catch a case where the field
        applies but _redrawPanel silently no-ops."""
        fig, ax = apl.subplots(1, 1, figsize=(FIG_W, FIG_H))
        v = ax.imshow(np.zeros((32, 32), dtype=np.float32))
        # A big, thick-stroked circle so the sample point is squarely on ink.
        w = v.add_circle_widget(cx=16, cy=16, r=10, color="#ff0000")
        page, tmp = _open_repr_page(_pw_browser, fig)
        try:
            before = _overlay_pixel_rgb(page, 26, 16)   # east point of the circle
            assert before is not None and before[3] > 0, "no ink at the sample point before the push"
            assert before[0] > 150 and before[1] < 80, f"expected red stroke, got {before}"

            _push_widget_field(page, v._id, w.id, color="#00ff00")
            page.wait_for_timeout(150)

            after = _overlay_pixel_rgb(page, 26, 16)
            assert after is not None and after[3] > 0, "ink disappeared after the push"
            assert after[1] > 150 and after[0] < 80, (
                f"pixel did not repaint green after the Python-pushed color update: {after}")
        finally:
            page.close()
            tmp.unlink(missing_ok=True)

    def test_event_json_push_does_not_disturb_other_traits(self, _pw_browser):
        """A figure_markers_json push arriving right after an event_json push
        (same bridge, same makeModel) must still apply — guards against an
        overzealous fix that under-fires instead of over-firing."""
        fig, ax = apl.subplots(1, 1, figsize=(FIG_W, FIG_H))
        v = ax.imshow(np.zeros((32, 32), dtype=np.float32))
        w = v.add_circle_widget(cx=16, cy=16, r=6, color="#00e5ff")
        page, tmp = _open_repr_page(_pw_browser, fig)
        try:
            _push_widget_field(page, v._id, w.id, color="#ff00ff")
            page.wait_for_timeout(60)

            markers = [{"id": "m1", "kind": "circle", "x": 0.5, "y": 0.5,
                        "r": 0.2, "color": "#ff9800"}]
            page.evaluate(
                "(v) => window.postMessage("
                "{type:'awi_state', key:'figure_markers_json', value: JSON.stringify(v)}, '*')",
                markers,
            )
            page.wait_for_timeout(150)

            widgets = page.evaluate(
                "(pid) => window._aplApi.panels.get(pid).state.overlay_widgets", v._id)
            assert widgets[0]["color"] == "#ff00ff", "earlier event_json push was lost"

            ink = page.evaluate("""() => {
                const c = window._aplApi.figMarkerCanvas;
                if (!c) return -1;
                const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
                let n = 0;
                for (let i = 3; i < d.length; i += 4) if (d[i] > 0) n++;
                return n;
            }""")
            assert ink > 0, "figure_markers_json push did not draw the marker"
        finally:
            page.close()
            tmp.unlink(missing_ok=True)

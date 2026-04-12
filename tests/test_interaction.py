"""
tests/test_interaction.py
=========================

Real browser interaction tests using headless Chromium (Playwright).

These tests open the widget's standalone HTML in a real browser, fire
actual mouse events (mousedown → mousemove → mouseup), and verify that:

  * Widget positions update correctly in the panel JSON state.
  * ``on_changed`` events are emitted during a drag.
  * ``on_release`` events are emitted on mouseup with the correct widget ID.

All coordinate maths mirrors the JavaScript constants exactly:
  PAD_L=58  PAD_R=12  PAD_T=12  PAD_B=42  gridDiv padding=8 px

For a 400×240 figure the plot rectangle in canvas space is:
  r = {x:58, y:12, w:330, h:186}

Canvas coords → page coords:  page_x = canvas_x + 8,  page_y = canvas_y + 8

Run:
    uv run pytest tests/test_interaction.py -v

"""
from __future__ import annotations

import json

import numpy as np
import pytest

import anyplotlib as apl

# ── layout constants (must match figure_esm.js) ───────────────────────────
PAD_L, PAD_R, PAD_T, PAD_B = 58, 12, 12, 42
GRID_PAD = 8  # gridDiv padding:8px — offset of canvas from page origin


# ── coordinate helpers ────────────────────────────────────────────────────

def _plot_rect(pw: int, ph: int) -> dict:
    """Return the 1-D/1-D-bar plot rectangle (mirrors _plotRect1d in JS)."""
    return dict(x=PAD_L, y=PAD_T, w=pw - PAD_L - PAD_R, h=ph - PAD_T - PAD_B)


def _data_to_frac(x_val: float, n_samples: int) -> float:
    """Data value → [0,1] fraction for a uniform x_axis = arange(n_samples)."""
    return x_val / (n_samples - 1)


def _frac_to_canvas_x(frac: float, r: dict,
                       view_x0: float = 0.0, view_x1: float = 1.0) -> float:
    """Fraction along the data axis → canvas-space x pixel."""
    return r["x"] + ((frac - view_x0) / (view_x1 - view_x0)) * r["w"]


def _val_to_canvas_y(val: float, data_min: float, data_max: float,
                     r: dict) -> float:
    """Data value → canvas-space y pixel (mirrors _valToPy1d in JS)."""
    return r["y"] + r["h"] - ((val - data_min) / (data_max - data_min)) * r["h"]


def _to_page(canvas_x: float, canvas_y: float) -> tuple[int, int]:
    """Canvas-space (x, y) → integer page-space (x, y)."""
    return int(round(canvas_x)) + GRID_PAD, int(round(canvas_y)) + GRID_PAD


def _rafter(page) -> None:
    """Wait one requestAnimationFrame so any pending draw/commit settles."""
    page.evaluate("() => new Promise(r => requestAnimationFrame(r))")


def _panel_state(page, panel_id: str) -> dict:
    """Return the parsed panel JSON from the model."""
    raw = page.evaluate(f"() => window._aplModel.get('panel_{panel_id}_json')")
    return json.loads(raw)


def _event(page) -> dict:
    """Return the last parsed event_json from the model."""
    raw = page.evaluate("() => window._aplModel.get('event_json')")
    return json.loads(raw)


# ── shared figure parameters ──────────────────────────────────────────────
FIG_W, FIG_H = 400, 240
N = 100  # number of data samples; x_axis = [0, 1, …, 99]

# ── CSS-scale simulation helpers ──────────────────────────────────────────

def _to_page_scaled(canvas_x: float, canvas_y: float, scale: float) -> tuple[int, int]:
    """Canvas coords → page coords when outerDiv has transform:scale(s) origin top-left.

    With transform-origin:top left the canvas (at layout offset GRID_PAD inside
    outerDiv) maps to visual page position::

        page_x = (GRID_PAD + canvas_x) * scale
        page_y = (GRID_PAD + canvas_y) * scale

    These are the coordinates a user would actually click on screen.
    """
    return (
        int(round((GRID_PAD + canvas_x) * scale)),
        int(round((GRID_PAD + canvas_y) * scale)),
    )


def _inject_scale(page, scale: float = 0.75) -> float:
    """Simulate a narrow Jupyter cell so ``_applyScale()`` computes AND maintains scale.

    The naive approach — directly setting ``transform:scale(s)`` on
    ``.apl-outer`` — breaks under drag because every ``model.save_changes()``
    in the standalone shim fires the ``change:layout_json`` callback, which
    schedules ``requestAnimationFrame(_applyScale)``.  ``_applyScale`` then
    recomputes ``s = cellW/nativeW`` and, seeing a cell that looks native-width,
    silently **removes** the manually-injected transform.

    Instead, we constrain ``#widget-root`` to ``nativeW * scale`` pixels so
    that ``_applyScale`` reads ``cellW = cell_w``, derives the same ``s``, and
    keeps re-applying it on every rAF — including those triggered during drag.

    The ``out.style.width = nativeW + 'px'`` pin below is a **defensive
    guard** only: since ``.apl-outer`` now carries ``min-width: max-content``
    in its CSS class, ``outerDiv.offsetWidth`` already equals the true native
    figure width even when the parent ``scaleWrap`` has been narrowed.
    Without ``min-width: max-content`` the ``inline-block`` would shrink to
    ``cellW``, making ``_applyScale`` compute ``s = cellW/cellW = 1.0``.

    Returns the actual scale factor applied (the ``s`` passed to the transform).
    """
    native_w = page.evaluate(
        "() => { const o = document.querySelector('.apl-outer'); return o ? o.offsetWidth : 0; }"
    )
    cell_w = max(10, int(round(native_w * scale)))
    # 1. Pin outerDiv width explicitly (defensive — min-width:max-content in
    #    .apl-outer CSS already prevents shrinkage, but this is cheap insurance
    #    for any edge-case where the class hasn't fully applied yet).
    # 2. Constrain #widget-root so _applyScale reads cellW = cell_w on every
    #    rAF — including those triggered by save_changes() during drag.
    # 3. Apply the transform immediately (same formula as _applyScale) so the
    #    scale takes effect without waiting for a rAF cycle to fire.
    actual_s = page.evaluate(f"""() => {{
        const el  = document.getElementById('widget-root');
        const out = document.querySelector('.apl-outer');
        if (!out || !el) return 1.0;
        // Defensive pin (redundant when min-width:max-content is active)
        const nativeW = out.offsetWidth;
        out.style.width = nativeW + 'px';
        // Constrain container so _applyScale re-derives s on every rAF
        el.style.maxWidth = '{cell_w}px';
        el.style.overflow = 'visible';
        // Apply scale immediately (mirrors _applyScale formula)
        const s = Math.min(1.0, {cell_w} / nativeW);
        out.style.transformOrigin = 'top left';
        out.style.transform = s < 1 ? 'scale(' + s + ')' : '';
        return s;
    }}""")
    _rafter(page)
    return float(actual_s) if actual_s else scale


# ═══════════════════════════════════════════════════════════════════════════
# VLine drag tests
# ═══════════════════════════════════════════════════════════════════════════

class TestVLineDrag1D:
    """Drag a VLineWidget on a 1-D panel and verify JS state + events."""

    def _make_fig(self):
        fig, ax = apl.subplots(1, 1, figsize=(FIG_W, FIG_H))
        t = np.arange(N, dtype=float)
        plot = ax.plot(np.sin(2 * np.pi * t / N))
        return fig, plot

    def _vline_page_coords(self, x_data: float, ph_override: int = FIG_H) -> tuple[int, int]:
        r = _plot_rect(FIG_W, ph_override)
        frac = _data_to_frac(x_data, N)
        cx = _frac_to_canvas_x(frac, r)
        # Use mid-height so the |mx - px| <= 5 hit-test branch fires reliably.
        cy = r["y"] + r["h"] // 2
        return _to_page(cx, cy)

    def test_position_changes_after_drag(self, interact_page):
        """Dragging the vline left updates its x value in the panel state."""
        fig, plot = self._make_fig()
        vline = plot.add_vline_widget(50.0)
        panel_id = plot._id

        page = interact_page(fig)
        r = _plot_rect(FIG_W, FIG_H)

        # Click on the vline at x=50, drag left to approximately x=20.
        px_start, py_start = self._vline_page_coords(50.0)
        frac_end = _data_to_frac(20.0, N)
        cx_end = _frac_to_canvas_x(frac_end, r)
        px_end, py_end = _to_page(cx_end, r["y"] + r["h"] // 2)

        page.mouse.move(px_start, py_start)
        page.mouse.down()
        page.mouse.move(px_end, py_end, steps=10)
        page.mouse.up()
        _rafter(page)

        new_x = _panel_state(page, panel_id)["overlay_widgets"][0]["x"]
        assert new_x < 35, f"VLine should have moved left; got x={new_x:.2f}"
        assert new_x > 5,  f"VLine should not have overshot; got x={new_x:.2f}"

    def test_release_event_widget_id(self, interact_page):
        """on_release event_json carries the correct widget ID."""
        fig, plot = self._make_fig()
        vline = plot.add_vline_widget(50.0)
        wid_id = vline._id

        page = interact_page(fig)
        r = _plot_rect(FIG_W, FIG_H)

        px_start, py_start = self._vline_page_coords(50.0)
        cx_end = _frac_to_canvas_x(_data_to_frac(30.0, N), r)
        px_end, py_end = _to_page(cx_end, r["y"] + r["h"] // 2)

        page.mouse.move(px_start, py_start)
        page.mouse.down()
        page.mouse.move(px_end, py_end, steps=10)
        page.mouse.up()
        _rafter(page)

        ev = _event(page)
        assert ev["event_type"] == "on_release", f"Expected on_release, got {ev['event_type']!r}"
        assert ev["widget_id"] == wid_id, (
            f"Event widget_id {ev['widget_id']!r} != expected {wid_id!r}"
        )

    def test_on_changed_events_during_drag(self, interact_page):
        """on_changed events are emitted for every mousemove during drag."""
        fig, plot = self._make_fig()
        vline = plot.add_vline_widget(50.0)
        wid_id = vline._id

        page = interact_page(fig)
        r = _plot_rect(FIG_W, FIG_H)

        # Patch model.set to accumulate event_json writes before the drag.
        page.evaluate("""() => {
            window._aplAllEvents = [];
            const orig = window._aplModel.set.bind(window._aplModel);
            window._aplModel.set = (k, v) => {
                if (k === 'event_json') {
                    try { window._aplAllEvents.push(JSON.parse(v)); } catch(_) {}
                }
                return orig(k, v);
            };
        }""")

        px_start, py_start = self._vline_page_coords(50.0)
        cx_end = _frac_to_canvas_x(_data_to_frac(25.0, N), r)
        px_end, py_end = _to_page(cx_end, r["y"] + r["h"] // 2)

        page.mouse.move(px_start, py_start)
        page.mouse.down()
        page.mouse.move(px_end, py_end, steps=8)
        page.mouse.up()
        _rafter(page)

        events = page.evaluate("() => window._aplAllEvents")

        changed = [e for e in events if e.get("event_type") == "on_changed"]
        released = [e for e in events if e.get("event_type") == "on_release"]

        assert len(changed) > 0, "Expected at least one on_changed event during drag"
        assert len(released) == 1, f"Expected exactly one on_release, got {len(released)}"
        assert all(e["widget_id"] == wid_id for e in changed + released), (
            "All events should carry the correct widget_id"
        )

    def test_drag_right_increases_x(self, interact_page):
        """Dragging the vline right increases its x value."""
        fig, plot = self._make_fig()
        vline = plot.add_vline_widget(20.0)
        panel_id = plot._id

        page = interact_page(fig)
        r = _plot_rect(FIG_W, FIG_H)

        px_start, py_start = self._vline_page_coords(20.0)
        cx_end = _frac_to_canvas_x(_data_to_frac(60.0, N), r)
        px_end, py_end = _to_page(cx_end, r["y"] + r["h"] // 2)

        page.mouse.move(px_start, py_start)
        page.mouse.down()
        page.mouse.move(px_end, py_end, steps=10)
        page.mouse.up()
        _rafter(page)

        new_x = _panel_state(page, panel_id)["overlay_widgets"][0]["x"]
        assert new_x > 35, f"VLine should have moved right; got x={new_x:.2f}"
        assert new_x < 80, f"VLine should not have overshot; got x={new_x:.2f}"


# ═══════════════════════════════════════════════════════════════════════════
# HLine drag tests
# ═══════════════════════════════════════════════════════════════════════════

class TestHLineDrag1D:
    """Drag an HLineWidget on a 1-D panel and verify JS state."""

    def _make_fig(self):
        fig, ax = apl.subplots(1, 1, figsize=(FIG_W, FIG_H))
        t = np.arange(N, dtype=float)
        # Sine so data spans [-1, 1]; padding gives data_min≈-1.1, data_max≈1.1.
        plot = ax.plot(np.sin(2 * np.pi * t / N))
        return fig, plot

    def test_drag_up_increases_y(self, interact_page):
        """Dragging the hline upward increases its data-y value."""
        fig, plot = self._make_fig()
        data_min = plot._state["data_min"]
        data_max = plot._state["data_max"]
        hline = plot.add_hline_widget(0.0)
        panel_id = plot._id

        page = interact_page(fig)
        r = _plot_rect(FIG_W, FIG_H)

        # Canvas coords for y=0.0 (mid-range).
        cy_start = _val_to_canvas_y(0.0, data_min, data_max, r)
        # Use mid-plot x so we're safely inside the plot area.
        cx_mid = r["x"] + r["w"] // 2
        px_start, py_start = _to_page(cx_mid, cy_start)

        # Drag up by 40 canvas pixels.
        px_end, py_end = _to_page(cx_mid, cy_start - 40)

        page.mouse.move(px_start, py_start)
        page.mouse.down()
        page.mouse.move(px_end, py_end, steps=10)
        page.mouse.up()
        _rafter(page)

        new_y = _panel_state(page, panel_id)["overlay_widgets"][0]["y"]
        assert new_y > 0.2, f"HLine should have moved up; got y={new_y:.3f}"
        assert new_y < data_max, f"HLine should stay within data range; got y={new_y:.3f}"

    def test_drag_down_decreases_y(self, interact_page):
        """Dragging the hline downward decreases its data-y value."""
        fig, plot = self._make_fig()
        data_min = plot._state["data_min"]
        data_max = plot._state["data_max"]
        hline = plot.add_hline_widget(0.0)
        panel_id = plot._id

        page = interact_page(fig)
        r = _plot_rect(FIG_W, FIG_H)

        cy_start = _val_to_canvas_y(0.0, data_min, data_max, r)
        cx_mid = r["x"] + r["w"] // 2
        px_start, py_start = _to_page(cx_mid, cy_start)
        # Drag down by 40 canvas pixels.
        px_end, py_end = _to_page(cx_mid, cy_start + 40)

        page.mouse.move(px_start, py_start)
        page.mouse.down()
        page.mouse.move(px_end, py_end, steps=10)
        page.mouse.up()
        _rafter(page)

        new_y = _panel_state(page, panel_id)["overlay_widgets"][0]["y"]
        assert new_y < -0.2, f"HLine should have moved down; got y={new_y:.3f}"
        assert new_y > data_min, f"HLine should stay within data range; got y={new_y:.3f}"

    def test_release_event_widget_id(self, interact_page):
        """on_release carries the hline widget ID."""
        fig, plot = self._make_fig()
        data_min = plot._state["data_min"]
        data_max = plot._state["data_max"]
        hline = plot.add_hline_widget(0.0)
        wid_id = hline._id

        page = interact_page(fig)
        r = _plot_rect(FIG_W, FIG_H)

        cy_start = _val_to_canvas_y(0.0, data_min, data_max, r)
        cx_mid = r["x"] + r["w"] // 2
        px_start, py_start = _to_page(cx_mid, cy_start)
        px_end, py_end = _to_page(cx_mid, cy_start - 30)

        page.mouse.move(px_start, py_start)
        page.mouse.down()
        page.mouse.move(px_end, py_end, steps=8)
        page.mouse.up()
        _rafter(page)

        ev = _event(page)
        assert ev["event_type"] == "on_release"
        assert ev["widget_id"] == wid_id


# ═══════════════════════════════════════════════════════════════════════════
# Point widget drag tests
# ═══════════════════════════════════════════════════════════════════════════

class TestPointDrag1D:
    """Drag a PointWidget on a 1-D panel — verifies 2-D free movement."""

    # Hit-test radius for the point handle (HR+4 = 11 px, from the JS).
    _HIT_R = 11

    def _make_fig(self, x_init: float = 50.0, y_init: float = 0.0):
        fig, ax = apl.subplots(1, 1, figsize=(FIG_W, FIG_H))
        t = np.arange(N, dtype=float)
        plot = ax.plot(np.sin(2 * np.pi * t / N))
        pt = plot.add_point_widget(x_init, y_init)
        return fig, plot, pt

    def _point_page_coords(self, x_data: float, y_data: float,
                           data_min: float, data_max: float) -> tuple[int, int]:
        r = _plot_rect(FIG_W, FIG_H)
        frac = _data_to_frac(x_data, N)
        cx = _frac_to_canvas_x(frac, r)
        cy = _val_to_canvas_y(y_data, data_min, data_max, r)
        return _to_page(cx, cy)

    def test_drag_changes_both_x_and_y(self, interact_page):
        """Dragging the point widget updates both x and y in the panel state."""
        fig, plot, pt = self._make_fig(50.0, 0.0)
        panel_id = plot._id
        data_min = plot._state["data_min"]
        data_max = plot._state["data_max"]

        page = interact_page(fig)
        r = _plot_rect(FIG_W, FIG_H)

        # Start on the point at (x=50, y=0).
        px_start, py_start = self._point_page_coords(50.0, 0.0, data_min, data_max)

        # Drag to approximately x=30, y=0.4.
        cx_end = _frac_to_canvas_x(_data_to_frac(30.0, N), r)
        cy_end = _val_to_canvas_y(0.4, data_min, data_max, r)
        px_end, py_end = _to_page(cx_end, cy_end)

        page.mouse.move(px_start, py_start)
        page.mouse.down()
        page.mouse.move(px_end, py_end, steps=12)
        page.mouse.up()
        _rafter(page)

        ws = _panel_state(page, panel_id)["overlay_widgets"][0]
        assert ws["x"] < 45,  f"Point x should have moved left; got x={ws['x']:.2f}"
        assert ws["x"] > 10,  f"Point x should not have overshot; got x={ws['x']:.2f}"
        assert ws["y"] > 0.1, f"Point y should have moved up; got y={ws['y']:.3f}"
        assert ws["y"] < 0.9, f"Point y should not have overshot; got y={ws['y']:.3f}"

    def test_release_event_widget_id(self, interact_page):
        """on_release event carries the point widget's ID."""
        fig, plot, pt = self._make_fig(50.0, 0.0)
        wid_id = pt._id
        data_min = plot._state["data_min"]
        data_max = plot._state["data_max"]

        page = interact_page(fig)
        r = _plot_rect(FIG_W, FIG_H)

        px_start, py_start = self._point_page_coords(50.0, 0.0, data_min, data_max)
        cx_end = _frac_to_canvas_x(_data_to_frac(70.0, N), r)
        cy_end = _val_to_canvas_y(-0.3, data_min, data_max, r)
        px_end, py_end = _to_page(cx_end, cy_end)

        page.mouse.move(px_start, py_start)
        page.mouse.down()
        page.mouse.move(px_end, py_end, steps=10)
        page.mouse.up()
        _rafter(page)

        ev = _event(page)
        assert ev["event_type"] == "on_release"
        assert ev["widget_id"] == wid_id

    def test_on_changed_events_during_drag(self, interact_page):
        """on_changed events fire on every mousemove step during drag."""
        fig, plot, pt = self._make_fig(50.0, 0.0)
        wid_id = pt._id
        data_min = plot._state["data_min"]
        data_max = plot._state["data_max"]

        page = interact_page(fig)
        r = _plot_rect(FIG_W, FIG_H)

        page.evaluate("""() => {
            window._aplAllEvents = [];
            const orig = window._aplModel.set.bind(window._aplModel);
            window._aplModel.set = (k, v) => {
                if (k === 'event_json') {
                    try { window._aplAllEvents.push(JSON.parse(v)); } catch(_) {}
                }
                return orig(k, v);
            };
        }""")

        px_start, py_start = self._point_page_coords(50.0, 0.0, data_min, data_max)
        cx_end = _frac_to_canvas_x(_data_to_frac(30.0, N), r)
        cy_end = _val_to_canvas_y(0.5, data_min, data_max, r)
        px_end, py_end = _to_page(cx_end, cy_end)

        page.mouse.move(px_start, py_start)
        page.mouse.down()
        page.mouse.move(px_end, py_end, steps=8)
        page.mouse.up()
        _rafter(page)

        events = page.evaluate("() => window._aplAllEvents")
        changed  = [e for e in events if e.get("event_type") == "on_changed"]
        released = [e for e in events if e.get("event_type") == "on_release"]

        assert len(changed) > 0,   "Expected on_changed events during drag"
        assert len(released) == 1, f"Expected one on_release, got {len(released)}"
        assert all(e["widget_id"] == wid_id for e in changed + released)

    def test_drag_right_and_down(self, interact_page):
        """Dragging right+down increases x and decreases y."""
        fig, plot, pt = self._make_fig(30.0, 0.4)
        panel_id = plot._id
        data_min = plot._state["data_min"]
        data_max = plot._state["data_max"]

        page = interact_page(fig)
        r = _plot_rect(FIG_W, FIG_H)

        px_start, py_start = self._point_page_coords(30.0, 0.4, data_min, data_max)
        cx_end = _frac_to_canvas_x(_data_to_frac(65.0, N), r)
        cy_end = _val_to_canvas_y(-0.4, data_min, data_max, r)
        px_end, py_end = _to_page(cx_end, cy_end)

        page.mouse.move(px_start, py_start)
        page.mouse.down()
        page.mouse.move(px_end, py_end, steps=12)
        page.mouse.up()
        _rafter(page)

        ws = _panel_state(page, panel_id)["overlay_widgets"][0]
        assert ws["x"] > 50,  f"Point x should have moved right; got x={ws['x']:.2f}"
        assert ws["y"] < 0.1, f"Point y should have moved down; got y={ws['y']:.3f}"

    def test_drag_outside_plot_clamps_to_boundary(self, interact_page):
        """Dragging past the plot edge clamps the point to the plot boundary."""
        fig, plot, pt = self._make_fig(50.0, 0.0)
        panel_id = plot._id
        data_min = plot._state["data_min"]
        data_max = plot._state["data_max"]

        page = interact_page(fig)
        r = _plot_rect(FIG_W, FIG_H)

        px_start, py_start = self._point_page_coords(50.0, 0.0, data_min, data_max)

        # Drag far to the right and up — well outside the plot area.
        far_right = r["x"] + r["w"] + 80   # 80 px past the right edge
        far_up    = r["y"] - 60             # 60 px above the top edge
        px_end, py_end = _to_page(far_right, far_up)

        page.mouse.move(px_start, py_start)
        page.mouse.down()
        page.mouse.move(px_end, py_end, steps=10)
        page.mouse.up()
        _rafter(page)

        ws = _panel_state(page, panel_id)["overlay_widgets"][0]
        # x should be clamped to ≤ the rightmost data value (99).
        assert ws["x"] <= N - 1 + 1, (
            f"Point x should be clamped to data range; got x={ws['x']:.2f}"
        )
        # y should be clamped to ≤ data_max.
        assert ws["y"] <= data_max + 0.01, (
            f"Point y should be clamped to data_max; got y={ws['y']:.3f}"
        )


# ═══════════════════════════════════════════════════════════════════════════
# Range widget drag tests
# ═══════════════════════════════════════════════════════════════════════════

class TestRangeDrag1D:
    """Drag a RangeWidget's edges and body on a 1-D panel."""

    def _make_fig(self, x0: float = 20.0, x1: float = 70.0):
        fig, ax = apl.subplots(1, 1, figsize=(FIG_W, FIG_H))
        plot = ax.plot(np.zeros(N))
        rw = plot.add_range_widget(x0, x1)
        return fig, plot, rw

    def test_right_edge_drag_moves_x1(self, interact_page):
        """Dragging the right edge inward decreases x1."""
        fig, plot, rw = self._make_fig(20.0, 70.0)
        panel_id = plot._id

        page = interact_page(fig)
        r = _plot_rect(FIG_W, FIG_H)

        # Right-edge canvas x at x1=70.
        cx_right = _frac_to_canvas_x(_data_to_frac(70.0, N), r)
        cy = r["y"] + r["h"] // 2
        px_start, py_start = _to_page(cx_right, cy)

        # Drag the right edge left to approximately x1=50.
        cx_new = _frac_to_canvas_x(_data_to_frac(50.0, N), r)
        px_end, py_end = _to_page(cx_new, cy)

        page.mouse.move(px_start, py_start)
        page.mouse.down()
        page.mouse.move(px_end, py_end, steps=10)
        page.mouse.up()
        _rafter(page)

        ws = _panel_state(page, panel_id)["overlay_widgets"][0]
        assert ws["x1"] < 65, f"Range right edge should have moved left; got x1={ws['x1']:.2f}"
        assert abs(ws["x0"] - 20.0) < 5, (
            f"Range left edge should be ~20 (unchanged); got x0={ws['x0']:.2f}"
        )

    def test_left_edge_drag_moves_x0(self, interact_page):
        """Dragging the left edge rightward increases x0."""
        fig, plot, rw = self._make_fig(20.0, 70.0)
        panel_id = plot._id

        page = interact_page(fig)
        r = _plot_rect(FIG_W, FIG_H)

        # Left-edge canvas x at x0=20.
        cx_left = _frac_to_canvas_x(_data_to_frac(20.0, N), r)
        cy = r["y"] + r["h"] // 2
        px_start, py_start = _to_page(cx_left, cy)

        # Drag the left edge right to approximately x0=40.
        cx_new = _frac_to_canvas_x(_data_to_frac(40.0, N), r)
        px_end, py_end = _to_page(cx_new, cy)

        page.mouse.move(px_start, py_start)
        page.mouse.down()
        page.mouse.move(px_end, py_end, steps=10)
        page.mouse.up()
        _rafter(page)

        ws = _panel_state(page, panel_id)["overlay_widgets"][0]
        assert ws["x0"] > 30, f"Range left edge should have moved right; got x0={ws['x0']:.2f}"
        assert abs(ws["x1"] - 70.0) < 5, (
            f"Range right edge should be ~70 (unchanged); got x1={ws['x1']:.2f}"
        )

    def test_body_drag_shifts_both_edges(self, interact_page):
        """Dragging the range body shifts both x0 and x1 by the same amount."""
        fig, plot, rw = self._make_fig(30.0, 60.0)
        panel_id = plot._id

        page = interact_page(fig)
        r = _plot_rect(FIG_W, FIG_H)

        # Body midpoint canvas x (safely inside the body, away from edges).
        cx_mid = _frac_to_canvas_x(_data_to_frac(45.0, N), r)
        cy = r["y"] + r["h"] // 2
        px_start, py_start = _to_page(cx_mid, cy)

        # Drag right by 33 canvas pixels (≈ 10 data units on a 330-px plot).
        px_end, py_end = _to_page(cx_mid + 33, cy)

        page.mouse.move(px_start, py_start)
        page.mouse.down()
        page.mouse.move(px_end, py_end, steps=10)
        page.mouse.up()
        _rafter(page)

        ws = _panel_state(page, panel_id)["overlay_widgets"][0]
        # Both edges should have moved right by roughly the same amount.
        delta_x0 = ws["x0"] - 30.0
        delta_x1 = ws["x1"] - 60.0
        assert delta_x0 > 2,  f"x0 should have moved right; Δx0={delta_x0:.2f}"
        assert delta_x1 > 2,  f"x1 should have moved right; Δx1={delta_x1:.2f}"
        assert abs(delta_x0 - delta_x1) < 3, (
            f"Both edges should shift by the same amount; Δx0={delta_x0:.2f}, Δx1={delta_x1:.2f}"
        )

    def test_release_event_widget_id(self, interact_page):
        """on_release event carries the range widget's ID."""
        fig, plot, rw = self._make_fig(30.0, 70.0)
        wid_id = rw._id

        page = interact_page(fig)
        r = _plot_rect(FIG_W, FIG_H)

        cx_right = _frac_to_canvas_x(_data_to_frac(70.0, N), r)
        cy = r["y"] + r["h"] // 2
        px_start, py_start = _to_page(cx_right, cy)
        px_end, py_end = _to_page(cx_right - 40, cy)

        page.mouse.move(px_start, py_start)
        page.mouse.down()
        page.mouse.move(px_end, py_end, steps=10)
        page.mouse.up()
        _rafter(page)

        ev = _event(page)
        assert ev["event_type"] == "on_release"
        assert ev["widget_id"] == wid_id


# ═══════════════════════════════════════════════════════════════════════════
# CSS-scale interaction tests  (simulate narrow Jupyter cell)
# ═══════════════════════════════════════════════════════════════════════════

class TestScaledInteraction1D:
    """Detect the _applyScale coordinate-mismatch bug.

    When ``_applyScale`` applies ``transform:scale(s)`` to ``outerDiv`` (because
    the Jupyter output cell is narrower than the figure), every event handler
    that computes ``e.clientX - getBoundingClientRect().left`` receives
    *visual* coordinates in the range ``[0, pw*s]`` rather than *canvas*
    coordinates in ``[0, pw]``.  Hit tests then miss by factor ``1/s``.

    Each test below:
    * calls ``_inject_scale(page, 0.75)`` to apply the transform directly —
      exactly what ``_applyScale`` would do in Jupyter,
    * clicks at the **visual** position of the widget handle (what the user
      actually sees and clicks on), and
    * asserts the widget moved.

    **Expected outcomes:**
    * **FAIL** with the current code (hit test misses → position unchanged).
    * **PASS** after the event-coordinate fix (``_clientPos`` helper divides
      by the scale factor so hit tests receive true canvas coordinates).
    """

    _SCALE = 0.75

    def test_vline_drag_under_scale(self, interact_page):
        """VLine drag at visual position must move the widget under CSS scale."""
        fig, ax = apl.subplots(1, 1, figsize=(FIG_W, FIG_H))
        plot = ax.plot(np.arange(N, dtype=float))
        vline = plot.add_vline_widget(50.0)
        panel_id = plot._id

        page = interact_page(fig)
        s = _inject_scale(page, self._SCALE)
        r = _plot_rect(FIG_W, FIG_H)

        cx = _frac_to_canvas_x(_data_to_frac(50.0, N), r)
        cy = r["y"] + r["h"] // 2
        px_s, py_s = _to_page_scaled(cx, cy, s)

        cx_end = _frac_to_canvas_x(_data_to_frac(20.0, N), r)
        px_e, py_e = _to_page_scaled(cx_end, cy, s)

        page.mouse.move(px_s, py_s)
        page.mouse.down()
        page.mouse.move(px_e, py_e, steps=10)
        page.mouse.up()
        _rafter(page)

        new_x = _panel_state(page, panel_id)["overlay_widgets"][0]["x"]
        assert new_x < 35, (
            f"VLine should have moved left under scale s={s:.2f}; "
            f"got x={new_x:.2f} (unchanged=50.0 means hit missed)"
        )

    def test_hline_drag_under_scale(self, interact_page):
        """HLine drag at visual position must move the widget under CSS scale."""
        fig, ax = apl.subplots(1, 1, figsize=(FIG_W, FIG_H))
        t = np.arange(N, dtype=float)
        plot = ax.plot(np.sin(2 * np.pi * t / N))
        data_min = plot._state["data_min"]
        data_max = plot._state["data_max"]
        hline = plot.add_hline_widget(0.0)
        panel_id = plot._id

        page = interact_page(fig)
        s = _inject_scale(page, self._SCALE)
        r = _plot_rect(FIG_W, FIG_H)

        cy = _val_to_canvas_y(0.0, data_min, data_max, r)
        cx = r["x"] + r["w"] // 2
        px_s, py_s = _to_page_scaled(cx, cy, s)
        px_e, py_e = _to_page_scaled(cx, cy - 40, s)   # drag up

        page.mouse.move(px_s, py_s)
        page.mouse.down()
        page.mouse.move(px_e, py_e, steps=10)
        page.mouse.up()
        _rafter(page)

        new_y = _panel_state(page, panel_id)["overlay_widgets"][0]["y"]
        assert new_y > 0.2, (
            f"HLine should have moved up under scale s={s:.2f}; "
            f"got y={new_y:.3f} (unchanged=0.0 means hit missed)"
        )

    def test_range_drag_under_scale(self, interact_page):
        """Range edge drag at visual position must move x1 under CSS scale."""
        fig, ax = apl.subplots(1, 1, figsize=(FIG_W, FIG_H))
        plot = ax.plot(np.zeros(N))
        rw = plot.add_range_widget(20.0, 70.0)
        panel_id = plot._id

        page = interact_page(fig)
        s = _inject_scale(page, self._SCALE)
        r = _plot_rect(FIG_W, FIG_H)

        cx_right = _frac_to_canvas_x(_data_to_frac(70.0, N), r)
        cy = r["y"] + r["h"] // 2
        px_s, py_s = _to_page_scaled(cx_right, cy, s)

        cx_new = _frac_to_canvas_x(_data_to_frac(50.0, N), r)
        px_e, py_e = _to_page_scaled(cx_new, cy, s)

        page.mouse.move(px_s, py_s)
        page.mouse.down()
        page.mouse.move(px_e, py_e, steps=10)
        page.mouse.up()
        _rafter(page)

        ws = _panel_state(page, panel_id)["overlay_widgets"][0]
        assert ws["x1"] < 65, (
            f"Range right edge should have moved under scale s={s:.2f}; "
            f"got x1={ws['x1']:.2f} (unchanged=70.0 means hit missed)"
        )

    def test_point_drag_under_scale(self, interact_page):
        """Point drag at visual position must move the widget under CSS scale.

        This is the exact failure mode the notebook user experiences: the cyan
        handle is visible but unresponsive because the hit-test coordinates are
        off by factor 1/s.
        """
        fig, ax = apl.subplots(1, 1, figsize=(FIG_W, FIG_H))
        t = np.arange(N, dtype=float)
        plot = ax.plot(np.sin(2 * np.pi * t / N))
        data_min = plot._state["data_min"]
        data_max = plot._state["data_max"]
        pt = plot.add_point_widget(50.0, 0.0)
        panel_id = plot._id

        page = interact_page(fig)
        s = _inject_scale(page, self._SCALE)
        r = _plot_rect(FIG_W, FIG_H)

        cx_s = _frac_to_canvas_x(_data_to_frac(50.0, N), r)
        cy_s = _val_to_canvas_y(0.0, data_min, data_max, r)
        px_s, py_s = _to_page_scaled(cx_s, cy_s, s)

        cx_e = _frac_to_canvas_x(_data_to_frac(30.0, N), r)
        cy_e = _val_to_canvas_y(0.4, data_min, data_max, r)
        px_e, py_e = _to_page_scaled(cx_e, cy_e, s)

        page.mouse.move(px_s, py_s)
        page.mouse.down()
        page.mouse.move(px_e, py_e, steps=12)
        page.mouse.up()
        _rafter(page)

        ws = _panel_state(page, panel_id)["overlay_widgets"][0]
        assert ws["x"] < 45, (
            f"Point x should have moved under scale s={s:.2f}; "
            f"got x={ws['x']:.2f} (unchanged=50.0 means hit missed)"
        )


# ═══════════════════════════════════════════════════════════════════════════
# Extra CSS-scale tests — pan, 2D widget drag, bar widget drag
# ═══════════════════════════════════════════════════════════════════════════

def _to_page_scaled_2d(ccx: float, ccy: float, scale: float) -> tuple[int, int]:
    """Canvas coords for a 2D overlayCanvas → page coords under CSS scale.

    For plain imshow panels (no physical axes) the overlayCanvas starts at
    (0, 0) inside the panel wrap, so the only offset is GRID_PAD::

        page_x = (GRID_PAD + ccx) * scale
        page_y = (GRID_PAD + ccy) * scale
    """
    return (
        int(round((GRID_PAD + ccx) * scale)),
        int(round((GRID_PAD + ccy) * scale)),
    )


class TestScaledInteractionExtra:
    """Additional scale tests covering pan, 2-D widget drag, and bar chart drag.

    All tests in this class apply ``transform:scale(0.75)`` to ``outerDiv``
    before firing mouse events, mirroring exactly what ``_applyScale()`` does
    in a narrow Jupyter cell.

    Expected outcomes:
    * **FAIL** with the current code (coordinates off by factor 1/s).
    * **PASS** after applying the ``_clientPos`` fix in ``figure_esm.js``.
    """

    _SCALE = 0.75

    # ── 1D pan under scale ────────────────────────────────────────────────

    def test_1d_pan_under_scale(self, interact_page):
        """Panning by N visual pixels must move the view by N/s canvas pixels.

        The broken code computes ``dx = (e.clientX - panStart.mx) / r.w``
        where the numerator is in visual (CSS-scaled) pixels and the denominator
        is in canvas pixels.  At s=0.75 this under-pans by factor s.

        Geometry (s=0.75, span=0.4, drag=-165 visual px):
          broken  nx0 = 0.3 + 165/330   × 0.4 = 0.500
          correct nx0 = 0.3 + 165/247.5 × 0.4 = 0.567

        The assertion ``view_x0 > 0.52`` cleanly separates the two outcomes.
        """
        fig, ax = apl.subplots(1, 1, figsize=(FIG_W, FIG_H))
        plot = ax.plot(np.zeros(N))
        panel_id = plot._id

        # Pre-zoom to [0.3, 0.7] so there is room to pan rightward.
        plot._state["view_x0"] = 0.3
        plot._state["view_x1"] = 0.7
        plot._push()

        page = interact_page(fig)
        s = _inject_scale(page, self._SCALE)
        r = _plot_rect(FIG_W, FIG_H)

        # Drag left (pan view to the right) starting at the plot mid-point.
        cx_start = r["x"] + r["w"] // 2
        cy_mid   = r["y"] + r["h"] // 2
        px_s, py_s = _to_page_scaled(cx_start, cy_mid, s)

        # Move 165 visual pixels to the left.
        px_e = px_s - 165
        py_e = py_s

        page.mouse.move(px_s, py_s)
        page.mouse.down()
        page.mouse.move(px_e, py_e, steps=10)
        page.mouse.up()
        _rafter(page)

        st = _panel_state(page, panel_id)
        x0 = st["view_x0"]
        assert x0 > 0.52, (
            f"Pan under scale s={s:.2f} under-panned; "
            f"got view_x0={x0:.3f} (broken≈0.500, correct≈0.567)"
        )

    # ── 2D crosshair drag under scale ─────────────────────────────────────

    def test_2d_crosshair_drag_under_scale(self, interact_page):
        """Crosshair drag at its visual position must move the widget under CSS scale.

        The broken ``_doDrag2d`` and ``_attachEvents2d`` use raw
        ``e.clientX - getBoundingClientRect().left``, which is in visual pixels,
        while ``_imgToCanvas2d`` works in canvas pixels.  At s=0.75 the
        initial hit misses by ~47 px (well outside HR+4=13) so the drag is
        never started.
        """
        rng  = np.random.default_rng(42)
        img  = rng.standard_normal((128, 128))

        fig, ax = apl.subplots(1, 1, figsize=(FIG_W, FIG_H))
        plot = ax.imshow(img)
        panel_id = plot._id

        # Crosshair centred in the image at (cx=64, cy=64) in image-pixel space.
        plot.add_widget("crosshair", cx=64.0, cy=64.0)

        page = interact_page(fig)
        s = _inject_scale(page, self._SCALE)

        # At zoom=1, center=(0.5,0.5), image 128×128 in panel 400×240,
        # no physical axes so imgW=400, imgH=240:
        #   fit = min(400/128, 240/128) = 1.875
        #   fr = {x:80, y:0, w:240, h:240}
        #   canvas pos of (64,64): ccx = 80+(64/128)*240 = 200, ccy = 120
        ccx, ccy = 200.0, 120.0
        px_s, py_s = _to_page_scaled_2d(ccx, ccy, s)

        # Drag 40 canvas pixels to the right and down.
        px_e, py_e = _to_page_scaled_2d(ccx + 40, ccy + 30, s)

        page.mouse.move(px_s, py_s)
        page.mouse.down()
        page.mouse.move(px_e, py_e, steps=10)
        page.mouse.up()
        _rafter(page)

        ws = _panel_state(page, panel_id)["overlay_widgets"][0]
        assert ws["cx"] > 64 + 5, (
            f"Crosshair cx should have moved right under scale s={s:.2f}; "
            f"got cx={ws['cx']:.2f} (unchanged=64.0 means hit missed)"
        )

    # ── bar-chart vline drag under scale ──────────────────────────────────

    def test_bar_vline_drag_under_scale(self, interact_page):
        """Bar-chart VLine drag at visual position must move the widget under CSS scale.

        ``_attachEventsBar`` calls ``_ovHitTest1d(e.clientX-rect.left, …)``
        which has the same coordinate bug as ``_attachEvents1d``.
        """
        values = np.array([1.0, 3.0, 2.0, 4.0, 2.5])
        fig, ax = apl.subplots(1, 1, figsize=(FIG_W, FIG_H))
        bar_plot = ax.bar(values)
        panel_id = bar_plot._id

        # x_axis = [-0.5, 4.5]; vline at x=2.0 (middle bar) → frac=0.5 → canvas_x=223
        vline = bar_plot.add_vline_widget(2.0)

        page = interact_page(fig)
        s = _inject_scale(page, self._SCALE)
        r = _plot_rect(FIG_W, FIG_H)

        # Canvas x for vline at data x=2.0 (frac=0.5):  PAD_L + 0.5*r.w = 58+165 = 223
        cx_vline = PAD_L + 0.5 * r["w"]
        cy_mid   = r["y"] + r["h"] // 2

        # Visual click position under scale
        px_s, py_s = _to_page_scaled(cx_vline, cy_mid, s)

        # Drag left to approximately x=0.5 (frac≈0.1 → canvas_x≈91)
        cx_end = PAD_L + 0.1 * r["w"]
        px_e, py_e = _to_page_scaled(cx_end, cy_mid, s)

        page.mouse.move(px_s, py_s)
        page.mouse.down()
        page.mouse.move(px_e, py_e, steps=10)
        page.mouse.up()
        _rafter(page)

        ws = _panel_state(page, panel_id)["overlay_widgets"][0]
        assert ws["x"] < 1.5, (
            f"Bar VLine should have moved under scale s={s:.2f}; "
            f"got x={ws['x']:.3f} (unchanged=2.0 means hit missed)"
        )

    # ── bar-chart on_click under scale ───────────────────────────────────

    def test_bar_click_under_scale(self, interact_page):
        """Bar on_click fires with correct bar_index when clicking at the
        visual (scaled) position of a bar.

        The test clicks at a position that is correct in *visual* (scaled)
        coordinates but would be wrong in unscaled canvas coordinates.
        ``_clientPos`` must undo the CSS transform so the hit-test operates
        in canvas space.

        Bar geometry (vertical, 5 bars, default bar_width=0.7, FIG_W=400):
          slotPx = 330 / 5 = 66
          bar 2 centre_x = 58 + 2.5 × 66 = 223 (canvas px)
          bar 2 y-range  = [barTopY, basePx] — computed from data_min/data_max
          click y        = midpoint of bar 2's y-span (safely inside the bar)
        """
        values = np.array([1.0, 3.0, 2.0, 4.0, 2.5])
        fig, ax = apl.subplots(1, 1, figsize=(FIG_W, FIG_H))
        bar_plot = ax.bar(values)
        panel_id = bar_plot._id

        # Read axis bounds computed by PlotBar (includes 7 % padding above max).
        data_min = bar_plot._state["data_min"]   # == 0.0
        data_max = bar_plot._state["data_max"]   # ≈ 4.28

        page = interact_page(fig)
        s = _inject_scale(page, self._SCALE)
        r = _plot_rect(FIG_W, FIG_H)

        # Bar geometry
        n_bars   = len(values)
        slot_px  = r["w"] / n_bars
        cx_bar2  = r["x"] + (2 + 0.5) * slot_px          # 58 + 165 = 223

        # y-coordinate: midpoint between bar 2's top and the baseline (bottom)
        bar_top_y  = _val_to_canvas_y(values[2], data_min, data_max, r)
        baseline_y = _val_to_canvas_y(0.0,       data_min, data_max, r)
        cy_bar2    = (bar_top_y + baseline_y) / 2          # well inside the bar

        # Scaled visual click position
        px_click, py_click = _to_page_scaled(cx_bar2, cy_bar2, s)

        page.mouse.click(px_click, py_click)
        _rafter(page)

        ev = _event(page)
        assert ev.get("event_type") == "on_click", (
            f"Expected on_click event under scale s={s:.2f}; "
            f"got event_type={ev.get('event_type')!r} "
            f"(missing means _clientPos failed to undo the CSS transform)"
        )
        assert ev.get("bar_index") == 2, (
            f"Expected bar_index=2 under scale s={s:.2f}; "
            f"got bar_index={ev.get('bar_index')!r}"
        )



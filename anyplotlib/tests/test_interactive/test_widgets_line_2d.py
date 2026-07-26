"""
tests/test_interactive/test_widgets_line_2d.py
===============================================

Three 2-D overlay widget kinds:

``line``
    A bare two-endpoint segment.  ``arrow`` draws a head and ``polygon``
    needs >= 3 vertices and closes the path, so neither could stand in for a
    line profile / cross-section cut / two-point measurement.

``vline`` / ``hline``
    Full-height / full-width rules, grabbable anywhere along their length.
    These existed on 1-D panels only; a 2-D panel had to fake a single-axis
    pointer with a ``crosshair``, which leaves a stray perpendicular rule.

Also covered: a ``crosshair`` can now be grabbed by either of its rules, not
only at the one-pixel centre hotspot.  Grabbing a rule constrains the drag to
that rule's own axis.

Drag tests aim at the real on-canvas geometry published by the draw path
(``window._aplWidgetGeom``) rather than deriving it from figure padding — the
image->canvas mapping depends on the zoom/extent state and the grab radius is
only HR=9 px, so a hard-coded guess silently misses and asserts nothing.
"""
from __future__ import annotations

import numpy as np
import pytest

import anyplotlib as apl
from anyplotlib.widgets import LineWidget
from anyplotlib.tests.test_interactive._event_test_utils import _collect_events

FIG_W, FIG_H = 400, 400
IMG = 64


# ── helpers ───────────────────────────────────────────────────────────────────

def _collect_panel_state(page) -> None:
    page.evaluate("""() => {
        window._aplPanelState = {};
        const m = window._aplModel;
        const orig = m.set.bind(m);
        m.set = (k, v) => {
            const mm = /^panel_(.+)_json$/.exec(k);
            if (mm) { try { window._aplPanelState[mm[1]] = JSON.parse(v); } catch(_) {} }
            return orig(k, v);
        };
    }""")


def _seed_panel_state(page, plot_id) -> None:
    page.evaluate(
        """(pid) => {
            try {
                const v = window._aplModel.get('panel_' + pid + '_json');
                if (v) window._aplPanelState[pid] = JSON.parse(v);
            } catch(_) {}
        }""", str(plot_id))


def _widget_state(page, plot_id, idx=0):
    return page.evaluate(
        """([pid, i]) => {
            const st = window._aplPanelState && window._aplPanelState[pid];
            const ws = st && st.overlay_widgets;
            return ws && ws[i] ? ws[i] : null;
        }""", [str(plot_id), idx])


def _canvas_origin(page):
    return page.evaluate("""() => {
        const c = document.querySelector('canvas');
        const r = c.getBoundingClientRect();
        return {left: r.left, top: r.top};
    }""")


def _geom(page, plot_id, widget_id):
    return page.evaluate(
        """([pid, wid]) => {
            const g = window._aplWidgetGeom && window._aplWidgetGeom[pid];
            return g ? (g[wid] || null) : null;
        }""", [str(plot_id), str(widget_id)])


def _open(interact_page, add):
    fig, ax = apl.subplots(1, 1, figsize=(FIG_W, FIG_H))
    plot = ax.imshow(np.zeros((IMG, IMG), dtype=np.float32))
    widget = add(plot)
    page = interact_page(fig)
    _collect_events(page)
    _collect_panel_state(page)
    _seed_panel_state(page, plot._id)
    return fig, plot, page, widget


def _drag(page, x0, y0, dx, dy):
    page.mouse.move(x0, y0)
    page.mouse.down()
    page.mouse.move(x0 + dx, y0 + dy, steps=10)
    page.mouse.up()
    page.wait_for_timeout(80)


# ═══════════════════════════════════════════════════════════════════════════
# 1. Python API
# ═══════════════════════════════════════════════════════════════════════════

class TestLineWidgetApi:
    def test_stores_endpoints(self):
        w = LineWidget(lambda: None, x1=1, y1=2, x2=3, y2=4)
        assert (w.x1, w.y1, w.x2, w.y2) == (1.0, 2.0, 3.0, 4.0)

    def test_type_is_line(self):
        assert LineWidget(lambda: None, x1=0, y1=0, x2=1, y2=1).get("type") == "line"

    def test_length(self):
        w = LineWidget(lambda: None, x1=0, y1=0, x2=3, y2=4)
        assert w.length == pytest.approx(5.0)

    def test_reaches_the_state_dict(self):
        w = LineWidget(lambda: None, x1=0, y1=0, x2=3, y2=4)
        assert w.to_dict()["x2"] == 3.0

    def test_add_line_widget_defaults(self):
        fig, ax = apl.subplots(1, 1)
        plot = ax.imshow(np.zeros((IMG, IMG)))
        w = plot.add_line_widget()
        assert w.x1 == IMG * 0.25 and w.x2 == IMG * 0.75

    @pytest.mark.parametrize("kind", ["line", "vline", "hline"])
    def test_add_widget_dispatch(self, kind):
        fig, ax = apl.subplots(1, 1)
        plot = ax.imshow(np.zeros((IMG, IMG)))
        assert plot.add_widget(kind).get("type") == kind

    def test_vline_defaults_to_middle(self):
        fig, ax = apl.subplots(1, 1)
        plot = ax.imshow(np.zeros((IMG, IMG)))
        assert plot.add_vline_widget().x == IMG / 2

    def test_hline_defaults_to_middle(self):
        fig, ax = apl.subplots(1, 1)
        plot = ax.imshow(np.zeros((IMG, IMG)))
        assert plot.add_hline_widget().y == IMG / 2

    def test_widgets_reach_the_wire(self):
        fig, ax = apl.subplots(1, 1)
        plot = ax.imshow(np.zeros((IMG, IMG)))
        plot.add_widget("line")
        plot.add_widget("vline")
        plot.add_widget("hline")
        types = [w["type"] for w in plot.to_state_dict()["overlay_widgets"]]
        assert types == ["line", "vline", "hline"]


# ═══════════════════════════════════════════════════════════════════════════
# 2. Rendering
# ═══════════════════════════════════════════════════════════════════════════

def _ink(img, rgb=(255, 0, 0), tol=60):
    a = img[..., :3].astype(int)
    return int((np.abs(a - np.array(rgb)).sum(axis=-1) < tol).sum())


class TestRendering:
    def test_line_is_drawn(self, take_screenshot):
        fig, ax = apl.subplots(1, 1, figsize=(FIG_W, FIG_H))
        plot = ax.imshow(np.zeros((IMG, IMG), dtype=np.float32))
        plot.add_line_widget(x1=8, y1=8, x2=56, y2=56, color="#ff0000",
                             show_handles=False)
        assert _ink(take_screenshot(fig)) > 100

    def test_vline_spans_more_rows_than_a_short_segment(self, take_screenshot):
        """A full-height rule must be taller than a stub segment."""
        def render(add):
            fig, ax = apl.subplots(1, 1, figsize=(FIG_W, FIG_H))
            plot = ax.imshow(np.zeros((IMG, IMG), dtype=np.float32))
            add(plot)
            img = take_screenshot(fig)[..., :3].astype(int)
            mask = np.abs(img - np.array([255, 0, 0])).sum(axis=-1) < 60
            return mask.any(axis=1).sum()   # number of rows containing ink

        rule = render(lambda p: p.add_vline_widget(x=32, color="#ff0000"))
        stub = render(lambda p: p.add_line_widget(x1=32, y1=30, x2=32, y2=34,
                                                  color="#ff0000",
                                                  show_handles=False))
        assert rule > stub * 3

    def test_hline_spans_more_columns_than_a_short_segment(self, take_screenshot):
        def render(add):
            fig, ax = apl.subplots(1, 1, figsize=(FIG_W, FIG_H))
            plot = ax.imshow(np.zeros((IMG, IMG), dtype=np.float32))
            add(plot)
            img = take_screenshot(fig)[..., :3].astype(int)
            mask = np.abs(img - np.array([255, 0, 0])).sum(axis=-1) < 60
            return mask.any(axis=0).sum()   # columns containing ink

        rule = render(lambda p: p.add_hline_widget(y=32, color="#ff0000"))
        stub = render(lambda p: p.add_line_widget(x1=30, y1=32, x2=34, y2=32,
                                                  color="#ff0000",
                                                  show_handles=False))
        assert rule > stub * 3

    def test_line_has_no_arrowhead(self, take_screenshot):
        """The whole point of a separate kind: less ink than the arrow."""
        def render(add):
            fig, ax = apl.subplots(1, 1, figsize=(FIG_W, FIG_H))
            plot = ax.imshow(np.zeros((IMG, IMG), dtype=np.float32))
            add(plot)
            return _ink(take_screenshot(fig))

        seg = render(lambda p: p.add_line_widget(x1=8, y1=8, x2=56, y2=56,
                                                 color="#ff0000",
                                                 show_handles=False))
        arw = render(lambda p: p.add_arrow_widget(x=8, y=8, u=48, v=48,
                                                  color="#ff0000",
                                                  show_handles=False))
        assert seg < arw, "the segment must not draw an arrowhead"


# ═══════════════════════════════════════════════════════════════════════════
# 3. Dragging (real browser input)
# ═══════════════════════════════════════════════════════════════════════════

class TestLineDrag:
    def test_endpoint_handle_moves_only_that_end(self, interact_page):
        fig, plot, page, w = _open(
            interact_page,
            lambda p: p.add_line_widget(x1=16, y1=16, x2=48, y2=48))
        g = _geom(page, plot._id, w.id)
        assert g is not None, "line geometry readback missing"
        o = _canvas_origin(page)
        before = _widget_state(page, plot._id)

        _drag(page, o["left"] + g["ax"], o["top"] + g["ay"], 40, 0)

        after = _widget_state(page, plot._id)
        assert after["x1"] > before["x1"] + 0.5, "p1 did not move"
        assert after["x2"] == pytest.approx(before["x2"], abs=1e-6), "p2 moved"
        assert after["y2"] == pytest.approx(before["y2"], abs=1e-6), "p2 moved"

    def test_shaft_drag_translates_both_ends(self, interact_page):
        fig, plot, page, w = _open(
            interact_page,
            lambda p: p.add_line_widget(x1=16, y1=16, x2=48, y2=48))
        g = _geom(page, plot._id, w.id)
        o = _canvas_origin(page)
        before = _widget_state(page, plot._id)

        mid_x = o["left"] + (g["ax"] + g["bx"]) / 2
        mid_y = o["top"] + (g["ay"] + g["by"]) / 2
        _drag(page, mid_x, mid_y, 30, 0)

        after = _widget_state(page, plot._id)
        d1 = after["x1"] - before["x1"]
        d2 = after["x2"] - before["x2"]
        assert d1 > 0.5, "the segment did not translate"
        assert d1 == pytest.approx(d2, abs=1e-6), "ends moved by different amounts"


class TestRuleDrag:
    def test_vline_grabbable_away_from_centre(self, interact_page):
        """The whole rule is the grab target, not just a hotspot."""
        fig, plot, page, w = _open(
            interact_page, lambda p: p.add_vline_widget(x=32))
        o = _canvas_origin(page)
        before = _widget_state(page, plot._id)
        # Aim near the top of the panel, far from the vertical middle.
        cx = o["left"] + _canvas_size(page)["w"] * 0.5
        _drag(page, cx, o["top"] + 20, 40, 0)
        after = _widget_state(page, plot._id)
        assert after["x"] > before["x"] + 0.5

    def test_vline_ignores_vertical_drag(self, interact_page):
        fig, plot, page, w = _open(
            interact_page, lambda p: p.add_vline_widget(x=32))
        o = _canvas_origin(page)
        before = _widget_state(page, plot._id)
        cx = o["left"] + _canvas_size(page)["w"] * 0.5
        _drag(page, cx, o["top"] + 20, 0, 40)
        after = _widget_state(page, plot._id)
        assert after["x"] == pytest.approx(before["x"], abs=1e-6)

    def test_hline_grabbable_away_from_centre(self, interact_page):
        fig, plot, page, w = _open(
            interact_page, lambda p: p.add_hline_widget(y=32))
        o = _canvas_origin(page)
        before = _widget_state(page, plot._id)
        cy = o["top"] + _canvas_size(page)["h"] * 0.5
        _drag(page, o["left"] + 20, cy, 0, 40)
        after = _widget_state(page, plot._id)
        assert after["y"] > before["y"] + 0.5


class TestCrosshairRuleGrab:
    def test_vertical_rule_grab_moves_x_only(self, interact_page):
        fig, plot, page, w = _open(
            interact_page, lambda p: p.add_crosshair_widget(cx=32, cy=32))
        o = _canvas_origin(page)
        before = _widget_state(page, plot._id)
        # On the vertical rule but well above the centre.
        cx = o["left"] + _canvas_size(page)["w"] * 0.5
        _drag(page, cx, o["top"] + 20, 40, 25)
        after = _widget_state(page, plot._id)
        assert after["cx"] > before["cx"] + 0.5, "grabbing the rule did nothing"
        assert after["cy"] == pytest.approx(before["cy"], abs=1e-6), \
            "a vertical-rule drag must not move cy"

    def test_centre_still_moves_both(self, interact_page):
        fig, plot, page, w = _open(
            interact_page, lambda p: p.add_crosshair_widget(cx=32, cy=32))
        o = _canvas_origin(page)
        size = _canvas_size(page)
        before = _widget_state(page, plot._id)
        _drag(page, o["left"] + size["w"] * 0.5, o["top"] + size["h"] * 0.5, 30, 30)
        after = _widget_state(page, plot._id)
        assert after["cx"] > before["cx"] + 0.5
        assert after["cy"] > before["cy"] + 0.5


def _canvas_size(page):
    return page.evaluate("""() => {
        const c = document.querySelector('canvas');
        const r = c.getBoundingClientRect();
        return {w: r.width, h: r.height};
    }""")

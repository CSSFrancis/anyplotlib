"""
tests/test_interactive/test_widget_max_extent.py
=================================================

``max_extent`` — a size cap enforced while the widget is being dragged.

Why it exists: when a widget's size drives real downstream work (an integrating
selector whose span is a number of frames to read), an unbounded drag is a
performance cliff. Clamping *after* the fact is worse than useless — it moves an
edge the user isn't holding, which reads as the selection jumping around under
the cursor. So the cap belongs in the drag itself: the dragged edge pins, the
opposite edge stays put, and the widget visibly stops growing.

Also covered: the band hit-test. Each edge of a range widget claimed a fixed
±12 px grab zone, so a band narrower than ~24 px on screen (routine when its
span is capped, or simply when zoomed out) had NO grabbable middle — aiming at
the body to translate it caught an edge and resized instead. Each edge now takes
at most a third of the band.

Coordinate system for the Playwright tests mirrors figure_esm.js:
  PAD_L=58  PAD_R=12  PAD_T=12  PAD_B=42  GRID_PAD=8
"""
from __future__ import annotations

import numpy as np
import pytest

import anyplotlib as apl
from anyplotlib.widgets import RangeWidget, RectangleWidget
from anyplotlib.tests.test_interactive._event_test_utils import (
    _collect_events,
    GRID_PAD, PAD_L, PAD_R, PAD_T, PAD_B,
)

FIG_W, FIG_H = 400, 300


# ═══════════════════════════════════════════════════════════════════════════
# 1. Python API
# ═══════════════════════════════════════════════════════════════════════════

class TestMaxExtentAttributes:
    def test_range_defaults_to_unbounded(self):
        w = RangeWidget(lambda: None, x0=0, x1=10)
        assert w.max_extent is None

    def test_range_stores_max_extent(self):
        w = RangeWidget(lambda: None, x0=0, x1=10, max_extent=16)
        assert w.max_extent == 16.0

    def test_range_max_extent_reaches_the_state_dict(self):
        """JS reads the widget dict, so the cap has to survive to_dict()."""
        w = RangeWidget(lambda: None, x0=0, x1=10, max_extent=16)
        assert w.to_dict()["max_extent"] == 16.0

    def test_rectangle_defaults_to_unbounded(self):
        w = RectangleWidget(lambda: None, x=0, y=0, w=10, h=10)
        assert w.max_w is None and w.max_h is None

    def test_rectangle_scalar_caps_both_axes(self):
        w = RectangleWidget(lambda: None, x=0, y=0, w=10, h=10, max_extent=16)
        assert w.max_w == 16.0 and w.max_h == 16.0

    def test_rectangle_pair_caps_axes_separately(self):
        w = RectangleWidget(lambda: None, x=0, y=0, w=10, h=10,
                            max_extent=(8, 32))
        assert w.max_w == 8.0 and w.max_h == 32.0

    def test_rectangle_max_extent_reaches_the_state_dict(self):
        w = RectangleWidget(lambda: None, x=0, y=0, w=10, h=10, max_extent=16)
        d = w.to_dict()
        assert d["max_w"] == 16.0 and d["max_h"] == 16.0


class TestMaxExtentFactories:
    def test_add_range_widget_passes_max_extent(self):
        fig, ax = apl.subplots(1, 1)
        v = ax.plot(np.zeros(64))
        w = v.add_range_widget(x0=10, x1=20, max_extent=16)
        assert isinstance(w, RangeWidget) and w.max_extent == 16.0

    def test_add_range_widget_without_max_extent(self):
        fig, ax = apl.subplots(1, 1)
        v = ax.plot(np.zeros(64))
        assert v.add_range_widget(x0=10, x1=20).max_extent is None

    def test_add_rectangle_widget_passes_max_extent(self):
        fig, ax = apl.subplots(1, 1)
        v = ax.imshow(np.zeros((32, 32), dtype=np.float32))
        w = v.add_rectangle_widget(x=0, y=0, w=4, h=4, max_extent=(8, 12))
        assert w.max_w == 8.0 and w.max_h == 12.0


# ═══════════════════════════════════════════════════════════════════════════
# 2. Drag behaviour in the browser — the logic lives in figure_esm.js, so a
#    Python-only test would prove nothing about what the user experiences.
# ═══════════════════════════════════════════════════════════════════════════

def _plot_rect():
    """Page-coordinate plot area (x, y, w, h)."""
    return (GRID_PAD + PAD_L, GRID_PAD + PAD_T,
            FIG_W - PAD_L - PAD_R, FIG_H - PAD_T - PAD_B)


def _collect_panel_state(page) -> None:
    """Record every ``model.set('panel_<id>_json', ...)`` write, seeded with the
    state the page already holds.

    The drag handlers push updated widget geometry back through the model, so the
    last write for a panel is its current state. Seeding from ``model.get`` first
    matters because a test may read the BEFORE state, and until something is
    dragged there has been no write to intercept. (There is no global panel
    registry to read — the panel object lives inside the JS closure.)"""
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
    """Pull one panel's current state out of the model (no drag needed)."""
    page.evaluate(
        """(pid) => {
            try {
                const v = window._aplModel.get('panel_' + pid + '_json');
                if (v) window._aplPanelState[pid] = JSON.parse(v);
            } catch(_) {}
        }""", str(plot_id))


def _widget_state(page, plot_id, idx=0):
    """The widget dict from the most recent panel-state write, or None."""
    return page.evaluate(
        """([pid, i]) => {
            const st = window._aplPanelState && window._aplPanelState[pid];
            const ws = st && st.overlay_widgets;
            return ws && ws[i] ? ws[i] : null;
        }""", [str(plot_id), idx])


def _x_to_page(xdata, n):
    """Data x -> page x for a line plot of n points spanning the full view."""
    px, _py, pw, _ph = _plot_rect()
    return px + (xdata / float(n - 1)) * pw


@pytest.mark.usefixtures("interact_page")
class TestRangeDragCap:
    def _setup(self, interact_page, max_extent):
        fig, ax = apl.subplots(1, 1, figsize=(FIG_W, FIG_H))
        n = 128
        plot = ax.plot(np.zeros(n))
        w = plot.add_range_widget(x0=40, x1=50, max_extent=max_extent)
        page = interact_page(fig)
        _collect_events(page)
        _collect_panel_state(page)
        return fig, plot, page, w, n

    def test_dragging_an_edge_stops_at_the_cap(self, interact_page):
        """Drag the right edge far past the cap: the span pins at max_extent and
        the LEFT edge — the one the user is not holding — must not move."""
        fig, plot, page, w, n = self._setup(interact_page, max_extent=16)
        _px, py, _pw, ph = _plot_rect()
        mid_y = py + ph // 2

        page.mouse.move(_x_to_page(50, n), mid_y)
        page.mouse.down()
        page.mouse.move(_x_to_page(120, n), mid_y, steps=10)   # way past the cap
        page.mouse.up()
        page.wait_for_timeout(80)

        st = _widget_state(page, plot._id)
        assert st is not None, "widget state should be readable"
        span = abs(st["x1"] - st["x0"])
        assert span <= 16.0 + 1e-6, f"span {span} exceeded the cap"
        assert st["x0"] == pytest.approx(40.0, abs=1.0), \
            "the anchor edge moved — that is the phantom-movement bug"

    def test_uncapped_range_still_grows_freely(self, interact_page):
        fig, plot, page, w, n = self._setup(interact_page, max_extent=None)
        _px, py, _pw, ph = _plot_rect()
        mid_y = py + ph // 2

        page.mouse.move(_x_to_page(50, n), mid_y)
        page.mouse.down()
        page.mouse.move(_x_to_page(100, n), mid_y, steps=10)
        page.mouse.up()
        page.wait_for_timeout(80)

        st = _widget_state(page, plot._id)
        assert abs(st["x1"] - st["x0"]) > 16.0, \
            "no cap was set, so the span should have grown past 16"

    def test_translating_a_capped_band_keeps_its_width(self, interact_page):
        """Dragging the BODY moves both edges together; a translation can't
        change the width, so the cap must not interfere with it."""
        fig, plot, page, w, n = self._setup(interact_page, max_extent=16)
        _px, py, _pw, ph = _plot_rect()
        mid_y = py + ph // 2

        _seed_panel_state(page, plot._id)
        before = _widget_state(page, plot._id)
        width0 = abs(before["x1"] - before["x0"])

        page.mouse.move(_x_to_page(45, n), mid_y)     # middle of the band
        page.mouse.down()
        page.mouse.move(_x_to_page(65, n), mid_y, steps=8)
        page.mouse.up()
        page.wait_for_timeout(80)

        after = _widget_state(page, plot._id)
        assert abs(after["x1"] - after["x0"]) == pytest.approx(width0, abs=0.5)
        assert after["x0"] > before["x0"] + 5, "the band should have moved"


@pytest.mark.usefixtures("interact_page")
class TestNarrowBandIsGrabbable:
    def test_middle_of_a_narrow_band_translates_rather_than_resizes(
            self, interact_page):
        """THE regression this guards: with fixed +-12 px edge zones, a band
        narrower than ~24 px had no grabbable body, so aiming at the middle
        resized an edge instead of moving the band. Each edge now takes at most
        a third of the band, leaving the middle third for 'move'."""
        fig, ax = apl.subplots(1, 1, figsize=(FIG_W, FIG_H))
        n = 128
        plot = ax.plot(np.zeros(n))
        # ~4 data units of 128 across ~330 px => roughly 10 px on screen.
        plot.add_range_widget(x0=60, x1=64)
        page = interact_page(fig)
        _collect_events(page)
        _collect_panel_state(page)

        _px, py, _pw, ph = _plot_rect()
        mid_y = py + ph // 2
        _seed_panel_state(page, plot._id)
        before = _widget_state(page, plot._id)
        width0 = abs(before["x1"] - before["x0"])

        page.mouse.move(_x_to_page(62, n), mid_y)      # dead centre of the band
        page.mouse.down()
        page.mouse.move(_x_to_page(82, n), mid_y, steps=8)
        page.mouse.up()
        page.wait_for_timeout(80)

        after = _widget_state(page, plot._id)
        assert abs(after["x1"] - after["x0"]) == pytest.approx(width0, abs=1.0), \
            "grabbing the middle of a narrow band resized it instead of moving it"
        assert after["x0"] > before["x0"] + 5, "the band should have moved"

    def test_edges_of_a_wide_band_still_resize(self, interact_page):
        """The narrow-band fix must not cost us edge resizing on normal bands."""
        fig, ax = apl.subplots(1, 1, figsize=(FIG_W, FIG_H))
        n = 128
        plot = ax.plot(np.zeros(n))
        plot.add_range_widget(x0=20, x1=80)            # wide: ~155 px on screen
        page = interact_page(fig)
        _collect_events(page)
        _collect_panel_state(page)

        _px, py, _pw, ph = _plot_rect()
        mid_y = py + ph // 2
        _seed_panel_state(page, plot._id)
        before = _widget_state(page, plot._id)

        page.mouse.move(_x_to_page(80, n), mid_y)      # right edge
        page.mouse.down()
        page.mouse.move(_x_to_page(100, n), mid_y, steps=8)
        page.mouse.up()
        page.wait_for_timeout(80)

        after = _widget_state(page, plot._id)
        assert after["x1"] > before["x1"] + 5, "the right edge should have moved"
        assert after["x0"] == pytest.approx(before["x0"], abs=1.0), \
            "the left edge should have stayed put"


@pytest.mark.usefixtures("interact_page")
class TestRectangleDragCap:
    def test_resizing_stops_at_the_cap_and_keeps_the_anchor(self, interact_page):
        fig, ax = apl.subplots(1, 1, figsize=(FIG_W, FIG_H))
        plot = ax.imshow(np.zeros((64, 64), dtype=np.float32))
        widget = plot.add_rectangle_widget(x=8, y=8, w=4, h=4, max_extent=16)
        page = interact_page(fig)
        _collect_events(page)
        _collect_panel_state(page)

        _seed_panel_state(page, plot._id)
        before = _widget_state(page, plot._id)
        assert before["max_w"] == 16.0

        # Aim at the REAL bottom-right handle using the canvas geometry the draw
        # path publishes (window._aplWidgetGeom). Deriving it from figure padding
        # doesn't work for a 2-D panel — the image->canvas mapping depends on the
        # zoom/extent state, and the grab radius is only HR=9 px, so a hard-coded
        # corner grabs the BODY ('move'), which legitimately ignores the cap and
        # would leave this test asserting nothing.
        geom = page.evaluate(
            """([pid, wid]) => {
                const g = window._aplWidgetGeom && window._aplWidgetGeom[pid];
                return g ? (g[wid] || Object.values(g)[0] || null) : null;
            }""", [str(plot._id), str(widget.id)])
        assert geom is not None, "widget geometry readback missing"

        canvas = page.evaluate(
            """() => {
                const c = document.querySelector('canvas');
                const r = c.getBoundingClientRect();
                return {left: r.left, top: r.top};
            }""")
        br_x = canvas["left"] + geom["rx"] + geom["rw"]
        br_y = canvas["top"] + geom["ry"] + geom["rh"]

        page.mouse.move(br_x, br_y)
        page.mouse.down()
        page.mouse.move(br_x + 300, br_y + 300, steps=12)   # far past the cap
        page.mouse.up()
        page.wait_for_timeout(80)

        after = _widget_state(page, plot._id)
        assert after["w"] > before["w"] + 0.5, \
            "no resize happened — the drag missed the handle"

        assert after["w"] <= 16.0 + 1e-6, f"width {after['w']} exceeded the cap"
        assert after["h"] <= 16.0 + 1e-6, f"height {after['h']} exceeded the cap"
        assert after["x"] == pytest.approx(before["x"], abs=1e-6), "anchor x moved"
        assert after["y"] == pytest.approx(before["y"], abs=1e-6), "anchor y moved"

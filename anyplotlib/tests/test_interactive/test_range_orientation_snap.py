"""
tests/test_interactive/test_range_orientation_snap.py
======================================================

Two range-widget capabilities:

``orientation="vertical"``
    A band spanning the plot width that selects a range of *values* rather
    than of x — an intensity window instead of a spectral one.  ``x0``/``x1``
    stay the field names: they are the extents along the selection axis, the
    same way matplotlib's ``SpanSelector.extents`` reads for either
    ``direction``.

``snap_values``
    Allowed positions.  The drag follows the cursor but lands only on the
    nearest allowed value (matplotlib's ``SpanSelector.snap_values``).  This
    has to happen inside the JS drag: snapping in Python afterwards moves an
    edge the user is holding, which reads as the selection fighting back.
"""
from __future__ import annotations

import numpy as np
import pytest

import anyplotlib as apl
from anyplotlib.widgets import RangeWidget, VLineWidget, HLineWidget
from anyplotlib.tests.test_interactive._event_test_utils import (
    _collect_events, GRID_PAD, PAD_L, PAD_R, PAD_T, PAD_B,
)

FIG_W, FIG_H = 400, 300
N = 128


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


def _plot_rect():
    """Page-coord plot rectangle (x, y, w, h)."""
    return (GRID_PAD + PAD_L, GRID_PAD + PAD_T,
            FIG_W - PAD_L - PAD_R, FIG_H - PAD_T - PAD_B)


def _drag(page, x0, y0, dx, dy):
    page.mouse.move(x0, y0)
    page.mouse.down()
    page.mouse.move(x0 + dx, y0 + dy, steps=10)
    page.mouse.up()
    page.wait_for_timeout(80)


def _open(interact_page, add):
    fig, ax = apl.subplots(1, 1, figsize=(FIG_W, FIG_H))
    plot = ax.plot(np.linspace(0.0, 100.0, N))
    widget = add(plot)
    page = interact_page(fig)
    _collect_events(page)
    _collect_panel_state(page)
    _seed_panel_state(page, plot._id)
    return fig, plot, page, widget


# ═══════════════════════════════════════════════════════════════════════════
# 1. Python API
# ═══════════════════════════════════════════════════════════════════════════

class TestOrientationApi:
    def test_defaults_to_horizontal(self):
        assert RangeWidget(lambda: None, x0=0, x1=1).orientation == "horizontal"

    def test_vertical_stored(self):
        w = RangeWidget(lambda: None, x0=0, x1=1, orientation="vertical")
        assert w.orientation == "vertical"

    def test_reaches_the_state_dict(self):
        w = RangeWidget(lambda: None, x0=0, x1=1, orientation="vertical")
        assert w.to_dict()["orientation"] == "vertical"

    def test_bad_orientation_raises(self):
        with pytest.raises(ValueError, match="orientation must be"):
            RangeWidget(lambda: None, x0=0, x1=1, orientation="diagonal")

    def test_vertical_fwhm_raises(self):
        """The FWHM indicator is defined against the x axis only."""
        with pytest.raises(ValueError, match="fwhm"):
            RangeWidget(lambda: None, x0=0, x1=1,
                        orientation="vertical", style="fwhm")

    def test_factory_passes_orientation(self):
        fig, ax = apl.subplots(1, 1)
        plot = ax.plot(np.zeros(N))
        w = plot.add_range_widget(1, 2, orientation="vertical")
        assert w.orientation == "vertical"


class TestSnapValuesApi:
    def test_defaults_to_none(self):
        assert RangeWidget(lambda: None, x0=0, x1=1).snap_values is None

    def test_empty_sequence_is_none(self):
        assert RangeWidget(lambda: None, x0=0, x1=1, snap_values=[]).snap_values is None

    def test_numpy_array_becomes_a_list(self):
        """A numpy array is not JSON-serialisable and would break the push."""
        w = RangeWidget(lambda: None, x0=0, x1=1,
                        snap_values=np.array([0.0, 1.0, 2.0]))
        assert isinstance(w.snap_values, list)
        assert w.snap_values == [0.0, 1.0, 2.0]

    @pytest.mark.parametrize("cls,kwargs", [
        (VLineWidget, {"x": 0}),
        (HLineWidget, {"y": 0}),
    ])
    def test_line_widgets_take_snap_values(self, cls, kwargs):
        w = cls(lambda: None, snap_values=[1, 2, 3], **kwargs)
        assert w.snap_values == [1.0, 2.0, 3.0]

    def test_state_dict_is_json_serialisable(self):
        import json
        fig, ax = apl.subplots(1, 1)
        plot = ax.plot(np.zeros(N))
        plot.add_range_widget(1, 2, snap_values=np.arange(5.0))
        json.dumps(plot.to_state_dict())   # must not raise


# ═══════════════════════════════════════════════════════════════════════════
# 2. Rendering
# ═══════════════════════════════════════════════════════════════════════════

class TestVerticalRendering:
    def _band_mask(self, take_screenshot, **kwargs):
        fig, ax = apl.subplots(1, 1, figsize=(FIG_W, FIG_H))
        plot = ax.plot(np.linspace(0.0, 100.0, N))
        plot.add_range_widget(color="#ff0000", **kwargs)
        img = take_screenshot(fig)[..., :3].astype(int)
        # The band fill is a translucent red wash over the background.
        return (img[..., 0] > img[..., 2] + 20)

    def test_vertical_band_spans_the_width(self, take_screenshot):
        mask = self._band_mask(take_screenshot, x0=30.0, x1=70.0,
                               orientation="vertical")
        plot_w = FIG_W - PAD_L - PAD_R
        cols = mask.any(axis=0).sum()
        assert cols > plot_w * 0.8, (
            f"a vertical band must span the plot width, covered {cols} of "
            f"~{plot_w} columns"
        )

    def test_horizontal_band_spans_the_height(self, take_screenshot):
        mask = self._band_mask(take_screenshot, x0=30.0, x1=70.0)
        plot_h = FIG_H - PAD_T - PAD_B
        rows = mask.any(axis=1).sum()
        assert rows > plot_h * 0.8

    def test_orientation_changes_the_shape(self, take_screenshot):
        """Sanity: the two orientations must not render the same thing."""
        horiz = self._band_mask(take_screenshot, x0=30.0, x1=70.0)
        vert = self._band_mask(take_screenshot, x0=30.0, x1=70.0,
                               orientation="vertical")
        assert horiz.any(axis=1).sum() != vert.any(axis=1).sum()


# ═══════════════════════════════════════════════════════════════════════════
# 3. Dragging (real browser input)
# ═══════════════════════════════════════════════════════════════════════════

class TestVerticalDrag:
    def test_dragging_the_band_moves_the_value_range(self, interact_page):
        fig, plot, page, w = _open(
            interact_page,
            lambda p: p.add_range_widget(x0=30.0, x1=70.0,
                                         orientation="vertical"))
        px, py, pw, ph = _plot_rect()
        before = _widget_state(page, plot._id)
        # Middle of the band: the data spans 0..100, the band 30..70, so the
        # band's centre value 50 sits at the vertical middle of the plot.
        _drag(page, px + pw / 2, py + ph / 2, 0, -30)
        after = _widget_state(page, plot._id)
        assert after["x0"] > before["x0"] + 0.5, "dragging up must raise x0"
        assert after["x1"] > before["x1"] + 0.5, "dragging up must raise x1"

    def test_band_width_is_preserved_by_a_translation(self, interact_page):
        fig, plot, page, w = _open(
            interact_page,
            lambda p: p.add_range_widget(x0=30.0, x1=70.0,
                                         orientation="vertical"))
        px, py, pw, ph = _plot_rect()
        before = _widget_state(page, plot._id)
        _drag(page, px + pw / 2, py + ph / 2, 0, -30)
        after = _widget_state(page, plot._id)
        assert (after["x1"] - after["x0"]) == pytest.approx(
            before["x1"] - before["x0"], abs=1e-6)

    def test_horizontal_drag_does_not_move_a_vertical_band(self, interact_page):
        fig, plot, page, w = _open(
            interact_page,
            lambda p: p.add_range_widget(x0=30.0, x1=70.0,
                                         orientation="vertical"))
        px, py, pw, ph = _plot_rect()
        before = _widget_state(page, plot._id)
        _drag(page, px + pw / 2, py + ph / 2, 60, 0)
        after = _widget_state(page, plot._id)
        assert after["x0"] == pytest.approx(before["x0"], abs=1e-6)


class TestSnapDrag:
    def test_edge_lands_on_an_allowed_value(self, interact_page):
        snaps = [0.0, 25.0, 50.0, 75.0, 100.0]
        fig, plot, page, w = _open(
            interact_page,
            lambda p: p.add_range_widget(x0=0.0, x1=25.0, snap_values=snaps))
        px, py, pw, ph = _plot_rect()
        # The x axis is the sample index 0..N-1; grab the right edge, which sits
        # at value 25 -> index 32 of 128.
        edge_x = px + pw * (25.0 / (N - 1))
        _drag(page, edge_x, py + ph / 2, pw * 0.3, 0)
        after = _widget_state(page, plot._id)
        assert after["x1"] in snaps, (
            f"x1={after['x1']} is not one of the allowed values {snaps}"
        )

    def test_snapping_actually_moved_the_edge(self, interact_page):
        """Guard against the test passing because nothing happened."""
        snaps = [0.0, 25.0, 50.0, 75.0, 100.0]
        fig, plot, page, w = _open(
            interact_page,
            lambda p: p.add_range_widget(x0=0.0, x1=25.0, snap_values=snaps))
        px, py, pw, ph = _plot_rect()
        before = _widget_state(page, plot._id)
        edge_x = px + pw * (25.0 / (N - 1))
        _drag(page, edge_x, py + ph / 2, pw * 0.3, 0)
        after = _widget_state(page, plot._id)
        assert after["x1"] > before["x1"], "the drag missed the edge"

    def test_without_snap_values_the_edge_lands_anywhere(self, interact_page):
        """Contrast case: continuous dragging is still the default."""
        fig, plot, page, w = _open(
            interact_page,
            lambda p: p.add_range_widget(x0=0.0, x1=25.0))
        px, py, pw, ph = _plot_rect()
        edge_x = px + pw * (25.0 / (N - 1))
        _drag(page, edge_x, py + ph / 2, pw * 0.3, 0)
        after = _widget_state(page, plot._id)
        assert after["x1"] not in (0.0, 25.0, 50.0, 75.0, 100.0)

    def test_vline_snaps(self, interact_page):
        snaps = [0.0, 32.0, 64.0, 96.0]
        fig, plot, page, w = _open(
            interact_page,
            lambda p: p.add_vline_widget(x=32.0, snap_values=snaps))
        px, py, pw, ph = _plot_rect()
        start = px + pw * (32.0 / (N - 1))
        _drag(page, start, py + ph / 2, pw * 0.2, 0)
        after = _widget_state(page, plot._id)
        assert after["x"] in snaps

"""
tests/test_interactive/test_pointer_down_1d.py
===============================================

Playwright tests for positional ``pointer_down`` on 1-D panels.

2-D panels have always emitted ``pointer_down`` with the clicked position in
data coordinates.  1-D panels used to emit it *only* when the click landed
within the hit-test radius of a line, which made ``pointer_down`` mean two
different things depending on panel kind and left click-position features
(e.g. "jump the cursor where I clicked") with nothing to listen to.

A click on a 1-D panel now always emits exactly one ``pointer_down`` carrying
``xdata``/``ydata``.  ``line_id`` still rides along when a line was hit, so the
older line-click contract is unchanged.
"""
from __future__ import annotations

import numpy as np

import anyplotlib as apl
from anyplotlib.tests.test_interactive._event_test_utils import (
    _collect_events,
    _get_events,
    _plot_center_page,
    GRID_PAD,
    PAD_L, PAD_R, PAD_T, PAD_B,
)

FIG_W, FIG_H = 400, 300


def _make_flat_1d(interact_page, value=0.0):
    """A flat line at *value* — its pixel row is easy to avoid or hit."""
    fig, ax = apl.subplots(1, 1, figsize=(FIG_W, FIG_H))
    plot = ax.plot(np.full(64, value), axes=[np.linspace(0.0, 10.0, 64)])
    page = interact_page(fig)
    _collect_events(page)
    return fig, plot, page


def _click(page, x, y):
    page.mouse.click(x, y)
    page.wait_for_timeout(100)


class TestPositionalPointerDown:
    def test_click_away_from_any_line_emits_pointer_down(self, interact_page):
        """The regression this fixes: an empty-area click used to emit nothing."""
        _, _, page = _make_flat_1d(interact_page)
        cx, _ = _plot_center_page(FIG_W, FIG_H)
        # A flat line at y=0 sits on the vertical mid-row; click well above it.
        near_top = GRID_PAD + PAD_T + 20
        _click(page, cx, near_top)
        events = _get_events(page, "pointer_down")
        assert len(events) == 1, (
            f"a click in empty plot area must emit exactly one pointer_down, "
            f"got {len(events)}"
        )

    def test_positional_event_carries_data_coords(self, interact_page):
        _, _, page = _make_flat_1d(interact_page)
        cx, _ = _plot_center_page(FIG_W, FIG_H)
        _click(page, cx, GRID_PAD + PAD_T + 20)
        ev = _get_events(page, "pointer_down")[0]
        assert ev.get("xdata") is not None
        assert ev.get("ydata") is not None
        # Clicked the horizontal centre of a 0..10 x-axis.
        assert 4.0 < ev["xdata"] < 6.0, ev["xdata"]

    def test_empty_area_click_has_no_line_id(self, interact_page):
        _, _, page = _make_flat_1d(interact_page)
        cx, _ = _plot_center_page(FIG_W, FIG_H)
        _click(page, cx, GRID_PAD + PAD_T + 20)
        ev = _get_events(page, "pointer_down")[0]
        assert ev.get("line_id") is None

    def test_click_outside_plot_area_emits_nothing(self, interact_page):
        """The axis gutters are not the plot; clicking there is not a position."""
        _, _, page = _make_flat_1d(interact_page)
        cx, _ = _plot_center_page(FIG_W, FIG_H)
        in_bottom_gutter = GRID_PAD + FIG_H - PAD_B + 15
        _click(page, cx, in_bottom_gutter)
        assert _get_events(page, "pointer_down") == []

    def test_xdata_tracks_click_x(self, interact_page):
        """Two clicks at different x must report different, ordered xdata."""
        _, _, page = _make_flat_1d(interact_page)
        y = GRID_PAD + PAD_T + 20
        left_x = GRID_PAD + PAD_L + 20
        right_x = GRID_PAD + FIG_W - PAD_R - 20
        _click(page, left_x, y)
        _click(page, right_x, y)
        events = _get_events(page, "pointer_down")
        assert len(events) == 2
        assert events[0]["xdata"] < events[1]["xdata"]


class TestLineClickContractPreserved:
    def test_click_on_overlay_still_reports_line_id(self, interact_page):
        """The pre-existing line-click payload must keep working.

        Only ``add_line`` overlays carry an id — a hit on the primary line
        reports ``line_id`` as ``None`` (``_lineHitTest1d`` passes ``null``
        for it), so the overlay is what pins this contract.
        """
        fig, ax = apl.subplots(1, 1, figsize=(FIG_W, FIG_H))
        plot = ax.plot(np.full(64, -1.0), axes=[np.linspace(0.0, 10.0, 64)])
        line = plot.add_line(np.full(64, 1.0))
        page = interact_page(fig)
        _collect_events(page)

        # The overlay sits at the top of the -1..1 range and the primary at the
        # bottom, but the exact pixel row depends on renderer padding — so scan
        # down the upper half of the plot rather than hard-coding it.
        cx, _ = _plot_center_page(FIG_W, FIG_H)
        top = GRID_PAD + PAD_T
        plot_h = FIG_H - PAD_T - PAD_B
        for dy in range(0, plot_h // 2, 4):
            _click(page, cx, top + dy)

        ids = {e.get("line_id") for e in _get_events(page, "pointer_down")}
        assert line.id in ids, (
            f"clicking the overlay must report its id; saw line_ids {ids}"
        )

    def test_line_click_also_carries_data_coords(self, interact_page):
        _, _, page = _make_flat_1d(interact_page)
        cx, cy = _plot_center_page(FIG_W, FIG_H)
        _click(page, cx, cy)
        ev = _get_events(page, "pointer_down")[0]
        assert ev.get("xdata") is not None
        assert ev.get("ydata") is not None

    def test_drag_does_not_emit_pointer_down(self, interact_page):
        """Panning is not a click."""
        _, _, page = _make_flat_1d(interact_page)
        cx, cy = _plot_center_page(FIG_W, FIG_H)
        page.mouse.move(cx, cy)
        page.mouse.down()
        page.mouse.move(cx + 60, cy, steps=10)
        page.mouse.up()
        page.wait_for_timeout(100)
        assert _get_events(page, "pointer_down") == []

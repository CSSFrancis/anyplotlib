"""
Snapshots must capture widgets where they *are*.

``Widget.set()`` reaches JS through ``Figure._push_widget``, which writes only
the ``event_json`` trait — re-serialising a whole panel (image bytes included)
on every drag frame is the cost that path exists to avoid.  The side effect was
that ``panel_<id>_json`` kept the geometry from widget-creation time, so
``save_html`` / ``to_html`` / ``figure_state`` snapshotted a widget at its
original position no matter how far it had since moved.

``Figure._sync_for_export()`` reconciles the panel traits, and every export
path reaches it through ``_repr_utils._widget_state``.
"""
from __future__ import annotations

import json

import numpy as np

import anyplotlib as apl
from anyplotlib.embed import figure_state, to_html


def _fig_with_widget():
    fig, ax = apl.subplots(1, 1, figsize=(300, 300))
    plot = ax.imshow(np.zeros((32, 32), dtype=np.float32))
    widget = plot.add_widget("rectangle", x=2, y=2, w=4, h=4)
    return fig, plot, widget


def _panel_widgets(state, plot):
    return json.loads(state[f"panel_{plot._id}_json"])["overlay_widgets"]


class TestFigureState:
    def test_moved_widget_is_current(self):
        fig, plot, widget = _fig_with_widget()
        widget.set(x=20, y=25)
        got = _panel_widgets(figure_state(fig), plot)[0]
        assert got["x"] == 20 and got["y"] == 25

    def test_resized_widget_is_current(self):
        fig, plot, widget = _fig_with_widget()
        widget.set(w=17, h=19)
        got = _panel_widgets(figure_state(fig), plot)[0]
        assert got["w"] == 17 and got["h"] == 19

    def test_unmoved_widget_still_captured(self):
        fig, plot, widget = _fig_with_widget()
        got = _panel_widgets(figure_state(fig), plot)[0]
        assert got["x"] == 2 and got["y"] == 2

    def test_removed_widget_is_gone(self):
        fig, plot, widget = _fig_with_widget()
        widget.remove()
        assert _panel_widgets(figure_state(fig), plot) == []

    def test_notify_false_move_is_also_captured(self):
        """A silent Python move must not be silent to the snapshot."""
        fig, plot, widget = _fig_with_widget()
        widget.set(_notify=False, x=13)
        assert _panel_widgets(figure_state(fig), plot)[0]["x"] == 13

    def test_every_panel_is_refreshed(self):
        fig, axs = apl.subplots(1, 2, figsize=(400, 200))
        p0 = axs[0].imshow(np.zeros((16, 16), dtype=np.float32))
        p1 = axs[1].imshow(np.zeros((16, 16), dtype=np.float32))
        w0 = p0.add_widget("circle", cx=1, cy=1, r=1)
        w1 = p1.add_widget("circle", cx=1, cy=1, r=1)
        w0.set(cx=9)
        w1.set(cx=11)
        state = figure_state(fig)
        assert _panel_widgets(state, p0)[0]["cx"] == 9
        assert _panel_widgets(state, p1)[0]["cx"] == 11


class TestHtmlExport:
    def test_moved_widget_reaches_the_html(self):
        fig, plot, widget = _fig_with_widget()
        widget.set(x=23.5)
        html = to_html(fig)
        assert "23.5" in html, "the moved position never reached the HTML"

    def test_stale_position_is_not_in_the_html(self):
        """The regression: the creation-time geometry used to be what shipped."""
        fig, ax = apl.subplots(1, 1, figsize=(300, 300))
        plot = ax.imshow(np.zeros((32, 32), dtype=np.float32))
        widget = plot.add_widget("rectangle", x=3.25, y=3.25, w=4, h=4)
        widget.set(x=21.75, y=21.75)
        html = to_html(fig)
        assert "3.25" not in html, "the stale creation position is still in the export"
        assert "21.75" in html

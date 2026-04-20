"""
tests/test_plotbar_extras.py
=============================

Tests for PlotBar features exercised in Examples/plot_bar.py but not yet
covered by the existing test_bar.py.

Covers:
  * New matplotlib-aligned API: bar(x, height, width, ...)
  * String x → category labels auto-detected
  * Grouped bars — 2-D height, group_labels, group_colors
  * Horizontal orientation (orient='h')
  * log_scale at construction time
  * set_data() with new x / x_labels
  * set_color(), set_colors(), set_show_values(), set_log_scale()
  * add_vline_widget() / add_hline_widget() / add_range_widget() / add_point_widget()
  * Widget management: get_widget, remove_widget, list_widgets, clear_widgets
  * on_click callback registration / disconnect
  * on_changed callback
  * repr
"""
from __future__ import annotations

import numpy as np
import pytest

import anyplotlib as apl
from anyplotlib.figure_plots import PlotBar


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _bar(x, height=None, **kwargs) -> PlotBar:
    fig, ax = apl.subplots(1, 1)
    if height is not None:
        return ax.bar(x, height, **kwargs)
    return ax.bar(x, **kwargs)


# ---------------------------------------------------------------------------
# New API — bar(x, height, ...)
# ---------------------------------------------------------------------------

class TestPlotBarNewAPI:

    def test_string_x_becomes_labels(self):
        months = ["Jan", "Feb", "Mar"]
        bar = _bar(months, [10, 20, 30])
        assert bar._state["x_labels"] == months

    def test_numeric_x_becomes_centers(self):
        x = [0.0, 1.0, 2.0]
        bar = _bar(x, [10, 20, 30])
        assert bar._state["x_centers"] == pytest.approx(x)

    def test_width_kwarg(self):
        bar = _bar([1, 2, 3], [10, 20, 30], width=0.4)
        assert bar._state["bar_width"] == pytest.approx(0.4)

    def test_bottom_kwarg(self):
        bar = _bar([1, 2, 3], [10, 20, 30], bottom=5.0)
        assert bar._state["baseline"] == pytest.approx(5.0)

    def test_show_values_kwarg(self):
        bar = _bar([1, 2, 3], [10, 20, 30], show_values=True)
        assert bar._state["show_values"] is True

    def test_orient_h(self):
        bar = _bar(["A", "B"], [10, 20], orient="h")
        assert bar._state["orient"] == "h"

    def test_orient_v_default(self):
        bar = _bar([1, 2], [5, 6])
        assert bar._state["orient"] == "v"

    def test_orient_invalid(self):
        with pytest.raises(ValueError):
            _bar([1, 2], [5, 6], orient="diagonal")

    def test_per_bar_colors(self):
        palette = ["#ff0000", "#00ff00", "#0000ff"]
        bar = _bar([1, 2, 3], [10, 20, 30], colors=palette)
        assert bar._state["bar_colors"] == palette


# ---------------------------------------------------------------------------
# Grouped bars
# ---------------------------------------------------------------------------

class TestPlotBarGrouped:

    def test_grouped_2d_height(self):
        data = np.array([[1, 2, 3], [4, 5, 6]], dtype=float)
        bar = _bar(["A", "B"], data, group_labels=["G1", "G2", "G3"])
        assert bar._state["groups"] == 3
        assert bar._state["group_labels"] == ["G1", "G2", "G3"]

    def test_grouped_default_colors_assigned(self):
        data = np.ones((3, 2))
        bar = _bar([1, 2, 3], data)
        assert len(bar._state["group_colors"]) == 2

    def test_grouped_custom_colors(self):
        data = np.ones((3, 2))
        bar = _bar([1, 2, 3], data, group_colors=["#aaa", "#bbb"])
        assert bar._state["group_colors"] == ["#aaa", "#bbb"]

    def test_grouped_3d_raises(self):
        with pytest.raises(ValueError):
            _bar([1], np.ones((1, 2, 3)))

    def test_set_data_group_mismatch(self):
        data = np.ones((3, 2))
        bar = _bar([1, 2, 3], data)
        with pytest.raises(ValueError, match="Group count"):
            bar.set_data(np.ones((3, 3)))   # 3 groups vs original 2


# ---------------------------------------------------------------------------
# Log scale
# ---------------------------------------------------------------------------

class TestPlotBarLogScale:

    def test_log_scale_construction(self):
        bar = _bar(["A", "B", "C", "D", "E"],
                   [1, 10, 100, 1000, 10000], log_scale=True)
        assert bar._state["log_scale"] is True

    def test_set_log_scale_on(self):
        bar = _bar([1, 2, 3], [1, 10, 100])
        bar.set_log_scale(True)
        assert bar._state["log_scale"] is True

    def test_set_log_scale_off(self):
        bar = _bar([1, 2, 3], [1, 10, 100], log_scale=True)
        bar.set_log_scale(False)
        assert bar._state["log_scale"] is False


# ---------------------------------------------------------------------------
# set_data
# ---------------------------------------------------------------------------

class TestPlotBarSetData:

    def test_set_data_updates_values(self):
        bar = _bar([1, 2, 3], [10, 20, 30])
        bar.set_data([5, 15, 25])
        assert bar._state["values"] == [[5], [15], [25]]

    def test_set_data_recalculates_range(self):
        bar = _bar([1, 2, 3], [10, 20, 30])
        old_max = bar._state["data_max"]
        bar.set_data([100, 200, 300])
        assert bar._state["data_max"] > old_max

    def test_set_data_with_new_x_labels(self):
        bar = _bar(["A", "B"], [1, 2])
        bar.set_data([3, 4], x_labels=["X", "Y"])
        assert bar._state["x_labels"] == ["X", "Y"]

    def test_set_data_with_x_centers(self):
        bar = _bar([0, 1], [10, 20])
        bar.set_data([30, 40], x=[5, 10])
        assert bar._state["x_centers"] == [5, 10]

    def test_set_data_bad_ndim(self):
        bar = _bar([1, 2], [10, 20])
        with pytest.raises(ValueError):
            bar.set_data(np.ones((2, 2, 2)))


# ---------------------------------------------------------------------------
# Display setters
# ---------------------------------------------------------------------------

class TestPlotBarDisplaySetters:

    def test_set_color(self):
        bar = _bar([1, 2], [10, 20])
        bar.set_color("#ff7043")
        assert bar._state["bar_color"] == "#ff7043"

    def test_set_colors(self):
        bar = _bar([1, 2, 3], [10, 20, 30])
        bar.set_colors(["#r", "#g", "#b"])
        assert bar._state["bar_colors"] == ["#r", "#g", "#b"]

    def test_set_show_values_true(self):
        bar = _bar([1, 2], [10, 20])
        bar.set_show_values(True)
        assert bar._state["show_values"] is True

    def test_set_show_values_false(self):
        bar = _bar([1, 2], [10, 20], show_values=True)
        bar.set_show_values(False)
        assert bar._state["show_values"] is False


# ---------------------------------------------------------------------------
# Widgets on PlotBar
# ---------------------------------------------------------------------------

class TestPlotBarWidgets:

    def test_add_vline_widget(self):
        bar = _bar(["A", "B", "C"], [10, 20, 30])
        w = bar.add_vline_widget(1.5, color="#ff6e40")
        assert len(bar._widgets) == 1

    def test_add_hline_widget(self):
        bar = _bar([1, 2, 3], [10, 20, 30])
        w = bar.add_hline_widget(15.0)
        assert len(bar._widgets) == 1

    def test_add_range_widget(self):
        bar = _bar([1, 2, 3], [10, 20, 30])
        w = bar.add_range_widget(0.5, 2.5)
        assert len(bar._widgets) == 1

    def test_add_point_widget(self):
        bar = _bar([1, 2, 3], [10, 20, 30])
        w = bar.add_point_widget(1.0, 15.0)
        assert len(bar._widgets) == 1

    def test_get_widget_by_id(self):
        bar = _bar([1, 2], [10, 20])
        w = bar.add_vline_widget(1.0)
        assert bar.get_widget(w.id) is w

    def test_get_widget_missing(self):
        bar = _bar([1, 2], [10, 20])
        with pytest.raises(KeyError):
            bar.get_widget("nope")

    def test_remove_widget(self):
        bar = _bar([1, 2], [10, 20])
        w = bar.add_vline_widget(1.0)
        bar.remove_widget(w)
        assert len(bar._widgets) == 0

    def test_remove_widget_missing(self):
        bar = _bar([1, 2], [10, 20])
        with pytest.raises(KeyError):
            bar.remove_widget("bad")

    def test_list_widgets(self):
        bar = _bar([1, 2], [10, 20])
        bar.add_vline_widget(1.0)
        bar.add_hline_widget(5.0)
        assert len(bar.list_widgets()) == 2

    def test_clear_widgets(self):
        bar = _bar([1, 2], [10, 20])
        bar.add_vline_widget(1.0)
        bar.clear_widgets()
        assert bar.list_widgets() == []


# ---------------------------------------------------------------------------
# Callbacks
# ---------------------------------------------------------------------------

class TestPlotBarCallbacks:

    def test_on_click_registration(self):
        from anyplotlib.callbacks import Event
        bar = _bar([1, 2, 3], [10, 20, 30])
        fired = []

        @bar.on_click
        def cb(event):
            fired.append(event)

        bar.callbacks.fire(Event("on_click", bar, {"bar_index": 0}))
        assert len(fired) == 1
        assert fired[0].bar_index == 0

    def test_on_changed_registration(self):
        from anyplotlib.callbacks import Event
        bar = _bar([1, 2, 3], [10, 20, 30])
        fired = []

        @bar.on_changed
        def cb(event):
            fired.append(event)

        bar.callbacks.fire(Event("on_changed", bar, {"view_x0": 0.1}))
        assert len(fired) == 1

    def test_disconnect(self):
        from anyplotlib.callbacks import Event
        bar = _bar([1, 2], [5, 6])
        fired = []

        @bar.on_click
        def cb(event):
            fired.append(1)

        bar.disconnect(cb._cid)
        bar.callbacks.fire(Event("on_click", bar, {}))
        assert fired == []

    def test_repr(self):
        bar = _bar([1, 2, 3], [10, 20, 30])
        r = repr(bar)
        assert "PlotBar" in r






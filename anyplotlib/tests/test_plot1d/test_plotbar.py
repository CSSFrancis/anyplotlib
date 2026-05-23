"""
tests/test_plot1d/test_plotbar.py
==================================

Unit tests for PlotBar (bar chart) — covering:

  * Construction: defaults and explicit matplotlib-aligned API
      (bar(x, height, width, bottom, ...), string x → category labels)
  * State dict contents and data integrity
  * Orientation: vertical / horizontal
  * Colour options: single colour, per-bar colours, group colours
  * Bar-width, baseline/bottom, show_values flags
  * x (positions or category labels) and x_labels
  * Range / padding calculations
  * Grouped bars: 2-D height array, group_labels, group_colors
  * Log scale: log_scale flag, clamping, set_log_scale()
  * set_data(): value replacement and axis recalculation
  * Display-setting mutations: set_color, set_colors, set_show_values, set_log_scale
  * _push() contract: state propagated to Figure; layout_json kind == "bar"
  * Callback API: on_click (incl. group_index/group_value), on_changed, disconnect
  * Widgets: add_vline_widget, add_hline_widget, add_range_widget, add_point_widget,
             get_widget, remove_widget, list_widgets, clear_widgets
  * Edge cases: single bar, negative values, all-equal values, large N, float values
  * Validation errors for bad inputs
  * repr()
"""
from __future__ import annotations

import json

import numpy as np
import pytest

import anyplotlib as apl
from anyplotlib.callbacks import CallbackRegistry, Event
from anyplotlib.plot1d import PlotBar


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_bar(values=None, **kwargs) -> PlotBar:
    """Create a PlotBar attached to a one-panel Figure (values-only call)."""
    if values is None:
        values = [1, 2, 3, 4, 5]
    fig, ax = apl.subplots(1, 1)
    return ax.bar(values, **kwargs)


def _bar(x, height=None, **kwargs) -> PlotBar:
    """Create a PlotBar via the full bar(x, height, ...) API."""
    fig, ax = apl.subplots(1, 1)
    if height is not None:
        return ax.bar(x, height, **kwargs)
    return ax.bar(x, **kwargs)


def _state(plot: PlotBar) -> dict:
    return plot.to_state_dict()


# ===========================================================================
# 1. Construction — defaults
# ===========================================================================

class TestPlotBarDefaults:

    def test_kind_is_bar(self):
        assert _state(_make_bar())["kind"] == "bar"

    def test_values_stored_as_2d(self):
        values = [10, 20, 30]
        p = _make_bar(values)
        assert _state(p)["values"] == pytest.approx(np.array([[10.0], [20.0], [30.0]]))

    def test_numpy_array_accepted(self):
        arr = np.array([1.0, 2.0, 3.0])
        p = _make_bar(arr)
        assert _state(p)["values"] == pytest.approx(np.array([[1.0], [2.0], [3.0]]))

    def test_default_x_centers(self):
        assert _state(_make_bar([5, 6, 7]))["x_centers"] == pytest.approx([0.0, 1.0, 2.0])

    def test_default_orient_is_vertical(self):
        assert _state(_make_bar())["orient"] == "v"

    def test_default_baseline_is_zero(self):
        assert _state(_make_bar())["baseline"] == pytest.approx(0.0)

    def test_default_bar_width(self):
        assert _state(_make_bar())["bar_width"] == pytest.approx(0.8)

    def test_default_show_values_false(self):
        assert _state(_make_bar())["show_values"] is False

    def test_default_color(self):
        assert _state(_make_bar())["bar_color"] == "#4fc3f7"

    def test_default_bar_colors_empty(self):
        assert _state(_make_bar())["bar_colors"] == []

    def test_default_x_labels_empty(self):
        assert _state(_make_bar())["x_labels"] == []

    def test_default_units_empty(self):
        st = _state(_make_bar())
        assert st["units"] == ""
        assert st["y_units"] == ""

    def test_default_groups_is_one(self):
        assert _state(_make_bar())["groups"] == 1

    def test_default_log_scale_false(self):
        assert _state(_make_bar())["log_scale"] is False


# ===========================================================================
# 2. Construction — explicit / matplotlib-aligned arguments
# ===========================================================================

class TestPlotBarExplicitArgs:

    def test_x_as_numeric_positions(self):
        p = _bar([0, 1, 2], [10, 20, 30])
        st = _state(p)
        assert st["x_centers"] == pytest.approx([0.0, 1.0, 2.0])
        assert st["values"] == pytest.approx(np.array([[10.0], [20.0], [30.0]]))

    def test_x_as_string_labels(self):
        months = ["Jan", "Feb", "Mar"]
        p = _bar(months, [10, 20, 30])
        st = _state(p)
        assert st["x_labels"] == months
        assert st["x_centers"] == pytest.approx([0.0, 1.0, 2.0])

    def test_width_parameter(self):
        p = _bar([0, 1, 2], [1, 2, 3], width=0.5)
        assert _state(p)["bar_width"] == pytest.approx(0.5)

    def test_bottom_parameter(self):
        p = _bar([0, 1, 2], [1, 2, 3], bottom=5.0)
        assert _state(p)["baseline"] == pytest.approx(5.0)

    def test_orient_h(self):
        assert _bar(["A", "B"], [10, 20], orient="h")._state["orient"] == "h"

    def test_orient_v_default(self):
        assert _bar([1, 2], [5, 6])._state["orient"] == "v"

    def test_show_values_kwarg(self):
        assert _bar([1, 2, 3], [10, 20, 30], show_values=True)._state["show_values"] is True

    def test_custom_color(self):
        assert _make_bar(color="#ff0000")._state["bar_color"] == "#ff0000"

    def test_custom_colors_list(self):
        palette = ["#ff0000", "#00ff00", "#0000ff"]
        p = _bar([1, 2, 3], [10, 20, 30], colors=palette)
        assert _state(p)["bar_colors"] == palette

    def test_legacy_x_centers(self):
        assert _state(_make_bar([1, 2, 3], x_centers=[10, 20, 30]))["x_centers"] == pytest.approx([10.0, 20.0, 30.0])

    def test_legacy_x_labels(self):
        assert _state(_make_bar([1, 2, 3], x_labels=["A", "B", "C"]))["x_labels"] == ["A", "B", "C"]

    def test_legacy_bar_width(self):
        assert _state(_make_bar(bar_width=0.5))["bar_width"] == pytest.approx(0.5)

    def test_legacy_baseline(self):
        assert _state(_make_bar(baseline=5.0))["baseline"] == pytest.approx(5.0)

    def test_units_and_y_units(self):
        st = _state(_make_bar(units="category", y_units="count"))
        assert st["units"] == "category"
        assert st["y_units"] == "count"

    def test_axes_bar_returns_plotbar_instance(self):
        fig, ax = apl.subplots(1, 1)
        assert isinstance(ax.bar([1, 2, 3]), PlotBar)

    def test_orient_invalid_raises(self):
        with pytest.raises(ValueError):
            _bar([1, 2], [5, 6], orient="diagonal")


# ===========================================================================
# 3. Range / padding calculations
# ===========================================================================

class TestPlotBarRange:

    def test_data_max_exceeds_max_value(self):
        assert _state(_make_bar([1, 2, 3, 4, 5]))["data_max"] > 5.0

    def test_data_min_at_baseline_for_positive_values(self):
        assert _state(_make_bar([1, 2, 3, 4, 5], baseline=0.0))["data_min"] <= 0.0

    def test_negative_values_extend_data_min(self):
        assert _state(_make_bar([-3, -1, 0, 2]))["data_min"] < -3.0

    def test_data_max_gt_data_min(self):
        st = _state(_make_bar([1, 2, 3]))
        assert st["data_max"] > st["data_min"]

    def test_all_equal_values_padded(self):
        st = _state(_make_bar([5, 5, 5]))
        assert st["data_max"] > st["data_min"]

    def test_baseline_above_all_values(self):
        assert _state(_make_bar([1, 2, 3], baseline=10.0))["data_max"] >= 10.0

    def test_baseline_below_all_values(self):
        assert _state(_make_bar([5, 6, 7], baseline=-5.0))["data_min"] <= -5.0


# ===========================================================================
# 4. Grouped bars
# ===========================================================================

class TestPlotBarGrouped:

    def test_2d_height_creates_groups(self):
        fig, ax = apl.subplots(1, 1)
        p = ax.bar(["A", "B", "C"], [[1, 2], [3, 4], [5, 6]])
        st = _state(p)
        assert st["groups"] == 2
        assert st["values"] == pytest.approx(np.array([[1, 2], [3, 4], [5, 6]]))

    def test_numpy_2d_height(self):
        arr = np.array([[10, 20], [30, 40]])
        fig, ax = apl.subplots(1, 1)
        assert _state(ax.bar([0, 1], arr))["groups"] == 2

    def test_grouped_2d_height_with_group_labels(self):
        data = np.array([[1, 2, 3], [4, 5, 6]], dtype=float)
        bar = _bar(["A", "B"], data, group_labels=["G1", "G2", "G3"])
        assert bar._state["groups"] == 3
        assert bar._state["group_labels"] == ["G1", "G2", "G3"]

    def test_group_labels_stored(self):
        fig, ax = apl.subplots(1, 1)
        p = ax.bar(["A", "B"], [[1, 2], [3, 4]], group_labels=["G1", "G2"])
        assert _state(p)["group_labels"] == ["G1", "G2"]

    def test_group_colors_stored(self):
        fig, ax = apl.subplots(1, 1)
        p = ax.bar(["A", "B"], [[1, 2], [3, 4]], group_colors=["#f00", "#0f0"])
        assert _state(p)["group_colors"] == ["#f00", "#0f0"]

    def test_default_group_colors_assigned_for_multi_group(self):
        """Multi-group without explicit group_colors gets a default palette."""
        fig, ax = apl.subplots(1, 1)
        gc = _state(ax.bar(["A", "B"], [[1, 2], [3, 4]]))["group_colors"]
        assert len(gc) == 2
        assert all(c.startswith("#") for c in gc)

    def test_grouped_default_colors_count(self):
        data = np.ones((3, 2))
        assert len(_bar([1, 2, 3], data)._state["group_colors"]) == 2

    def test_single_group_colors_empty_by_default(self):
        assert _state(_make_bar([1, 2, 3]))["group_colors"] == []

    def test_3d_height_raises(self):
        with pytest.raises(ValueError):
            _bar([1], np.ones((1, 2, 3)))

    def test_set_data_2d_values(self):
        fig, ax = apl.subplots(1, 1)
        p = ax.bar(["A", "B"], [[1, 2], [3, 4]])
        p.set_data([[10, 20], [30, 40]])
        assert _state(p)["values"] == pytest.approx(np.array([[10, 20], [30, 40]]))

    def test_set_data_group_count_mismatch_raises(self):
        fig, ax = apl.subplots(1, 1)
        p = ax.bar(["A", "B"], [[1, 2], [3, 4]])  # groups=2
        with pytest.raises(ValueError, match="Group count"):
            p.set_data([[1, 2, 3], [4, 5, 6]])


# ===========================================================================
# 5. Log scale
# ===========================================================================

class TestPlotBarLogScale:

    def test_log_scale_flag_stored(self):
        fig, ax = apl.subplots(1, 1)
        p = ax.bar([0, 1, 2], [1, 10, 100], log_scale=True)
        assert _state(p)["log_scale"] is True

    def test_log_scale_data_min_positive(self):
        """data_min must be > 0 when log_scale=True."""
        fig, ax = apl.subplots(1, 1)
        assert _state(ax.bar([0, 1, 2], [1, 10, 100], log_scale=True))["data_min"] > 0.0

    def test_log_scale_negative_values_clamped(self):
        """Negative values are clamped for display, not raised."""
        fig, ax = apl.subplots(1, 1)
        st = _state(ax.bar([0, 1, 2], [-5, 10, 100], log_scale=True))
        assert st["log_scale"] is True
        assert st["data_min"] > 0.0

    def test_log_scale_all_negative_clamped(self):
        """All-negative values → data_min clamps to 1e-10."""
        fig, ax = apl.subplots(1, 1)
        assert _state(ax.bar([0, 1], [-3, -1], log_scale=True))["data_min"] > 0.0

    def test_set_log_scale_on(self):
        p = _make_bar([1, 10, 100])
        p.set_log_scale(True)
        st = _state(p)
        assert st["log_scale"] is True
        assert st["data_min"] > 0.0

    def test_set_log_scale_off(self):
        fig, ax = apl.subplots(1, 1)
        p = ax.bar([0, 1, 2], [1, 10, 100], log_scale=True)
        p.set_log_scale(False)
        assert _state(p)["log_scale"] is False

    def test_set_log_scale_push(self):
        fig, ax = apl.subplots(1, 1)
        p = ax.bar([0, 1, 2], [1, 10, 100])
        p.set_log_scale(True)
        data = json.loads(getattr(fig, f"panel_{p._id}_json"))
        assert data["log_scale"] is True


# ===========================================================================
# 6. set_data() — value replacement
# ===========================================================================

class TestPlotBarSetData:

    def test_update_replaces_values(self):
        p = _make_bar([1, 2, 3])
        p.set_data([10, 20, 30])
        assert _state(p)["values"] == pytest.approx(np.array([[10.0], [20.0], [30.0]]))

    def test_update_recalculates_data_max(self):
        p = _make_bar([1, 2, 3])
        p.set_data([100, 200, 300])
        assert _state(p)["data_max"] > 300.0

    def test_update_recalculates_data_min(self):
        p = _make_bar([1, 2, 3])
        p.set_data([-50, -20, -10])
        assert _state(p)["data_min"] < -50.0

    def test_update_with_new_x_centers(self):
        p = _make_bar([1, 2, 3])
        p.set_data([4, 5, 6], x_centers=[0.5, 1.5, 2.5])
        assert _state(p)["x_centers"] == pytest.approx([0.5, 1.5, 2.5])

    def test_update_with_new_x(self):
        p = _make_bar([1, 2, 3])
        p.set_data([4, 5, 6], x=[0.5, 1.5, 2.5])
        assert _state(p)["x_centers"] == pytest.approx([0.5, 1.5, 2.5])

    def test_update_with_new_x_labels(self):
        p = _make_bar([1, 2, 3], x_labels=["a", "b", "c"])
        p.set_data([4, 5, 6], x_labels=["x", "y", "z"])
        assert _state(p)["x_labels"] == ["x", "y", "z"]

    def test_update_preserves_orient(self):
        p = _make_bar([1, 2, 3], orient="h")
        p.set_data([4, 5, 6])
        assert _state(p)["orient"] == "h"

    def test_update_preserves_baseline(self):
        p = _make_bar([1, 2, 3], baseline=2.0)
        p.set_data([10, 20, 30])
        assert _state(p)["baseline"] == pytest.approx(2.0)

    def test_set_data_range_recalculated(self):
        bar = _bar([1, 2, 3], [10, 20, 30])
        old_max = bar._state["data_max"]
        bar.set_data([100, 200, 300])
        assert bar._state["data_max"] > old_max

    def test_set_data_bad_ndim_raises(self):
        p = _make_bar([1, 2, 3])
        with pytest.raises(ValueError, match="1-D or 2-D"):
            p.set_data(np.zeros((2, 2, 2)))


# ===========================================================================
# 7. Display-setting mutations
# ===========================================================================

class TestPlotBarDisplayMutations:

    def test_set_color(self):
        p = _make_bar()
        p.set_color("#abcdef")
        assert _state(p)["bar_color"] == "#abcdef"

    def test_set_colors(self):
        p = _make_bar([1, 2, 3])
        p.set_colors(["red", "green", "blue"])
        assert _state(p)["bar_colors"] == ["red", "green", "blue"]

    def test_set_show_values_true(self):
        p = _make_bar(show_values=False)
        p.set_show_values(True)
        assert _state(p)["show_values"] is True

    def test_set_show_values_false(self):
        p = _make_bar(show_values=True)
        p.set_show_values(False)
        assert _state(p)["show_values"] is False


# ===========================================================================
# 8. _push() / Figure integration
# ===========================================================================

class TestPlotBarPush:

    def test_panel_trait_exists_after_attach(self):
        fig, ax = apl.subplots(1, 1)
        p = ax.bar([1, 2, 3])
        assert fig.has_trait(f"panel_{p._id}_json")

    def test_panel_json_contains_kind_bar(self):
        fig, ax = apl.subplots(1, 1)
        p = ax.bar([1, 2, 3])
        data = json.loads(getattr(fig, f"panel_{p._id}_json"))
        assert data["kind"] == "bar"

    def test_panel_json_values_after_update(self):
        fig, ax = apl.subplots(1, 1)
        p = ax.bar([1, 2, 3])
        p.set_data([7, 8, 9])
        data = json.loads(getattr(fig, f"panel_{p._id}_json"))
        assert data["values"] == pytest.approx(np.array([[7.0], [8.0], [9.0]]))

    def test_panel_json_color_after_set_color(self):
        fig, ax = apl.subplots(1, 1)
        p = ax.bar([1, 2, 3])
        p.set_color("#112233")
        data = json.loads(getattr(fig, f"panel_{p._id}_json"))
        assert data["bar_color"] == "#112233"

    def test_push_without_figure_is_noop(self):
        p = PlotBar([1, 2, 3])
        p._push()  # must not raise

    def test_layout_json_kind_bar(self):
        fig, ax = apl.subplots(1, 1)
        p = ax.bar([10, 20, 30])
        layout = json.loads(fig.layout_json)
        panel_spec = next(s for s in layout["panel_specs"] if s["id"] == p._id)
        assert panel_spec["kind"] == "bar"


# ===========================================================================
# 9. Callback API
# ===========================================================================

class TestPlotBarCallbacks:

    def test_has_callback_registry(self):
        assert isinstance(_make_bar().callbacks, CallbackRegistry)

    def test_on_click_decorator_returns_fn(self):
        p = _make_bar()
        fn = lambda e: None
        result = p.add_event_handler(fn, "pointer_down")
        assert result is fn

    def test_on_click_stamps_event_types(self):
        p = _make_bar()

        @p.add_event_handler("pointer_down")
        def cb(event): pass

        assert hasattr(cb, "_event_types") and "pointer_down" in cb._event_types

    def test_on_click_fires(self):
        p = _make_bar()
        fired = []

        @p.add_event_handler("pointer_down")
        def cb(event): fired.append(event)

        p.callbacks.fire(Event("pointer_down", p, bar_index=2, value=3.0,
                               group_index=0))
        assert len(fired) == 1

    def test_on_click_event_data_with_group(self):
        p = _make_bar([10, 20, 30])
        fired = []

        @p.add_event_handler("pointer_down")
        def cb(event): fired.append(event)

        p.callbacks.fire(Event("pointer_down", p,
                               bar_index=1, value=20.0,
                               group_index=0,
                               x_label="B"))
        ev = fired[0]
        assert ev.bar_index == 1
        assert ev.value == pytest.approx(20.0)
        assert ev.group_index == 0
        assert ev.x_label == "B"

    def test_on_click_grouped_event(self):
        fig, ax = apl.subplots(1, 1)
        p = ax.bar(["A", "B"], [[1, 10], [2, 20]])
        fired = []

        @p.add_event_handler("pointer_down")
        def cb(event): fired.append(event)

        p.callbacks.fire(Event("pointer_down", p,
                               bar_index=1, group_index=1,
                               value=20.0,
                               x_label="B"))
        assert fired[0].group_index == 1
        assert fired[0].value == pytest.approx(20.0)

    def test_on_changed_fires(self):
        p = _make_bar()
        fired = []

        @p.add_event_handler("pointer_move")
        def cb(event): fired.append(event)

        p.callbacks.fire(Event("pointer_move", p))
        assert len(fired) == 1

    def test_on_click_not_fired_by_on_changed(self):
        p = _make_bar()
        fired = []

        @p.add_event_handler("pointer_down")
        def cb(event): fired.append(event)

        p.callbacks.fire(Event("pointer_move", p))
        assert fired == []

    def test_disconnect(self):
        p = _make_bar()
        fired = []

        @p.add_event_handler("pointer_down")
        def cb(event): fired.append(event)

        p.remove_handler(cb)
        p.callbacks.fire(Event("pointer_down", p))
        assert fired == []

    def test_multiple_on_click_handlers(self):
        p = _make_bar()
        log = []

        @p.add_event_handler("pointer_down")
        def cb1(event): log.append("a")

        @p.add_event_handler("pointer_down")
        def cb2(event): log.append("b")

        p.callbacks.fire(Event("pointer_down", p))
        assert sorted(log) == ["a", "b"]


# ===========================================================================
# 10. Widgets
# ===========================================================================

class TestPlotBarWidgets:

    def test_add_vline_widget(self):
        bar = _bar(["A", "B", "C"], [10, 20, 30])
        bar.add_vline_widget(1.5, color="#ff6e40")
        assert len(bar._widgets) == 1

    def test_add_hline_widget(self):
        bar = _bar([1, 2, 3], [10, 20, 30])
        bar.add_hline_widget(15.0)
        assert len(bar._widgets) == 1

    def test_add_range_widget(self):
        bar = _bar([1, 2, 3], [10, 20, 30])
        bar.add_range_widget(0.5, 2.5)
        assert len(bar._widgets) == 1

    def test_add_point_widget(self):
        bar = _bar([1, 2, 3], [10, 20, 30])
        bar.add_point_widget(1.0, 15.0)
        assert len(bar._widgets) == 1

    def test_get_widget_by_id(self):
        bar = _bar([1, 2], [10, 20])
        w = bar.add_vline_widget(1.0)
        assert bar.get_widget(w.id) is w

    def test_get_widget_missing_raises(self):
        bar = _bar([1, 2], [10, 20])
        with pytest.raises(KeyError):
            bar.get_widget("nope")

    def test_remove_widget(self):
        bar = _bar([1, 2], [10, 20])
        w = bar.add_vline_widget(1.0)
        bar.remove_widget(w)
        assert len(bar._widgets) == 0

    def test_remove_widget_missing_raises(self):
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


# ===========================================================================
# 11. Edge cases
# ===========================================================================

class TestPlotBarEdgeCases:

    def test_single_bar(self):
        st = _state(_make_bar([42]))
        assert len(st["values"]) == 1
        assert st["data_max"] > st["data_min"]

    def test_large_n(self):
        values = list(range(200))
        st = _state(_make_bar(values))
        assert len(st["values"]) == 200
        assert len(st["x_centers"]) == 200

    def test_all_negative_values(self):
        st = _state(_make_bar([-5, -3, -1]))
        assert st["data_min"] < -5.0
        assert st["data_max"] >= 0.0

    def test_mixed_positive_negative(self):
        st = _state(_make_bar([-10, 0, 10]))
        assert st["data_min"] < -10.0
        assert st["data_max"] > 10.0

    def test_float_values(self):
        assert _state(_make_bar([1.1, 2.2, 3.3]))["values"] == pytest.approx(
            np.array([[1.1], [2.2], [3.3]])
        )

    def test_x_centers_float(self):
        assert _state(_make_bar([1, 2, 3], x_centers=[0.5, 1.5, 2.5]))["x_centers"] == pytest.approx(
            [0.5, 1.5, 2.5]
        )

    def test_bar_width_zero_boundary(self):
        assert _state(_make_bar(bar_width=0.0))["bar_width"] == pytest.approx(0.0)

    def test_bar_width_one_boundary(self):
        assert _state(_make_bar(bar_width=1.0))["bar_width"] == pytest.approx(1.0)


# ===========================================================================
# 12. Validation errors
# ===========================================================================

class TestPlotBarValidation:

    def test_3d_values_raises(self):
        with pytest.raises(ValueError, match="1-D or 2-D"):
            PlotBar(np.zeros((2, 2, 2)))

    def test_invalid_orient_raises(self):
        with pytest.raises(ValueError, match="orient"):
            PlotBar([1, 2, 3], orient="diagonal")

    def test_x_centers_length_mismatch_raises(self):
        with pytest.raises(ValueError, match="length"):
            PlotBar([1, 2, 3], x_centers=[0, 1])


# ===========================================================================
# 13. repr
# ===========================================================================

class TestPlotBarRepr:

    def test_repr_contains_n(self):
        assert "n=4" in repr(_make_bar([1, 2, 3, 4]))

    def test_repr_contains_orient_v(self):
        assert "orient='v'" in repr(_make_bar([1, 2, 3]))

    def test_repr_contains_orient_h(self):
        assert "orient='h'" in repr(_make_bar([1, 2, 3], orient="h"))

    def test_repr_is_string(self):
        assert isinstance(repr(_make_bar()), str)

    def test_repr_grouped_shows_groups(self):
        fig, ax = apl.subplots(1, 1)
        p = ax.bar([0, 1], [[1, 2], [3, 4]])
        assert "groups=2" in repr(p)
        assert "n=2" in repr(p)

    def test_repr_contains_plotbar(self):
        assert "PlotBar" in repr(_bar([1, 2, 3], [10, 20, 30]))


# ===========================================================================
# New state keys added in audit fix
# ===========================================================================

class TestPlotBarNewStateKeys:
    def test_title_default_empty(self):
        assert _make_bar()._state["title"] == ""

    def test_x_label_in_state(self):
        assert "x_label" in _make_bar()._state

    def test_y_label_in_state(self):
        assert "y_label" in _make_bar()._state

    def test_axis_visible_true_by_default(self):
        assert _make_bar()._state["axis_visible"] is True

    def test_x_ticks_visible_true_by_default(self):
        assert _make_bar()._state["x_ticks_visible"] is True

    def test_y_ticks_visible_true_by_default(self):
        assert _make_bar()._state["y_ticks_visible"] is True

    def test_align_stored(self):
        assert _make_bar(align="edge")._state["align"] == "edge"

    def test_align_center_by_default(self):
        assert _make_bar()._state["align"] == "center"

    def test_y_range_none_by_default(self):
        p = _make_bar()
        assert "y_range" in p._state
        assert p._state["y_range"] is None

    def test_view_from_python_false_by_default(self):
        assert _make_bar()._state["_view_from_python"] is False


# ===========================================================================
# New display-control methods added in audit fix
# ===========================================================================

class TestPlotBarDisplayMethods:
    def test_set_title(self):
        p = _make_bar()
        p.set_title("My Chart")
        assert p._state["title"] == "My Chart"

    def test_set_xlabel(self):
        p = _make_bar()
        p.set_xlabel("Category")
        assert p._state["x_label"] == "Category"

    def test_set_ylabel(self):
        p = _make_bar()
        p.set_ylabel("Value")
        assert p._state["y_label"] == "Value"

    def test_set_axis_off(self):
        p = _make_bar()
        p.set_axis_off()
        assert p._state["axis_visible"] is False

    def test_set_axis_on_restores(self):
        p = _make_bar()
        p.set_axis_off()
        p.set_axis_on()
        assert p._state["axis_visible"] is True

    def test_set_ticks_visible_both_false(self):
        p = _make_bar()
        p.set_ticks_visible(False)
        assert p._state["x_ticks_visible"] is False
        assert p._state["y_ticks_visible"] is False

    def test_set_ticks_visible_x_only(self):
        p = _make_bar()
        p.set_ticks_visible(True, x=True, y=False)
        assert p._state["x_ticks_visible"] is True
        assert p._state["y_ticks_visible"] is False

    def test_set_ylim(self):
        p = _make_bar()
        p.set_ylim(0.0, 10.0)
        assert p._state["y_range"] == [0.0, 10.0]

    def test_get_ylim_default(self):
        p = _make_bar()
        lo, hi = p.get_ylim()
        assert lo == pytest.approx(p._state["data_min"])
        assert hi == pytest.approx(p._state["data_max"])

    def test_get_ylim_after_set_ylim(self):
        p = _make_bar()
        p.set_ylim(-1.0, 20.0)
        lo, hi = p.get_ylim()
        assert lo == pytest.approx(-1.0)
        assert hi == pytest.approx(20.0)

    def test_set_xlim_changes_view(self):
        fig, ax = apl.subplots(1, 1)
        p = ax.bar(np.arange(10), np.ones(10))
        p.set_xlim(2.0, 7.0)
        assert p._state["view_x0"] != 0.0 or p._state["view_x1"] != 1.0

    def test_reset_view(self):
        fig, ax = apl.subplots(1, 1)
        p = ax.bar(np.arange(10), np.ones(10))
        p.set_xlim(2.0, 7.0)
        p.set_ylim(0.0, 5.0)
        p.reset_view()
        assert p._state["view_x0"] == pytest.approx(0.0)
        assert p._state["view_x1"] == pytest.approx(1.0)
        assert p._state["y_range"] is None


# ===========================================================================
# _view_from_python flag on PlotBar
# ===========================================================================

class TestPlotBarViewFromPython:
    def test_set_xlim_clears_flag(self):
        fig, ax = apl.subplots(1, 1)
        p = ax.bar(np.arange(10), np.ones(10))
        p.set_xlim(2.0, 7.0)
        assert p._state["_view_from_python"] is False

    def test_reset_view_clears_flag(self):
        p = _make_bar()
        p.reset_view()
        assert p._state["_view_from_python"] is False



# ===========================================================================
# PlotBar: get_xlim and fixed set_ticks_visible signature
# ===========================================================================

class TestPlotBarGetXlim:
    def test_get_xlim_default(self):
        p = _make_bar()
        x_axis = p._state["x_axis"]
        lo, hi = p.get_xlim()
        assert lo == pytest.approx(x_axis[0])
        assert hi == pytest.approx(x_axis[-1])

    def test_get_xlim_after_set_xlim(self):
        fig, ax = apl.subplots(1, 1)
        p = ax.bar(np.arange(10), np.ones(10))
        p.set_xlim(2.0, 7.0)
        lo, hi = p.get_xlim()
        assert lo == pytest.approx(2.0, abs=0.5)
        assert hi == pytest.approx(7.0, abs=0.5)


class TestPlotBarSetTicksVisibleSignature:
    def test_positional_visible_both(self):
        p = _make_bar()
        p.set_ticks_visible(False)
        assert p._state["x_ticks_visible"] is False
        assert p._state["y_ticks_visible"] is False

    def test_positional_visible_true(self):
        p = _make_bar()
        p.set_ticks_visible(False)
        p.set_ticks_visible(True)
        assert p._state["x_ticks_visible"] is True
        assert p._state["y_ticks_visible"] is True

    def test_keyword_x_only(self):
        p = _make_bar()
        p.set_ticks_visible(True, x=False)
        assert p._state["x_ticks_visible"] is False
        assert p._state["y_ticks_visible"] is True

    def test_keyword_y_only(self):
        p = _make_bar()
        p.set_ticks_visible(True, y=False)
        assert p._state["x_ticks_visible"] is True
        assert p._state["y_ticks_visible"] is False


# ===========================================================================
# M3: PlotBar constructor-only setters
# ===========================================================================

class TestPlotBarNewSetters:
    def test_set_bar_width(self):
        p = _make_bar()
        p.set_bar_width(0.5)
        assert p._state["bar_width"] == pytest.approx(0.5)

    def test_set_align_center(self):
        p = _make_bar()
        p.set_align("center")
        assert p._state["align"] == "center"

    def test_set_align_edge(self):
        p = _make_bar()
        p.set_align("edge")
        assert p._state["align"] == "edge"

    def test_set_align_invalid(self):
        p = _make_bar()
        with pytest.raises(ValueError):
            p.set_align("left")

    def test_set_orient_h(self):
        p = _make_bar()
        p.set_orient("h")
        assert p._state["orient"] == "h"

    def test_set_orient_v(self):
        p = _make_bar()
        p.set_orient("v")
        assert p._state["orient"] == "v"

    def test_set_orient_invalid(self):
        p = _make_bar()
        with pytest.raises(ValueError):
            p.set_orient("diagonal")

    def test_set_group_labels(self):
        p = _make_bar()
        p.set_group_labels(["a", "b", "c"])
        assert p._state["group_labels"] == ["a", "b", "c"]


# ===========================================================================
# M1/M2: standardized parameter names
# ===========================================================================

class TestPlotBarParameterNames:
    def test_set_title_uses_label_param(self):
        import inspect
        p = _make_bar()
        sig = inspect.signature(p.set_title)
        assert "label" in sig.parameters

    def test_set_xlabel_uses_label_param(self):
        import inspect
        p = _make_bar()
        sig = inspect.signature(p.set_xlabel)
        assert "label" in sig.parameters

    def test_set_xlim_uses_xmin_xmax(self):
        import inspect
        p = _make_bar()
        sig = inspect.signature(p.set_xlim)
        params = list(sig.parameters)
        assert params[0] == "xmin"
        assert params[1] == "xmax"

    def test_set_title_works(self):
        p = _make_bar()
        p.set_title(label="My Bar Chart")
        assert p._state["title"] == "My Bar Chart"


# ===========================================================================
# m2: configure_pointer_settled public on PlotBar
# ===========================================================================

class TestPlotBarConfigurePointerSettled:
    def test_public_method_exists(self):
        p = _make_bar()
        assert hasattr(p, "configure_pointer_settled")
        assert callable(p.configure_pointer_settled)

    def test_sets_state(self):
        p = _make_bar()
        p.configure_pointer_settled(300, 6)
        assert p._state["pointer_settled_ms"] == 300
        assert p._state["pointer_settled_delta"] == 6

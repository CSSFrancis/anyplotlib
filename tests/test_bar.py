"""
tests/test_bar.py
=================

Tests for the bar chart (PlotBar) functionality.

Covers:
  * Construction – default and explicit arguments (matplotlib-aligned API)
  * State dict contents and data integrity
  * Orientation (vertical / horizontal)
  * Colour options: single colour, per-bar colours, group colours
  * Bar-width, baseline/bottom, and show_values flags
  * x (positions or category labels) and x_labels
  * Range / padding calculations
  * Grouped bars – 2-D height array, group_labels, group_colors
  * Log scale – log_scale flag, clamping, set_log_scale()
  * update() – value replacement and axis recalculation
  * Display-setting mutations: set_color, set_colors, set_show_values, set_log_scale
  * _push() contract – state is propagated to the Figure
  * Layout JSON reflects "bar" kind for PlotBar panels
  * Callback API: on_click (incl. group_index/group_value), on_changed, disconnect
  * Edge cases: single bar, negative values, all-equal values, large N
  * Validation errors for bad inputs
  * repr()
"""

from __future__ import annotations

import json
import numpy as np
import pytest

import anyplotlib as apl
from anyplotlib.callbacks import CallbackRegistry, Event
from anyplotlib.figure_plots import PlotBar


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_bar(values=None, **kwargs) -> PlotBar:
    """Create a PlotBar attached to a one-panel Figure (backward-compat call)."""
    if values is None:
        values = [1, 2, 3, 4, 5]
    fig, ax = apl.subplots(1, 1)
    return ax.bar(values, **kwargs)


def _state(plot: PlotBar) -> dict:
    return plot.to_state_dict()


# ─────────────────────────────────────────────────────────────────────────────
# 1. Construction – defaults
# ─────────────────────────────────────────────────────────────────────────────

class TestPlotBarConstruction:

    def test_kind_is_bar(self):
        p = _make_bar()
        assert _state(p)["kind"] == "bar"

    def test_values_stored_as_2d(self):
        values = [10, 20, 30]
        p = _make_bar(values)
        # values are always stored as N×G (2-D) — [[v], [v], ...] for G=1
        assert _state(p)["values"] == pytest.approx(np.array([[10.0], [20.0], [30.0]]))

    def test_numpy_array_accepted(self):
        arr = np.array([1.0, 2.0, 3.0])
        p = _make_bar(arr)
        assert _state(p)["values"] == pytest.approx(np.array([[1.0], [2.0], [3.0]]))

    def test_default_x_centers(self):
        p = _make_bar([5, 6, 7])
        assert _state(p)["x_centers"] == pytest.approx([0.0, 1.0, 2.0])

    def test_default_orient_is_vertical(self):
        p = _make_bar()
        assert _state(p)["orient"] == "v"

    def test_default_baseline_is_zero(self):
        p = _make_bar()
        assert _state(p)["baseline"] == pytest.approx(0.0)

    def test_default_bar_width(self):
        p = _make_bar()
        assert _state(p)["bar_width"] == pytest.approx(0.8)

    def test_default_show_values_false(self):
        p = _make_bar()
        assert _state(p)["show_values"] is False

    def test_default_color(self):
        p = _make_bar()
        assert _state(p)["bar_color"] == "#4fc3f7"

    def test_default_bar_colors_empty(self):
        p = _make_bar()
        assert _state(p)["bar_colors"] == []

    def test_default_x_labels_empty(self):
        p = _make_bar()
        assert _state(p)["x_labels"] == []

    def test_default_units_empty(self):
        p = _make_bar()
        assert _state(p)["units"] == ""
        assert _state(p)["y_units"] == ""

    def test_default_groups_is_one(self):
        p = _make_bar()
        assert _state(p)["groups"] == 1

    def test_default_log_scale_false(self):
        p = _make_bar()
        assert _state(p)["log_scale"] is False


# ─────────────────────────────────────────────────────────────────────────────
# 2. Construction – explicit arguments (matplotlib-aligned)
# ─────────────────────────────────────────────────────────────────────────────

class TestPlotBarExplicitArgs:

    def test_x_as_positions(self):
        """bar(x, height) — x as numeric positions."""
        fig, ax = apl.subplots(1, 1)
        p = ax.bar([0, 1, 2], [10, 20, 30])
        st = _state(p)
        assert st["x_centers"] == pytest.approx([0.0, 1.0, 2.0])
        assert st["values"] == pytest.approx(np.array([[10.0], [20.0], [30.0]]))

    def test_x_as_string_labels(self):
        """bar(['A','B','C'], height) — x as category strings."""
        fig, ax = apl.subplots(1, 1)
        p = ax.bar(["A", "B", "C"], [1, 2, 3])
        st = _state(p)
        assert st["x_labels"] == ["A", "B", "C"]
        assert st["x_centers"] == pytest.approx([0.0, 1.0, 2.0])

    def test_width_parameter(self):
        fig, ax = apl.subplots(1, 1)
        p = ax.bar([0, 1, 2], [1, 2, 3], width=0.5)
        assert _state(p)["bar_width"] == pytest.approx(0.5)

    def test_bottom_parameter(self):
        fig, ax = apl.subplots(1, 1)
        p = ax.bar([0, 1, 2], [1, 2, 3], bottom=5.0)
        assert _state(p)["baseline"] == pytest.approx(5.0)

    def test_legacy_x_centers(self):
        p = _make_bar([1, 2, 3], x_centers=[10, 20, 30])
        assert _state(p)["x_centers"] == pytest.approx([10.0, 20.0, 30.0])

    def test_legacy_x_labels(self):
        p = _make_bar([1, 2, 3], x_labels=["A", "B", "C"])
        assert _state(p)["x_labels"] == ["A", "B", "C"]

    def test_custom_color(self):
        p = _make_bar(color="#ff0000")
        assert _state(p)["bar_color"] == "#ff0000"

    def test_custom_colors_list(self):
        colors = ["#f00", "#0f0", "#00f"]
        p = _make_bar([1, 2, 3], colors=colors)
        assert _state(p)["bar_colors"] == colors

    def test_legacy_bar_width(self):
        p = _make_bar(bar_width=0.5)
        assert _state(p)["bar_width"] == pytest.approx(0.5)

    def test_horizontal_orient(self):
        p = _make_bar(orient="h")
        assert _state(p)["orient"] == "h"

    def test_legacy_baseline(self):
        p = _make_bar(baseline=5.0)
        assert _state(p)["baseline"] == pytest.approx(5.0)

    def test_show_values_true(self):
        p = _make_bar(show_values=True)
        assert _state(p)["show_values"] is True

    def test_units_and_y_units(self):
        p = _make_bar(units="category", y_units="count")
        assert _state(p)["units"] == "category"
        assert _state(p)["y_units"] == "count"


# ─────────────────────────────────────────────────────────────────────────────
# 3. Range / padding calculations
# ─────────────────────────────────────────────────────────────────────────────

class TestPlotBarRange:

    def test_data_max_exceeds_max_value(self):
        p = _make_bar([1, 2, 3, 4, 5])
        assert _state(p)["data_max"] > 5.0

    def test_data_min_at_baseline_for_positive_values(self):
        p = _make_bar([1, 2, 3, 4, 5], baseline=0.0)
        assert _state(p)["data_min"] <= 0.0

    def test_negative_values_extend_data_min(self):
        p = _make_bar([-3, -1, 0, 2])
        assert _state(p)["data_min"] < -3.0

    def test_data_max_gt_data_min(self):
        p = _make_bar([1, 2, 3])
        st = _state(p)
        assert st["data_max"] > st["data_min"]

    def test_all_equal_values_padded(self):
        p = _make_bar([5, 5, 5])
        st = _state(p)
        assert st["data_max"] > st["data_min"]

    def test_baseline_above_all_values(self):
        p = _make_bar([1, 2, 3], baseline=10.0)
        assert _state(p)["data_max"] >= 10.0

    def test_baseline_below_all_values(self):
        p = _make_bar([5, 6, 7], baseline=-5.0)
        assert _state(p)["data_min"] <= -5.0


# ─────────────────────────────────────────────────────────────────────────────
# 4. Grouped bars
# ─────────────────────────────────────────────────────────────────────────────

class TestPlotBarGrouped:

    def test_2d_height_creates_groups(self):
        """2-D height array (N, G) → groups == G."""
        fig, ax = apl.subplots(1, 1)
        p = ax.bar(["A", "B", "C"], [[1, 2], [3, 4], [5, 6]])
        st = _state(p)
        assert st["groups"] == 2
        assert st["values"] == pytest.approx(np.array([[1, 2], [3, 4], [5, 6]]))

    def test_numpy_2d_height(self):
        arr = np.array([[10, 20], [30, 40]])
        fig, ax = apl.subplots(1, 1)
        p = ax.bar([0, 1], arr)
        assert _state(p)["groups"] == 2

    def test_group_labels_stored(self):
        fig, ax = apl.subplots(1, 1)
        p = ax.bar(["A", "B"], [[1, 2], [3, 4]], group_labels=["G1", "G2"])
        assert _state(p)["group_labels"] == ["G1", "G2"]

    def test_group_colors_stored(self):
        fig, ax = apl.subplots(1, 1)
        p = ax.bar(["A", "B"], [[1, 2], [3, 4]],
                   group_colors=["#f00", "#0f0"])
        assert _state(p)["group_colors"] == ["#f00", "#0f0"]

    def test_default_group_colors_assigned_for_multi_group(self):
        """Multi-group without explicit group_colors gets a default palette."""
        fig, ax = apl.subplots(1, 1)
        p = ax.bar(["A", "B"], [[1, 2], [3, 4]])
        gc = _state(p)["group_colors"]
        assert len(gc) == 2
        assert all(c.startswith("#") for c in gc)

    def test_single_group_colors_empty_by_default(self):
        """Ungrouped charts have empty group_colors (uses bar_color)."""
        p = _make_bar([1, 2, 3])
        assert _state(p)["group_colors"] == []

    def test_repr_shows_groups(self):
        fig, ax = apl.subplots(1, 1)
        p = ax.bar([0, 1], [[1, 2], [3, 4]])
        assert "groups=2" in repr(p)

    def test_update_2d_values(self):
        fig, ax = apl.subplots(1, 1)
        p = ax.bar(["A", "B"], [[1, 2], [3, 4]])
        p.update([[10, 20], [30, 40]])
        assert _state(p)["values"] == pytest.approx(np.array([[10, 20], [30, 40]]))

    def test_update_group_count_mismatch_raises(self):
        fig, ax = apl.subplots(1, 1)
        p = ax.bar(["A", "B"], [[1, 2], [3, 4]])  # groups=2
        with pytest.raises(ValueError, match="Group count mismatch"):
            p.update([[1, 2, 3], [4, 5, 6]])       # 3 groups → error


# ─────────────────────────────────────────────────────────────────────────────
# 5. Log scale
# ─────────────────────────────────────────────────────────────────────────────

class TestPlotBarLogScale:

    def test_log_scale_flag_stored(self):
        fig, ax = apl.subplots(1, 1)
        p = ax.bar([0, 1, 2], [1, 10, 100], log_scale=True)
        assert _state(p)["log_scale"] is True

    def test_log_scale_data_min_positive(self):
        """data_min must be > 0 when log_scale=True."""
        fig, ax = apl.subplots(1, 1)
        p = ax.bar([0, 1, 2], [1, 10, 100], log_scale=True)
        assert _state(p)["data_min"] > 0.0

    def test_log_scale_negative_values_clamped(self):
        """Negative values do NOT raise; they are clamped for display."""
        fig, ax = apl.subplots(1, 1)
        p = ax.bar([0, 1, 2], [-5, 10, 100], log_scale=True)
        st = _state(p)
        assert st["log_scale"] is True
        assert st["data_min"] > 0.0   # clamped, not raised

    def test_log_scale_all_negative_clamped(self):
        """All-negative values → data_min clamps to 1e-10."""
        fig, ax = apl.subplots(1, 1)
        p = ax.bar([0, 1], [-3, -1], log_scale=True)
        assert _state(p)["data_min"] > 0.0

    def test_set_log_scale_enables(self):
        p = _make_bar([1, 10, 100])
        p.set_log_scale(True)
        st = _state(p)
        assert st["log_scale"] is True
        assert st["data_min"] > 0.0

    def test_set_log_scale_disables(self):
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


# ─────────────────────────────────────────────────────────────────────────────
# 6. update() — value replacement
# ─────────────────────────────────────────────────────────────────────────────

class TestPlotBarUpdate:

    def test_update_replaces_values(self):
        p = _make_bar([1, 2, 3])
        p.update([10, 20, 30])
        assert _state(p)["values"] == pytest.approx(np.array([[10.0], [20.0], [30.0]]))

    def test_update_recalculates_data_max(self):
        p = _make_bar([1, 2, 3])
        p.update([100, 200, 300])
        assert _state(p)["data_max"] > 300.0

    def test_update_recalculates_data_min(self):
        p = _make_bar([1, 2, 3])
        p.update([-50, -20, -10])
        assert _state(p)["data_min"] < -50.0

    def test_update_with_new_x_centers(self):
        p = _make_bar([1, 2, 3])
        p.update([4, 5, 6], x_centers=[0.5, 1.5, 2.5])
        assert _state(p)["x_centers"] == pytest.approx([0.5, 1.5, 2.5])

    def test_update_with_new_x(self):
        p = _make_bar([1, 2, 3])
        p.update([4, 5, 6], x=[0.5, 1.5, 2.5])
        assert _state(p)["x_centers"] == pytest.approx([0.5, 1.5, 2.5])

    def test_update_with_new_x_labels(self):
        p = _make_bar([1, 2, 3], x_labels=["a", "b", "c"])
        p.update([4, 5, 6], x_labels=["x", "y", "z"])
        assert _state(p)["x_labels"] == ["x", "y", "z"]

    def test_update_preserves_orient(self):
        p = _make_bar([1, 2, 3], orient="h")
        p.update([4, 5, 6])
        assert _state(p)["orient"] == "h"

    def test_update_preserves_baseline(self):
        p = _make_bar([1, 2, 3], baseline=2.0)
        p.update([10, 20, 30])
        assert _state(p)["baseline"] == pytest.approx(2.0)

    def test_update_3d_raises(self):
        p = _make_bar([1, 2, 3])
        with pytest.raises(ValueError, match="1-D or 2-D"):
            p.update(np.zeros((2, 2, 2)))


# ─────────────────────────────────────────────────────────────────────────────
# 7. Display-setting mutations
# ─────────────────────────────────────────────────────────────────────────────

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


# ─────────────────────────────────────────────────────────────────────────────
# 8. _push() / Figure integration
# ─────────────────────────────────────────────────────────────────────────────

class TestPlotBarPush:

    def test_panel_trait_exists_after_attach(self):
        fig, ax = apl.subplots(1, 1)
        p = ax.bar([1, 2, 3])
        trait_name = f"panel_{p._id}_json"
        assert fig.has_trait(trait_name), f"Missing trait {trait_name!r}"

    def test_panel_json_contains_kind_bar(self):
        fig, ax = apl.subplots(1, 1)
        p = ax.bar([1, 2, 3])
        trait_name = f"panel_{p._id}_json"
        data = json.loads(getattr(fig, trait_name))
        assert data["kind"] == "bar"

    def test_panel_json_values_after_update(self):
        fig, ax = apl.subplots(1, 1)
        p = ax.bar([1, 2, 3])
        p.update([7, 8, 9])
        trait_name = f"panel_{p._id}_json"
        data = json.loads(getattr(fig, trait_name))
        assert data["values"] == pytest.approx(np.array([[7.0], [8.0], [9.0]]))

    def test_panel_json_color_after_set_color(self):
        fig, ax = apl.subplots(1, 1)
        p = ax.bar([1, 2, 3])
        p.set_color("#112233")
        trait_name = f"panel_{p._id}_json"
        data = json.loads(getattr(fig, trait_name))
        assert data["bar_color"] == "#112233"

    def test_push_without_figure_is_noop(self):
        p = PlotBar([1, 2, 3])
        p._push()

    def test_layout_json_kind_bar(self):
        fig, ax = apl.subplots(1, 1)
        p = ax.bar([10, 20, 30])
        layout = json.loads(fig.layout_json)
        panel_spec = next(s for s in layout["panel_specs"] if s["id"] == p._id)
        assert panel_spec["kind"] == "bar"


# ─────────────────────────────────────────────────────────────────────────────
# 9. Callback API
# ─────────────────────────────────────────────────────────────────────────────

class TestPlotBarCallbacks:

    def test_has_callback_registry(self):
        p = _make_bar()
        assert isinstance(p.callbacks, CallbackRegistry)

    def test_on_click_decorator_returns_fn(self):
        p = _make_bar()
        fn = lambda e: None
        returned = p.on_click(fn)
        assert returned is fn

    def test_on_click_stamps_cid(self):
        p = _make_bar()

        @p.on_click
        def cb(event): pass

        assert hasattr(cb, "_cid") and isinstance(cb._cid, int)

    def test_on_click_fires(self):
        p = _make_bar()
        fired = []

        @p.on_click
        def cb(event): fired.append(event)

        p.callbacks.fire(Event("on_click", p, {"bar_index": 2, "value": 3.0,
                                                "group_index": 0, "group_value": 3.0}))
        assert len(fired) == 1

    def test_on_click_event_data_with_group(self):
        """on_click event carries group_index and group_value."""
        p = _make_bar([10, 20, 30])
        fired = []

        @p.on_click
        def cb(event): fired.append(event)

        p.callbacks.fire(Event("on_click", p,
                               {"bar_index": 1, "value": 20.0,
                                "group_index": 0, "group_value": 20.0,
                                "x_center": 1.0, "x_label": "B"}))
        assert fired[0].bar_index == 1
        assert fired[0].value == pytest.approx(20.0)
        assert fired[0].group_index == 0
        assert fired[0].group_value == pytest.approx(20.0)
        assert fired[0].x_center == pytest.approx(1.0)
        assert fired[0].x_label == "B"

    def test_on_click_grouped_event(self):
        """group_index reflects which group was clicked."""
        fig, ax = apl.subplots(1, 1)
        p = ax.bar(["A", "B"], [[1, 10], [2, 20]])
        fired = []

        @p.on_click
        def cb(event): fired.append(event)

        p.callbacks.fire(Event("on_click", p,
                               {"bar_index": 1, "group_index": 1,
                                "value": 20.0, "group_value": 20.0,
                                "x_center": 1.0, "x_label": "B"}))
        assert fired[0].group_index == 1
        assert fired[0].group_value == pytest.approx(20.0)

    def test_on_changed_fires(self):
        p = _make_bar()
        fired = []

        @p.on_changed
        def cb(event): fired.append(event)

        p.callbacks.fire(Event("on_changed", p, {}))
        assert len(fired) == 1

    def test_on_click_not_fired_by_on_changed(self):
        p = _make_bar()
        fired = []

        @p.on_click
        def cb(event): fired.append(event)

        p.callbacks.fire(Event("on_changed", p, {}))
        assert fired == []

    def test_disconnect(self):
        p = _make_bar()
        fired = []

        @p.on_click
        def cb(event): fired.append(event)

        p.disconnect(cb._cid)
        p.callbacks.fire(Event("on_click", p, {}))
        assert fired == []

    def test_multiple_on_click_handlers(self):
        p = _make_bar()
        log = []

        @p.on_click
        def cb1(event): log.append("a")

        @p.on_click
        def cb2(event): log.append("b")

        p.callbacks.fire(Event("on_click", p, {}))
        assert sorted(log) == ["a", "b"]


# ─────────────────────────────────────────────────────────────────────────────
# 10. Edge cases
# ─────────────────────────────────────────────────────────────────────────────

class TestPlotBarEdgeCases:

    def test_single_bar(self):
        p = _make_bar([42])
        st = _state(p)
        assert len(st["values"]) == 1
        assert st["data_max"] > st["data_min"]

    def test_large_n(self):
        values = list(range(200))
        p = _make_bar(values)
        assert len(_state(p)["values"]) == 200
        assert len(_state(p)["x_centers"]) == 200

    def test_all_negative_values(self):
        p = _make_bar([-5, -3, -1])
        st = _state(p)
        assert st["data_min"] < -5.0
        assert st["data_max"] >= 0.0

    def test_mixed_positive_negative(self):
        p = _make_bar([-10, 0, 10])
        st = _state(p)
        assert st["data_min"] < -10.0
        assert st["data_max"] > 10.0

    def test_float_values(self):
        p = _make_bar([1.1, 2.2, 3.3])
        assert _state(p)["values"] == pytest.approx(np.array([[1.1], [2.2], [3.3]]))

    def test_x_centers_float(self):
        p = _make_bar([1, 2, 3], x_centers=[0.5, 1.5, 2.5])
        assert _state(p)["x_centers"] == pytest.approx([0.5, 1.5, 2.5])

    def test_bar_width_zero_boundary(self):
        p = _make_bar(bar_width=0.0)
        assert _state(p)["bar_width"] == pytest.approx(0.0)

    def test_bar_width_one_boundary(self):
        p = _make_bar(bar_width=1.0)
        assert _state(p)["bar_width"] == pytest.approx(1.0)


# ─────────────────────────────────────────────────────────────────────────────
# 11. Validation errors
# ─────────────────────────────────────────────────────────────────────────────

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

    def test_axes_bar_returns_plotbar_instance(self):
        fig, ax = apl.subplots(1, 1)
        p = ax.bar([1, 2, 3])
        assert isinstance(p, PlotBar)


# ─────────────────────────────────────────────────────────────────────────────
# 12. repr
# ─────────────────────────────────────────────────────────────────────────────

class TestPlotBarRepr:

    def test_repr_contains_n(self):
        p = _make_bar([1, 2, 3, 4])
        assert "n=4" in repr(p)

    def test_repr_contains_orient_v(self):
        p = _make_bar([1, 2, 3])
        assert "orient='v'" in repr(p)

    def test_repr_contains_orient_h(self):
        p = _make_bar([1, 2, 3], orient="h")
        assert "orient='h'" in repr(p)

    def test_repr_is_string(self):
        p = _make_bar()
        assert isinstance(repr(p), str)

    def test_repr_grouped_shows_groups(self):
        fig, ax = apl.subplots(1, 1)
        p = ax.bar([0, 1], [[1, 2], [3, 4]])
        assert "groups=2" in repr(p)
        assert "n=2" in repr(p)


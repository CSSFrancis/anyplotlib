"""
tests/test_plot1d/test_plot1d.py
=================================

Unit tests for Plot1D — covering:

  * _norm_linestyle helper
  * Default state values
  * Construction via Axes.plot() (linestyle, ls shorthand, alpha, marker)
  * Setter methods: set_color, set_linewidth, set_linestyle, set_alpha,
                    set_marker, set_data
  * data property (read-only view)
  * line property returning Line1D
  * add_line() / remove_line() / clear_lines() and Line1D handle
  * add_line() field parity (linestyle/alpha/marker in extra_lines dicts)
  * State-dict round-trip (to_state_dict)
  * Data-range recomputation (data_min / data_max) after overlay changes
  * add_span() / remove_span() / clear_spans()
  * add_vline_widget() / add_hline_widget() / add_range_widget()
  * Widget management: get_widget, remove_widget, list_widgets, clear_widgets
  * Marker helpers: add_points, add_vlines, add_hlines,
                    list_markers, remove_marker, clear_markers
"""
from __future__ import annotations

import numpy as np
import pytest

import anyplotlib as apl
from anyplotlib._utils import _norm_linestyle
from anyplotlib.plot1d import Plot1D
from anyplotlib.plot1d._plot1d import Line1D


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _plot(n: int = 128, **kwargs) -> Plot1D:
    """Create a Plot1D attached to a one-panel Figure with deterministic data."""
    fig, ax = apl.subplots(1, 1)
    data = np.sin(np.linspace(0, 2 * np.pi, n))
    return ax.plot(data, **kwargs)


def _plot_lin(n: int = 32, **kwargs) -> Plot1D:
    """Create a Plot1D with linspace data (useful for range tests)."""
    fig, ax = apl.subplots(1, 1)
    return ax.plot(np.linspace(0.0, 1.0, n), **kwargs)


t = np.linspace(0, 2 * np.pi, 128)


# ===========================================================================
# _norm_linestyle
# ===========================================================================

class TestNormLinestyle:

    def test_canonical_names_round_trip(self):
        for ls in ("solid", "dashed", "dotted", "dashdot"):
            assert _norm_linestyle(ls) == ls

    def test_shorthand_solid(self):
        assert _norm_linestyle("-") == "solid"

    def test_shorthand_dashed(self):
        assert _norm_linestyle("--") == "dashed"

    def test_shorthand_dotted(self):
        assert _norm_linestyle(":") == "dotted"

    def test_shorthand_dashdot(self):
        assert _norm_linestyle("-.") == "dashdot"

    def test_invalid_raises(self):
        with pytest.raises(ValueError, match="Unknown linestyle"):
            _norm_linestyle("loose")

    def test_invalid_empty_raises(self):
        with pytest.raises(ValueError):
            _norm_linestyle("")


# ===========================================================================
# Default state values
# ===========================================================================

class TestPlot1DDefaults:

    def test_linestyle_default(self):
        p = _plot_lin()
        assert p._state["line_linestyle"] == "solid"

    def test_alpha_default(self):
        p = _plot_lin()
        assert p._state["line_alpha"] == 1.0

    def test_marker_default(self):
        p = _plot_lin()
        assert p._state["line_marker"] == "none"

    def test_markersize_default(self):
        p = _plot_lin()
        assert p._state["line_markersize"] == 4.0


# ===========================================================================
# Construction via Axes.plot()
# ===========================================================================

class TestPlot1DConstruction:

    def test_linestyle_dashed(self):
        p = _plot(linestyle="dashed")
        assert p._state["line_linestyle"] == "dashed"

    def test_linestyle_dotted(self):
        p = _plot(linestyle="dotted")
        assert p._state["line_linestyle"] == "dotted"

    def test_linestyle_dashdot(self):
        p = _plot(linestyle="-.")
        assert p._state["line_linestyle"] == "dashdot"

    def test_ls_shorthand(self):
        p = _plot(ls="--")
        assert p._state["line_linestyle"] == "dashed"

    def test_ls_shorthand_takes_precedence_over_linestyle(self):
        p = _plot_lin(linestyle="solid", ls="--")
        assert p._state["line_linestyle"] == "dashed"

    def test_ls_only(self):
        p = _plot_lin(ls=":")
        assert p._state["line_linestyle"] == "dotted"

    def test_alpha_stored(self):
        p = _plot(alpha=0.4)
        assert p._state["line_alpha"] == pytest.approx(0.4)

    def test_marker_stored(self):
        p = _plot(marker="s", markersize=5)
        assert p._state["line_marker"] == "s"
        assert p._state["line_markersize"] == pytest.approx(5.0)

    def test_markersize_stored(self):
        p = _plot_lin(marker="s", markersize=8.0)
        assert p._state["line_markersize"] == pytest.approx(8.0)

    def test_marker_none_string(self):
        p = _plot_lin(marker="none")
        assert p._state["line_marker"] == "none"

    def test_invalid_linestyle_raises(self):
        with pytest.raises(ValueError, match="Unknown linestyle"):
            _plot_lin(linestyle="zigzag")

    def test_all_known_markers(self):
        for sym in ("o", "s", "^", "v", "D", "+", "x", "none"):
            p = _plot_lin(marker=sym)
            assert p._state["line_marker"] == sym


# ===========================================================================
# Setter methods
# ===========================================================================

class TestPlot1DSetters:

    def test_set_color(self):
        p = _plot(color="#4fc3f7")
        p.set_color("#ff7043")
        assert p._state["line_color"] == "#ff7043"

    def test_set_linewidth(self):
        p = _plot()
        p.set_linewidth(3.0)
        assert p._state["line_linewidth"] == pytest.approx(3.0)

    def test_set_linestyle_canonical(self):
        p = _plot_lin()
        p.set_linestyle("dotted")
        assert p._state["line_linestyle"] == "dotted"

    def test_set_linestyle_word(self):
        p = _plot()
        p.set_linestyle("dashed")
        assert p._state["line_linestyle"] == "dashed"

    def test_set_linestyle_shorthand_dashdot(self):
        p = _plot()
        p.set_linestyle("-.")
        assert p._state["line_linestyle"] == "dashdot"

    def test_set_linestyle_shorthand_colon(self):
        p = _plot_lin()
        p.set_linestyle(":")
        assert p._state["line_linestyle"] == "dotted"

    def test_set_linestyle_invalid_raises(self):
        p = _plot_lin()
        with pytest.raises(ValueError):
            p.set_linestyle("bad")

    def test_set_alpha(self):
        p = _plot()
        p.set_alpha(0.5)
        assert p._state["line_alpha"] == pytest.approx(0.5)

    def test_set_marker_with_size(self):
        p = _plot()
        p.set_marker("o", markersize=6)
        assert p._state["line_marker"] == "o"
        assert p._state["line_markersize"] == pytest.approx(6.0)

    def test_set_marker_symbol_only(self):
        p = _plot_lin()
        p.set_marker("D")
        assert p._state["line_marker"] == "D"

    def test_set_marker_no_size_leaves_default(self):
        p = _plot_lin()
        p.set_marker("^")
        assert p._state["line_markersize"] == pytest.approx(4.0)

    def test_set_marker_none_normalised(self):
        p = _plot_lin(marker="o")
        p.set_marker(None)  # type: ignore[arg-type]
        assert p._state["line_marker"] == "none"

    def test_setters_chain_without_error(self):
        """Multiple setter calls in sequence must not raise."""
        p = _plot_lin()
        p.set_color("#aabbcc")
        p.set_linewidth(2.5)
        p.set_linestyle("--")
        p.set_alpha(0.8)
        p.set_marker("o", markersize=6)
        assert p._state["line_linestyle"] == "dashed"
        assert p._state["line_alpha"] == pytest.approx(0.8)
        assert p._state["line_marker"] == "o"

    def test_set_data_replaces_primary(self):
        p = _plot(n=64)
        new_data = np.cos(np.linspace(0, 2 * np.pi, 64))
        p.set_data(new_data)
        np.testing.assert_allclose(p._state["data"], new_data)

    def test_set_data_with_new_x_axis(self):
        p = _plot(n=32)
        y = np.ones(32)
        x = np.linspace(10, 42, 32)
        p.set_data(y, x_axis=x)
        np.testing.assert_allclose(p._state["x_axis"], x)

    def test_set_data_updates_units(self):
        p = _plot()
        p.set_data(np.zeros(128), units="eV")
        assert p._state["units"] == "eV"

    def test_set_data_2d_raises(self):
        p = _plot()
        with pytest.raises(ValueError):
            p.set_data(np.ones((4, 4)))

    def test_data_property_readonly(self):
        p = _plot()
        arr = p.data
        assert not arr.flags.writeable

    def test_line_property_returns_line1d(self):
        p = _plot()
        assert isinstance(p.line, Line1D)
        assert p.line.id is None


# ===========================================================================
# Overlay lines (add_line / remove_line / clear_lines / Line1D handle)
# ===========================================================================

class TestPlot1DOverlayLines:

    def test_add_line_returns_line1d(self):
        p = _plot()
        line = p.add_line(np.cos(t))
        assert isinstance(line, Line1D)
        assert line.id is not None

    def test_add_line_stored_in_extra_lines(self):
        p = _plot()
        p.add_line(np.cos(t), color="#ff7043", label="cos")
        assert len(p._state["extra_lines"]) == 1
        assert p._state["extra_lines"][0]["color"] == "#ff7043"

    def test_add_line_linestyle_alpha_marker(self):
        p = _plot()
        p.add_line(np.cos(t), linestyle="dashed", alpha=0.75, marker="o", markersize=5)
        entry = p._state["extra_lines"][0]
        assert entry["linestyle"] == "dashed"
        assert entry["alpha"] == pytest.approx(0.75)
        assert entry["marker"] == "o"

    def test_add_line_ls_shorthand(self):
        p = _plot()
        p.add_line(np.cos(t), ls=":")
        assert p._state["extra_lines"][0]["linestyle"] == "dotted"

    def test_add_multiple_lines(self):
        p = _plot()
        p.add_line(np.cos(t))
        p.add_line(np.cos(t) * 0.5)
        assert len(p._state["extra_lines"]) == 2

    def test_remove_line_by_id(self):
        p = _plot()
        line = p.add_line(np.cos(t))
        p.remove_line(line.id)
        assert len(p._state["extra_lines"]) == 0

    def test_remove_line_by_line1d(self):
        p = _plot()
        line = p.add_line(np.cos(t))
        p.remove_line(line)
        assert len(p._state["extra_lines"]) == 0

    def test_remove_line_bad_id_raises(self):
        p = _plot()
        with pytest.raises(KeyError):
            p.remove_line("nonexistent")

    def test_clear_lines(self):
        p = _plot()
        p.add_line(np.cos(t))
        p.add_line(np.cos(2 * t))
        p.clear_lines()
        assert p._state["extra_lines"] == []

    def test_line1d_set_data(self):
        p = _plot()
        line = p.add_line(np.cos(t))
        new_y = np.zeros(128)
        line.set_data(new_y)
        entry = next(e for e in p._state["extra_lines"] if e["id"] == line.id)
        np.testing.assert_allclose(entry["data"], new_y)

    def test_line1d_set_data_primary_raises(self):
        p = _plot()
        primary = Line1D(p, None)
        with pytest.raises(ValueError, match="primary line"):
            primary.set_data(np.zeros(10))

    def test_line1d_set_data_bad_id_raises(self):
        p = _plot()
        phantom = Line1D(p, "deadbeef")
        with pytest.raises(KeyError):
            phantom.set_data(np.zeros(128))

    def test_line1d_remove(self):
        p = _plot()
        line = p.add_line(np.cos(t))
        line.remove()
        assert len(p._state["extra_lines"]) == 0

    def test_line1d_remove_primary_raises(self):
        p = _plot()
        primary = Line1D(p, None)
        with pytest.raises(ValueError):
            primary.remove()

    def test_line1d_eq_str(self):
        p = _plot()
        line = p.add_line(np.cos(t))
        assert line == line.id
        assert not (line == "other")

    def test_line1d_hash(self):
        p = _plot()
        line = p.add_line(np.cos(t))
        d = {line: "val"}
        assert d[line] == "val"

    def test_line1d_str(self):
        p = _plot()
        line = p.add_line(np.cos(t))
        assert str(line) == line.id


# ===========================================================================
# Secondary (right-hand) y-axis / twinx
# ===========================================================================

class TestPlot1DTwinx:

    def test_right_axis_off_by_default(self):
        p = _plot()
        assert p._state["right_axis"] is False

    def test_add_right_axis_enables_and_sets_color(self):
        p = _plot()
        p.add_right_axis(color="#e05a2b")
        assert p._state["right_axis"] is True
        assert p._state["right_axis_color"] == "#e05a2b"

    def test_add_line_right_sets_axis_field(self):
        p = _plot()
        p.add_right_axis()
        p.add_line(np.cos(t) * 100, axis="right")
        assert p._state["extra_lines"][-1]["axis"] == "right"

    def test_add_line_right_implies_right_axis(self):
        p = _plot()
        p.add_line(np.cos(t) * 100, axis="right")  # no explicit add_right_axis
        assert p._state["right_axis"] is True

    def test_add_line_default_axis_is_left(self):
        p = _plot()
        p.add_line(np.cos(t))
        assert p._state["extra_lines"][-1]["axis"] == "left"

    def test_add_line_bad_axis_raises(self):
        p = _plot()
        with pytest.raises(ValueError, match="axis must be"):
            p.add_line(np.cos(t), axis="top")

    def test_right_line_excluded_from_left_range(self):
        """A large-scale right line must not stretch the left y-range."""
        p = _plot()  # sine, roughly -1..1
        left_max_before = p._state["data_max"]
        p.add_line(np.full(128, 1000.0), axis="right")
        # left range unchanged (right line does not participate)
        assert p._state["data_max"] == pytest.approx(left_max_before)

    def test_right_range_auto_from_right_lines(self):
        p = _plot()
        p.add_line(np.linspace(0.0, 500.0, 128), axis="right")
        assert p._state["right_data_min"] < 50.0
        assert p._state["right_data_max"] > 450.0

    def test_set_right_ylim_overrides_auto(self):
        p = _plot()
        p.add_line(np.linspace(0.0, 500.0, 128), axis="right")
        p.set_right_ylim(0.0, 100.0)
        assert p.get_right_ylim() == (0.0, 100.0)

    def test_set_right_ylabel(self):
        p = _plot()
        p.add_right_axis()
        p.set_right_ylabel("Temp (K)")
        assert p._state["right_y_units"] == "Temp (K)"

    def test_remove_right_axis_drops_right_lines(self):
        p = _plot()
        p.add_line(np.cos(t), axis="left")
        p.add_line(np.cos(t) * 100, axis="right")
        p.remove_right_axis()
        assert p._state["right_axis"] is False
        # left line survives; right line removed
        axes = [e.get("axis", "left") for e in p._state["extra_lines"]]
        assert axes == ["left"]

    def test_axis_field_survives_wire(self):
        p = _plot()
        p.add_line(np.cos(t) * 100, axis="right")
        wire = p.to_state_dict()
        assert wire["extra_lines"][-1]["axis"] == "right"
        assert wire["right_axis"] is True


# ===========================================================================
# add_line() field parity
# ===========================================================================

class TestAddLineParity:

    def _extra(self, **kwargs) -> dict:
        p = _plot_lin()
        p.add_line(np.ones(32), **kwargs)
        return p._state["extra_lines"][0]

    def test_default_linestyle(self):
        assert self._extra()["linestyle"] == "solid"

    def test_linestyle_stored(self):
        assert self._extra(linestyle="dashed")["linestyle"] == "dashed"

    def test_ls_shorthand(self):
        assert self._extra(ls=":")["linestyle"] == "dotted"

    def test_ls_overrides_linestyle(self):
        assert self._extra(linestyle="solid", ls="--")["linestyle"] == "dashed"

    def test_default_alpha(self):
        assert self._extra()["alpha"] == pytest.approx(1.0)

    def test_alpha_stored(self):
        assert self._extra(alpha=0.4)["alpha"] == pytest.approx(0.4)

    def test_default_marker(self):
        assert self._extra()["marker"] == "none"

    def test_marker_stored(self):
        ex = self._extra(marker="o", markersize=6.0)
        assert ex["marker"] == "o"
        assert ex["markersize"] == pytest.approx(6.0)

    def test_invalid_linestyle_raises(self):
        p = _plot_lin()
        with pytest.raises(ValueError):
            p.add_line(np.ones(32), linestyle="bad")

    def test_multiple_extra_lines_independent(self):
        p = _plot_lin()
        p.add_line(np.ones(32), linestyle="dashed", alpha=0.5)
        p.add_line(np.ones(32), linestyle="dotted", alpha=0.8)
        assert p._state["extra_lines"][0]["linestyle"] == "dashed"
        assert p._state["extra_lines"][1]["linestyle"] == "dotted"
        assert p._state["extra_lines"][0]["alpha"] == pytest.approx(0.5)
        assert p._state["extra_lines"][1]["alpha"] == pytest.approx(0.8)


# ===========================================================================
# State-dict round-trip (to_state_dict)
# ===========================================================================

class TestStateDict:

    def test_primary_keys_present(self):
        p = _plot_lin(linestyle="dotted", alpha=0.7, marker="s", markersize=5.0)
        sd = p.to_state_dict()
        assert sd["line_linestyle"] == "dotted"
        assert sd["line_alpha"] == pytest.approx(0.7)
        assert sd["line_marker"] == "s"
        assert sd["line_markersize"] == pytest.approx(5.0)

    def test_extra_line_keys_present(self):
        p = _plot_lin()
        p.add_line(np.zeros(32), linestyle="dashdot", alpha=0.6, marker="D")
        sd = p.to_state_dict()
        ex = sd["extra_lines"][0]
        assert ex["linestyle"] == "dashdot"
        assert ex["alpha"] == pytest.approx(0.6)
        assert ex["marker"] == "D"


# ===========================================================================
# Data-range recomputation
# ===========================================================================

class TestDataRangeRecompute:
    """data_min/data_max must always cover all visible lines."""

    def test_add_line_expands_range_upward(self):
        p = _plot_lin()
        primary_max = p._state["data_max"]
        p.add_line(np.full(32, 5.0))
        assert p._state["data_max"] > primary_max
        assert p._state["data_max"] >= 5.0

    def test_add_line_expands_range_downward(self):
        p = _plot_lin()
        primary_min = p._state["data_min"]
        p.add_line(np.full(32, -5.0))
        assert p._state["data_min"] < primary_min
        assert p._state["data_min"] <= -5.0

    def test_add_line_both_directions(self):
        p = _plot_lin()
        p.add_line(np.full(32, 10.0))
        p.add_line(np.full(32, -10.0))
        assert p._state["data_max"] >= 10.0
        assert p._state["data_min"] <= -10.0

    def test_remove_line_shrinks_range(self):
        p = _plot_lin()
        lid = p.add_line(np.full(32, 100.0))
        assert p._state["data_max"] >= 100.0
        p.remove_line(lid)
        assert p._state["data_max"] < 10.0

    def test_clear_lines_restores_primary_range(self):
        p = _plot_lin()
        original_min = p._state["data_min"]
        original_max = p._state["data_max"]
        p.add_line(np.full(32, 50.0))
        p.add_line(np.full(32, -50.0))
        p.clear_lines()
        assert p._state["data_min"] == pytest.approx(original_min)
        assert p._state["data_max"] == pytest.approx(original_max)

    def test_range_includes_padding(self):
        """5 % padding must be applied after recompute."""
        p = _plot_lin()
        p.add_line(np.zeros(32) + 3.0)
        assert p._state["data_max"] >= 3.0 * 1.05 - 0.01

    def test_overlay_within_bounds_does_not_change_range(self):
        p = _plot_lin()
        pre_min = p._state["data_min"]
        pre_max = p._state["data_max"]
        p.add_line(np.full(32, 0.5))
        assert p._state["data_min"] == pytest.approx(pre_min)
        assert p._state["data_max"] == pytest.approx(pre_max)

    def test_sin_overlay_expands_max(self):
        p = _plot()
        old_max = p._state["data_max"]
        p.add_line(np.sin(t) + 5)
        assert p._state["data_max"] > old_max


# ===========================================================================
# Spans
# ===========================================================================

class TestPlot1DSpans:

    def test_add_span_returns_id(self):
        p = _plot()
        sid = p.add_span(1.0, 2.0)
        assert isinstance(sid, str)
        assert len(p._state["spans"]) == 1

    def test_add_span_y_axis(self):
        p = _plot()
        p.add_span(0.5, 0.8, axis="y", color="#ff0000")
        assert p._state["spans"][0]["axis"] == "y"

    def test_remove_span(self):
        p = _plot()
        sid = p.add_span(1.0, 2.0)
        p.remove_span(sid)
        assert p._state["spans"] == []

    def test_remove_span_bad_id_raises(self):
        p = _plot()
        with pytest.raises(KeyError):
            p.remove_span("nonexistent")

    def test_clear_spans(self):
        p = _plot()
        p.add_span(1.0, 2.0)
        p.add_span(3.0, 4.0)
        p.clear_spans()
        assert p._state["spans"] == []


# ===========================================================================
# Widgets
# ===========================================================================

class TestPlot1DWidgets:

    def test_add_vline_widget(self):
        p = _plot()
        w = p.add_vline_widget(1.5, color="#ff6e40")
        assert w is not None
        assert len(p._widgets) == 1

    def test_add_hline_widget(self):
        p = _plot()
        p.add_hline_widget(0.5)
        assert len(p._widgets) == 1

    def test_add_range_widget(self):
        p = _plot()
        p.add_range_widget(1.0, 3.0)
        assert len(p._widgets) == 1

    def test_get_widget_by_id(self):
        p = _plot()
        w = p.add_vline_widget(1.0)
        assert p.get_widget(w.id) is w

    def test_get_widget_by_widget(self):
        p = _plot()
        w = p.add_vline_widget(1.0)
        assert p.get_widget(w) is w

    def test_get_widget_missing_raises(self):
        p = _plot()
        with pytest.raises(KeyError):
            p.get_widget("bad_id")

    def test_remove_widget(self):
        p = _plot()
        w = p.add_vline_widget(1.0)
        p.remove_widget(w)
        assert len(p._widgets) == 0

    def test_remove_widget_missing_raises(self):
        p = _plot()
        with pytest.raises(KeyError):
            p.remove_widget("bad_id")

    def test_list_widgets(self):
        p = _plot()
        p.add_vline_widget(1.0)
        p.add_hline_widget(0.5)
        assert len(p.list_widgets()) == 2

    def test_clear_widgets(self):
        p = _plot()
        p.add_vline_widget(1.0)
        p.add_hline_widget(0.5)
        p.clear_widgets()
        assert p.list_widgets() == []


# ===========================================================================
# Marker helpers
# ===========================================================================

class TestPlot1DMarkerHelpers:

    def test_add_points_with_facecolors(self):
        p = _plot()
        offsets = np.column_stack([[1.0, 2.0], [0.5, 0.8]])
        p.add_points(offsets, name="peaks", sizes=7,
                     color="#ff1744", facecolors="#ff174433")
        wl = p.markers.to_wire_list()
        assert any(w["type"] == "points" for w in wl)

    def test_list_markers_count(self):
        p = _plot()
        offsets = np.column_stack([[1.0, 2.0, 3.0], [0.1, 0.2, 0.3]])
        p.add_points(offsets, name="pts")
        info = p.list_markers()
        assert any(d["name"] == "pts" and d["n"] == 3 for d in info)

    def test_remove_marker(self):
        p = _plot()
        p.add_vlines([1.0, 2.0], name="m")
        p.remove_marker("vlines", "m")
        assert p.markers.to_wire_list() == []

    def test_clear_markers(self):
        p = _plot()
        p.add_vlines([1.0], name="v")
        p.add_hlines([0.5], name="h")
        p.clear_markers()
        assert p.markers.to_wire_list() == []


# ===========================================================================
# Phase 2 — Plot1D state methods
# ===========================================================================

class TestPlot1DProperties:

    def test_color_property(self):
        p = _plot(color="#ff0000")
        assert p.color == "#ff0000"

    def test_x_property_returns_ndarray(self):
        p = _plot_lin(32)
        x = p.x
        assert isinstance(x, np.ndarray)
        assert len(x) == 32

    def test_y_property_returns_ndarray(self):
        data = np.linspace(0.0, 1.0, 64)
        fig, ax = apl.subplots(1, 1)
        p = ax.plot(data)
        y = p.y
        assert isinstance(y, np.ndarray)
        assert len(y) == 64


class TestPlot1DLabels:

    def test_set_xlabel_updates_units(self):
        p = _plot()
        p.set_xlabel("Energy (eV)")
        assert p._state["units"] == "Energy (eV)"

    def test_set_ylabel_updates_y_units(self):
        p = _plot()
        p.set_ylabel("Counts")
        assert p._state["y_units"] == "Counts"

    def test_set_title(self):
        p = _plot()
        p.set_title("Spectrum")
        assert p._state["title"] == "Spectrum"

    def test_default_title_empty(self):
        p = _plot()
        assert p._state["title"] == ""


class TestPlot1DAxisLimits:

    def test_set_xlim_changes_view(self):
        p = _plot_lin(64)
        p.set_xlim(10, 50)
        assert p._state["view_x0"] != 0.0 or p._state["view_x1"] != 1.0

    def test_set_ylim_stores_y_range(self):
        p = _plot()
        p.set_ylim(-2.0, 2.0)
        assert p._state["y_range"] == [-2.0, 2.0]

    def test_get_ylim_returns_data_bounds(self):
        data = np.array([0.0, 1.0, 2.0, 3.0, 4.0])
        fig, ax = apl.subplots(1, 1)
        p = ax.plot(data)
        lo, hi = p.get_ylim()
        assert lo < hi
        assert lo <= 0.0
        assert hi >= 4.0

    def test_get_xbound_returns_x_range(self):
        p = _plot_lin(32)
        lo, hi = p.get_xbound()
        assert lo == pytest.approx(0.0)
        assert hi == pytest.approx(31.0)


class TestPlot1DAxisVisibility:

    def test_set_axis_off(self):
        p = _plot()
        assert p._state["axis_visible"] is True
        p.set_axis_off()
        assert p._state["axis_visible"] is False

    def test_set_ticks_visible_false(self):
        p = _plot()
        p.set_ticks_visible(False)
        assert p._state["x_ticks_visible"] is False
        assert p._state["y_ticks_visible"] is False

    def test_set_ticks_visible_per_axis(self):
        p = _plot()
        p.set_ticks_visible(False, x=True, y=False)
        assert p._state["x_ticks_visible"] is True
        assert p._state["y_ticks_visible"] is False


# ===========================================================================
# Phase 5 — step-mid linestyle + semilogy / yscale
# ===========================================================================

class TestNormLinestyleStepMid:

    def test_step_mid_accepted(self):
        from anyplotlib._utils import _norm_linestyle
        assert _norm_linestyle("step-mid") == "step-mid"

    def test_steps_mid_alias(self):
        from anyplotlib._utils import _norm_linestyle
        assert _norm_linestyle("steps-mid") == "step-mid"

    def test_step_mid_stored_in_state(self):
        fig, ax = apl.subplots(1, 1)
        p = ax.plot(np.zeros(16), linestyle="step-mid")
        assert p._state["line_linestyle"] == "step-mid"

    def test_step_mid_via_set_linestyle(self):
        p = _plot()
        p.set_linestyle("step-mid")
        assert p._state["line_linestyle"] == "step-mid"


class TestSemilogy:

    def test_semilogy_sets_yscale_log(self):
        fig, ax = apl.subplots(1, 1)
        p = ax.semilogy(np.logspace(0, 3, 64))
        assert p._state["yscale"] == "log"

    def test_yscale_stored_in_state(self):
        fig, ax = apl.subplots(1, 1)
        p = ax.plot(np.zeros(16), yscale="log")
        assert p._state["yscale"] == "log"

    def test_yscale_default_is_linear(self):
        p = _plot()
        assert p._state["yscale"] == "linear"

    def test_semilogy_passes_kwargs(self):
        fig, ax = apl.subplots(1, 1)
        p = ax.semilogy(np.ones(16), color="#ff0000")
        assert p._state["line_color"] == "#ff0000"
        assert p._state["yscale"] == "log"


# ===========================================================================
# set_ylim / get_ylim
# ===========================================================================

class TestSetGetYlim:
    def test_get_ylim_default_returns_data_bounds(self):
        p = _plot()
        lo, hi = p.get_ylim()
        assert lo == pytest.approx(p._state["data_min"])
        assert hi == pytest.approx(p._state["data_max"])

    def test_set_ylim_stored_in_state(self):
        p = _plot()
        p.set_ylim(-2.0, 5.0)
        assert p._state["y_range"] == [-2.0, 5.0]

    def test_get_ylim_after_set_ylim(self):
        p = _plot()
        p.set_ylim(-1.5, 3.0)
        lo, hi = p.get_ylim()
        assert lo == pytest.approx(-1.5)
        assert hi == pytest.approx(3.0)

    def test_y_range_not_cleared_by_reset_view(self):
        p = _plot()
        p.set_ylim(-1.0, 1.0)
        p.reset_view()
        lo, hi = p.get_ylim()
        assert lo == pytest.approx(-1.0)
        assert hi == pytest.approx(1.0)

    def test_y_range_in_state_dict(self):
        p = _plot()
        p.set_ylim(0.0, 10.0)
        assert p.to_state_dict()["y_range"] == [0.0, 10.0]

    def test_y_range_none_by_default(self):
        assert _plot()._state["y_range"] is None

    def test_y_range_propagated_to_state_dict(self):
        p = _plot()
        p.set_ylim(-5.0, 5.0)
        assert p.to_state_dict()["y_range"] == [-5.0, 5.0]

    def test_markers_state_dict_contains_y_range(self):
        p = _plot()
        p.set_ylim(0.0, 10.0)
        assert p.to_state_dict()["y_range"] == [0.0, 10.0]


# ===========================================================================
# get_xlim
# ===========================================================================

class TestGetXlim:
    def test_get_xlim_full_view(self):
        fig, ax = apl.subplots(1, 1)
        x = np.linspace(0.0, 10.0, 64)
        p = ax.plot(np.sin(x), axes=[x])
        lo, hi = p.get_xlim()
        assert lo == pytest.approx(0.0, abs=0.01)
        assert hi == pytest.approx(10.0, abs=0.01)

    def test_get_xlim_after_set_xlim(self):
        fig, ax = apl.subplots(1, 1)
        x = np.linspace(0.0, 10.0, 64)
        p = ax.plot(np.sin(x), axes=[x])
        p.set_xlim(2.0, 8.0)
        lo, hi = p.get_xlim()
        assert lo == pytest.approx(2.0, abs=0.1)
        assert hi == pytest.approx(8.0, abs=0.1)

    def test_get_xlim_default_x_axis(self):
        p = _plot_lin(n=100)
        lo, hi = p.get_xlim()
        assert lo == pytest.approx(0.0, abs=0.01)
        assert hi == pytest.approx(99.0, abs=0.01)


# ===========================================================================
# _view_from_python flag
# ===========================================================================

class TestViewFromPython:
    def test_initial_view_from_python_false(self):
        assert _plot()._state["_view_from_python"] is False

    def test_set_view_clears_flag_after_push(self):
        p = _plot()
        p.set_view(x0=0.2, x1=0.8)
        assert p._state["_view_from_python"] is False

    def test_reset_view_clears_flag_after_push(self):
        p = _plot()
        p.set_view(x0=0.2, x1=0.8)
        p.reset_view()
        assert p._state["_view_from_python"] is False

    def test_set_xlim_clears_flag_after_push(self):
        fig, ax = apl.subplots(1, 1)
        x = np.linspace(0, 10, 64)
        p = ax.plot(np.sin(x), axes=[x])
        p.set_xlim(2.0, 8.0)
        assert p._state["_view_from_python"] is False
        assert p._state["view_x0"] != 0.0 or p._state["view_x1"] != 1.0

    def test_view_from_python_present_in_state_dict(self):
        p = _plot()
        p.set_view(x0=0.1, x1=0.9)
        sd = p.to_state_dict()
        assert "_view_from_python" in sd
        assert sd["_view_from_python"] is False


# ===========================================================================
# add_line default color
# ===========================================================================

class TestAddLineDefaultColor:
    def test_default_color_is_not_white(self):
        import inspect
        p = _plot()
        default = inspect.signature(p.add_line).parameters["color"].default
        assert default != "#ffffff"
        assert default == "#4fc3f7"

    def test_add_line_uses_default_color_in_state(self):
        p = _plot()
        p.add_line(np.linspace(-1, 1, 128))
        assert p._state["extra_lines"][-1]["color"] == "#4fc3f7"



# ===========================================================================
# set_axis_on (Plot1D)
# ===========================================================================

class TestSetAxisOnPlot1D:
    def test_set_axis_on_restores(self):
        p = _plot()
        p.set_axis_off()
        assert p._state["axis_visible"] is False
        p.set_axis_on()
        assert p._state["axis_visible"] is True

    def test_set_axis_on_default_state(self):
        p = _plot()
        p.set_axis_on()
        assert p._state["axis_visible"] is True


# ===========================================================================
# M4: set_yscale on Plot1D
# ===========================================================================

class TestSetYscale:
    def test_set_yscale_log(self):
        p = _plot()
        p.set_yscale("log")
        assert p._state["yscale"] == "log"

    def test_set_yscale_linear(self):
        p = _plot()
        p.set_yscale("log")
        p.set_yscale("linear")
        assert p._state["yscale"] == "linear"

    def test_set_yscale_invalid(self):
        p = _plot()
        with pytest.raises(ValueError):
            p.set_yscale("symlog")


# ===========================================================================
# m2: configure_pointer_settled public on Plot1D
# ===========================================================================

class TestPlot1DConfigurePointerSettled:
    def test_public_method_exists(self):
        p = _plot()
        assert hasattr(p, "configure_pointer_settled")
        assert callable(p.configure_pointer_settled)

    def test_sets_state(self):
        p = _plot()
        p.configure_pointer_settled(200, 5)
        assert p._state["pointer_settled_ms"] == 200
        assert p._state["pointer_settled_delta"] == 5


# ===========================================================================
# m3: direct tests for set_title/xlabel/ylabel and set_axis_on on Plot1D
# ===========================================================================

class TestPlot1DDisplayMethods:
    def test_set_title(self):
        p = _plot()
        p.set_title("My Plot")
        assert p._state["title"] == "My Plot"

    def test_set_xlabel(self):
        p = _plot()
        p.set_xlabel("Time (s)")
        assert p._state["units"] == "Time (s)"

    def test_set_ylabel(self):
        p = _plot()
        p.set_ylabel("Amplitude")
        assert p._state["y_units"] == "Amplitude"

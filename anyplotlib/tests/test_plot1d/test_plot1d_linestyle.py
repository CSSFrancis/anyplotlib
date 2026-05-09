"""
tests/test_plot1d_linestyle.py
==============================

Unit tests for the new Plot1D line-style parameters:
  * linestyle / ls — dash pattern
  * alpha          — line opacity
  * marker / markersize — per-point symbols

Tests cover:
  - _norm_linestyle helper
  - Plot1D._state storage for all new params
  - Axes.plot() forwarding (including ``ls`` shorthand)
  - Setter methods (set_color, set_linewidth, set_linestyle, set_alpha, set_marker)
  - add_line() parity (new fields present in extra_lines dicts)
  - Edge cases: invalid linestyle, marker=None normalised to "none"
"""
from __future__ import annotations

import numpy as np
import pytest

import anyplotlib as apl
from anyplotlib.figure_plots import _norm_linestyle, Plot1D


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _plot(**kwargs) -> Plot1D:
    """Create a Plot1D via Axes.plot() with deterministic data."""
    fig, ax = apl.subplots(1, 1)
    return ax.plot(np.linspace(0.0, 1.0, 32), **kwargs)


# ===========================================================================
# _norm_linestyle
# ===========================================================================

class TestNormLinestyle:
    def test_canonical_names_round_trip(self):
        for ls in ("solid", "dashed", "dotted", "dashdot"):
            assert _norm_linestyle(ls) == ls

    def test_shorthand_dash(self):
        assert _norm_linestyle("-") == "solid"

    def test_shorthand_double_dash(self):
        assert _norm_linestyle("--") == "dashed"

    def test_shorthand_colon(self):
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
# Plot1D._state — defaults
# ===========================================================================

class TestPlot1DDefaults:
    def test_linestyle_default(self):
        p = _plot()
        assert p._state["line_linestyle"] == "solid"

    def test_alpha_default(self):
        p = _plot()
        assert p._state["line_alpha"] == 1.0

    def test_marker_default(self):
        p = _plot()
        assert p._state["line_marker"] == "none"

    def test_markersize_default(self):
        p = _plot()
        assert p._state["line_markersize"] == 4.0


# ===========================================================================
# Plot1D._state — construction via Axes.plot()
# ===========================================================================

class TestAxesPlotForwarding:
    def test_linestyle_stored(self):
        p = _plot(linestyle="dashed")
        assert p._state["line_linestyle"] == "dashed"

    def test_ls_shorthand_takes_precedence(self):
        # ls= should win over linestyle= when both are given
        p = _plot(linestyle="solid", ls="--")
        assert p._state["line_linestyle"] == "dashed"

    def test_ls_only(self):
        p = _plot(ls=":")
        assert p._state["line_linestyle"] == "dotted"

    def test_alpha_stored(self):
        p = _plot(alpha=0.5)
        assert p._state["line_alpha"] == pytest.approx(0.5)

    def test_marker_stored(self):
        p = _plot(marker="o")
        assert p._state["line_marker"] == "o"

    def test_markersize_stored(self):
        p = _plot(marker="s", markersize=8.0)
        assert p._state["line_markersize"] == pytest.approx(8.0)

    def test_marker_none_string(self):
        p = _plot(marker="none")
        assert p._state["line_marker"] == "none"

    def test_invalid_linestyle_raises(self):
        with pytest.raises(ValueError, match="Unknown linestyle"):
            _plot(linestyle="zigzag")

    def test_all_known_markers(self):
        for sym in ("o", "s", "^", "v", "D", "+", "x", "none"):
            p = _plot(marker=sym)
            assert p._state["line_marker"] == sym


# ===========================================================================
# Setter methods
# ===========================================================================

class TestSetters:
    def test_set_color(self):
        p = _plot()
        p.set_color("#ff0000")
        assert p._state["line_color"] == "#ff0000"

    def test_set_linewidth(self):
        p = _plot()
        p.set_linewidth(3.0)
        assert p._state["line_linewidth"] == pytest.approx(3.0)

    def test_set_linestyle_canonical(self):
        p = _plot()
        p.set_linestyle("dotted")
        assert p._state["line_linestyle"] == "dotted"

    def test_set_linestyle_shorthand(self):
        p = _plot()
        p.set_linestyle(":")
        assert p._state["line_linestyle"] == "dotted"

    def test_set_linestyle_invalid_raises(self):
        p = _plot()
        with pytest.raises(ValueError):
            p.set_linestyle("bad")

    def test_set_alpha(self):
        p = _plot()
        p.set_alpha(0.3)
        assert p._state["line_alpha"] == pytest.approx(0.3)

    def test_set_marker_symbol(self):
        p = _plot()
        p.set_marker("D")
        assert p._state["line_marker"] == "D"

    def test_set_marker_with_size(self):
        p = _plot()
        p.set_marker("s", markersize=10.0)
        assert p._state["line_marker"] == "s"
        assert p._state["line_markersize"] == pytest.approx(10.0)

    def test_set_marker_no_size_leaves_default(self):
        p = _plot()
        p.set_marker("^")
        assert p._state["line_markersize"] == pytest.approx(4.0)

    def test_set_marker_none_normalised(self):
        p = _plot(marker="o")
        p.set_marker(None)  # type: ignore[arg-type]
        assert p._state["line_marker"] == "none"

    def test_setters_chain_without_error(self):
        """Multiple setter calls in sequence must not raise."""
        p = _plot()
        p.set_color("#aabbcc")
        p.set_linewidth(2.5)
        p.set_linestyle("--")
        p.set_alpha(0.8)
        p.set_marker("o", markersize=6)
        assert p._state["line_linestyle"] == "dashed"
        assert p._state["line_alpha"] == pytest.approx(0.8)
        assert p._state["line_marker"] == "o"


# ===========================================================================
# add_line() parity
# ===========================================================================

class TestAddLineParity:
    def _extra(self, **kwargs) -> dict:
        p = _plot()
        p.add_line(np.ones(32), **kwargs)
        return p._state["extra_lines"][0]

    def test_default_linestyle(self):
        ex = self._extra()
        assert ex["linestyle"] == "solid"

    def test_linestyle_stored(self):
        ex = self._extra(linestyle="dashed")
        assert ex["linestyle"] == "dashed"

    def test_ls_shorthand(self):
        ex = self._extra(ls=":")
        assert ex["linestyle"] == "dotted"

    def test_ls_overrides_linestyle(self):
        ex = self._extra(linestyle="solid", ls="--")
        assert ex["linestyle"] == "dashed"

    def test_default_alpha(self):
        ex = self._extra()
        assert ex["alpha"] == pytest.approx(1.0)

    def test_alpha_stored(self):
        ex = self._extra(alpha=0.4)
        assert ex["alpha"] == pytest.approx(0.4)

    def test_default_marker(self):
        ex = self._extra()
        assert ex["marker"] == "none"

    def test_marker_stored(self):
        ex = self._extra(marker="o", markersize=6.0)
        assert ex["marker"] == "o"
        assert ex["markersize"] == pytest.approx(6.0)

    def test_invalid_linestyle_raises(self):
        p = _plot()
        with pytest.raises(ValueError):
            p.add_line(np.ones(32), linestyle="bad")

    def test_multiple_extra_lines_independent(self):
        p = _plot()
        p.add_line(np.ones(32), linestyle="dashed", alpha=0.5)
        p.add_line(np.ones(32), linestyle="dotted", alpha=0.8)
        assert p._state["extra_lines"][0]["linestyle"] == "dashed"
        assert p._state["extra_lines"][1]["linestyle"] == "dotted"
        assert p._state["extra_lines"][0]["alpha"] == pytest.approx(0.5)
        assert p._state["extra_lines"][1]["alpha"] == pytest.approx(0.8)


# ===========================================================================
# State dict completeness (to_state_dict round-trip)
# ===========================================================================

class TestStateDict:
    def test_new_keys_present_in_to_state_dict(self):
        p = _plot(linestyle="dotted", alpha=0.7, marker="s", markersize=5.0)
        sd = p.to_state_dict()
        assert sd["line_linestyle"] == "dotted"
        assert sd["line_alpha"] == pytest.approx(0.7)
        assert sd["line_marker"] == "s"
        assert sd["line_markersize"] == pytest.approx(5.0)

    def test_extra_line_new_keys_present(self):
        p = _plot()
        p.add_line(np.zeros(32), linestyle="dashdot", alpha=0.6, marker="D")
        sd = p.to_state_dict()
        ex = sd["extra_lines"][0]
        assert ex["linestyle"] == "dashdot"
        assert ex["alpha"] == pytest.approx(0.6)
        assert ex["marker"] == "D"


# ===========================================================================
# Data range recomputation
# ===========================================================================

class TestDataRangeRecompute:
    """data_min/data_max must always cover all visible lines."""

    def test_add_line_expands_range_upward(self):
        """Overlay line with larger values must push data_max up."""
        p = _plot()          # primary: linspace(0, 1, 32) → max ≈ 1
        primary_max = p._state["data_max"]
        p.add_line(np.full(32, 5.0))   # far above primary
        assert p._state["data_max"] > primary_max
        assert p._state["data_max"] >= 5.0

    def test_add_line_expands_range_downward(self):
        """Overlay line with smaller values must push data_min down."""
        p = _plot()          # primary: linspace(0, 1, 32) → min ≈ 0
        primary_min = p._state["data_min"]
        p.add_line(np.full(32, -5.0))  # far below primary
        assert p._state["data_min"] < primary_min
        assert p._state["data_min"] <= -5.0

    def test_add_line_both_directions(self):
        """Range must encompass all added lines simultaneously."""
        p = _plot()
        p.add_line(np.full(32, 10.0))
        p.add_line(np.full(32, -10.0))
        assert p._state["data_max"] >= 10.0
        assert p._state["data_min"] <= -10.0

    def test_remove_line_shrinks_range(self):
        """Removing the outlier line must restore a tighter range."""
        p = _plot()                              # primary: [0, 1]
        lid = p.add_line(np.full(32, 100.0))    # pushes max to ≥100
        assert p._state["data_max"] >= 100.0
        p.remove_line(lid)
        # After removal the range should be based on primary data only
        assert p._state["data_max"] < 10.0      # well below 100

    def test_clear_lines_restores_primary_range(self):
        """clear_lines must revert the range to the primary line only."""
        p = _plot()
        original_min = p._state["data_min"]
        original_max = p._state["data_max"]
        p.add_line(np.full(32, 50.0))
        p.add_line(np.full(32, -50.0))
        p.clear_lines()
        assert p._state["data_min"] == pytest.approx(original_min)
        assert p._state["data_max"] == pytest.approx(original_max)

    def test_range_includes_padding(self):
        """5 % padding must be applied after recompute, same as construction."""
        p = _plot()          # primary min=0, max=1 → padded to (-0.05, 1.05)
        p.add_line(np.zeros(32) + 3.0)   # new max = 3
        # padding = (3 - 0) * 0.05 = 0.15 → data_max ≥ 3.15
        assert p._state["data_max"] >= 3.0 * 1.05 - 0.01

    def test_primary_only_range_unchanged_when_overlay_within_bounds(self):
        """An overlay that fits inside the primary range must not change the range."""
        p = _plot()   # primary covers [0, 1] with padding
        pre_min = p._state["data_min"]
        pre_max = p._state["data_max"]
        p.add_line(np.full(32, 0.5))   # well inside existing range
        assert p._state["data_min"] == pytest.approx(pre_min)
        assert p._state["data_max"] == pytest.approx(pre_max)



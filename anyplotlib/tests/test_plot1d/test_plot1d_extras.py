"""
tests/test_plot1d_extras.py
============================

Additional tests for Plot1D — focusing on features exercised in the
Examples/plot_spectra1d.py and Examples/plot_line_styles.py galleries but
not yet covered by the existing test_plot1d_linestyle.py.

Covers:
  * add_line() with linestyle / alpha / marker / ls shorthand
  * remove_line() / clear_lines()
  * Line1D.set_data() / Line1D.remove()
  * add_span() / remove_span() / clear_spans()
  * add_vline_widget() / add_hline_widget() / add_range_widget()
  * Widget management: get_widget, remove_widget, list_widgets, clear_widgets
  * set_color, set_linewidth, set_linestyle, set_alpha, set_marker, set_data
  * data property (read-only view)
  * Primary-line Line1D.set_data raises
  * Primary-line Line1D.remove raises
  * line property returns Line1D(id=None)
  * list_markers / remove_marker / clear_markers
"""
from __future__ import annotations

import numpy as np
import pytest

import anyplotlib as apl
from anyplotlib.figure_plots import Line1D, Plot1D


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _plot(n=128, **kwargs) -> Plot1D:
    fig, ax = apl.subplots(1, 1)
    data = np.sin(np.linspace(0, 2 * np.pi, n))
    return ax.plot(data, **kwargs)


t = np.linspace(0, 2 * np.pi, 128)

# ---------------------------------------------------------------------------
# Primary-line style setters
# ---------------------------------------------------------------------------

class TestPlot1DSetters:

    def test_set_color(self):
        v = _plot(color="#4fc3f7")
        v.set_color("#ff7043")
        assert v._state["line_color"] == "#ff7043"

    def test_set_linewidth(self):
        v = _plot()
        v.set_linewidth(3.0)
        assert v._state["line_linewidth"] == pytest.approx(3.0)

    def test_set_linestyle_word(self):
        v = _plot()
        v.set_linestyle("dashed")
        assert v._state["line_linestyle"] == "dashed"

    def test_set_linestyle_shorthand(self):
        v = _plot()
        v.set_linestyle("-.")
        assert v._state["line_linestyle"] == "dashdot"

    def test_set_alpha(self):
        v = _plot()
        v.set_alpha(0.5)
        assert v._state["line_alpha"] == pytest.approx(0.5)

    def test_set_marker(self):
        v = _plot()
        v.set_marker("o", markersize=6)
        assert v._state["line_marker"] == "o"
        assert v._state["line_markersize"] == pytest.approx(6.0)

    def test_set_data_replaces_primary(self):
        v = _plot(n=64)
        new_data = np.cos(np.linspace(0, 2 * np.pi, 64))
        v.set_data(new_data)
        np.testing.assert_allclose(v._state["data"], new_data)

    def test_set_data_with_new_x_axis(self):
        v = _plot(n=32)
        y = np.ones(32)
        x = np.linspace(10, 42, 32)
        v.set_data(y, x_axis=x)
        np.testing.assert_allclose(v._state["x_axis"], x)

    def test_set_data_updates_units(self):
        v = _plot()
        v.set_data(np.zeros(128), units="eV")
        assert v._state["units"] == "eV"

    def test_set_data_2d_raises(self):
        v = _plot()
        with pytest.raises(ValueError):
            v.set_data(np.ones((4, 4)))

    def test_data_property_readonly(self):
        v = _plot()
        arr = v.data
        assert not arr.flags.writeable

    def test_line_property_returns_line1d(self):
        v = _plot()
        assert isinstance(v.line, Line1D)
        assert v.line.id is None


# ---------------------------------------------------------------------------
# Construction — linestyle / alpha / marker at creation time
# ---------------------------------------------------------------------------

class TestPlot1DConstruction:

    def test_linestyle_dashed(self):
        v = _plot(linestyle="dashed")
        assert v._state["line_linestyle"] == "dashed"

    def test_ls_shorthand(self):
        v = _plot(ls="--")
        assert v._state["line_linestyle"] == "dashed"

    def test_linestyle_dotted(self):
        v = _plot(linestyle="dotted")
        assert v._state["line_linestyle"] == "dotted"

    def test_linestyle_dashdot(self):
        v = _plot(linestyle="-.")
        assert v._state["line_linestyle"] == "dashdot"

    def test_alpha_stored(self):
        v = _plot(alpha=0.4)
        assert v._state["line_alpha"] == pytest.approx(0.4)

    def test_marker_stored(self):
        v = _plot(marker="s", markersize=5)
        assert v._state["line_marker"] == "s"
        assert v._state["line_markersize"] == pytest.approx(5.0)


# ---------------------------------------------------------------------------
# add_line / remove_line / clear_lines
# ---------------------------------------------------------------------------

class TestPlot1DOverlayLines:

    def test_add_line_returns_line1d(self):
        v = _plot()
        line = v.add_line(np.cos(t))
        assert isinstance(line, Line1D)
        assert line.id is not None

    def test_add_line_stored_in_extra_lines(self):
        v = _plot()
        v.add_line(np.cos(t), color="#ff7043", label="cos")
        assert len(v._state["extra_lines"]) == 1
        assert v._state["extra_lines"][0]["color"] == "#ff7043"

    def test_add_line_linestyle_alpha_marker(self):
        v = _plot()
        line = v.add_line(np.cos(t), linestyle="dashed", alpha=0.75,
                          marker="o", markersize=5)
        entry = v._state["extra_lines"][0]
        assert entry["linestyle"] == "dashed"
        assert entry["alpha"] == pytest.approx(0.75)
        assert entry["marker"] == "o"

    def test_add_line_ls_shorthand(self):
        v = _plot()
        v.add_line(np.cos(t), ls=":")
        assert v._state["extra_lines"][0]["linestyle"] == "dotted"

    def test_add_multiple_lines(self):
        v = _plot()
        v.add_line(np.cos(t))
        v.add_line(np.cos(t) * 0.5)
        assert len(v._state["extra_lines"]) == 2

    def test_remove_line_by_id(self):
        v = _plot()
        line = v.add_line(np.cos(t))
        v.remove_line(line.id)
        assert len(v._state["extra_lines"]) == 0

    def test_remove_line_by_line1d(self):
        v = _plot()
        line = v.add_line(np.cos(t))
        v.remove_line(line)
        assert len(v._state["extra_lines"]) == 0

    def test_remove_line_bad_id(self):
        v = _plot()
        with pytest.raises(KeyError):
            v.remove_line("nonexistent")

    def test_clear_lines(self):
        v = _plot()
        v.add_line(np.cos(t))
        v.add_line(np.cos(2 * t))
        v.clear_lines()
        assert v._state["extra_lines"] == []

    def test_data_range_expands_for_overlay(self):
        v = _plot()
        old_max = v._state["data_max"]
        v.add_line(np.sin(t) + 5)   # shifted much higher
        assert v._state["data_max"] > old_max

    def test_line1d_set_data(self):
        v = _plot()
        line = v.add_line(np.cos(t))
        new_y = np.zeros(128)
        line.set_data(new_y)
        entry = next(e for e in v._state["extra_lines"] if e["id"] == line.id)
        np.testing.assert_allclose(entry["data"], new_y)

    def test_line1d_set_data_primary_raises(self):
        v = _plot()
        primary = Line1D(v, None)
        with pytest.raises(ValueError, match="primary line"):
            primary.set_data(np.zeros(10))

    def test_line1d_set_data_bad_id_raises(self):
        v = _plot()
        phantom = Line1D(v, "deadbeef")
        with pytest.raises(KeyError):
            phantom.set_data(np.zeros(128))

    def test_line1d_remove(self):
        v = _plot()
        line = v.add_line(np.cos(t))
        line.remove()
        assert len(v._state["extra_lines"]) == 0

    def test_line1d_remove_primary_raises(self):
        v = _plot()
        primary = Line1D(v, None)
        with pytest.raises(ValueError):
            primary.remove()

    def test_line1d_eq_str(self):
        v = _plot()
        line = v.add_line(np.cos(t))
        assert line == line.id
        assert not (line == "other")

    def test_line1d_hash(self):
        v = _plot()
        line = v.add_line(np.cos(t))
        d = {line: "val"}
        assert d[line] == "val"

    def test_line1d_str(self):
        v = _plot()
        line = v.add_line(np.cos(t))
        assert str(line) == line.id


# ---------------------------------------------------------------------------
# Spans
# ---------------------------------------------------------------------------

class TestPlot1DSpans:

    def test_add_span_returns_id(self):
        v = _plot()
        sid = v.add_span(1.0, 2.0)
        assert isinstance(sid, str)
        assert len(v._state["spans"]) == 1

    def test_add_span_y_axis(self):
        v = _plot()
        v.add_span(0.5, 0.8, axis="y", color="#ff0000")
        assert v._state["spans"][0]["axis"] == "y"

    def test_remove_span(self):
        v = _plot()
        sid = v.add_span(1.0, 2.0)
        v.remove_span(sid)
        assert v._state["spans"] == []

    def test_remove_span_bad_id(self):
        v = _plot()
        with pytest.raises(KeyError):
            v.remove_span("nonexistent")

    def test_clear_spans(self):
        v = _plot()
        v.add_span(1.0, 2.0)
        v.add_span(3.0, 4.0)
        v.clear_spans()
        assert v._state["spans"] == []


# ---------------------------------------------------------------------------
# Widgets
# ---------------------------------------------------------------------------

class TestPlot1DWidgets:

    def test_add_vline_widget(self):
        v = _plot()
        w = v.add_vline_widget(1.5, color="#ff6e40")
        assert w is not None
        assert len(v._widgets) == 1

    def test_add_hline_widget(self):
        v = _plot()
        w = v.add_hline_widget(0.5)
        assert len(v._widgets) == 1

    def test_add_range_widget(self):
        v = _plot()
        w = v.add_range_widget(1.0, 3.0)
        assert len(v._widgets) == 1

    def test_get_widget_by_id(self):
        v = _plot()
        w = v.add_vline_widget(1.0)
        assert v.get_widget(w.id) is w

    def test_get_widget_by_widget(self):
        v = _plot()
        w = v.add_vline_widget(1.0)
        assert v.get_widget(w) is w

    def test_get_widget_missing(self):
        v = _plot()
        with pytest.raises(KeyError):
            v.get_widget("bad_id")

    def test_remove_widget(self):
        v = _plot()
        w = v.add_vline_widget(1.0)
        v.remove_widget(w)
        assert len(v._widgets) == 0

    def test_remove_widget_missing(self):
        v = _plot()
        with pytest.raises(KeyError):
            v.remove_widget("bad_id")

    def test_list_widgets(self):
        v = _plot()
        w1 = v.add_vline_widget(1.0)
        w2 = v.add_hline_widget(0.5)
        wlist = v.list_widgets()
        assert len(wlist) == 2

    def test_clear_widgets(self):
        v = _plot()
        v.add_vline_widget(1.0)
        v.add_hline_widget(0.5)
        v.clear_widgets()
        assert v.list_widgets() == []


# ---------------------------------------------------------------------------
# Marker helpers (add_points, add_vlines, add_hlines, list_markers)
# ---------------------------------------------------------------------------

class TestPlot1DMarkerHelpersExtras:

    def test_add_points_with_facecolors(self):
        v = _plot()
        offsets = np.column_stack([[1.0, 2.0], [0.5, 0.8]])
        v.add_points(offsets, name="peaks", sizes=7,
                     color="#ff1744", facecolors="#ff174433")
        wl = v.markers.to_wire_list()
        assert any(w["type"] == "points" for w in wl)

    def test_list_markers_count(self):
        v = _plot()
        offsets = np.column_stack([[1.0, 2.0, 3.0], [0.1, 0.2, 0.3]])
        v.add_points(offsets, name="pts")
        info = v.list_markers()
        assert any(d["name"] == "pts" and d["n"] == 3 for d in info)

    def test_remove_marker_1d(self):
        v = _plot()
        v.add_vlines([1.0, 2.0], name="m")
        v.remove_marker("vlines", "m")
        assert v.markers.to_wire_list() == []

    def test_clear_markers_1d(self):
        v = _plot()
        v.add_vlines([1.0], name="v")
        v.add_hlines([0.5], name="h")
        v.clear_markers()
        assert v.markers.to_wire_list() == []


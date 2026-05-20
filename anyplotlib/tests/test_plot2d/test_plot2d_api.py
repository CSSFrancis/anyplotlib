"""
tests/test_plot2d/test_plot2d_api.py
=====================================
Cross-cutting API and regression tests for the anyplotlib plot2d module.
Covers:
  * __repr__ for Plot1D, Plot2D, Plot3D, PlotBar
  * Plot1D.add_circles still uses "points" wire type (regression guard)
  * cividis colormap alias resolves to a valid colorcet palette
  * Top-level public imports: Plot1D, Plot2D, Axes, CallbackRegistry, Event
  * __all__ completeness: all names in anyplotlib.__all__ exist on the module
  * No debug print in Figure._on_event
"""
from __future__ import annotations
import numpy as np
import pytest
import anyplotlib as apl
from anyplotlib.plot1d import Plot1D, PlotBar
from anyplotlib.plot2d import Plot2D
from anyplotlib.plot3d import Plot3D
from anyplotlib.callbacks import CallbackRegistry, Event
# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_plot2d(shape=(32, 32)) -> Plot2D:
    fig, ax = apl.subplots(1, 1)
    return ax.imshow(np.zeros(shape))
def _make_plot1d(n=64) -> Plot1D:
    fig, ax = apl.subplots(1, 1)
    return ax.plot(np.zeros(n))
def _make_plot3d() -> Plot3D:
    fig, ax = apl.subplots(1, 1)
    x = np.linspace(0, 1, 4)
    y = np.linspace(0, 1, 4)
    X, Y = np.meshgrid(x, y)
    Z = X + Y
    return ax.plot_surface(X, Y, Z)
# ===========================================================================
# __repr__
# ===========================================================================
class TestRepr:
    def test_plot2d_repr(self):
        plot = _make_plot2d((128, 256))
        r = repr(plot)
        assert "Plot2D" in r
        assert "256" in r
        assert "128" in r
        assert "gray" in r
    def test_plot1d_repr(self):
        plot = _make_plot1d(100)
        r = repr(plot)
        assert "Plot1D" in r
        assert "100" in r
    def test_plot3d_repr(self):
        plot = _make_plot3d()
        r = repr(plot)
        assert "Plot3D" in r
        assert "surface" in r
    def test_plotbar_repr(self):
        fig, ax = apl.subplots(1, 1)
        plot = ax.bar([1, 2, 3])
        r = repr(plot)
        assert "PlotBar" in r
        assert "3" in r
# ===========================================================================
# Marker type regression
# ===========================================================================
def test_plot1d_add_circles_still_uses_points():
    """Plot1D.add_circles should continue to use the "points" wire type."""
    plot = _make_plot1d()
    offsets = np.array([10.0, 20.0, 30.0])
    plot.add_circles(offsets, name="ev")
    wire = plot.markers.to_wire_list()
    assert wire[0]["type"] == "points"
# ===========================================================================
# Colormap alias
# ===========================================================================
def test_cividis_alias_resolves():
    from anyplotlib._utils import _build_colormap_lut, _CMAP_ALIASES
    alias = _CMAP_ALIASES.get("cividis", "cividis")
    assert alias != "dimgray"
    import colorcet as cc
    assert alias in cc.palette
    lut = _build_colormap_lut("cividis")
    assert len(lut) == 256
    assert lut[0] != lut[-1]
# ===========================================================================
# Top-level public API
# ===========================================================================
def test_top_level_imports():
    from anyplotlib import Plot1D, Plot2D, Axes, CallbackRegistry, Event  # noqa: F401
    assert Plot1D is not None
    assert Plot2D is not None
    assert Axes is not None
    assert CallbackRegistry is not None
    assert Event is not None
def test_top_level_all():
    import anyplotlib
    for name in anyplotlib.__all__:
        assert hasattr(anyplotlib, name), f"anyplotlib.{name} not found"
# ===========================================================================
# No debug print in Figure._on_event
# ===========================================================================
def test_no_debug_print_in_on_event(capsys):
    import json
    fig, ax = apl.subplots(1, 1)
    plot = ax.plot(np.zeros(16))
    payload = {
        "source": "js",
        "panel_id": plot._id,
        "event_type": "on_changed",
        "zoom": 1.5,
        "center_x": 0.5,
        "center_y": 0.5,
    }
    fig._on_event({"new": json.dumps(payload)})
    captured = capsys.readouterr()
    assert captured.out == "", f"Unexpected stdout: {captured.out!r}"


# ===========================================================================
# Phase 2 — Plot2D state methods
# ===========================================================================

class TestPlot2DLabels:

    def test_set_xlabel(self):
        p = _make_plot2d()
        p.set_xlabel("x (nm)")
        assert p._state["x_label"] == "x (nm)"

    def test_set_ylabel(self):
        p = _make_plot2d()
        p.set_ylabel("y (nm)")
        assert p._state["y_label"] == "y (nm)"

    def test_set_title(self):
        p = _make_plot2d()
        p.set_title("My Image")
        assert p._state["title"] == "My Image"

    def test_set_colorbar_label(self):
        p = _make_plot2d()
        p.set_colorbar_label("Intensity")
        assert p._state["colorbar_label"] == "Intensity"

    def test_default_labels_empty(self):
        p = _make_plot2d()
        assert p._state["x_label"] == ""
        assert p._state["y_label"] == ""
        assert p._state["title"] == ""
        assert p._state["colorbar_label"] == ""


class TestPlot2DAxisLimits:

    def test_set_xlim_delegates_to_set_view(self):
        p = _make_plot2d((32, 32))
        p.set_xlim(5, 20)
        assert p._state["zoom"] != 1.0 or p._state["center_x"] != 0.5

    def test_set_ylim_delegates_to_set_view(self):
        p = _make_plot2d((32, 32))
        p.set_ylim(5, 20)
        assert p._state["zoom"] != 1.0 or p._state["center_y"] != 0.5

    def test_get_ylim_returns_y_axis_bounds(self):
        fig, ax = apl.subplots(1, 1)
        y_axis = np.linspace(0.0, 5.0, 32)
        p = ax.imshow(np.zeros((32, 32)), axes=[np.arange(32), y_axis])
        lo, hi = p.get_ylim()
        assert lo == pytest.approx(0.0)
        assert hi == pytest.approx(5.0)

    def test_get_xbound_returns_x_axis_bounds(self):
        fig, ax = apl.subplots(1, 1)
        x_axis = np.linspace(-1.0, 3.0, 32)
        p = ax.imshow(np.zeros((32, 32)), axes=[x_axis, np.arange(32)])
        lo, hi = p.get_xbound()
        assert lo == pytest.approx(-1.0)
        assert hi == pytest.approx(3.0)


class TestPlot2DExtent:

    def test_set_extent_updates_axes(self):
        p = _make_plot2d((32, 32))
        x_new = np.linspace(0.0, 10.0, 32)
        y_new = np.linspace(0.0, 20.0, 32)
        p.set_extent(x_new, y_new)
        assert p._state["x_axis"][0] == pytest.approx(0.0)
        assert p._state["x_axis"][-1] == pytest.approx(10.0)
        assert p._state["y_axis"][-1] == pytest.approx(20.0)

    def test_set_extent_updates_scale(self):
        p = _make_plot2d((32, 32))
        x_new = np.linspace(0.0, 31.0, 32)
        y_new = np.linspace(0.0, 62.0, 32)
        p.set_extent(x_new, y_new)
        assert p._state["scale_x"] == pytest.approx(1.0)
        assert p._state["scale_y"] == pytest.approx(2.0)


class TestPlot2DColorbar:

    def test_set_colorbar_visible_true(self):
        p = _make_plot2d()
        p.set_colorbar_visible(True)
        assert p._state["show_colorbar"] is True

    def test_set_colorbar_visible_false(self):
        p = _make_plot2d()
        p.set_colorbar_visible(True)
        p.set_colorbar_visible(False)
        assert p._state["show_colorbar"] is False


class TestPlot2DAspect:

    def test_set_aspect_float(self):
        p = _make_plot2d()
        p.set_aspect(2.0)
        assert p._state["aspect"] == pytest.approx(2.0)

    def test_set_aspect_equal_string(self):
        p = _make_plot2d()
        p.set_aspect("equal")
        assert p._state["aspect"] == pytest.approx(1.0)

    def test_set_aspect_none(self):
        p = _make_plot2d()
        p.set_aspect("equal")
        p.set_aspect(None)
        assert p._state["aspect"] is None


class TestPlot2DAxisVisibility:

    def test_set_axis_off(self):
        p = _make_plot2d()
        assert p._state["axis_visible"] is True
        p.set_axis_off()
        assert p._state["axis_visible"] is False

    def test_set_ticks_visible_false(self):
        p = _make_plot2d()
        p.set_ticks_visible(False)
        assert p._state["x_ticks_visible"] is False
        assert p._state["y_ticks_visible"] is False

    def test_set_ticks_visible_per_axis(self):
        p = _make_plot2d()
        p.set_ticks_visible(False, x=False, y=True)
        assert p._state["x_ticks_visible"] is False
        assert p._state["y_ticks_visible"] is True

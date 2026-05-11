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

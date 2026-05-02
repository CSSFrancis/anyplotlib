"""
tests/test_plot2d_polish.py
===========================

Regression tests for the 0.1.0 pre-release bug-fix sweep:

  * Plot2D.add_circles / add_points use the correct "circles" marker type
  * Plot2D.set_view writes zoom/center_x/center_y (not the non-existent view_x0)
  * Plot2D.reset_view restores zoom=1, center_x=0.5, center_y=0.5
  * Plot2D.__repr__ returns a useful string
  * Plot1D.__repr__ returns a useful string
  * Plot3D.__repr__ returns a useful string
  * cividis colormap alias resolves to a valid colorcet palette (not 'dimgray')
  * Top-level imports: Plot1D, Plot2D, Axes, CallbackRegistry, Event
  * No debug print in Figure._on_event
"""

from __future__ import annotations

import io
import sys
import numpy as np
import pytest

import anyplotlib as apl
from anyplotlib.figure_plots import Plot1D, Plot2D, Plot3D, PlotBar
from anyplotlib.callbacks import CallbackRegistry, Event


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

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


# ─────────────────────────────────────────────────────────────────────────────
# 1. add_circles on Plot2D  — must use "circles" type, not "points"
# ─────────────────────────────────────────────────────────────────────────────

def test_plot2d_add_circles_does_not_crash():
    """add_circles on a Plot2D must not raise ValueError ('points' absent from _KNOWN_2D)."""
    plot = _make_plot2d()
    offsets = np.array([[8.0, 8.0], [16.0, 16.0]])
    mg = plot.add_circles(offsets, name="g1", radius=3)
    assert mg is not None
    wire = plot.markers.to_wire_list()
    assert len(wire) == 1
    assert wire[0]["type"] == "circles"


def test_plot2d_add_circles_radius_kwarg():
    """add_circles must pass radius, not sizes, to the wire format."""
    plot = _make_plot2d()
    offsets = np.array([[4.0, 4.0]])
    mg = plot.add_circles(offsets, name="c1", radius=7)
    wire = plot.markers.to_wire_list()
    assert wire[0]["type"] == "circles"
    # radius is embedded in the wire as 'sizes' by MarkerGroup.to_wire()
    sizes = wire[0].get("sizes")
    assert sizes is not None and all(s == 7.0 for s in sizes)


# ─────────────────────────────────────────────────────────────────────────────
# 2. add_points on Plot2D  — must use "circles" type
# ─────────────────────────────────────────────────────────────────────────────

def test_plot2d_add_points_does_not_crash():
    """add_points on a Plot2D must not raise ValueError."""
    plot = _make_plot2d()
    offsets = np.array([[8.0, 8.0]])
    mg = plot.add_points(offsets, name="p1", sizes=5)
    assert mg is not None
    wire = plot.markers.to_wire_list()
    assert wire[0]["type"] == "circles"


# ─────────────────────────────────────────────────────────────────────────────
# 3. Plot1D.add_circles still uses "points" (regression guard)
# ─────────────────────────────────────────────────────────────────────────────

def test_plot1d_add_circles_still_uses_points():
    """Plot1D.add_circles should continue to use the 'points' type."""
    plot = _make_plot1d()
    offsets = np.array([10.0, 20.0, 30.0])
    mg = plot.add_circles(offsets, name="ev")
    wire = plot.markers.to_wire_list()
    assert wire[0]["type"] == "points"


# ─────────────────────────────────────────────────────────────────────────────
# 4. Plot2D.set_view writes correct state keys
# ─────────────────────────────────────────────────────────────────────────────

def test_plot2d_set_view_x_only():
    """set_view(x0, x1) must update center_x and zoom, not view_x0/view_x1."""
    data = np.zeros((32, 32))
    x_axis = np.linspace(0.0, 32.0, 32)
    fig, ax = apl.subplots(1, 1)
    plot = ax.imshow(data, axes=[x_axis, None])

    plot.set_view(x0=8.0, x1=24.0)

    # center_x should be midpoint fraction: (8+24)/2 / 32 = 0.5
    assert abs(plot._state["center_x"] - 0.5) < 1e-6
    # zoom_x = 32 / (24-8) = 2.0
    assert abs(plot._state["zoom"] - 2.0) < 1e-6
    # The wrong keys must NOT exist
    assert "view_x0" not in plot._state
    assert "view_x1" not in plot._state


def test_plot2d_set_view_y_only():
    """set_view(y0=..., y1=...) must update center_y and zoom."""
    data = np.zeros((32, 32))
    y_axis = np.linspace(0.0, 32.0, 32)
    fig, ax = apl.subplots(1, 1)
    plot = ax.imshow(data, axes=[None, y_axis])

    plot.set_view(y0=8.0, y1=24.0)

    assert abs(plot._state["center_y"] - 0.5) < 1e-6
    assert abs(plot._state["zoom"] - 2.0) < 1e-6


def test_plot2d_set_view_xy():
    """set_view(x0, x1, y0, y1) uses minimum zoom when both axes given."""
    data = np.zeros((32, 64))
    x_axis = np.linspace(0.0, 64.0, 64)
    y_axis = np.linspace(0.0, 32.0, 32)
    fig, ax = apl.subplots(1, 1)
    plot = ax.imshow(data, axes=[x_axis, y_axis])

    # Zoom half of x (zoom=2) and a quarter of y (zoom=4): min = 2
    plot.set_view(x0=0, x1=32, y0=0, y1=16)

    zoom_x = 64.0 / 32.0   # = 2.0
    zoom_y = 32.0 / 16.0   # = 2.0
    expected_zoom = min(zoom_x, zoom_y)
    assert abs(plot._state["zoom"] - expected_zoom) < 1e-6


# ─────────────────────────────────────────────────────────────────────────────
# 5. Plot2D.reset_view restores defaults
# ─────────────────────────────────────────────────────────────────────────────

def test_plot2d_reset_view():
    """reset_view must restore zoom=1, center_x=0.5, center_y=0.5."""
    plot = _make_plot2d()
    plot.set_view(x0=4, x1=28)   # changes zoom & center_x
    plot.reset_view()

    assert plot._state["zoom"]     == 1.0
    assert plot._state["center_x"] == 0.5
    assert plot._state["center_y"] == 0.5
    assert "view_x0" not in plot._state
    assert "view_x1" not in plot._state


# ─────────────────────────────────────────────────────────────────────────────
# 6. __repr__ methods
# ─────────────────────────────────────────────────────────────────────────────

def test_plot2d_repr():
    plot = _make_plot2d((128, 256))
    r = repr(plot)
    assert "Plot2D" in r
    assert "256" in r    # width
    assert "128" in r    # height
    assert "gray" in r   # default colormap


def test_plot1d_repr():
    plot = _make_plot1d(100)
    r = repr(plot)
    assert "Plot1D" in r
    assert "100" in r


def test_plot3d_repr():
    plot = _make_plot3d()
    r = repr(plot)
    assert "Plot3D" in r
    assert "surface" in r


def test_plotbar_repr():
    """PlotBar already had __repr__; make sure it still works."""
    fig, ax = apl.subplots(1, 1)
    plot = ax.bar([1, 2, 3])
    r = repr(plot)
    assert "PlotBar" in r
    assert "3" in r


# ─────────────────────────────────────────────────────────────────────────────
# 7. cividis colormap alias resolves to a valid colorcet palette
# ─────────────────────────────────────────────────────────────────────────────

def test_cividis_alias_resolves():
    """'cividis' must map to a real colorcet palette (not 'dimgray')."""
    from anyplotlib.figure_plots import _build_colormap_lut, _CMAP_ALIASES
    alias = _CMAP_ALIASES.get("cividis", "cividis")
    assert alias != "dimgray", "cividis alias must not be a CSS colour name"
    import colorcet as cc
    assert alias in cc.palette, f"cividis alias '{alias}' not found in colorcet"
    lut = _build_colormap_lut("cividis")
    assert len(lut) == 256
    # Must not be a gray ramp (first and last entries must differ)
    assert lut[0] != lut[-1], "cividis LUT should not be a flat gray ramp"


# ─────────────────────────────────────────────────────────────────────────────
# 8. Top-level public API imports
# ─────────────────────────────────────────────────────────────────────────────

def test_top_level_imports():
    """Plot1D, Plot2D, Axes, CallbackRegistry, Event must all be importable."""
    from anyplotlib import Plot1D, Plot2D, Axes, CallbackRegistry, Event  # noqa: F401
    assert Plot1D is not None
    assert Plot2D is not None
    assert Axes is not None
    assert CallbackRegistry is not None
    assert Event is not None


def test_top_level_all():
    """All names in __all__ must actually exist on the module."""
    import anyplotlib
    for name in anyplotlib.__all__:
        assert hasattr(anyplotlib, name), f"anyplotlib.{name} not found"


# ─────────────────────────────────────────────────────────────────────────────
# 9. No debug print in Figure._on_event
# ─────────────────────────────────────────────────────────────────────────────

def test_no_debug_print_in_on_event(capsys):
    """Figure._on_event must not print to stdout."""
    import json
    fig, ax = apl.subplots(1, 1)
    plot = ax.plot(np.zeros(16))

    # Simulate a JS event (zoom change)
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


# ─────────────────────────────────────────────────────────────────────────────
# 10. set_overlay_mask()
# ─────────────────────────────────────────────────────────────────────────────

def test_set_overlay_mask_sets_state():
    """set_overlay_mask with a valid mask populates overlay_mask_b64."""
    plot = _make_plot2d((16, 16))
    mask = np.zeros((16, 16), dtype=bool)
    mask[4:12, 4:12] = True
    plot.set_overlay_mask(mask)
    assert plot._state["overlay_mask_b64"] != ""
    assert plot._state["overlay_mask_color"] == "#ff4444"
    assert plot._state["overlay_mask_alpha"] == 0.4


def test_set_overlay_mask_clear():
    """set_overlay_mask(None) clears the overlay."""
    plot = _make_plot2d((16, 16))
    mask = np.ones((16, 16), dtype=bool)
    plot.set_overlay_mask(mask)
    assert plot._state["overlay_mask_b64"] != ""

    plot.set_overlay_mask(None)
    assert plot._state["overlay_mask_b64"] == ""


def test_set_overlay_mask_shape_mismatch():
    """set_overlay_mask with wrong shape raises ValueError."""
    plot = _make_plot2d((16, 32))
    bad_mask = np.zeros((8, 8), dtype=bool)
    with pytest.raises(ValueError, match="mask shape"):
        plot.set_overlay_mask(bad_mask)


def test_set_overlay_mask_alpha_validation():
    """set_overlay_mask clamps alpha to [0, 1]; out-of-range raises ValueError."""
    plot = _make_plot2d((16, 16))
    mask = np.zeros((16, 16), dtype=bool)
    # Valid boundary values should work
    plot.set_overlay_mask(mask, alpha=0.0)
    assert plot._state["overlay_mask_alpha"] == 0.0
    plot.set_overlay_mask(mask, alpha=1.0)
    assert plot._state["overlay_mask_alpha"] == 1.0
    # Out-of-range should raise
    with pytest.raises(ValueError, match="alpha"):
        plot.set_overlay_mask(mask, alpha=1.5)
    with pytest.raises(ValueError, match="alpha"):
        plot.set_overlay_mask(mask, alpha=-0.1)


def test_set_overlay_mask_color_validation():
    """set_overlay_mask raises ValueError for non-#RRGGBB color strings."""
    plot = _make_plot2d((16, 16))
    mask = np.zeros((16, 16), dtype=bool)
    # Valid color should work
    plot.set_overlay_mask(mask, color="#aabbcc")
    assert plot._state["overlay_mask_color"] == "#aabbcc"
    # Short hex, named colors, or malformed should raise
    with pytest.raises(ValueError, match="color"):
        plot.set_overlay_mask(mask, color="red")
    with pytest.raises(ValueError, match="color"):
        plot.set_overlay_mask(mask, color="#fff")
    with pytest.raises(ValueError, match="color"):
        plot.set_overlay_mask(mask, color="#GGGGGG")


def test_set_overlay_mask_origin_lower_flips():
    """For origin='lower' the mask is flipped to match the internally-flipped image."""
    import base64
    fig, ax = apl.subplots(1, 1)
    data = np.zeros((4, 4))
    plot = ax.imshow(data, origin="lower")

    # Mask with only the top row (row 0) set True
    mask = np.zeros((4, 4), dtype=bool)
    mask[0, :] = True

    plot.set_overlay_mask(mask)
    # Decode the stored bytes
    raw = base64.b64decode(plot._state["overlay_mask_b64"])
    stored = np.frombuffer(raw, dtype=np.uint8).reshape(4, 4)
    # After flipud the True row should be at the last row (index 3), not row 0
    assert stored[3, 0] == 255
    assert stored[0, 0] == 0


def test_view_from_python_flag_set_view():
    """set_view() sets _view_from_python briefly; it is False after push."""
    data = np.zeros((32, 32))
    x_axis = np.linspace(0.0, 32.0, 32)
    fig, ax = apl.subplots(1, 1)
    plot = ax.imshow(data, axes=[x_axis, None])

    plot.set_view(x0=8.0, x1=24.0)
    # After the push completes _view_from_python must be reset
    assert plot._state["_view_from_python"] is False


def test_view_from_python_flag_reset_view():
    """reset_view() sets _view_from_python briefly; it is False after push."""
    plot = _make_plot2d()
    plot.reset_view()
    assert plot._state["_view_from_python"] is False



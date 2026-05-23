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


class TestGetColorCycle:

    def test_get_color_cycle_returns_list(self):
        import anyplotlib as apl
        result = apl.get_color_cycle()
        assert isinstance(result, list)

    def test_get_color_cycle_elements_are_strings(self):
        import anyplotlib as apl
        result = apl.get_color_cycle()
        assert all(isinstance(c, str) for c in result)

    def test_get_color_cycle_returns_copy(self):
        import anyplotlib as apl
        a = apl.get_color_cycle()
        b = apl.get_color_cycle()
        a.append("extra")
        assert len(b) == len(apl.get_color_cycle())

    def test_get_color_cycle_nonempty(self):
        import anyplotlib as apl
        assert len(apl.get_color_cycle()) > 0


# ===========================================================================
# Figure resize — Plot2D correctness
# ===========================================================================

class TestFigureResizePlot2D:
    """Figure resize correctly propagates to layout_json and Plot2D panel state.

    The _on_resize observer calls _push_layout() (which recomputes panel pixel
    dimensions from the new fig_width/fig_height) then re-pushes every panel's
    JSON.  For Plot2D panels the panel JSON must still carry the full axis state
    so the JS renderer can correctly position tick labels and scale the image.
    """

    def test_resize_updates_layout_fig_size(self):
        """layout_json reflects the new fig_width and fig_height after resize."""
        import json
        fig, ax = apl.subplots(1, 1, figsize=(400, 300))
        ax.imshow(np.zeros((32, 32)))

        fig.fig_width  = 800
        fig.fig_height = 600

        layout = json.loads(fig.layout_json)
        assert layout["fig_width"]  == 800
        assert layout["fig_height"] == 600

    def test_resize_updates_single_panel_dimensions(self):
        """Panel width/height in layout_json match the new figure size (1×1 grid)."""
        import json
        fig, ax = apl.subplots(1, 1, figsize=(400, 300))
        plot = ax.imshow(np.zeros((32, 32)))

        fig.fig_width  = 800
        fig.fig_height = 600

        layout = json.loads(fig.layout_json)
        spec = next(s for s in layout["panel_specs"] if s["id"] == plot._id)
        assert spec["panel_width"]  == 800
        assert spec["panel_height"] == 600

    def test_resize_plot2d_with_axes_preserves_axis_state(self):
        """Plot2D with physical axes keeps has_axes, x_axis, y_axis, and units after resize."""
        import json
        fig, ax = apl.subplots(1, 1, figsize=(400, 300))
        x_axis = np.linspace(0.0, 10.0, 32)
        y_axis = np.linspace(0.0, 20.0, 32)
        plot = ax.imshow(np.zeros((32, 32)), axes=[x_axis, y_axis], units="nm")

        panel_before = json.loads(getattr(fig, f"panel_{plot._id}_json"))

        fig.fig_width  = 800
        fig.fig_height = 600

        panel_after = json.loads(getattr(fig, f"panel_{plot._id}_json"))
        assert panel_after["has_axes"] is True
        assert panel_after["x_axis"]  == panel_before["x_axis"]
        assert panel_after["y_axis"]  == panel_before["y_axis"]
        assert panel_after["units"]   == "nm"

    def test_resize_does_not_alter_data_scale(self):
        """Resizing the figure must not change Plot2D scale_x/scale_y (data-space quantities)."""
        fig, ax = apl.subplots(1, 1, figsize=(400, 300))
        x_axis = np.linspace(0.0, 10.0, 32)
        y_axis = np.linspace(0.0, 20.0, 32)
        plot = ax.imshow(np.zeros((32, 32)), axes=[x_axis, y_axis], units="nm")

        scale_x_before = plot._state["scale_x"]
        scale_y_before = plot._state["scale_y"]

        fig.fig_width  = 800
        fig.fig_height = 600

        assert plot._state["scale_x"] == pytest.approx(scale_x_before)
        assert plot._state["scale_y"] == pytest.approx(scale_y_before)

    def test_resize_plot2d_with_axes_layout_kind(self):
        """layout_json marks a Plot2D with axes as kind='2d' after resize."""
        import json
        fig, ax = apl.subplots(1, 1, figsize=(400, 300))
        plot = ax.imshow(np.zeros((32, 32)), axes=[np.arange(32), np.arange(32)])

        fig.fig_width  = 640
        fig.fig_height = 480

        layout = json.loads(fig.layout_json)
        spec = next(s for s in layout["panel_specs"] if s["id"] == plot._id)
        assert spec["kind"] == "2d"

    def test_resize_two_panel_splits_width_evenly(self):
        """Both Plot2D panels in a 1×2 grid each get half the new figure width."""
        import json
        fig, axs = apl.subplots(1, 2, figsize=(400, 200))
        plot_l = axs[0].imshow(np.zeros((16, 16)))
        plot_r = axs[1].imshow(np.zeros((16, 16)))

        fig.fig_width = 800

        layout = json.loads(fig.layout_json)
        specs = {s["id"]: s for s in layout["panel_specs"]}
        assert specs[plot_l._id]["panel_width"] == pytest.approx(400, abs=1)
        assert specs[plot_r._id]["panel_width"] == pytest.approx(400, abs=1)

    def test_resize_with_height_ratios_scales_proportionally(self):
        """GridSpec height_ratios [3, 1] scale correctly when fig_height changes."""
        import json
        gs  = apl.GridSpec(2, 1, height_ratios=[3, 1])
        fig = apl.Figure(figsize=(400, 400))
        plot_top = fig.add_subplot(gs[0, 0]).imshow(np.zeros((32, 32)))
        plot_bot = fig.add_subplot(gs[1, 0]).imshow(np.zeros((16, 16)))

        fig.fig_height = 800

        layout = json.loads(fig.layout_json)
        specs  = {s["id"]: s for s in layout["panel_specs"]}
        # top: 3/4 × 800 = 600 px;  bottom: 1/4 × 800 = 200 px
        assert specs[plot_top._id]["panel_height"] == pytest.approx(600, abs=1)
        assert specs[plot_bot._id]["panel_height"] == pytest.approx(200, abs=1)


# ===========================================================================
# Plot2D.get_xlim
# ===========================================================================

class TestPlot2DGetXlim:
    def test_get_xlim_exists(self):
        p = _make_plot2d()
        assert hasattr(p, "get_xlim")

    def test_get_xlim_with_physical_axes(self):
        fig, ax = apl.subplots(1, 1)
        x = np.linspace(0.0, 10.0, 16)
        p = ax.imshow(np.zeros((16, 16)), axes=[x, np.linspace(0, 5, 16)], units="nm")
        lo, hi = p.get_xlim()
        assert lo == pytest.approx(0.0)
        assert hi == pytest.approx(10.0)

    def test_get_xlim_and_get_ylim_match_axes(self):
        fig, ax = apl.subplots(1, 1)
        x = np.linspace(1.0, 5.0, 16)
        y = np.linspace(2.0, 8.0, 16)
        p = ax.imshow(np.zeros((16, 16)), axes=[x, y], units="m")
        xlo, xhi = p.get_xlim()
        ylo, yhi = p.get_ylim()
        assert xlo == pytest.approx(1.0)
        assert xhi == pytest.approx(5.0)
        assert ylo == pytest.approx(2.0)
        assert yhi == pytest.approx(8.0)


# ===========================================================================
# Plot2D: set_axis_on and no log_scale key
# ===========================================================================

class TestPlot2DSetAxisOn:
    def test_set_axis_on_restores(self):
        fig, ax = apl.subplots(1, 1)
        p = ax.imshow(np.zeros((8, 8)), units="px")
        p.set_axis_off()
        assert p._state["axis_visible"] is False
        p.set_axis_on()
        assert p._state["axis_visible"] is True

    def test_no_log_scale_key(self):
        fig, ax = apl.subplots(1, 1)
        p = ax.imshow(np.zeros((8, 8)), units="px")
        assert "log_scale" not in p._state


class TestPlotMeshRepr:
    def test_repr_is_plotmesh(self):
        from anyplotlib.plot2d import PlotMesh
        fig, ax = apl.subplots(1, 1)
        p = ax.pcolormesh(np.ones((4, 6)))
        r = repr(p)
        assert r.startswith("PlotMesh(")
        assert "4" in r
        assert "6" in r

    def test_repr_not_plot2d(self):
        from anyplotlib.plot2d import PlotMesh
        fig, ax = apl.subplots(1, 1)
        p = ax.pcolormesh(np.ones((3, 5)))
        assert not repr(p).startswith("Plot2D(")


# ===========================================================================
# m2: configure_pointer_settled public on Plot2D
# ===========================================================================

class TestPlot2DConfigurePointerSettled:
    def test_public_method_exists(self):
        fig, ax = apl.subplots(1, 1)
        p = ax.imshow(np.zeros((8, 8)), units="px")
        assert hasattr(p, "configure_pointer_settled")
        assert callable(p.configure_pointer_settled)

    def test_sets_state(self):
        fig, ax = apl.subplots(1, 1)
        p = ax.imshow(np.zeros((8, 8)), units="px")
        p.configure_pointer_settled(150, 3)
        assert p._state["pointer_settled_ms"] == 150
        assert p._state["pointer_settled_delta"] == 3


# ===========================================================================
# m3: set_title / set_xlabel / set_ylabel direct tests on Plot2D
# ===========================================================================

class TestPlot2DDisplayMethods:
    def test_set_title(self):
        fig, ax = apl.subplots(1, 1)
        p = ax.imshow(np.zeros((8, 8)), units="px")
        p.set_title("My Image")
        assert p._state["title"] == "My Image"

    def test_set_xlabel(self):
        fig, ax = apl.subplots(1, 1)
        p = ax.imshow(np.zeros((8, 8)), units="px")
        p.set_xlabel("x (nm)")
        assert p._state["x_label"] == "x (nm)"

    def test_set_ylabel(self):
        fig, ax = apl.subplots(1, 1)
        p = ax.imshow(np.zeros((8, 8)), units="px")
        p.set_ylabel("y (nm)")
        assert p._state["y_label"] == "y (nm)"

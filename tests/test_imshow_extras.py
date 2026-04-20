"""
tests/test_imshow_extras.py
============================

Tests for Plot2D (imshow) features covered in Examples/plot_image2d.py
and Examples/plot_inset.py but not yet well covered.

Covers:
  * cmap / vmin / vmax kwargs at construction
  * origin='lower' — data orientation, y-axis reversal
  * origin='upper' (default)
  * set_colormap()
  * set_clim() — vmin only, vmax only, both
  * set_scale_mode()
  * set_data() — replace image
  * colormap_name property
  * data property (read-only, origin-aware)
  * Validation: bad origin, bad data shape
  * add_widget() — all widget kinds
  * Widget management: remove_widget, list_widgets, clear_widgets, get_widget
  * Insets: add_inset, minimize, maximize, restore, inset_state
"""
from __future__ import annotations

import numpy as np
import pytest

import anyplotlib as apl
from anyplotlib.figure_plots import Plot2D


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _img(n=32, **kwargs) -> Plot2D:
    fig, ax = apl.subplots(1, 1)
    data = np.arange(n * n, dtype=float).reshape(n, n)
    return ax.imshow(data, **kwargs)


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------

class TestPlot2DConstruction:

    def test_kind_is_2d(self):
        v = _img()
        assert v._state["kind"] == "2d"

    def test_default_cmap_is_gray(self):
        v = _img()
        assert v._state["colormap_name"] == "gray"

    def test_cmap_kwarg(self):
        v = _img(cmap="viridis")
        assert v._state["colormap_name"] == "viridis"

    def test_vmin_vmax_clamp(self):
        data = np.linspace(0, 1, 64).reshape(8, 8)
        fig, ax = apl.subplots(1, 1)
        v = ax.imshow(data, vmin=0.2, vmax=0.8)
        assert v._state["display_min"] == pytest.approx(0.2)
        assert v._state["display_max"] == pytest.approx(0.8)

    def test_default_vmin_vmax_full_range(self):
        data = np.linspace(0.0, 1.0, 64).reshape(8, 8)
        fig, ax = apl.subplots(1, 1)
        v = ax.imshow(data)
        assert v._state["display_min"] == pytest.approx(0.0)
        assert v._state["display_max"] == pytest.approx(1.0)

    def test_origin_upper_default(self):
        v = _img()
        assert v._origin == "upper"

    def test_origin_lower_stored(self):
        v = _img(origin="lower")
        assert v._origin == "lower"

    def test_origin_lower_reverses_y_axis(self):
        data = np.zeros((8, 8))
        y = np.arange(8, dtype=float)
        fig, ax = apl.subplots(1, 1)
        v = ax.imshow(data, axes=[np.arange(8), y], origin="lower")
        # y-axis should be reversed (values decreasing)
        stored = v._state["y_axis"]
        assert stored[0] > stored[-1]

    def test_origin_invalid(self):
        with pytest.raises(ValueError, match="origin"):
            fig, ax = apl.subplots(1, 1)
            ax.imshow(np.zeros((4, 4)), origin="diagonal")

    def test_bad_data_shape_1d(self):
        with pytest.raises(ValueError):
            fig, ax = apl.subplots(1, 1)
            ax.imshow(np.zeros(16))

    def test_3d_data_squeezed(self):
        """3-D input with one channel should be accepted (first channel used)."""
        data = np.zeros((8, 8, 3))
        fig, ax = apl.subplots(1, 1)
        v = ax.imshow(data)
        assert v._state["image_width"] == 8

    def test_with_physical_axes(self):
        data = np.zeros((8, 8))
        x = np.linspace(0, 1, 8)
        y = np.linspace(0, 1, 8)
        fig, ax = apl.subplots(1, 1)
        v = ax.imshow(data, axes=[x, y], units="nm")
        assert v._state["has_axes"] is True
        assert v._state["units"] == "nm"


# ---------------------------------------------------------------------------
# Display setting mutations
# ---------------------------------------------------------------------------

class TestPlot2DSetters:

    def test_set_colormap(self):
        v = _img()
        v.set_colormap("plasma")
        assert v._state["colormap_name"] == "plasma"
        assert isinstance(v._state["colormap_data"], list)

    def test_colormap_name_property(self):
        v = _img(cmap="viridis")
        assert v.colormap_name == "viridis"

    def test_colormap_name_setter(self):
        v = _img()
        v.colormap_name = "inferno"
        assert v._state["colormap_name"] == "inferno"

    def test_set_clim_vmin(self):
        v = _img()
        v.set_clim(vmin=0.1)
        assert v._state["display_min"] == pytest.approx(0.1)

    def test_set_clim_vmax(self):
        v = _img()
        v.set_clim(vmax=0.9)
        assert v._state["display_max"] == pytest.approx(0.9)

    def test_set_clim_both(self):
        v = _img()
        v.set_clim(vmin=0.0, vmax=0.8)
        assert v._state["display_min"] == pytest.approx(0.0)
        assert v._state["display_max"] == pytest.approx(0.8)

    def test_set_scale_mode_log(self):
        v = _img()
        v.set_scale_mode("log")
        assert v._state["scale_mode"] == "log"

    def test_set_scale_mode_invalid(self):
        v = _img()
        with pytest.raises(ValueError):
            v.set_scale_mode("square_root")

    def test_set_data_replaces(self):
        v = _img()
        new = np.ones((32, 32))
        v.set_data(new)
        assert v._state["image_width"] == 32
        assert v._state["image_height"] == 32

    def test_set_data_updates_units(self):
        v = _img()
        v.set_data(np.zeros((32, 32)), units="Å")
        assert v._state["units"] == "Å"

    def test_set_data_bad_shape(self):
        v = _img()
        with pytest.raises(ValueError):
            v.set_data(np.zeros(16))

    def test_data_property_readonly(self):
        v = _img()
        arr = v.data
        assert not arr.flags.writeable

    def test_data_property_origin_lower(self):
        """data property should undo the internal flipud for origin='lower'."""
        data = np.arange(64, dtype=float).reshape(8, 8)
        fig, ax = apl.subplots(1, 1)
        v = ax.imshow(data, origin="lower")
        np.testing.assert_array_equal(v.data, data)


# ---------------------------------------------------------------------------
# add_widget
# ---------------------------------------------------------------------------

class TestPlot2DAddWidget:

    def test_add_circle_widget(self):
        v = _img(n=64)
        w = v.add_widget("circle", cx=32, cy=32, r=10)
        assert w is not None
        assert len(v._widgets) == 1

    def test_add_rectangle_widget(self):
        v = _img(n=64)
        w = v.add_widget("rectangle")
        assert len(v._widgets) == 1

    def test_add_annular_widget(self):
        v = _img(n=64)
        w = v.add_widget("annular", r_outer=20, r_inner=10)
        assert len(v._widgets) == 1

    def test_add_polygon_widget(self):
        v = _img(n=64)
        w = v.add_widget("polygon")
        assert len(v._widgets) == 1

    def test_add_crosshair_widget(self):
        v = _img(n=64)
        w = v.add_widget("crosshair", cx=32, cy=32)
        assert len(v._widgets) == 1

    def test_add_label_widget(self):
        v = _img(n=64)
        w = v.add_widget("label", text="hello")
        assert len(v._widgets) == 1

    def test_bad_widget_kind(self):
        v = _img(n=64)
        with pytest.raises(ValueError):
            v.add_widget("star")

    def test_remove_widget(self):
        v = _img(n=64)
        w = v.add_widget("circle")
        v.remove_widget(w)
        assert len(v._widgets) == 0

    def test_list_widgets(self):
        v = _img(n=64)
        v.add_widget("circle")
        v.add_widget("crosshair")
        assert len(v.list_widgets()) == 2

    def test_clear_widgets(self):
        v = _img(n=64)
        v.add_widget("circle")
        v.clear_widgets()
        assert v.list_widgets() == []


# ---------------------------------------------------------------------------
# Insets
# ---------------------------------------------------------------------------

class TestInsets:

    def _fig_with_inset(self, **kwargs):
        fig, ax = apl.subplots(1, 1, figsize=(500, 500))
        ax.imshow(np.zeros((64, 64)))
        inset = fig.add_inset(0.25, 0.25, **kwargs)
        return fig, inset

    def test_add_inset_returns_axes(self):
        fig, inset = self._fig_with_inset(title="Test")
        assert inset is not None

    def test_inset_default_state(self):
        fig, inset = self._fig_with_inset()
        assert inset.inset_state == "normal"

    def test_inset_minimize(self):
        fig, inset = self._fig_with_inset()
        inset.minimize()
        assert inset.inset_state == "minimized"

    def test_inset_maximize(self):
        fig, inset = self._fig_with_inset()
        inset.maximize()
        assert inset.inset_state == "maximized"

    def test_inset_restore(self):
        fig, inset = self._fig_with_inset()
        inset.minimize()
        inset.restore()
        assert inset.inset_state == "normal"

    def test_inset_with_plot(self):
        fig, ax = apl.subplots(1, 1, figsize=(500, 500))
        ax.imshow(np.zeros((64, 64)))
        inset = fig.add_inset(0.3, 0.3, corner="top-right", title="Profile")
        inset.plot(np.sin(np.linspace(0, 2 * np.pi, 64)), color="#4fc3f7")

    def test_inset_with_imshow(self):
        fig, ax = apl.subplots(1, 1, figsize=(500, 500))
        ax.imshow(np.zeros((64, 64)))
        inset = fig.add_inset(0.3, 0.3, corner="bottom-left")
        inset.imshow(np.ones((32, 32)), cmap="hot")

    def test_multiple_insets_same_corner(self):
        fig, ax = apl.subplots(1, 1, figsize=(600, 600))
        ax.imshow(np.zeros((64, 64)))
        i1 = fig.add_inset(0.25, 0.25, corner="top-right", title="I1")
        i2 = fig.add_inset(0.25, 0.25, corner="top-right", title="I2")
        assert i1 is not i2


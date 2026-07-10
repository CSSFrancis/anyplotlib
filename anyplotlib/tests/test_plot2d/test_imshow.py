"""
tests/test_plot2d/test_imshow.py
=================================

Comprehensive tests for Plot2D (imshow).

Covers:
  * Construction: kind, cmap, vmin/vmax, origin, axes, validation
  * Colormap: cmap kwarg, LUT building, None default, name property/setter
  * vmin/vmax: defaults, overrides, raw_min/raw_max, set_clim post-construction
  * Origin: upper/lower storage, y-axis reversal, data flip, set_data re-flip
  * Setters: set_colormap, set_clim, set_scale_mode, set_data, data property
  * Widgets: add_widget (all kinds), remove_widget, list_widgets, clear_widgets, get_widget
  * Markers: add_circles, add_points (uses "circles" wire type on Plot2D)
  * View: set_view (x-only, y-only, x+y), reset_view, _view_from_python flag
  * Overlay mask: set_overlay_mask, clear, shape/alpha/color validation, origin-lower flip
  * Insets: add_inset, minimize, maximize, restore, inset_state
  * __repr__
"""
from __future__ import annotations

import base64
import numpy as np
import pytest

import anyplotlib as apl
from anyplotlib.plot2d import Plot2D


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _img(n=32, **kwargs) -> Plot2D:
    """Create a Plot2D attached to a one-panel Figure with deterministic data."""
    fig, ax = apl.subplots(1, 1)
    data = np.arange(n * n, dtype=float).reshape(n, n)
    return ax.imshow(data, **kwargs)


# 4×4 ramp: values 0..15 (row 0 = [0,1,2,3], row 3 = [12,13,14,15])
DATA = np.arange(16, dtype=float).reshape(4, 4)
X = np.array([1.0, 2.0, 3.0, 4.0])
Y = np.array([10.0, 20.0, 30.0, 40.0])


def _decoded(v: Plot2D) -> np.ndarray:
    """Return the stored uint8 image as a (H, W) array.

    Resolves any raw-bytes change-token (used when binary transport is active)
    back to real base64 via ``resolve_pixel_tokens`` before decoding, so the
    helper works regardless of transport mode."""
    st = v.resolve_pixel_tokens(v.to_state_dict())
    raw = base64.b64decode(st["image_b64"])
    return np.frombuffer(raw, dtype=np.uint8).reshape(
        st["image_height"], st["image_width"]
    )


# ===========================================================================
# Construction
# ===========================================================================

class TestImshowConstruction:

    def test_kind_is_2d(self):
        v = _img()
        assert v._state["kind"] == "2d"

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

    def test_bad_data_shape_1d(self):
        with pytest.raises(ValueError):
            fig, ax = apl.subplots(1, 1)
            ax.imshow(np.zeros(16))


# ===========================================================================
# Colormap
# ===========================================================================

class TestImshowColormap:

    def test_default_cmap_is_gray(self):
        fig, ax = apl.subplots()
        v = ax.imshow(DATA)
        assert v._state["colormap_name"] == "gray"

    def test_cmap_kwarg(self):
        fig, ax = apl.subplots()
        v = ax.imshow(DATA, cmap="viridis")
        assert v._state["colormap_name"] == "viridis"

    def test_cmap_builds_lut(self):
        fig, ax = apl.subplots()
        v = ax.imshow(DATA, cmap="inferno")
        lut = v._state["colormap_data"]
        assert len(lut) == 256
        assert len(lut[0]) == 3  # [r, g, b]

    def test_cmap_none_uses_gray(self):
        fig, ax = apl.subplots()
        v = ax.imshow(DATA, cmap=None)
        assert v._state["colormap_name"] == "gray"

    def test_colormap_name_property(self):
        v = _img(cmap="viridis")
        assert v.colormap_name == "viridis"

    def test_colormap_name_setter(self):
        v = _img()
        v.colormap_name = "inferno"
        assert v._state["colormap_name"] == "inferno"


# ===========================================================================
# vmin / vmax
# ===========================================================================

class TestImshowVminVmax:

    def test_default_uses_data_range(self):
        fig, ax = apl.subplots()
        v = ax.imshow(DATA)
        assert v._state["display_min"] == pytest.approx(0.0)
        assert v._state["display_max"] == pytest.approx(15.0)

    def test_vmin_sets_display_min(self):
        fig, ax = apl.subplots()
        v = ax.imshow(DATA, vmin=3.0)
        assert v._state["display_min"] == pytest.approx(3.0)
        assert v._state["display_max"] == pytest.approx(15.0)  # unchanged

    def test_vmax_sets_display_max(self):
        fig, ax = apl.subplots()
        v = ax.imshow(DATA, vmax=12.0)
        assert v._state["display_min"] == pytest.approx(0.0)   # unchanged
        assert v._state["display_max"] == pytest.approx(12.0)

    def test_vmin_vmax_together(self):
        fig, ax = apl.subplots()
        v = ax.imshow(DATA, vmin=3.0, vmax=12.0)
        assert v._state["display_min"] == pytest.approx(3.0)
        assert v._state["display_max"] == pytest.approx(12.0)

    def test_raw_range_unaffected_by_vmin_vmax(self):
        """raw_min/raw_max always reflect the actual data range."""
        fig, ax = apl.subplots()
        v = ax.imshow(DATA, vmin=3.0, vmax=12.0)
        assert v._state["raw_min"] == pytest.approx(0.0)
        assert v._state["raw_max"] == pytest.approx(15.0)

    def test_set_clim_still_works_after_construction(self):
        fig, ax = apl.subplots()
        v = ax.imshow(DATA, vmin=3.0, vmax=12.0)
        v.set_clim(vmin=1.0, vmax=14.0)
        assert v._state["display_min"] == pytest.approx(1.0)
        assert v._state["display_max"] == pytest.approx(14.0)


class TestImshowClimQuantization:
    """set_data(clim=) / set_clim quantise the uint8 codes over the clim (not the
    raw min/max), so a single hot pixel / zero beam can't crush the signal into a
    handful of codes. raw_min/raw_max then equal the clim so the JS LUT reconstructs
    each code's value correctly."""

    @staticmethod
    def _hot_frame():
        rng = np.random.RandomState(0)
        f = rng.gamma(2.0, 400.0, (48, 48)).astype(np.float32)  # faint signal ~0-4000
        f[5, 5] = 60000.0                                        # hot pixel / zero beam
        return f

    def test_set_data_clim_quantises_over_clim(self):
        fig, ax = apl.subplots()
        v = ax.imshow(np.zeros((4, 4)))
        frame = self._hot_frame()
        clim = (88.0, 2638.0)
        v.set_data(frame, clim=clim)
        # raw_min/max are the quantisation endpoints (== clim), so the LUT maps back
        # correctly; display window is the same range.
        assert v._state["raw_min"] == pytest.approx(clim[0])
        assert v._state["raw_max"] == pytest.approx(clim[1])
        assert v._state["display_min"] == pytest.approx(clim[0])
        assert v._state["display_max"] == pytest.approx(clim[1])
        # The signal now spans nearly all 256 codes (vs ~12 quantising over raw
        # min/max), and the hot pixel saturates to 255 instead of stealing the range.
        u8 = v._raw_u8
        sig_codes = len(np.unique(u8[frame <= clim[1]]))
        assert sig_codes > 128, f"signal only got {sig_codes} codes — hot pixel crushed it"
        assert u8[5, 5] == 255, "hot pixel above clim must saturate to 255"

    def test_set_data_without_clim_unchanged(self):
        """No clim → quantise over raw min/max (backward-compatible)."""
        fig, ax = apl.subplots()
        v = ax.imshow(np.zeros((4, 4)))
        frame = self._hot_frame()
        v.set_data(frame)
        assert v._state["raw_min"] == pytest.approx(float(frame.min()))
        assert v._state["raw_max"] == pytest.approx(float(frame.max()))

    def test_set_clim_requantises_from_raw(self):
        """set_clim re-quantises from the cached raw frame so a NEW range is honoured
        at full fidelity (not capped by the previous quantisation band)."""
        fig, ax = apl.subplots()
        v = ax.imshow(np.zeros((4, 4)))
        frame = self._hot_frame()
        v.set_data(frame, clim=(88.0, 2638.0))
        # Widen the window well past the previous band toward the beam.
        v.set_clim(0.0, 30000.0)
        assert v._state["raw_min"] == pytest.approx(0.0)
        assert v._state["raw_max"] == pytest.approx(30000.0)
        # The hot pixel (60000, still above the new max) saturates; a mid value is
        # now representable (it wasn't at the old narrow band).
        assert v._raw_u8[5, 5] == 255


# ===========================================================================
# Origin
# ===========================================================================

class TestImshowOrigin:

    def test_upper_is_default(self):
        fig, ax = apl.subplots()
        v = ax.imshow(DATA)
        assert v._origin == "upper"

    def test_upper_keeps_y_axis_order(self):
        fig, ax = apl.subplots()
        v = ax.imshow(DATA, axes=[X, Y], origin="upper")
        assert v._state["y_axis"][0]  == pytest.approx(10.0)  # top of image
        assert v._state["y_axis"][-1] == pytest.approx(40.0)  # bottom

    def test_upper_row0_at_top(self):
        """With origin='upper', row 0 of data (min values) is stored first."""
        fig, ax = apl.subplots()
        v = ax.imshow(DATA, origin="upper")
        stored = _decoded(v)
        assert stored[0, 0] == 0  # row 0, col 0 → value 0 → uint8 min

    def test_lower_stored(self):
        v = _img(origin="lower")
        assert v._origin == "lower"

    def test_lower_reverses_y_axis_with_axes(self):
        fig, ax = apl.subplots()
        v = ax.imshow(DATA, axes=[X, Y], origin="lower")
        assert v._state["y_axis"][0]  == pytest.approx(40.0)  # max at top
        assert v._state["y_axis"][-1] == pytest.approx(10.0)  # min at bottom

    def test_lower_default_y_axis_reversed(self):
        """Without explicit axes, origin='lower' still reverses default y."""
        fig, ax = apl.subplots()
        v = ax.imshow(DATA, origin="lower")
        assert v._state["y_axis"][0] > v._state["y_axis"][-1]

    def test_lower_flips_data(self):
        """With origin='lower', row 0 of original data appears at the bottom."""
        fig, ax = apl.subplots()
        v = ax.imshow(DATA, origin="lower")
        stored = _decoded(v)
        assert stored[0, :].max() == 255   # top row contains the global max
        assert stored[-1, :].min() == 0    # bottom row contains the global min

    def test_lower_set_data_reapplies_flip(self):
        """set_data() with origin='lower' automatically re-flips new data."""
        fig, ax = apl.subplots()
        v = ax.imshow(DATA, origin="lower")
        v.set_data(DATA)
        stored = _decoded(v)
        assert stored[0, :].max() == 255
        assert stored[-1, :].min() == 0

    def test_lower_set_data_reverses_new_y_axis(self):
        fig, ax = apl.subplots()
        v = ax.imshow(DATA, origin="lower")
        v.set_data(DATA, y_axis=Y)
        assert v._state["y_axis"][0]  == pytest.approx(40.0)
        assert v._state["y_axis"][-1] == pytest.approx(10.0)

    def test_data_property_origin_lower(self):
        """data property should undo the internal flipud for origin='lower'."""
        data = np.arange(64, dtype=float).reshape(8, 8)
        fig, ax = apl.subplots(1, 1)
        v = ax.imshow(data, origin="lower")
        np.testing.assert_array_equal(v.data, data)

    def test_invalid_origin_raises(self):
        fig, ax = apl.subplots()
        with pytest.raises(ValueError, match="origin"):
            ax.imshow(DATA, origin="diagonal")

    def test_combined_params(self):
        fig, ax = apl.subplots()
        v = ax.imshow(DATA, cmap="inferno", vmin=2.0, vmax=13.0,
                      origin="lower", axes=[X, Y])
        assert v._state["colormap_name"] == "inferno"
        assert v._state["display_min"]   == pytest.approx(2.0)
        assert v._state["display_max"]   == pytest.approx(13.0)
        assert v._state["y_axis"][0]     == pytest.approx(40.0)  # reversed
        stored = _decoded(v)
        assert stored[0, :].max() == 255  # flipped: top row has max value


# ===========================================================================
# Setters and data property
# ===========================================================================

class TestImshowSetters:

    def test_set_colormap(self):
        v = _img()
        v.set_colormap("plasma")
        assert v._state["colormap_name"] == "plasma"
        assert isinstance(v._state["colormap_data"], list)

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


# ===========================================================================
# Widgets
# ===========================================================================

class TestImshowWidgets:

    def test_add_circle_widget(self):
        v = _img(n=64)
        w = v.add_widget("circle", cx=32, cy=32, r=10)
        assert w is not None
        assert len(v._widgets) == 1

    def test_add_rectangle_widget(self):
        v = _img(n=64)
        v.add_widget("rectangle")
        assert len(v._widgets) == 1

    def test_add_annular_widget(self):
        v = _img(n=64)
        v.add_widget("annular", r_outer=20, r_inner=10)
        assert len(v._widgets) == 1

    def test_add_polygon_widget(self):
        v = _img(n=64)
        v.add_widget("polygon")
        assert len(v._widgets) == 1

    def test_add_crosshair_widget(self):
        v = _img(n=64)
        v.add_widget("crosshair", cx=32, cy=32)
        assert len(v._widgets) == 1

    def test_add_label_widget(self):
        v = _img(n=64)
        v.add_widget("label", text="hello")
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


# ===========================================================================
# Markers (add_circles / add_points on Plot2D)
# ===========================================================================

class TestImshowMarkers:

    def test_add_circles_does_not_crash(self):
        """add_circles on a Plot2D must not raise ValueError."""
        plot = _img()
        offsets = np.array([[8.0, 8.0], [16.0, 16.0]])
        mg = plot.add_circles(offsets, name="g1", radius=3)
        assert mg is not None
        wire = plot.markers.to_wire_list()
        assert len(wire) == 1
        assert wire[0]["type"] == "circles"

    def test_add_circles_radius_in_wire(self):
        """add_circles must pass radius embedded as 'sizes' in wire format."""
        plot = _img()
        offsets = np.array([[4.0, 4.0]])
        plot.add_circles(offsets, name="c1", radius=7)
        wire = plot.markers.to_wire_list()
        assert wire[0]["type"] == "circles"
        sizes = wire[0].get("sizes")
        assert sizes is not None and all(s == 7.0 for s in sizes)

    def test_add_points_uses_circles_type(self):
        """add_points on a Plot2D must use the 'circles' wire type, not 'points'."""
        plot = _img()
        offsets = np.array([[8.0, 8.0]])
        mg = plot.add_points(offsets, name="p1", sizes=5)
        assert mg is not None
        wire = plot.markers.to_wire_list()
        assert wire[0]["type"] == "circles"


# ===========================================================================
# View: set_view / reset_view
# ===========================================================================

class TestImshowView:

    def _make_with_x_axis(self, shape=(32, 32)):
        data = np.zeros(shape)
        x_axis = np.linspace(0.0, float(shape[1]), shape[1])
        fig, ax = apl.subplots(1, 1)
        return ax.imshow(data, axes=[x_axis, None])

    def test_set_view_x_only(self):
        """set_view(x0, x1) must update center_x and zoom, not view_x0/view_x1."""
        plot = self._make_with_x_axis()
        plot.set_view(x0=8.0, x1=24.0)
        # center_x should be midpoint fraction: (8+24)/2 / 32 = 0.5
        assert abs(plot._state["center_x"] - 0.5) < 1e-6
        # zoom_x = 32 / (24-8) = 2.0
        assert abs(plot._state["zoom"] - 2.0) < 1e-6
        assert "view_x0" not in plot._state
        assert "view_x1" not in plot._state

    def test_set_view_y_only(self):
        """set_view(y0=..., y1=...) must update center_y and zoom."""
        data = np.zeros((32, 32))
        y_axis = np.linspace(0.0, 32.0, 32)
        fig, ax = apl.subplots(1, 1)
        plot = ax.imshow(data, axes=[None, y_axis])
        plot.set_view(y0=8.0, y1=24.0)
        assert abs(plot._state["center_y"] - 0.5) < 1e-6
        assert abs(plot._state["zoom"] - 2.0) < 1e-6

    def test_set_view_xy(self):
        """set_view(x0, x1, y0, y1) uses minimum zoom when both axes given."""
        data = np.zeros((32, 64))
        x_axis = np.linspace(0.0, 64.0, 64)
        y_axis = np.linspace(0.0, 32.0, 32)
        fig, ax = apl.subplots(1, 1)
        plot = ax.imshow(data, axes=[x_axis, y_axis])
        plot.set_view(x0=0, x1=32, y0=0, y1=16)
        zoom_x = 64.0 / 32.0  # = 2.0
        zoom_y = 32.0 / 16.0  # = 2.0
        expected_zoom = min(zoom_x, zoom_y)
        assert abs(plot._state["zoom"] - expected_zoom) < 1e-6

    def test_reset_view(self):
        """reset_view must restore zoom=1, center_x=0.5, center_y=0.5."""
        plot = _img()
        plot.set_view(x0=4, x1=28)
        plot.reset_view()
        assert plot._state["zoom"]     == 1.0
        assert plot._state["center_x"] == 0.5
        assert plot._state["center_y"] == 0.5
        assert "view_x0" not in plot._state
        assert "view_x1" not in plot._state

    def test_view_from_python_flag_set_view(self):
        """set_view() sets _view_from_python briefly; it is False after push."""
        plot = self._make_with_x_axis()
        plot.set_view(x0=8.0, x1=24.0)
        assert plot._state["_view_from_python"] is False

    def test_view_from_python_flag_reset_view(self):
        """reset_view() sets _view_from_python briefly; it is False after push."""
        plot = _img()
        plot.reset_view()
        assert plot._state["_view_from_python"] is False


# ===========================================================================
# Overlay mask
# ===========================================================================

class TestImshowOverlayMask:

    def test_set_overlay_mask_sets_state(self):
        plot = _img(n=16)
        mask = np.zeros((16, 16), dtype=bool)
        mask[4:12, 4:12] = True
        plot.set_overlay_mask(mask)
        assert plot._state["overlay_mask_b64"] != ""
        assert plot._state["overlay_mask_color"] == "#ff4444"
        assert plot._state["overlay_mask_alpha"] == 0.4

    def test_set_overlay_mask_clear(self):
        plot = _img(n=16)
        mask = np.ones((16, 16), dtype=bool)
        plot.set_overlay_mask(mask)
        assert plot._state["overlay_mask_b64"] != ""
        plot.set_overlay_mask(None)
        assert plot._state["overlay_mask_b64"] == ""

    def test_set_overlay_mask_shape_mismatch(self):
        fig, ax = apl.subplots(1, 1)
        plot = ax.imshow(np.zeros((16, 32)))
        bad_mask = np.zeros((8, 8), dtype=bool)
        with pytest.raises(ValueError, match="mask shape"):
            plot.set_overlay_mask(bad_mask)

    def test_set_overlay_mask_alpha_boundary(self):
        plot = _img(n=16)
        mask = np.zeros((16, 16), dtype=bool)
        plot.set_overlay_mask(mask, alpha=0.0)
        assert plot._state["overlay_mask_alpha"] == 0.0
        plot.set_overlay_mask(mask, alpha=1.0)
        assert plot._state["overlay_mask_alpha"] == 1.0

    def test_set_overlay_mask_alpha_out_of_range(self):
        plot = _img(n=16)
        mask = np.zeros((16, 16), dtype=bool)
        with pytest.raises(ValueError, match="alpha"):
            plot.set_overlay_mask(mask, alpha=1.5)
        with pytest.raises(ValueError, match="alpha"):
            plot.set_overlay_mask(mask, alpha=-0.1)

    def test_set_overlay_mask_valid_color(self):
        plot = _img(n=16)
        mask = np.zeros((16, 16), dtype=bool)
        plot.set_overlay_mask(mask, color="#aabbcc")
        assert plot._state["overlay_mask_color"] == "#aabbcc"

    def test_set_overlay_mask_invalid_color(self):
        plot = _img(n=16)
        mask = np.zeros((16, 16), dtype=bool)
        with pytest.raises(ValueError, match="color"):
            plot.set_overlay_mask(mask, color="red")
        with pytest.raises(ValueError, match="color"):
            plot.set_overlay_mask(mask, color="#fff")
        with pytest.raises(ValueError, match="color"):
            plot.set_overlay_mask(mask, color="#GGGGGG")

    def test_set_overlay_mask_origin_lower_flips(self):
        """For origin='lower' the mask is flipped to match the internally-flipped image."""
        fig, ax = apl.subplots(1, 1)
        data = np.zeros((4, 4))
        plot = ax.imshow(data, origin="lower")
        mask = np.zeros((4, 4), dtype=bool)
        mask[0, :] = True  # only the top row
        plot.set_overlay_mask(mask)
        raw = base64.b64decode(plot._state["overlay_mask_b64"])
        stored = np.frombuffer(raw, dtype=np.uint8).reshape(4, 4)
        # After flipud the True row should be at the last row (index 3), not row 0
        assert stored[3, 0] == 255
        assert stored[0, 0] == 0


# ===========================================================================
# Insets
# ===========================================================================

class TestImshowInsets:

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


# ===========================================================================
# __repr__
# ===========================================================================

class TestImshowRepr:

    def test_repr_contains_dimensions_and_cmap(self):
        fig, ax = apl.subplots(1, 1)
        plot = ax.imshow(np.zeros((128, 256)))
        r = repr(plot)
        assert "Plot2D" in r
        assert "256" in r   # width
        assert "128" in r   # height
        assert "gray" in r  # default colormap


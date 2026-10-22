"""
Plot2D.transform — data ↔ image-pixel coordinates.

Widgets and markers on a 2-D panel live in image pixels (integer i = centre
of pixel i); users think in the calibrated axis units.  These tests pin the
conversion against the renderer's own convention, which the Python tick/view
code (``_axis_extent_frac``) already mirrors.

Shapes are deliberately all different — 12 rows × 25 columns — so a swapped
x/y would show up immediately.
"""
from __future__ import annotations

import numpy as np
import pytest

import anyplotlib as apl
from anyplotlib import ImageTransform
from anyplotlib.plot2d._transform import _AxisMap

H, W = 12, 25
X = 10.0 + 0.5 * np.arange(W)       # 0.5 units / px, offset 10
Y = -3.0 + 0.25 * np.arange(H)      # 0.25 units / px, offset -3


def _imshow(**kwargs):
    fig, ax = apl.subplots(1, 1)
    return ax.imshow(np.zeros((H, W)), **kwargs)


class TestBasics:
    def test_type_and_export(self):
        plot = _imshow()
        assert isinstance(plot.transform, ImageTransform)

    def test_default_axes_are_identity(self):
        t = _imshow().transform
        assert t.x_to_pixel(7.0) == pytest.approx(7.0)
        assert t.pixel_to_y(3.25) == pytest.approx(3.25)
        assert t.x_scale == pytest.approx(1.0)

    def test_scalar_in_float_out(self):
        t = _imshow(axes=[X, Y]).transform
        assert isinstance(t.x_to_pixel(11.0), float)
        assert isinstance(t.x_length_to_pixels(1.0), float)

    def test_axis_properties_are_copies(self):
        plot = _imshow(axes=[X, Y])
        np.testing.assert_allclose(plot.x_axis, X)
        np.testing.assert_allclose(plot.y_axis, Y)
        plot.x_axis[0] = 999.0
        assert plot.x_axis[0] == pytest.approx(10.0)


class TestCalibrated:
    def test_points(self):
        t = _imshow(axes=[X, Y]).transform
        assert t.x_to_pixel(10.0) == pytest.approx(0.0)
        assert t.x_to_pixel(11.0) == pytest.approx(2.0)
        assert t.y_to_pixel(-2.0) == pytest.approx(4.0)
        assert t.pixel_to_x(2.0) == pytest.approx(11.0)
        assert t.pixel_to_y(4.0) == pytest.approx(-2.0)

    def test_extrapolates_to_image_edges(self):
        """Half a pixel beyond the first/last centre is the image edge."""
        t = _imshow(axes=[X, Y]).transform
        assert t.x_to_pixel(X[0] - 0.25) == pytest.approx(-0.5)
        assert t.x_to_pixel(X[-1] + 0.25) == pytest.approx(W - 0.5)
        assert t.pixel_to_y(-0.5) == pytest.approx(Y[0] - 0.125)

    def test_lengths(self):
        t = _imshow(axes=[X, Y]).transform
        assert t.x_length_to_pixels(1.5) == pytest.approx(3.0)
        assert t.y_length_to_pixels(1.5) == pytest.approx(6.0)
        assert t.pixels_to_x_length(3.0) == pytest.approx(1.5)
        assert t.pixels_to_y_length(6.0) == pytest.approx(1.5)
        assert t.x_length_to_pixels(-1.5) == pytest.approx(3.0)

    def test_pairs_shapes(self):
        t = _imshow(axes=[X, Y]).transform
        one = t.data_to_pixel((11.0, -2.0))
        assert one.shape == (2,)
        np.testing.assert_allclose(one, [2.0, 4.0])
        many = t.data_to_pixel([[10.0, -3.0], [11.0, -2.0], [12.0, -1.0]])
        assert many.shape == (3, 2)
        np.testing.assert_allclose(t.pixel_to_data(many),
                                   [[10.0, -3.0], [11.0, -2.0], [12.0, -1.0]])

    def test_plot_shorthands(self):
        plot = _imshow(axes=[X, Y])
        np.testing.assert_allclose(plot.data_to_pixel([11.0, -2.0]), [2.0, 4.0])
        np.testing.assert_allclose(plot.pixel_to_data([2.0, 4.0]), [11.0, -2.0])

    def test_bad_pairs_shape(self):
        with pytest.raises(ValueError):
            _imshow().transform.data_to_pixel([1.0, 2.0, 3.0])

    def test_arrays(self):
        t = _imshow(axes=[X, Y]).transform
        px = t.x_to_pixel(X)
        assert isinstance(px, np.ndarray)
        np.testing.assert_allclose(px, np.arange(W))
        np.testing.assert_allclose(t.pixel_to_x(px), X)

    def test_live_after_set_extent(self):
        plot = _imshow(axes=[X, Y])
        t = plot.transform
        plot.set_extent(2 * X, 2 * Y)
        assert t.x_to_pixel(22.0) == pytest.approx(2.0)
        assert t.x_scale == pytest.approx(1.0)

    def test_agrees_with_view_fraction(self):
        """Matches the renderer convention used by set_view / ticks."""
        plot = _imshow(axes=[X, Y])
        for v in (9.0, 10.0, 13.3, X[-1], X[-1] + 2.0):
            frac = plot._axis_extent_frac(plot.x_axis, v, W)
            assert (plot.transform.x_to_pixel(v) + 0.5) / W == pytest.approx(frac)


class TestDescending:
    def test_origin_lower(self):
        """origin='lower' reverses y: the first y value is the bottom row."""
        plot = _imshow(axes=[X, Y], origin="lower")
        t = plot.transform
        assert t.y_to_pixel(Y[0]) == pytest.approx(H - 1)
        assert t.y_to_pixel(Y[-1]) == pytest.approx(0.0)
        assert t.pixel_to_y(H - 1) == pytest.approx(Y[0])
        assert t.y_scale == pytest.approx(-0.25)
        # Lengths stay positive.
        assert t.y_length_to_pixels(0.5) == pytest.approx(2.0)
        assert t.pixels_to_y_length(2.0) == pytest.approx(0.5)

    def test_descending_x(self):
        t = _imshow(axes=[X[::-1], Y]).transform
        assert t.x_to_pixel(X[-1]) == pytest.approx(0.0)
        assert t.x_to_pixel(X[0]) == pytest.approx(W - 1)
        assert t.x_to_pixel(X[0] - 0.25) == pytest.approx(W - 0.5)
        assert t.x_scale == pytest.approx(-0.5)


class TestNonUniform:
    XN = np.cumsum(np.linspace(0.1, 2.0, W))

    def test_points_interpolate(self):
        t = _imshow(axes=[self.XN, Y]).transform
        np.testing.assert_allclose(t.x_to_pixel(self.XN), np.arange(W))
        mid = 0.5 * (self.XN[3] + self.XN[4])
        assert t.x_to_pixel(mid) == pytest.approx(3.5)

    def test_length_at(self):
        t = _imshow(axes=[self.XN, Y]).transform
        step = self.XN[11] - self.XN[10]
        assert t.x_length_to_pixels(step, at=self.XN[10]) == pytest.approx(1.0)
        assert t.pixels_to_x_length(1.0, at=self.XN[10]) == pytest.approx(step)
        # Without `at` the average pixel size is used.
        avg = (self.XN[-1] - self.XN[0]) / (W - 1)
        assert t.pixels_to_x_length(1.0) == pytest.approx(avg)


class TestMesh:
    def test_edges(self):
        xe = 5.0 + 2.0 * np.arange(W + 1)
        ye = np.linspace(0.0, 1.2, H + 1)
        fig, ax = apl.subplots(1, 1)
        plot = ax.pcolormesh(np.zeros((H, W)), x_edges=xe, y_edges=ye)
        t = plot.transform
        assert t.x_to_pixel(xe[0]) == pytest.approx(-0.5)
        assert t.x_to_pixel(6.0) == pytest.approx(0.0)      # first cell centre
        assert t.y_to_pixel(ye[-1]) == pytest.approx(H - 0.5)
        assert t.x_length_to_pixels(4.0) == pytest.approx(2.0)


class TestEdgeCases:
    def test_single_pixel_axis(self):
        fig, ax = apl.subplots(1, 1)
        plot = ax.imshow(np.zeros((1, W)), axes=[X, [7.0]])
        t = plot.transform
        assert t.y_to_pixel(7.0) == pytest.approx(0.0)
        assert t.pixel_to_y(0.0) == pytest.approx(7.0)
        assert t.y_length_to_pixels(1.0) == pytest.approx(1.0)

    def test_degenerate_axis_raises(self):
        plot = _imshow(axes=[np.full(W, 3.0), Y])
        with pytest.raises(ValueError, match="degenerate"):
            plot.transform.x_to_pixel(3.0)

    def test_tile_mode_axis_shorter_than_image(self):
        """In tile mode the axis can be sampled more coarsely than the image."""
        m = _AxisMap.for_axis([0.0, 10.0, 20.0], 21, is_mesh=False)
        assert m.to_pixel(10.0) == pytest.approx(10.0)
        assert m.to_value(5.0) == pytest.approx(5.0)

    def test_repr(self):
        assert "x_scale=0.5" in repr(_imshow(axes=[X, Y]).transform)

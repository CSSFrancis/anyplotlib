"""
Edge-based calibration: ``imshow(extent=...)`` and ``Plot2D.set_extent_edges``.

matplotlib describes an image by its outer box ``(left, right, bottom, top)``;
anyplotlib stores one coordinate per pixel centre.  These pin the conversion,
including ``origin="lower"`` and a "y grows downwards" box, on a 12 × 25 image.
"""
from __future__ import annotations

import numpy as np
import pytest

import anyplotlib as apl

H, W = 12, 25


def _ax():
    fig, ax = apl.subplots(1, 1)
    return ax


class TestSetExtentEdges:
    def test_centres(self):
        plot = _ax().imshow(np.zeros((H, W)))
        plot.set_extent_edges(0.0, 5.0, 2.4, 0.0, units="nm")
        np.testing.assert_allclose(plot.x_axis, 0.1 + 0.2 * np.arange(W))
        np.testing.assert_allclose(plot.y_axis, 0.1 + 0.2 * np.arange(H))
        assert plot._state["units"] == "nm"
        assert plot._state["has_axes"] is True

    def test_edges_land_on_image_edges(self):
        plot = _ax().imshow(np.zeros((H, W)))
        plot.set_extent_edges(10.0, 22.5, -3.0, 0.0)
        t = plot.transform
        assert t.x_to_pixel(10.0) == pytest.approx(-0.5)
        assert t.x_to_pixel(22.5) == pytest.approx(W - 0.5)
        # top of the panel is y = 0, bottom is y = -3
        assert t.y_to_pixel(0.0) == pytest.approx(-0.5)
        assert t.y_to_pixel(-3.0) == pytest.approx(H - 0.5)

    def test_matches_axes_arrays(self):
        x = 10.0 + 0.5 * np.arange(W)
        y = -3.0 + 0.25 * np.arange(H)
        a = _ax().imshow(np.zeros((H, W)), axes=[x, y])
        b = _ax().imshow(np.zeros((H, W)))
        b.set_extent_edges(9.75, 22.25, y[-1] + 0.125, -3.125)
        np.testing.assert_allclose(b.x_axis, a.x_axis)
        np.testing.assert_allclose(b.y_axis, a.y_axis)


class TestImshowExtent:
    def test_upper(self):
        plot = _ax().imshow(np.zeros((H, W)), extent=(0.0, 5.0, 2.4, 0.0))
        np.testing.assert_allclose(plot.x_axis[[0, -1]], [0.1, 4.9])
        np.testing.assert_allclose(plot.y_axis[[0, -1]], [0.1, 2.3])

    def test_lower(self):
        """origin='lower': y increases upwards, so the top row is y ~ top."""
        data = np.zeros((H, W))
        plot = _ax().imshow(data, origin="lower", extent=(0.0, 5.0, 0.0, 2.4))
        np.testing.assert_allclose(plot.y_axis[[0, -1]], [2.3, 0.1])
        assert plot.transform.y_to_pixel(2.4) == pytest.approx(-0.5)

    def test_same_as_set_extent_edges(self):
        a = _ax().imshow(np.zeros((H, W)), extent=(1.0, 2.0, 5.0, 3.0))
        b = _ax().imshow(np.zeros((H, W)))
        b.set_extent_edges(1.0, 2.0, 5.0, 3.0)
        np.testing.assert_allclose(a.x_axis, b.x_axis)
        np.testing.assert_allclose(a.y_axis, b.y_axis)
        assert a._state["has_axes"] is True

    def test_axes_and_extent_conflict(self):
        with pytest.raises(ValueError, match="extent"):
            _ax().imshow(np.zeros((H, W)), axes=[np.arange(W), np.arange(H)],
                         extent=(0, 1, 1, 0))


class TestMarkerGroupAccessors:
    def test_get_type_name(self):
        plot = _ax().imshow(np.zeros((H, W)))
        g = plot.add_circles([[1, 2]], name="spots", edgecolors="#00ff00")
        assert g.marker_type == "circles"
        assert g.name == "spots"
        assert g.get("edgecolors") == "#00ff00"
        assert g.get("missing", 3) == 3

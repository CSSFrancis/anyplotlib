"""
``size_units="px"`` — marker sizes that do not grow with zoom.

Marker radii and widths were always in data units, so a marker standing in for
a *point* (a detected peak, a cursor) swelled as the user zoomed in.  That is
right for a shape drawn *on* the data and wrong for a glyph marking a
position — matplotlib sizes scatter markers in display points for the same
reason.

``size_units`` is independent of ``transform``: positions can be in data
coordinates while sizes are in pixels.
"""
from __future__ import annotations

import numpy as np
import pytest

import anyplotlib as apl

FIG = 400
IMG = 32


def _fig_with(**kwargs):
    fig, ax = apl.subplots(1, 1, figsize=(FIG, FIG))
    plot = ax.imshow(np.zeros((IMG, IMG), dtype=np.float32))
    plot.add_circles([[16.0, 16.0]], radius=3, edgecolors="#ff0000",
                     facecolors="#ff0000", **kwargs)
    return fig, plot


def _marker_px(take_screenshot, fig):
    img = take_screenshot(fig)[..., :3].astype(int)
    return int((np.abs(img - np.array([255, 0, 0])).sum(axis=-1) < 60).sum())


class TestWireFormat:
    def test_px_reaches_the_wire(self):
        fig, ax = apl.subplots(1, 1)
        plot = ax.imshow(np.zeros((IMG, IMG)))
        g = plot.add_circles([[5, 5]], radius=4, size_units="px")
        assert g.to_wire("g")["size_units"] == "px"

    def test_default_is_data(self):
        fig, ax = apl.subplots(1, 1)
        plot = ax.imshow(np.zeros((IMG, IMG)))
        g = plot.add_circles([[5, 5]], radius=4)
        assert g.to_wire("g")["size_units"] == "data"

    def test_registry_path_may_omit_it(self):
        """A group added straight through the registry need not set it;
        the renderer treats absent as 'data'."""
        fig, ax = apl.subplots(1, 1)
        plot = ax.imshow(np.zeros((IMG, IMG)))
        g = plot.markers.add("circles", offsets=[[5, 5]], radius=4)
        assert "size_units" not in g.to_wire("g")

    def test_invalid_value_raises(self):
        fig, ax = apl.subplots(1, 1)
        plot = ax.imshow(np.zeros((IMG, IMG)))
        with pytest.raises(ValueError, match="size_units must be"):
            plot.add_circles([[5, 5]], radius=4, size_units="inches").to_wire("g")

    @pytest.mark.parametrize("factory,kwargs", [
        ("add_circles", {"radius": 3}),
        ("add_points", {"sizes": 3}),
        ("add_ellipses", {"widths": 3, "heights": 2}),
        ("add_rectangles", {"widths": 3, "heights": 2}),
        ("add_squares", {"widths": 3}),
    ])
    def test_every_sized_factory_accepts_it(self, factory, kwargs):
        fig, ax = apl.subplots(1, 1)
        plot = ax.imshow(np.zeros((IMG, IMG)))
        g = getattr(plot, factory)([[5, 5]], size_units="px", **kwargs)
        assert g.to_wire("g")["size_units"] == "px"


class TestRendering:
    # Zoom in on the middle quarter, where the marker sits.
    ZOOM_VIEW = dict(x0=8.0, x1=24.0, y0=8.0, y1=24.0)

    def test_data_sized_markers_grow_with_zoom(self, take_screenshot):
        """The existing behaviour, as a contrast case.

        The count is of the *outline* — the fill is translucent and does not
        match a saturated red — so it grows with the circumference, linearly
        in the radius, not with the area.
        """
        fig, plot = _fig_with()
        before = _marker_px(take_screenshot, fig)
        fig2, plot2 = _fig_with()
        plot2.set_view(**self.ZOOM_VIEW)
        after = _marker_px(take_screenshot, fig2)
        assert after > before * 1.5, (
            f"data-sized markers must scale with zoom ({before} -> {after} px)"
        )

    def test_px_sized_markers_keep_their_size(self, take_screenshot):
        fig, plot = _fig_with(size_units="px")
        before = _marker_px(take_screenshot, fig)
        fig2, plot2 = _fig_with(size_units="px")
        plot2.set_view(**self.ZOOM_VIEW)
        after = _marker_px(take_screenshot, fig2)
        assert after == pytest.approx(before, rel=0.25), (
            f"px-sized markers must not scale with zoom ({before} -> {after} px)"
        )

    def test_px_marker_is_still_drawn(self, take_screenshot):
        fig, plot = _fig_with(size_units="px")
        assert _marker_px(take_screenshot, fig) > 0

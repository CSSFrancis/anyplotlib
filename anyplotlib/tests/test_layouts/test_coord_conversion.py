"""
plot_box() / data_to_display() / display_to_data().

Anything doing display-space work — pixel-sized handles, hit-test tolerances,
screenshot-driven tests — previously had to re-derive the renderer's layout
(the ``PAD_*`` constants and the ``_imgFitRect`` letterbox math) in its own
code, and then keep it in step with ``figure_esm.js`` by hand.

The important test here is :class:`TestAgreesWithTheRenderer`: it draws a
marker at a known data coordinate, finds it in a real screenshot, and checks
the Python answer against where the browser actually put it.  Without that,
these methods could be self-consistently wrong.
"""
from __future__ import annotations

import numpy as np
import pytest

import anyplotlib as apl

FIG_W, FIG_H = 400, 300
GRID_PAD = 8   # figure_esm.js gridDiv padding, present in every screenshot


def _line_plot(n=50):
    fig, ax = apl.subplots(1, 1, figsize=(FIG_W, FIG_H))
    return fig, ax.plot(np.linspace(0.0, 1.0, n))


class TestPlotBox:
    def test_matches_the_padding_constants(self):
        _, plot = _line_plot()
        box = plot.plot_box()
        left, right, top, bottom = plot.PLOT_PADDING
        assert box["x"] == left
        assert box["y"] == top
        assert box["width"] == FIG_W - left - right
        assert box["height"] == FIG_H - top - bottom

    def test_image_box_is_letterboxed(self):
        """Data coords map onto the fitted image, not the full padded area."""
        fig, ax = apl.subplots(1, 1, figsize=(400, 400))
        plot = ax.imshow(np.zeros((10, 20), dtype=np.float32))
        box = plot.plot_box()
        # A 20x10 image is twice as wide as tall: it fills the width and is
        # centred vertically.
        assert box["width"] == pytest.approx(box["height"] * 2.0)
        assert box["y"] > plot.PLOT_PADDING[2]

    def test_square_image_is_pillarboxed(self):
        """A square image in a wide panel is centred horizontally.

        This one has no physical axes, so the renderer drops the left/right
        gutters entirely and the image fills the panel width before fitting —
        hence the box starts left of PLOT_PADDING, not right of it.
        """
        fig, ax = apl.subplots(1, 1, figsize=(FIG_W, FIG_H))
        plot = ax.imshow(np.zeros((32, 32), dtype=np.float32))
        box = plot.plot_box()
        assert box["width"] == pytest.approx(box["height"])
        assert box["x"] > 0
        assert box["x"] < plot.PLOT_PADDING[0]

    def test_axes_reinstate_the_gutters(self):
        """With physical axes the padded layout applies again."""
        fig, ax = apl.subplots(1, 1, figsize=(FIG_W, FIG_H))
        x = np.linspace(0.0, 10.0, 32)
        plot = ax.imshow(np.zeros((32, 32), dtype=np.float32),
                         axes=[x, x], units="nm")
        assert plot.plot_box()["x"] >= plot.PLOT_PADDING[0]

    def test_colorbar_narrows_the_box(self):
        """The strip and its gap come out of the image width.

        The image is deliberately WIDE so width is the binding constraint —
        a square image in this panel is height-limited, and narrowing the
        available width would not change its fitted size at all.
        """
        fig, ax = apl.subplots(1, 1, figsize=(FIG_W, FIG_H))
        plot = ax.imshow(np.zeros((8, 64), dtype=np.float32),
                         axes=[np.linspace(0.0, 10.0, 64),
                               np.linspace(0.0, 1.0, 8)], units="nm")
        before = plot.plot_box()["width"]
        plot.set_colorbar_visible(True)
        assert plot.plot_box()["width"] < before

    def test_unattached_panel_raises(self):
        from anyplotlib.plot1d import Plot1D

        plot = Plot1D(np.zeros(8))
        with pytest.raises(RuntimeError, match="not attached"):
            plot.plot_box()


class TestConversions:
    def test_round_trip(self):
        _, plot = _line_plot()
        pts = [[5.0, 0.2], [25.0, 0.5], [40.0, 0.9]]
        back = plot.display_to_data(plot.data_to_display(pts))
        np.testing.assert_allclose(back, pts, atol=1e-9)

    def test_single_point_shape_is_preserved(self):
        _, plot = _line_plot()
        out = plot.data_to_display([25.0, 0.5])
        assert out.shape == (2,)

    def test_sequence_shape_is_preserved(self):
        _, plot = _line_plot()
        out = plot.data_to_display([[1.0, 0.1], [2.0, 0.2]])
        assert out.shape == (2, 2)

    def test_bad_shape_raises(self):
        _, plot = _line_plot()
        with pytest.raises(ValueError, match=r"\(N, 2\)"):
            plot.data_to_display([[1.0, 2.0, 3.0]])

    def test_x_increases_rightwards(self):
        _, plot = _line_plot()
        lo = plot.data_to_display([5.0, 0.5])
        hi = plot.data_to_display([40.0, 0.5])
        assert hi[0] > lo[0]

    def test_y_increases_upwards_in_data_downwards_on_screen(self):
        _, plot = _line_plot()
        lo = plot.data_to_display([25.0, 0.1])
        hi = plot.data_to_display([25.0, 0.9])
        assert hi[1] < lo[1], "a larger data y must map to a smaller screen y"

    def test_left_edge_maps_to_the_box_edge(self):
        _, plot = _line_plot()
        x0, _ = plot.get_xlim()
        box = plot.plot_box()
        assert plot.data_to_display([x0, 0.0])[0] == pytest.approx(box["x"])


class TestAgreesWithTheRenderer:
    """The Python geometry must match what the browser draws.

    A marker is placed at a known data coordinate; its centre of mass in the
    screenshot is compared with ``data_to_display``.  Marker offsets go
    through the renderer's own transform, so any drift between the Python
    mirror and ``figure_esm.js`` shows up here.
    """

    def _marker_centre(self, take_screenshot, fig, rgb=(255, 0, 0)):
        img = take_screenshot(fig)[..., :3].astype(int)
        hit = np.abs(img - np.array(rgb)).sum(axis=-1) < 60
        assert hit.any(), "marker not found in the screenshot"
        ys, xs = np.where(hit)
        return xs.mean(), ys.mean()

    def test_1d_vline_marker_lands_where_predicted(self, take_screenshot):
        fig, ax = apl.subplots(1, 1, figsize=(FIG_W, FIG_H))
        plot = ax.plot(np.linspace(0.0, 1.0, 50))
        # A vlines marker is positioned by x alone, so its column is exactly
        # what data_to_display's x should predict.
        plot.add_vlines([25.0], color="#ff0000", linewidths=2)
        cx, _ = self._marker_centre(take_screenshot, fig)
        want_x = plot.data_to_display([25.0, 0.5])[0] + GRID_PAD
        assert cx == pytest.approx(want_x, abs=3.0), (
            f"renderer drew the marker at x={cx:.1f}, "
            f"data_to_display predicted {want_x:.1f}"
        )

    def test_2d_circle_marker_lands_where_predicted(self, take_screenshot):
        fig, ax = apl.subplots(1, 1, figsize=(400, 400))
        plot = ax.imshow(np.zeros((32, 32), dtype=np.float32))
        plot.add_circles(offsets=[[8.0, 24.0]], radius=2,
                         edgecolors="#ff0000", facecolors="#ff0000")
        cx, cy = self._marker_centre(take_screenshot, fig)
        want = plot.data_to_display([8.0, 24.0])
        assert cx == pytest.approx(want[0] + GRID_PAD, abs=4.0)
        assert cy == pytest.approx(want[1] + GRID_PAD, abs=4.0)

    def test_prediction_is_not_trivially_the_centre(self, take_screenshot):
        """Guard: an off-centre point must be predicted off-centre."""
        fig, ax = apl.subplots(1, 1, figsize=(400, 400))
        plot = ax.imshow(np.zeros((32, 32), dtype=np.float32))
        box = plot.plot_box()
        want = plot.data_to_display([8.0, 24.0])
        assert abs(want[0] - (box["x"] + box["width"] / 2)) > 20

"""
Colorbar gap and scale-bar colours.

The colorbar strip used to be drawn 2 px from the image edge, and most plots
have no ``colorbar_label`` — so the label gutter that would otherwise separate
them is zero-width and the strip reads as part of the image.  There is now a
real gap, taken out of the image width so the strip can never be pushed off
the panel, and configurable per panel.

The automatic scale bar was hardcoded white-on-a-dark-pill, which is unreadable
over a light image and cannot be matched to a house style.
"""
from __future__ import annotations

import numpy as np
import pytest

import anyplotlib as apl

FIG_W, FIG_H = 400, 300


def _img_fig(**calls):
    fig, ax = apl.subplots(1, 1, figsize=(FIG_W, FIG_H))
    plot = ax.imshow(np.zeros((32, 32), dtype=np.float32))
    for name, arg in calls.items():
        getattr(plot, name)(arg)
    return fig, plot


class TestColorbarPadApi:
    def test_defaults_to_none(self):
        _, plot = _img_fig()
        assert plot._state["colorbar_pad"] is None

    def test_setter_stores_value(self):
        _, plot = _img_fig()
        plot.set_colorbar_pad(12)
        assert plot._state["colorbar_pad"] == 12.0

    def test_none_restores_default(self):
        _, plot = _img_fig()
        plot.set_colorbar_pad(12)
        plot.set_colorbar_pad(None)
        assert plot._state["colorbar_pad"] is None

    def test_negative_is_clamped(self):
        _, plot = _img_fig()
        plot.set_colorbar_pad(-5)
        assert plot._state["colorbar_pad"] == 0.0

    def test_reaches_the_state_dict(self):
        _, plot = _img_fig()
        plot.set_colorbar_pad(9)
        assert plot.to_state_dict()["colorbar_pad"] == 9.0


class TestColorbarGapRendering:
    """The gap is measured on the rendered canvas, not asserted in Python."""

    def _strip_left_edge(self, take_screenshot, pad=None):
        """Return the x of the leftmost colorbar-strip pixel, and of the image's
        right edge, from a rendered screenshot."""
        fig, ax = apl.subplots(1, 1, figsize=(FIG_W, FIG_H))
        # A bright uniform image so the image area is easy to segment.
        plot = ax.imshow(np.ones((32, 32), dtype=np.float32), cmap="gray")
        plot.set_colorbar_visible(True)
        if pad is not None:
            plot.set_colorbar_pad(pad)
        img = take_screenshot(fig)[..., :3].astype(int)
        row = img[img.shape[0] // 2]
        # Non-background pixels along the middle row.
        bg = img[2, 2]
        ink = np.where(np.abs(row - bg).sum(axis=-1) > 30)[0]
        assert ink.size, "nothing rendered"
        # The image block is the long run; the strip is the run after the gap.
        gaps = np.where(np.diff(ink) > 1)[0]
        assert gaps.size, "image and colorbar strip are not separated"
        return int(ink[gaps[-1]]), int(ink[gaps[-1] + 1])

    def test_there_is_a_gap_at_all(self, take_screenshot):
        img_right, strip_left = self._strip_left_edge(take_screenshot)
        assert strip_left - img_right >= 4, (
            f"expected a visible gap, image ends at {img_right} and the strip "
            f"starts at {strip_left}"
        )

    def test_pad_widens_the_gap(self, take_screenshot):
        d_default = np.subtract(*reversed(self._strip_left_edge(take_screenshot)))
        d_wide = np.subtract(*reversed(self._strip_left_edge(take_screenshot, pad=20)))
        assert d_wide > d_default + 5

    def test_strip_stays_inside_the_panel(self, take_screenshot):
        """The gap comes out of the image width, so a big pad must not push
        the strip off the right edge."""
        fig, ax = apl.subplots(1, 1, figsize=(FIG_W, FIG_H))
        plot = ax.imshow(np.ones((32, 32), dtype=np.float32), cmap="gray")
        plot.set_colorbar_visible(True)
        plot.set_colorbar_pad(40)
        img = take_screenshot(fig)[..., :3].astype(int)
        row = img[img.shape[0] // 2]
        bg = img[2, 2]
        ink = np.where(np.abs(row - bg).sum(axis=-1) > 30)[0]
        assert ink.size, "the colorbar strip was pushed off the panel"
        assert ink[-1] < img.shape[1] - 1


class TestScalebarStyleApi:
    def test_defaults_are_none(self):
        _, plot = _img_fig()
        assert plot._state["scalebar_color"] is None
        assert plot._state["scalebar_bgcolor"] is None

    def test_sets_color(self):
        _, plot = _img_fig()
        plot.set_scalebar_style(color="black")
        assert plot._state["scalebar_color"] == "black"

    def test_sets_bgcolor(self):
        _, plot = _img_fig()
        plot.set_scalebar_style(bgcolor="none")
        assert plot._state["scalebar_bgcolor"] == "none"

    def test_partial_update_leaves_the_other(self):
        _, plot = _img_fig()
        plot.set_scalebar_style(color="red", bgcolor="white")
        plot.set_scalebar_style(color="blue")
        assert plot._state["scalebar_bgcolor"] == "white"

    def test_reaches_the_state_dict(self):
        _, plot = _img_fig()
        plot.set_scalebar_style(color="#123456")
        assert plot.to_state_dict()["scalebar_color"] == "#123456"


class TestScalebarRendering:
    # The scale bar sits 12 px in from the image's bottom-right corner.  For a
    # 400x300 figure with physical axes the image spans x 66..396, y 20..266 in
    # screenshot coords (GRID_PAD=8 plus PAD_L/PAD_T), so this box contains the
    # bar and nothing else.
    SB_BOX = (slice(200, 266), slice(280, 396))

    @staticmethod
    def _white_image_fig(**style):
        """A figure whose image renders uniformly WHITE under the scale bar.

        The pill is ``rgba(0,0,0,0.60)`` — translucent, so it can only be
        measured against what is underneath.  Explicit ``vmin``/``vmax`` are
        what make the image white: passing a uniform array instead would
        normalise vmin == vmax straight to black, and passing a ramp leaves
        mid-grey data in the box that is indistinguishable from the pill.
        """
        fig, ax = apl.subplots(1, 1, figsize=(FIG_W, FIG_H))
        data = np.full((32, 32), 1.0, dtype=np.float32)
        plot = ax.imshow(data, cmap="gray", vmin=0.0, vmax=1.0,
                         axes=[np.linspace(0, 100, 32)] * 2, units="nm")
        if style:
            plot.set_scalebar_style(**style)
        return fig

    def _scalebar_pixels(self, take_screenshot, rgb, **style):
        """Count pixels of a colour in the scale-bar box."""
        img = take_screenshot(self._white_image_fig(**style))[..., :3].astype(int)
        box = img[self.SB_BOX[0], self.SB_BOX[1]]
        return int((np.abs(box - np.array(rgb)).sum(axis=-1) < 40).sum())

    def _pill_pixels(self, take_screenshot, **style):
        """Count pill pixels: neutral grey, clearly darker than the white data.

        Over white the translucent pill renders mid-grey (~102 per channel),
        never black.  Requiring the three channels to match excludes a
        coloured bar; the upper sum bound excludes the white image.
        """
        img = take_screenshot(self._white_image_fig(**style))[..., :3].astype(int)
        box = img[self.SB_BOX[0], self.SB_BOX[1]]
        neutral = (box.max(axis=-1) - box.min(axis=-1)) < 12
        midtone = (box.sum(axis=-1) > 100) & (box.sum(axis=-1) < 600)
        return int((neutral & midtone).sum())

    def test_default_draws_a_pill(self, take_screenshot):
        """Baseline for the tests below."""
        assert self._pill_pixels(take_screenshot) > 100

    def test_color_recolours_the_bar(self, take_screenshot):
        red = self._scalebar_pixels(take_screenshot, (255, 0, 0), color="#ff0000")
        assert red > 0, "scalebar_color did not reach the rendered bar"

    def test_default_bar_is_not_red(self, take_screenshot):
        """Contrast case, so the test above cannot pass by accident."""
        assert self._scalebar_pixels(take_screenshot, (255, 0, 0)) == 0

    def test_bgcolor_none_drops_the_pill(self, take_screenshot):
        """The dark pill is the thing that looks wrong on a light image."""
        with_pill = self._pill_pixels(take_screenshot)
        without = self._pill_pixels(take_screenshot, color="#ff0000",
                                    bgcolor="none")
        assert without < with_pill * 0.2, (
            f"bgcolor='none' must remove the pill "
            f"({without} pill px vs {with_pill} with it)"
        )

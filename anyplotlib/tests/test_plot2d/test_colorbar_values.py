"""
The colorbar says how much, not only which way.

The strip drew a gradient, two white marks at display_min / display_max and a
rotated label, and nothing else — so a map labelled "strain (%)" still never
said whether its red was 0.2 % or 2 %.  The display range is now written
beside the marks, in the same format the axis ticks use, in a gutter the
image gives up so the numbers never clip.
"""
from __future__ import annotations

import numpy as np

import anyplotlib as apl

FIG_W, FIG_H = 400, 300
STRIP_W, VALUE_GUTTER = 16, 39      # 3.6 × the 10 px tick size, plus a 3 px gap


def _colorbar_figure(lo=-1.5, hi=1.5, label=None, **extra):
    fig, ax = apl.subplots(1, 1, figsize=(FIG_W, FIG_H))
    plot = ax.imshow(np.linspace(lo, hi, 32 * 32, dtype=np.float32)
                     .reshape(32, 32), cmap="gray")
    plot.set_clim(lo, hi)
    plot.set_colorbar_visible(True)
    if label:
        plot.set_colorbar_label(label)
    for name, value in extra.items():
        getattr(plot, name)(value)
    return fig, plot


def _ink(img):
    """Boolean mask of pixels that differ from the panel background."""
    rgb = img[..., :3].astype(int)
    background = rgb[2, 2]
    return np.abs(rgb - background).sum(axis=-1) > 30


def _strip_columns(ink):
    """``(left, right)`` columns of the colorbar strip: the LAST run of ink on
    the middle row that is exactly the strip's width."""
    row = np.where(ink[ink.shape[0] // 2])[0]
    assert row.size, "nothing rendered"
    breaks = np.where(np.diff(row) > 1)[0]
    starts = np.concatenate([[row[0]], row[breaks + 1]])
    ends = np.concatenate([row[breaks], [row[-1]]])
    for start, end in zip(starts[::-1], ends[::-1]):
        if abs((end - start + 1) - STRIP_W) <= 2:
            return int(start), int(end)
    raise AssertionError(f"no {STRIP_W} px strip on the middle row: "
                         f"{list(zip(starts, ends))}")


def _value_gutter(ink):
    """The ink right of the strip, restricted to the strip's own rows."""
    left, right = _strip_columns(ink)
    rows = np.where(ink[:, left:right + 1].any(axis=1))[0]
    top, bottom = int(rows[0]), int(rows[-1])
    gutter = ink[top:bottom + 1, right + 1:right + 1 + VALUE_GUTTER]
    return gutter, (top, bottom)


class TestGeometry:
    def test_the_value_gutter_comes_out_of_the_image(self):
        # A wide image, so width is the binding constraint (a square one in
        # this panel is height-limited and would not move).
        fig, ax = apl.subplots(1, 1, figsize=(FIG_W, FIG_H))
        plot = ax.imshow(np.zeros((8, 64), dtype=np.float32))
        before = plot.plot_box()["width"]
        plot.set_colorbar_visible(True)
        assert before - plot.plot_box()["width"] >= STRIP_W + VALUE_GUTTER

    def test_the_gutter_grows_with_the_tick_size(self):
        fig, ax = apl.subplots(1, 1, figsize=(FIG_W, FIG_H))
        plot = ax.imshow(np.zeros((8, 64), dtype=np.float32))
        plot.set_colorbar_visible(True)
        small = plot.plot_box()["width"]
        plot.set_tick_label_size(14)
        assert plot.plot_box()["width"] < small


class TestRendering:
    def test_the_range_is_written_at_the_ends_of_the_strip(self, take_screenshot):
        fig, _plot = _colorbar_figure()
        gutter, _ = _value_gutter(_ink(take_screenshot(fig)))
        rows = np.where(gutter.any(axis=1))[0]
        assert rows.size, "no value text beside the strip"
        h = gutter.shape[0]
        assert rows[0] < h * 0.25, "the maximum is not written near the top"
        assert rows[-1] > h * 0.75, "the minimum is not written near the bottom"
        # Two numbers, not a smear: the middle of the gutter stays empty.
        assert not gutter[int(h * 0.35):int(h * 0.65)].any()

    def test_the_numbers_stay_inside_the_strip_height(self, take_screenshot):
        fig, _plot = _colorbar_figure()
        ink = _ink(take_screenshot(fig))
        left, right = _strip_columns(ink)
        strip_rows = np.where(ink[:, left:right + 1].any(axis=1))[0]
        text_rows = np.where(ink[:, right + 1:right + 1 + VALUE_GUTTER].any(axis=1))[0]
        assert text_rows[0] >= strip_rows[0] and text_rows[-1] <= strip_rows[-1]

    def test_a_tiny_range_keeps_the_two_numbers_apart(self, take_screenshot):
        fig, _plot = _colorbar_figure(lo=0.999, hi=1.001)
        gutter, _ = _value_gutter(_ink(take_screenshot(fig)))
        rows = np.where(gutter.any(axis=1))[0]
        gaps = np.where(np.diff(rows) > 1)[0]
        assert gaps.size >= 1, "the two values were drawn on top of each other"

    def test_the_label_sits_right_of_the_numbers(self, take_screenshot):
        fig, _plot = _colorbar_figure(label="strain (%)")
        ink = _ink(take_screenshot(fig))
        _left, right = _strip_columns(ink)
        # (That it also FITS the panel is test_no_clipping's job.)
        assert ink[:, right + 1 + VALUE_GUTTER:].any(), \
            "no label ink beyond the value gutter"

    def test_an_rgb_image_still_draws_no_strip(self, take_screenshot):
        fig, ax = apl.subplots(1, 1, figsize=(FIG_W, FIG_H))
        plot = ax.imshow(np.full((32, 32, 3), 200, dtype=np.uint8))
        plot.set_colorbar_visible(True)
        ink = _ink(take_screenshot(fig))
        row = np.where(ink[ink.shape[0] // 2])[0]
        assert np.diff(row).max() == 1, "an RGB image grew a colorbar"

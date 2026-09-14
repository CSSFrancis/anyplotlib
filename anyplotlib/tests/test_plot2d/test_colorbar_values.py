"""
The colorbar says how much, not only which way.

The strip drew a gradient, two white marks at display_min / display_max and a
rotated label, and nothing else — so a map labelled "strain (%)" still never
said whether its red was 0.2 % or 2 %.  The display range is now written
beside the marks, in the same format the axis ticks use, in a gutter the
image gives up so the numbers never clip.

The gutter is budgeted for 7 characters (all of ``fmtVal``'s ordinary output)
so the image does not wobble as the contrast handles are dragged, grows for
the rare longer strings, and is dropped in a cell too narrow to keep 40 px of
image beside it.  ``plot_box`` mirrors every one of those rules.
"""
from __future__ import annotations

import numpy as np
import pytest

import anyplotlib as apl
from anyplotlib._base_plot import (
    COLORBAR_MIN_IMAGE_WIDTH, _colorbar_value_width, colorbar_texts,
)

FIG_W, FIG_H = 400, 300
STRIP_W = 16
VALUE_GUTTER = 45        # 7 characters × 0.6 × the 10 px tick size, plus 3 px


def _colorbar_figure(lo=-1.5, hi=1.5, label=None, size=(FIG_W, FIG_H), **extra):
    fig, ax = apl.subplots(1, 1, figsize=size)
    # viridis: BOTH ends of the strip differ from the panel background (the
    # white end of a gray strip does not), so the strip reads as ink top to
    # bottom and its rows can be found.
    plot = ax.imshow(np.linspace(lo, hi, 32 * 32, dtype=np.float32)
                     .reshape(32, 32), cmap="viridis")
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


def _longest_run(mask):
    """``(first, last)`` of the longest contiguous run of True in *mask*
    (``(0, -1)`` when there is none)."""
    best, start = (0, -1), None
    for i, on in enumerate(list(mask) + [False]):
        if on and start is None:
            start = i
        elif not on and start is not None:
            if i - start > best[1] - best[0] + 1:
                best = (start, i - 1)
            start = None
    return best


def _strip_columns(ink):
    """``(left, right)`` columns of the colorbar strip.

    Scanning rows from the middle outward (a short strip in a squat cell may
    not reach the middle row), the LAST run of ink on a row that is the
    strip's width AND whose columns hold a contiguous tall run of ink — a
    cluster of glyphs that happens to be 16 px wide is a few rows tall, the
    strip is at least a dozen."""
    height = ink.shape[0]
    middle = height // 2
    order = sorted(range(height), key=lambda r: abs(r - middle))
    for r in order:
        row = np.where(ink[r])[0]
        if not row.size:
            continue
        breaks = np.where(np.diff(row) > 1)[0]
        starts = np.concatenate([[row[0]], row[breaks + 1]])
        ends = np.concatenate([row[breaks], [row[-1]]])
        for start, end in zip(starts[::-1], ends[::-1]):
            if abs((end - start + 1) - STRIP_W) > 2:
                continue
            first, last = _strip_rows(ink, start, end)
            if last - first + 1 >= 12 and first <= r <= last:
                return int(start), int(end)
    raise AssertionError(f"no {STRIP_W} px strip found")


def _strip_rows(ink, left, right):
    """``(top, bottom)`` of the strip: the longest contiguous run of rows with
    ink in its columns (axis text below the strip is a separate run)."""
    return _longest_run(ink[:, left:right + 1].any(axis=1))


def _value_gutter(ink, width=VALUE_GUTTER):
    """The ink right of the strip, restricted to the strip's own rows."""
    left, right = _strip_columns(ink)
    top, bottom = _strip_rows(ink, left, right)
    return ink[top:bottom + 1, right + 1:right + 1 + width], (top, bottom)


class TestColorbarTexts:
    """The Python mirror of the renderer's ``fmtRange``, pair for pair: one
    format for both ends, decimals from the span, exponents from the larger
    magnitude, ties rounded away from zero like JavaScript."""

    @pytest.mark.parametrize("low, high, expected", [
        (-1.5, 1.5, ("-1.5", "1.5")),
        (-1.25, 1.25, ("-1.25", "1.25")),           # the ends exactly, not "1.3"
        (-0.005, 0.02, ("-0.005", "0.02")),          # NOT "-5.0e-3" beside "0.02"
        (1.9e-4, 0.9995, ("0", "1")),
        (0.0, 1234.0, ("0", "1234")),
        (0.999, 1.001, ("0.999", "1.001")),
        (0.2, 0.6, ("0.2", "0.6")),
        (5.0, 5.0, ("5", "5")),
        (-0.001, 0.001, ("-1.0e-3", "1.0e-3")),
        (12500.0, 20000.0, ("1.3e+4", "2.0e+4")),  # 12500 ties away, like toExponential
        (-1.5e-10, 1.5e-10, ("-1.5e-10", "1.5e-10")),
        (-1.2e308, 1.2e308, ("-1.2e+308", "1.2e+308")),
        (0.0, 0.0, ("0", "0")),
    ])
    def test_matches_the_renderer(self, low, high, expected):
        assert colorbar_texts(low, high) == expected

    def test_a_non_finite_end_has_no_text(self):
        assert colorbar_texts(float("nan"), 1.0) == ("", "")
        assert colorbar_texts(0.0, float("inf")) == ("", "")


class TestGeometry:
    def _wide_image(self, size=(FIG_W, FIG_H)):
        fig, ax = apl.subplots(1, 1, figsize=size)
        return ax.imshow(np.zeros((8, 64), dtype=np.float32))

    def test_the_value_gutter_comes_out_of_the_image(self):
        # A wide image, so width is the binding constraint (a square one in
        # this panel is height-limited and would not move).
        plot = self._wide_image()
        before = plot.plot_box()["width"]
        plot.set_colorbar_visible(True)
        assert before - plot.plot_box()["width"] == STRIP_W + VALUE_GUTTER + 6

    def test_the_gutter_grows_with_the_tick_size(self):
        plot = self._wide_image()
        plot.set_colorbar_visible(True)
        small = plot.plot_box()["width"]
        plot.set_tick_label_size(14)
        assert plot.plot_box()["width"] < small

    def test_an_ordinary_contrast_drag_does_not_move_the_image(self):
        # Every value fmtVal writes for ordinary data fits the 7-character
        # budget, so dragging the handles must not change the layout.
        plot = self._wide_image()
        plot.set_colorbar_visible(True)
        plot.set_clim(-1.5, 1.5)
        steady = plot.plot_box()["width"]
        for lo, hi in [(-0.1234, 0.1234), (0.0, 1234.0), (-12.34, 0.5), (-1.2e5, 1.2e5)]:
            plot.set_clim(lo, hi)
            assert plot.plot_box()["width"] == steady, (lo, hi)

    def test_a_long_value_widens_the_gutter_instead_of_clipping(self):
        plot = self._wide_image()
        plot.set_colorbar_visible(True)
        plot.set_clim(-1.5, 1.5)
        ordinary = plot.plot_box()["width"]
        plot.set_clim(-1.5e-10, 1.5e-10)          # "-1.5e-10": 8 characters
        assert _colorbar_value_width(plot._state) == 51
        assert ordinary - plot.plot_box()["width"] == 6

    def test_a_narrow_cell_drops_the_values_and_keeps_the_strip(self):
        # 100 px wide: strip + values + gap would leave 33 px of image, under
        # the 40 px floor — so the values go, and the image keeps 78 px.
        plot = self._wide_image(size=(100, 200))
        plot.set_colorbar_visible(True)
        box = plot.plot_box()
        assert box["width"] == 100 - 6 - STRIP_W
        assert box["width"] >= COLORBAR_MIN_IMAGE_WIDTH


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

    def test_the_numbers_are_strictly_inside_the_strip_height(self, take_screenshot):
        # A glyph cut off at the canvas edge leaves ink ON the edge row; an
        # intact one has a clear row above its ascender and below its
        # descender.  The strip paints every row, so only the text can tell.
        fig, _plot = _colorbar_figure()
        ink = _ink(take_screenshot(fig))
        left, right = _strip_columns(ink)
        top, bottom = _strip_rows(ink, left, right)
        text_rows = np.where(ink[:, right + 1:right + 1 + VALUE_GUTTER].any(axis=1))[0]
        assert text_rows[0] > top and text_rows[-1] < bottom

    def test_a_tiny_range_keeps_the_two_numbers_apart(self, take_screenshot):
        # The raw band stays the full ±1.5 the pixels were encoded over; only
        # the DISPLAY window collapses, so the two marks land on top of each
        # other in the middle of the strip and the text has to be held apart.
        fig, plot = _colorbar_figure()
        plot.set_display_window(-0.001, 0.001)
        gutter, _ = _value_gutter(_ink(take_screenshot(fig)))
        rows = np.where(gutter.any(axis=1))[0]
        h = gutter.shape[0]
        assert h * 0.2 < rows[0] and rows[-1] < h * 0.8, "the text left the middle"
        gaps = np.where(np.diff(rows) > 1)[0]
        assert gaps.size >= 1, "the two values were drawn on top of each other"

    def test_a_long_value_moves_the_strip_by_the_extra_gutter(self, take_screenshot):
        # "-1.2e-100" is 9 characters: the layout must reserve two more than
        # the 7-character budget, which shows as the strip sitting that much
        # further left of the panel edge — and the glyphs stay inside.
        fig, plot = _colorbar_figure(lo=-1.5, hi=1.5)
        before = _strip_columns(_ink(take_screenshot(fig)))[0]
        plot.set_display_window(-1.2e-100, 1.2e-100)
        ink = _ink(take_screenshot(fig))
        left, right = _strip_columns(ink)
        extra = _colorbar_value_width(plot._state) - VALUE_GUTTER
        assert extra == 12
        assert abs((before - left) - extra) <= 1, "the layout did not grow for the long values"
        values = ink[:, right + 1:right + 1 + VALUE_GUTTER + extra]
        value_cols = np.where(values.any(axis=0))[0]
        assert value_cols.size and value_cols[-1] < VALUE_GUTTER + extra - 1

    def test_the_strip_is_coloured_through_the_display_window(self, take_screenshot):
        # The image maps 0.2..0.6 onto the whole colormap; the strip must too,
        # saturating beyond the window, or the numbers sit beside colours the
        # image never uses.
        fig, plot = _colorbar_figure(lo=0.0, hi=1.0)
        plot.set_display_window(0.2, 0.6)
        img = take_screenshot(fig)[..., :3].astype(int)
        ink = _ink(img)
        left, right = _strip_columns(ink)
        top, bottom = _strip_rows(ink, left, right)
        column = img[top:bottom + 1, (left + right) // 2]
        h = column.shape[0]
        above, below = column[: int(h * 0.35)], column[int(h * 0.85):]
        # viridis ends: yellow (253, 231, 37) above the window, purple
        # (68, 1, 84) below it.
        assert ((above[:, 0] > 235) & (above[:, 2] < 80)).all(), \
            "above the window the strip is not saturated yellow"
        assert ((below[:, 0] < 100) & (below[:, 2] > 60)).all(), \
            "below the window the strip is not saturated purple"

    def test_a_short_strip_shows_the_maximum_alone_and_whole(self, take_screenshot):
        # 70 px tall with axes on leaves a 16 px strip: room for one value,
        # not two. The maximum is drawn, at its own place, and never cut off.
        fig, ax = apl.subplots(1, 1, figsize=(300, 70))
        x = np.linspace(0.0, 1.0, 32)
        plot = ax.imshow(np.linspace(-1.5, 1.5, 32 * 32, dtype=np.float32)
                         .reshape(32, 32), cmap="viridis", axes=[x, x], units="nm")
        plot.set_clim(-1.5, 1.5)
        plot.set_colorbar_visible(True)
        ink = _ink(take_screenshot(fig))
        left, right = _strip_columns(ink)
        top, bottom = _strip_rows(ink, left, right)
        assert bottom - top < 24, "the strip is not short in this cell"
        rows = np.where(ink[:, right + 1:right + 1 + VALUE_GUTTER].any(axis=1))[0]
        assert rows.size, "no value drawn on the short strip"
        assert np.diff(rows).max() == 1, \
            "two values were squeezed onto a strip with room for one"
        assert rows[0] > top and rows[-1] < bottom, "the lone maximum is cut off"

    def test_a_narrow_cell_draws_the_strip_without_values(self, take_screenshot):
        fig, _plot = _colorbar_figure(size=(100, 200))
        ink = _ink(take_screenshot(fig))
        # Only the gap and the panel's own border lie right of the strip now;
        # look inside the strip's rows and short of that border.
        gutter, _ = _value_gutter(ink, width=6)
        assert not gutter.any(), "values drawn where the layout dropped them"

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

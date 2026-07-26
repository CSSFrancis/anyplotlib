"""
The 1-D y-axis label must not be drawn through the tick numbers.

The label's x was a fixed ``PAD_L * 0.28``, with a comment asserting that
cleared the tick numbers "regardless of how wide those numbers are".  It did
not: at the default tick size a string like ``-5.6e-17`` reaches back past
that column, and the rotated label was drawn straight through it.

The label is now placed relative to the widest tick string, so these tests
compare where the label's ink lands with where the ticks' ink lands.  Both are
drawn into the same gutter, so they are separated by rendering each alone.

Not fixed here: a tick string wide enough to fill the gutter on its own (8
characters, e.g. ``-5.6e-17``) leaves nowhere clear to put the label.  See
``test_extreme_ticks_push_the_label_to_the_edge``.
"""
from __future__ import annotations

import numpy as np
import pytest

import anyplotlib as apl

FIG_W, FIG_H = 400, 300
PAD_L = 58
GRID_PAD = 8

WIDE_TICKS = np.linspace(0.0, 100000.0, 64)        # -> "100000" (6 chars)
NARROW_TICKS = np.linspace(0.0, 1.0, 64)           # -> "0.2"
EXTREME_TICKS = np.linspace(-5.6e-17, 5.6e-17, 64)  # -> "-5.6e-17" (8 chars)


def _gutter_ink_per_column(take_screenshot, data, label=None):
    """Ink count per column of the left axis gutter."""
    fig, ax = apl.subplots(1, 1, figsize=(FIG_W, FIG_H))
    plot = ax.plot(data)
    if label is not None:
        plot.set_ylabel(label)
    img = take_screenshot(fig)[..., :3].astype(int)
    gutter = img[:, GRID_PAD:GRID_PAD + PAD_L]
    bg = img[2, 2]
    ink = np.abs(gutter - bg).sum(axis=-1) > 40
    return ink.sum(axis=0)


def _label_columns(take_screenshot, data, label="Intensity"):
    """Columns whose ink is contributed by the label, not the ticks."""
    without = _gutter_ink_per_column(take_screenshot, data)
    with_label = _gutter_ink_per_column(take_screenshot, data, label)
    extra = with_label - without
    return {i for i, v in enumerate(extra) if v > 0}, without


class TestNoOverlap:
    def test_wide_ticks_do_not_collide_with_the_label(self, take_screenshot):
        label_cols, tick_ink = _label_columns(take_screenshot, WIDE_TICKS)
        tick_cols = {i for i, v in enumerate(tick_ink) if v > 0}
        clash = label_cols & tick_cols
        assert not clash, (
            f"label and tick numbers share columns {sorted(clash)} — "
            "the label is drawn through the ticks"
        )

    def test_narrow_ticks_do_not_collide_either(self, take_screenshot):
        label_cols, tick_ink = _label_columns(take_screenshot, NARROW_TICKS)
        tick_cols = {i for i, v in enumerate(tick_ink) if v > 0}
        assert not (label_cols & tick_cols)

    def test_label_is_actually_drawn(self, take_screenshot):
        """Guard: the tests above would pass trivially on a missing label."""
        label_cols, _ = _label_columns(take_screenshot, WIDE_TICKS)
        assert label_cols, "no label ink found at all"

    def test_label_stays_on_canvas(self, take_screenshot):
        """Shifting left must stop at the canvas edge, not run off it."""
        label_cols, _ = _label_columns(take_screenshot, EXTREME_TICKS)
        assert min(label_cols) >= 0
        assert max(label_cols) < PAD_L

    def test_extreme_ticks_push_the_label_to_the_edge(self, take_screenshot):
        """A gutter too narrow for both is not something placement can fix.

        ``-5.6e-17`` is 8 characters; at the default tick size it spans almost
        the whole 58 px gutter, leaving no clear column for a rotated label.
        The label goes as far left as it can and overlaps only the leading
        characters — better than the fixed mid-gutter position, which struck
        through the middle of every number — but eliminating the overlap needs
        a wider gutter, and PAD_L is shared across panels to keep their plot
        areas aligned.  That is a layout policy decision, not a placement one.
        """
        label_cols, tick_ink = _label_columns(take_screenshot, EXTREME_TICKS)
        assert min(label_cols) <= 6, (
            "with no room to spare the label should sit at the far left edge"
        )

    def test_wide_ticks_push_the_label_left(self, take_screenshot):
        """The mechanism, not just the outcome."""
        wide, _ = _label_columns(take_screenshot, WIDE_TICKS)
        narrow, _ = _label_columns(take_screenshot, NARROW_TICKS)
        assert min(wide) <= min(narrow), (
            f"wide ticks should move the label left or leave it "
            f"(wide starts at {min(wide)}, narrow at {min(narrow)})"
        )


class TestLogScale:
    def test_log_ticks_do_not_collide(self, take_screenshot):
        """The log branch measures its own tick width too."""
        fig, ax = apl.subplots(1, 1, figsize=(FIG_W, FIG_H))
        plot = ax.plot(np.logspace(-12, 3, 64))
        plot.set_yscale("log")
        img_no = take_screenshot(fig)[..., :3].astype(int)

        fig2, ax2 = apl.subplots(1, 1, figsize=(FIG_W, FIG_H))
        plot2 = ax2.plot(np.logspace(-12, 3, 64))
        plot2.set_yscale("log")
        plot2.set_ylabel("Counts")
        img_yes = take_screenshot(fig2)[..., :3].astype(int)

        def cols(img):
            gutter = img[:, GRID_PAD:GRID_PAD + PAD_L]
            bg = img[2, 2]
            return (np.abs(gutter - bg).sum(axis=-1) > 40).sum(axis=0)

        without, with_label = cols(img_no), cols(img_yes)
        label_cols = {i for i, v in enumerate(with_label - without) if v > 0}
        tick_cols = {i for i, v in enumerate(without) if v > 0}
        assert label_cols, "no label ink found on the log panel"
        assert not (label_cols & tick_cols)

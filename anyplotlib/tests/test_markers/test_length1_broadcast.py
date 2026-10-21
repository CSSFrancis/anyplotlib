"""
Length-1 sequences in marker kwargs broadcast like scalars.

matplotlib stores a singleton style as a 1-tuple and cycles it over the
collection, so code ported from matplotlib passes ``radius=[5]`` or
``linewidths=(1.5,)``.  Per-marker kwargs must broadcast such a value across
the group, and group-wide kwargs must unwrap it.
"""
from __future__ import annotations

import numpy as np
import pytest

import anyplotlib as apl


def _plot2d():
    fig, ax = apl.subplots(1, 1)
    return ax.imshow(np.zeros((12, 25)))


def _wire(group):
    return group.to_wire("g")


OFFSETS = [[1, 2], [3, 4], [5, 6]]


class TestPerMarkerBroadcast:
    @pytest.mark.parametrize("value", [[4.0], (4.0,), np.array([4.0])])
    def test_circles_radius(self, value):
        g = _plot2d().add_circles(OFFSETS, radius=value)
        assert _wire(g)["sizes"] == [4.0, 4.0, 4.0]

    def test_rectangles_widths_heights_angles(self):
        g = _plot2d().add_rectangles(OFFSETS, widths=[2], heights=(3,), angles=[10])
        w = _wire(g)
        assert w["widths"] == [2.0] * 3
        assert w["heights"] == [3.0] * 3
        assert w["angles"] == [10.0] * 3

    def test_arrows_uv(self):
        g = _plot2d().add_arrows(OFFSETS, U=[1], V=(2,))
        w = _wire(g)
        assert w["U"] == [1.0] * 3 and w["V"] == [2.0] * 3

    def test_set_with_length1(self):
        g = _plot2d().add_circles(OFFSETS, radius=2)
        g.set(radius=[7])
        assert _wire(g)["sizes"] == [7.0] * 3

    def test_full_length_unchanged(self):
        g = _plot2d().add_circles(OFFSETS, radius=[1, 2, 3])
        assert _wire(g)["sizes"] == [1.0, 2.0, 3.0]

    def test_wrong_length_still_rejected(self):
        with pytest.raises(ValueError):
            _plot2d().add_circles(OFFSETS, radius=[1, 2])


class TestGroupWideUnwrap:
    def test_linewidths(self):
        g = _plot2d().add_circles(OFFSETS, linewidths=(2.5,))
        assert _wire(g)["linewidth"] == 2.5

    def test_alpha(self):
        g = _plot2d().add_circles(OFFSETS, facecolors="#f00", alpha=[0.5])
        assert _wire(g)["fill_alpha"] == 0.5

    def test_fontsize(self):
        g = _plot2d().add_texts(OFFSETS, ["a", "b", "c"], fontsize=[14])
        assert _wire(g)["fontsize"] == 14

    def test_single_colour_lists(self):
        g = _plot2d().add_circles(OFFSETS, edgecolors=["#00ff00"],
                                  facecolors=("#0000ff",),
                                  hover_edgecolors=["#ffffff"])
        w = _wire(g)
        assert w["color"] == "#00ff00"
        assert w["fill_color"] == "#0000ff"
        assert w["hover_color"] == "#ffffff"

    def test_per_marker_colours_kept(self):
        cols = ["#f00", "#0f0", "#00f"]
        g = _plot2d().add_circles(OFFSETS, edgecolors=cols)
        assert _wire(g)["color"] == cols

    def test_1d_lines(self):
        fig, ax = apl.subplots(1, 1)
        plot = ax.plot(np.arange(48.0))
        g = plot.markers.add("vlines", offsets=[1, 2], linewidths=[3])
        assert _wire(g)["linewidth"] == 3.0

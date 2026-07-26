"""
Per-marker edge/face colours (matplotlib ``edgecolors=[...]`` / scatter ``c=``).

``edgecolors`` and ``facecolors`` may be a sequence parallel to the markers
instead of one colour for the whole group.  ``points`` and ``polygons`` on 1-D
panels already honoured this; every other type painted the whole group in the
first colour (or, on 2-D panels, in whatever the canvas made of being handed
an array as a ``strokeStyle``).

Canvas contents can't be read back as geometry, so these tests count pixels of
each requested colour in the rendered screenshot: a group asked for red, green
and blue markers must actually put all three on the canvas.
"""
from __future__ import annotations

import numpy as np
import pytest

import anyplotlib as apl

RGB = {
    "#ff0000": (255, 0, 0),
    "#00ff00": (0, 255, 0),
    "#0000ff": (0, 0, 255),
}
COLORS = list(RGB)


def _count(img: np.ndarray, rgb: tuple[int, int, int], tol: int = 60) -> int:
    """Pixels within *tol* of an exact RGB triple."""
    a = img[..., :3].astype(int)
    return int((np.abs(a - np.array(rgb)).sum(axis=-1) < tol).sum())


def _colors_present(img: np.ndarray) -> set[str]:
    return {c for c in COLORS if _count(img, RGB[c]) > 0}


def _image_fig(add, **kwargs):
    """A 2-D panel with one marker group added by *add*."""
    fig, ax = apl.subplots(1, 1, figsize=(400, 400))
    plot = ax.imshow(np.zeros((40, 40), dtype=np.float32))
    add(plot, **kwargs)
    return fig


def _line_fig(add, **kwargs):
    """A 1-D panel with one marker group added by *add*."""
    fig, ax = apl.subplots(1, 1, figsize=(400, 400))
    plot = ax.plot(np.zeros(40))
    add(plot, **kwargs)
    return fig


# Three well-separated positions on a 40x40 image.
OFFSETS = [[8, 8], [20, 20], [32, 32]]


# ══════════════════════════════════════════════════════════════════════════════
# 2-D panels
# ══════════════════════════════════════════════════════════════════════════════

class TestPerMarkerEdgeColors2D:
    """Every 2-D marker type must paint each marker its own edge colour."""

    @pytest.mark.parametrize("kind,extra", [
        ("circles",    {"radius": 4}),
        ("ellipses",   {"widths": 8, "heights": 5}),
        ("rectangles", {"widths": 8, "heights": 5}),
        ("squares",    {"widths": 8}),
        ("arrows",     {"U": 6, "V": 6}),
    ])
    def test_all_three_colors_rendered(self, take_screenshot, kind, extra):
        fig = _image_fig(
            lambda p, **k: p.markers.add(kind, offsets=OFFSETS,
                                         edgecolors=COLORS, linewidths=3, **k),
            **extra,
        )
        present = _colors_present(take_screenshot(fig))
        assert present == set(COLORS), (
            f"{kind}: expected all of {COLORS} on the canvas, got {sorted(present)}"
        )

    def test_lines_segments_take_their_own_colors(self, take_screenshot):
        segs = [[[4, 4], [36, 4]], [[4, 20], [36, 20]], [[4, 36], [36, 36]]]
        fig = _image_fig(
            lambda p: p.markers.add("lines", segments=segs,
                                    edgecolors=COLORS, linewidths=3)
        )
        assert _colors_present(take_screenshot(fig)) == set(COLORS)

    def test_polygons_take_their_own_colors(self, take_screenshot):
        polys = [
            [[2, 2], [12, 2], [12, 12]],
            [[14, 14], [26, 14], [26, 26]],
            [[28, 28], [38, 28], [38, 38]],
        ]
        fig = _image_fig(
            lambda p: p.markers.add("polygons", vertices_list=polys,
                                    edgecolors=COLORS, linewidths=3)
        )
        assert _colors_present(take_screenshot(fig)) == set(COLORS)

    def test_texts_take_their_own_colors(self, take_screenshot):
        fig = _image_fig(
            lambda p: p.markers.add("texts", offsets=OFFSETS,
                                    texts=["AAA", "BBB", "CCC"],
                                    edgecolors=COLORS, fontsize=20)
        )
        assert _colors_present(take_screenshot(fig)) == set(COLORS)

    def test_per_marker_facecolors(self, take_screenshot):
        """Fills are per-marker too, not just edges."""
        fig = _image_fig(
            lambda p: p.markers.add("circles", offsets=OFFSETS, radius=5,
                                    edgecolors="#ffffff", facecolors=COLORS,
                                    alpha=1.0)
        )
        assert _colors_present(take_screenshot(fig)) == set(COLORS)

    def test_shorter_sequence_cycles(self, take_screenshot):
        """A 2-colour sequence over 3 markers cycles, as matplotlib does."""
        fig = _image_fig(
            lambda p: p.markers.add("circles", offsets=OFFSETS, radius=4,
                                    edgecolors=COLORS[:2], linewidths=3)
        )
        img = take_screenshot(fig)
        # Two markers red (indices 0 and 2), one green.
        assert _count(img, RGB["#ff0000"]) > _count(img, RGB["#00ff00"])
        assert _count(img, RGB["#0000ff"]) == 0


class TestScalarColorUnchanged2D:
    """A single colour must keep painting the whole group — no regression."""

    def test_single_edgecolor_applies_to_all(self, take_screenshot):
        fig = _image_fig(
            lambda p: p.markers.add("circles", offsets=OFFSETS, radius=4,
                                    edgecolors="#ff0000", linewidths=3)
        )
        present = _colors_present(take_screenshot(fig))
        assert present == {"#ff0000"}


# ══════════════════════════════════════════════════════════════════════════════
# 1-D panels
# ══════════════════════════════════════════════════════════════════════════════

class TestPerMarkerColors1D:
    def test_vlines_take_their_own_colors(self, take_screenshot):
        fig = _line_fig(
            lambda p: p.markers.add("vlines", offsets=[[8], [20], [32]],
                                    edgecolors=COLORS, linewidths=3)
        )
        assert _colors_present(take_screenshot(fig)) == set(COLORS)

    def test_hlines_take_their_own_colors(self, take_screenshot):
        fig, ax = apl.subplots(1, 1, figsize=(400, 400))
        plot = ax.plot(np.linspace(-1.0, 1.0, 40))
        plot.markers.add("hlines", offsets=[[-0.5], [0.0], [0.5]],
                         edgecolors=COLORS, linewidths=3)
        assert _colors_present(take_screenshot(fig)) == set(COLORS)

    def test_points_take_their_own_colors(self, take_screenshot):
        """Already supported before this change — kept as a regression guard."""
        fig = _line_fig(
            lambda p: p.markers.add("points", offsets=[[8], [20], [32]],
                                    sizes=6, edgecolors=COLORS, linewidths=3)
        )
        assert _colors_present(take_screenshot(fig)) == set(COLORS)


# ══════════════════════════════════════════════════════════════════════════════
# Wire format
# ══════════════════════════════════════════════════════════════════════════════

class TestWireFormat:
    def test_color_sequence_survives_to_wire(self):
        fig, ax = apl.subplots(1, 1)
        plot = ax.imshow(np.zeros((10, 10)))
        g = plot.markers.add("circles", offsets=OFFSETS, edgecolors=COLORS)
        assert g.to_wire("gid")["color"] == COLORS

    def test_facecolor_sequence_survives_to_wire(self):
        fig, ax = apl.subplots(1, 1)
        plot = ax.imshow(np.zeros((10, 10)))
        g = plot.markers.add("circles", offsets=OFFSETS, facecolors=COLORS)
        assert g.to_wire("gid")["fill_color"] == COLORS

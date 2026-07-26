"""
Playwright tests for ``linestyle="none"`` and ``linewidth=0`` on Plot1D.

Strategy
--------
Both mean "draw no connecting line".  Canvas contents cannot be inspected as
geometry, so these tests assert on *ink*: a markers-only series must leave
far fewer coloured pixels than the same data drawn as a solid line, while
still leaving some (the markers themselves).

The data is a ramp, so a connecting line would sweep across the whole plot
area — a markers-only version of the same series is unambiguously sparser.
"""
from __future__ import annotations

import numpy as np

import anyplotlib as apl

PAD_L, PAD_R, PAD_T, PAD_B = 58, 12, 12, 42

# The series colour, chosen well away from both themes' backgrounds and grid.
LINE_COLOR = "#ff0000"


# ── helpers ───────────────────────────────────────────────────────────────────

def _plot_area(img: np.ndarray) -> np.ndarray:
    """Return just the plot rectangle, excluding the axis gutters."""
    return img[PAD_T:-PAD_B, PAD_L:-PAD_R, :3].astype(int)


def _red_ink(img: np.ndarray) -> int:
    """Count pixels in the plot area that are predominantly the line colour."""
    area = _plot_area(img)
    r, g, b = area[..., 0], area[..., 1], area[..., 2]
    return int(((r > 120) & (g < 100) & (b < 100)).sum())


def _render(take_screenshot, **plot_kwargs) -> int:
    fig, ax = apl.subplots(1, 1, figsize=(400, 300))
    ax.plot(np.linspace(0.0, 1.0, 24), color=LINE_COLOR, **plot_kwargs)
    return _red_ink(take_screenshot(fig))


# ══════════════════════════════════════════════════════════════════════════════


class TestLinestyleNone:
    def test_none_draws_less_ink_than_solid(self, take_screenshot):
        solid = _render(take_screenshot, linestyle="solid", marker="o")
        none = _render(take_screenshot, linestyle="none", marker="o")
        assert none < solid, (
            f"linestyle='none' must drop the connecting stroke "
            f"(got {none} px vs {solid} px for solid)"
        )

    def test_ink_dropped_is_the_full_span(self, take_screenshot):
        """The ink lost to ``none`` is a stroke crossing the whole plot area.

        The series is a monotonic ramp, so its connecting line spans the full
        width of the plot rectangle.  Anything less than that would mean part
        of the stroke survived.
        """
        solid = _render(take_screenshot, linestyle="solid", marker="o")
        none = _render(take_screenshot, linestyle="none", marker="o")
        plot_width = 400 - PAD_L - PAD_R
        assert solid - none > plot_width * 0.5, (
            f"expected to lose a full-width stroke, lost only {solid - none} px "
            f"across a {plot_width} px wide plot area"
        )

    def test_none_still_draws_markers(self, take_screenshot):
        """Markers-only is not the same as invisible."""
        none = _render(take_screenshot, linestyle="none", marker="o", markersize=6)
        assert none > 0, "markers must still be drawn when linestyle='none'"

    def test_none_without_markers_draws_nothing(self, take_screenshot):
        blank = _render(take_screenshot, linestyle="none", marker="none")
        assert blank == 0, (
            f"linestyle='none' with no marker must draw nothing, got {blank} px"
        )


class TestZeroLinewidth:
    def test_zero_linewidth_suppresses_stroke(self, take_screenshot):
        """A 0 width must not fall back to the 1.5 default in the renderer."""
        thin = _render(take_screenshot, linewidth=0, marker="none")
        assert thin == 0, f"linewidth=0 must draw no stroke, got {thin} px"

    def test_zero_linewidth_keeps_markers(self, take_screenshot):
        pts = _render(take_screenshot, linewidth=0, marker="o", markersize=6)
        assert pts > 0, "markers must survive linewidth=0"


class TestOverlayLineNone:
    """The same rules apply to add_line() overlays, not just the primary line."""

    def _overlay_ink(self, take_screenshot, **line_kwargs) -> int:
        fig, ax = apl.subplots(1, 1, figsize=(400, 300))
        plot = ax.plot(np.zeros(24), color="#222222", linewidth=0.5)
        plot.add_line(np.linspace(0.0, 1.0, 24), color=LINE_COLOR, **line_kwargs)
        return _red_ink(take_screenshot(fig))

    def test_overlay_none_draws_less_than_solid(self, take_screenshot):
        solid = self._overlay_ink(take_screenshot, linestyle="solid", marker="o")
        none = self._overlay_ink(take_screenshot, linestyle="none", marker="o")
        assert none < solid, (
            f"overlay linestyle='none' must drop the stroke "
            f"(got {none} px vs {solid} px)"
        )

    def test_overlay_none_with_no_marker_draws_nothing(self, take_screenshot):
        assert self._overlay_ink(take_screenshot, linestyle="none",
                                 marker="none") == 0

    def test_overlay_zero_linewidth_suppresses_stroke(self, take_screenshot):
        assert self._overlay_ink(take_screenshot, linewidth=0, marker="none") == 0

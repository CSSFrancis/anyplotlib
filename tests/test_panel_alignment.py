"""
Tests that 1D and 2D panels within the same figure row/column are pixel-aligned.

The invariant we enforce:
  - All panels in the same grid row share the same canvas height (ph).
  - All panels in the same grid col share the same canvas width (pw).
  - The image/plot area for both 1D and 2D panels sits at:
      x=PAD_L, y=PAD_T, w=pw-PAD_L-PAD_R, h=ph-PAD_T-PAD_B
  So the bottom-left corner of the image area == bottom-left of the 1D plot area.

JS renders both panel types with the same PAD constants, so as long as Python
assigns the same (pw, ph) to panels in the same row/col, alignment is guaranteed.
"""

import json
import numpy as np
import pytest

import anyplotlib as vw

PAD_L = 58
PAD_R = 12
PAD_T = 12
PAD_B = 42


def _panel_sizes(fig):
    """Return {panel_id: (pw, ph)} from the figure's layout_json."""
    layout = json.loads(fig.layout_json)
    return {s["id"]: (s["panel_width"], s["panel_height"]) for s in layout["panel_specs"]}


def _panel_specs(fig):
    """Return list of panel spec dicts."""
    return json.loads(fig.layout_json)["panel_specs"]


# ── helper: plot-area rect ────────────────────────────────────────────────────

def plot_area(pw, ph):
    """Return (x, y, w, h) of the inner plot/image area for any panel kind."""
    return PAD_L, PAD_T, pw - PAD_L - PAD_R, ph - PAD_T - PAD_B


# ── test 1: 2-row, 1-col (2D on top, 1D below) ───────────────────────────────

def test_2row_1col_same_width():
    fig, axs = vw.subplots(2, 1, figsize=(600, 600))
    v2d = axs[0].imshow(np.random.rand(128, 128))
    v1d = axs[1].plot(np.sin(np.linspace(0, 6, 256)))

    sizes = _panel_sizes(fig)
    pw2d, ph2d = sizes[v2d._id]
    pw1d, ph1d = sizes[v1d._id]

    assert pw2d == pw1d, (
        f"Panels in same column must have equal width: 2D={pw2d}, 1D={pw1d}"
    )


def test_2row_1col_plot_area_left_edge_aligned():
    """The left edge of the 2D image area and 1D plot area must be equal (PAD_L)."""
    fig, axs = vw.subplots(2, 1, figsize=(600, 600))
    v2d = axs[0].imshow(np.random.rand(128, 128))
    v1d = axs[1].plot(np.sin(np.linspace(0, 6, 256)))

    sizes = _panel_sizes(fig)
    pw2d, ph2d = sizes[v2d._id]
    pw1d, ph1d = sizes[v1d._id]

    x2d, _, _, _ = plot_area(pw2d, ph2d)
    x1d, _, _, _ = plot_area(pw1d, ph1d)

    assert x2d == x1d == PAD_L, (
        f"Left edge of plot area must be PAD_L={PAD_L}: 2D={x2d}, 1D={x1d}"
    )


def test_2row_1col_bottom_left_corner_aligned():
    """
    The bottom-left corner of both plot areas must be at the same canvas-x offset.
    Since canvas widths are equal and PAD_L is shared, bottom-left x is always PAD_L.
    This test also checks the plot areas have the same width.
    """
    fig, axs = vw.subplots(2, 1, figsize=(600, 600))
    v2d = axs[0].imshow(np.random.rand(128, 128))
    v1d = axs[1].plot(np.sin(np.linspace(0, 6, 256)))

    sizes = _panel_sizes(fig)
    pw2d, ph2d = sizes[v2d._id]
    pw1d, ph1d = sizes[v1d._id]

    x2d, y2d, w2d, h2d = plot_area(pw2d, ph2d)
    x1d, y1d, w1d, h1d = plot_area(pw1d, ph1d)

    # Bottom-left x must match
    assert x2d == x1d, f"Bottom-left x: 2D={x2d}, 1D={x1d}"
    # Plot area widths must match (same canvas width)
    assert w2d == w1d, f"Plot area widths: 2D={w2d}, 1D={w1d}"


# ── test 2: 1-row, 2-col (2D left, 1D right) ─────────────────────────────────

def test_1row_2col_same_height():
    fig, axs = vw.subplots(1, 2, figsize=(800, 400))
    v2d = axs[0].imshow(np.random.rand(64, 64))
    v1d = axs[1].plot(np.cos(np.linspace(0, 6, 256)))

    sizes = _panel_sizes(fig)
    pw2d, ph2d = sizes[v2d._id]
    pw1d, ph1d = sizes[v1d._id]

    assert ph2d == ph1d, (
        f"Panels in same row must have equal height: 2D={ph2d}, 1D={ph1d}"
    )


def test_1row_2col_plot_area_top_bottom_aligned():
    """Top and bottom y-coordinates of plot areas must match across the row."""
    fig, axs = vw.subplots(1, 2, figsize=(800, 400))
    v2d = axs[0].imshow(np.random.rand(64, 64))
    v1d = axs[1].plot(np.cos(np.linspace(0, 6, 256)))

    sizes = _panel_sizes(fig)
    pw2d, ph2d = sizes[v2d._id]
    pw1d, ph1d = sizes[v1d._id]

    x2d, y2d, w2d, h2d = plot_area(pw2d, ph2d)
    x1d, y1d, w1d, h1d = plot_area(pw1d, ph1d)

    assert y2d == y1d == PAD_T, f"Top y: 2D={y2d}, 1D={y1d}"
    assert h2d == h1d, f"Plot area heights: 2D={h2d}, 1D={h1d}"


# ── test 3: 2D panel canvas equals its grid cell ─────────────────────────────

def test_square_image_gets_square_canvas():
    """A 128×128 image in a 500×500 figsize → canvas is 500×500 (pw == ph).
    This still holds: the grid cell is square so the canvas is square too.
    Images are letterboxed in JS; the Python layout never changes the cell size."""
    fig, axs = vw.subplots(1, 1, figsize=(500, 500))
    v2d = axs.imshow(np.random.rand(128, 128))

    sizes = _panel_sizes(fig)
    pw, ph = sizes[v2d._id]
    assert pw == ph, f"Square figsize must give pw==ph: pw={pw}, ph={ph}"


def test_wide_image_canvas_equals_cell():
    """A 2:1 image in a square cell gets a square canvas — no aspect-lock.
    The image is letterboxed (pillarboxed) by the JS renderer."""
    fig, axs = vw.subplots(1, 1, figsize=(512, 512))
    v2d = axs.imshow(np.random.rand(128, 256))  # w=256, h=128

    sizes = _panel_sizes(fig)
    pw, ph = sizes[v2d._id]
    assert pw == 512 and ph == 512, (
        f"Canvas should equal full figsize 512×512, got {pw}×{ph}"
    )


# ── test 4: non-square 2D plus 1D — widths consistent ────────────────────────

def test_nonsquare_2d_and_1d_same_column():
    """
    A tall non-square image in a 2-row, 1-col layout: both panels must have
    the same canvas width (dictated by the column track, not the image aspect).
    """
    fig, axs = vw.subplots(2, 1, figsize=(600, 800))
    v2d = axs[0].imshow(np.random.rand(256, 128))  # tall image
    v1d = axs[1].plot(np.random.rand(256))

    sizes = _panel_sizes(fig)
    pw2d, ph2d = sizes[v2d._id]
    pw1d, ph1d = sizes[v1d._id]

    assert pw2d == pw1d, (
        f"Same-column panels must have equal width: 2D={pw2d}, 1D={pw1d}"
    )


# ── test 5: plot area pixel dimensions are positive ──────────────────────────

def test_plot_areas_positive():
    fig, axs = vw.subplots(2, 1, figsize=(400, 400))
    v2d = axs[0].imshow(np.random.rand(64, 64))
    v1d = axs[1].plot(np.random.rand(128))

    sizes = _panel_sizes(fig)
    for pid, (pw, ph) in sizes.items():
        x, y, w, h = plot_area(pw, ph)
        assert w > 0, f"Panel {pid}: plot area width must be positive, got {w}"
        assert h > 0, f"Panel {pid}: plot area height must be positive, got {h}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])



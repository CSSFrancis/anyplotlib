"""
tests/test_gridspec.py
======================

Tests for GridSpec / SubplotSpec indexing, the figure sizing pipeline
(_compute_cell_sizes), and per-panel plot-area alignment.

Sizing contract (all measured at the *canvas* level, before PAD margins):
  - All panels in the same grid column have the same canvas width  (pw).
  - All panels in the same grid row    have the same canvas height (ph).
  - Grid tracks are pure ratio math — no aspect-locking.
        col_px[i] = fig_width  * width_ratios[i]  / sum(width_ratios)
        row_px[r] = fig_height * height_ratios[r] / sum(height_ratios)
  - For N equal-ratio columns inside figsize (fw, fh):
        each column width == fw / N   (within 1 px rounding).
  - width_ratios / height_ratios scale the tracks proportionally.
  - The total figure area is not exceeded: sum(col tracks) <= fw,
    sum(row tracks) <= fh.
  - Images are rendered "contain" (letterboxed) in JS — the Python layout
    engine never modifies tracks because of image content.

Alignment contract (inner plot-area coordinates, shared PAD constants):
  - PAD_L=58  PAD_R=12  PAD_T=12  PAD_B=42
  - The inner plot/image area for any panel kind is:
      x=PAD_L, y=PAD_T, w=pw-PAD_L-PAD_R, h=ph-PAD_T-PAD_B
  - All panels in the same column share pw → same left/right edges.
  - All panels in the same row share ph → same top/bottom edges.
"""

from __future__ import annotations

import json
import numpy as np
import pytest

import anyplotlib as vw
from anyplotlib.figure import Figure
from anyplotlib.figure import GridSpec, SubplotSpec
from anyplotlib.axes import Axes  # noqa: F401

# PAD constants must match figure_esm.js (used in panel-alignment tests)
PAD_L, PAD_R, PAD_T, PAD_B = 58, 12, 12, 42


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _sizes(fig: Figure) -> dict[str, tuple[int, int]]:
    """Return {panel_id: (panel_width, panel_height)} from layout_json."""
    layout = json.loads(fig.layout_json)
    return {s["id"]: (s["panel_width"], s["panel_height"])
            for s in layout["panel_specs"]}


def _specs(fig: Figure) -> list[dict]:
    return json.loads(fig.layout_json)["panel_specs"]


def _layout(fig: Figure) -> dict:
    return json.loads(fig.layout_json)


def approx(a, b, tol=1):
    """True when two integer pixel values are within `tol` pixels."""
    return abs(a - b) <= tol


# ─────────────────────────────────────────────────────────────────────────────
# Part 1 – GridSpec / SubplotSpec indexing
# ─────────────────────────────────────────────────────────────────────────────

class TestGridSpecIndexing:

    def test_integer_index(self):
        gs = GridSpec(3, 3)
        s = gs[1, 2]
        assert s.row_start == 1 and s.row_stop == 2
        assert s.col_start == 2 and s.col_stop == 3

    def test_negative_index(self):
        gs = GridSpec(3, 4)
        s = gs[-1, -2]
        assert s.row_start == 2 and s.row_stop == 3   # last row
        assert s.col_start == 2 and s.col_stop == 3   # second-to-last col

    def test_full_slice(self):
        gs = GridSpec(2, 4)
        s = gs[0, :]    # entire first row
        assert s.row_start == 0 and s.row_stop == 1
        assert s.col_start == 0 and s.col_stop == 4

    def test_partial_slice(self):
        gs = GridSpec(3, 4)
        s = gs[1, 1:3]
        assert s.row_start == 1 and s.row_stop == 2
        assert s.col_start == 1 and s.col_stop == 3

    def test_row_span(self):
        gs = GridSpec(4, 2)
        s = gs[1:3, 0]
        assert s.row_start == 1 and s.row_stop == 3
        assert s.col_start == 0 and s.col_stop == 1

    def test_full_row_and_col_span(self):
        gs = GridSpec(3, 3)
        s = gs[:, :]
        assert s.row_start == 0 and s.row_stop == 3
        assert s.col_start == 0 and s.col_stop == 3

    def test_last_row_full_col_span(self):
        """gs[-1, :] should select the last row across all columns."""
        gs = GridSpec(3, 4)
        s = gs[-1, :]
        assert s.row_start == 2 and s.row_stop == 3
        assert s.col_start == 0 and s.col_stop == 4

    def test_multi_row_multi_col_span(self):
        """gs[0:2, 1:3] spans rows 0–1 and cols 1–2."""
        gs = GridSpec(4, 4)
        s = gs[0:2, 1:3]
        assert s.row_start == 0 and s.row_stop == 2
        assert s.col_start == 1 and s.col_stop == 3

    # --- error cases ---

    def test_slice_step_raises(self):
        gs = GridSpec(3, 3)
        with pytest.raises(ValueError, match="step"):
            _ = gs[0, 0:3:2]

    def test_out_of_bounds_int_row_raises(self):
        gs = GridSpec(2, 2)
        with pytest.raises(IndexError):
            _ = gs[5, 0]

    def test_out_of_bounds_int_col_raises(self):
        gs = GridSpec(2, 2)
        with pytest.raises(IndexError):
            _ = gs[0, 10]

    def test_out_of_bounds_negative_raises(self):
        gs = GridSpec(2, 2)
        with pytest.raises(IndexError):
            _ = gs[-5, 0]

    def test_empty_slice_raises(self):
        """A slice that produces no cells (start >= stop) must raise."""
        gs = GridSpec(3, 3)
        with pytest.raises(IndexError):
            _ = gs[2:2, 0]   # start == stop → empty

    def test_bad_index_raises(self):
        gs = GridSpec(2, 2)
        with pytest.raises(IndexError):
            _ = gs[0]           # must be 2-tuple

    def test_wrong_index_type_raises(self):
        gs = GridSpec(2, 2)
        with pytest.raises(IndexError):
            _ = gs["a", 0]

    def test_wrong_width_ratios_length_raises(self):
        with pytest.raises(ValueError, match="width_ratios"):
            GridSpec(2, 3, width_ratios=[1, 2])   # length 2 ≠ ncols 3

    def test_wrong_height_ratios_length_raises(self):
        with pytest.raises(ValueError, match="height_ratios"):
            GridSpec(2, 3, height_ratios=[1, 2, 3])  # length 3 ≠ nrows 2

    def test_default_ratios_are_equal(self):
        gs = GridSpec(2, 3)
        assert gs.width_ratios  == [1, 1, 1]
        assert gs.height_ratios == [1, 1]

    def test_custom_ratios_stored(self):
        gs = GridSpec(2, 3, width_ratios=[2, 1, 1], height_ratios=[3, 1])
        assert gs.width_ratios  == [2, 1, 1]
        assert gs.height_ratios == [3, 1]

    def test_subplot_spec_parent_gs(self):
        """SubplotSpec must reference the GridSpec it came from."""
        gs = GridSpec(2, 2)
        s = gs[0, 1]
        assert s._gs is gs

    def test_subplot_spec_repr(self):
        gs = GridSpec(2, 2)
        s = gs[0, 1]
        r = repr(s)
        assert "0:1" in r and "1:2" in r

    def test_gridspec_repr(self):
        gs = GridSpec(3, 4)
        assert "3" in repr(gs) and "4" in repr(gs)


# ─────────────────────────────────────────────────────────────────────────────
# Part 2 – subplots() convenience API
# ─────────────────────────────────────────────────────────────────────────────

class TestSubplotsAPI:

    def test_1x1_returns_scalar_axes(self):
        fig, ax = vw.subplots(1, 1)
        assert isinstance(ax, Axes)

    def test_1xN_returns_1d_array(self):
        fig, axs = vw.subplots(1, 3)
        assert axs.shape == (3,)
        assert all(isinstance(a, Axes) for a in axs)

    def test_Nx1_returns_1d_array(self):
        fig, axs = vw.subplots(3, 1)
        assert axs.shape == (3,)

    def test_NxM_returns_2d_array(self):
        fig, axs = vw.subplots(2, 3)
        assert axs.shape == (2, 3)

    def test_axes_specs_match_positions(self):
        fig, axs = vw.subplots(2, 3)
        for r in range(2):
            for c in range(3):
                ax = axs[r, c]
                assert ax._spec.row_start == r
                assert ax._spec.col_start == c

    def test_figure_nrows_ncols(self):
        fig, _ = vw.subplots(3, 4)
        assert fig._nrows == 3 and fig._ncols == 4

    def test_figsize_stored(self):
        fig, _ = vw.subplots(1, 1, figsize=(800, 600))
        assert fig.fig_width == 800 and fig.fig_height == 600

    def test_width_ratios_forwarded(self):
        fig, _ = vw.subplots(1, 3, width_ratios=[2, 1, 1])
        assert fig._width_ratios == [2, 1, 1]

    def test_height_ratios_forwarded(self):
        fig, _ = vw.subplots(3, 1, height_ratios=[1, 2, 1])
        assert fig._height_ratios == [1, 2, 1]

    def test_sharex_stored(self):
        fig, _ = vw.subplots(2, 1, sharex=True)
        assert fig._sharex is True

    def test_gridspec_kw_width_ratios(self):
        """gridspec_kw={'width_ratios': ...} should work like width_ratios=."""
        fig1, _ = vw.subplots(1, 2, width_ratios=[2, 1], figsize=(300, 100))
        fig2, _ = vw.subplots(1, 2, gridspec_kw={"width_ratios": [2, 1]}, figsize=(300, 100))
        assert fig1._width_ratios == fig2._width_ratios == [2, 1]

    def test_gridspec_kw_height_ratios(self):
        fig1, _ = vw.subplots(2, 1, height_ratios=[3, 1], figsize=(100, 400))
        fig2, _ = vw.subplots(2, 1, gridspec_kw={"height_ratios": [3, 1]}, figsize=(100, 400))
        assert fig1._height_ratios == fig2._height_ratios == [3, 1]


# ─────────────────────────────────────────────────────────────────────────────
# Part 3 – _compute_cell_sizes: equal-ratio grids (no images)
# ─────────────────────────────────────────────────────────────────────────────

class TestEqualRatioSizing:
    """1D-only panels, equal ratios: each track should be fw/ncols × fh/nrows."""

    def test_1x1_1d(self):
        fig, ax = vw.subplots(1, 1, figsize=(400, 300))
        v = ax.plot(np.zeros(10))
        pw, ph = _sizes(fig)[v._id]
        assert pw == 400 and ph == 300

    def test_2x1_equal_heights(self):
        fig, axs = vw.subplots(2, 1, figsize=(400, 600))
        v0 = axs[0].plot(np.zeros(10))
        v1 = axs[1].plot(np.zeros(10))
        s = _sizes(fig)
        pw0, ph0 = s[v0._id]
        pw1, ph1 = s[v1._id]
        assert pw0 == pw1, f"widths should match: {pw0} vs {pw1}"
        assert approx(ph0, 300) and approx(ph1, 300), \
            f"each row height should be 300, got {ph0}, {ph1}"

    def test_1x2_equal_widths(self):
        fig, axs = vw.subplots(1, 2, figsize=(600, 300))
        v0 = axs[0].plot(np.zeros(10))
        v1 = axs[1].plot(np.zeros(10))
        s = _sizes(fig)
        pw0, ph0 = s[v0._id]
        pw1, ph1 = s[v1._id]
        assert ph0 == ph1, f"heights should match: {ph0} vs {ph1}"
        assert approx(pw0, 300) and approx(pw1, 300), \
            f"each column width should be 300, got {pw0}, {pw1}"

    def test_3x3_equal_all(self):
        fig, axs = vw.subplots(3, 3, figsize=(600, 600))
        # Attach 1D plots to all 9 cells
        plots = [[axs[r, c].plot(np.zeros(10)) for c in range(3)] for r in range(3)]
        s = _sizes(fig)
        for r in range(3):
            for c in range(3):
                pw, ph = s[plots[r][c]._id]
                assert approx(pw, 200), f"[{r},{c}] pw={pw}, expected 200"
                assert approx(ph, 200), f"[{r},{c}] ph={ph}, expected 200"

    def test_total_width_not_exceeded(self):
        fig, axs = vw.subplots(1, 3, figsize=(500, 200))
        plots = [axs[c].plot(np.zeros(10)) for c in range(3)]
        s = _sizes(fig)
        total_w = sum(s[p._id][0] for p in plots)
        assert total_w <= 500 + 3, f"total_w={total_w} exceeds figsize width 500"

    def test_total_height_not_exceeded(self):
        fig, axs = vw.subplots(3, 1, figsize=(200, 500))
        plots = [axs[r].plot(np.zeros(10)) for r in range(3)]
        s = _sizes(fig)
        total_h = sum(s[p._id][1] for p in plots)
        assert total_h <= 500 + 3, f"total_h={total_h} exceeds figsize height 500"


# ───────────────────────────���─────────────────────────────────────────────────
# Part 4 – _compute_cell_sizes: width_ratios / height_ratios
# ─────────────────────────────────────────────────────────────────────────────

class TestRatioSizing:
    """Verify that width/height ratios correctly scale the tracks."""

    def test_2col_2to1_width_ratio(self):
        """Left column 2× wider than right column."""
        fig, axs = vw.subplots(1, 2, figsize=(600, 200),
                               width_ratios=[2, 1])
        v0 = axs[0].plot(np.zeros(10))
        v1 = axs[1].plot(np.zeros(10))
        s = _sizes(fig)
        pw0 = s[v0._id][0]
        pw1 = s[v1._id][0]
        # expected: pw0 = 400, pw1 = 200
        assert approx(pw0, 400, tol=2), f"left pw={pw0}, expected 400"
        assert approx(pw1, 200, tol=2), f"right pw={pw1}, expected 200"
        assert approx(pw0, 2 * pw1, tol=2), f"pw0 should be 2×pw1: {pw0} vs {pw1}"

    def test_2row_3to1_height_ratio(self):
        """Top row 3× taller than bottom row."""
        fig, axs = vw.subplots(2, 1, figsize=(200, 800),
                               height_ratios=[3, 1])
        v0 = axs[0].plot(np.zeros(10))
        v1 = axs[1].plot(np.zeros(10))
        s = _sizes(fig)
        ph0 = s[v0._id][1]
        ph1 = s[v1._id][1]
        assert approx(ph0, 600, tol=2), f"top ph={ph0}, expected 600"
        assert approx(ph1, 200, tol=2), f"bottom ph={ph1}, expected 200"
        assert approx(ph0, 3 * ph1, tol=3), f"ph0 should be 3×ph1: {ph0} vs {ph1}"

    def test_3col_equal_after_normalisation(self):
        """Ratios [2, 2, 2] → same as [1, 1, 1] → equal widths."""
        fig_eq,  axs_eq  = vw.subplots(1, 3, figsize=(600, 100))
        fig_rat, axs_rat = vw.subplots(1, 3, figsize=(600, 100),
                                       width_ratios=[2, 2, 2])
        for i in range(3):
            axs_eq[i].plot(np.zeros(5))
            axs_rat[i].plot(np.zeros(5))

        s_eq  = sorted(pw for pw, ph in _sizes(fig_eq).values())
        s_rat = sorted(pw for pw, ph in _sizes(fig_rat).values())
        for a, b in zip(s_eq, s_rat):
            assert approx(a, b, tol=1), f"equal vs scaled ratio: {a} vs {b}"

    def test_ratios_reflected_in_layout_json(self):
        """layout_json must carry the correct ratios."""
        fig, _ = vw.subplots(2, 2,
                             width_ratios=[1, 3],
                             height_ratios=[2, 1])
        layout = _layout(fig)
        assert layout["width_ratios"]  == [1, 3]
        assert layout["height_ratios"] == [2, 1]

    def test_nrows_ncols_in_layout_json(self):
        fig, _ = vw.subplots(3, 4)
        layout = _layout(fig)
        assert layout["nrows"] == 3
        assert layout["ncols"] == 4

    def test_panel_row_col_indices_in_layout_json(self):
        """Each panel spec must carry the correct row/col start-stop."""
        fig, axs = vw.subplots(2, 3, figsize=(600, 400))
        for r in range(2):
            for c in range(3):
                axs[r, c].plot(np.zeros(5))
        specs = {(s["row_start"], s["col_start"]): s for s in _specs(fig)}
        for r in range(2):
            for c in range(3):
                s = specs[(r, c)]
                assert s["row_start"] == r and s["row_stop"] == r + 1
                assert s["col_start"] == c and s["col_stop"] == c + 1


# ─────────────────────────────────────────────────────────────────────────────
# Part 5 – _compute_cell_sizes: 2D panels obey pure ratio math (no aspect-lock)
# ─────────────────────────────────────────────────────────────────────────────

class Test2DPanelLayout:
    """2D panels must receive exactly the canvas size their grid cell dictates.

    Images are rendered "contain" (letterboxed) by the JS renderer, so the
    Python layout engine never shrinks tracks to match image aspect ratios.
    """

    def test_2d_panel_gets_full_cell_width(self):
        """A 2D panel's canvas width equals the grid-ratio column width."""
        fig, ax = vw.subplots(1, 1, figsize=(400, 300))
        v = ax.imshow(np.zeros((128, 128)))
        pw, ph = _sizes(fig)[v._id]
        assert pw == 400, f"expected pw=400, got {pw}"
        assert ph == 300, f"expected ph=300, got {ph}"

    def test_2d_nonsquare_canvas_from_nonsquare_figsize(self):
        """Non-square figsize → non-square canvas even for a square image."""
        fig, ax = vw.subplots(1, 1, figsize=(600, 200))
        v = ax.imshow(np.zeros((128, 128)))
        pw, ph = _sizes(fig)[v._id]
        assert pw == 600 and ph == 200, f"expected 600×200, got {pw}×{ph}"

    def test_wide_image_does_not_shrink_canvas(self):
        """Wide image (2:1) in a square cell — canvas stays square."""
        fig, ax = vw.subplots(1, 1, figsize=(400, 400))
        v = ax.imshow(np.zeros((128, 256)))   # H=128, W=256
        pw, ph = _sizes(fig)[v._id]
        assert pw == 400 and ph == 400, f"expected 400×400, got {pw}×{ph}"

    def test_tall_image_does_not_shrink_canvas(self):
        """Tall image (1:2) in a square cell — canvas stays square."""
        fig, ax = vw.subplots(1, 1, figsize=(400, 400))
        v = ax.imshow(np.zeros((256, 128)))   # H=256, W=128
        pw, ph = _sizes(fig)[v._id]
        assert pw == 400 and ph == 400, f"expected 400×400, got {pw}×{ph}"

    def test_2d_and_1d_same_row_same_height(self):
        """2D and 1D panels in the same row must have the same canvas height."""
        fig, axs = vw.subplots(1, 2, figsize=(800, 400))
        v2d = axs[0].imshow(np.zeros((128, 128)))
        v1d = axs[1].plot(np.zeros(256))
        s = _sizes(fig)
        ph2d = s[v2d._id][1]
        ph1d = s[v1d._id][1]
        assert ph2d == ph1d, \
            f"same-row panels must have equal height: 2D={ph2d}, 1D={ph1d}"

    def test_2d_and_1d_same_col_same_width(self):
        """2D and 1D panels in the same column must have the same canvas width."""
        fig, axs = vw.subplots(2, 1, figsize=(400, 800))
        v2d = axs[0].imshow(np.zeros((128, 128)))
        v1d = axs[1].plot(np.zeros(256))
        s = _sizes(fig)
        pw2d = s[v2d._id][0]
        pw1d = s[v1d._id][0]
        assert pw2d == pw1d, \
            f"same-col panels must have equal width: 2D={pw2d}, 1D={pw1d}"

    def test_image_does_not_affect_sibling_panel_size(self):
        """Adding an image to one panel must NOT change a sibling panel's dimensions.

        This is the key regression test for the old aspect-lock bug:
        a square image in row-0 of a height_ratios=[2,1] layout used to
        shrink the shared column from 800 px to 333 px.
        """
        fig, axs = vw.subplots(2, 1, figsize=(800, 600),
                               height_ratios=[2, 1])
        v2d = axs[0].imshow(np.zeros((256, 256)))
        v1d = axs[1].plot(np.zeros(10))
        s = _sizes(fig)
        pw2d, ph2d = s[v2d._id]
        pw1d, ph1d = s[v1d._id]
        # Both panels must share the full figure width
        assert pw2d == 800, f"2D panel width should be 800, got {pw2d}"
        assert pw1d == 800, f"1D panel width should be 800, got {pw1d}"
        # Heights follow height_ratios=[2,1] → 400 and 200
        assert approx(ph2d, 400, tol=2), f"2D panel height should be ~400, got {ph2d}"
        assert approx(ph1d, 200, tol=2), f"1D panel height should be ~200, got {ph1d}"

    def test_two_2d_panels_same_col_same_width(self):
        """Two 2D panels with different aspect ratios in the same column
        must both get the column width — no convergence loop needed."""
        fig, axs = vw.subplots(2, 1, figsize=(400, 800))
        vA = axs[0].imshow(np.zeros((128, 128)))   # square
        vB = axs[1].imshow(np.zeros((128, 64)))    # wide
        s = _sizes(fig)
        pwA, phA = s[vA._id]
        pwB, phB = s[vB._id]
        assert pwA == pwB == 400, \
            f"Both 2D panels in same col must have pw=400: {pwA}, {pwB}"

    def test_minimum_canvas_size_floor(self):
        """Even a tiny figsize must produce canvas size ≥ 64 px."""
        fig, ax = vw.subplots(1, 1, figsize=(10, 10))
        v = ax.imshow(np.zeros((128, 128)))
        pw, ph = _sizes(fig)[v._id]
        assert pw >= 64 and ph >= 64, f"min size floor: {pw}×{ph}"


# ─────────────────────────────────────────────────────────────────────────────
# Part 6 – layout_json structure and live update
# ─────────────────────────────────────────────────────────────────────────────

class TestLayoutJson:

    def test_layout_json_has_required_keys(self):
        fig, _ = vw.subplots(2, 2)
        layout = _layout(fig)
        for key in ("nrows", "ncols", "width_ratios", "height_ratios",
                    "fig_width", "fig_height", "panel_specs", "share_groups"):
            assert key in layout, f"missing key '{key}' in layout_json"

    def test_panel_specs_has_required_keys(self):
        fig, ax = vw.subplots(1, 1)
        ax.plot(np.zeros(5))
        spec = _specs(fig)[0]
        for key in ("id", "kind", "row_start", "row_stop",
                    "col_start", "col_stop", "panel_width", "panel_height"):
            assert key in spec, f"missing key '{key}' in panel_spec"

    def test_panel_kind_1d(self):
        fig, ax = vw.subplots(1, 1)
        ax.plot(np.zeros(5))
        assert _specs(fig)[0]["kind"] == "1d"

    def test_panel_kind_2d(self):
        fig, ax = vw.subplots(1, 1)
        ax.imshow(np.zeros((32, 32)))
        assert _specs(fig)[0]["kind"] == "2d"

    def test_sharex_group_in_layout(self):
        fig, axs = vw.subplots(2, 1, sharex=True)
        axs[0].plot(np.zeros(5))
        axs[1].plot(np.zeros(5))
        layout = _layout(fig)
        assert "x" in layout["share_groups"], "sharex=True must produce 'x' share group"
        group = layout["share_groups"]["x"][0]
        assert len(group) == 2

    def test_sharey_group_in_layout(self):
        fig, axs = vw.subplots(1, 2, sharey=True)
        axs[0].plot(np.zeros(5))
        axs[1].plot(np.zeros(5))
        layout = _layout(fig)
        assert "y" in layout["share_groups"]

    def test_no_share_groups_when_false(self):
        fig, axs = vw.subplots(2, 1)
        axs[0].plot(np.zeros(5))
        axs[1].plot(np.zeros(5))
        layout = _layout(fig)
        assert layout["share_groups"] == {}

    def test_layout_updates_on_resize(self):
        """fig_width/fig_height change must propagate into layout_json."""
        fig, ax = vw.subplots(1, 1, figsize=(400, 300))
        ax.plot(np.zeros(5))
        fig.fig_width = 800
        fig.fig_height = 600
        layout = _layout(fig)
        assert layout["fig_width"]  == 800
        assert layout["fig_height"] == 600
        pw, ph = list(_sizes(fig).values())[0]
        assert pw == 800 and ph == 600

    def test_panel_sizes_update_after_adding_second_panel(self):
        """
        Add a second panel after the first.  Both must get updated sizes
        (the column or row track must be recalculated).
        """
        fig, axs = vw.subplots(2, 1, figsize=(400, 400))
        v0 = axs[0].plot(np.zeros(5))
        # At this point only one panel is registered
        s_before = _sizes(fig)[v0._id]
        # Add second panel
        v1 = axs[1].plot(np.zeros(5))
        s = _sizes(fig)
        ph0 = s[v0._id][1]
        ph1 = s[v1._id][1]
        assert ph0 == ph1, f"after adding 2nd panel, row heights must equalise: {ph0} vs {ph1}"
        assert approx(ph0, 200, tol=2), f"each row should be 200 px, got {ph0}"

    def test_panel_count_in_layout(self):
        fig, axs = vw.subplots(2, 3, figsize=(600, 400))
        for r in range(2):
            for c in range(3):
                axs[r, c].plot(np.zeros(5))
        assert len(_specs(fig)) == 6

    def test_figure_repr(self):
        fig, _ = vw.subplots(2, 3, figsize=(600, 400))
        r = repr(fig)
        assert "2x3" in r

    def test_get_axes_order(self):
        """get_axes() must return axes sorted row-major (top-left → bottom-right)."""
        fig, axs = vw.subplots(2, 2, figsize=(400, 400))
        for r in range(2):
            for c in range(2):
                axs[r, c].plot(np.zeros(5))
        ordered = fig.get_axes()
        positions = [(a._spec.row_start, a._spec.col_start) for a in ordered]
        assert positions == sorted(positions), f"axes not in row-major order: {positions}"


# ─────────────────────────────────────────────────────────────────────────────
# Part 7 – edge cases
# ─────────────────────────────────────────────────────────────────────────────

class TestEdgeCases:

    def test_single_row_many_cols(self):
        fig, axs = vw.subplots(1, 5, figsize=(500, 100))
        plots = [axs[c].plot(np.zeros(5)) for c in range(5)]
        s = _sizes(fig)
        widths = [s[p._id][0] for p in plots]
        heights = [s[p._id][1] for p in plots]
        # All same height
        assert len(set(heights)) == 1, f"all heights must be equal: {heights}"
        # Each ~100 px wide
        for w in widths:
            assert approx(w, 100, tol=2), f"width {w} should be ≈100"

    def test_single_col_many_rows(self):
        fig, axs = vw.subplots(5, 1, figsize=(100, 500))
        plots = [axs[r].plot(np.zeros(5)) for r in range(5)]
        s = _sizes(fig)
        widths  = [s[p._id][0] for p in plots]
        heights = [s[p._id][1] for p in plots]
        assert len(set(widths)) == 1, f"all widths must be equal: {widths}"
        for h in heights:
            assert approx(h, 100, tol=2), f"height {h} should be ≈100"

    def test_add_subplot_by_int(self):
        """add_subplot(int) should map correctly to row/col."""
        fig = Figure(2, 3, figsize=(600, 400))
        ax = fig.add_subplot(4)   # index 4 → row=1, col=1
        assert ax._spec.row_start == 1
        assert ax._spec.col_start == 1

    def test_add_subplot_by_tuple(self):
        fig = Figure(2, 3, figsize=(600, 400))
        ax = fig.add_subplot((0, 2))
        assert ax._spec.row_start == 0
        assert ax._spec.col_start == 2

    def test_add_subplot_by_subplot_spec(self):
        fig = Figure(3, 3, figsize=(300, 300))
        gs = GridSpec(3, 3)
        spec = gs[1:3, 0:2]
        ax = fig.add_subplot(spec)
        assert ax._spec.row_start == 1
        assert ax._spec.row_stop  == 3
        assert ax._spec.col_start == 0
        assert ax._spec.col_stop  == 2

    def test_replacing_plot_preserves_panel_id(self):
        """Calling imshow/plot a second time on the same Axes must reuse panel id."""
        fig, ax = vw.subplots(1, 1)
        v1 = ax.plot(np.zeros(5))
        pid1 = v1._id
        v2 = ax.imshow(np.zeros((32, 32)))
        pid2 = v2._id
        assert pid1 == pid2, "replacing plot must reuse the same panel id"

    def test_2d_canvas_equals_cell_allocation(self):
        """Non-square figsize with a square image → canvas equals the full cell
        (no aspect-lock shrinking).  The image is letterboxed by the JS renderer."""
        fig, ax = vw.subplots(1, 1, figsize=(600, 300))
        v = ax.imshow(np.zeros((128, 128)))
        pw, ph = _sizes(fig)[v._id]
        assert pw == 600 and ph == 300, \
            f"canvas should equal full figsize 600×300, got {pw}×{ph}"

    def test_layout_json_is_valid_json(self):
        fig, axs = vw.subplots(2, 2, figsize=(400, 400))
        for r in range(2):
            for c in range(2):
                axs[r, c].plot(np.zeros(5))
        # Should not raise
        json.loads(fig.layout_json)

    def test_add_subplot_bad_type_raises(self):
        fig = Figure(2, 2, figsize=(200, 200))
        with pytest.raises(TypeError):
            fig.add_subplot("bad")

    def test_add_subplot_by_subplot_spec_is_identity(self):
        """add_subplot(SubplotSpec) must use the spec exactly — no re-wrapping."""
        fig = Figure(3, 3, figsize=(300, 300))
        gs = GridSpec(3, 3)
        spec = gs[1:3, 0:2]
        ax = fig.add_subplot(spec)
        assert ax._spec is spec   # same object, not a copy

    def test_figure_add_subplot_with_gridspec_typical_workflow(self):
        """Mirror the typical matplotlib workflow:
        gs = GridSpec(2, 2); fig.add_subplot(gs[0, :]); etc."""
        fig = Figure(2, 2, figsize=(400, 400))
        gs = GridSpec(2, 2)
        ax_top = fig.add_subplot(gs[0, :])   # top row, full width
        ax_bl  = fig.add_subplot(gs[1, 0])   # bottom-left
        ax_br  = fig.add_subplot(gs[1, 1])   # bottom-right
        assert ax_top._spec.col_start == 0 and ax_top._spec.col_stop == 2
        assert ax_bl._spec.row_start  == 1 and ax_bl._spec.col_start == 0
        assert ax_br._spec.row_start  == 1 and ax_br._spec.col_start == 1

    def test_figsize_in_layout_json(self):
        fig, ax = vw.subplots(1, 1, figsize=(777, 555))
        ax.plot(np.zeros(5))
        layout = _layout(fig)
        assert layout["fig_width"]  == 777
        assert layout["fig_height"] == 555


# ─────────────────────────────────────────────────────────────────────────────
# Part 8 – Panel alignment
# ─────────────────────────────────────────────────────────────────────────────

def _plot_area(pw: int, ph: int) -> tuple[int, int, int, int]:
    """Return (x, y, w, h) of the inner plot/image area for any panel kind.

    Both 1-D and 2-D panels use the same PAD constants in figure_esm.js,
    so as long as Python assigns the same (pw, ph) to sibling panels they
    are guaranteed to be pixel-aligned inside the shared canvas grid cell.
    """
    return PAD_L, PAD_T, pw - PAD_L - PAD_R, ph - PAD_T - PAD_B


class TestPanelAlignment:
    """Same-row / same-column panels must share canvas dimensions and
    therefore produce identical inner plot-area coordinates."""

    # ── two-row, one-column ───────────────────────────────────────────────

    def test_2row_1col_same_width(self):
        fig, axs = vw.subplots(2, 1, figsize=(600, 600))
        v2d = axs[0].imshow(np.random.rand(128, 128))
        v1d = axs[1].plot(np.sin(np.linspace(0, 6, 256)))
        s = _sizes(fig)
        pw2d = s[v2d._id][0]
        pw1d = s[v1d._id][0]
        assert pw2d == pw1d, (
            f"Panels in same column must have equal width: 2D={pw2d}, 1D={pw1d}"
        )

    def test_2row_1col_left_edge_aligned(self):
        """Left edge of the 2D image area and 1D plot area must both be PAD_L."""
        fig, axs = vw.subplots(2, 1, figsize=(600, 600))
        v2d = axs[0].imshow(np.random.rand(128, 128))
        v1d = axs[1].plot(np.sin(np.linspace(0, 6, 256)))
        s = _sizes(fig)
        x2d = _plot_area(*s[v2d._id])[0]
        x1d = _plot_area(*s[v1d._id])[0]
        assert x2d == x1d == PAD_L, (
            f"Left edge must be PAD_L={PAD_L}: 2D={x2d}, 1D={x1d}"
        )

    def test_2row_1col_plot_area_widths_equal(self):
        """Plot-area widths must match when panels share a column."""
        fig, axs = vw.subplots(2, 1, figsize=(600, 600))
        v2d = axs[0].imshow(np.random.rand(128, 128))
        v1d = axs[1].plot(np.sin(np.linspace(0, 6, 256)))
        s = _sizes(fig)
        w2d = _plot_area(*s[v2d._id])[2]
        w1d = _plot_area(*s[v1d._id])[2]
        assert w2d == w1d, f"Plot area widths: 2D={w2d}, 1D={w1d}"

    # ── one-row, two-column ───────────────────────────────────────────────

    def test_1row_2col_same_height(self):
        fig, axs = vw.subplots(1, 2, figsize=(800, 400))
        v2d = axs[0].imshow(np.random.rand(64, 64))
        v1d = axs[1].plot(np.cos(np.linspace(0, 6, 256)))
        s = _sizes(fig)
        ph2d = s[v2d._id][1]
        ph1d = s[v1d._id][1]
        assert ph2d == ph1d, (
            f"Panels in same row must have equal height: 2D={ph2d}, 1D={ph1d}"
        )

    def test_1row_2col_top_bottom_aligned(self):
        """Top and bottom y-coordinates of plot areas must match across the row."""
        fig, axs = vw.subplots(1, 2, figsize=(800, 400))
        v2d = axs[0].imshow(np.random.rand(64, 64))
        v1d = axs[1].plot(np.cos(np.linspace(0, 6, 256)))
        s = _sizes(fig)
        y2d, h2d = _plot_area(*s[v2d._id])[1], _plot_area(*s[v2d._id])[3]
        y1d, h1d = _plot_area(*s[v1d._id])[1], _plot_area(*s[v1d._id])[3]
        assert y2d == y1d == PAD_T, f"Top y: 2D={y2d}, 1D={y1d}"
        assert h2d == h1d, f"Plot area heights: 2D={h2d}, 1D={h1d}"

    # ── 2D panel canvas equals its grid cell ─────────────────────────────

    def test_square_image_gets_square_canvas(self):
        """A 128×128 image in a 500×500 figsize → canvas is 500×500 (pw == ph).
        Images are letterboxed in JS; the Python layout never changes the cell."""
        fig, axs = vw.subplots(1, 1, figsize=(500, 500))
        v2d = axs.imshow(np.random.rand(128, 128))
        pw, ph = _sizes(fig)[v2d._id]
        assert pw == ph, f"Square figsize must give pw==ph: pw={pw}, ph={ph}"

    def test_wide_image_canvas_equals_cell(self):
        """A 2:1 image in a square cell gets a square canvas — no aspect-lock."""
        fig, axs = vw.subplots(1, 1, figsize=(512, 512))
        v2d = axs.imshow(np.random.rand(128, 256))  # w=256, h=128
        pw, ph = _sizes(fig)[v2d._id]
        assert pw == 512 and ph == 512, (
            f"Canvas should equal full figsize 512×512, got {pw}×{ph}"
        )

    # ── non-square 2D panel plus 1D panel — column width consistent ───────

    def test_nonsquare_2d_and_1d_same_column(self):
        """A tall non-square image in a 2-row, 1-col layout must not affect the
        1D panel's canvas width — both must equal the column track width."""
        fig, axs = vw.subplots(2, 1, figsize=(600, 800))
        v2d = axs[0].imshow(np.random.rand(256, 128))  # tall image
        v1d = axs[1].plot(np.random.rand(256))
        s = _sizes(fig)
        pw2d = s[v2d._id][0]
        pw1d = s[v1d._id][0]
        assert pw2d == pw1d, (
            f"Same-column panels must have equal width: 2D={pw2d}, 1D={pw1d}"
        )

    # ── plot-area dimensions are positive ─────────────────────────────────

    def test_plot_areas_positive(self):
        fig, axs = vw.subplots(2, 1, figsize=(400, 400))
        v2d = axs[0].imshow(np.random.rand(64, 64))
        v1d = axs[1].plot(np.random.rand(128))
        for pid, (pw, ph) in _sizes(fig).items():
            x, y, w, h = _plot_area(pw, ph)
            assert w > 0, f"Panel {pid}: plot area width must be positive, got {w}"
            assert h > 0, f"Panel {pid}: plot area height must be positive, got {h}"


# ─────────────────────────────────────────────────────────────────────────────
# Part 9 – Figure + GridSpec workflow (bare Figure auto-syncs to GridSpec)
# ─────────────────────────────────────────────────────────────────────────────

class TestFigureGridSpecWorkflow:
    """Tests for the Figure + GridSpec workflow where Figure is created without
    explicit nrows/ncols and auto-syncs its grid from the parent GridSpec.

    The typical pattern under test::

        gs = GridSpec(2, 2, height_ratios=[3, 1])
        fig = Figure(figsize=(800, 600))   # defaults to nrows=1, ncols=1
        ax = fig.add_subplot(gs[0, :])     # Figure adopts 2×2 grid from gs

    Without the auto-sync, panels at row_start≥1 would get ph=0 (floored to 64)
    because the Figure only knows about 1 row track.
    """

    def test_auto_sync_nrows_from_gridspec(self):
        """Figure auto-updates _nrows when GridSpec has more rows."""
        gs = GridSpec(2, 1)
        fig = Figure(figsize=(400, 400))
        fig.add_subplot(gs[0, 0])
        fig.add_subplot(gs[1, 0])
        assert fig._nrows == 2, f"nrows should auto-sync to 2, got {fig._nrows}"
        assert fig._ncols == 1

    def test_auto_sync_ncols_from_gridspec(self):
        """Figure auto-updates _ncols when GridSpec has more columns."""
        gs = GridSpec(1, 3)
        fig = Figure(figsize=(600, 200))
        fig.add_subplot(gs[0, 0])
        fig.add_subplot(gs[0, 1])
        fig.add_subplot(gs[0, 2])
        assert fig._ncols == 3, f"ncols should auto-sync to 3, got {fig._ncols}"
        assert fig._nrows == 1

    def test_auto_sync_height_ratios_from_gridspec(self):
        """height_ratios from the GridSpec are adopted into the Figure."""
        gs = GridSpec(2, 1, height_ratios=[3, 1])
        fig = Figure(figsize=(400, 800))
        fig.add_subplot(gs[0, 0])
        assert fig._height_ratios == [3, 1], (
            f"height_ratios should be [3, 1], got {fig._height_ratios}"
        )

    def test_auto_sync_width_ratios_from_gridspec(self):
        """width_ratios from the GridSpec are adopted into the Figure."""
        gs = GridSpec(1, 2, width_ratios=[2, 1])
        fig = Figure(figsize=(600, 200))
        fig.add_subplot(gs[0, 0])
        assert fig._width_ratios == [2, 1], (
            f"width_ratios should be [2, 1], got {fig._width_ratios}"
        )

    def test_gridspec_height_ratios_applied_to_sizes(self):
        """Panels at correct heights according to GridSpec height_ratios."""
        gs = GridSpec(2, 1, height_ratios=[3, 1])
        fig = Figure(figsize=(400, 800))
        v0 = fig.add_subplot(gs[0, 0]).plot(np.zeros(10))
        v1 = fig.add_subplot(gs[1, 0]).plot(np.zeros(10))
        s = _sizes(fig)
        ph0 = s[v0._id][1]
        ph1 = s[v1._id][1]
        assert approx(ph0, 600, tol=2), (
            f"top panel should be 600px (3/4 of 800), got {ph0}"
        )
        assert approx(ph1, 200, tol=2), (
            f"bottom panel should be 200px (1/4 of 800), got {ph1}"
        )
        assert approx(ph0, 3 * ph1, tol=3), (
            f"3:1 height ratio not met: {ph0} vs {ph1}"
        )

    def test_gridspec_width_ratios_applied_to_sizes(self):
        """Panels at correct widths according to GridSpec width_ratios."""
        gs = GridSpec(1, 2, width_ratios=[2, 1])
        fig = Figure(figsize=(600, 200))
        v0 = fig.add_subplot(gs[0, 0]).plot(np.zeros(10))
        v1 = fig.add_subplot(gs[0, 1]).plot(np.zeros(10))
        s = _sizes(fig)
        pw0 = s[v0._id][0]
        pw1 = s[v1._id][0]
        assert approx(pw0, 400, tol=2), (
            f"left panel should be 400px (2/3 of 600), got {pw0}"
        )
        assert approx(pw1, 200, tol=2), (
            f"right panel should be 200px (1/3 of 600), got {pw1}"
        )

    def test_two_spectra_side_by_side_not_squished(self):
        """Two 1D spectra side by side must each get half the figure width."""
        gs = GridSpec(1, 2)
        fig = Figure(figsize=(800, 300))
        v0 = fig.add_subplot(gs[0, 0]).plot(np.zeros(100))
        v1 = fig.add_subplot(gs[0, 1]).plot(np.zeros(100))
        s = _sizes(fig)
        pw0, ph0 = s[v0._id]
        pw1, ph1 = s[v1._id]
        assert approx(pw0, 400, tol=2), (
            f"left spectrum should be 400px wide, got {pw0}"
        )
        assert approx(pw1, 400, tol=2), (
            f"right spectrum should be 400px wide, got {pw1}"
        )
        assert ph0 == ph1 == 300, (
            f"both spectra should be 300px tall: {ph0}, {ph1}"
        )
        # Inner plot area must be substantial (not 64px-floor squished)
        inner_w = pw0 - PAD_L - PAD_R
        assert inner_w > 200, (
            f"inner plot width should be >200px, got {inner_w} "
            f"(panel was squished if ≤64)"
        )

    def test_image_and_two_spectra_correct_ratios(self):
        """Image spanning top row (3×), two spectra below (1×) side by side.

        This is the canonical use-case the bug report describes: when using
        GridSpec with a bare Figure, the second-row spectra used to get floored
        to 64px because Figure._height_ratios had only 1 track.
        """
        gs = GridSpec(2, 2, height_ratios=[3, 1])
        fig = Figure(figsize=(800, 800))
        v_img = fig.add_subplot(gs[0, :]).imshow(np.zeros((64, 64)))
        v_sp1 = fig.add_subplot(gs[1, 0]).plot(np.zeros(100))
        v_sp2 = fig.add_subplot(gs[1, 1]).plot(np.zeros(100))
        s = _sizes(fig)

        pw_img, ph_img = s[v_img._id]
        pw_sp1, ph_sp1 = s[v_sp1._id]
        pw_sp2, ph_sp2 = s[v_sp2._id]

        # Image spans full width
        assert pw_img == 800, f"image should span full width 800, got {pw_img}"
        # Image gets 3/4 of height = 600px
        assert approx(ph_img, 600, tol=2), (
            f"image should be 600px tall (3/4 of 800), got {ph_img}"
        )
        # Each spectrum gets half width
        assert approx(pw_sp1, 400, tol=2), (
            f"left spectrum width should be 400, got {pw_sp1}"
        )
        assert approx(pw_sp2, 400, tol=2), (
            f"right spectrum width should be 400, got {pw_sp2}"
        )
        # Spectra get 1/4 of height = 200px (not 64px floor!)
        assert approx(ph_sp1, 200, tol=2), (
            f"spectrum height should be 200px (1/4 of 800), not 64 floor, got {ph_sp1}"
        )
        assert ph_sp1 == ph_sp2, (
            f"both spectra must have the same height: {ph_sp1} vs {ph_sp2}"
        )

    def test_explicit_figure_dims_beat_smaller_gridspec(self):
        """When Figure has explicit nrows/ncols >= GridSpec, Figure values win."""
        gs = GridSpec(2, 1, height_ratios=[1, 1])  # equal ratios
        fig = Figure(2, 1, figsize=(400, 800), height_ratios=[3, 1])  # explicit 3:1
        v0 = fig.add_subplot(gs[0, 0]).plot(np.zeros(10))
        v1 = fig.add_subplot(gs[1, 0]).plot(np.zeros(10))
        s = _sizes(fig)
        ph0 = s[v0._id][1]
        ph1 = s[v1._id][1]
        # Figure's [3:1] must win over GridSpec's [1:1]
        assert approx(ph0, 600, tol=2), (
            f"Figure's 3:1 ratio must be preserved: top={ph0}, expected 600"
        )
        assert approx(ph1, 200, tol=2), (
            f"Figure's 3:1 ratio must be preserved: bottom={ph1}, expected 200"
        )

    def test_layout_json_nrows_ncols_after_auto_sync(self):
        """layout_json must reflect the auto-synced nrows/ncols."""
        gs = GridSpec(3, 2)
        fig = Figure(figsize=(600, 600))
        fig.add_subplot(gs[0, 0]).plot(np.zeros(5))
        fig.add_subplot(gs[1, 0]).plot(np.zeros(5))
        fig.add_subplot(gs[2, 0]).plot(np.zeros(5))
        layout = _layout(fig)
        assert layout["nrows"] == 3, (
            f"layout_json nrows should be 3, got {layout['nrows']}"
        )
        assert layout["ncols"] == 2, (
            f"layout_json ncols should be 2, got {layout['ncols']}"
        )

    def test_second_row_panel_not_floored_to_64(self):
        """Regression: panel at row_start=1 with a 1-row Figure used to be floored to 64px."""
        gs = GridSpec(2, 1)
        fig = Figure(figsize=(400, 400))
        _ = fig.add_subplot(gs[0, 0]).plot(np.zeros(5))
        v1 = fig.add_subplot(gs[1, 0]).plot(np.zeros(5))
        s = _sizes(fig)
        ph1 = s[v1._id][1]
        assert ph1 > 64, (
            f"Row-1 panel must NOT be floored to 64px; got ph={ph1}. "
            "This indicates the Figure failed to auto-sync its nrows from the GridSpec."
        )
        assert approx(ph1, 200, tol=2), (
            f"Row-1 panel should be 200px (half of 400), got {ph1}"
        )

    def test_three_row_gridspec_all_panels_correct_height(self):
        """All three panels in a 3-row GridSpec (equal ratios) get 1/3 of height."""
        gs = GridSpec(3, 1)
        fig = Figure(figsize=(400, 600))
        plots = [fig.add_subplot(gs[r, 0]).plot(np.zeros(5)) for r in range(3)]
        s = _sizes(fig)
        for i, v in enumerate(plots):
            ph = s[v._id][1]
            assert approx(ph, 200, tol=2), (
                f"Panel {i} should be 200px (1/3 of 600), got {ph}"
            )

    def test_spanning_subplot_correct_size(self):
        """gs[0, :] spanning all columns must get the full figure width."""
        gs = GridSpec(2, 3, height_ratios=[2, 1])
        fig = Figure(figsize=(900, 600))
        v_top = fig.add_subplot(gs[0, :]).plot(np.zeros(10))   # spans 3 cols
        v_bl  = fig.add_subplot(gs[1, 0]).plot(np.zeros(10))
        v_bm  = fig.add_subplot(gs[1, 1]).plot(np.zeros(10))
        v_br  = fig.add_subplot(gs[1, 2]).plot(np.zeros(10))
        s = _sizes(fig)

        pw_top, ph_top = s[v_top._id]
        assert pw_top == 900, f"spanning subplot should be full width 900, got {pw_top}"
        assert approx(ph_top, 400, tol=2), (
            f"spanning subplot should be 400px (2/3 of 600), got {ph_top}"
        )

        # Bottom row: each panel = 300px wide, 200px tall
        for label, v in [("bottom-left", v_bl), ("bottom-mid", v_bm), ("bottom-right", v_br)]:
            pw, ph = s[v._id]
            assert approx(pw, 300, tol=2), f"{label} width should be 300, got {pw}"
            assert approx(ph, 200, tol=2), f"{label} height should be 200, got {ph}"


# ─────────────────────────────────────────────────────────────────────────────
# subplots_adjust
# ─────────────────────────────────────────────────────────────────────────────

class TestSubplotsAdjust:

    def test_hspace_in_layout_json(self):
        fig, _ = vw.subplots(2, 1, figsize=(400, 400))
        fig.subplots_adjust(hspace=0.3)
        layout = _layout(fig)
        assert abs(layout['hspace'] - 0.3) < 1e-9

    def test_wspace_in_layout_json(self):
        fig, _ = vw.subplots(1, 2, figsize=(400, 200))
        fig.subplots_adjust(wspace=0.2)
        layout = _layout(fig)
        assert abs(layout['wspace'] - 0.2) < 1e-9

    def test_defaults_are_none(self):
        fig, _ = vw.subplots(2, 2, figsize=(400, 400))
        layout = _layout(fig)
        assert layout['hspace'] is None
        assert layout['wspace'] is None

    def test_both_together(self):
        fig, _ = vw.subplots(2, 2, figsize=(600, 600))
        fig.subplots_adjust(hspace=0.15, wspace=0.25)
        layout = _layout(fig)
        assert abs(layout['hspace'] - 0.15) < 1e-9
        assert abs(layout['wspace'] - 0.25) < 1e-9

    def test_retriggers_layout_push(self):
        fig, _ = vw.subplots(2, 1, figsize=(400, 400))
        before = fig.layout_json
        fig.subplots_adjust(hspace=0.1)
        assert fig.layout_json != before


# ===========================================================================
# hspace / wspace initial-value contract
# ===========================================================================

class TestHspaceWspaceInitialState:
    def test_initial_hspace_is_none(self):
        """Before subplots_adjust the internal value is None (browser 4px default)."""
        fig, _ = vw.subplots(2, 2)
        assert fig._hspace is None
        assert fig._wspace is None

    def test_subplots_adjust_zero_stores_zero(self):
        """subplots_adjust(hspace=0.0) must store 0.0, not None."""
        fig, _ = vw.subplots(2, 1)
        fig.subplots_adjust(hspace=0.0, wspace=0.0)
        assert fig._hspace == 0.0
        assert fig._wspace == 0.0

    def test_subplots_adjust_zero_appears_in_layout(self):
        fig, _ = vw.subplots(2, 2)
        fig.subplots_adjust(hspace=0.0, wspace=0.0)
        layout = json.loads(fig.layout_json)
        assert layout["hspace"] == pytest.approx(0.0)
        assert layout["wspace"] == pytest.approx(0.0)



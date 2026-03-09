"""
tests/test_gridspec.py
======================

Tests for GridSpec / SubplotSpec indexing AND the figure sizing pipeline
(_compute_cell_sizes) that converts grid specs + figsize into per-panel
canvas pixel dimensions.

The sizing contract (all measured at the *canvas* level, before PAD margins):
  - All panels in the same grid column have the same canvas width  (pw).
  - All panels in the same grid row    have the same canvas height (ph).
  - For a 2-D panel with an image of aspect ratio ar = iw/ih:
        canvas_pw / canvas_ph  == ar   (within 1 px rounding).
  - For N equal-ratio columns inside figsize (fw, fh):
        each column width == fw / N   (within 1 px rounding).
  - width_ratios / height_ratios scale the tracks proportionally.
  - The total figure area is not exceeded: sum(col tracks) <= fw,
    sum(row tracks) <= fh.
"""

from __future__ import annotations

import json
import numpy as np
import pytest

import anyplotlib as vw
from anyplotlib.figure import Figure
from anyplotlib.figure_plots import GridSpec, SubplotSpec, Axes  # noqa: F401


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
# Part 5 – _compute_cell_sizes: 2D aspect-locking
# ─────────────────────────────────────────────────────────────────────────────

class TestAspectLocking:
    """2D images must produce square-pixel canvases (pw/ph == iw/ih)."""

    def _assert_aspect(self, pw, ph, iw, ih, tol=1):
        expected_ph = round(pw * ih / iw)
        assert approx(ph, expected_ph, tol=tol), \
            f"aspect wrong: image {iw}×{ih}, canvas {pw}×{ph}, " \
            f"expected ph≈{expected_ph}"

    def test_square_image_square_canvas(self):
        fig, ax = vw.subplots(1, 1, figsize=(400, 400))
        v = ax.imshow(np.zeros((128, 128)))
        pw, ph = _sizes(fig)[v._id]
        assert approx(pw, ph, tol=1), f"square image → square canvas: {pw}×{ph}"

    def test_2to1_wide_image(self):
        """256×128 image (2:1) in square cell → pw/ph ≈ 2."""
        fig, ax = vw.subplots(1, 1, figsize=(400, 400))
        v = ax.imshow(np.zeros((128, 256)))  # H=128, W=256
        pw, ph = _sizes(fig)[v._id]
        ratio = pw / ph
        assert approx(round(ratio * 100), 200, tol=3), \
            f"2:1 image should give pw/ph≈2, got {ratio:.3f}"

    def test_tall_image_portrait(self):
        """128×64 image (1:2 — tall) in square cell → ph/pw ≈ 2."""
        fig, ax = vw.subplots(1, 1, figsize=(400, 400))
        v = ax.imshow(np.zeros((256, 128)))   # H=256 (tall), W=128
        pw, ph = _sizes(fig)[v._id]
        ratio = ph / pw
        assert approx(round(ratio * 100), 200, tol=3), \
            f"tall image should give ph/pw≈2, got {ratio:.3f}"

    def test_aspect_does_not_exceed_cell(self):
        """Canvas must not exceed allocated cell size."""
        fig, ax = vw.subplots(1, 1, figsize=(300, 500))
        v = ax.imshow(np.zeros((64, 128)))  # wide image, tall cell
        pw, ph = _sizes(fig)[v._id]
        assert pw <= 300 + 1, f"pw={pw} exceeds cell width 300"
        assert ph <= 500 + 1, f"ph={ph} exceeds cell height 500"

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

    def test_wide_2d_shrinks_col_not_row(self):
        """
        Wide image (W > H) in a taller-than-wide cell:
        the aspect lock should shrink the column width, leaving row height intact.
        The 1D panel in the same column must match the shrunken width.
        """
        # figsize 400×600, square image 128×128:
        # cell is 400×600 → taller than wide → shrink row: ph = pw = 400
        fig, axs = vw.subplots(2, 1, figsize=(400, 600))
        v2d = axs[0].imshow(np.zeros((128, 128)))
        v1d = axs[1].plot(np.zeros(256))
        s = _sizes(fig)
        pw2d, ph2d = s[v2d._id]
        pw1d, ph1d = s[v1d._id]
        assert pw2d == pw1d, f"column widths must match: {pw2d} vs {pw1d}"
        assert approx(pw2d, ph2d, tol=1), \
            f"square image canvas must be square: {pw2d}×{ph2d}"

    def test_aspect_locks_converge_multiple_2d(self):
        """
        Two 2D panels in the same column with different aspect ratios.
        The more-constrained one determines the final column width.
        Both panels must get the same pw.
        """
        # Col width = 400. Image A: 128×128 (ar=1) → ph=pw=400 (no shrink needed for height).
        # Image B: 64×128 (ar=0.5, tall) → ph = pw / 0.5 = 800, too tall.
        # The taller cell gets shrunk: row_px[1] = pw_col / (1/0.5) = pw_col * 0.5 …
        # The column serves both; they must end up the same pw.
        fig, axs = vw.subplots(2, 1, figsize=(400, 800))
        vA = axs[0].imshow(np.zeros((128, 128)))   # square
        vB = axs[1].imshow(np.zeros((128, 64)))    # wide (W=64 is wrong, fix: W>H)
        s = _sizes(fig)
        pwA = s[vA._id][0]
        pwB = s[vB._id][0]
        assert pwA == pwB, f"Two 2D panels in same col must have same pw: {pwA} vs {pwB}"

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

    def test_2d_in_nonsquare_cell_aspect_preserved(self):
        """Non-square figsize with a square image → canvas must still be square."""
        fig, ax = vw.subplots(1, 1, figsize=(600, 300))
        v = ax.imshow(np.zeros((128, 128)))
        pw, ph = _sizes(fig)[v._id]
        assert approx(pw, ph, tol=1), \
            f"square image in non-square cell should produce square canvas: {pw}×{ph}"

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







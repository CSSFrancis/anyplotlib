"""
tests/test_visual.py
====================

Pixel-level visual regression tests.

Each test:
  1. Builds a deterministic Figure using the OO API.
  2. Renders it in headless Chromium via the ``take_screenshot`` fixture
     (see conftest.py) — the *exact* JS renderer the user sees in a notebook.
  3. Compares the result against a golden PNG in ``tests/baselines/``.

Workflow
--------
Generate / refresh baselines (first run or after intentional visual change)::

    uv run pytest tests/test_visual.py --update-baselines -v

Normal CI run (fails on regression)::

    uv run pytest tests/test_visual.py -v

Comparison tolerance
--------------------
* Per-pixel tolerance: 8 DN (≈3 % of 255) on any channel.
* Maximum bad-pixel fraction: 2 % of all pixels.

These values absorb sub-pixel anti-aliasing differences between Chromium
versions while still catching genuine rendering regressions.
"""
from __future__ import annotations

import pathlib

import numpy as np
import pytest

import anyplotlib as apl
from anyplotlib.tests._png_utils import decode_png, encode_png, compare_arrays

BASELINES = pathlib.Path(__file__).parent.parent / "baselines"


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _check(name: str, arr: np.ndarray, update: bool) -> None:
    """Assert *arr* matches the baseline named *name*, or write it if *update*."""
    path = BASELINES / f"{name}.png"

    if update:
        BASELINES.mkdir(exist_ok=True)
        path.write_bytes(encode_png(arr))
        pytest.skip(f"Baseline updated: {path.name}")

    if not path.exists():
        pytest.skip(
            f"No baseline for {name!r} — run with --update-baselines to create it"
        )

    expected = decode_png(path.read_bytes())
    ok, msg = compare_arrays(arr, expected)
    assert ok, f"Visual regression [{name}]: {msg}"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestVisual:
    """Pixel-accurate rendering checks for each plot kind."""

    # ── 2-D image ──────────────────────────────────────────────────────────

    def test_imshow_gradient(self, take_screenshot, update_baselines):
        """Grayscale linear gradient — exercises the 2-D colormap + LUT path."""
        fig, ax = apl.subplots(1, 1, figsize=(320, 320))
        data = np.linspace(0.0, 1.0, 64 * 64, dtype=np.float32).reshape(64, 64)
        ax.imshow(data)
        arr = take_screenshot(fig)
        _check("imshow_gradient", arr, update_baselines)

    def test_imshow_checkerboard(self, take_screenshot, update_baselines):
        """High-contrast checkerboard — exercises sharp edge rendering."""
        fig, ax = apl.subplots(1, 1, figsize=(256, 256))
        board = np.indices((32, 32)).sum(axis=0) % 2  # 0/1 alternating
        ax.imshow(board.astype(np.float32))
        arr = take_screenshot(fig)
        _check("imshow_checkerboard", arr, update_baselines)

    def test_imshow_viridis(self, take_screenshot, update_baselines):
        """2-D image with viridis colormap — exercises non-gray LUT path."""
        fig, ax = apl.subplots(1, 1, figsize=(320, 256))
        rng = np.random.default_rng(0)
        data = rng.uniform(0.0, 1.0, (48, 64)).astype(np.float32)
        plot = ax.imshow(data)
        plot.set_colormap("viridis")
        arr = take_screenshot(fig)
        _check("imshow_viridis", arr, update_baselines)

    # ── 1-D line ───────────────────────────────────────────────────────────

    def test_plot1d_sine(self, take_screenshot, update_baselines):
        """Single sine wave — exercises the 1-D line renderer."""
        fig, ax = apl.subplots(1, 1, figsize=(400, 240))
        t = np.linspace(0.0, 2.0 * np.pi, 256)
        ax.plot(np.sin(t))
        arr = take_screenshot(fig)
        _check("plot1d_sine", arr, update_baselines)

    def test_plot1d_multi(self, take_screenshot, update_baselines):
        """Multiple overlaid 1-D lines — exercises add_line() layering."""
        fig, ax = apl.subplots(1, 1, figsize=(400, 240))
        t = np.linspace(0.0, 2.0 * np.pi, 256)
        plot = ax.plot(np.sin(t), color="#4fc3f7")
        plot.add_line(np.cos(t), color="#ff7043")
        arr = take_screenshot(fig)
        _check("plot1d_multi", arr, update_baselines)

    def test_plot1d_dashed(self, take_screenshot, update_baselines):
        """Dashed primary line — exercises linestyle→setLineDash path."""
        fig, ax = apl.subplots(1, 1, figsize=(400, 240))
        t = np.linspace(0.0, 2.0 * np.pi, 256)
        ax.plot(np.sin(t), color="#ff7043", linestyle="dashed", linewidth=2)
        arr = take_screenshot(fig)
        _check("plot1d_dashed", arr, update_baselines)

    def test_plot1d_alpha(self, take_screenshot, update_baselines):
        """Semi-transparent overlapping lines — exercises globalAlpha path."""
        fig, ax = apl.subplots(1, 1, figsize=(400, 240))
        t = np.linspace(0.0, 2.0 * np.pi, 256)
        plot = ax.plot(np.sin(t), color="#4fc3f7", alpha=0.4)
        plot.add_line(np.cos(t), color="#ff7043", alpha=0.4)
        arr = take_screenshot(fig)
        _check("plot1d_alpha", arr, update_baselines)

    def test_plot1d_markers(self, take_screenshot, update_baselines):
        """Circle markers along a sparse line — exercises marker render path."""
        fig, ax = apl.subplots(1, 1, figsize=(400, 240))
        t = np.linspace(0.0, 2.0 * np.pi, 24)
        ax.plot(np.sin(t), color="#4fc3f7", marker="o", markersize=4)
        arr = take_screenshot(fig)
        _check("plot1d_markers", arr, update_baselines)

    def test_plot1d_all_linestyles(self, take_screenshot, update_baselines):
        """All four linestyles on one panel — exercises every dash pattern."""
        fig, ax = apl.subplots(1, 1, figsize=(440, 300))
        t = np.linspace(0.0, 2.0 * np.pi, 256)
        plot = ax.plot(np.sin(t),         color="#4fc3f7", linestyle="solid",   label="solid")
        plot.add_line(np.sin(t) + 0.6,    color="#ff7043", linestyle="dashed",  label="dashed")
        plot.add_line(np.sin(t) + 1.2,    color="#aed581", linestyle="dotted",  label="dotted")
        plot.add_line(np.sin(t) + 1.8,    color="#ce93d8", linestyle="dashdot", label="dashdot")
        arr = take_screenshot(fig)
        _check("plot1d_all_linestyles", arr, update_baselines)

    def test_plot1d_marker_symbols(self, take_screenshot, update_baselines):
        """All seven marker symbols on one panel."""
        fig, ax = apl.subplots(1, 1, figsize=(440, 380))
        t = np.linspace(0.0, 2.0 * np.pi, 20)
        symbols = [("o", "#4fc3f7"), ("s", "#ff7043"), ("^", "#aed581"),
                   ("v", "#ce93d8"), ("D", "#ffcc02"), ("+", "#80cbc4"),
                   ("x", "#ef9a9a")]
        plot = ax.plot(np.sin(t) - 3.0, color=symbols[0][1],
                       marker=symbols[0][0], markersize=5, label=symbols[0][0])
        for i, (sym, col) in enumerate(symbols[1:], 1):
            plot.add_line(np.sin(t) + (i - 3) * 1.0, color=col,
                          marker=sym, markersize=5, label=sym)
        arr = take_screenshot(fig)
        _check("plot1d_marker_symbols", arr, update_baselines)

    # ── pcolormesh ─────────────────────────────────────────────────────────

    def test_pcolormesh_uniform(self, take_screenshot, update_baselines):
        """Uniform-grid pcolormesh with sine × cosine pattern."""
        x = np.linspace(0.0, 2.0 * np.pi, 33)   # 32 cells → 33 edges
        y = np.linspace(0.0, 2.0 * np.pi, 33)
        Xc = (x[:-1] + x[1:]) / 2
        Yc = (y[:-1] + y[1:]) / 2
        Z = np.sin(Xc[np.newaxis, :]) * np.cos(Yc[:, np.newaxis])
        fig, ax = apl.subplots(1, 1, figsize=(320, 320))
        ax.pcolormesh(Z, x_edges=x, y_edges=y)
        arr = take_screenshot(fig)
        _check("pcolormesh_uniform", arr, update_baselines)

    # ── 3-D surface ────────────────────────────────────────────────────────

    def test_plot3d_surface(self, take_screenshot, update_baselines):
        """3-D paraboloid surface — exercises the software 3-D renderer."""
        x = np.linspace(-1.5, 1.5, 24)
        y = np.linspace(-1.5, 1.5, 24)
        X, Y = np.meshgrid(x, y)
        Z = X ** 2 + Y ** 2
        fig, ax = apl.subplots(1, 1, figsize=(320, 320))
        ax.plot_surface(X, Y, Z, colormap="viridis")
        arr = take_screenshot(fig)
        _check("plot3d_surface", arr, update_baselines)

    # ── bar chart ──────────────────────────────────────────────────────────

    def test_bar_basic(self, take_screenshot, update_baselines):
        """Basic vertical bar chart — exercises the bar renderer end-to-end."""
        fig, ax = apl.subplots(1, 1, figsize=(400, 300))
        ax.bar(["Jan", "Feb", "Mar", "Apr", "May"],
               [42, 55, 48, 61, 37],
               color="#4fc3f7")
        arr = take_screenshot(fig)
        _check("bar_basic", arr, update_baselines)

    # ── multi-panel layout ─────────────────────────────────────────────────

    def test_subplots_2x1(self, take_screenshot, update_baselines):
        """Two-row figure: image on top, 1-D line below."""
        fig, axs = apl.subplots(2, 1, figsize=(320, 480))
        data = np.linspace(0.0, 1.0, 32 * 32).reshape(32, 32).astype(np.float32)
        axs[0].imshow(data)
        t = np.linspace(0.0, 2.0 * np.pi, 128)
        axs[1].plot(np.sin(t))
        arr = take_screenshot(fig)
        _check("subplots_2x1", arr, update_baselines)

    # ── GridSpec layouts ───────────────────────────────────────────────────

    def test_gridspec_side_by_side_1d(self, take_screenshot, update_baselines):
        """Two 1-D spectra side by side — exercises 1×2 GridSpec layout.

        Verifies that side-by-side spectra are not squished and each occupies
        exactly half the figure width with a reasonable inner plot area.
        """
        gs = apl.GridSpec(1, 2)
        fig = apl.Figure(figsize=(640, 240))
        t = np.linspace(0.0, 2.0 * np.pi, 256)
        fig.add_subplot(gs[0, 0]).plot(np.sin(t), color="#4fc3f7")
        fig.add_subplot(gs[0, 1]).plot(np.cos(t), color="#ff7043")
        arr = take_screenshot(fig)
        _check("gridspec_side_by_side_1d", arr, update_baselines)

    def test_gridspec_image_two_spectra(self, take_screenshot, update_baselines):
        """Image on top (3×height), two 1-D spectra below (1×height) side by side.

        This is the canonical layout that exposed the squishing bug: bare
        Figure + GridSpec with height_ratios caused row-1 panels to be floored
        to 64px.  The image should occupy 3/4 of the height; each spectrum 1/4.
        """
        gs = apl.GridSpec(2, 2, height_ratios=[3, 1])
        fig = apl.Figure(figsize=(480, 480))
        data = np.linspace(0.0, 1.0, 32 * 32).reshape(32, 32).astype(np.float32)
        fig.add_subplot(gs[0, :]).imshow(data)
        t = np.linspace(0.0, 2.0 * np.pi, 128)
        fig.add_subplot(gs[1, 0]).plot(np.sin(t), color="#4fc3f7")
        fig.add_subplot(gs[1, 1]).plot(np.cos(t), color="#ff7043")
        arr = take_screenshot(fig)
        _check("gridspec_image_two_spectra", arr, update_baselines)

    def test_gridspec_height_ratio_image_histogram(self, take_screenshot, update_baselines):
        """Image (3×) + histogram (1×) with explicit height_ratios via GridSpec."""
        gs = apl.GridSpec(2, 1, height_ratios=[3, 1])
        fig = apl.Figure(figsize=(400, 400))
        rng = np.random.default_rng(42)
        data = rng.uniform(0.0, 1.0, (32, 32)).astype(np.float32)
        fig.add_subplot(gs[0, 0]).imshow(data, cmap="viridis")
        counts = np.histogram(data.ravel(), bins=32)[0].astype(float)
        fig.add_subplot(gs[1, 0]).plot(counts, color="#aed581")
        arr = take_screenshot(fig)
        _check("gridspec_height_ratio_image_histogram", arr, update_baselines)

    def test_gridspec_3col_equal_spectra(self, take_screenshot, update_baselines):
        """Three equal-width 1-D spectra in a single row — 1×3 GridSpec."""
        gs = apl.GridSpec(1, 3)
        fig = apl.Figure(figsize=(720, 200))
        rng = np.random.default_rng(7)
        t = np.linspace(0.0, 2.0 * np.pi, 200)
        colors = ["#4fc3f7", "#ff7043", "#aed581"]
        for i, color in enumerate(colors):
            noise = rng.normal(scale=0.1, size=len(t))
            fig.add_subplot(gs[0, i]).plot(np.sin(t * (i + 1)) + noise, color=color)
        arr = take_screenshot(fig)
        _check("gridspec_3col_equal_spectra", arr, update_baselines)

    def test_gridspec_asymmetric_width_ratios(self, take_screenshot, update_baselines):
        """2:1 width ratio: wide spectrum left, narrow spectrum right."""
        gs = apl.GridSpec(1, 2, width_ratios=[2, 1])
        fig = apl.Figure(figsize=(480, 200))
        t = np.linspace(0.0, 2.0 * np.pi, 256)
        fig.add_subplot(gs[0, 0]).plot(np.sin(t), color="#4fc3f7")
        fig.add_subplot(gs[0, 1]).plot(np.cos(t), color="#ff7043")
        arr = take_screenshot(fig)
        _check("gridspec_asymmetric_width_ratios", arr, update_baselines)

    def test_gridspec_spanning_top_two_bottom(self, take_screenshot, update_baselines):
        """Full-width spectrum on top (gs[0, :]), two spectra below (gs[1, 0:2])."""
        gs = apl.GridSpec(2, 2, height_ratios=[2, 1])
        fig = apl.Figure(figsize=(480, 360))
        t = np.linspace(0.0, 4.0 * np.pi, 512)
        fig.add_subplot(gs[0, :]).plot(np.sin(t), color="#4fc3f7")
        fig.add_subplot(gs[1, 0]).plot(np.sin(2 * t), color="#ff7043")
        fig.add_subplot(gs[1, 1]).plot(np.cos(2 * t), color="#aed581")
        arr = take_screenshot(fig)
        _check("gridspec_spanning_top_two_bottom", arr, update_baselines)

    # ── Phase 4 — labels, title, colorbar label, axis visibility ───────────

    def test_plot1d_title(self, take_screenshot, update_baselines):
        """1-D plot with set_title — title text drawn in top PAD area."""
        fig, ax = apl.subplots(1, 1, figsize=(400, 240))
        p = ax.plot(np.sin(np.linspace(0, 2 * np.pi, 256)), color="#4fc3f7")
        p.set_title("Sine Wave")
        arr = take_screenshot(fig)
        _check("plot1d_title", arr, update_baselines)

    def test_plot1d_axis_off(self, take_screenshot, update_baselines):
        """1-D plot with set_axis_off — tick labels hidden."""
        fig, ax = apl.subplots(1, 1, figsize=(400, 240))
        p = ax.plot(np.sin(np.linspace(0, 2 * np.pi, 256)), color="#4fc3f7")
        p.set_axis_off()
        arr = take_screenshot(fig)
        _check("plot1d_axis_off", arr, update_baselines)

    def test_imshow_labels(self, take_screenshot, update_baselines):
        """2-D image with x_label, y_label, title, and colorbar_label."""
        fig, ax = apl.subplots(1, 1, figsize=(400, 400))
        x = np.linspace(0.0, 10.0, 64)
        p = ax.imshow(
            np.random.default_rng(0).uniform(size=(64, 64)),
            axes=[x, x], units="nm",
        )
        p.set_xlabel("x (nm)")
        p.set_ylabel("y (nm)")
        p.set_title("Test Image")
        p.set_colorbar_visible(True)
        p.set_colorbar_label("Intensity")
        arr = take_screenshot(fig)
        _check("imshow_labels", arr, update_baselines)

    def test_imshow_axis_off(self, take_screenshot, update_baselines):
        """2-D image with set_axis_off — axis gutters hidden."""
        fig, ax = apl.subplots(1, 1, figsize=(320, 320))
        x = np.linspace(0.0, 5.0, 32)
        p = ax.imshow(np.zeros((32, 32)), axes=[x, x], units="nm")
        p.set_axis_off()
        arr = take_screenshot(fig)
        _check("imshow_axis_off", arr, update_baselines)


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
from tests._png_utils import decode_png, encode_png, compare_arrays

BASELINES = pathlib.Path(__file__).parent / "baselines"


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


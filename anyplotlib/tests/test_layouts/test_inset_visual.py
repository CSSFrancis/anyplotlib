"""
tests/test_inset_visual.py
==========================

Pixel-level visual regression tests for InsetAxes.

Each test:
  1. Builds a deterministic Figure with one or more insets.
  2. Renders it in headless Chromium via ``take_screenshot``.
  3. Compares against a golden PNG in ``tests/baselines/``.

Generate / refresh baselines::

    uv run pytest tests/test_inset_visual.py --update-baselines -v

Normal CI run (fails on regression)::

    uv run pytest tests/test_inset_visual.py -v
"""
from __future__ import annotations

import pathlib

import numpy as np
import pytest

import anyplotlib as apl

BASELINES = pathlib.Path(__file__).parent / "baselines"


def _check(name: str, arr: np.ndarray, update: bool) -> None:
    from tests._png_utils import decode_png, encode_png, compare_arrays

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


def _main_fig():
    """640×480 figure with a grayscale 64×64 imshow — the inset host."""
    rng = np.random.default_rng(0)
    fig, ax = apl.subplots(1, 1, figsize=(640, 480))
    ax.imshow(rng.uniform(0.0, 1.0, (64, 64)).astype(np.float32))
    return fig


class TestInsetVisual:
    """Visual regression tests for the floating inset panel system."""

    # ── single inset, normal state ─────────────────────────────────────────

    def test_inset_normal_2d(self, take_screenshot, update_baselines):
        """2-D inset in top-right corner, normal state."""
        rng = np.random.default_rng(1)
        fig = _main_fig()
        inset = fig.add_inset(0.30, 0.30, corner="top-right", title="Zoom")
        inset.imshow(rng.uniform(0.0, 1.0, (32, 32)).astype(np.float32),
                     cmap="viridis")
        arr = take_screenshot(fig)
        _check("inset_normal_2d", arr, update_baselines)

    def test_inset_minimized(self, take_screenshot, update_baselines):
        """Inset collapsed to title bar only after minimize()."""
        rng = np.random.default_rng(2)
        fig = _main_fig()
        inset = fig.add_inset(0.30, 0.30, corner="top-right", title="Phase")
        inset.imshow(rng.uniform(0.0, 1.0, (32, 32)).astype(np.float32))
        inset.minimize()
        arr = take_screenshot(fig)
        _check("inset_minimized", arr, update_baselines)

    def test_inset_maximized(self, take_screenshot, update_baselines):
        """Inset expanded to ~72 % of figure after maximize()."""
        rng = np.random.default_rng(3)
        fig = _main_fig()
        inset = fig.add_inset(0.30, 0.30, corner="top-right", title="Detail")
        inset.imshow(rng.uniform(0.0, 1.0, (32, 32)).astype(np.float32),
                     cmap="inferno")
        inset.maximize()
        arr = take_screenshot(fig)
        _check("inset_maximized", arr, update_baselines)

    # ── two insets stacked in the same corner ──────────────────────────────

    def test_inset_stacked(self, take_screenshot, update_baselines):
        """Two insets sharing top-right corner stack with constant gap."""
        rng = np.random.default_rng(4)
        fig = _main_fig()
        i1 = fig.add_inset(0.28, 0.25, corner="top-right", title="A")
        i1.imshow(rng.uniform(0.0, 1.0, (32, 32)).astype(np.float32))
        i2 = fig.add_inset(0.28, 0.25, corner="top-right", title="B")
        i2.imshow(rng.uniform(0.0, 1.0, (32, 32)).astype(np.float32),
                  cmap="hot")
        arr = take_screenshot(fig)
        _check("inset_stacked", arr, update_baselines)

    # ── 1-D line inset ─────────────────────────────────────────────────────

    def test_inset_1d(self, take_screenshot, update_baselines):
        """1-D line plot inset in bottom-right corner."""
        rng = np.random.default_rng(5)
        fig = _main_fig()
        inset = fig.add_inset(0.32, 0.22, corner="bottom-right",
                               title="Profile")
        t = np.linspace(0.0, 2 * np.pi, 128)
        inset.plot(np.sin(t) + rng.normal(0, 0.05, 128),
                   color="#4fc3f7", linewidth=1.5)
        arr = take_screenshot(fig)
        _check("inset_1d", arr, update_baselines)

    # ── stacked with one minimized (restack test) ──────────────────────────

    def test_inset_stacked_one_minimized(self, take_screenshot, update_baselines):
        """Two insets in same corner; first minimized — second shifts up."""
        rng = np.random.default_rng(6)
        fig = _main_fig()
        i1 = fig.add_inset(0.28, 0.25, corner="bottom-left", title="Min")
        i1.imshow(rng.uniform(0.0, 1.0, (32, 32)).astype(np.float32))
        i2 = fig.add_inset(0.28, 0.25, corner="bottom-left", title="Normal")
        i2.imshow(rng.uniform(0.0, 1.0, (32, 32)).astype(np.float32),
                  cmap="viridis")
        i1.minimize()
        arr = take_screenshot(fig)
        _check("inset_stacked_one_minimized", arr, update_baselines)


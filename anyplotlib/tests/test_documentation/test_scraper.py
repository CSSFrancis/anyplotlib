"""
tests/test_documentation/test_scraper.py
=========================================

Tests for the Playwright-based scraper thumbnail functionality.

Two sections:

1. **PNG format validation** — verifies ``_make_thumbnail_png`` returns a valid
   PNG array for common figure types.  No Playwright required.

2. **Dark-theme validation** — checks the top-left pixel of the thumbnail is
   dark-blue (matching the library's dark theme).  Requires Playwright; skipped
   automatically when not installed.
"""

from __future__ import annotations

import numpy as np
import pytest

import anyplotlib as apl
from anyplotlib.sphinx_anywidget._scraper import _make_thumbnail_png
from anyplotlib.tests._png_utils import decode_png


# ─────────────────────────────────────────────────────────────────────────────
# Shared fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def line_fig():
    fig, ax = apl.subplots(1, 1, figsize=(400, 250))
    ax.plot(np.sin(np.linspace(0, 2 * np.pi, 128)), color="#4fc3f7")
    return fig


@pytest.fixture
def imshow_fig():
    fig, ax = apl.subplots(1, 1, figsize=(320, 320))
    data = np.linspace(0, 1, 64 * 64, dtype=np.float32).reshape(64, 64)
    ax.imshow(data)
    return fig


@pytest.fixture
def multi_panel_fig():
    fig, axes = apl.subplots(1, 2, figsize=(640, 300))
    axes[0].plot(np.cos(np.linspace(0, 2 * np.pi, 64)))
    axes[1].imshow(
        np.random.default_rng(0).uniform(0, 1, (32, 32)).astype(np.float32)
    )
    return fig


# ─────────────────────────────────────────────────────────────────────────────
# Helper
# ─────────────────────────────────────────────────────────────────────────────

def _decode_thumbnail(fig, label: str):
    """Return the decoded RGBA/RGB array for *fig*'s thumbnail, asserting PNG."""
    png = _make_thumbnail_png(fig)
    assert png[:4] == b"\x89PNG", f"[{label}] result is not a PNG"
    arr = decode_png(png)
    assert arr.ndim == 3, f"[{label}] expected H×W×C array, got shape {arr.shape}"
    assert arr.shape[2] in (3, 4), (
        f"[{label}] expected RGB/RGBA, got {arr.shape[2]} channels"
    )
    return arr


# ─────────────────────────────────────────────────────────────────────────────
# Section 1 — PNG format validation  (no Playwright required)
# ─────────────────────────────────────────────────────────────────────────────

class TestThumbnailFormat:
    """Verify that _make_thumbnail_png produces a well-formed PNG for each
    common figure type."""

    def test_thumbnail_1d_line(self, line_fig):
        _decode_thumbnail(line_fig, "1D line")

    def test_thumbnail_2d_imshow(self, imshow_fig):
        _decode_thumbnail(imshow_fig, "2D imshow")

    def test_thumbnail_multi_panel(self, multi_panel_fig):
        _decode_thumbnail(multi_panel_fig, "multi-panel")


# ─────────────────────────────────────────────────────────────────────────────
# Section 2 — Dark-theme pixel validation  (requires Playwright)
# ─────────────────────────────────────────────────────────────────────────────

pytest.importorskip("playwright", reason="playwright not installed")


class TestThumbnailDarkTheme:
    """Verify the top-left pixel of each thumbnail is dark-blue, matching the
    library's default dark theme.  These tests are skipped when Playwright is
    not installed."""

    def _assert_dark_theme(self, fig, label: str) -> None:
        arr = _decode_thumbnail(fig, label)
        r, g, b = int(arr[0, 0, 0]), int(arr[0, 0, 1]), int(arr[0, 0, 2])
        assert (b > r) and (b > 30), (
            f"[{label}] expected a dark-theme thumbnail "
            f"(top-left RGB=({r},{g},{b}))"
        )

    def test_dark_theme_1d_line(self, line_fig):
        self._assert_dark_theme(line_fig, "1D line")

    def test_dark_theme_2d_imshow(self, imshow_fig):
        self._assert_dark_theme(imshow_fig, "2D imshow")

    def test_dark_theme_multi_panel(self, multi_panel_fig):
        self._assert_dark_theme(multi_panel_fig, "multi-panel")

"""
tests/test_scraper.py
=====================

Pytest tests for the Playwright-based scraper thumbnail functionality.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

import anyplotlib as apl
from anyplotlib.sphinx_anywidget._scraper import _make_thumbnail_png
from tests._png_utils import decode_png


# ── fixtures ──────────────────────────────────────────────────────────────────

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


# ── thumbnail PNG validation ──────────────────────────────────────────────────

def _assert_thumbnail_is_png(widget, label: str):
    png = _make_thumbnail_png(widget)
    assert png[:4] == b"\x89PNG", f"[{label}] result is not a PNG"
    arr = decode_png(png)
    assert arr.ndim == 3, f"[{label}] expected H×W×C array, got shape {arr.shape}"
    assert arr.shape[2] in (3, 4), f"[{label}] expected RGB/RGBA, got {arr.shape[2]} channels"


def test_thumbnail_1d_line(line_fig):
    _assert_thumbnail_is_png(line_fig, "1D line")


def test_thumbnail_2d_imshow(imshow_fig):
    _assert_thumbnail_is_png(imshow_fig, "2D imshow")


def test_thumbnail_multi_panel(multi_panel_fig):
    _assert_thumbnail_is_png(multi_panel_fig, "multi-panel")

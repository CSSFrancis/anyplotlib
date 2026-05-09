"""
tests/test_sphinx_anywidget.py
================================

Smoke tests for the ``anyplotlib.sphinx_anywidget`` extension.
"""

from __future__ import annotations

import numpy as np
import pytest

import anyplotlib as apl
import anyplotlib.figure as _af
from anyplotlib.sphinx_anywidget import AnywidgetScraper, ViewerScraper, setup  # noqa: F401
from anyplotlib.sphinx_anywidget._directive import AnywidgetFigureDirective  # noqa: F401
from anyplotlib.sphinx_anywidget._repr_utils import build_standalone_html, _widget_px
from anyplotlib.sphinx_anywidget._scraper import (
    _INTERACTIVE_RE,
    _find_widget,
    _iframe_html,
)
from anyplotlib.sphinx_anywidget._wheel_builder import build_wheel  # noqa: F401


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def simple_fig():
    fig, ax = apl.subplots(1, 1, figsize=(400, 300))
    ax.plot(np.sin(np.linspace(0, 6.28, 64)))
    return fig


# ── standalone HTML builder ───────────────────────────────────────────────────

def test_standalone_html_contains_awi_state(simple_fig):
    html = build_standalone_html(simple_fig, resizable=False, fig_id="tf")
    assert "awi_state" in html, "Missing awi_state listener"


def test_standalone_html_contains_fig_id(simple_fig):
    html = build_standalone_html(simple_fig, resizable=False, fig_id="tf")
    assert '"tf"' in html, "Missing fig_id in HTML"


def test_widget_px(simple_fig):
    w, h = _widget_px(simple_fig)
    assert w == 416, f"Expected 416 got {w}"


# ── iframe HTML helper ────────────────────────────────────────────────────────

def test_iframe_html_interactive_has_activate_btn():
    b = _iframe_html("t.html", 400, 300, fig_id="a", interactive=True)
    assert "awi-activate-btn" in b, "Missing activate button"


def test_iframe_html_static_no_activate_btn():
    s = _iframe_html("t.html", 400, 300, fig_id="a", interactive=False)
    assert "awi-activate-btn" not in s, "Should not have activate btn on static"


# ── no stale push hook ────────────────────────────────────────────────────────

def test_no_pyodide_push_hook():
    assert not hasattr(_af, "_pyodide_push_hook"), "_pyodide_push_hook should be gone"


# ── _find_widget ──────────────────────────────────────────────────────────────

def test_find_widget_finds_figure(simple_fig):
    found = _find_widget({"fig": simple_fig, "x": 42})
    assert found is simple_fig, "Should find Figure"


def test_find_widget_returns_none_for_non_widget():
    assert _find_widget({"x": 42}) is None


# ── # Interactive detection ───────────────────────────────────────────────────

def test_interactive_re_matches_inline_comment():
    assert _INTERACTIVE_RE.search("fig  # Interactive\n"), "Should match"


def test_interactive_re_matches_lowercase():
    assert _INTERACTIVE_RE.search("fig  # interactive"), "Should match lowercase"


def test_interactive_re_no_false_positives():
    assert not _INTERACTIVE_RE.search("fig  # not a match"), "Should not match"

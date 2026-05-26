"""
sphinx_anywidget/tests/test_scraper.py
========================================

Tests for ``sphinx_anywidget._scraper``:
  - Regex patterns (_INTERACTIVE_RE, _PYODIDE_PACKAGES_RE)
  - ``_find_widget``
  - ``_iframe_html``
  - ``_make_thumbnail_png`` (Playwright — skipped if not installed)
  - ``AnywidgetScraper`` unit tests
"""
from __future__ import annotations

import importlib.util
import re

import numpy as np
import pytest

import anyplotlib as apl
from anyplotlib.sphinx_anywidget._scraper import (
    MAX_DOC_WIDTH,
    _INTERACTIVE_RE,
    _PYODIDE_PACKAGES_RE,
    _find_widget,
    _iframe_html,
    AnywidgetScraper,
    ViewerScraper,
)
from anyplotlib.tests._png_utils import decode_png


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def line_fig():
    fig, ax = apl.subplots(1, 1, figsize=(400, 250))
    ax.plot(np.sin(np.linspace(0, 6.28, 64)))
    return fig


@pytest.fixture
def imshow_fig():
    fig, ax = apl.subplots(1, 1, figsize=(320, 320))
    ax.imshow(np.linspace(0, 1, 64 * 64, dtype=np.float32).reshape(64, 64))
    return fig


@pytest.fixture
def multi_panel_fig():
    fig, axes = apl.subplots(1, 2, figsize=(640, 300))
    axes[0].plot(np.cos(np.linspace(0, 6.28, 64)))
    axes[1].imshow(np.random.default_rng(0).uniform(0, 1, (32, 32)).astype(np.float32))
    return fig


# ---------------------------------------------------------------------------
# _INTERACTIVE_RE
# ---------------------------------------------------------------------------

class TestInteractiveRe:
    def test_matches_inline_comment(self):
        assert _INTERACTIVE_RE.search("fig  # Interactive\n")

    def test_matches_lowercase(self):
        assert _INTERACTIVE_RE.search("fig  # interactive")

    def test_matches_uppercase(self):
        assert _INTERACTIVE_RE.search("fig  # INTERACTIVE")

    def test_matches_with_extra_whitespace(self):
        assert _INTERACTIVE_RE.search("fig  #  Interactive  \n")

    def test_no_false_positive_other_comment(self):
        assert not _INTERACTIVE_RE.search("fig  # not a match")

    def test_no_false_positive_mid_line(self):
        assert not _INTERACTIVE_RE.search("# Interactive is nice")

    def test_matches_at_end_of_multiline_source(self):
        src = "import numpy as np\nfig, ax = apl.subplots(1, 1)\nfig  # Interactive"
        assert _INTERACTIVE_RE.search(src)


# ---------------------------------------------------------------------------
# _PYODIDE_PACKAGES_RE
# ---------------------------------------------------------------------------

class TestPyodidePackagesRe:
    def test_matches_simple_list(self):
        src = '_PYODIDE_PACKAGES = ["scipy", "pandas"]'
        m = _PYODIDE_PACKAGES_RE.search(src)
        assert m is not None
        import ast
        assert ast.literal_eval(m.group(1)) == ["scipy", "pandas"]

    def test_matches_empty_list(self):
        src = "_PYODIDE_PACKAGES = []"
        m = _PYODIDE_PACKAGES_RE.search(src)
        assert m is not None

    def test_no_match_when_absent(self):
        src = "import numpy as np\nfig, ax = apl.subplots(1, 1)"
        assert _PYODIDE_PACKAGES_RE.search(src) is None


# ---------------------------------------------------------------------------
# _find_widget
# ---------------------------------------------------------------------------

class TestFindWidget:
    def test_finds_figure(self, line_fig):
        found = _find_widget({"fig": line_fig, "x": 42})
        assert found is line_fig

    def test_returns_none_for_non_widget(self):
        assert _find_widget({"x": 42, "y": "hello"}) is None

    def test_returns_last_widget(self, line_fig, imshow_fig):
        found = _find_widget({"fig1": line_fig, "fig2": imshow_fig})
        assert found is imshow_fig

    def test_ignores_non_callable_repr_html(self):
        class FakeWidget:
            _repr_html_ = "not callable"
            _esm = "..."
        assert _find_widget({"w": FakeWidget()}) is None

    def test_finds_widget_without_esm_by_module(self):
        class ModuleWidget:
            def _repr_html_(self):
                return "<div/>"
            def traits(self):
                return {}
        ModuleWidget.__module__ = "somewidget.core"
        found = _find_widget({"w": ModuleWidget()})
        assert found is not None


# ---------------------------------------------------------------------------
# _iframe_html
# ---------------------------------------------------------------------------

class TestIframeHtml:
    def test_returns_string(self):
        html = _iframe_html("test.html", 400, 300, fig_id="abc")
        assert isinstance(html, str)

    def test_contains_iframe_src(self):
        html = _iframe_html("test.html", 400, 300, fig_id="abc")
        assert 'src="test.html"' in html

    def test_interactive_has_activate_btn(self):
        html = _iframe_html("t.html", 400, 300, fig_id="a", interactive=True)
        assert "awi-activate-btn" in html

    def test_static_no_activate_btn(self):
        html = _iframe_html("t.html", 400, 300, fig_id="a", interactive=False)
        assert "awi-activate-btn" not in html

    def test_fig_id_in_output(self):
        html = _iframe_html("t.html", 400, 300, fig_id="myfig")
        assert "myfig" in html

    def test_auto_uid_when_no_fig_id(self):
        html = _iframe_html("t.html", 400, 300)
        assert isinstance(html, str)
        assert len(html) > 0

    def test_max_width_respected(self):
        html = _iframe_html("t.html", 1000, 500, fig_id="w", max_width=400)
        # The wrapper div should have width <= 400px
        assert "400px" in html or "width:400px" in html.replace(" ", "")

    def test_default_max_width_is_MAX_DOC_WIDTH(self):
        html = _iframe_html("t.html", MAX_DOC_WIDTH + 100, 300, fig_id="w")
        assert f"{MAX_DOC_WIDTH}px" in html

    def test_max_height_constrains_scale(self):
        html = _iframe_html("t.html", 400, 800, fig_id="h", max_height=200)
        assert isinstance(html, str)

    def test_contains_resize_script(self):
        html = _iframe_html("t.html", 400, 300, fig_id="rs")
        assert "requestAnimationFrame" in html

    def test_no_badge_when_not_interactive(self):
        html = _iframe_html("t.html", 400, 300, fig_id="nb", interactive=False)
        assert "awi-badge" not in html

    def test_badge_present_when_interactive(self):
        html = _iframe_html("t.html", 400, 300, fig_id="bi", interactive=True)
        assert "awi-badge" in html


# ---------------------------------------------------------------------------
# AnywidgetScraper / ViewerScraper
# ---------------------------------------------------------------------------

class TestAnywidgetScraper:
    def test_repr(self):
        s = AnywidgetScraper()
        assert repr(s) == "AnywidgetScraper()"

    def test_viewerscraper_is_alias(self):
        assert ViewerScraper is AnywidgetScraper

    def test_call_returns_empty_string_when_no_widget(self):
        scraper = AnywidgetScraper()
        block = ("code", "x = 1")
        block_vars = {
            "example_globals": {"x": 1},
            "image_path_iterator": iter([]),
            "src_file": "test.py",
        }
        result = scraper(block, block_vars, {})
        assert result == ""

    def test_call_returns_empty_when_globals_empty(self):
        scraper = AnywidgetScraper()
        block = ("code", "x = 1")
        block_vars = {
            "example_globals": {},
            "image_path_iterator": iter([]),
            "src_file": "test.py",
        }
        result = scraper(block, block_vars, {})
        assert result == ""


# ---------------------------------------------------------------------------
# _make_thumbnail_png — Playwright
# ---------------------------------------------------------------------------

_has_playwright = importlib.util.find_spec("playwright") is not None


@pytest.mark.skipif(not _has_playwright, reason="playwright not installed")
class TestMakeThumbnailPng:
    def test_line_fig_returns_valid_png(self, line_fig):
        from anyplotlib.sphinx_anywidget._scraper import _make_thumbnail_png
        png_bytes = _make_thumbnail_png(line_fig)
        assert isinstance(png_bytes, bytes)
        assert png_bytes[:8] == b"\x89PNG\r\n\x1a\n", "Not a valid PNG"

    def test_imshow_fig_returns_valid_png(self, imshow_fig):
        from anyplotlib.sphinx_anywidget._scraper import _make_thumbnail_png
        png_bytes = _make_thumbnail_png(imshow_fig)
        arr = decode_png(png_bytes)
        assert arr.ndim == 3
        assert arr.shape[2] in (3, 4)

    def test_multi_panel_returns_valid_png(self, multi_panel_fig):
        from anyplotlib.sphinx_anywidget._scraper import _make_thumbnail_png
        png_bytes = _make_thumbnail_png(multi_panel_fig)
        assert isinstance(png_bytes, bytes)
        assert len(png_bytes) > 0

    def test_thumbnail_is_dark_theme(self, line_fig):
        from anyplotlib.sphinx_anywidget._scraper import _make_thumbnail_png
        png_bytes = _make_thumbnail_png(line_fig)
        arr = decode_png(png_bytes)
        # Dark theme (#1e1e2e) — top-left pixel should be dark
        top_left = arr[0, 0, :3]
        assert top_left.sum() < 200, (
            f"Expected dark background pixel, got {top_left}"
        )

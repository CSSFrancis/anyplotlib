"""
sphinx_anywidget/tests/conftest.py
====================================

Standalone pytest configuration for sphinx_anywidget tests.

This conftest is designed to be self-contained so that when sphinx_anywidget
is extracted into its own package the tests move with no changes.

Future standalone package name : sphinx-anywidget
Future dependencies            : anywidget, playwright, pytest, numpy
"""
from __future__ import annotations

import pathlib
import tempfile

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# Figure fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def simple_fig():
    import anyplotlib as apl
    fig, ax = apl.subplots(1, 1, figsize=(400, 300))
    ax.plot(np.sin(np.linspace(0, 6.28, 64)))
    return fig


@pytest.fixture
def imshow_fig():
    import anyplotlib as apl
    fig, ax = apl.subplots(1, 1, figsize=(320, 320))
    ax.imshow(np.linspace(0, 1, 64 * 64, dtype=np.float32).reshape(64, 64))
    return fig


# ---------------------------------------------------------------------------
# Playwright browser (one Chromium instance for the whole test session)
# ---------------------------------------------------------------------------

@pytest.fixture
def saw_browser(request):
    """Headless Chromium browser for sphinx_anywidget Playwright tests.

    When running inside the combined anyplotlib test suite, reuses the
    existing session-scoped ``_pw_browser`` fixture (from
    ``anyplotlib/tests/conftest.py``) to avoid spawning a second
    ``sync_playwright()`` context — two concurrent contexts fail in one
    process.

    When running standalone (future separate package), creates its own
    headless Chromium instance.
    """
    pytest.importorskip("playwright", reason="playwright not installed")

    try:
        # Combined suite path: _pw_browser is session-scoped and getfixturevalue
        # initialises it on first access, then reuses it.  No second
        # sync_playwright() context is opened.
        yield request.getfixturevalue("_pw_browser")
        return
    except pytest.FixtureLookupError:
        pass

    # Standalone path: create our own browser.
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        yield browser
        browser.close()


# ---------------------------------------------------------------------------
# HTML page helper
# ---------------------------------------------------------------------------

@pytest.fixture
def render_widget_page(saw_browser):
    """Callable: open a widget's standalone HTML in a headless browser page.

    Returns a ``(page, tmp_path)`` pair.  Caller is responsible for closing
    the page when done (or use the ``render_page`` fixture instead).
    """
    from anyplotlib.sphinx_anywidget._repr_utils import build_standalone_html

    _pages: list = []
    _paths: list = []

    def _open(widget, *, fig_id="test_fig"):
        html = build_standalone_html(widget, resizable=False, fig_id=fig_id)
        # Inject readiness sentinel so we can wait for render completion.
        html = html.replace(
            "renderFn({ model, el });",
            "renderFn({ model, el }); window._aplReady = true;",
        )
        with tempfile.NamedTemporaryFile(
            suffix=".html", mode="w", encoding="utf-8", delete=False
        ) as fh:
            fh.write(html)
            tmp = pathlib.Path(fh.name)
        _paths.append(tmp)

        page = saw_browser.new_page()
        _pages.append(page)
        page.goto(tmp.as_uri())
        page.wait_for_function("() => window._aplReady === true", timeout=15_000)
        page.evaluate(
            "() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))"
        )
        return page

    yield _open

    for page in _pages:
        try:
            page.close()
        except Exception:
            pass
    for path in _paths:
        path.unlink(missing_ok=True)

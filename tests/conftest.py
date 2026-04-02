"""
tests/conftest.py
=================
Shared pytest fixtures and command-line options for the anyplotlib test suite.
Visual regression
-----------------
* ``--update-baselines``  regenerate the golden PNG files in ``tests/baselines/``
* ``take_screenshot``  session-scoped fixture: callable(widget) -> H×W×C uint8 ndarray

The screenshot helper:
  1. Calls ``build_standalone_html(widget, resizable=False)`` to get a fully
     self-contained HTML page (ESM + initial model state inlined).
  2. Injects a ``window._aplReady`` sentinel that fires after the widget's
     ``render()`` function has run and all canvases have been painted.
  3. Opens the HTML in headless Chromium (Playwright) and waits for the sentinel.
  4. Grabs a full-page screenshot and decodes it to a numpy array via our
     pure-stdlib PNG decoder (no PIL / matplotlib required).
"""
from __future__ import annotations
import pathlib
import tempfile
import pytest


# ---------------------------------------------------------------------------
# CLI option
# ---------------------------------------------------------------------------

def pytest_addoption(parser):
    parser.addoption(
        "--update-baselines",
        action="store_true",
        default=False,
        help="Regenerate golden PNG baselines in tests/baselines/",
    )


@pytest.fixture(scope="session")
def update_baselines(request):
    return request.config.getoption("--update-baselines")


# ---------------------------------------------------------------------------
# Playwright browser  (one Chromium instance for the whole test session)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def _pw_browser():
    """Yield a headless Chromium browser for the whole test session."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        yield browser
        browser.close()


# ---------------------------------------------------------------------------
# HTML builder with readiness sentinel
# ---------------------------------------------------------------------------

def _build_ready_html(widget):
    """Return build_standalone_html() output with a window._aplReady sentinel.

    The sentinel ``window._aplReady = true`` is injected immediately after
    the synchronous ``renderFn({ model, el })`` call so Playwright's
    ``wait_for_function`` can poll for render completion without relying on
    arbitrary sleep durations.
    """
    from anyplotlib._repr_utils import build_standalone_html

    html = build_standalone_html(widget, resizable=False)
    # The template always produces this exact substring after .format()
    html = html.replace(
        "renderFn({ model, el });",
        "renderFn({ model, el }); window._aplReady = true;",
    )
    return html


# ---------------------------------------------------------------------------
# Core screenshot helper (not a fixture — called by the fixture below)
# ---------------------------------------------------------------------------

def _screenshot_widget(browser, widget):
    """Render *widget* in headless Chromium; return an H×W×C uint8 ndarray."""
    from tests._png_utils import decode_png

    html = _build_ready_html(widget)

    # Write to a temp file so the browser can load it via file://
    # Blob-URL imports work in Chromium from file:// origins.
    with tempfile.NamedTemporaryFile(
        suffix=".html", mode="w", encoding="utf-8", delete=False
    ) as fh:
        fh.write(html)
        tmp_path = pathlib.Path(fh.name)

    page = browser.new_page()
    try:
        page.goto(tmp_path.as_uri())
        # Wait until render() has fully executed (sentinel set synchronously
        # inside the import().then() microtask).
        page.wait_for_function("() => window._aplReady === true", timeout=15_000)
        # Two rAFs: first lets the compositor transfer canvas pixels to the
        # frame buffer; second ensures the element bounding-box is stable.
        page.evaluate(
            "() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))"
        )
        # Screenshot only the widget root — gives exact widget pixels,
        # independent of the browser's default 1280×720 viewport size.
        png_bytes = page.locator("#widget-root").screenshot()
    finally:
        page.close()
        tmp_path.unlink(missing_ok=True)

    return decode_png(png_bytes)


# ---------------------------------------------------------------------------
# Public fixture
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def take_screenshot(_pw_browser):
    """Return a callable ``(widget) -> H×W×C uint8 ndarray``.

    Renders the widget's ``build_standalone_html()`` output in headless
    Chromium and decodes the resulting PNG with the pure-stdlib decoder in
    ``tests/_png_utils``.  The browser instance is shared across the whole
    test session for speed.
    """
    def _take(widget):
        return _screenshot_widget(_pw_browser, widget)
    return _take


# ---------------------------------------------------------------------------
# Interaction helper + fixture
# ---------------------------------------------------------------------------

def _build_interact_html(widget):
    """Like _build_ready_html but also exposes ``window._aplModel``.

    Injecting the model reference into ``window`` lets Playwright tests read
    back any traitlet value via ``page.evaluate()`` after a simulated
    mouse interaction without needing a live Python kernel.
    """
    html = _build_ready_html(widget)
    # The template renders "const model   = makeModel(STATE);" exactly once.
    html = html.replace(
        "const model   = makeModel(STATE);",
        "const model   = makeModel(STATE);\nwindow._aplModel = model;",
    )
    return html


@pytest.fixture
def interact_page(_pw_browser):
    """Fixture returning a callable ``open_widget(fig) → page``.

    Opens the widget HTML in a new headless Chromium page, waits for
    ``window._aplReady``, then returns the live ``Page`` object so the test
    can fire mouse events and read back model state.  All pages are closed
    and temp files removed automatically when the test ends.

    Usage::

        def test_something(interact_page):
            fig, ax = apl.subplots(1, 1, figsize=(400, 240))
            plot = ax.plot(np.zeros(100))
            vline = plot.add_vline_widget(50.0)

            page = interact_page(fig)
            page.mouse.move(233, 113)
            page.mouse.down()
            page.mouse.move(133, 113, steps=10)
            page.mouse.up()
            ...
    """
    import pathlib
    import tempfile

    _pages: list = []
    _paths: list = []

    def _open(widget):
        html = _build_interact_html(widget)
        with tempfile.NamedTemporaryFile(
            suffix=".html", mode="w", encoding="utf-8", delete=False
        ) as fh:
            fh.write(html)
            tmp = pathlib.Path(fh.name)
        _paths.append(tmp)

        page = _pw_browser.new_page()
        _pages.append(page)
        page.goto(tmp.as_uri())
        page.wait_for_function("() => window._aplReady === true", timeout=15_000)
        # Two rAFs: let the initial canvas draw settle before any mouse event.
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


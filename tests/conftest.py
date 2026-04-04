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
import json
import pathlib
import tempfile
import pytest


# ---------------------------------------------------------------------------
# CLI options
# ---------------------------------------------------------------------------

def pytest_addoption(parser):
    parser.addoption(
        "--update-baselines",
        action="store_true",
        default=False,
        help="Regenerate golden PNG baselines in tests/baselines/",
    )
    parser.addoption(
        "--update-benchmarks",
        action="store_true",
        default=False,
        help="Regenerate render-time benchmark baselines in tests/benchmarks/baselines.json",
    )
    parser.addoption(
        "--run-slow",
        action="store_true",
        default=False,
        help="Include slow benchmark scenarios (4096², 8192² images) skipped in fast CI",
    )
    parser.addoption(
        "--baselines-path",
        default=None,
        metavar="PATH",
        help=(
            "Override the path used to read/write benchmark baselines "
            "(default: tests/benchmarks/baselines.json). "
            "Use this in CI to keep the committed developer baselines untouched: "
            "run the base branch with --update-benchmarks --baselines-path /tmp/ci_baselines.json, "
            "then run the head branch with --baselines-path /tmp/ci_baselines.json."
        ),
    )


@pytest.fixture(scope="session")
def update_baselines(request):
    return request.config.getoption("--update-baselines")


# ---------------------------------------------------------------------------
# Baselines-path override
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session", autouse=True)
def _set_baselines_path(request):
    """Patch BASELINES_PATH in both benchmark modules when --baselines-path is given.

    This lets CI workflows direct reads/writes to a temporary file without
    modifying the committed ``tests/benchmarks/baselines.json``.  Because
    both ``_load_baselines`` and ``_save_baselines`` look up the module-level
    ``BASELINES_PATH`` at call time, patching the attribute after import is
    sufficient — no test-function signature changes required.

    The scan uses ``sys.modules`` rather than a hard-coded import path so it
    works correctly under both pytest's default ``prepend`` import mode
    (modules imported as ``test_benchmarks_py``) and ``importlib`` mode
    (``tests.test_benchmarks_py``).
    """
    import sys

    path_opt = request.config.getoption("--baselines-path")
    if not path_opt:
        return

    new_path = pathlib.Path(path_opt)

    patched = []
    for mod_name, mod in list(sys.modules.items()):
        if mod is None:
            continue
        if "test_benchmarks" not in mod_name:
            continue
        if not hasattr(mod, "BASELINES_PATH"):
            continue
        mod.BASELINES_PATH = new_path
        patched.append(mod_name)

    if not patched:
        import warnings
        warnings.warn(
            f"--baselines-path={path_opt!r} was given but no benchmark module "
            "was found in sys.modules to patch. The option has no effect.",
            stacklevel=1,
        )


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


# ---------------------------------------------------------------------------
# Benchmark fixtures + helper
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def update_benchmarks(request):
    """True when --update-benchmarks was passed on the command line."""
    return request.config.getoption("--update-benchmarks")


@pytest.fixture(scope="session")
def run_slow(request):
    """True when --run-slow was passed (enables 4K²/8K² scenarios)."""
    return request.config.getoption("--run-slow")


@pytest.fixture
def bench_page(_pw_browser):
    """Fixture: open a widget in headless Chromium and return the live Page.

    Identical to ``interact_page`` but purpose-named for benchmark tests so
    the two fixture pools stay independent.  The opened page exposes both
    ``window._aplModel`` (for model mutations) and ``window._aplTiming``
    (populated by ``_recordFrame`` inside ``figure_esm.js``) so Playwright
    can drive renders and read back timing without a live Python kernel.

    Usage::

        def test_bench_something(bench_page):
            fig, ax = apl.subplots(1, 1, figsize=(320, 320))
            plot = ax.imshow(np.random.rand(256, 256).astype(np.float32))
            page = bench_page(fig)
            timing = _run_bench(page, plot._id)
            assert timing["mean_ms"] < 50
    """
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
        page.wait_for_function("() => window._aplReady === true", timeout=60_000)
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


def _run_bench(page, panel_id, *, n_warmup=3, n_samples=15,
               perturb_field="display_min", perturb_delta=1e-4,
               timeout=120_000):
    """Drive N render cycles in *page* and return the ``_aplTiming`` dict.

    Each cycle slightly perturbs *perturb_field* in the panel state so the
    JS blit-cache is always invalidated and the full decode→LUT→render path
    is exercised on every frame.  Renders are paced with ``requestAnimationFrame``
    so successive ``createImageBitmap`` calls have time to commit before the
    next one is queued — giving realistic throughput numbers rather than a
    burst of back-to-back initiations.

    ``n_warmup`` frames are discarded (they prime the JIT and caches);
    ``n_samples`` frames are timed.  The function blocks until all frames
    are complete (or *timeout* ms elapses).

    Parameters
    ----------
    page        : Playwright Page (from ``bench_page`` fixture)
    panel_id    : str — ``plot._id`` of the panel to benchmark
    n_warmup    : int — frames to discard before timing starts
    n_samples   : int — frames to time
    perturb_field : str — state field to nudge each frame (invalidates cache)
    perturb_delta : float — amount to nudge by per frame
    timeout     : int — Playwright evaluate timeout in ms

    Returns
    -------
    dict with keys: count, fps, mean_ms, min_ms, max_ms
    """
    js = """
    ([panelId, nWarmup, nSamples, field, delta]) =>
      new Promise((resolve, reject) => {
        const total = nWarmup + nSamples;
        let i = 0;

        function step() {
          if (i >= total) {
            resolve(window._aplTiming ? window._aplTiming[panelId] : null);
            return;
          }

          // Perturb one small field so the blit-cache key changes and the
          // full draw path is exercised on every frame.
          const key = 'panel_' + panelId + '_json';
          try {
            const st = JSON.parse(window._aplModel.get(key));
            st[field] = (st[field] || 0) + delta;
            window._aplModel.set(key, JSON.stringify(st));
          } catch(e) { reject(e); return; }

          // After warmup completes, wipe the timing buffer so only the
          // measured frames are included in the final result.
          if (i === nWarmup - 1) {
            if (window._aplTiming) delete window._aplTiming[panelId];
          }

          i++;
          requestAnimationFrame(step);
        }

        requestAnimationFrame(step);
      })
    """
    page.set_default_timeout(timeout)
    try:
        return page.evaluate(js, [panel_id, n_warmup, n_samples,
                                   perturb_field, perturb_delta])
    finally:
        page.set_default_timeout(30_000)  # restore Playwright default


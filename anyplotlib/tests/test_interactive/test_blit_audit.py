"""
tests/test_interactive/test_blit_audit.py
==========================================

Playwright tests that audit canvas redraws and verify blitting behaviour.

What we are testing
--------------------
1. **Blit cache correctness** — The ``blitCache`` in ``figure_esm.js`` keyed
   on ``(b64, lutKey, w, h)`` must be a genuine cache: adding a marker must
   NOT create a new ``OffscreenCanvas`` (GPU texture), while changes to the
   LUT parameters (display_min/max, scale_mode, cmap) MUST create a new one.

2. **No flash on marker add** — Since markers live on a separate
   ``markersCanvas`` layer, adding a marker should only clear-and-redraw that
   layer.  The base ``plotCanvas`` texture must be preserved (blitted, not
   rebuilt).

3. **Draw-call auditing** — Each ``model.set(panel_<id>_json, ...)`` call
   triggers exactly one ``draw2d`` invocation.  We count draw calls via an
   injected Proxy on ``window._aplTiming`` that increments
   ``window._aplDrawCount[id]`` on every timing assignment.

Instrumentation strategy
-------------------------
Two counters are injected via ``page.add_init_script()`` before any page JS:

**OffscreenCanvas counter** — wraps the global class:

    window._aplBitmapRebuildCount = 0
    class _TrackedOffscreen extends OffscreenCanvas {
        constructor(w, h) { super(w, h); window._aplBitmapRebuildCount++; }
    }
    globalThis.OffscreenCanvas = _TrackedOffscreen;

After the initial render this counter equals 1.  Each blit-cache miss bumps
it by 1; a cache hit leaves it unchanged.

**Draw-call counter** — intercepts ``_aplTiming[id]`` property assignments:

    window._aplTiming = new Proxy({}, {
        set(target, key, value) {
            window._aplDrawCount[key]++;
            ...
        }
    });

``_recordFrame`` in ``figure_esm.js`` sets ``window._aplTiming[id]`` every
draw when ``n >= 2`` (rolling buffer has at least 2 entries).  The very first
draw (n=1) is not counted, so ``_aplDrawCount[id] = total_draws - 1``.
Delta tests are used throughout to avoid dependence on this off-by-one.
"""
from __future__ import annotations

import pathlib
import tempfile

import numpy as np
import pytest

import anyplotlib as apl

# ---------------------------------------------------------------------------
# Init script: injects both counters before page JS runs
# ---------------------------------------------------------------------------

_INSTRUMENTATION_SCRIPT = """
(function () {
  // ── OffscreenCanvas rebuild counter ───────────────────────────────────────
  window._aplBitmapRebuildCount = 0;
  const _OrigOffscreen = globalThis.OffscreenCanvas;
  class _TrackedOffscreen extends _OrigOffscreen {
    constructor(w, h) {
      super(w, h);
      window._aplBitmapRebuildCount++;
    }
  }
  globalThis.OffscreenCanvas = _TrackedOffscreen;

  // ── Draw-call counter via _aplTiming Proxy ────────────────────────────────
  // _recordFrame() in figure_esm.js does:
  //   if (!window._aplTiming) window._aplTiming = {};   // skipped: proxy is truthy
  //   window._aplTiming[p.id] = { count: n, ... };      // triggers our setter
  // This fires on every draw after the rolling buffer reaches n >= 2.
  window._aplDrawCount = {};
  window._aplTiming = new Proxy({}, {
    set: function(target, key, value) {
      if (typeof key === 'string') {
        window._aplDrawCount[key] = (window._aplDrawCount[key] || 0) + 1;
      }
      return Reflect.set(target, key, value);
    }
  });
})();
"""


# ---------------------------------------------------------------------------
# blit_page fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def blit_page(_pw_browser):
    """Like ``bench_page`` but injects rebuild + draw-call counters.

    Uses ``page.add_init_script()`` to wrap ``OffscreenCanvas`` and
    ``window._aplTiming`` *before* the page's ``render()`` function runs.

    Usage::

        def test_something(blit_page):
            fig, ax = apl.subplots(1, 1, figsize=(400, 300))
            plot = ax.imshow(np.zeros((32, 32)))
            page = blit_page(fig)
            assert _get_rebuild_count(page) == 1
    """
    from anyplotlib.tests.conftest import _build_interact_html

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
        # Inject counters BEFORE navigation so they wrap globals at startup.
        page.add_init_script(_INSTRUMENTATION_SCRIPT)
        page.goto(tmp.as_uri())
        page.wait_for_function("() => window._aplReady === true", timeout=30_000)
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
# JS helpers
# ---------------------------------------------------------------------------

def _get_rebuild_count(page) -> int:
    """Number of OffscreenCanvas instances created (= bitmap rebuilds)."""
    return page.evaluate("() => window._aplBitmapRebuildCount")


def _get_draw_count(page, panel_id: str) -> int:
    """Monotonic draw-call count for *panel_id* via the _aplTiming proxy.

    Returns 0 after the initial render (n=1, proxy not yet set) and
    increments by 1 for each subsequent draw.  Delta comparisons are
    therefore reliable: draw_after - draw_before == draws_triggered.
    """
    return page.evaluate(
        "([id]) => (window._aplDrawCount && window._aplDrawCount[id] || 0)",
        [panel_id],
    )


def _set_panel_state(page, panel_id: str, update: dict) -> None:
    """Merge *update* into the panel state and push to the model synchronously."""
    page.evaluate(
        """([id, patch]) => {
            const key = 'panel_' + id + '_json';
            const st = JSON.parse(window._aplModel.get(key));
            Object.assign(st, patch);
            window._aplModel.set(key, JSON.stringify(st));
        }""",
        [panel_id, update],
    )


def _add_circle_markers(page, panel_id: str, offsets=None) -> None:
    """Append a circle marker group to the panel state (no image data change)."""
    if offsets is None:
        offsets = [[16, 16]]
    page.evaluate(
        """([id, offsets]) => {
            const key = 'panel_' + id + '_json';
            const st = JSON.parse(window._aplModel.get(key));
            const existing = st.markers || [];
            existing.push({
                type: 'circles',
                offsets: offsets,
                sizes: [5],
                color: '#ff0000',
            });
            st.markers = existing;
            window._aplModel.set(key, JSON.stringify(st));
        }""",
        [panel_id, offsets],
    )


def _wait_raf(page) -> None:
    """Wait two rAF ticks so canvas compositing catches up."""
    page.evaluate(
        "() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))"
    )


# ══════════════════════════════════════════════════════════════════════════════
# Blit cache correctness
# ══════════════════════════════════════════════════════════════════════════════

class TestBlitCacheCorrectness:
    """The blit cache key (b64 string + LUT params) must be honoured."""

    def _make_page(self, blit_page):
        fig, ax = apl.subplots(1, 1, figsize=(400, 300))
        plot = ax.imshow(np.zeros((32, 32), dtype=np.float32))
        page = blit_page(fig)
        return page, plot

    def test_initial_render_creates_one_bitmap(self, blit_page):
        """After initial render exactly one OffscreenCanvas has been created."""
        page, plot = self._make_page(blit_page)
        count = _get_rebuild_count(page)
        assert count == 1, (
            f"Expected 1 OffscreenCanvas after initial render, got {count}"
        )

    def test_adding_marker_does_not_rebuild_bitmap(self, blit_page):
        """Adding a marker uses the cached bitmap — no new OffscreenCanvas.

        This is the core 'no flash' assertion: markers live on a separate
        canvas layer, so the base image texture must not be invalidated.
        """
        page, plot = self._make_page(blit_page)
        count_before = _get_rebuild_count(page)

        _add_circle_markers(page, plot._id)
        _wait_raf(page)

        count_after = _get_rebuild_count(page)
        assert count_after == count_before, (
            f"Adding a marker must NOT create a new OffscreenCanvas "
            f"(before={count_before}, after={count_after})"
        )

    def test_adding_multiple_markers_does_not_rebuild_bitmap(self, blit_page):
        """Adding N markers sequentially causes 0 extra OffscreenCanvas creations."""
        page, plot = self._make_page(blit_page)
        count_before = _get_rebuild_count(page)

        for i in range(5):
            _add_circle_markers(page, plot._id, offsets=[[i * 5, i * 5]])
        _wait_raf(page)

        count_after = _get_rebuild_count(page)
        assert count_after == count_before, (
            f"Adding 5 markers must not rebuild the bitmap "
            f"(before={count_before}, after={count_after})"
        )

    def test_lut_change_invalidates_cache(self, blit_page):
        """Changing display_min (LUT key) creates exactly one new OffscreenCanvas."""
        page, plot = self._make_page(blit_page)
        count_before = _get_rebuild_count(page)

        _set_panel_state(page, plot._id, {"display_min": -0.5})
        _wait_raf(page)

        count_after = _get_rebuild_count(page)
        assert count_after == count_before + 1, (
            f"Changing display_min must trigger one bitmap rebuild "
            f"(before={count_before}, after={count_after})"
        )

    def test_lut_change_then_marker_add_reuses_new_bitmap(self, blit_page):
        """After a LUT rebuild, subsequent marker adds still hit the cache."""
        page, plot = self._make_page(blit_page)

        # Invalidate cache with LUT change
        _set_panel_state(page, plot._id, {"display_min": -0.5})
        count_after_lut = _get_rebuild_count(page)

        # Marker add must reuse the updated bitmap
        _add_circle_markers(page, plot._id)
        _wait_raf(page)

        count_after_marker = _get_rebuild_count(page)
        assert count_after_marker == count_after_lut, (
            "After LUT rebuild, marker add must still use the cached bitmap. "
            f"(after_lut={count_after_lut}, after_marker={count_after_marker})"
        )

    def test_display_max_change_invalidates_cache(self, blit_page):
        """Changing display_max also invalidates the blit cache."""
        page, plot = self._make_page(blit_page)
        count_before = _get_rebuild_count(page)

        _set_panel_state(page, plot._id, {"display_max": 2.0})
        _wait_raf(page)

        count_after = _get_rebuild_count(page)
        assert count_after > count_before, (
            "Changing display_max must trigger a bitmap rebuild"
        )

    def test_pan_does_not_rebuild_bitmap(self, blit_page):
        """Changing center_x/y (pan) does not rebuild the bitmap."""
        page, plot = self._make_page(blit_page)
        count_before = _get_rebuild_count(page)

        _set_panel_state(page, plot._id, {"center_x": 0.6, "center_y": 0.4})
        _wait_raf(page)

        count_after = _get_rebuild_count(page)
        assert count_after == count_before, (
            f"Pan (center_x/y change) must not rebuild the bitmap "
            f"(before={count_before}, after={count_after})"
        )

    def test_zoom_does_not_rebuild_bitmap(self, blit_page):
        """Changing zoom does not rebuild the bitmap."""
        page, plot = self._make_page(blit_page)
        count_before = _get_rebuild_count(page)

        _set_panel_state(page, plot._id, {"zoom": 2.0})
        _wait_raf(page)

        count_after = _get_rebuild_count(page)
        assert count_after == count_before, (
            f"Zoom change must not rebuild the bitmap "
            f"(before={count_before}, after={count_after})"
        )


# ══════════════════════════════════════════════════════════════════════════════
# Draw-call count audit
# ══════════════════════════════════════════════════════════════════════════════

class TestDrawCallAudit:
    """Each state mutation must trigger exactly one draw2d call.

    Draw counts use _aplDrawCount which increments on every _aplTiming[id]
    assignment (after n≥2 frames).  The very first draw (n=1) is not counted,
    so deltas are used: draw_after - draw_before == draws_triggered_by_action.
    """

    def _make_page(self, blit_page):
        fig, ax = apl.subplots(1, 1, figsize=(400, 300))
        plot = ax.imshow(np.zeros((32, 32), dtype=np.float32))
        page = blit_page(fig)
        return page, plot

    def test_draw_count_baseline_after_initial_render(self, blit_page):
        """After initial render only, draw count = 0 (1 draw occurred, n=1 < threshold)."""
        page, plot = self._make_page(blit_page)
        count = _get_draw_count(page, plot._id)
        assert count == 0, (
            f"After initial render, draw count must be 0 (n=1 not yet counted). "
            f"Got {count} — indicates unexpected extra draws during setup."
        )

    def test_marker_add_triggers_exactly_one_draw(self, blit_page):
        """Adding a single marker triggers exactly one additional draw2d call."""
        page, plot = self._make_page(blit_page)
        draw_before = _get_draw_count(page, plot._id)

        _add_circle_markers(page, plot._id)

        draw_after = _get_draw_count(page, plot._id)
        assert draw_after == draw_before + 1, (
            f"Adding a marker must trigger exactly 1 draw "
            f"(before={draw_before}, after={draw_after}, delta={draw_after - draw_before})"
        )

    def test_n_marker_adds_trigger_n_draws(self, blit_page):
        """Adding N markers sequentially triggers exactly N draw2d calls."""
        page, plot = self._make_page(blit_page)
        draw_before = _get_draw_count(page, plot._id)

        n = 5
        for i in range(n):
            _add_circle_markers(page, plot._id, offsets=[[i * 4, i * 4]])

        draw_after = _get_draw_count(page, plot._id)
        assert draw_after == draw_before + n, (
            f"Adding {n} markers must trigger exactly {n} draws "
            f"(before={draw_before}, after={draw_after}, delta={draw_after - draw_before})"
        )

    def test_lut_change_triggers_exactly_one_draw(self, blit_page):
        """A LUT parameter change triggers exactly one draw2d call."""
        page, plot = self._make_page(blit_page)
        draw_before = _get_draw_count(page, plot._id)

        _set_panel_state(page, plot._id, {"display_min": -0.5})

        draw_after = _get_draw_count(page, plot._id)
        assert draw_after == draw_before + 1, (
            f"LUT change must trigger exactly 1 draw "
            f"(before={draw_before}, after={draw_after})"
        )

    def test_pan_triggers_exactly_one_draw(self, blit_page):
        """A Python-side pan update triggers exactly one draw2d call."""
        page, plot = self._make_page(blit_page)
        draw_before = _get_draw_count(page, plot._id)

        _set_panel_state(page, plot._id, {"center_x": 0.6})

        draw_after = _get_draw_count(page, plot._id)
        assert draw_after == draw_before + 1, (
            "Python-side pan update must trigger exactly 1 draw "
            f"(before={draw_before}, after={draw_after})"
        )


# ══════════════════════════════════════════════════════════════════════════════
# No-flash integration test
# ══════════════════════════════════════════════════════════════════════════════

class TestNoFlashOnMarkerAdd:
    """End-to-end: adding a marker must not flash (no bitmap rebuild + 1 draw)."""

    def test_no_flash_single_marker(self, blit_page):
        """Single marker add: one extra draw, zero extra bitmap rebuilds."""
        fig, ax = apl.subplots(1, 1, figsize=(400, 300))
        plot = ax.imshow(
            np.random.default_rng(0).standard_normal((64, 64)).astype(np.float32)
        )
        page = blit_page(fig)

        rebuild_before = _get_rebuild_count(page)
        draw_before = _get_draw_count(page, plot._id)

        _add_circle_markers(page, plot._id, offsets=[[32, 32]])
        _wait_raf(page)

        rebuild_after = _get_rebuild_count(page)
        draw_after = _get_draw_count(page, plot._id)

        assert rebuild_after == rebuild_before, (
            "Adding a marker must not rebuild the GPU bitmap (would cause a flash). "
            f"OffscreenCanvas count: {rebuild_before} → {rebuild_after}"
        )
        assert draw_after == draw_before + 1, (
            f"Expected exactly 1 new draw call, got {draw_after - draw_before}"
        )

    def test_no_flash_multiple_markers_on_real_image(self, blit_page):
        """Multiple marker adds on a real image: zero bitmap rebuilds throughout."""
        rng = np.random.default_rng(42)
        fig, ax = apl.subplots(1, 1, figsize=(400, 300))
        plot = ax.imshow(rng.standard_normal((128, 128)).astype(np.float32))
        page = blit_page(fig)

        rebuild_before = _get_rebuild_count(page)

        for i in range(4):
            _add_circle_markers(
                page, plot._id,
                offsets=[[int(rng.integers(10, 118)), int(rng.integers(10, 118))]]
            )
        _wait_raf(page)

        rebuild_after = _get_rebuild_count(page)
        assert rebuild_after == rebuild_before, (
            "4 sequential marker adds must not rebuild the bitmap. "
            f"OffscreenCanvas count: {rebuild_before} → {rebuild_after}"
        )

    def test_flash_does_occur_on_lut_change(self, blit_page):
        """Sanity: changing LUT params DOES create a new OffscreenCanvas."""
        fig, ax = apl.subplots(1, 1, figsize=(400, 300))
        plot = ax.imshow(np.zeros((32, 32), dtype=np.float32))
        page = blit_page(fig)

        rebuild_before = _get_rebuild_count(page)

        _set_panel_state(page, plot._id, {"display_min": -1.0, "display_max": 1.0})
        _wait_raf(page)

        rebuild_after = _get_rebuild_count(page)
        assert rebuild_after > rebuild_before, (
            "LUT change must create a new OffscreenCanvas (confirms counter works). "
            f"OffscreenCanvas count: {rebuild_before} → {rebuild_after}"
        )

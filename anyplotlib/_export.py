"""Render a :class:`~anyplotlib.Figure` to a PNG file.

The renderer is the JavaScript one, so ``savefig`` drives it in a headless
Chromium rather than duplicating the LUT, gutter geometry and label engine in
Python: the figure is serialised to a standalone page and its ``exportPNG`` is
called through ``window._aplRenderApi``.

``source='native'`` needs the full array in the browser, which a **tiled** plot
never has — above ``Plot2D.TILE_THRESHOLD`` the page holds a downsampled
overview plus one detail tile.  For that case the plot is re-encoded at full
resolution into the snapshot only (:func:`_temporarily_untiled`).

Playwright is optional and imported lazily.
"""
from __future__ import annotations

import base64
import contextlib
import pathlib
import tempfile

import numpy as np

from anyplotlib._utils import _normalize_image

__all__ = ["savefig"]

#: Refuse to materialise a frame larger than this — a 16384² float64 array is
#: already 2 GB, and failing here beats an OOM.
MAX_NATIVE_PIXELS = 1 << 28          # 268 435 456 px

_PLAYWRIGHT_HINT = (
    "savefig() renders the figure in a headless browser and needs Playwright:\n"
    "\n"
    '    pip install "anyplotlib[docs]"\n'
    "    playwright install chromium\n"
)


# ── headless page plumbing (shared with the Sphinx thumbnail scraper) ─────────

def run_in_page(html: str, page_fn, *, timeout_ms: int = 30_000,
                color_scheme: str | None = None):
    """Load *html* in headless Chromium and return ``page_fn(page)``.

    Waits for ``window._aplReady`` and two animation frames.  Playwright's sync
    API cannot run inside a live asyncio loop (the Jupyter case), so the session
    moves to a worker thread when one is detected.
    """
    try:
        import playwright  # noqa: F401
    except ImportError as exc:                      # pragma: no cover - env dep
        raise RuntimeError(_PLAYWRIGHT_HINT) from exc

    with tempfile.NamedTemporaryFile(
        suffix=".html", mode="w", encoding="utf-8", delete=False
    ) as fh:
        fh.write(html)
        tmp = pathlib.Path(fh.name)

    def _run():
        from playwright.sync_api import sync_playwright

        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=True, args=["--no-sandbox", "--disable-setuid-sandbox"])
            page = None
            try:
                page = browser.new_page()
                if color_scheme:
                    page.emulate_media(color_scheme=color_scheme)
                page.goto(tmp.as_uri())
                page.wait_for_function(
                    "() => window._aplReady === true", timeout=timeout_ms)
                page.evaluate("() => new Promise(r => requestAnimationFrame("
                              "() => requestAnimationFrame(r)))")
                return page_fn(page)
            finally:
                if page is not None:
                    page.close()
                browser.close()

    try:
        import asyncio
        import concurrent.futures

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop is not None and loop.is_running():
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(_run).result()
        return _run()
    finally:
        tmp.unlink(missing_ok=True)


def _standalone_html(fig) -> str:
    """The figure's standalone page, with the ``_aplReady`` sentinel injected."""
    from anyplotlib._repr_utils import build_standalone_html

    html = build_standalone_html(fig, resizable=False)
    return html.replace(
        "renderFn({ model, el });",
        "renderFn({ model, el }); window._aplReady = true;",
    )


# ── full-resolution re-encode for tiled plots ────────────────────────────────

def _full_resolution_array(plot) -> np.ndarray:
    """Sample a tiled plot's backend at full resolution.

    Backend rows are in source order, so an ``origin='lower'`` backend is
    flipped to display order here — as the overview and detail tiles are.
    """
    backend = plot._tile_backend
    h, w = backend.full_shape
    if h * w > MAX_NATIVE_PIXELS:
        raise ValueError(
            f"source='native' would materialise a {w}x{h} frame "
            f"({w * h:,} px), over the {MAX_NATIVE_PIXELS:,} px limit. "
            "Export a sub-region (set_xlim/set_ylim then source='view'), or "
            "raise anyplotlib._export.MAX_NATIVE_PIXELS if you have the memory.")
    arr = backend.sample(0, w, 0, h, w, h, plot._integration_method)
    if backend.origin == "lower":
        arr = np.flipud(arr)
    return np.ascontiguousarray(arr)


#: Tiling keys, saved and restored around the full-resolution re-encode.
_TILE_STATE_KEYS = (
    "image_b64", "image_width", "image_height", "base_width", "base_height",
    "tile_enabled", "display_min", "display_max", "raw_min", "raw_max",
    "raw_is_int", "detail_b64", "detail_region", "detail_width",
    "detail_height", "detail_min", "detail_max", "detail_is_int",
)


@contextlib.contextmanager
def _temporarily_untiled(plot):
    """Re-encode *plot* at full resolution for the duration of the block.

    Only the panel's ``_state`` is touched and every key is restored, so the
    live figure is unchanged.  The current display window is reused as the
    quantisation clim, so the export carries the contrast on screen.
    """
    st = plot._state
    saved = {k: st.get(k) for k in _TILE_STATE_KEYS}
    saved_tile_on = plot._tile_on
    try:
        raw = _full_resolution_array(plot)
        h, w = raw.shape[:2]
        clim = (st.get("display_min"), st.get("display_max"))
        clim = clim if all(v is not None for v in clim) and clim[1] > clim[0] else None
        img_u8, vmin, vmax = _normalize_image(raw, clim=clim)
        st.update({
            "image_b64": plot._encode_pixels("image_b64", img_u8),
            "image_width": w,
            "image_height": h,
            # base_* == 0 → the base texture IS the full image
            "base_width": 0,
            "base_height": 0,
            "tile_enabled": False,
            "display_min": vmin,
            "display_max": vmax,
            "raw_min": vmin,
            "raw_max": vmax,
            # integral source → the renderer can invert codes to exact values
            "raw_is_int": bool(np.issubdtype(raw.dtype, np.integer)),
            # any detail tile describes the old base
            "detail_b64": "", "detail_region": [], "detail_width": 0,
            "detail_height": 0, "detail_min": None, "detail_max": None,
            "detail_is_int": False,
        })
        plot._tile_on = False
        yield
    finally:
        st.update(saved)
        plot._tile_on = saved_tile_on


# ── the public entry point ───────────────────────────────────────────────────

def _resolve_panel(fig, panel):
    """Return ``(panel_id, plot)`` for *panel*, or ``(None, None)``."""
    if panel is None:
        return None, None
    plots = fig._plots_map
    if isinstance(panel, str):
        if panel not in plots:
            raise ValueError(
                f"no panel with id {panel!r}; this figure has "
                f"{sorted(plots)!r}")
        return panel, plots[panel]
    for pid, plot in plots.items():
        if plot is panel:
            return pid, plot
    raise ValueError("panel= is not a plot of this figure")


def savefig(fig, path, *, source: str = "view", theme: str = "current",
            scale: float = 1, include_widgets: bool = True,
            panel=None, timeout_ms: int = 30_000) -> pathlib.Path:
    """Write *fig* to *path* as a PNG.  See :meth:`anyplotlib.Figure.savefig`."""
    if source not in ("view", "full", "native"):
        raise ValueError(
            f"source must be 'view', 'full' or 'native', got {source!r}")
    if theme not in ("current", "light", "dark"):
        raise ValueError(
            f"theme must be 'current', 'light' or 'dark', got {theme!r}")

    out = pathlib.Path(path)
    panel_id, plot = _resolve_panel(fig, panel)

    if source == "native":
        if plot is None:
            two_d = [(pid, p) for pid, p in fig._plots_map.items()
                     if getattr(p, "_state", {}).get("kind") == "2d"]
            if len(two_d) != 1:
                raise ValueError(
                    "source='native' exports one image panel, and this figure has "
                    f"{len(two_d)} — name it with panel=<plot> or panel=<panel_id>.")
            panel_id, plot = two_d[0]
        if plot._state.get("kind") != "2d":
            raise ValueError(
                "source='native' is only available for 2-D image panels; "
                f"panel {panel_id!r} is {plot._state.get('kind')!r}.")

    opts = {"source": source, "theme": theme, "scale": scale,
            "includeWidgets": bool(include_widgets)}
    if panel_id is not None:
        opts["panelId"] = panel_id

    def _export(page):
        return page.evaluate(
            """(opts) => {
                 const api = window._aplRenderApi;
                 if (!api || typeof api.exportPNG !== 'function')
                   throw new Error('figure not ready (exportPNG unavailable)');
                 return api.exportPNG(opts).then(r => r.dataUrl);
               }""", opts)

    tiled = (source == "native" and plot is not None
             and bool(plot._state.get("tile_enabled")))
    if tiled:
        # The browser only ever received an overview; push the real pixels into
        # the snapshot so the ordinary native render has something to draw.
        with _temporarily_untiled(plot):
            data_url = run_in_page(_standalone_html(fig), _export,
                                   timeout_ms=timeout_ms)
    else:
        data_url = run_in_page(_standalone_html(fig), _export,
                               timeout_ms=timeout_ms)

    prefix = "data:image/png;base64,"
    if not data_url.startswith(prefix):
        raise RuntimeError(f"unexpected export payload: {data_url[:48]!r}")
    out.write_bytes(base64.b64decode(data_url[len(prefix):]))
    return out

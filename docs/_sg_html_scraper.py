"""
Custom Sphinx Gallery scraper for anyplotlib Widgets.

Sphinx Gallery requires every scraper to write a PNG file to the path provided
by ``image_path_iterator`` — otherwise it raises ``ExtensionError``.

This scraper:
1. Finds a anyplotlib widget in ``example_globals`` (any object from the ``anyplotlib``
   package that has ``_repr_html_``).
2. Renders a **pixel-accurate dark-theme thumbnail PNG** by loading the widget's
   standalone HTML in headless Chromium (Playwright) — the exact same renderer
   the user sees in a notebook.
3. Writes the **full interactive HTML** (iframe + widget JS) alongside the PNG.
4. Returns rST that embeds both: the PNG as a fallback image AND an iframe for
   interactive use, using a ``.. raw:: html`` block.
"""

from __future__ import annotations

import json as _json
import tempfile
from html import escape as _html_escape
from pathlib import Path
from uuid import uuid4

# Maximum iframe width (px) that fits comfortably inside the pydata-sphinx-theme
# content column on a desktop browser.  Figures wider than this are scaled down
# proportionally via CSS transform; a JS resize listener makes the embed fully
# responsive so it also looks correct on tablets and phones.
MAX_DOC_WIDTH = 684


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_viewer(globals_dict: dict):
    """Return the most-recently assigned anyplotlib widget, or None."""
    for val in reversed(list(globals_dict.values())):
        module = getattr(type(val), "__module__", "") or ""
        if module.startswith("anyplotlib") and callable(getattr(val, "_repr_html_", None)):
            return val
    return None


def _make_thumbnail_png(widget) -> bytes:
    """Render *widget* in headless Chromium and return a dark-theme PNG screenshot.

    Mirrors the ``_screenshot_widget`` helper in ``tests/conftest.py`` but
    forces the dark Dracula theme by:

    * Replacing the page background with ``#1e1e2e`` so ``_isDarkBg()``
      inside the widget JS immediately detects a dark parent.
    * Calling ``page.emulate_media(color_scheme='dark')`` so the
      ``prefers-color-scheme`` media query also resolves to dark (the
      fallback path in ``_isDarkBg`` when no explicit background is set).
    """
    from playwright.sync_api import sync_playwright
    from anyplotlib._repr_utils import build_standalone_html

    # Build the fully self-contained HTML page.
    html = build_standalone_html(widget, resizable=False)

    # Inject the render-complete sentinel exactly as conftest.py does so
    # Playwright can wait for the canvas to be fully painted.
    html = html.replace(
        "renderFn({ model, el });",
        "renderFn({ model, el }); window._aplReady = true;",
    )

    # Override the transparent page background with the dark theme colour.
    # This makes _isDarkBg() in figure_esm.js immediately return True and
    # avoids a flash of the light theme before the media-query listener fires.
    html = html.replace("background: transparent;", "background: #1e1e2e;")

    with tempfile.NamedTemporaryFile(
        suffix=".html", mode="w", encoding="utf-8", delete=False
    ) as fh:
        fh.write(html)
        tmp_path = Path(fh.name)

    try:
        with sync_playwright() as pw:
            # --no-sandbox is required on Linux CI runners (GitHub Actions,
            # etc.) where the kernel user-namespace sandbox is not available.
            browser = pw.chromium.launch(
                headless=True, args=["--no-sandbox", "--disable-setuid-sandbox"]
            )
            try:
                page = browser.new_page()
                # Set OS-level dark preference so every media query agrees.
                page.emulate_media(color_scheme="dark")
                page.goto(tmp_path.as_uri())
                page.wait_for_function(
                    "() => window._aplReady === true", timeout=15_000
                )
                # Two rAFs: first lets the compositor flush canvas pixels;
                # second ensures element bounds are stable (mirrors conftest.py).
                page.evaluate(
                    "() => new Promise(r =>"
                    " requestAnimationFrame(() => requestAnimationFrame(r)))"
                )
                png_bytes = page.locator("#widget-root").screenshot()
            finally:
                page.close()
                browser.close()
    finally:
        tmp_path.unlink(missing_ok=True)

    return png_bytes


def _iframe_html(src: str, w: int, h: int, fig_id: str | None = None) -> str:
    """Return a single-line HTML snippet that embeds *src* responsively.

    The iframe is always rendered at its native resolution (``w × h`` px) so
    the interactive widget is pixel-perfect on wide screens.  On narrower
    viewports (docs sidebar layout, tablet, phone) a CSS ``transform:scale()``
    shrinks the whole iframe proportionally — CSS transforms correctly
    translate pointer events, so dragging and scrolling continue to work.

    A tiny inline script re-runs the scale calculation on every ``resize``
    event so the embed reflows without a page reload.
    """
    uid = fig_id or f"f{uuid4().hex[:8]}"

    # Static initial scale so the page renders correctly before JS runs
    init_scale = min(1.0, MAX_DOC_WIDTH / w)
    init_w = round(w * init_scale)
    init_h = round(h * init_scale)
    scale_css = f"{init_scale:.6f}".rstrip("0").rstrip(".")

    # Inline JS: re-scale whenever the window is resized.
    # Uses the wrapper's parent width as the available space so the figure
    # always fills (but never overflows) the content column.
    #
    # requestAnimationFrame defers the first call until after the browser has
    # finished its initial layout pass, so offsetWidth is always non-zero.
    # The !avail guard ensures a partially-laid-out parent (offsetWidth==0)
    # never collapses the wrapper — the CSS-baked initial scale stays intact
    # until a valid measurement is available.
    js = (
        f"(function(){{"
        f"var wrap=document.getElementById('{uid}'),"
        f"ifr=wrap.querySelector('iframe'),"
        f"nw={w},nh={h};"
        f"function r(){{"
        f"var avail=wrap.parentElement?wrap.parentElement.offsetWidth:0;"
        f"if(!avail)return;"
        f"var s=Math.min(1,avail/nw);"
        f"wrap.style.width=Math.round(nw*s)+'px';"
        f"wrap.style.height=Math.round(nh*s)+'px';"
        f"ifr.style.transform='scale('+s+')';"
        f"}}"
        f"requestAnimationFrame(r);window.addEventListener('resize',r);"
        f"}})()"
    )

    # The wrapper is sized to the *scaled* dimensions and clips overflow.
    # The iframe is absolutely positioned at (0,0) at its full native size;
    # CSS transform scales it to fit exactly inside the wrapper.
    return (
        f'<div style="display:block;text-align:center;line-height:0;margin:12px 0;">'
        f'<div id="{uid}" style="display:inline-block;overflow:hidden;'
        f'position:relative;width:{init_w}px;height:{init_h}px;">'
        f'<iframe src="{src}" data-apl-fig="{uid}" frameborder="0" scrolling="no" '
        f'style="width:{w}px;height:{h}px;border:none;overflow:hidden;display:block;'
        f'transform-origin:top left;transform:scale({scale_css});'
        f'position:absolute;top:0;left:0;">'
        f'</iframe>'
        f'</div>'
        f'<script>{js}</script>'
        f'</div>'
    )


# ---------------------------------------------------------------------------
# Scraper
# ---------------------------------------------------------------------------

class ViewerScraper:
    """Sphinx Gallery image scraper that embeds anyplotlib Widgets as live iframes."""

    def __init__(self):
        # Maps src_file path → list of fig_ids emitted so far for that example.
        # Used to assign a stable fig_index (creation order) so pyodide_bridge.js
        # can run the example source once and tag figures in the right order.
        self._example_figs: dict = {}

    def __repr__(self) -> str:
        return "ViewerScraper()"

    def __call__(self, block, block_vars, gallery_conf):
        globals_dict = block_vars.get("example_globals", {})
        widget = _find_viewer(globals_dict)
        if widget is None:
            return ""

        src_file = str(block_vars.get("src_file", ""))

        # ── assign a stable fig_id and fig_index for this widget ──────────
        if src_file not in self._example_figs:
            self._example_figs[src_file] = []
        fig_index = len(self._example_figs[src_file])

        # ── 1. Write the thumbnail PNG (Sphinx Gallery requires this) ──────
        image_path_iterator = block_vars["image_path_iterator"]
        png_path = Path(next(image_path_iterator))
        png_path.parent.mkdir(parents=True, exist_ok=True)
        png_path.write_bytes(_make_thumbnail_png(widget))

        # fig_id is derived from the PNG stem so it is stable across rebuilds
        # and unique within the built docs (Sphinx Gallery guarantees unique stems).
        fig_id = png_path.stem   # e.g. "sphx_glr_plot_image2d_001"
        self._example_figs[src_file].append(fig_id)

        # ── 2. Write the standalone HTML into docs/_static/viewer_widgets/ ─
        try:
            from anyplotlib._repr_utils import build_standalone_html, _widget_px
            docs_dir = Path(gallery_conf["src_dir"])
            widgets_dir = docs_dir / "_static" / "viewer_widgets"
            widgets_dir.mkdir(parents=True, exist_ok=True)

            html_name = png_path.stem + ".html"   # sphx_glr_plot_..._001.html
            html_path = widgets_dir / html_name

            inner_html = build_standalone_html(widget, resizable=False, fig_id=fig_id)
            html_path.write_text(inner_html, encoding="utf-8")
            w, h = _widget_px(widget)
            interactive = True
        except Exception:
            interactive = False

        # ── 3. Return rST ──────────────────────────────────────────────────
        if interactive:
            try:
                src_dir = Path(gallery_conf["src_dir"])
                page_dir = png_path.parent.parent  # strip /images
                rel_parts = page_dir.relative_to(src_dir).parts
                depth = len(rel_parts)
            except Exception:
                depth = 1
            prefix = "../" * depth
            src = f"{prefix}_static/viewer_widgets/{html_name}"

            iframe_block = _iframe_html(src, w, h, fig_id=fig_id)

            # Embed the full example Python source alongside the iframe so
            # pyodide_bridge.js can run it in Pyodide and wire live callbacks.
            python_src = ""
            try:
                python_src = Path(src_file).read_text(encoding="utf-8")
            except Exception:
                pass

            if python_src:
                # The Python source is JSON-encoded and HTML-escaped into a
                # data-src attribute so the <script> tag stays on ONE line.
                # Multi-line textContent would break the RST `.. raw:: html`
                # block — docutils treats any non-indented line as the end of
                # the directive.  pyodide_bridge.js reads dataset.src instead.
                data_src = _html_escape(_json.dumps(python_src), quote=True)
                python_block = (
                    f'<script type="text/x-python"'
                    f' data-fig-id="{fig_id}"'
                    f' data-fig-index="{fig_index}"'
                    f' data-src-file="{Path(src_file).stem}"'
                    f' data-src="{data_src}"></script>'
                )
            else:
                python_block = ""

            rst = "\n\n.. raw:: html\n\n    " + iframe_block + "\n\n"
            if python_block:
                rst += "\n\n.. raw:: html\n\n    " + python_block + "\n\n"
            return rst
        else:
            rel_png = png_path.name
            return (
                f"\n\n.. image:: {rel_png}\n"
                f"   :width: 100%\n\n"
            )

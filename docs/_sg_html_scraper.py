"""
Custom Sphinx Gallery scraper for anyplotlib Widgets.

Sphinx Gallery requires every scraper to write a PNG file to the path provided
by ``image_path_iterator`` — otherwise it raises ``ExtensionError``.

This scraper:
1. Finds a anyplotlib widget in ``example_globals`` (any object from the ``anyplotlib``
   package that has ``_repr_html_``).
2. Renders a **pixel-accurate dark-theme thumbnail PNG** by loading the widget's
   standalone HTML in headless Chromium (Playwright) — the exact same renderer
   the user sees in a notebook.  Falls back to a plain matplotlib placeholder
   if Playwright is not installed.
3. Writes the **full interactive HTML** (iframe + widget JS) alongside the PNG.
4. Returns rST that embeds both: the PNG as a fallback image AND an iframe for
   interactive use, using a ``.. raw:: html`` block.
"""

from __future__ import annotations

import io
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
    """Render a thumbnail PNG of *widget* using headless Chromium (Playwright).

    The widget is rendered at its native size with the dark theme forced on.
    Falls back to a minimal matplotlib placeholder if Playwright is not
    available in the current environment.
    """
    try:
        return _playwright_thumbnail(widget)
    except Exception:
        return _matplotlib_fallback_png(widget)


def _playwright_thumbnail(widget) -> bytes:
    """Render *widget* in headless Chromium and return dark-theme PNG bytes.

    Mirrors the ``_screenshot_widget`` helper in ``tests/conftest.py`` but
    forces the dark Dracula theme by:

    * Replacing the page background with ``#1e1e2e`` so ``_isDarkBg()``
      inside the widget JS immediately detects a dark parent.
    * Calling ``page.emulate_media(color_scheme='dark')`` so the
      ``prefers-color-scheme`` media query also resolves to dark (the
      fallback path in ``_isDarkBg`` when no explicit background is set).
    """
    import tempfile
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
            browser = pw.chromium.launch(headless=True)
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


def _matplotlib_fallback_png(widget) -> bytes:
    """Minimal dark-background placeholder used when Playwright is unavailable."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    kind = type(widget).__name__
    fig, ax = plt.subplots(figsize=(4, 3), dpi=72)
    ax.set_facecolor("#1e1e2e")
    fig.patch.set_facecolor("#1e1e2e")
    ax.text(0.5, 0.5, kind, ha="center", va="center",
            color="#cdd6f4", transform=ax.transAxes, fontsize=12)
    ax.axis("off")
    plt.tight_layout(pad=0.3)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=72, facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return buf.read()


def _iframe_html(src: str, w: int, h: int) -> str:
    """Return a single-line HTML snippet that embeds *src* responsively.

    The iframe is always rendered at its native resolution (``w × h`` px) so
    the interactive widget is pixel-perfect on wide screens.  On narrower
    viewports (docs sidebar layout, tablet, phone) a CSS ``transform:scale()``
    shrinks the whole iframe proportionally — CSS transforms correctly
    translate pointer events, so dragging and scrolling continue to work.

    A tiny inline script re-runs the scale calculation on every ``resize``
    event so the embed reflows without a page reload.
    """
    uid = f"f{uuid4().hex[:8]}"

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
        f'<iframe src="{src}" frameborder="0" scrolling="no" '
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

    def __repr__(self) -> str:
        return "ViewerScraper()"

    def __call__(self, block, block_vars, gallery_conf):
        globals_dict = block_vars.get("example_globals", {})
        widget = _find_viewer(globals_dict)
        if widget is None:
            return ""

        # ── 1. Write the thumbnail PNG (Sphinx Gallery requires this) ──────
        image_path_iterator = block_vars["image_path_iterator"]
        png_path = Path(next(image_path_iterator))
        png_path.parent.mkdir(parents=True, exist_ok=True)
        png_path.write_bytes(_make_thumbnail_png(widget))

        # ── 2. Write the standalone HTML into docs/_static/viewer_widgets/ ─
        #
        # WHY NOT srcdoc=:
        #   The srcdoc= attribute value is thousands of lines. Docutils parses
        #   the content of a ``.. raw:: html`` block as indented text, so a
        #   multi-line attribute value confuses the RST parser and the block is
        #   silently dropped from the output.
        #
        # WHY NOT src= into auto_examples/images/:
        #   Sphinx only copies *.png files from that directory to _build/html/.
        #   Any .html file referenced via src= would be a 404 in the built docs.
        #
        # SOLUTION:
        #   Write to docs/_static/viewer_widgets/ which is in html_static_path
        #   and is copied verbatim by Sphinx.  The src= path is a single line,
        #   which is safe for docutils.
        try:
            from anyplotlib._repr_utils import build_standalone_html, _widget_px
            docs_dir = Path(gallery_conf["src_dir"])
            widgets_dir = docs_dir / "_static" / "viewer_widgets"
            widgets_dir.mkdir(parents=True, exist_ok=True)

            html_name = png_path.stem + ".html"   # sphx_glr_plot_..._001.html
            html_path = widgets_dir / html_name

            inner_html = build_standalone_html(widget, resizable=False)
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
            return (
                "\n\n.. raw:: html\n\n"
                "    " + _iframe_html(src, w, h) + "\n\n"
            )
        else:
            rel_png = png_path.name
            return (
                f"\n\n.. image:: {rel_png}\n"
                f"   :width: 100%\n\n"
            )

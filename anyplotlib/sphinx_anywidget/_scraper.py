"""
sphinx_anywidget/_scraper.py
=============================

Generic Sphinx Gallery image scraper for any ``anywidget.AnyWidget`` subclass.

Drop-in replacement for the anyplotlib-specific ``_sg_html_scraper.ViewerScraper``.
Works with **any** library built on anywidget — just add the scraper to your
``sphinx_gallery_conf["image_scrapers"]``.

Interactive tagging
-------------------
If a code block's last expression line contains a ``# Interactive`` comment
(case-insensitive), the scraper:

* embeds the full example Python source in a ``<script type="text/x-python">``
  tag so the Pyodide bridge can re-run it live;
* adds an **⚡ activation badge** to the figure iframe wrapper.

Example::

    fig, ax = vw.subplots(1, 1, figsize=(640, 400))
    ax.imshow(data)
    fig  # Interactive

Without the comment the figure is rendered as a plain static iframe with
no Pyodide wiring.

Usage in ``conf.py``::

    from anyplotlib.sphinx_anywidget import AnywidgetScraper

    sphinx_gallery_conf = {
        "image_scrapers": (AnywidgetScraper(), "matplotlib"),
        ...
    }
"""

from __future__ import annotations

import json as _json
import re
import tempfile
from html import escape as _html_escape
from pathlib import Path
from uuid import uuid4

# Maximum iframe width (px) that fits inside the pydata-sphinx-theme column.
MAX_DOC_WIDTH = 684

# Sentinel that marks a code block as interactive.
_INTERACTIVE_RE = re.compile(r"#\s*interactive\s*$", re.IGNORECASE | re.MULTILINE)

# Pattern that extracts _PYODIDE_PACKAGES = [...] declarations from source.
_PYODIDE_PACKAGES_RE = re.compile(
    r"^_PYODIDE_PACKAGES\s*=\s*(\[[^\]]*\])", re.MULTILINE
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_widget(globals_dict: dict):
    """Return the most-recently assigned anywidget in *globals_dict*, or None.

    Accepts any object that:
    * has a ``_repr_html_`` callable, and
    * belongs to a class that either inherits from ``anywidget.AnyWidget``
      (identified by the ``_esm`` attribute) or whose module starts with
      ``anywidget``.
    """
    for val in reversed(list(globals_dict.values())):
        if not callable(getattr(val, "_repr_html_", None)):
            continue
        # Check for anywidget fingerprint: _esm attribute
        if hasattr(val, "_esm") and hasattr(val, "traits"):
            return val
        # Fallback: module check
        module = getattr(type(val), "__module__", "") or ""
        if "widget" in module.lower():
            return val
    return None


def _make_thumbnail_png(widget) -> bytes:
    """Render *widget* in headless Chromium and return a dark-theme PNG screenshot."""
    from playwright.sync_api import sync_playwright
    from anyplotlib.sphinx_anywidget._repr_utils import build_standalone_html

    html = build_standalone_html(widget, resizable=False)
    html = html.replace(
        "renderFn({ model, el });",
        "renderFn({ model, el }); window._aplReady = true;",
    )
    html = html.replace("background: transparent;", "background: #1e1e2e;")

    with tempfile.NamedTemporaryFile(
        suffix=".html", mode="w", encoding="utf-8", delete=False
    ) as fh:
        fh.write(html)
        tmp_path = Path(fh.name)

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=True, args=["--no-sandbox", "--disable-setuid-sandbox"]
            )
            try:
                page = browser.new_page()
                page.emulate_media(color_scheme="dark")
                page.goto(tmp_path.as_uri())
                page.wait_for_function(
                    "() => window._aplReady === true", timeout=15_000
                )
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


def _iframe_html(
    src: str,
    w: int,
    h: int,
    fig_id: str | None = None,
    interactive: bool = False,
    max_width: int | None = None,
) -> str:
    """Return a single-line HTML snippet embedding *src* responsively.

    Parameters
    ----------
    src : str
        Relative URL to the standalone widget HTML file.
    w, h : int
        Native pixel dimensions of the widget.
    fig_id : str or None
        Stable identifier; used as the ``data-awi-fig`` attribute.
    interactive : bool
        When True, renders the ⚡ activation badge.
    max_width : int or None
        Override the default ``MAX_DOC_WIDTH`` cap (pixels).
    """
    uid = fig_id or f"f{uuid4().hex[:8]}"
    cap = max_width if max_width is not None else MAX_DOC_WIDTH

    init_scale = min(1.0, cap / w)
    init_w = round(w * init_scale)
    init_h = round(h * init_scale)
    scale_css = f"{init_scale:.6f}".rstrip("0").rstrip(".")

    # JS: re-scale on resize
    resize_js = (
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

    # Badge HTML — only the ⚡ button when interactive; nothing otherwise.
    badge_parts = []
    if interactive:
        badge_parts.append(
            f'<button class="awi-badge-icon awi-activate-btn" '
            f'data-awi-fig="{uid}" '
            f'title="Make interactive (boots Pyodide — may take ~10 s)">&#x26A1;</button>'
        )
    if not badge_parts:
        badge_html = ""
    else:
        badge_html = (
            f'<div class="awi-badge" data-awi-badge="{uid}">'
            + "".join(badge_parts)
            + "</div>"
        )

    return (
        f'<div style="display:block;text-align:center;line-height:0;margin:12px 0;">'
        f'<div id="{uid}" class="awi-fig-wrap" data-awi-fig="{uid}" '
        f'style="display:inline-block;overflow:hidden;'
        f'position:relative;width:{init_w}px;height:{init_h}px;">'
        f'<iframe src="{src}" data-awi-fig="{uid}" frameborder="0" scrolling="no" '
        f'style="width:{w}px;height:{h}px;border:none;overflow:hidden;display:block;'
        f'transform-origin:top left;transform:scale({scale_css});'
        f'position:absolute;top:0;left:0;">'
        f'</iframe>'
        f'{badge_html}'
        f'</div>'
        f'<script>{resize_js}</script>'
        f'</div>'
    )


# ---------------------------------------------------------------------------
# Scraper
# ---------------------------------------------------------------------------

class AnywidgetScraper:
    """Sphinx Gallery image scraper for any ``anywidget.AnyWidget`` subclass.
    """

    def __init__(self):
        # Maps src_file → list of fig_ids emitted so far (creation order).
        self._example_figs: dict = {}

    def __repr__(self) -> str:
        return "AnywidgetScraper()"

    def __call__(self, block, block_vars, gallery_conf):
        globals_dict = block_vars.get("example_globals", {})
        widget = _find_widget(globals_dict)
        if widget is None:
            return ""

        src_file = str(block_vars.get("src_file", ""))

        # ── detect # Interactive tag ──────────────────────────────────────
        block_source = block[1] if isinstance(block, (list, tuple)) else ""
        is_interactive = bool(_INTERACTIVE_RE.search(block_source))

        # ── assign a stable fig_id and fig_index ─────────────────────────
        if src_file not in self._example_figs:
            self._example_figs[src_file] = []
        fig_index = len(self._example_figs[src_file])

        # ── 1. Write the thumbnail PNG ────────────────────────────────────
        image_path_iterator = block_vars["image_path_iterator"]
        png_path = Path(next(image_path_iterator))
        png_path.parent.mkdir(parents=True, exist_ok=True)
        png_path.write_bytes(_make_thumbnail_png(widget))

        fig_id = png_path.stem   # stable, unique stem from Sphinx Gallery
        self._example_figs[src_file].append(fig_id)

        # ── 2. Write the standalone HTML ──────────────────────────────────
        try:
            from anyplotlib.sphinx_anywidget._repr_utils import (
                build_standalone_html, _widget_px,
            )
            docs_dir = Path(gallery_conf["src_dir"])
            widgets_dir = docs_dir / "_static" / "viewer_widgets"
            widgets_dir.mkdir(parents=True, exist_ok=True)

            html_name = png_path.stem + ".html"
            html_path = widgets_dir / html_name

            inner_html = build_standalone_html(widget, resizable=False, fig_id=fig_id)
            html_path.write_text(inner_html, encoding="utf-8")
            w, h = _widget_px(widget)
            have_html = True
        except Exception as exc:
            print(f"[sphinx_anywidget] WARNING: could not write iframe HTML: {exc}")
            have_html = False

        # ── 3. Return rST ─────────────────────────────────────────────────
        if have_html:
            try:
                src_dir = Path(gallery_conf["src_dir"])
                page_dir = png_path.parent.parent  # strip /images
                rel_parts = page_dir.relative_to(src_dir).parts
                depth = len(rel_parts)
            except Exception:
                depth = 1
            prefix = "../" * depth
            src = f"{prefix}_static/viewer_widgets/{html_name}"

            iframe_block = _iframe_html(
                src, w, h,
                fig_id=fig_id,
                interactive=is_interactive,
            )

            rst = "\n\n.. raw:: html\n\n    " + iframe_block + "\n\n"

            if is_interactive:
                # Embed the example Python source so the Pyodide bridge can
                # re-execute it and wire live callbacks.
                python_src = ""
                try:
                    python_src = Path(src_file).read_text(encoding="utf-8")
                except Exception:
                    pass

                if python_src:
                    data_src = _html_escape(_json.dumps(python_src), quote=True)

                    # Detect _PYODIDE_PACKAGES = [...] in the source.
                    _pkg_attr = ""
                    m = _PYODIDE_PACKAGES_RE.search(python_src)
                    if m:
                        try:
                            import ast as _ast
                            pkgs = _ast.literal_eval(m.group(1))
                            if pkgs:
                                _pkg_attr = (
                                    f' data-pyodide-packages='
                                    f'"{_html_escape(_json.dumps(pkgs), quote=True)}"'
                                )
                        except Exception:
                            pass

                    python_block = (
                        f'<script type="text/x-python"'
                        f' data-fig-id="{fig_id}"'
                        f' data-fig-index="{fig_index}"'
                        f' data-src-file="{Path(src_file).stem}"'
                        f'{_pkg_attr}'
                        f' data-src="{data_src}"></script>'
                    )
                    rst += "\n\n.. raw:: html\n\n    " + python_block + "\n\n"

            return rst
        else:
            return (
                f"\n\n.. image:: {png_path.name}\n"
                f"   :width: 100%\n\n"
            )


# Back-compat alias used by the existing anyplotlib docs.
ViewerScraper = AnywidgetScraper


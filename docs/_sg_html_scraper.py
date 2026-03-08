"""
Custom Sphinx Gallery scraper for viewer widgets.

Sphinx Gallery requires every scraper to write a PNG file to the path provided
by ``image_path_iterator`` — otherwise it raises ``ExtensionError``.

This scraper:
1. Finds a viewer widget in ``example_globals`` (any object from the ``viewer``
   package that has ``_repr_html_``).
2. Renders a **static thumbnail PNG** via matplotlib for the gallery index.
3. Writes the **full interactive HTML** (iframe + widget JS) alongside the PNG.
4. Returns rST that embeds both: the PNG as a fallback image AND an iframe for
   interactive use, using a ``.. raw:: html`` block.
"""

from __future__ import annotations

import io
from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_viewer(globals_dict: dict):
    """Return the most-recently assigned viewer widget, or None."""
    for val in reversed(list(globals_dict.values())):
        module = getattr(type(val), "__module__", "") or ""
        if module.startswith("viewer") and callable(getattr(val, "_repr_html_", None)):
            return val
    return None


def _make_thumbnail_png(widget) -> bytes:
    """Render a small static thumbnail PNG for the gallery index card."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    fig, ax = plt.subplots(figsize=(4, 3), dpi=72)
    ax.set_facecolor("#1e1e2e")
    fig.patch.set_facecolor("#1e1e2e")
    ax.tick_params(colors="#cdd6f4")
    for spine in ax.spines.values():
        spine.set_edgecolor("#44475a")

    kind = type(widget).__name__

    try:
        if kind == "Viewer2D":
            import json
            raw = widget._raw_u8
            cmap = widget.colormap_name or "gray"
            ax.imshow(raw, cmap=cmap, aspect="auto", interpolation="nearest")
            ax.set_title("Viewer2D", color="#cdd6f4", fontsize=9)
            ax.set_xticks([]); ax.set_yticks([])

        elif kind == "Viewer1D":
            import json
            data   = np.array(json.loads(widget.data_json))
            x_axis = np.array(json.loads(widget.x_axis_json))
            ax.plot(x_axis, data, color="#4fc3f7", linewidth=1)
            ax.set_title("Viewer1D", color="#cdd6f4", fontsize=9)
            ax.set_facecolor("#181825")

        elif kind == "Figure":
            from viewer.figure_plots import Plot2D, Plot1D
            import json
            plots = list(widget._plots_map.values())
            ax.set_title(f"Figure ({widget._nrows}×{widget._ncols})",
                         color="#cdd6f4", fontsize=9)
            if plots:
                p = plots[0]
                if isinstance(p, Plot2D):
                    ax.imshow(p._raw_u8, cmap=p._state.get("colormap_name", "gray"),
                              aspect="auto", interpolation="nearest")
                elif isinstance(p, Plot1D):
                    d = np.asarray(p._state.get("data", []))
                    x = np.asarray(p._state.get("x_axis", np.arange(len(d))))
                    ax.plot(x, d, color=p._state.get("line_color", "#4fc3f7"), linewidth=1)
            ax.set_xticks([]); ax.set_yticks([])
        else:
            ax.text(0.5, 0.5, kind, ha="center", va="center",
                    color="#cdd6f4", transform=ax.transAxes)
            ax.axis("off")

    except Exception:
        ax.text(0.5, 0.5, kind, ha="center", va="center",
                color="#cdd6f4", transform=ax.transAxes)
        ax.axis("off")

    plt.tight_layout(pad=0.3)
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=72, facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return buf.read()


# ---------------------------------------------------------------------------
# Scraper
# ---------------------------------------------------------------------------

class ViewerScraper:
    """Sphinx Gallery image scraper that embeds viewer widgets as live iframes."""

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
            from viewer._repr_utils import build_standalone_html, _widget_px
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
            # Single-line src= — safe for docutils raw:: html.
            # Relative path from auto_examples/ up to _static/viewer_widgets/.
            src = f"../_static/viewer_widgets/{html_name}"
            return (
                "\n\n.. raw:: html\n\n"
                f'    <div style="display:block;text-align:center;line-height:0;margin:12px 0;">'
                f'<iframe src="{src}" frameborder="50" scrolling="no"'
                f' style="width:{w}px;height:{h}px;border:none;overflow:hidden;'
                f'display:inline-block;max-width:100%;"></iframe></div>\n\n'
            )
        else:
            rel_png = png_path.name
            return (
                f"\n\n.. image:: {rel_png}\n"
                f"   :width: 100%\n\n"
            )

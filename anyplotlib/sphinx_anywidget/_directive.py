"""
sphinx_anywidget/_directive.py
================================

RST directive for embedding interactive anywidget figures directly in ``.rst``
pages — no Sphinx Gallery required.

Usage
-----

Static snapshot only::

    .. anywidget-figure:: ../Examples/plot_image2d.py

Interactive (Pyodide-activatable)::

    .. anywidget-figure:: ../Examples/plot_image2d.py
       :interactive:

Options
-------
``:interactive:``
    Flag.  When present the ⚡ activation badge is shown and the example
    source is embedded for live re-execution by the Pyodide bridge.
``:width:`` (int, default 684)
    Maximum display width in pixels.
``:static-icon:`` (str, default "📷")
    Unicode character for the static snapshot badge.  Falls back to the
    ``anywidget_static_icon`` Sphinx config value, then ``"📷"``.
"""

from __future__ import annotations

import json as _json
import runpy
import tempfile
from html import escape as _html_escape
from pathlib import Path

from docutils import nodes
from docutils.parsers.rst import Directive, directives


class AnywidgetFigureDirective(Directive):
    """Directive: ``.. anywidget-figure:: path/to/script.py``."""

    required_arguments = 1   # path to the Python source file
    optional_arguments = 0
    has_content = False
    option_spec = {
        "interactive": directives.flag,
        "width":       directives.nonnegative_int,
        "static-icon": directives.unchanged,
    }

    def run(self):
        env    = self.state.document.settings.env
        config = env.config

        # ── resolve the source file path ─────────────────────────────────
        src_arg  = self.arguments[0]
        conf_dir = Path(env.confdir)
        src_path = (conf_dir / src_arg).resolve()

        if not src_path.exists():
            error = self.reporter.error(
                f"anywidget-figure: source file not found: {src_path}",
                nodes.literal_block(src_arg, src_arg),
                line=self.lineno,
            )
            return [error]

        # ── options ──────────────────────────────────────────────────────
        is_interactive = "interactive" in self.options
        max_width = self.options.get("width", 684)
        static_icon = self.options.get(
            "static-icon",
            getattr(config, "anywidget_static_icon", "\U0001f4f7"),
        )

        # ── execute the script to get the widget ─────────────────────────
        try:
            g = runpy.run_path(str(src_path), run_name="__main__")
        except Exception as exc:
            error = self.reporter.error(
                f"anywidget-figure: failed to execute {src_path.name}: {exc}",
                nodes.literal_block(str(exc), str(exc)),
                line=self.lineno,
            )
            return [error]

        widget = _find_widget(g)
        if widget is None:
            error = self.reporter.error(
                f"anywidget-figure: no anywidget found in {src_path.name}",
                line=self.lineno,
            )
            return [error]

        # ── write the standalone HTML file ───────────────────────────────
        from anyplotlib.sphinx_anywidget._repr_utils import (
            build_standalone_html, _widget_px,
        )
        from anyplotlib.sphinx_anywidget._scraper import _iframe_html

        # Use a stable ID based on the source file name
        stem   = src_path.stem
        fig_id = f"rst_{stem}"

        docs_static = Path(env.app.outdir).parent / "_static" / "viewer_widgets"
        docs_static.mkdir(parents=True, exist_ok=True)
        html_name = f"{fig_id}.html"
        html_path = docs_static / html_name

        inner_html = build_standalone_html(widget, resizable=False, fig_id=fig_id)
        html_path.write_text(inner_html, encoding="utf-8")

        w, h = _widget_px(widget)

        # Compute relative path from the current RST file's output dir
        # to _static/viewer_widgets/
        try:
            out_dir  = Path(env.app.outdir)
            doc_name = env.docname  # e.g. "getting_started"
            page_out = out_dir / (doc_name + ".html")
            rel_depth = len(Path(doc_name).parts)  # depth from out root
            prefix = "../" * rel_depth
        except Exception:
            prefix = ""

        src_url = f"{prefix}_static/viewer_widgets/{html_name}"
        iframe_block = _iframe_html(
            src_url, w, h,
            fig_id=fig_id,
            interactive=is_interactive,
            static_icon=static_icon,
        )

        raw_html = "\n" + iframe_block + "\n"

        if is_interactive:
            python_src = ""
            try:
                python_src = src_path.read_text(encoding="utf-8")
            except Exception:
                pass

            if python_src:
                data_src = _html_escape(_json.dumps(python_src), quote=True)
                script_tag = (
                    f'<script type="text/x-python"'
                    f' data-fig-id="{fig_id}"'
                    f' data-fig-index="0"'
                    f' data-src-file="{stem}"'
                    f' data-src="{data_src}"></script>'
                )
                raw_html += "\n" + script_tag + "\n"

        return [nodes.raw("", raw_html, format="html")]


def _find_widget(globals_dict: dict):
    """Locate the most-recently created anywidget in *globals_dict*."""
    for val in reversed(list(globals_dict.values())):
        if not callable(getattr(val, "_repr_html_", None)):
            continue
        if hasattr(val, "_esm") and hasattr(val, "traits"):
            return val
    return None


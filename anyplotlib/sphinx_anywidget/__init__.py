"""
sphinx_anywidget
================

A generic Sphinx extension that makes any ``anywidget.AnyWidget``-based
figure interactive in documentation pages — powered by Pyodide, with no
server or Jupyter kernel required.

Quick start (any project)
-------------------------

In your ``conf.py``::

    extensions = [
        "anyplotlib.sphinx_anywidget",
    ]

    # Package whose wheel is built and served to Pyodide at runtime.
    anywidget_pyodide_package = "mypackage"


The extension:
* builds a pure-Python wheel at docs-build time;
* injects ``anywidget_bridge.js`` (per-figure ⚡ badges + Pyodide boot);
* provides ``AnywidgetScraper`` for Sphinx Gallery (``# Interactive`` tag);
* registers ``.. anywidget-figure::`` RST directive.

Monkey-patch approach
---------------------
``anywidget_bridge.js`` patches ``AnyWidget.__init__`` in Pyodide to add a
``traitlets.observe(names=All)`` observer.  When any ``sync=True`` trait
changes and the widget has ``_anywidget_fig_id`` set, the observer calls
``window._anywidgetPush(fig_id, name, value_str)`` which postMessages the
new state into the matching iframe — no library-side Pyodide code needed.
"""

from __future__ import annotations

from pathlib import Path

from anyplotlib.sphinx_anywidget._scraper import AnywidgetScraper, ViewerScraper  # noqa: F401

_HERE = Path(__file__).parent
_STATIC_SRC = _HERE / "static"


def setup(app):
    """Register sphinx_anywidget with Sphinx."""
    app.add_config_value("anywidget_pyodide_package", default=None, rebuild="html")

    from anyplotlib.sphinx_anywidget._directive import AnywidgetFigureDirective
    app.add_directive("anywidget-figure", AnywidgetFigureDirective)

    app.connect("builder-inited", _copy_static_assets)
    app.connect("builder-inited", _build_pyodide_wheel)

    # anywidget_config.js is written dynamically by _build_pyodide_wheel;
    # it must load BEFORE anywidget_bridge.js so _inferPackageName sees the name.
    app.add_js_file("anywidget_config.js", loading_method="defer", priority=490)
    app.add_js_file("anywidget_bridge.js", loading_method="defer", priority=500)
    app.add_css_file("anywidget_overlay.css")

    return {
        "version": "0.1.0",
        "parallel_read_safe": True,
        "parallel_write_safe": True,
    }


def _copy_static_assets(app):
    """Add the extension's static/ dir to html_static_path."""
    src_str = str(_STATIC_SRC)
    if hasattr(app.config, "html_static_path"):
        if src_str not in app.config.html_static_path:
            app.config.html_static_path.append(src_str)


def _build_pyodide_wheel(app):
    """Build the configured package wheel for the Pyodide bridge."""
    pkg = getattr(app.config, "anywidget_pyodide_package", None)
    if not pkg:
        pkg = _infer_package_name(app)
    if not pkg:
        print(
            "[sphinx_anywidget] WARNING: anywidget_pyodide_package not set; "
            "Pyodide interactive mode disabled."
        )
        return

    conf_dir     = Path(app.confdir)
    static_dir   = conf_dir / "_static"
    static_dir.mkdir(parents=True, exist_ok=True)

    # Write a tiny config script so anywidget_bridge.js can find the package
    # name without fragile heuristics.  Loaded before anywidget_bridge.js.
    import json as _json
    config_js = f"window._anywidgetPackage = {_json.dumps(pkg)};\n"
    (static_dir / "anywidget_config.js").write_text(config_js, encoding="utf-8")

    from anyplotlib.sphinx_anywidget._wheel_builder import build_wheel
    project_root = conf_dir.parent
    build_wheel(static_dir, pkg, project_root)


def _infer_package_name(app) -> str | None:
    """Infer package name from pyproject.toml near conf.py."""
    try:
        import tomllib
    except ImportError:
        try:
            import tomli as tomllib  # type: ignore[no-redef]
        except ImportError:
            return None
    conf_dir = Path(app.confdir)
    for candidate in [conf_dir / "pyproject.toml", conf_dir.parent / "pyproject.toml"]:
        if candidate.exists():
            with open(candidate, "rb") as fh:
                data = tomllib.load(fh)
            name = (
                data.get("project", {}).get("name")
                or data.get("tool", {}).get("poetry", {}).get("name")
            )
            if name:
                return name
    return None


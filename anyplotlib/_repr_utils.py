"""
_repr_utils.py
==============

Produces a self-contained HTML page that renders anywidget Widgets
interactively without a live Jupyter kernel.

Strategy
--------
 and 1. Serialise every synced traitlet value to a plain JSON dict.
2. Embed that dict and the widget's ``_esm`` source directly in the page.
3. Provide a minimal model shim (get/set/on/save_changes) so the ESM's
   render() function works without any Jupyter comm infrastructure.
4. Import the ESM as a Blob URL and call render({ model, el }).

When resizable=False (the default for documentation) the resize handle is
hidden via CSS and the iframe is sized exactly to the widget's own dimensions,
producing a tight, centred embed with no dead space.
"""

from __future__ import annotations

import json
from html import escape
from uuid import uuid4


# ---------------------------------------------------------------------------
# Trait serialisation
# ---------------------------------------------------------------------------

def _widget_state(widget) -> dict:
    """Return a {name: value} dict of every synced traitlet."""
    state: dict = {}
    for name, trait in widget.traits(sync=True).items():
        if name.startswith("_"):
            continue
        raw = getattr(widget, name)
        if isinstance(raw, (bytes, bytearray)):
            import base64
            raw = {"buffer": base64.b64encode(raw).decode("ascii")}
        state[name] = raw
    return state


def _widget_px(widget) -> tuple[int, int]:
    """Return (width_px, height_px) for the widget's full rendered size.

    These are the *outer* pixel dimensions of the widget's root DOM element,
    including any padding the widget JS adds around the canvas grid.
    """
    try:
        kind = type(widget).__name__
        if kind == "Figure":
            # figure_esm.js: gridDiv has padding:8px on all sides → +16 each axis
            return int(widget.fig_width) + 16, int(widget.fig_height) + 16
        # Viewer1D / Viewer2D — the outerContainer has padding:10px
        w = int(getattr(widget, "viewer_width",  480))
        h = int(getattr(widget, "viewer_height", 256))
        PAD = 20  # 10px padding each side
        if kind == "Viewer2D":
            # Add axis canvas gutters (AXIS_SIZE = 40 in viewer2d JS)
            AXIS = 40
            w += AXIS + PAD
            h += AXIS + PAD
            if getattr(widget, "histogram_visible", False):
                h_gap = int(getattr(widget, "gap", 10))
                h_hw  = int(getattr(widget, "histogram_width", 120))
                w    += h_hw + h_gap
        else:
            # Viewer1D: PAD_L=58, PAD_R=12, PAD_T=12, PAD_B=36 + outer 10px pad each side
            w += 58 + 12 + 20   # PAD_L + PAD_R + outer
            h += 12 + 36 + 20   # PAD_T + PAD_B + outer
        return w, h
    except Exception:
        return 560, 340


# ---------------------------------------------------------------------------
# HTML builder
# ---------------------------------------------------------------------------

# Extra CSS injected when resizable=False:
# - hides every resize-handle div
# - locks the outermost container to exact pixel dims so it can't grow
_NO_RESIZE_CSS = """\
  /* ── resizable=False overrides ─────────────────────────────── */
  /* Hide all resize handles rendered by the widget JS */
  div[style*="nwse-resize"],
  div[title="Drag to resize"],
  div[title="Drag to resize figure"] {{
    display: none !important;
  }}
  /* Remove any bottom-right padding that was reserved for the handle */
  #widget-root > div {{
    padding-bottom: 0 !important;
    padding-right:  0 !important;
  }}
"""

_PAGE_TEMPLATE = """\
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8"/>
<style>
  html, body {{
    margin: 0;
    padding: 0;
    background: transparent;
    overflow: hidden;
    /* Size the document exactly to the widget so scrollHeight == widget height */
    width:  {width}px;
    height: {height}px;
  }}
  #widget-root {{
    display: inline-block;
    line-height: 0;
  }}
{extra_css}\
</style>
</head>
<body>
<div id="widget-root"></div>
<script type="module">
const STATE = {state_json};

function makeModel(state) {{
  const _data   = Object.assign({{}}, state);
  const _cbs    = {{}};
  const _anyCbs = [];
  return {{
    get(key)          {{ return _data[key]; }},
    set(key, val)     {{ _data[key] = val; }},
    save_changes()    {{
      for (const [ev, cbs] of Object.entries(_cbs))
        for (const cb of cbs) try {{ cb({{ new: _data[ev.slice(7)] }}); }} catch(_) {{}}
      for (const cb of _anyCbs) try {{ cb(); }} catch(_) {{}}
    }},
    on(event, cb)  {{
      if (event === "change") {{ _anyCbs.push(cb); return; }}
      (_cbs[event] = _cbs[event] || []).push(cb);
    }},
    off(event, cb) {{
      if (!event) {{ for (const k in _cbs) _cbs[k]=[]; _anyCbs.length=0; return; }}
      if (_cbs[event]) _cbs[event] = _cbs[event].filter(c => c !== cb);
    }},
    get model() {{ return this; }},
  }};
}}

const esmSource = {esm_json};
const blob    = new Blob([esmSource], {{ type: "text/javascript" }});
const blobUrl = URL.createObjectURL(blob);
const el      = document.getElementById("widget-root");
const model   = makeModel(STATE);

import(blobUrl).then(mod => {{
  const renderFn = mod.default?.render ?? mod.render;
  if (typeof renderFn === "function") {{
    renderFn({{ model, el }});
  }} else {{
    el.textContent = "ESM has no render() export";
  }}
}}).catch(err => {{
  el.textContent = "Widget load error: " + err;
  console.error(err);
}});
</script>
</body>
</html>
"""


def build_standalone_html(widget, *, resizable: bool = True) -> str:
    """Return a self-contained HTML page that renders *widget* interactively.

    Parameters
    ----------
    widget :
        Any ``anywidget.AnyWidget`` subclass with ``_esm`` defined.
    resizable : bool
        When ``True`` (default) the widget's built-in resize handle is
        preserved.  When ``False`` the handle is hidden via CSS and the page
        is sized exactly to the widget's natural dimensions.
    """
    state = _widget_state(widget)

    esm = getattr(widget, "_esm", "") or ""
    if hasattr(esm, "read_text"):
        esm = esm.read_text(encoding="utf-8")
    esm = str(esm)

    w, h = _widget_px(widget)
    extra_css = _NO_RESIZE_CSS.format() if not resizable else ""

    return _PAGE_TEMPLATE.format(
        width=w,
        height=h,
        extra_css=extra_css,
        state_json=json.dumps(state, default=str),
        esm_json=json.dumps(esm),
    )


def repr_html_iframe(widget, *, resizable: bool = False,
                     max_height: int = 800) -> str:
    """Return a centred ``<iframe srcdoc=...>`` embedding *widget*.

    Parameters
    ----------
    widget :
        Any ``anywidget.AnyWidget`` subclass.
    resizable : bool
        Passed to :func:`build_standalone_html`.  Default ``False`` for
        documentation embeds — hides the resize handle and sizes the iframe
        exactly to the widget.
    max_height : int
        Upper bound on iframe height in pixels (only applied when
        ``resizable=True`` and auto-sizing is used).
    """
    inner_html = build_standalone_html(widget, resizable=resizable)
    escaped    = escape(inner_html, quote=True)
    uid        = str(uuid4()).replace("-", "")

    w, h = _widget_px(widget)

    if not resizable:
        # Fixed size — iframe is exactly the widget's natural dimensions.
        # Centred via a block wrapper with auto margins.
        return (
            f'<div style="display:block;text-align:center;line-height:0;">'
            f'<iframe id="vw-{uid}" srcdoc="{escaped}" frameborder="0" '
            f'scrolling="no" '
            f'style="width:{w}px;height:{h}px;border:none;overflow:hidden;'
            f'display:inline-block;max-width:100%;">'
            f'</iframe>'
            f'</div>'
        )
    else:
        # Resizable — fill container width, auto-resize height after render.
        return (
            f'<iframe id="vw-{uid}" srcdoc="{escaped}" frameborder="0" '
            f'style="width:100%;height:{h}px;border:none;overflow:hidden;" '
            f'onload="setTimeout(function(){{'
            f'var f=document.getElementById(\'vw-{uid}\');'
            f'if(f&&f.contentWindow&&f.contentWindow.document.body){{'
            f'f.style.height=Math.min('
            f'f.contentWindow.document.body.scrollHeight+20,{max_height})+\'px\''
            f'}}}},'
            f'300)"></iframe>'
        )


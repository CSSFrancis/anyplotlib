"""
sphinx_anywidget/_repr_utils.py
================================

Self-contained HTML builder for any ``anywidget.AnyWidget`` subclass.
No runtime dependency on anyplotlib or any specific widget library.

Strategy
--------
1. Serialise every ``sync=True`` traitlet to a plain JSON dict.
2. Embed that dict and the widget's ``_esm`` source directly in the page.
3. Provide a minimal model shim (get/set/on/save_changes) so the ESM's
   render() function works without any Jupyter comm infrastructure.
4. Import the ESM as a Blob URL and call ``render({ model, el })``.
"""

from __future__ import annotations

import json
from html import escape
from uuid import uuid4

# Maximum display width (px) for the non-resizable notebook embed.
MAX_NOTEBOOK_WIDTH = 860


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
    """Return ``(width_px, height_px)`` for any anywidget subclass.

    Tries common trait names in priority order before falling back to a
    sensible default.  Widget authors can override by adding
    ``_display_width`` and ``_display_height`` *non-synced* attributes.
    """
    # Explicit override
    if hasattr(widget, "_display_width") and hasattr(widget, "_display_height"):
        return int(widget._display_width), int(widget._display_height)

    kind = type(widget).__name__

    # anyplotlib Figure — gridDiv adds 16 px padding on each side
    if kind == "Figure":
        try:
            return int(widget.fig_width) + 16, int(widget.fig_height) + 16
        except Exception:
            pass

    # Common viewer patterns: viewer_width / viewer_height traits
    if hasattr(widget, "viewer_width") and hasattr(widget, "viewer_height"):
        return int(widget.viewer_width) + 20, int(widget.viewer_height) + 20

    # width / height traits
    if hasattr(widget, "width") and hasattr(widget, "height"):
        try:
            return int(widget.width), int(widget.height)
        except Exception:
            pass

    return 560, 340


# ---------------------------------------------------------------------------
# HTML builder
# ---------------------------------------------------------------------------

_NO_RESIZE_CSS = """\
  /* ── resizable=False overrides ─────────────────────────────── */
  div[style*="nwse-resize"],
  div[title="Drag to resize"],
  div[title="Drag to resize figure"] {{
    display: none !important;
  }}
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
// Identifies this iframe to the parent-page anywidget bridge.
// null → no Pyodide wiring (plain notebook / static docs embed).
const FIG_ID = {fig_id_json};

// Loop-prevention flag: set while applying a parent-originated update so
// save_changes() doesn't echo the change back as an awi_event.
let _fromParent = false;
// Dirty flag: true only when model.set('event_json', ...) was called in the
// current transaction.
let _eventJsonDirty = false;

function makeModel(state) {{
  const _data   = Object.assign({{}}, state);
  const _cbs    = {{}};
  const _anyCbs = [];
  return {{
    get(key)      {{ return _data[key]; }},
    set(key, val) {{
      _data[key] = val;
      if (key === 'event_json') _eventJsonDirty = true;
    }},
    save_changes() {{
      for (const [ev, cbs] of Object.entries(_cbs))
        for (const cb of cbs) try {{ cb({{ new: _data[ev.slice(7)] }}); }} catch(_) {{}}
      for (const cb of _anyCbs) try {{ cb(); }} catch(_) {{}}
      // Forward interaction events to the parent-page Pyodide instance.
      if (!_fromParent && FIG_ID && window.parent !== window && _eventJsonDirty) {{
        _eventJsonDirty = false;
        try {{
          const ev = JSON.parse(_data.event_json || '{{}}');
          if (ev && ev.source !== 'python') {{
            window.parent.postMessage(
              {{ type: 'awi_event', figId: FIG_ID, data: _data.event_json }}, '*');
          }}
        }} catch(_) {{}}
      }} else {{
        _eventJsonDirty = false;
      }}
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

// ── Inbound state updates from parent-page Pyodide ───────────────────────────
window.addEventListener('message', (e) => {{
  if (!e.data || e.data.type !== 'awi_state') return;
  _fromParent = true;
  model.set(e.data.key, e.data.value);
  model.save_changes();
  _fromParent = false;
}});
</script>
</body>
</html>
"""


def build_standalone_html(widget, *, resizable: bool = True,
                           fig_id: str | None = None) -> str:
    """Return a self-contained HTML page that renders *widget* interactively.

    Parameters
    ----------
    widget :
        Any ``anywidget.AnyWidget`` subclass with ``_esm`` defined.
    resizable : bool
        When ``True`` (default) the widget's built-in resize handle is
        preserved.  When ``False`` the handle is hidden and the page is
        sized exactly to the widget's natural dimensions.
    fig_id : str or None
        When provided, embedded as ``FIG_ID`` so the parent-page bridge
        can route ``postMessage`` state updates to this iframe.
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
        fig_id_json=json.dumps(fig_id),
    )


def repr_html_iframe(widget, *, resizable: bool = False,
                     max_width: int = MAX_NOTEBOOK_WIDTH,
                     max_height: int = 800) -> str:
    """Return a centred, responsive ``<iframe srcdoc=...>`` embedding *widget*."""
    inner_html = build_standalone_html(widget, resizable=resizable)
    escaped    = escape(inner_html, quote=True)
    uid        = str(uuid4()).replace("-", "")

    w, h = _widget_px(widget)

    if not resizable:
        init_scale = min(1.0, max_width / w)
        init_w     = round(w * init_scale)
        init_h     = round(h * init_scale)
        scale_css  = f"{init_scale:.6f}".rstrip("0").rstrip(".")

        js = (
            f"(function(){{"
            f"var wrap=document.getElementById('vw-{uid}'),"
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

        return (
            f'<div style="display:block;text-align:center;line-height:0;margin:8px 0;">'
            f'<div id="vw-{uid}" style="display:inline-block;overflow:hidden;'
            f'position:relative;width:{init_w}px;height:{init_h}px;">'
            f'<iframe srcdoc="{escaped}" frameborder="0" scrolling="no" '
            f'style="width:{w}px;height:{h}px;border:none;overflow:hidden;display:block;'
            f'transform-origin:top left;transform:scale({scale_css});'
            f'position:absolute;top:0;left:0;">'
            f'</iframe>'
            f'</div>'
            f'<script>{js}</script>'
            f'</div>'
        )
    else:
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


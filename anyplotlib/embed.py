"""
embed.py
========

Use anyplotlib figures **outside Jupyter** — in Electron apps, MDI
sub-windows, kiosk dashboards, or any plain web page.  No kernel, no
ipywidgets, no anywidget runtime in the page.

Three levels of integration
---------------------------

**1. Static / self-contained (no Python at runtime)** — export a fully
self-contained HTML page (renderer + data inlined) and load it anywhere a
browser engine runs, e.g. an Electron ``BrowserWindow`` or ``<webview>``::

    import anyplotlib as apl
    fig, ax = apl.subplots(1, 1)
    ax.imshow(data)
    fig.save_html("plot.html")          # win.loadFile('plot.html')

All client-side interactivity (pan, zoom, widgets, markers) works; Python
callbacks obviously do not.

**2. JS-driven (your app owns the data)** — ship ``figure_esm.js`` with your
app and mount figures from JavaScript using the exported ``mount()``::

    import { mount } from './figure_esm.js';
    const handle = mount(container, state, { onEvent: ev => ... });
    handle.setPanelState(panelId, newPanelState);   // live updates
    handle.resize(w, h);  handle.dispose();

``state`` is the JSON dict produced by :func:`figure_state` — generate it
once from Python (build time, or a one-shot script) or construct it in JS.
Each ``mount()`` is fully self-contained, so one window can host many
figures (MDI-style) by mounting into separate containers.

**3. Live Python backend** — run Python alongside your app (sidecar process,
local WebSocket server, …) and keep figures fully interactive with Python
callbacks via :class:`FigureBridge`, which is transport-agnostic::

    # Python side (e.g. behind a websocket)
    bridge = FigureBridge(fig, send=lambda key, value: ws.send(
        json.dumps({"key": key, "value": value})))
    ws.on_message = lambda m: bridge.receive(**json.loads(m))

    // JS side
    const handle = mount(el, snapshot, {
      onSync: (key, value) => ws.send(JSON.stringify({key, value})),
    });
    ws.onmessage = (m) => { const u = JSON.parse(m.data);
                            handle.applyUpdate(u.key, u.value); };

See ``docs/embedding.rst`` for a complete Electron walkthrough.
"""

from __future__ import annotations

import base64
import dataclasses
import pathlib
from html import escape

import numpy as np

from anyplotlib._repr_utils import (
    PNG_HARVEST_LISTENER, build_standalone_html, script_json, _widget_state,
)

__all__ = ["figure_state", "to_html", "save_html", "esm_path", "FigureBridge",
           "Ragged", "pack_blocks", "navigated_html"]


def figure_state(fig) -> dict:
    """Return the figure's full serialised state as a plain JSON-safe dict.

    The dict contains every synced trait — ``layout_json``, ``fig_width``,
    ``fig_height``, ``event_json``, and one ``panel_<id>_json`` entry per
    panel — and is exactly what the JS ``mount(el, state)`` entry point
    expects.

    Parameters
    ----------
    fig : Figure

    Returns
    -------
    dict
    """
    # _widget_state also picks up ipywidgets infrastructure traits (layout,
    # tabbable, …) whose values aren't JSON.  The renderer only reads scalar
    # traits, so keep exactly those.
    return {k: v for k, v in _widget_state(fig).items()
            if isinstance(v, (str, int, float, bool)) or v is None}


def to_html(fig, *, resizable: bool = True) -> str:
    """Return a fully self-contained HTML page rendering *fig*.

    The page inlines the renderer and all figure data; it needs no network,
    kernel, or Python at view time.  Client-side interactivity (pan, zoom,
    overlay widgets) is preserved.

    Parameters
    ----------
    fig : Figure
    resizable : bool, optional
        Keep the figure's drag-to-resize handle.  Default ``True``.
    """
    return build_standalone_html(fig, resizable=resizable)


def save_html(fig, path, *, resizable: bool = True) -> pathlib.Path:
    """Write :func:`to_html` output to *path* and return it as a ``Path``."""
    p = pathlib.Path(path)
    p.write_text(to_html(fig, resizable=resizable), encoding="utf-8")
    return p


def esm_path() -> pathlib.Path:
    """Return the path to ``figure_esm.js`` for bundling into a JS app.

    Copy (or import) this file into your Electron / web build; it exports
    ``mount`` and ``createLocalModel`` alongside the anywidget ``render``.
    """
    return pathlib.Path(__file__).parent / "figure_esm.js"


class FigureBridge:
    """Transport-agnostic two-way sync between a live ``Figure`` and a
    remote JS view mounted with ``mount(el, state, {onSync})``.

    You supply the pipe (WebSocket, Electron IPC via a sidecar, stdio, …);
    the bridge supplies the protocol: plain ``(key, value)`` pairs.

    Parameters
    ----------
    fig : Figure
        The live figure.  All Python-side mutations (``plot.set_data(...)``,
        marker/widget updates, layout changes) are forwarded automatically.
    send : callable(key: str, value) -> None
        Called for every outbound state change.  Wire it to your transport.

    Notes
    -----
    * **Python → JS**: any synced trait change triggers ``send(key, value)``;
      deliver it to ``handle.applyUpdate(key, value)`` in JS.
    * **JS → Python**: deliver each JS ``onSync(key, value)`` message to
      :meth:`receive`.  Interaction events (``event_json``) are dispatched to
      the figure's callback registries exactly as in Jupyter, so
      ``@plot.add_event_handler(...)`` handlers fire unchanged.
    * Echo is suppressed in both directions.
    """

    def __init__(self, fig, send) -> None:
        self._fig = fig
        self._send = send
        self._applying = False
        # names=traitlets.All: also covers panel traits added dynamically
        # after the bridge is created (Figure.add_traits on new panels).
        import traitlets
        fig.observe(self._on_trait_change, names=traitlets.All)

    # ── outbound (Python → JS) ────────────────────────────────────────────
    def _on_trait_change(self, change) -> None:
        if self._applying:
            return
        name = change["name"]
        trait = self._fig.traits().get(name)
        if trait is None or not trait.metadata.get("sync") or name.startswith("_"):
            return
        self._send(name, change["new"])

    def snapshot(self) -> dict:
        """Full state dict for the initial ``mount()`` on the JS side."""
        return figure_state(self._fig)

    # ── inbound (JS → Python) ─────────────────────────────────────────────
    def receive(self, key: str, value) -> None:
        """Apply one inbound ``(key, value)`` message from the JS view.

        ``event_json`` messages are dispatched to plot/widget callbacks;
        other keys (e.g. a panel's view state after a JS-side 3D rotate)
        are stored on the figure without echoing back.
        """
        if key == "event_json":
            self._fig._dispatch_event(value)
            return
        if not self._fig.has_trait(key):
            return
        self._applying = True
        try:
            setattr(self._fig, key, value)
        finally:
            self._applying = False

    def close(self) -> None:
        """Stop forwarding (unobserve the figure)."""
        import traitlets
        try:
            self._fig.unobserve(self._on_trait_change, names=traitlets.All)
        except ValueError:
            pass


# ---------------------------------------------------------------------------
# Navigated pages
# ---------------------------------------------------------------------------

#: The dtypes the JS runtime has a typed array for.  Anything else has to be
#: cast before packing, because a view it cannot name is a silent wrong answer.
_BLOCK_DTYPES = frozenset({"uint8", "int8", "uint16", "int16",
                           "uint32", "int32", "float32", "float64"})

#: Block offsets are padded to this, the largest element size above.
_BLOCK_ALIGNMENT = 8


@dataclasses.dataclass
class Ragged:
    """A block with a variable number of rows per navigation position.

    ``offsets`` is the row-pointer array: position ``i`` owns rows
    ``offsets[i]`` up to ``offsets[i + 1]``, so it has ``n_positions + 1``
    entries.  ``columns`` maps a name to one value per row.  ``nav_shape``
    gives the navigation grid when it has more than one axis, so a
    two-dimensional index resolves to the right row span.
    """

    offsets: np.ndarray
    columns: dict
    nav_shape: tuple = ()


def _block_dtype_name(array) -> str:
    name = str(array.dtype)
    if name not in _BLOCK_DTYPES:
        raise ValueError(
            f"block dtype {name!r} cannot be viewed by the page; cast it to one "
            f"of {', '.join(sorted(_BLOCK_DTYPES))} first")
    return name


def pack_blocks(blocks: dict) -> tuple[bytes, dict]:
    """Pack arrays into one little-endian byte string plus a manifest.

    *blocks* maps a name to a numpy array (a dense block whose leading axes are
    the navigation axes) or to a :class:`Ragged`.  The return is
    ``(payload, manifest)``: the page base64-decodes *payload* once into a
    single ``ArrayBuffer`` and takes a typed-array view per manifest entry, so
    no block is encoded or copied on its own.
    """
    payload = bytearray()
    manifest: dict = {}

    def append(array) -> dict:
        contiguous = np.ascontiguousarray(array)
        dtype_name = _block_dtype_name(contiguous)
        # A typed array can only view an offset that is a multiple of its
        # element size.
        padding = (-len(payload)) % _BLOCK_ALIGNMENT
        payload.extend(b"\0" * padding)
        spec = {"dtype": dtype_name, "offset": len(payload),
                "nbytes": int(contiguous.nbytes)}
        payload.extend(contiguous.astype(contiguous.dtype.newbyteorder("<"),
                                         copy=False).tobytes())
        return spec

    for name, block in blocks.items():
        if isinstance(block, Ragged):
            offsets = np.ascontiguousarray(block.offsets, dtype=np.int32)
            nav_shape = tuple(block.nav_shape) or (int(offsets.size) - 1,)
            entry = {"kind": "ragged", "nav_shape": [int(n) for n in nav_shape],
                     "offsets": append(offsets),
                     "columns": {column: append(values)
                                 for column, values in block.columns.items()}}
        else:
            array = np.ascontiguousarray(block)
            entry = dict(append(array), kind="dense",
                         shape=[int(n) for n in array.shape])
        manifest[name] = entry

    return bytes(payload), manifest


def _validate_bindings(state: dict, blocks: dict, bindings: list) -> None:
    """Raise when a binding names a panel or a block the page does not have."""
    panel_ids = {key[len("panel_"):-len("_json")] for key in state
                 if key.startswith("panel_") and key.endswith("_json")}
    for binding in bindings:
        panel_id = binding.get("panel_id")
        if panel_id not in panel_ids:
            raise ValueError(f"binding names unknown panel {panel_id!r}; "
                             f"the figure has {sorted(panel_ids)}")
        names = []
        if binding.get("frame") and binding["frame"].get("block"):
            names.append(binding["frame"]["block"])
        for overlay in binding.get("overlays") or []:
            names.append(overlay["block"])
        if binding.get("reduce"):
            names.append(binding["reduce"]["block"])
            navigator = binding["reduce"]["navigator_panel"]
            if navigator not in panel_ids:
                raise ValueError(f"reduce names unknown navigator panel {navigator!r}")
        for view in binding.get("views") or []:
            names.append(view["block"])
        if binding.get("readout"):
            names.append(binding["readout"]["block"])
        for name in names:
            if name not in blocks:
                raise ValueError(f"binding names unknown block {name!r}; "
                                 f"the page carries {sorted(blocks)}")


def _views_control(binding: dict) -> str:
    """The segmented control that picks which block a panel's frame comes from."""
    buttons = "".join(
        f'<button type="button" data-block="{escape(view["block"], quote=True)}"'
        f' aria-pressed="false">{escape(view["label"])}</button>'
        for view in binding["views"])
    panel_id = escape(str(binding["panel_id"]), quote=True)
    return f'<div class="apl-views" id="apl-views-{panel_id}">{buttons}</div>'


_NAVIGATED_PAGE = """\
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{title}</title>
<style>
  html, body {{ margin: 0; padding: 0; background: transparent; }}
  #apl-page {{ width: 100%; }}
  /* The renderer shrinks .apl-outer with transform:scale() whenever the
     figure is wider than its box; min-width:max-content is what lets it
     measure the native width to scale from. */
  .apl-outer {{ min-width: max-content; transform-origin: top left; }}
  .apl-title {{ font: 600 15px system-ui, sans-serif; margin: 8px 4px 4px; }}
  .apl-caption {{ font: 13px system-ui, sans-serif; margin: 4px 4px 8px;
                 color: #555; }}
  .apl-strip {{ font: 12px ui-monospace, monospace; margin: 2px 4px;
               color: #444; min-height: 1.2em; }}
  .apl-views {{ margin: 4px; display: flex; }}
  .apl-views button {{ font: 12px system-ui, sans-serif; padding: 3px 10px;
                      border: 1px solid #bbb; background: #f6f6f6; color: #222;
                      cursor: pointer; }}
  .apl-views button[aria-pressed="true"] {{ background: #2f6fd0; color: #fff;
                                           border-color: #2f6fd0; }}
  @media (prefers-color-scheme: dark) {{
    .apl-caption {{ color: #aaa; }}
    .apl-strip {{ color: #bbb; }}
    .apl-views button {{ background: #2a2a2a; border-color: #444; color: #ddd; }}
  }}
</style>
</head>
<body>
<div id="apl-page">
{title_html}<div id="apl-host"></div>{strips_html}{caption_html}
</div>
<script type="module">
const PAGE = {page_json};
const esmSource = {esm_json};
const blobUrl = URL.createObjectURL(new Blob([esmSource], {{type: "text/javascript"}}));
import(blobUrl).then(async (mod) => {{
  const handle = await mod.mountNavigated(
    document.getElementById("apl-host"), PAGE, {{}});
  window._aplHandle = handle;
  // The page's own inputs, so a host can mount a second figure from them or
  // read back what this one was built with.
  window._aplPage = PAGE;
  // The readers (maskFromWidget, rasterDisks, robustLevels, …) are useful to
  // anything this page grows around the figure, so keep the module reachable.
  window._aplModule = mod;
  globalThis.__aplExportPNG = (o) => handle.exportPNG(o);
  window._aplReady = true;
}}).catch((err) => {{
  document.getElementById("apl-host").textContent = "mount error: " + err;
}});

{png_harvest}
</script>
</body>
</html>
"""


def navigated_html(fig_or_state, blocks: dict, bindings: list, *,
                   chrome: dict | None = None, title: str = "",
                   caption: str = "") -> str:
    """Return a self-contained page whose navigator drives its other panels.

    *fig_or_state* is a live ``Figure`` or the dict :func:`figure_state`
    returns.  *blocks* is the data the page navigates, in the form
    :func:`pack_blocks` takes.  *bindings* says what each panel does::

        {panel_id, role: "navigator" | "driven" | "static",
         widgets: [...],
         frame: {block, kind: "image" | "disks", radius?, combine?, levels?,
                 width?, height?},
         views: [{label, block}],
         overlays: [{block, kind, style, columns?}],
         reduce: {block, navigator_panel, x?, y?, value?},
         readout: {block, names, units}}

    ``views`` are a committed result's alternative frames (a strain map's
    epsilon_xx, epsilon_yy, epsilon_xy, omega): the page renders a segmented
    control that swaps which block the panel's frame is read from, at whatever
    position the navigator is already on.  With ``views``, ``frame.block`` may
    be omitted and the first entry is the one shown first.  A navigator binding
    may carry ``initial_index`` to open somewhere other than the origin.

    The renderer, the figure state, the packed data and the bindings are all
    inlined, so the page needs no network and no Python at view time.

    Raises
    ------
    ValueError
        When a binding names a panel or a block the page does not carry.
    """
    state = (fig_or_state if isinstance(fig_or_state, dict)
             else figure_state(fig_or_state))
    payload, manifest = pack_blocks(blocks)
    _validate_bindings(state, manifest, bindings)

    page = {"state": state, "bindings": bindings, "chrome": chrome or {},
            "blocks": {"data": base64.b64encode(payload).decode("ascii"),
                       "manifest": manifest}}

    strips = "".join(
        '<div class="apl-strip" '
        f'id="apl-readout-{escape(str(binding["panel_id"]), quote=True)}"></div>'
        for binding in bindings if binding.get("readout"))
    strips += "".join(_views_control(binding)
                      for binding in bindings if binding.get("views"))

    return _NAVIGATED_PAGE.format(
        title=escape(title or "anyplotlib figure"),
        title_html=(f'<div class="apl-title">{escape(title)}</div>\n' if title else ""),
        caption_html=(f'<div class="apl-caption">{escape(caption)}</div>'
                      if caption else ""),
        strips_html=strips,
        page_json=script_json(page),
        esm_json=script_json(esm_path().read_text(encoding="utf-8")),
        png_harvest=PNG_HARVEST_LISTENER,
    )

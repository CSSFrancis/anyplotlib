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

import pathlib

from anyplotlib._repr_utils import build_standalone_html, _widget_state

__all__ = ["figure_state", "to_html", "save_html", "esm_path", "FigureBridge"]


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

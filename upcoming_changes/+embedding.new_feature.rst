anyplotlib figures can now be embedded outside Jupyter — e.g. in Electron
apps, MDI sub-windows, or plain web pages — with no anywidget runtime.
``fig.save_html()`` / ``fig.to_html()`` export a self-contained interactive
page; ``figure_esm.js`` now exports a ``mount(el, state, opts)`` entry point
for direct JS embedding (with ``onEvent`` interaction callbacks, live
``setPanelState`` updates, ``resize``, and ``dispose``); and the new
``anyplotlib.embed`` module provides ``figure_state()``, ``esm_path()``, and
a transport-agnostic ``FigureBridge`` for live two-way Python sync over any
pipe (WebSocket, IPC, stdio) with full event-callback support.

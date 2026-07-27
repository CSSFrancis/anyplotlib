=================================
Embedding outside Jupyter
=================================

anyplotlib figures do not require Jupyter, ipywidgets, or the anywidget
runtime.  The renderer is a single self-contained ES module
(``figure_esm.js``) that draws from a plain JSON state dict, so a figure can
live anywhere a browser engine runs: an **Electron** app, a Tauri/webview
app, an MDI-style multi-window workspace, a kiosk dashboard, or a static
web page.

There are three levels of integration, from zero-Python-at-runtime to a
fully live Python backend.

Level 1 — self-contained HTML (no Python at view time)
=======================================================

Export the figure as a single HTML file with the renderer and all data
inlined::

    import anyplotlib as apl
    import numpy as np

    fig, ax = apl.subplots(1, 1, figsize=(800, 500))
    ax.imshow(np.load("frame.npy"), cmap="viridis")
    fig.save_html("plot.html")

Load it in an Electron window — that's the whole integration::

    const { BrowserWindow } = require('electron');
    const win = new BrowserWindow({ width: 840, height: 560 });
    win.loadFile('plot.html');

Pan, zoom, overlay widgets, markers, and keyboard shortcuts all work;
Python callbacks (obviously) do not.  ``fig.to_html()`` returns the same
page as a string if you want to serve or template it yourself.

Level 2 — JS-driven: your app owns the data
============================================

Bundle ``figure_esm.js`` into your app (``anyplotlib.embed.esm_path()``
tells you where to copy it from) and mount figures directly from
JavaScript:

.. code-block:: javascript

    import { mount } from './figure_esm.js';

    const handle = mount(document.getElementById('plot-host'), state, {
      onEvent: (ev) => {
        // every interaction event: pointer_down/up/move, wheel, key_down …
        if (ev.event_type === 'pointer_down')
          console.log('clicked data coords', ev.xdata, ev.ydata);
      },
    });

    // Live updates — replace one panel's state and it re-renders:
    handle.setPanelState(panelId, newPanelState);
    handle.resize(900, 600);
    handle.dispose();          // remove the figure's DOM

``state`` is the figure-state dict.  Generate it from Python once (at build
time or via a one-shot script)::

    import json, anyplotlib as apl
    from anyplotlib.embed import figure_state

    fig, ax = apl.subplots(1, 1)
    plot = ax.imshow(template_data)
    json.dump(figure_state(fig), open("figure_state.json", "w"))
    print("panel id:", plot._id)   # key for setPanelState

Each ``mount()`` call is fully independent — mount as many figures as you
like into separate containers in one window.  This is the natural fit for
**MDI sub-windows**: give every sub-window its own host ``<div>`` (or
``<webview>``/iframe for hard isolation) and call ``mount`` per window.
Call ``handle.resize(w, h)`` from your sub-window's resize hook.

Level 3 — live Python backend (full callback support)
======================================================

Run Python next to your app (a sidecar process exposing a local WebSocket
is the common Electron pattern) and keep figures *fully* interactive —
``@plot.add_event_handler(...)`` callbacks fire exactly as in Jupyter.

:class:`anyplotlib.embed.FigureBridge` is transport-agnostic: you supply
the pipe, it supplies the ``(key, value)`` protocol.

**Python sidecar** (here with the ``websockets`` package)::

    import asyncio, json
    import numpy as np
    import websockets
    import anyplotlib as apl
    from anyplotlib.embed import FigureBridge

    fig, ax = apl.subplots(1, 1, figsize=(700, 450))
    plot = ax.imshow(np.random.rand(256, 256))
    cross = plot.add_widget("crosshair", cx=128, cy=128)

    async def serve(ws):
        loop = asyncio.get_running_loop()
        bridge = FigureBridge(fig, send=lambda key, value:
            loop.create_task(ws.send(json.dumps({"key": key, "value": value}))))
        await ws.send(json.dumps({"snapshot": bridge.snapshot()}))

        @cross.add_event_handler("pointer_move")     # fires from Electron!
        def follow(event):
            print("crosshair at", cross.cx, cross.cy)

        async for message in ws:
            m = json.loads(message)
            bridge.receive(m["key"], m["value"])     # JS → Python

    asyncio.run(websockets.serve(serve, "localhost", 8765))

**Electron renderer**:

.. code-block:: javascript

    import { mount } from './figure_esm.js';

    const ws = new WebSocket('ws://localhost:8765');
    let handle = null;

    ws.onmessage = (msg) => {
      const m = JSON.parse(msg.data);
      if (m.snapshot) {
        handle = mount(document.getElementById('plot-host'), m.snapshot, {
          // forward every JS-side write (events, view changes) to Python
          onSync: (key, value) => ws.send(JSON.stringify({ key, value })),
        });
      } else if (handle) {
        handle.applyUpdate(m.key, m.value);   // Python → JS, echo-free
      }
    };

Any Python-side mutation — ``plot.set_data(...)``, markers, titles, layout
changes — streams to the window automatically; drags, clicks, and keys
stream back into your Python callbacks.  Echo is suppressed in both
directions by the bridge and ``applyUpdate``.

API reference
=============

.. automodule:: anyplotlib.embed
   :members:
   :undoc-members:

JS handle reference
-------------------

``mount(el, state, opts) → handle``

================================  ============================================
``handle.setPanelState(id, st)``  Replace one panel's state (dict or JSON
                                  string) and re-render it.
``handle.set(key, value)``        Raw model write + sync flush.
``handle.get(key)``               Read any model key.
``handle.applyUpdate(key, v)``    Apply a Python-originated update without
                                  echoing it back through ``onSync``.
``handle.resize(w, h)``           Resize the figure (CSS pixels).
``handle.dispose()``              Remove the figure's DOM and listeners.
``handle.model``                  The underlying local model (advanced).
================================  ============================================

``opts.onEvent(ev)`` receives parsed interaction events (the same payloads
Python's :class:`~anyplotlib.Event` carries); ``opts.onSync(key, value)``
receives every outbound model write for bridging to Python.

Notes and caveats
=================

* The state dict is the **wire format**, not a stable public schema — treat
  panel-state internals as opaque where you can, and prefer regenerating
  states from Python when upgrading anyplotlib versions.
* ``dispose()`` removes the figure's DOM; for hard teardown of all
  window-level listeners, host each figure in its own iframe/webview and
  drop the frame (this is also the most robust MDI isolation).
* One renderer file, no build step: ``figure_esm.js`` has no imports, so it
  works with any bundler or directly as a ``<script type="module">``.

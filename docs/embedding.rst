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
      // 2-D hover readout (position + pixel value) for your own status bar —
      // see "Owning the hover readout" below.
      onReadout: (info) => { statusEl.textContent = info ? info.text : ''; },
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

Navigated pages — one page that owns its data
==============================================

A *navigated* figure is one where a navigator panel drives the others: move the
crosshair over the scan and the signal panel shows that position's frame, its
overlays follow, and a detector drawn on the signal panel reduces the whole
dataset back onto the navigator.  :func:`~anyplotlib.embed.navigated_html`
exports that as a single file — the renderer, the figure state, the data and the
bindings all inlined, no network and no Python at view time.

The data travels as *blocks*.  A **dense** block is a numpy array whose leading
axes are the navigation axes; a :class:`~anyplotlib.embed.Ragged` block is a
row-pointer array plus one value array per column, for a variable number of rows
per position (diffraction spots, detected particles, peaks).
:func:`~anyplotlib.embed.pack_blocks` concatenates them into one little-endian
byte string, which the page decodes once into a single ``ArrayBuffer`` and reads
through typed-array views — no per-block base64, no copy per frame.

::

    import numpy as np
    import anyplotlib as apl
    from anyplotlib.embed import navigated_html

    scan = np.load("scan.npy")            # (32, 32, 128, 128) uint8

    fig, axes = apl.subplots(1, 2, figsize=(760, 380))
    navigator = axes[0].imshow(scan.sum(axis=(2, 3)), cmap="gray")
    signal    = axes[1].imshow(scan[0, 0], cmap="gray")
    navigator.add_widget("crosshair", cx=0, cy=0)
    signal.add_widget("rectangle", x=48, y=48, w=32, h=32)   # the detector

    html = navigated_html(
        fig,
        {"scan": scan},
        [
            {"panel_id": navigator._id, "role": "navigator"},
            {"panel_id": signal._id, "role": "driven",
             "frame":  {"block": "scan", "kind": "image"},
             "reduce": {"block": "scan", "navigator_panel": navigator._id}},
        ],
        title="Scan", caption="Drag the crosshair; drag the detector to re-map.",
    )
    open("scan.html", "w", encoding="utf-8").write(html)

Open ``scan.html`` in any browser, or point an Electron window or an ``<iframe>``
at it.  The page posts ``{aplEmbedHeight}`` to its parent so a host frame can
size itself, answers the ``anyplotlib_export_png`` harvest protocol
(see :doc:`exporting`), and translates touches into pointer events so it works
on a phone.

Bindings
--------

One binding per panel.  ``role`` is ``"navigator"`` (its widgets drive the
page), ``"driven"`` (it is refreshed on every dispatch) or ``"static"``.

=====================  ========================================================
``panel_id``           Which panel this binding describes.
``widgets``            Optional ``overlay_widgets`` entries to install on it.
``frame``              ``{block, kind}`` — ``"image"`` blits the block's frame,
                       ``"disks"`` splats a ragged block's rows as filled disks
                       (``radius``, ``combine``).  ``levels`` fixes the display
                       window; without it each frame gets a robust 2–98 %
                       window of its own.
``overlays``           ``[{block, kind, style, columns}]`` — ``"circles"``,
                       ``"arrows"`` and ``"lines"`` become markers on a 2-D
                       panel, ``"curves"`` becomes an extra line on a 1-D one.
                       ``style`` keys are the ones ``MarkerGroup.to_wire``
                       emits; ``columns`` renames the block's columns when they
                       are not ``x``/``y`` (and ``u``/``v``, ``x1``…``y2``).
``reduce``             ``{block, navigator_panel}`` — a detector widget on this
                       panel re-maps the navigator (see below).  For a ragged
                       block, name the ``x``, ``y`` and ``value`` columns.
``views``              ``[{label, block}]`` — a committed result's alternative
                       frames (a strain map's εxx, εyy, εxy, ω).  The page
                       renders a segmented control that swaps which block the
                       panel's frame is read from, at whatever position the
                       navigator is on.  With ``views``, ``frame.block`` may be
                       omitted and the first entry is shown first.
``readout``            ``{block, names, units}`` — written into
                       ``#apl-readout-<panel_id>``.
=====================  ========================================================

``frame`` also takes ``width`` and ``height``, the pixel grid a ``"disks"``
raster is splatted into; they default to the panel's own image size.  A
navigator binding takes ``initial_index`` to open somewhere other than the
origin.

How a virtual image flows through it
------------------------------------

The signal panel carries a detector widget — a rectangle, a circle or an
annulus — and its binding's ``reduce`` names the block to read and the
navigator panel to write.  When the detector moves, the page turns the widget
into a mask over the signal grid: every pixel whose integer coordinate lies
inside the shape.  It then sums, for each navigation position, that position's
frame under the mask (a dense block) or the intensity of every row whose
rounded position falls inside it (a ragged block).  The result is one value per
navigation position — exactly the navigator's own shape — and it goes to the
navigator with ``setImage``.  Moving the detector therefore re-maps the whole
scan, which is what a virtual image is.

A binding that names a panel or a block the page does not carry raises
``ValueError`` at build time rather than rendering an empty figure.

Driving it from JavaScript
--------------------------

The same runtime is a plain export, so a host that already has the data can
skip ``navigated_html`` and mount it directly:

.. code-block:: javascript

    import { mountNavigated } from './figure_esm.js';

    const handle = await mountNavigated(host, page);   // page = {state, blocks, …}
    handle.dispatch([12, 7]);        // navigate from code
    handle.index;                    // the current navigation index
    handle.blocks;                   // the decoded typed-array views

``mountNavigated`` returns the ordinary ``mount()`` handle, so everything in
the table above still works on it.

The readers are exported too, under the ``embed`` namespace, for chrome the
page grows around the figure: ``embed.dense(block)`` and ``embed.ragged(block)``
give ``at`` / ``gather`` / ``reduce``, ``embed.maskFromWidget(widget, w, h)``
turns a rectangle, circle or annulus widget into a selection mask,
``embed.rasterDisks(rows, w, h, radius, combine)`` splats rows as disks, and
``embed.robustLevels`` / ``embed.toU8`` are the percentile window and the 8-bit
code map the renderer blits.  ``mountNavigated`` is both a named export and a
member of that namespace.

Pushing frames: ``setImage``
-----------------------------

``handle.setImage(panelId, bytes, width, height, opts)`` replaces a 2-D panel's
image with **raw pixel bytes** — ``width * height`` colormap codes, or
``width * height * 4`` RGBA bytes with ``opts.rgb``.  This is the setter a scrub
needs: pushing a frame through the panel state costs 6.7 ms at 512² and
129–136 ms at 2048² of main-thread time, against a fraction of a millisecond
here, because the bytes go straight to the renderer's draw path instead of
through base64 and a JSON trait.

``opts.display_min`` / ``opts.display_max`` set the colour window the codes were
mapped over; geometry follows the bytes in the same animation frame, so a frame
of a different size never paints once at the new dimensions over the old
pixels.  The repaint lands on the next animation frame, so several frames pushed
in one task paint once — call ``handle.flushImages()`` if you need the pixels
before then (``exportPNG`` and ``exportCanvas`` already do).


API reference
=============

.. automodule:: anyplotlib.embed
   :members:
   :undoc-members:

JS handle reference
-------------------

``mount(el, state, opts) → handle``

=====================================  ========================================================
``handle.setPanelState(id, st)``       Replace one panel's state (dict or JSON string) and
                                       re-render it.
``handle.patchPanel(id, partial)``     Merge *partial* into one panel's state and re-render.
                                       Values are stored verbatim — markers, ``extra_lines``,
                                       ``display_min``/``max``, ``overlay_widgets``.
``handle.setImage(id, b, w, h, o)``    Replace a 2-D panel's image with raw pixel bytes
                                       (``w*h`` codes, or ``w*h*4`` with ``o.rgb``).  Repaints
                                       on the next animation frame.
``handle.flushImages()``               Paint pending ``setImage`` frames now.
``handle.panelIds()``                  The panel ids in layout order.
``handle.set(key, value)``             Raw model write + sync flush.
``handle.get(key)``                    Read any model key.
``handle.applyUpdate(key, v)``         Apply a Python-originated update without echoing it back
                                       through ``onSync``.
``handle.resize(w, h)``                Resize the figure (CSS pixels).
``handle.exportPNG(opts)``             Composite to a PNG data URL.  Resolves to ``{dataUrl,
                                       width, height}``.  See :doc:`exporting`.
``handle.exportCanvas(opts)``          The same, synchronously, returning ``{canvas, width,
                                       height}`` so a host can encode it itself (TIFF, JPEG, a
                                       PDF page).
``handle.registerExportAction(a)``     Add an entry to the right-click export menu; returns an
                                       unregister function.
``handle.unregisterExportAction(id)``  Remove one by id.
``handle.dispose()``                   Remove the figure's DOM and listeners.
``handle.model``                       The underlying local model (advanced).
=====================================  ========================================================

Export options (all optional), shared by ``exportPNG`` and ``exportCanvas``:

==================  ==========================================================
``scale``           Extra multiplier over ``devicePixelRatio`` (default 1).
``includeWidgets``  Draw overlay widgets, without their drag handles.
``panelId``         Export just this panel instead of the whole figure.
``source``          ``'view'`` (as displayed), ``'full'`` (whole data extent)
                    or ``'native'`` (one output pixel per data pixel).
``theme``           ``'current'``, ``'light'`` or ``'dark'``.
==================  ==========================================================

``opts.onEvent(ev)`` receives parsed interaction events (the same payloads
Python's :class:`~anyplotlib.Event` carries); ``opts.onSync(key, value)``
receives every outbound model write for bridging to Python.

.. _embed-readout:

Owning the hover readout
------------------------

2-D panels show the cursor's position and pixel value in a small pill drawn on the
image (see :ref:`hover-readout`).  In a desktop app you usually want that in your own
chrome instead — a status line pinned to the bottom-right of the window, where it
never covers data.  Hide the pill from Python and take the payload from
``opts.onReadout``:

.. code-block:: python

    plot.set_readout_visible(False)      # before figure_state(fig)

.. code-block:: javascript

    const statusEl = document.getElementById('status-bar');   // your own chrome

    mount(host, state, {
      onReadout: (info) => {
        // info === null when the cursor leaves the image
        statusEl.textContent = info ? info.text : '';
      },
    });

The same payload is also dispatched as an ``apl:readout`` :class:`CustomEvent` that
bubbles off the mount container, which is handy when the listener lives somewhere
other than the ``mount()`` call site::

    host.addEventListener('apl:readout', (e) => render(e.detail));

``info`` fields:

======================  ======================================================
``panel_id``            Which panel the cursor is over.
``img_x``, ``img_y``    Fractional position in image pixels.
``col``, ``row``        Integer pixel index (``img_x``/``img_y`` floored).
``xdata``, ``ydata``    Physical position in ``units``.
``units``               Axis units string (``"px"`` when unset).
``value``               Pixel value, or ``null`` for a true-colour image.
``exact``               ``true`` when ``value`` is the true datum rather than a
                        quantised estimate (see :ref:`hover-readout`).
``rgba``                ``[r, g, b, a]`` for a true-colour image, else ``null``.
``text``                The formatted one-line string the built-in pill uses.
======================  ======================================================

Updates are deduplicated by ``text``, so a cursor moving inside one pixel does not
call back repeatedly.  ``exact`` flips to ``true`` for the same pixel when a value
probe resolves, which fires one more callback — render it, don't ignore it.

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

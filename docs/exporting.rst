Exporting images
================

Every figure can be saved or copied as a PNG — from the plot itself, from the
keyboard, or from Python.

.. _export-menu:

The right-click menu
--------------------

Hover a figure and a **⤓** badge appears in its top-right corner; click it for
the export menu.  Right-clicking anywhere on the figure — including the axis
gutters, the colorbar and the title strip — opens the same menu.

.. note::

   Prefer the badge inside JupyterLab, PyCharm and VS Code.  Those hosts install
   their own ``contextmenu`` and keyboard handlers, and may swallow a right-click
   or ``Ctrl``/``Cmd+C`` before the figure ever sees it.  The badge is an
   ordinary left click and always works.

Entries act on **the panel you clicked** (or last hovered) first, then on the
whole figure:

.. code-block:: text

   This panel
     Copy image                        Ctrl+C
     Save PNG…
     Save full view…
     Save at native resolution…
   Whole figure
     Copy figure
     Save PNG…
     Save full view…
   Theme
     ● Current    ○ Light    ○ Dark

The **Theme** choice is sticky for that figure and applies to everything above
it, so a dark-themed notebook can still produce a light figure for a paper
without changing the notebook's theme.

``Ctrl+C`` (``Cmd+C`` on macOS) copies the plot under the cursor and shows a
brief *"Image copied to clipboard"* confirmation.  With no plot hovered it
copies the whole figure.  The shortcut only fires while the figure has focus, so
it never interferes with copying a notebook cell — and for the same reason a
host that claims the key first wins; use *Copy image* from the badge menu when
that happens.

.. note::

   Clipboard image writes need a secure page (``https``, or ``localhost`` —
   which covers a normal local Jupyter server).  If the browser refuses, the
   toast says so and *Save PNG…* still works.

.. _export-sources:

The three sources
-----------------

.. list-table::
   :header-rows: 1
   :widths: 18 82

   * - Source
     - What you get
   * - **Current view**
     - The plot exactly as displayed — zoom, pan and contrast included.  The
       output is the size it is on screen (times ``scale``).
   * - **Full view**
     - The whole data extent, with the zoom reset, at the panel's on-screen
       resolution.  Useful when you have zoomed in to inspect something but want
       to save the whole frame.
   * - **Native resolution**
     - One output pixel per data pixel, so a 2048×2048 array becomes a 2048×2048
       image.  The axes, colorbar, title, markers and widgets are all redrawn at
       that size, so nothing is lost — but they keep their normal point sizes,
       which look small against a very large image.  Raise ``title_size``,
       ``tick_size`` and ``x_label_size`` / ``y_label_size`` if that matters.

Native resolution applies to a single 2-D image panel — different panels have
different native sizes, so there is no figure-wide version.

Interactive overlay widgets (line profiles, span selectors and so on) are
**included** by both the menu and :meth:`~anyplotlib.Figure.savefig`, drawn
without their drag handles so the export looks like the plot rather than the
editor.  Pass ``include_widgets=False`` to leave them out.  The lower-level
``handle.exportPNG`` defaults to ``includeWidgets: false`` instead, for
backwards compatibility.

.. _export-savefig:

From Python
-----------

:meth:`~anyplotlib.Figure.savefig` offers the same three sources:

.. code-block:: python

   import numpy as np
   import anyplotlib as apl

   fig, ax = apl.subplots(1, 1, figsize=(600, 480))
   plot = ax.imshow(np.random.random((2048, 2048)), cmap="viridis")

   fig.savefig("figure.png")                             # as displayed
   fig.savefig("paper.png", theme="light", scale=2)      # light theme, 2x
   fig.savefig("panel.png", panel=plot)                  # just this panel
   fig.savefig("data.png", source="native", panel=plot)  # 2048x2048

Because the renderer is the JavaScript one, ``savefig`` draws the figure in a
headless browser rather than re-implementing anything — so the file is
pixel-for-pixel what you see, including the zoom and contrast you set
interactively.  That needs Playwright, which is not a hard dependency:

.. code-block:: console

   $ pip install "anyplotlib[docs]"
   $ playwright install chromium

.. _export-tiled:

Large images and tile mode
--------------------------

Images larger than ``Plot2D.TILE_THRESHOLD`` (1024 px on a side) stream to the
browser in **tile mode** by default: the page receives a downsampled overview
plus one high-resolution tile of whatever you are looking at.  That keeps very
large frames interactive, but it means *the full array is never in the browser*.

So for a tiled plot:

* **In the menu**, *Save at native resolution…* is shown but disabled, with a
  tooltip explaining why.
* **From Python**, ``fig.savefig(..., source="native")`` works: the backend is
  re-sampled at full resolution for the export only, and the live figure is left
  untouched.

*Current view* and *full view* are unaffected and work identically either way.

Pass ``tile=False`` to :meth:`~anyplotlib.Axes.imshow` if you would rather send
the whole frame up front and keep native export available in the browser.

.. _export-downloads:

Where the file goes
-------------------

There are two save entries, because they make different trade-offs:

**Save PNG…** downloads straight to your downloads folder.  No permission
prompt, works in every browser.  If you would rather be asked where to put it,
turn on Chrome's *Settings → Downloads → "Ask where to save each file before
downloading"* — that gives a native dialog through this same route.

**Save as… (choose folder)** opens a real system Save dialog so you can pick the
name and folder directly.  It only appears where the browser supports it
(Chromium-based, on a secure page), and it costs a one-time Chrome permission
prompt warning that the site *"can see edits you make"*.  That is unavoidable:
the underlying API hands the page a persistent writable handle to the file
rather than a one-shot save, so Chrome asks for file-editing permission.  The
image is written once and the handle discarded.

If a host blocks script-started downloads — VS Code notebooks, pages inside a
sandboxed ``<iframe>`` — which it does silently, with no way to detect in
advance, the image appears in an **in-figure preview** captioned *"Right-click
the image → Save image as…"*.  That needs no permission and always works.
Embedding hosts also receive the PNG over ``postMessage``.

.. _export-registry:

Adding your own save formats
----------------------------

An application embedding anyplotlib (see :doc:`embedding`) can add entries to the
same menu, so a host can offer formats anyplotlib knows nothing about:

.. code-block:: javascript

   const handle = mount(el, state, {});

   const unregister = handle.registerExportAction({
     id:      'save-tiff',
     label:   'Save as TIFF…',
     group:   'My app',           // section heading in the menu
     scope:   'panel',            // 'panel' | 'figure' | 'both'
     order:   10,                 // sort order within the group
     enabled: (ctx) => ctx.kind === '2d',
     handler: async (ctx) => {
       const { canvas } = ctx.exportCanvas({ source: 'native' });
       await myHost.writeTiff(ctx.panelId, canvas);
       ctx.toast('Saved as TIFF');
     },
   });

The handler receives a context object:

======================  ======================================================
``panelId``, ``kind``   The clicked panel (``''``/``null`` for figure scope).
``isInset``             Whether that panel is an inset.
``state``               The panel's live state object.
``theme``               The resolved palette, honouring the menu's choice.
``themeName``           ``'current'``, ``'light'`` or ``'dark'``.
``figure``              ``{width, height}`` in CSS pixels.
``exportPNG(opts)``     Promise of ``{dataUrl, width, height}``.
``exportCanvas(opts)``  ``{canvas, width, height}``, synchronously.
``downloadPNG(c, n)``   Hand a canvas to the browser as a download.
``copyPNG(c)``          Write a canvas to the clipboard.
``toast(text, ms)``     Show a transient message on the figure.
``model``               The underlying model.
``event``               The originating ``MouseEvent``.
======================  ======================================================

``exportPNG`` and ``exportCanvas`` come pre-bound to the clicked panel and the
selected theme, so ``ctx.exportCanvas()`` with no arguments is already the right
thing.  ``registerExportAction`` returns a function that removes the entry
again.

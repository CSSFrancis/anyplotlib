Figures can now be **saved and copied as PNG images**. Right-click any plot for a
menu offering *Copy image*, *Save PNG…*, *Save full view…* and *Save at native
resolution…* for the panel you clicked, the same for the whole figure, and a
sticky **Theme** choice (*Current* / *Light* / *Dark*) so a dark-themed notebook
can still produce a light figure for a paper. ``Ctrl+C`` (``Cmd+C`` on macOS)
copies the plot under the cursor to the clipboard, with a brief
*"Image copied to clipboard"* confirmation; with no plot hovered it copies the
whole figure. Inside JupyterLab, PyCharm and VS Code the badge is the reliable
route: those hosts install their own ``contextmenu`` and keyboard handlers and
may swallow a right-click or ``Cmd+C`` before the figure ever sees it. *Save PNG…* downloads without any permission prompt; a separate *Save as…*
entry opens a real system file dialog where the browser supports one
(Chromium), at the cost of Chrome's file-editing permission prompt. Hosts that
block script-started downloads get an in-figure preview instead.
The three sources are *current view* (zoom, pan and contrast
exactly as displayed), *full view* (the whole data extent at the panel's
on-screen resolution) and *native resolution* (one output pixel per data pixel,
with the axes, colorbar, title, markers and widgets all redrawn at that size).

The same thing is available from Python as :meth:`~anyplotlib.Figure.savefig`::

    fig.savefig("figure.png")                                # as displayed
    fig.savefig("paper.png", theme="light", scale=2)         # light, 2x
    fig.savefig("data.png", source="native", panel=plot)     # 1:1 with the data

``savefig`` renders through the real JavaScript renderer in a headless browser,
so the output is exactly what the figure looks like on screen — it needs
Playwright (``pip install "anyplotlib[docs]"`` then
``playwright install chromium``). ``source="native"`` works even for a **tiled**
plot, whose full-resolution array normally never leaves Python: the backend is
re-sampled at full resolution for the export only, leaving the live figure
untouched. In the browser that case is offered but disabled, with a tooltip
pointing at ``savefig``, because the page only ever holds a downsampled
overview.

Downstream applications can add their own entries to the menu through the
embedding handle, so a host can save formats anyplotlib knows nothing about::

    handle.registerExportAction({
      id: 'save-tiff', label: 'Save as TIFF…', scope: 'panel',
      handler: (ctx) => host.writeTiff(ctx.panelId, ctx.exportCanvas().canvas),
    })

The handler receives the clicked panel, its state, the chosen theme, and bound
``exportPNG`` / ``exportCanvas`` / ``downloadPNG`` / ``copyPNG`` / ``toast``
helpers. See :doc:`exporting` for the full reference.

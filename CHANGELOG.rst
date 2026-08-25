=========
Changelog
=========

All notable changes to **anyplotlib** are documented here.

Fragment files in ``upcoming_changes/`` are assembled into this file by
`towncrier <https://towncrier.readthedocs.io/>`_ when a release is prepared
(see ``upcoming_changes/README.rst`` for contributor instructions).

.. towncrier release notes start

0.8.0 (2026-08-25)
==================

API and Behaviour Changes
-------------------------

- In tile mode, ``set_data``/``update_tile_source`` now re-derive the quantisation band
  ``raw_min``/``raw_max`` from the incoming frame when the current band is unset or
  degenerate (it previously stayed as first derived, even from a flat placeholder). A
  band that is already valid is still never re-derived, so a contrast change keeps
  re-windowing in the LUT with no pixel re-encode. One visible consequence: a tiled plot
  born on a placeholder now quantises subsequent frames over the frame's own range
  rather than the display window, matching what ``imshow`` of a large frame has always
  done — so its wire bytes can differ by a rounding step from the equivalent untiled
  plot, while the displayed image is unchanged. (`#60 <https://github.com/CSSFrancis/anyplotlib/pull/60>`_)


New Features
------------

- Added :meth:`~anyplotlib.plot2d.Plot2D.set_tile_band` to pin the fixed quantisation
  band tile bytes are encoded over, for a consumer that already knows the honest range
  (a camera's bit depth, a detector's saturation point) or whose source starts flat and
  so has no range to auto-derive. It re-samples the overview and any active detail tile
  over the new band in a single push, replacing the practice of reaching into
  ``plot._state["raw_min"/"raw_max"]`` and calling ``update_tile_source()`` by hand. (`#60 <https://github.com/CSSFrancis/anyplotlib/pull/60>`_)
- Added :meth:`~anyplotlib.plot2d.Plot2D.set_display_window`, which moves the
  contrast window without re-quantising the pixels — the non-destructive
  counterpart to :meth:`~anyplotlib.plot2d.Plot2D.set_clim`, and what lets a
  saved page be re-windowed with no Python behind it. (`#61 <https://github.com/CSSFrancis/anyplotlib/pull/61>`_)


Bug Fixes
---------

- Fixed a tiled 2-D image rendering solid black when tile mode was entered on a flat
  placeholder frame (e.g. ``imshow`` of zeros before real data exists). The fixed
  quantisation band ``raw_min``/``raw_max`` was derived from that placeholder — a
  degenerate ``(0, 0)`` — and no later ``set_data`` re-derived it, leaving the two ends
  of the protocol disagreeing about what it meant: the Python encoder treats a
  degenerate band as unset and quantises over the display window, while the renderer
  honoured ``(0, 0)`` and mapped every code below the display floor. The panel rendered
  black on the WebGPU and Canvas2D paths alike, beside perfectly healthy stats and
  histograms, with no warning. ``set_data`` and ``update_tile_source`` now re-derive a
  degenerate band from the incoming frame, and the renderer falls back to the display
  window for a degenerate band in tile mode — in the image LUT and in the colorbar
  tick placement, which read the band the same way. (`#60 <https://github.com/CSSFrancis/anyplotlib/pull/60>`_)


0.7.3 (2026-08-13)
==================

New Features
------------

- ``Plot2D.add_circle_widget`` gains ``lock_center``: the centre is pinned and
  only the radius is draggable. A grab on the ring body is refused at hit-test
  time and falls through to the plot's own pan, so the hover cursor never
  promises a move and the centre cannot drift. Use it when the centre is fixed by
  the data — a ring on a power spectrum is centred on the DC term, and one nudged
  off-centre silently corrupts every radius measured from it.


0.7.2 (2026-08-03)
==================

Bug Fixes
---------

- ``Plot2D.set_overlay_mask`` now works in TILE mode. The renderer sizes the mask
  against ``base_width || image_width`` -- the tile overview grid -- but tile mode
  sets ``image_width`` to the full native frame, so the shape check accepted only
  the one shape the renderer silently discards (``maskCache = null``, no error) and
  rejected the one that actually renders. On a 4096x4096 tiled plot neither a
  1024x1024 nor a 4096x4096 mask could be drawn: the first raised ``ValueError``,
  the second encoded 22.4 MB the renderer dropped. Both shapes are now accepted and
  a full-resolution mask is reduced to the overview grid with a block ANY -- never
  a subsample, so an object a few pixels across cannot vanish into a skipped
  sample.


0.7.1 (2026-08-02)
==================

Bug Fixes
---------

- Fixed ``save_html`` / ``to_html`` / ``figure_state`` dropping image pixels
  under the Electron binary transport: the snapshot kept the ``"\x00bin:"``
  change-tokens whose bytes only ever ride the live PLOTBIN channel, so an
  overlay added with :meth:`~anyplotlib.Plot2D.add_layer` did not render in the
  exported document. (`#52 <https://github.com/CSSFrancis/anyplotlib/pull/52>`_)


Documentation
-------------

- Fixed the documentation build failing on
  :class:`~anyplotlib.keys.KeyOverlay`, whose ``id`` and ``name`` were described
  both in the class docstring and by the properties themselves — a duplicate
  object description, which the build treats as an error. (`#53 <https://github.com/CSSFrancis/anyplotlib/pull/53>`_)


0.7.0 (2026-07-31)
==================

New Features
------------

- Added :meth:`~anyplotlib.Plot2D.add_key` for pinning a floating image *key* over
  a panel — an inverse pole figure triangle over an orientation map, a hue wheel
  over a polarization field, a phase key over a segmentation.  A key is the scale
  bar's sibling: it floats in screen space and neither pans nor zooms with the
  data, it takes an RGBA image so a triangle or a disc needs no rectangular card
  around it, and ``labels=`` annotates the picture itself (an IPF triangle's
  corner indices) in fractions of the key image.  Optional ``bgcolor`` /
  ``border`` / ``alpha`` give it a card when the data underneath is busy, and
  ``hover_only=True`` reveals it only while the pointer is over the panel.
  Available on every panel type, and included in PNG export.


0.6.0 (2026-07-31)
==================

API and Behaviour Changes
-------------------------

- **3-D orbit drags have reversed direction.**  Both azimuth and elevation now
  move the geometry *with* the cursor instead of away from it, matching
  matplotlib's ``mplot3d`` and every other turntable control — dragging right
  spins a globe right.  Azimuth and elevation position the *camera*, so adding
  the drag delta swept the surface the opposite way, as if you had grabbed its
  far side.  Any muscle memory (or scripted pointer drag) built against the old
  direction is inverted; panels driven from Python with
  :meth:`~anyplotlib.Plot3D.set_view` are unaffected.


New Features
------------

- :class:`~anyplotlib.Event` now carries ``azimuth`` and ``elevation`` for 3-D
  orbit events. The renderer had always emitted them alongside ``zoom``, but they
  were dropped on the way to Python — and since a JS-side drag does not sync back
  into ``Plot3D._state``, a handler had no way to react to an orbit at all. See
  the new ``Star Globe Explorer`` gallery example, which links a celestial sphere
  to a sky map through them.
- Added :meth:`~anyplotlib.Plot2D.add_brush_widget` for painting freehand
  multi-class label strokes on a 2-D image with Shift-drag, leaving a bare drag to
  pan as before.
- Added :meth:`~anyplotlib.Plot3D.set_texture` for wrapping an image around a 3-D
  surface — a globe, a planet, or a star chart on the celestial sphere — with
  optional diffuse shading and backface culling.  ``Axes.plot_surface`` gained
  ``texture=``, ``bounds=``, and ``gpu=`` to match.  Textured surfaces render on
  WebGPU when it is available (roughly 9k triangles at 54 ms/frame on Canvas2D
  versus 0.4 ms on the GPU), falling back to Canvas2D silently otherwise.
  ``set_axis_off()`` now also hides a 3-D panel's axis lines, labels, and ticks.


Bug Fixes
---------

- Fixed WebGPU 3-D geometry being clipped at the corners of a cube-shaped
  dataset.  The clip-space depth scale let ``clip.z`` reach 1.09 for a point at
  the far corner of the normalised bounds box, outside the ``[0, 1]`` range
  WebGPU keeps, so the nearest corner of a dense :meth:`~anyplotlib.Axes.scatter3d`
  cloud silently vanished at the default camera angles.  Spherical geometry was
  never affected.
- Fixed an inverted depth comparison in the WebGPU 3-D projection: a GPU-rendered
  :meth:`~anyplotlib.Axes.scatter3d` cloud drew its far points on top of its near
  ones wherever two points overlapped on screen.  Voxel panels were unaffected
  (they disable depth writes), and the Canvas2D path was always correct.
- Fixed the docs deployment racing itself on release. A push to ``main`` and its
  release tag are different refs, so the ``docs-${{ github.ref }}`` concurrency
  group put them in separate groups and both pushed to ``gh-pages`` at once; the
  loser was rejected and its versioned directory never appeared, while
  ``switcher.json`` still advertised the version. The deploy job now uses a
  ref-independent group so deployments queue instead.


0.5.0 (2026-07-26)
==================

New Features
------------

- :meth:`Widget.set` takes ``_notify=False`` to move a widget without firing
  ``pointer_move`` callbacks, so a handler that writes back to its own widget no
  longer feeds into itself.  Widgets also gained a
  :meth:`~anyplotlib.widgets.Widget.remove` method.
- :meth:`~anyplotlib.Plot1D.add_range_widget` takes ``orientation="vertical"``
  for a band that selects a range of values, and ``snap_values`` to restrict a
  drag to a set of allowed positions (matplotlib's
  ``SpanSelector.snap_values``).  ``snap_values`` is also available on the
  vline, hline and point widgets.
- Added :meth:`~anyplotlib.Plot2D.set_scalebar_style` to recolour the automatic
  scale bar, which was hardcoded white on a translucent dark pill and unreadable
  over a light image.  ``bgcolor="none"`` drops the pill entirely.
- Added ``linestyle="none"`` (also spelled ``"None"``) for a series drawn as
  markers with no connecting line — matplotlib's scatter idiom,
  ``ax.plot(y, linestyle="none", marker="o")``.  An explicit ``linewidth=0``
  now means the same thing; it previously fell back to the 1.5 default in the
  renderer.
- Added three 2-D overlay widget kinds: ``line``
  (:meth:`~anyplotlib.Plot2D.add_line_widget`), a bare two-endpoint segment for
  line profiles and two-point measurements, and ``vline`` / ``hline``, full-height
  and full-width rules grabbable anywhere along their length.
- Clicking a 1-D panel now emits a ``pointer_down`` event carrying the clicked
  position as ``xdata``/``ydata``, matching 2-D panels; it previously fired only
  when the click landed on a line.  Clicks on a line still report ``line_id``,
  so existing line-click handlers are unaffected.
- Panels expose their geometry through :meth:`~anyplotlib.Plot1D.plot_box`,
  :meth:`~anyplotlib.Plot1D.data_to_display` and
  :meth:`~anyplotlib.Plot1D.display_to_data`, so callers working in display space
  no longer have to re-derive the renderer's layout constants and letterbox maths
  themselves.
- Sized marker types take ``size_units="px"`` so their radii and widths stay
  fixed in screen pixels through a zoom instead of scaling with the data — what
  a marker standing in for a *point* wants, and what matplotlib does by sizing
  scatter markers in display points.
- ``edgecolors`` and ``facecolors`` accept a sequence of colours parallel to the
  markers — matplotlib's ``edgecolors=[...]`` / scatter ``c=[...]`` — for every
  marker type on both 1-D and 2-D panels, where previously only ``points`` and
  ``polygons`` on 1-D panels honoured it.  A short sequence cycles.


Bug Fixes
---------

- A ``crosshair`` widget can now be grabbed anywhere along either of its rules
  rather than only at the one-pixel centre hotspot; grabbing a rule constrains
  the drag to that rule's own axis.
- The 1-D y-axis label is no longer drawn through the tick numbers; its position
  was a fixed fraction of the left gutter and is now measured against the widest
  tick string.
- The colorbar strip is no longer drawn flush against the image: there is now a
  6 px gap, taken out of the image width so the strip cannot be pushed off the
  panel, and settable with :meth:`~anyplotlib.Plot2D.set_colorbar_pad`.  This
  shifts every colorbar plot by 4 px.
- ``save_html`` / ``to_html`` / ``figure_state`` now capture overlay widgets at
  their current positions; widget moves reach JS as targeted events that never
  rewrite the panel traits, so a snapshot used to show every widget where it was
  created.


0.4.1 (2026-07-26)
==================

New Features
------------

- Added ``max_extent=`` to :class:`~anyplotlib.widgets.RangeWidget` and
  :class:`~anyplotlib.widgets.RectangleWidget` (and the matching
  ``add_range_widget`` / ``add_rectangle_widget`` factories) — a size cap enforced
  *while dragging*, so the widget physically stops growing instead of being
  clamped after the fact. The dragged edge/corner pins and the opposite one stays
  put, so the selection never jumps under the cursor. ``RangeWidget`` takes a span
  width in data units; ``RectangleWidget`` takes a scalar (both axes) or a
  ``(max_w, max_h)`` pair. Default ``None`` leaves widgets unbounded.

  Use it when a widget's size drives real downstream work — e.g. an integrating
  selector whose span is a number of frames to read.


Bug Fixes
---------

- Fixed the band-style :class:`~anyplotlib.widgets.RangeWidget` being impossible
  to drag by its body when narrow. Each edge claimed a fixed ±12 px grab zone, so
  a band under ~24 px wide on screen (routine when zoomed out, or when its span is
  capped) had no grabbable middle: aiming at the body to translate the band caught
  an edge and resized it instead. Each edge now takes at most a third of the
  band's width, leaving the middle third for the move handle. Wide bands are
  unaffected.


0.4.0 (2026-07-18)
==================

New Features
------------

- Added :meth:`~anyplotlib.axes.InsetAxes.indicate_point` — the point sibling of
  :meth:`~anyplotlib.axes.InsetAxes.indicate_region`: a circle-and-cross marker
  at a data point of the parent plot plus a single leader line to the inset's
  nearest corner, tracking zoom/pan and hiding the leader while minimized.
- Added :meth:`~anyplotlib.plot1d.Plot1D.set_legend_fontsize` to control the
  legend text size on 1-D line plots.
- Added ``linewidth=`` to every overlay widget constructor and ``add_*_widget``
  factory on :class:`~anyplotlib.plot2d.Plot2D` and
  :class:`~anyplotlib.plot1d.Plot1D` (rectangle, circle, annular, crosshair,
  polygon, vline, hline, range, point) — stroke width in px, default 2, stored
  and round-tripped like ``color``.
- Added ``tint=`` to :meth:`~anyplotlib.plot2d.Plot2D.add_layer` and
  :meth:`~anyplotlib.plot2d.Layer.set` — a ``#rgb``/``#rrggbb`` hex colour that
  renders the layer as a clear→colour intensity ramp (transparent at low
  intensity, opaque tint at high, via a 256×4 RGBA LUT) instead of a named
  colormap; passing ``cmap=`` reverts a tinted layer to colormap display.
- An :meth:`~anyplotlib.figure.Figure.add_inset` with no title (the default,
  ``title=""``) now renders with NO title-bar strip at all — a clean bordered
  plot box, content filling the whole area, instead of a useless empty header.
  A titled inset is unchanged: its bar renders as before, with click-to-toggle
  minimize. A title-less inset has no minimize affordance (there is no bar to
  click), but drag-to-move / drag-to-resize in edit mode still work exactly as
  before, since those gestures are wired on the inset body, not the bar.
- Double-clicking a plot's text chrome now reports which element was hit. The
  ``double_click`` :class:`~anyplotlib.callbacks.Event` gains a ``target`` field
  naming the hit element — one of ``'title'``, ``'x_label'``, ``'x_ticks'``,
  ``'y_label'``, ``'y_ticks'``, ``'colorbar_label'`` or ``'legend'`` — so a host
  can open the right edit affordance for the axis label vs the ticks vs the title
  vs the colorbar label vs the legend. The axis gutters, colorbar strip and title
  band each get their own hit-test (2-D panels emit from the separate axis/title
  canvases; 1-D panels zone-split the single canvas around the plot rect and
  legend box). A plain plot-area double-click is unchanged and carries no
  ``target`` (``event.target is None``), so existing handlers keep working.
- Insets can now be dragged and resized directly in the renderer's edit mode
  (``edit_chrome``): drag the body to move an inset (a corner-stacked inset
  converts to a free anchor and its siblings re-stack), or drag the bottom-right
  grip to resize it (min 64 px per dimension). On release the renderer emits a
  new figure-level ``inset_geometry_change`` event carrying the final
  ``anchor``/``w_frac``/``h_frac`` (figure fractions), which
  :meth:`~anyplotlib.figure.Figure.add_event_handler` handlers can observe to
  persist the layout. The same geometry is applied programmatically via the new
  :meth:`~anyplotlib.axes.InsetAxes.set_geometry` (``anchor``, ``w_frac``,
  ``h_frac``). Off edit mode the affordances are hidden and the inset is inert.


Bug Fixes
---------

- Fixed ``exportPNG`` compositing WebGPU-rendered 3-D panels (``scatter3d`` /
  ``voxels``) as blank background rectangles — the 3-D render pass is now
  re-rendered synchronously in-task before the canvas readback, exactly like
  active-GPU 2-D image panels.


0.3.0b1 (2026-07-13)
====================

New Features
------------

- Added :class:`~anyplotlib.widgets.ArrowWidget` (draggable arrow overlay, tail
  at ``(x, y)`` and head at ``(x + u, y + v)``) via ``Plot2D.add_arrow_widget`` /
  ``add_widget("arrow")``, and a ``show_handles`` option (default ``True``) on
  every 2-D overlay widget to hide the grab-handle dots without affecting drag.
- Added figure-level edit-mode chrome to :class:`~anyplotlib.Figure`: the
  ``edit_chrome`` and ``selected_panel`` traits (per-panel hover / selection
  outlines), figure-background click events, and a figure-level annotation layer
  (``set_figure_markers`` / ``figure_markers``, positioned in figure fractions and
  always included in ``exportPNG``) with figure-level callbacks via
  ``add_event_handler``.
- Extended :class:`~anyplotlib.Figure` edit-mode interaction:

  * Circle and rectangle overlay widgets are now **resizable via visible nodes** —
    a circle draws a centre (move) node and an east-point radius node; a rectangle
    draws all four corner nodes (opposite corner anchored on drag).  Drawn only
    when ``show_handles`` is ``True``, with matching resize cursors.
  * :class:`~anyplotlib.widgets.ArrowWidget` **tail is now a reshape node**:
    dragging the tail moves it while the head stays anchored (dragging the shaft
    still moves the whole arrow; the head node still re-aims it).
  * The selected-panel and hover **outlines are fully inset** (``outline-offset:
    -2px``) so an edge/corner panel's ring is no longer clipped at the figure's
    right/bottom edge.
  * **Panel drag-swap** under ``edit_chrome``: each grid panel shows a move grip
    in its top-left corner; dragging it over a *different* panel emits a
    figure-level ``pointer_up`` event with ``panel_swap: true`` and
    ``source_panel_id`` / ``target_panel_id`` (new :class:`~anyplotlib.Event`
    fields).  anyplotlib performs no layout change itself — the host swaps and
    rebuilds.  Releasing on the source panel or empty space cancels cleanly; the
    grip is inert when ``edit_chrome`` is off.
  * The JS ``mount()`` embedding entry point accepts an ``onResize({width,
    height})`` callback, fired (debounced) when the **root container resizes**, so
    an embedding host can relayout the figure to its new box.


0.2.0 (2026-07-10)
==================

New Features
------------

- 2-D scalar images can now render on the **GPU via WebGPU** (``imshow(...,
  gpu="auto"|True|False)``): the image uploads as an R8 texture and a WGSL fragment
  shader applies the colormap LUT + contrast (clim) in one draw, replacing the
  per-pixel JavaScript colormap loop. Large images (≳1 megapixel) take the GPU path
  automatically; everything below the threshold, RGB images, ``gpu=False``, and any
  device without WebGPU keep the identical Canvas2D path. ``plot.gpu_active`` reports
  which path ran. Verified on an NVIDIA Pascal GPU.
- Arbitrarily large images can now display through **tile mode**
  (``imshow(..., tile="auto")``): the figure shows a downsampled overview as its
  base and, after each zoom/pan settles, samples a high-resolution detail tile of
  just the visible region at panel resolution — deep zooms stay crisp without
  ever shipping the full-resolution frame. ``Plot2D.enable_tile`` /
  ``update_tile_source`` swap the underlying frame while the zoom and
  subselection persist (live-data contract), and a pluggable ``TileBackend``
  (default: a fast vectorised numpy box-mean) lets out-of-core or GPU sources
  own the sampling.
- Markers gained a ``clip_display`` option controlling whether they draw
  outside the current axes view or are clipped to it.
- ``set_extent`` now updates the axes state (calibrated units / scale bar), so
  applying a calibrated extent after figure creation renders labelled axes
  instead of bare pixels.
- Regular ``pcolormesh`` meshes are detected and rasterized to an image for
  display (fast IPF-style heatmaps) instead of drawing per-quad.


Bug Fixes
---------

- Fixed a display freeze under the Electron binary pixel transport: the routing
  layer stripped the pixel key out of the slimmed geom JSON, so the renderer's
  "unchanged → skip re-upload" caches (Canvas2D blit cache, WebGPU texture,
  overlay-mask cache) fell back to a 4-sampled-byte fingerprint of the buffer —
  two frames differing anywhere else collided and the display stayed frozen on
  the old frame (seen as a stale overview after a movie scrub). The slimmed geom
  now carries a small ``\x00bin:<checksum>`` content token under the pixel key,
  binary buffers are additionally stamped with an arrival sequence as a fallback
  key, and the overlay-mask draw path now reads the binary byte side-channel
  (it previously only decoded base64, so masks never displayed over the binary
  transport).
- Fixed the WebGPU 2-D image path sampling a vertically MIRRORED window when the
  view was panned off-centre: the shader applied a global ``1 - v`` flip after
  interpolating the ``[v0, v1]`` uv window, which sampled ``[1-v1, 1-v0]``
  instead — correct only for a full or vertically-centred view. Symptoms: pan-y
  moved the image the wrong way on GPU-rendered panels, and markers/widgets
  (drawn by the shared Canvas2D overlay transform, which was always correct)
  appeared detached from the image features they marked. The base and
  detail-tile passes share the shader, so both are fixed. GPU-vs-CPU screenshot
  parity tests (zoom, pan, markers, widgets, detail tile) now run on real WebGPU
  in headless Chromium (``channel="chromium"`` + ``--enable-unsafe-webgpu``) and
  skip on machines with no adapter.
- ``Plot2D.set_data`` no longer makes a float64 copy of every incoming frame.
  The float64 cast now happens lazily in the ``.data`` property (the only reader),
  so a frame stream — e.g. scrubbing an in-situ movie — keeps the source dtype and
  skips a ~12 ms float64 copy of a 4k frame per tick. ``.data`` still returns a
  read-only float64 copy, unchanged for callers.
- The Electron binary pixel transport now ships the RAW uint8 image bytes end to
  end, instead of base64-encoding them in ``set_data`` only to base64-decode them
  straight back in the routing layer. ``Plot2D.set_data`` stashes the raw bytes on
  the Figure's ``_raw_pixels`` side-table and leaves a tiny content-checksum
  change-token in ``image_b64``; ``_electron._route_change`` ships those bytes to a
  PLOTBIN frame directly. This removes the ~20 ms base64 encode, the ~17 ms decode,
  and the megabyte ``json.dumps`` of the pixel string from every scrub frame — a
  2.2x faster ``set_data`` (≈98 ms → ≈44 ms on a 2048² frame) and ~25% less
  bytes-on-wire. Non-Electron hosts (Jupyter / Pyodide / standalone / ``save_html``)
  are unchanged: they have no PLOTBIN channel, so the token is resolved back to
  inline base64 via ``Plot2D.resolve_pixel_tokens`` when the figure state is
  serialised for them.
- Tile mode: a data update while zoomed in (``update_tile_source`` with a detail
  tile shown) refreshes only the detail tile, leaving the overview base on the
  old frame — zooming out then flashed the pre-update frame. The skipped
  overview is now marked stale and re-sampled once on the next view settle
  (riding the same push as the detail/clear), preserving the per-frame skip
  optimisation while never exposing stale base pixels.
- Interactive zoom/pan on a 2-D image no longer re-serialises (and re-transmits)
  the full image on every mouse tick. The wheel/pan/orbit handlers write only the
  light *view* state back to the ``panel_<id>_json`` trait now, excluding the
  cached geometry (pixels, colormap LUT) that ``_applyGeom`` splices into the panel
  state for drawing. Previously the whole frame was ``JSON.stringify``-d per tick —
  catastrophically so on the binary transport, where the pixel buffer is a
  ``Uint8Array`` that stringifies to a ``{"0":..,"1":..}`` object with one key per
  byte — which stalled zoom on large images.
- Fixed a first-paint race under the Electron binary transport: binary
  side-table bytes that arrived before ``render()`` attached its listeners were
  stranded, leaving the first frame blank until the next update — they are now
  spliced into the initial paint.


Maintenance
-----------

- ``anyplotlib.__version__`` is now exposed from the package metadata.
- Per-frame hot-path costs trimmed: the colormap LUT is cached instead of being
  rebuilt every frame (~100 ms), and small-range data rescales in float32
  (~60 ms → ~27 ms per 2048² frame).


0.1.0 (2026-06-24)
==================

Initial release. Provides ``Figure``, ``Axes``, ``GridSpec``, ``subplots``,
``Plot1D``, ``Plot2D``, ``PlotMesh``, ``Plot3D``, ``PlotBar`` and ``PlotXY``, a
full marker system, interactive overlay widgets, and a two-tier callback
registry, plus the additions below.

New Features
------------

- Added :class:`~anyplotlib.InsetAxes` — floating overlay sub-plots that sit
  above the main figure grid, created via :meth:`~anyplotlib.Figure.add_inset`
  and supporting all plot types (:meth:`~anyplotlib.Axes.imshow`,
  :meth:`~anyplotlib.Axes.plot`, :meth:`~anyplotlib.Axes.pcolormesh`, etc.)
  as well as interactive minimise, maximise, and restore states. (`#6 <https://github.com/CSSFrancis/anyplotlib/pull/6>`_)
- Added ``anyplotlib.sphinx_anywidget`` Sphinx extension for interactive,
  Pyodide-powered figures in documentation (``.. anywidget-figure::`` directive,
  automatic wheel building, Sphinx Gallery integration), plus several supporting
  improvements (`#9 <https://github.com/CSSFrancis/anyplotlib/pull/9>`_):

  * Improved widget–parent page postMessage communication bridge.
  * Made colormap LUT construction more robust against unknown colormap names.
  * Subplot panels now use deterministic IDs.
  * Added an end-to-end test for the Playwright thumbnail scraper.
- 3-D ``scatter3d`` and ``voxels`` now render on the GPU via WebGPU when
  available, as a transparent progressive enhancement: a ``gpu="auto"`` kwarg
  (default) uses instanced WebGPU rendering above ~20k points / ~8k voxels and
  falls back to Canvas2D otherwise or whenever a GPU is unavailable (no
  ``navigator.gpu``, null adapter, or device loss) — query the actual path via
  ``plot.gpu_active``.  Voxel slice emphasis and per-face shading are GPU
  uniforms, so dragging a ``PlaneWidget`` re-renders without re-uploading
  geometry.  Decorations (axes, labels, sphere, planes, highlight) always
  render on the 2-D canvas, so visuals are identical to the fallback.  No new
  JavaScript dependencies (raw WebGPU + inline WGSL).
- :meth:`PlotXY.pcolormesh` now renders a **regular, uniformly spaced scalar
  mesh** as a single stretched RGBA raster instead of one polygon per cell — the
  fast path for dense orientation-density / IPF heatmaps. Irregular meshes,
  colour-string ``c``, or an explicit ``edgecolor`` keep the per-cell polygon
  path. The win is twofold: the image is encoded once and travels on the deduped
  geometry channel (a view-only pan/zoom never re-transmits it), and the renderer
  blits it in a single ``drawImage`` whose cost is independent of cell count —
  so a 256×256 heatmap draws as fast as a 32×32 one.

  The underlying primitive is exposed directly as :meth:`PlotXY.add_raster`
  (also on :class:`Plot1D`): an RGBA image drawn between data-coordinate
  ``extent`` corners, with an optional ``clip_path`` polygon (e.g. the curved
  fundamental-sector boundary). Image bytes ride the geometry channel
  (``Plot1D._GEOM_KEYS``) and the decoded bitmap is cached on the marker set.
  Pass ``smooth=True`` (on either ``add_raster`` or ``pcolormesh``) to bilinearly
  interpolate the raster for a continuous heat field; the default keeps crisp
  nearest-neighbour cells.

  New example ``Examples/Interactive/plot_ipf_density_map.py`` — a linked IPF
  orientation map + density heat map where the modal (peak-density) bin is the
  "best-fit" orientation, ringed on the IPF and highlighted on the map.
- Added :meth:`Axes.axes2d` / :class:`PlotXY` — a blank **data-coordinate
  2-D axis** (matplotlib ``transData`` + ``PathCollection`` model). Set
  ``xlim``/``ylim`` (+ ``aspect="equal"``) and draw ``scatter``/``plot``/``fill``/
  ``text`` as collection-style artists in data coords — the surface needed for
  stereographic / IPF / pole-figure plots (e.g. an orix plotting backend).
  ``scatter(c=[...])`` honours per-point face/edge colours, and ``aspect="equal"``
  applies matplotlib's ``apply_aspect`` in the renderer (the panel box is shrunk
  and centred so one data unit spans equal pixels on x and y).
  :meth:`PlotXY.pcolormesh` draws a data-coord quad mesh (per-cell colours via a
  polygon ``PathCollection``); masked / non-finite cells are skipped, so an
  ``orix`` pole-density histogram renders natively as an IPF density heatmap. A
  marker group (and ``pcolormesh``) accepts a ``clip_path`` — a data-coord polygon
  the group is clipped to (matplotlib ``set_clip_path``), e.g. the curved sector
  boundary so the mesh's edge cells don't overflow it.
- Axis labels, titles, and colorbar labels now accept a ``fontsize`` keyword
  (``set_xlabel("...", fontsize=14)``), and a new ``set_tick_label_size()``
  controls tick-number size. Label strings support a mini-TeX subset inside
  ``$...$`` — superscripts (``$10^{-3}$``), subscripts (``$E_F$``), Greek
  letters, and common symbols (``\times``, ``\AA``, ``\degree``) — rendered
  natively on the canvas. Logarithmic tick labels now draw true superscripts.

  Text is never clipped: the 2D title strip grows to fit large or TeX titles,
  the colorbar (strip + label) now reserves real layout space instead of
  overflowing the panel edge, rotated y-labels stay inside their gutter at any
  size, and edge tick labels are nudged inward rather than cut off.
- Heavy plot geometry now travels on a separate sync channel and is
  re-transmitted only when it actually changes.  ``Plot2D`` and ``Plot3D``
  panels split their large, slow-changing state (vertex/face/image buffers,
  per-point colours, colormap LUTs) into a ``panel_<id>_geom`` trait keyed by
  a content hash; the light view payload references it by revision and the JS
  renderer splices the cached geometry back in.  Consequently view-only
  updates — ``set_highlight``, ``set_view``, ``set_zoom``, plane-widget drags,
  titles — no longer re-send the panel's geometry.  Combined with
  ``Figure.batch()`` coalescing, the voxel grain explorer's per-crosshair
  wire traffic drops ~65% (1155 -> 400 KB/frame at 192-cubed), the main
  source of Pyodide lag.  Plots that declare no geometry keys (e.g. ``Plot1D``)
  keep the prior single-trait behaviour unchanged.
- New ``Axes.voxels()`` 3-D geometry renders volumes as shaded translucent
  cubes (per-voxel colours, global ``alpha``), and 3-D panels gained their
  first interactive widget: ``add_widget("plane", axis=..., position=...)``
  adds a draggable :class:`PlaneWidget` slice selector — drag it along its
  normal in the browser and ``pointer_move``/``pointer_up`` callbacks fire in
  Python.  Voxels lying on a plane render more opaque
  (``voxel_slice_alpha``), so selected slices glow inside the volume.  The
  voxel grain explorer example now uses all of this: three plane widgets
  bidirectionally linked with three orthoslice crosshairs and the 3-D IPF.
- Plots are now usable on touch devices (iPad / iPhone) and trackpads.  A touch
  bridge in the renderer translates gestures into the existing interaction
  handlers, so every panel type and every example becomes touch-capable with no
  API change: one-finger drag pans / orbits / moves a widget, ROI, marker or
  slice plane (whatever is under the finger); two-finger pinch zooms; and
  double-tap fires the panel's ``double_click`` event.  Overlay canvases set
  ``touch-action: none`` so the browser hands gestures to the plot instead of
  scrolling the page.
- The ``double_click`` event on a 1-D / :class:`PlotXY` panel now reports
  ``ydata`` alongside ``xdata`` (data coordinates), matching the 2-D image path —
  so a coordinate axis can be picked in data space (e.g. an IPF / pole-figure mask).
- Voxel rendering is ~2–3× faster: cubes render once per (colour, emphasis)
  into sprites and are blitted per voxel with typed-array projection and
  integer-snapped draws; camera-static redraws (plane-widget drags) reuse a
  cached projection/depth-sort.  3-D interaction no longer double-draws —
  self-originated model writes skip the panel-listener echo.  New voxel
  benchmarks (``test_bench_voxels_orbit`` / ``_reblit``) guard the budget
  (~3–6 µs/cube), and ``voxels()`` warns above ~20k cubes with downsampling
  guidance for large volumes (e.g. 512×512×300 tomograms).  Local docs builds
  now rebuild the Pyodide wheel when sources are newer, so the ⚡ interactive
  mode never runs stale code.
- ``Figure.batch()`` coalesces panel pushes: every plot mutation inside the
  ``with fig.batch():`` block is serialised and transferred at most once per
  panel when the block exits, instead of once per mutation.  Linked-view
  handlers (e.g. the voxel grain explorer's crosshairs, which touch 5 panels
  per mouse event) drop from ~8 full-state pushes per frame to one per changed
  panel — a large reduction in comm traffic that removes most of the lag under
  Pyodide and remote kernels.  ``set_highlight`` / ``set_view`` / ``set_zoom``
  on 3-D panels now route through this coalescing path so re-aiming the camera
  or moving the highlight never re-transmits the panel's (potentially hundreds
  of KB) unchanged geometry.  RGB ``imshow`` updates also skip the unused
  colormap-LUT rebuild.
- ``imshow`` now renders ``(H, W, 3|4)`` arrays as true-colour RGB(A) images
  (previously the extra channels were silently dropped).  ``scatter3d`` gained
  per-point ``colors=`` and a ``bounds=`` override for origin-true geometry
  (e.g. unit vectors on a sphere), ``Plot3D.set_highlight()`` marks a
  single emphasised point, and ``Plot3D.set_sphere()`` draws a shaded,
  wireframed reference sphere behind the data (far-side points dimmed).  The 3-D camera is now a proper turntable
  (matplotlib ``azim``/``elev`` semantics — azimuth spins about the data
  z-axis): the previous camera could not aim at arbitrary directions, which
  blocked rotate-to-face interactions.  A new gallery example,
  *Inverse Pole Figure (IPF) Explorer*, combines all of these: an IPF-RGB
  orientation map whose crosshair rotates a reduced 3-D IPF sphere to face
  the selected grain's crystal direction.
- anyplotlib figures can now be embedded outside Jupyter — e.g. in Electron
  apps, MDI sub-windows, or plain web pages — with no anywidget runtime.
  ``fig.save_html()`` / ``fig.to_html()`` export a self-contained interactive
  page; ``figure_esm.js`` now exports a ``mount(el, state, opts)`` entry point
  for direct JS embedding (with ``onEvent`` interaction callbacks, live
  ``setPanelState`` updates, ``resize``, and ``dispose``); and the new
  ``anyplotlib.embed`` module provides ``figure_state()``, ``esm_path()``, and
  a transport-agnostic ``FigureBridge`` for live two-way Python sync over any
  pipe (WebSocket, IPC, stdio) with full event-callback support.


Bug Fixes
---------

- Fixed 3-D plane-widget drags snapping back instead of moving smoothly.
  ``Plot3D.to_state_dict()`` now always serialises the live overlay widgets, so
  a view-only push on the same panel (``set_highlight`` / ``set_view``) no
  longer re-sends a stale plane position and clobbers an in-progress drag.  The
  voxel grain explorer also tracks smooth (float) positions for the highlight
  marker so it glides with the planes instead of jumping by whole voxels.
- Fixed a 3-D GPU panel breaking — voxels and axes both vanishing after
  rendering correctly — when the WebGPU device throws mid-draw or is lost,
  as Safari's experimental WebGPU does after working for a while.  The GPU
  path makes the decoration ``plotCanvas`` transparent and takes GPU-only
  branches, so a mid-draw failure left the frame half-built and only a window
  resize (which forces a full redraw) restored it.  The fallback now disposes
  the GPU panel, restores the opaque background, and re-renders the whole panel
  once on the Canvas2D path in the same frame, so it self-heals without a
  resize.
- Fixed large voxel volumes (e.g. a 256³ grain explorer) rendering "empty" —
  only the plane widgets and highlight marker visible, with no cubes — in
  WebGPU-enabled browsers such as PyCharm's embedded JCEF.  The WebGPU voxel
  path draws cubes on a ``gpuCanvas`` beneath the ``plotCanvas`` that carries
  the axes/planes/highlight; activating the GPU path cleared the plotCanvas
  bitmap but left its opaque CSS ``background``, so the element painted over
  every GPU-drawn voxel.  The plotCanvas background is now set transparent
  while the GPU path is active (and restored on fallback / device loss).  The
  voxel shader itself was verified correct on real hardware (NVIDIA TITAN X via
  native wgpu).  The GPU geometry cache also keys on ``point_colors_b64`` now,
  so ``set_point_colors`` recolours voxels live.
- Fixed the 3-D voxel highlight appearing to "float" or land on random voxels
  in large grain volumes.  ``Plot3D.set_point_colors`` now accepts ``voxels``
  panels (not just ``scatter``), so the orthoslice explorer can re-colour voxels
  live.  The voxel grain explorer now renders the voxels that lie *on* the three
  slice planes (instead of a sparse random subsample of the whole volume), so the
  highlight marker is always anchored on a real cube at the slice intersection.
  The on-plane voxel count is ~3·(N/step)² regardless of N, so this stays fast
  even for a 256³ volume.
- Interactive (⚡) documentation figures are much smoother under Pyodide.  Each
  user interaction event was dispatched with ``pyodide.runPythonAsync`` on a
  freshly-built code string, which recompiles Python source every frame
  (~1.2 ms/event in WASM — the dominant per-frame cost on a drag).  The bridge
  now calls a pre-compiled dispatcher proxy directly (~50× faster, ~0.02 ms),
  so panning, orbiting, and dragging widgets / slice planes in the docs keep up
  with the gesture.


Maintenance
-----------

- Refactored the test suite. Moved to a new directory, combined like
  tests into single files, added a couple new tests and removed some redundant tests. (`#11 <https://github.com/CSSFrancis/anyplotlib/pull/11>`_)

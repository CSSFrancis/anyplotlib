=========
Changelog
=========

All notable changes to **anyplotlib** are documented here.

Fragment files in ``upcoming_changes/`` are assembled into this file by
`towncrier <https://towncrier.readthedocs.io/>`_ when a release is prepared
(see ``upcoming_changes/README.rst`` for contributor instructions).

.. towncrier release notes start

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

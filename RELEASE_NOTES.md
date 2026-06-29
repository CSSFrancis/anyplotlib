# anyplotlib 0.1.0 — first public release

**anyplotlib** is a plotting library built on Python, JavaScript, and
[anywidget](https://anywidget.dev/) for fast, interactive, in-browser plotting
— in Jupyter, in the docs, and (new in this release) embedded in standalone apps.

This first release ships the full core: `Figure`, `Axes`, `GridSpec` /
`subplots`, the `Plot1D` / `Plot2D` / `PlotMesh` / `Plot3D` / `PlotBar` /
`PlotXY` plot types, a marker system, interactive overlay widgets, and a
two-tier callback registry.

## Install

```bash
pip install anyplotlib
```

Requires Python ≥ 3.10. Optional extras: `anyplotlib[jupyter]`, `anyplotlib[docs]`.

## Highlights

### New plotting surfaces
- **`PlotXY` / `Axes.axes2d`** — a blank data-coordinate 2-D axis (matplotlib
  `transData` + `PathCollection` model). Draw `scatter` / `plot` / `fill` /
  `text` in data coords with per-point face/edge colours and `aspect="equal"`
  — the surface for stereographic / IPF / pole-figure plots (e.g. an `orix`
  backend).
- **Fast density heatmaps** — `PlotXY.pcolormesh` rasterizes regular meshes into
  a single blit whose cost is independent of cell count (a 256×256 heatmap draws
  as fast as 32×32). The underlying `add_raster` primitive draws an RGBA image
  between data-coord corners, with an optional `clip_path` polygon and a
  `smooth=True` bilinear option.
- **`InsetAxes`** — floating overlay sub-plots above the main grid (`add_inset`),
  supporting every plot type plus interactive minimise / maximise / restore.
- **True-colour `imshow`** — `(H, W, 3|4)` arrays now render as RGB(A) instead of
  silently dropping channels.

### 3-D and GPU
- **`Axes.voxels()`** — volumes as shaded translucent cubes, with a draggable
  `PlaneWidget` slice selector that fires `pointer_move` / `pointer_up`
  callbacks; voxels on the slice plane glow.
- **WebGPU acceleration** — `scatter3d` and `voxels` render on the GPU via WebGPU
  when available (`gpu="auto"`), with a transparent, identical-looking Canvas2D
  fallback when no GPU is present. Query the active path with `plot.gpu_active`.
- **Richer 3-D scatter** — per-point `colors=`, a `bounds=` override, single-point
  `set_highlight()`, a shaded reference `set_sphere()`, and a proper turntable
  camera (matplotlib `azim` / `elev` semantics).

### Interactivity
- **Touch support** — one-finger pan / orbit / drag, two-finger pinch zoom, and
  double-tap, on iPad / iPhone / trackpads, with no API change.
- **Data-coordinate picking** — `double_click` on 1-D / `PlotXY` panels now
  reports `ydata` alongside `xdata`.
- **Typography** — `fontsize` on labels/titles/colorbars, `set_tick_label_size()`,
  and a mini-TeX subset inside `$...$` (super/subscripts, Greek, `\times`, `\AA`,
  `\degree`) rendered natively on the canvas; text is no longer clipped.

### Performance
- **Geometry sync channel** — large, slow-changing buffers are deduped by content
  hash, so view-only updates (highlight, view, zoom, widget drags) no longer
  re-transmit geometry.
- **`Figure.batch()`** — coalesces panel pushes so linked-view handlers send one
  update per changed panel instead of one per mutation.
- **Voxels ~2–3× faster** via sprite caching and cached projection/depth-sort.
- **~50× faster Pyodide dispatch** — interactions call a pre-compiled dispatcher
  instead of recompiling Python source every frame, so the interactive docs keep
  up with gestures.

### Embedding outside Jupyter
- `fig.save_html()` / `fig.to_html()` export a self-contained interactive page.
- `figure_esm.js` exports a `mount(el, state, opts)` entry point for direct JS
  embedding (Electron, MDI windows, plain web pages) with `onEvent` callbacks,
  live `setPanelState`, `resize`, and `dispose`.
- The new `anyplotlib.embed` module provides `figure_state()`, `esm_path()`, and a
  transport-agnostic `FigureBridge` for two-way Python ↔ JS sync over any pipe.

### Documentation tooling
- The `anyplotlib.sphinx_anywidget` extension renders live, Pyodide-powered
  figures in the docs (`.. anywidget-figure::` directive, automatic wheel
  building, Sphinx Gallery integration).

## Bug fixes
- 3-D plane-widget drags no longer snap back (view-only pushes stop clobbering an
  in-progress drag).
- GPU 3-D panels self-heal when a WebGPU device is lost mid-draw (no more vanishing
  voxels/axes until a window resize) — seen on Safari's experimental WebGPU.
- Large voxel volumes no longer render "empty" in WebGPU browsers (e.g. PyCharm's
  JCEF) — the plot canvas background is now transparent while the GPU path is active.
- The 3-D voxel highlight no longer floats onto random voxels in large volumes.
- Interactive (⚡) docs figures are much smoother under Pyodide (the ~50× dispatch
  speedup above).

## Full changelog
See [`CHANGELOG.rst`](./CHANGELOG.rst) for the complete, detailed list.

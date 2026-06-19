# Making anyplotlib a plotting backend for orix

Goal: render orix's IPF / stereographic / pole-figure plots **natively in
anyplotlib** so orix (and SpyDE) can drop matplotlib for them.

## How orix plots today (matplotlib)

orix builds everything on **matplotlib Axes subclasses + registered projections**:

- `orix/plot/stereographic_plot.py` — `StereographicPlot(name="stereographic")`
  subclasses `matplotlib.axes.Axes`. It overrides `plot` / `scatter` / `text` to
  first project spherical → (x, y) via `orix.projections.StereographicProjection`
  (pure numpy, **no matplotlib**), then call `super().plot/scatter/text(x, y, …)`
  in **data coordinates** with `set_aspect("equal")`.
- `inverse_pole_figure_plot.py` — `InversePoleFigurePlot` (subclass of the above)
  draws the fundamental-sector outline + `[hkl]` corner labels.
- `IPFColorKeyTSL.plot()` — fills the sector with colour (scatter / mesh of
  projected directions) on such an axis.

So the orix side that's *not* matplotlib is just the **projection math**
(`vector2xy`); the rendering is plain 2-D matplotlib: `scatter`, `plot`, `text`,
`fill`/patches, in **data coords**, aspect-equal.

## The gap in anyplotlib

anyplotlib's 2-D is **image-centric**. Marker/overlay groups (`add_points`,
`add_lines`, `add_polygons`, `add_texts`, `add_circles`) with `transform="data"`
map offsets through **`_imgFitRect` (image pixels)** — i.e. an offset `(x, y)` is
treated as image column/row, *not* the axis's `x_axis`/`y_axis` data values
(confirmed in `figure_esm.js`: all 2-D coordinate fns derive from `_imgFitRect`;
markers use it, never `st.x_axis`). There is no "blank axis with x/y limits +
data-coord scatter/line/polygon/text" surface — which is exactly what orix needs.

(This is also why the SpyDE IPF-refine triangle is currently a matplotlib raster:
its overlays in stereographic coords collapsed into the image's top-left corner.)

## Staged plan

**Stage 1 — data-coordinate overlays for `Plot2D` (foundation).**
Make marker groups honour the panel's `x_axis`/`y_axis` when present: a
`transform="data"` offset `(x, y)` maps via the axis values → image fraction →
canvas (the matplotlib `imshow(extent=…)` + `scatter` alignment). Smallest change
that (a) unblocks a fully-native IPF triangle over the heatmap imshow and (b)
proves the data→pixel plumbing. Touches `markers.py` (wire) + `figure_esm.js`
(`drawMarkers2d` coord branch). Demo/test: native IPF heatmap triangle.

**Stage 2 — a coordinate-only 2-D axis (no image).**
`ax.set_xlim/ylim` + `set_aspect("equal")` on a panel with **no imshow**, where
`add_points/lines/polygons/texts` live in data coords. This is the general
"matplotlib-Axes-like 2-D" surface orix's `StereographicPlot` draws onto. Likely
a lightweight `Plot2DCoords` (or extend `Plot2D` to allow `data_bounds` without an
image) reusing the Stage-1 transform.

**Stage 3 — orix targets anyplotlib (lives in ORIX, not here).**
The stereographic projection + IPF / pole-figure plotting **belongs in orix** and
already exists there (`StereographicProjection`, `StereographicPlot`,
`IPFColorKeyTSL`). anyplotlib stays domain-agnostic — it must NOT know about
stereographic projections. The integration is an **orix-side** change: refactor
orix's plotting to draw through a backend (matplotlib OR anyplotlib's `axes2d`
surface) — `vector2xy` (orix) → `PlotXY.scatter/plot/fill/text` (anyplotlib).
anyplotlib's only job is to be a complete-enough generic 2-D backend.

## Align with matplotlib's model

matplotlib's data drawing is two ideas we should mirror:

1. **`transData` = a composed transform chain.** `transData = transScale (log/lin)
   + transLimits (data Bbox → unit [0,1] box) + transAxes (unit box → display)`.
   i.e. **data → [0,1] via the axis limits → pixels via the axes rect**.
   `set_aspect("equal")` is `apply_aspect()` — it adjusts the box (and limits) so a
   data unit is the same length on x and y.
   - anyplotlib's **1-D path already does this**: marker offsets are normalised to
     `[0,1]` by the x/y data range, then `_tc2d(fx,fy)=[r.x+fx*r.w, r.y+(1-fy)*r.h]`
     maps the unit box → the panel rect. That's exactly `transLimits` → `transAxes`.
   - So the coordinate axis just needs **explicit `xlim`/`ylim`** as the transData
     domain + an aspect step, reusing the same unit-box→rect mapping.

2. **Scatter is a `Collection` (offsets + per-point props), not N artists.**
   `ax.scatter(x,y,c=,s=)` → one `PathCollection`: an offsets array drawn with a
   shared marker path, per-point colours/sizes. anyplotlib's `MarkerGroup`
   (`add_points`/`add_circles`) is **already this** — offsets + `facecolors`/
   `sizes` arrays. So `ax.scatter` becomes a thin wrapper returning a points
   MarkerGroup positioned via transData; `plot`→a polyline marker group (`Line2D`),
   `fill`/polygons→`add_polygons` (`Polygon`/`PathCollection`), `text`→`add_texts`.

So the coordinate axis = **the 1-D unit-box→rect transform driven by explicit
xlim/ylim (+ aspect), with the existing collection-style markers as the artists** —
semantically the same as matplotlib's `transData` + `PathCollection`.

## API sketch (matplotlib-parity)

```python
ax = fig.add_axes2d()          # blank data-coord axis (no image)
ax.set_xlim(-1, 1); ax.set_ylim(-1, 1); ax.set_aspect("equal")
ax.scatter(xs, ys, c=colors, s=8)     # -> PathCollection-style MarkerGroup
ax.plot(ex, ey, color="w")            # -> Line2D-style polyline
ax.fill(px, py, facecolor="…")        # -> Polygon
ax.text(x, y, r"$[111]$")             # -> Text
```

## Status

**Stage 2 landed:** `Axes.axes2d()` → `PlotXY` (`anyplotlib/plotxy/`). It reuses
the 1-D data→canvas transform (`kind="1d"`, hidden curve) so `scatter`/`plot`/
`fill`/`text` draw as collection markers in **data coords** with no renderer
change. `set_xlim`/`set_ylim`/`set_aspect`. Tests in `tests/test_plotxy/`
(5 pass incl. a chromium render); demo = a native IPF triangle (fill + scatter +
labels in data coords).

**Two renderer gaps the demo exposed — both now CLOSED:**
1. **Per-point scatter colours — DONE.** `drawMarkers1d` `points` now reads
   per-offset `facecolors`/`color` arrays (matplotlib `PathCollection`), so
   `scatter(c=[...])` renders the IPF colour-key gradient.
2. **`aspect="equal"` — DONE.** `_plotRect1d(p)` applies matplotlib
   `apply_aspect`: when `state.aspect==='equal'` it shrinks + centres the panel
   box so one data unit spans equal pixels on x and y. Baked into the shared rect
   helper, so draw / markers / overlay / hit-test all use the identical adjusted
   box (matplotlib's transData derives from the axes box). A wide-panel IPF
   triangle now renders undistorted (`tests/test_plotxy`:
   `test_aspect_equal_renders_square` vs `test_aspect_auto_fills_panel`).

**Then the orix side (in the orix repo, not here):** the stereographic / IPF /
pole-figure plotting STAYS in orix; refactor it to draw through a backend so
`vector2xy` (orix) feeds `PlotXY.scatter/plot/fill/text` (anyplotlib). anyplotlib
stays generic — finishing (1) + (2) makes it a complete-enough backend.

## Recommendation

Built **Stage 2 (chosen): the coordinate-only 2-D axis** as above —
reuse the 1-D `transLimits→transAxes` unit-box transform with explicit xlim/ylim +
aspect, expose `scatter`/`plot`/`fill`/`text` as collection-style artists. Demo =
a native IPF fundamental-sector triangle (filled colour-key + outline + `[hkl]`
labels) drawn purely with these primitives.

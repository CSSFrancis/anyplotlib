# FIGURE_ESM.md — Navigator for `figure_esm.js`

`figure_esm.js` is **~6,000 lines** and one big closure. Everything lives inside
`function render({ model, el })` so that all helpers share the same scope
(`theme`, `PAD_*`, `panels` Map, etc.).  This document is a section map so you
can jump straight to the relevant code without reading the whole file.

> **Keeping this file fresh:** line numbers drift as the JS evolves. The
> section banners are greppable — regenerate the quick-reference with
> `rg -n '^\s*// ──' anyplotlib/figure_esm.js` and function anchors with
> `rg -n '^\s*function \w+' anyplotlib/figure_esm.js`. Update this file
> whenever a PR moves a section by more than ~50 lines.

---

## Sizing contract

```
Rule 1 – Grid tracks are always pure ratio math.
         col_px[i] = fig_width  × width_ratios[i]  / Σ width_ratios
         row_px[r] = fig_height × height_ratios[r] / Σ height_ratios
         No exceptions.  No 2-D special-casing.  Both Python
         (_compute_cell_sizes) and JS (_applyFigResizeDOM) follow this rule.

Rule 2 – All panels in the same grid column have the same canvas width.
         All panels in the same grid row    have the same canvas height.
         (Follows automatically from Rule 1.)

Rule 3 – Images are displayed "contain" (letterbox / pillarbox).
         _imgFitRect(iw, ih, cw, ch) → largest rect of aspect iw:ih
         that fits inside cw×ch, centred.

Rule 4 – Zoom is relative to the fit-rect.
         zoom=1 → fit-rect exactly filled by the whole image.
         zoom=Z → a 1/Z portion of the image fills the fit-rect.

Rule 5 – Text never clips.  Optional gutters earn real layout space:
         the colorbar (strip + label, _cbWidth) is subtracted from the
         image width; the 2D title strip (_padT) grows for large or TeX
         titles; 1D/bar titles clamp their drawn size to the fixed strip
         (_titlePx); edge tick labels are nudged inward.
```

---

## Quick-reference: function anchors

| Section / function | Line |
|--------------------|------|
| Shared plot-area padding (`PAD_*`) | 9 |
| Theme (dark/light detection) | 15 |
| Shared math helpers | 53 |
| b64 array decode helpers | 95 |
| **Rich-text (mini-TeX) engine**: `_texRuns` / `_texLayout` / `_drawTex` | 147 / 214 / 236 |
| **2D gutter geometry**: `_cbWidth` / `_padT` / `_titlePx` | 287 / 299 / 309 |
| **Layout engine** `applyLayout` | 590 |
| `_buildCanvasStack` | 656 |
| `_createPanelDOM` | 763 |
| `_createInsetDOM` / `_applyAllInsetStates` | 846 / 968 |
| `_resizePanelDOM` | 1027 |
| **2D drawing**: `_imgFitRect` | 1176 |
| `draw2d` | 1258 |
| `drawScaleBar2d` / `drawColorbar2d` | 1360 / 1436 |
| `_drawAxes2d` (ticks, labels, title) | 1491 |
| `drawOverlay2d` / `drawMarkers2d` | 1629 / 1685 |
| **Image layers**: `_layerBytes` / `_layerBitmap` / `_drawLayers2d` | 1553 / 1577 / 1629 |
| Binary-bytes splice: `_spliceBinaryBytes` / `_registerBinaryPixelListeners` | 675 / 706 |
| **3D drawing**: `draw3d` | 1833 |
| Event emission `_emitEvent` | 2031 |
| 3D event handlers `_attachEvents3d` | 2059 |
| **1D drawing**: `draw1d` | 2177 |
| `drawOverlay1d` / `drawMarkers1d` | 2516 / 2586 |
| Marker hit-test `_markerHitTest2d` | 2787 |

> **`raster` marker (1D/PlotXY)** — `drawMarkers1d` has a `type==='raster'`
> branch that blits a single RGBA image across data-coord `extent` (the fast
> path for dense `PlotXY.pcolormesh` heatmaps). The image bytes ride the geom
> channel as `st.raster_geom[id]` (Python `Plot1D._GEOM_KEYS`), so view-only
> redraws never re-transmit them; the decoded `OffscreenCanvas` is cached on
> the marker set (`ms._rasterBmp`/`_rasterKey`). The shared `clip_path` block
> clips it to a curved sector.
| Panel event dispatch `_attachPanelEvents` | 2905 |
| 2D events `_attachEvents2d` | 2928 |
| 1D events `_attachEvents1d` | 3201 |
| 2D widget drag `_ovHitTest2d` / `_doDrag2d` | 3409 / 3491 |
| 1D widget drag `_canvasXToFrac1d` … | 3565 |
| Shared-axis propagation `_getShareGroups` | 3650 |
| Figure resize `_applyFigResizeDOM` | 3714 |
| **Bar chart**: `_barGeom` / `drawBar` / `_attachEventsBar` | 3902 / 3965 / 4341 |
| Generic redraw `_redrawPanel` | 4531 |

---

## Rich-text (mini-TeX) label engine

Canvas cannot run MathJax, so labels support a small TeX subset inside
`$...$` delimiters — superscripts/subscripts (`$10^{-3}$`, `$E_F$`), Greek
letters (`\alpha`…`\Omega`), and symbols (`\times`, `\AA`, `\degree`,
`\propto`, …; see `_TEX_SYM`).  `\mathrm{...}` gives upright text; math-mode
letters are italic.  Python stores label strings verbatim — all parsing
happens here at draw time.

| Function | Purpose |
|----------|---------|
| `_texRuns(text)` | Parse a label into runs `[{t, lvl, it}]` — lvl 0/+1/−1, it = italic |
| `_texLayout(ctx, text, px, weight, family)` | Measure runs; sup/sub at 0.68×, dy −0.28/+0.16 em from a shared alphabetic baseline |
| `_drawTex(ctx, text, x, y, px, opts)` | Draw a label.  `opts: {align, weight, family}`.  Fast path (no `$`) is a single `fillText`.  Respects caller's `fillStyle`/`textBaseline`. |

**Baseline conversion gotcha:** `TextMetrics.fontBoundingBoxAscent` is
measured **relative to the current `textBaseline`**, not alphabetic.
`_drawTex` therefore measures the ascent under the caller's baseline AND
under `alphabetic`, and shifts by the difference — this makes TeX text land
at exactly the same height a plain `fillText` would.

**All axis labels, titles, the colorbar label, 3D axis labels, and log tick
labels (`$10^{N}$`) render through `_drawTex`.**  Font sizes come from state
with fallbacks to the historical defaults: `title_size||11`,
`x_label_size`/`y_label_size` (11 for 2D, 9 for 1D units, 10 for bar, 11 for
3D), `tick_size||10`, `colorbar_label_size||10`.

## 2D gutter geometry helpers

| Function | Purpose |
|----------|---------|
| `_cbWidth(st)` | Width reserved for the colorbar: 0 when hidden, else `16 + (label ? label_size+8 : 0)`.  Subtracted from the image width in `_resizePanelDOM` / `_resizePanelCSS` so the strip + label always fit inside the panel. |
| `_padT(st)` | 2D title-strip height: `PAD_T` (12) for default-size plain titles (pixel-identical layouts); grows to `ceil(size*1.3)+2..4` for `title_size > 11` or TeX titles (superscript rise). Stored as `p._padT`. |
| `_titlePx(st)` | Drawn title size for fixed-strip panels (1D/bar): clamps to 11 (10 for TeX titles) so nothing clips. |

`draw2d` calls `_resizePanelDOM` on every state push, so colorbar/title
geometry changes (visibility, label, sizes) re-layout automatically.

---

## Layout / panel details

#### `applyLayout()` (line 590)
Reads `layout_json`. Builds CSS grid tracks from `panel_specs[].panel_width/height`.
Creates panels that don't exist yet, resizes existing ones, removes stale ones.
Also creates/updates inset panels from `inset_specs`, then draws region
indications from `layout.indications` (on the next frame — see below).

#### Inset placement (`_applyAllInsetStates`)
Each `inset_specs[]` entry carries EITHER `corner` (one of the four corners;
`anchor` is `null`) OR `anchor` (`[x_frac, y_frac]` of the inset's top-left in
figure fraction; `corner` is `null`). Corner insets stack per-corner with
`INSET_GAP`; anchored insets are placed directly at their fraction (clamped
inside the figure). Minimize / maximize / restore work for both — a maximized
inset floats centred at ~72 % (z 45); a minimized one collapses to its title
bar in place.

#### Region/point indications (callouts — `_drawCallouts`)
`layout.indications` is an array of mark_inset-style callouts, each
`{inset_id, parent_id, region:[x,y,w,h], color, linestyle, linewidth}` (from
`indicate_region`) or `{inset_id, parent_id, point:[x,y], color, linestyle,
linewidth, marker_size}` (from `indicate_point` — the `point` key selects the
branch). `_drawCallouts()` renders them onto a figure-level `calloutCanvas`
(z 30, above panels + insets, below maximized-inset float and the resize
handle, `pointer-events:none`):
- The **dashed source rect** maps `region` (parent DATA coords) through the
  parent's `_imgToCanvas2d` every draw, so it tracks the parent's zoom/pan; it
  is clipped to the parent's image area.
- Two **leader lines** connect the rect's corners facing the inset to the
  inset's nearest corners (loc1/loc2-auto by comparing centres); they follow
  the inset's live DOM rect and are **hidden while the inset is minimized**.
- A **point indication** draws a solid circle-and-cross marker (radius
  `marker_size`, clipped to the parent image area like the rect) at the mapped
  data point, plus ONE leader from the marker's rim to the inset's nearest
  corner (same minimized-hide rule; the leader uses the indication's
  linestyle, the marker itself is always solid).

`_drawCallouts()` is called at the end of `_redrawPanel` / `redrawAll` (tracks
zoom/pan), at the end of `_applyAllInsetStates` (inset moved), on `applyLayout`
(deferred one rAF so `getBoundingClientRect` is real), and inside `exportPNG`
(forced fresh draw, then `calloutCanvas` composited last). All coordinates go
through element bounding rects relative to the callout canvas, so no layout math
is duplicated. Cheap no-op when `indications` is empty (just clears the canvas).
The `if (!parent || !parent.state || !inset || !inset.isInset) continue;` guard
per indication is defensive/permanent — kept even though a foreign-figure
`parent_plot` can no longer reach this array at all (see validation below); it
still protects against other edge cases (e.g. a panel mid-teardown).

**`InsetAxes.indicate_region(parent_plot, region, …)` validates both arguments**
before recording an indication: `parent_plot` must be a panel registered on
THIS inset's own `Figure` (`self._fig._plots_map.get(pid) is parent_plot` —
not just "has some `_id`", which is the pre-existing check for "never attached
to any figure") — a plot that belongs to a *different* `Figure` raises
`ValueError`. `region` must be exactly 4 finite numbers `(x, y, w, h)` with
`w > 0` and `h > 0` — `NaN`/`inf`, a degenerate/negative size, or the wrong
number of values raises `ValueError`. A region that extends OUTSIDE the
parent's data bounds is explicitly **allowed** (clipping is a visual concern
handled by `_drawCallouts`'s clip-to-image-area, not a validation error). See
`test_indicate_region_foreign_figure_parent_raises`,
`test_indicate_region_foreign_inset_parent_raises`,
`test_indicate_region_degenerate_region_raises`, and
`test_indicate_region_out_of_bounds_is_allowed` in
`tests/test_layouts/test_inset_callout.py`.

**Inset removal**: as of this writing there is no `remove_inset` (or
equivalent) API — `Figure._insets_map` / `_plots_map` are only ever appended
to, never deleted from, so `indications` (rebuilt fresh from `_insets_map` on
every `_push_layout()` call) cannot go stale from a removed inset today. If a
removal API is added later, it MUST also delete the inset's entry from both
maps — otherwise `layout.indications` would keep emitting an entry whose
`inset_id` no longer resolves to a live panel (caught by the `_drawCallouts`
guard above, but a dangling entry all the same).

#### `_createPanelDOM(id, kind, pw, ph, spec)` (line 763)
Builds all canvas/DOM elements for one panel (via `_buildCanvasStack`),
stores the **`p` object** in `panels`, subscribes to
`change:panel_{id}_json`, runs the initial draw.

**DOM structure by kind:**
| kind | elements |
|------|----------|
| `'2d'` | `plotWrap > plotCanvas + overlayCanvas + markersCanvas + yAxisCanvas + xAxisCanvas + cbCanvas + scaleBar + statusBar + titleCanvas` |
| `'3d'` | `wrap3 > plotCanvas + overlayCanvas + markersCanvas + statusBar` |
| `'1d'` / `'bar'` | `wrap > plotCanvas + overlayCanvas + markersCanvas + statusBar` |

#### `_resizePanelDOM(id, pw, ph)` (line 1027)
Updates `canvas.width / canvas.height` (DPR-scaled) for every canvas in the
panel.  For 2D, computes `imgX/imgY/imgW/imgH` from the gutters
(`PAD_*`, `_padT`, `_cbWidth`) and stores them on `p` plus `p._cbW`/`p._padT`.

#### The `p` (panel) object — key fields
```js
p.id, p.kind, p.pw, p.ph
p.state          // parsed JSON from panel_{id}_json (full plot state dict)
p.imgX, p.imgY, p.imgW, p.imgH   // 2D inner image area (gutters removed)
p._cbW, p._padT                  // 2D gutter geometry at last layout
p.plotCanvas/.overlayCanvas/.markersCanvas (+ 2D: x/yAxisCanvas, cbCanvas,
p.titleCanvas, p.scaleBar), p.statusBar
p.blitCache      // { bitmap, bytesKey, lutKey, w, h } — ImageBitmap cache
p.ovDrag / p.ovDrag2d / p.isPanning
```

---

## 2D drawing (from line 1176)

Key state fields:
```
st.image_b64, st.image_width/height
st.zoom, st.center_x/y
st.display_min/max, st.raw_min/max, st.scale_mode
st.colormap_data    [[r,g,b], ...] × 256
st.x_axis, st.y_axis, st.axis_visible
st.markers, st.overlay_widgets, st.overlay_mask_b64/_color/_alpha
st.title_size, st.x_label_size, st.y_label_size, st.tick_size,
st.colorbar_label_size            (label font sizes; optional)
```

| Function | Line | Purpose |
|----------|------|---------|
| **`_imgFitRect(iw,ih,cw,ch)`** | **1176** | Largest rect of aspect `iw:ih` centred in `cw×ch`; all 2-D coordinate functions derive from this |
| `draw2d(p)` | 1258 | Main render: `_resizePanelDOM` → decode → LUT → ImageBitmap → blit; then mask, axes, scale bar, colorbar, overlay, markers |
| `drawScaleBar2d(p)` | 1360 | Physical scale bar |
| `drawColorbar2d(p)` | 1436 | Gradient strip + min/max marks + rotated label centred in the `_cbWidth` gutter |
| `_drawAxes2d(p)` | 1491 | Ticks (edge labels nudged inward both axes), axis labels + title via `_drawTex` |
| `drawOverlay2d(p)` / `drawMarkers2d(p)` | 1629 / 1685 | Widgets / marker groups |

Zoom model: at `zoom=1` the whole image fills the fit-rect; at `zoom=Z>1` a
`1/Z` region fills it.  `_imgToCanvas2d` / `_canvasToImg2d` must stay exact
inverses of the blit geometry.

---

## Image layers (multi-image overlay)

`Plot2D.add_layer(data, cmap=, alpha=, clim=, visible=)` composites a second
(third, …) scalar image OVER the base image in the same panel, each with its own
colormap / clim / alpha. Distinct from `set_overlay_mask` (single-colour boolean
mask). `Layer.set(...)`, `Layer.set_data(frame)`, `Layer.remove()`,
`Plot2D.layers`, `Plot2D.remove_layer(layer)`. **Layers and tile mode are mutually
exclusive** (guard raises in both directions: `add_layer` on a tiled plot, and
`enable_tile` / `set_data(tile=True)` / auto-tile on a layered plot).

**A shape-changing `Plot2D.set_data` on a plot with layers raises `ValueError`.**
Each layer entry keeps the `(width, height)` it had at `add_layer` / its last
`Layer.set_data` time (`_encode_layer_pixels`), but `_drawLayers2d` always fits
every layer's bitmap into the BASE image's *current* `_imgFitRect(iw, ih, …)`
(`iw`/`ih` = the live `image_width`/`image_height`). So a base `set_data` that
changes shape while a stale-sized layer is still attached would silently stretch
that layer's old pixels over the new image instead of erroring — `set_data`
now checks `data.shape[:2]` against the current `image_height`/`image_width`
whenever `st.layers` is non-empty and raises before touching any state if they
differ (same-shape updates, the common live-update case, are unaffected). Remove
all layers first (`remove_layer`), change the base shape, then re-add them at the
new size. A layer-FREE plot's shape-changing `set_data` is unaffected and always
refreshes `image_width`/`image_height` (they're set unconditionally in the
pushed `fields` dict). See `TestTileGuards` / `TestShapeChangeNoLayers` in
`tests/test_plot2d/test_layers.py`.

**`Layer.set(clim=…)` has three distinct meanings** — `None` (default) leaves
the clim UNCHANGED (a no-op on that field, not "reset to auto"); a `(vmin, vmax)`
tuple sets an explicit range and re-quantises the cached frame over it;
`"auto"` is the sentinel to explicitly RESET to auto — recomputes the display
range from the layer's own current data (`self._layer_raw[layer_id]`) min/max,
the same auto-ranging `add_layer(..., clim=None)` does at creation time, and
re-quantises. Before this, `clim=None` was documented as "auto" but actually
behaved as a no-op, and there was no way to get back to auto range after
setting an explicit clim short of `remove()` + `add_layer()` again. See
`TestSet::test_set_clim_auto_resets_to_data_range` /
`test_set_clim_auto_matches_add_layer_auto` /
`test_set_clim_none_is_a_noop` in `tests/test_plot2d/test_layers.py`.

### State + transport (dynamic per-layer pixel keys)

The layer *metadata* lives in `st.layers` (a list of small dicts on the light view
trait):

```
st.layers = [{ id, cmap, clim_min, clim_max, alpha, visible,
               width, height, colormap_data, image_b64 }, …]   # z-order
```

`image_b64` in each entry is the layer's pixels: a base64 string (Jupyter /
standalone / `save_html`) OR a `"\x00bin:<adler32>"` change-token (Electron binary
transport). The JS reads pixels from this entry field on the base64 path.

The *heavy pixel bytes* additionally ride a **DYNAMIC geometry key**
`layer_<id>_b64` — one per layer — mirroring how the base image `image_b64` rides
the geom channel. The dynamic-key mechanism:

- **`Plot2D._GEOM_KEYS` is a PROPERTY** (not a plain frozenset): it returns the
  fixed base set (`image_b64`, `colormap_data`, `overlay_mask_b64`, `detail_b64`)
  UNION the current `layer_<id>_b64` keys. So `Figure._push` splits every layer's
  pixels off the light view trait onto `panel_<id>_geom` and dedup-caches them
  exactly like the base image; a removed layer's key drops out automatically.
- **`_electron._route_change`** ships each layer key as its own PLOTBIN frame:
  `_is_binary_pixel_key(k)` matches `k in _BINARY_KEYS` OR `layer_*_b64`. The
  binary frame header carries `{"geom": "panel_<id>_geom"}` and `key=layer_<id>_b64`,
  so the receiver builds slot `panel_<id>_geom::layer_<id>_b64` (the same
  `awi_state_binary` handler as the base image — already generic on `hdr.geom` +
  `e.data.key`, no change needed there).
- **`resolve_pixel_tokens`** (cold path: `save_html` / standalone) materialises
  real base64 for every `layer_<id>_b64` key AND the entry `image_b64` mirror, so a
  snapshot is self-contained.
- **JS `_spliceBinaryBytes`** scans `__apl_pixbytes` by the `panel_<id>_geom::`
  PREFIX (not the old hardcoded 3-key list) so it splices any `layer_<id>_b64_bytes`
  into `p2._geomCache`. The per-slot binary listeners are registered only for the
  fixed keys (`_registerBinaryPixelListeners`); dynamic layer bytes are consumed by
  the **geom-JSON change handler**, which now also calls `_spliceBinaryBytes` — the
  geom trait always re-pushes when layers change, so a layer's bytes converge into
  the cache regardless of trait arrival order.

### JS compositing (`_drawLayers2d`, called from `draw2d`)

After the base image (Canvas2D blit OR WebGPU) and the overlay mask, and BEFORE
`_drawAxes2d` / markers / widgets, `_drawLayers2d(p, st, imgW, imgH, ctx, iw, ih)`
draws each **visible** layer bottom-up on `plotCanvas`:

- `_layerBytes(st, layer)` prefers `layer_<id>_b64_bytes` (binary) over the entry
  `image_b64` base64;
- `_layerBitmap(p, st, layer)` builds a LUT-colormapped RGBA `OffscreenCanvas`,
  **cached per layer id** by `(pixel key, cmap, tint, has-alpha, clim)` —
  rebuilt only when the layer's data or appearance changes (a live scrub that
  only swaps one layer's data rebuilds just that layer). The LUT honours a 4th
  (alpha) channel when present (`cmapData[i][3] ?? 255`) — a `tint=` layer
  ships a 256×4 clear→colour ramp (`_build_tint_lut`), so per-texel alpha
  composites through the unpremultiplied `ImageData` and multiplies naturally
  with the per-layer `ctx.globalAlpha`;
- it blits with the SAME fit-rect + zoom/pan transform as the base blit
  (`_imgFitRect` + the `zoom>=1` window math) at `ctx.globalAlpha = layer.alpha`,
  so zoom/pan track the base exactly.

Because layers draw on `plotCanvas`, they sit UNDER `markersCanvas` /
`overlayCanvas` (z-order) and are captured by `exportPNG` for free (plotCanvas is
z1 in the composite). Over a WebGPU base the layers still composite in Canvas2D on
`plotCanvas` (which sits above the transparent `gpuCanvas`) — verified by
`test_layers_playwright.py::TestGpuBaseWithLayer`. Per-move perf: only the changed
layer's LUT bitmap is rebuilt (the box-loop is ~one pass over H×W uint8 → uint32,
comparable to the base image's `_buildLut32` blit).

---

## 3D drawing (line ~1840)
Orthographic projection; geometry b64-decoded and cached.  `draw3d` sorts
triangles, draws axes with per-axis `_drawTex` labels (`x/y/z_label_size`).

- **Camera** (`_rot3`): turntable with matplotlib azim/elev semantics —
  azimuth spins about the DATA z-axis, elevation tilts toward the viewer.
  Faces unit vector v when `el = asin(vz)`, `az = atan2(vx, -vy)`.
- **Scatter colours**: `st.point_colors_b64` (uint8 RGB triplets) gives
  per-point colours; empty string falls back to `st.color`.
- **Highlight**: `st.highlight = {x,y,z,color,size}` draws an emphasised
  ringed dot on top of everything (semi-transparent on the far side).
- **Reference sphere**: `st.sphere = {radius,color,alpha,wireframe}` draws a
  shaded silhouette disk + lat/long wireframe behind the geometry; far-side
  wireframe segments and scatter points are dimmed.
- **Voxels** (`geom_type 'voxels'`): shaded translucent cubes at the vertex
  centres.  `st.voxel_size`, `st.voxel_alpha`, `st.voxel_slice_alpha`.
  Performance design (budget ~3–6 µs/cube, ≤ ~20k cubes interactive):
  cube-corner screen offsets + face visibility computed once per frame;
  per-(colour, emphasis) sprites blitted with integer-snapped `drawImage`
  (≤256 unique colours; falls back to path fills above); typed-array
  projection + depth-sort cached per (geometry generation, view, panel
  size) so camera-static redraws (plane drags) only re-blit.  Benchmarks:
  `test_bench_voxels_orbit` / `test_bench_voxels_reblit`.
- **Echo guard**: `_attachEvents3d` writes interaction state via
  `_writeState()` (sets `p._selfWrite`), and the panel-json listener skips
  self-writes — without this every drag frame paid a second
  JSON.parse + full redraw.
- **Touch bridge** (`_attachTouch`, called from `_attachPanelEvents` for
  every panel kind): translates touch gestures into the *existing* mouse /
  wheel handlers via real `MouseEvent` / `WheelEvent` dispatch — 1-finger →
  mousedown/move/up, 2-finger pinch → wheel (anchored at the gesture
  midpoint via `p.mouseX/Y`), double-tap → dblclick.  `move`/`up` go to
  `document` (handlers listen there for off-canvas drags); `down`/`wheel`/
  `dblclick` go to the overlay canvas.  Overlay canvases set
  `touch-action:none` so the browser yields gestures to the plot.  No
  handler rewrites — a working mouse interaction is automatically a working
  touch one.
- **Geometry channel** (perf): plots that declare `_GEOM_KEYS` on the Python
  side (Plot2D, Plot3D) split heavy keys (`vertices_b64`, `image_b64`,
  `colormap_data`, …) into a second `panel_<id>_geom` trait, re-sent only
  when their content hash changes; the view trait carries `_geom_rev`.  JS
  caches the decoded geom (`p._geomCache`/`p._geomRev`) and `_applyGeom`
  splices it into the state before every draw, so view-only updates
  (highlight, camera, planes, title) never re-parse or re-transmit
  geometry.  Both the `change:panel_<id>_geom` and `change:panel_<id>_json`
  listeners call `_applyGeom`; the geom trait is loaded before the first
  draw.  Pairs with `Figure.batch()` push-coalescing on the Python side.
- **WebGPU path** (progressive enhancement, additive): scatter points
  (`_GPU_POINT_WGSL`) and voxels (`_GPU_VOXEL_WGSL`) render instanced on the
  GPU when available and above threshold (`GPU_POINT_THRESHOLD` 20k /
  `GPU_VOXEL_THRESHOLD` 8k); `gpu_mode` ∈ auto/always/off.  `gpuCanvas` sits
  below `plotCanvas`; decorations always draw on the 2D `plotCanvas` over a
  transparent background.  `_gpuMatrix` reproduces the canvas projection
  EXACTLY (verify numerically — the y-coefficients are NOT negated: canvas
  screen-y-down and NDC-y-up cancel).  Voxel slice emphasis + per-face shade
  are uniforms, so plane drags are a uniform write.  Every failure path
  (no `navigator.gpu`, null adapter, device lost, draw throw) sets
  `p._gpu='unavailable'` and the Canvas2D path renders unchanged.  **Testing:
  use offscreen-texture readback (`copyTextureToBuffer`), NOT screenshots —
  the WebGPU swapchain doesn't snapshot reliably under automation.**
- **Plane widgets** (`st.overlay_widgets`, type `'plane'`): translucent
  draggable slice selectors.  `draw3d` caches screen quads + the axis screen
  direction on `p._3dPlanes`; `_attachEvents3d` hit-tests them on mousedown
  (plane drag wins over orbit) and drags along the normal.  Voxels within
  half a voxel of a plane render at `voxel_slice_alpha`.  NOTE: during drags
  re-resolve widgets by id in `p.state` — object references go stale because
  the model echo replaces `p.state` on every `save_changes()`.
- `st.data_bounds` may be fixed from Python (`bounds=` kwarg) so geometry
  normalisation stays origin-true (unit-sphere direction vectors).

## Events
- `_emitEvent(panelId, eventType, widgetId, extraData)` (line 2031) writes
  `{source:'js', ...}` to `model.event_json`; `eventType` is any
  `pointer_*` / `key_*` / `wheel` / `double_click` string
  (see `callbacks.VALID_EVENT_TYPES`).
- Kind-specific attach functions: 3D 2059, 2D 2928, 1D 3201, bar 4341.
- Widget drag: 2D hit-test/drag 3409/3491; 1D from 3565.

## 1D drawing (line 2177)
`draw1d` renders series (b64 decode cache), axes, ticks (log ticks as TeX
`$10^{N}$`; edge labels nudged inward), grid, legend, units labels + title
via `_drawTex` (title size clamped via `_titlePx`).

## Bar chart (lines 3902–4530)
`_barGeom` (3902) computes per-bar geometry incl. grouped offsets and
log-scale mappers; `drawBar` (3965) renders grid, bars, value labels, ticks
(log ticks as TeX superscripts, category edge labels nudged inward), legend,
labels + clamped title; `_attachEventsBar` (4341) handles drag/hover/click.
Bar zoom/pan modifies `st.data_min/max` (value axis); `view_x0/x1` stays 0/1.

---

## Key data flows

```
Python push:
  plot._push() → figure._push(id) → panel_{id}_json trait changes
  → model.on('change:panel_{id}_json') → p.state = JSON.parse(...)
  → _redrawPanel(p)

JS → Python (widget drag):
  _doDrag2d / _doDrag1d → updates p.state.overlay_widgets in-place
  → _emitEvent(id, 'pointer_move', widgetId, {…})
  → model.set('event_json', …) + save_changes()
  → Python Figure._on_event() → Widget._update_from_js() + CallbackRegistry.fire()

JS → Python (3D rotate / zoom):
  _attachEvents3d → model.set('panel_{id}_json', …) + save_changes()

Python → JS (set widget position from Python):
  widget.set(…) → Figure._push_widget → event_json with source:'python'
  → model.on('change:event_json') patches overlay_widgets + redraws
```

---

## PNG export (`exportPNG`)

`render()` now RETURNS an internal API object `{ panels, exportPNG,
_gpuDisposeImagePanel, _gpuDisposePanel }` (anywidget ignores render()'s return;
`mount()` captures it — this also fixed a latent bug where the old
mount-handle `dispose()` referenced `panels`/`_gpuDispose*` from module scope,
which are inside `render`'s closure, and silently threw). The mount handle
exposes `handle.exportPNG({scale=1, includeWidgets=false}) →
Promise<{dataUrl,width,height}>`.

`exportPNG(opts)` (inside `render`, near `redrawAll`) composites the WHOLE
figure onto one offscreen canvas at `devicePixelRatio × scale`:

- **WebGPU hazard first**: a WebGPU canvas's drawing buffer is only valid right
  after its render pass, so exportPNG force-calls `draw2d(p)` on every
  active-GPU 2-D panel and `draw3d(p)` on every active-GPU 3-D panel
  (`p._gpu==='active' && p.gpuCanvas` visible, `_gpuImg`/`_gpuObj` present) to
  re-submit its pass, THEN composites in the SAME synchronous task — so
  `drawImage(gpuCanvas,…)` reads live pixels, not a blank buffer. (draw3d's
  active-GPU path uploads + submits in-task, no rAF, so the same-task re-render
  suffices for 3-D too — without it a scatter3d/voxels panel exported as an
  empty background rectangle; see `TestExportGpu3d` in
  `tests/test_embed/test_export_png.py`.)
- **Extent**: `fig_width/height + 2×8 px` gridDiv padding (NOT the measured
  `gridDiv` width — a bare `mount()` page has no `.apl-outer` inline-block CSS,
  so the grid container can stretch to the viewport). **Origin**: `gridDiv`'s
  top-left (grid tracks are fixed-px + left-anchored, so panels sit correctly).
- **Per-panel z-order** (`_drawEl` positions each canvas by its
  `getBoundingClientRect()` relative to the root): gpuCanvas (z0) → plotCanvas
  (z1) → x/yAxisCanvas → cbCanvas → [overlayCanvas z5 only if `includeWidgets`]
  → markersCanvas (z6) → scaleBar (z7) → titleCanvas (z8). Grid panels first,
  then insets (`p.isInset`) on top — **each titled inset's title bar text is
  drawn directly onto the output canvas right after its canvas stack**
  (`_drawInsetTitle`; the title bar is plain DOM — a `<div>`/`<span>`, not a
  canvas — so `_drawEl` alone never captures it; approximates the on-screen
  CSS: 11px sans-serif, `theme.tickText` colour, left-padded to the titleBar's
  rect) — then the figure-level `calloutCanvas` (region indications) composited
  LAST. Status bars / stats overlays are excluded.
- **Coordinate snapping** (`_drawEl`): `dx`/`dy` are `Math.round()`ed from the
  element's `left`/`top`, and `dw`/`dh` are the ROUNDED `right`/`bottom` edge
  minus the rounded `dx`/`dy` — never `Math.round(width)` directly. This makes
  two elements that share a CSS edge (e.g. adjacent grid panels, or a
  panel's axis-gutter canvas against its plotCanvas) round that shared edge to
  the *same* output pixel on both sides. Without it, at a fractional effective
  scale (`devicePixelRatio × opts.scale` — e.g. a real 150% Windows display, or
  `scale: 1.25`), each element's `dx`/`dw` were computed independently as raw
  floats, and adjacent elements could round their common boundary to different
  output pixels — a 1px background-coloured seam (or overlap) exactly at the
  join. See `TestExportMultiPanel::test_fractional_scale_no_seam_between_panels`
  in `tests/test_embed/test_export_png.py` (reproduced with
  `device_scale_factor=1.5`).
- Ends with `out.toDataURL('image/png')`; rejects the promise with a message on
  failure (no 2-D context, `toDataURL` throw).

The standalone HTML template (`_repr_utils.build_standalone_html`) captures
render()'s api into `_aplRenderApi` and adds a `message` listener:
`{type:'anyplotlib_export_png', requestId, opts}` → `exportPNG(opts)` → replies
`{type:'anyplotlib_export_png_result', requestId, dataUrl, width, height}` (or
`{…, error}`) to `event.source` (targetOrigin `'*'`) — the same channel the
`awi_state` postMessages ride. Tests: `tests/test_embed/test_export_png.py`.

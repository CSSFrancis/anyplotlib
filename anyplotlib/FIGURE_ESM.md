# FIGURE_ESM.md — Navigator for `figure_esm.js`

`figure_esm.js` is **~9,470 lines** and one big closure. Everything lives inside
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
| Theme (dark/light detection) | 26 |
| Shared math helpers | 64 |
| b64 array decode helpers | 109 |
| **Rich-text (mini-TeX) engine**: `_texRuns` / `_texLayout` / `_drawTex` | 161 / 228 / 250 |
| **2D gutter geometry**: `_cbWidth` / `_cbGap` / `_padT` / `_titlePx` | 301 / 313 / 323 / 333 |
| **Layout engine** `applyLayout` | 778 |
| `_buildCanvasStack` | 861 |
| `_createPanelDOM` | 1003 |
| `_createInsetDOM` / `_applyAllInsetStates` | 1144 / 1538 |
| `_resizePanelDOM` | 2251 |
| **2D drawing**: `_imgFitRect` | 2415 |
| `draw2d` | 2744 |
| `drawScaleBar2d` / `drawColorbar2d` | 2939 / 3219 |
| **Floating keys**: `_keyEnsure` / `_keyRect` / `drawKeys` | 3038 / 3061 / 3074 |
| `_drawAxes2d` (ticks, labels, title) | 3273 |
| `drawOverlay2d` / `drawMarkers2d` | 3426 / 3590 |
| **Image layers**: `_layerBytes` / `_layerBitmap` / `_drawLayers2d` | 2564 / 2588 / 2649 |
| Binary-bytes splice: `_spliceBinaryBytes` / `_registerBinaryPixelListeners` | 734 / 765 |
| **Hover readout**: `_pixelValue2d` / `_readoutInfo2d` | 4434 / 4516 |
| `_notifyReadout` / `_updateStatus2d` / `_armValueProbe` | 4556 / 4571 / 4592 |
| **3D drawing**: `draw3d` | 5568 |
| Event emission `_emitEvent` | 6405 |
| 3D event handlers `_attachEvents3d` | 6462 |
| **1D drawing**: `draw1d` | 6686 |
| `_drawLine` (1D series + markers) | 6839 |
| `drawOverlay1d` / `drawMarkers1d` | 7132 / 7216 |
| Marker hit-test `_markerHitTest2d` | 7484 |

> **`raster` marker (1D/PlotXY)** — `drawMarkers1d` has a `type==='raster'`
> branch that blits a single RGBA image across data-coord `extent` (the fast
> path for dense `PlotXY.pcolormesh` heatmaps). The image bytes ride the geom
> channel as `st.raster_geom[id]` (Python `Plot1D._GEOM_KEYS`), so view-only
> redraws never re-transmit them; the decoded `OffscreenCanvas` is cached on
> the marker set (`ms._rasterBmp`/`_rasterKey`). The shared `clip_path` block
> clips it to a curved sector.
| Panel event dispatch `_attachPanelEvents` | 7741 |
| 2D events `_attachEvents2d` | 7783 |
| 1D events `_attachEvents1d` | 8176 |
| 2D widget drag `_ovHitTest2d` / `_doDrag2d` | 8451 / 8730 |
| **Brush strokes**: `_brushLiveBegin` / `_brushCommit` / `_brushErase` / `_brushPaintAt` | 8643 / 8657 / 8686 / 8721 |
| 1D widget drag `_canvasXToFrac1d` … / snapping `_snapVal` | 8855 / 8928 |
| Shared-axis propagation `_getShareGroups` | 8999 |
| Figure resize `_applyFigResizeDOM` | 9063 |
| **Bar chart**: `_barGeom` / `drawBar` / `_attachEventsBar` | 9254 / 9317 / 9693 |
| Generic redraw `_redrawPanel` | 9883 |
| **PNG export**: `_compositeCanvas` / `exportCanvas` / `exportPNG` | 10042 / 10238 / 10292 |
| Native-resolution render `_withNativeSize` | 10018 |
| **Export UI**: `_toast` / `_downloadCanvas` / `_openMenu` | 10326 / 10420 / 10563 |
| Export registry `registerExportAction` | 10451 |

> **`brush` widget (2-D)** — the one widget whose drag is *modal*, and the one
> that must NOT write the model per tick. `_ovHitTest2d` takes an extra `mods`
> argument and runs a FIRST PASS that claims the drag for an armed brush
> (`active !== false`) only when `mods.shift` is set — so a bare drag still pans
> and still drags other widgets, and a Shift-drag beats every widget regardless
> of z-order. The hit carries `silent:true`, which suppresses the per-move
> `pointer_move` emit, and `_doDrag2d` returns before its
> `_viewStateJson`/`save_changes()` tail. The in-progress stroke lives in
> `p._brushLive` (a per-panel scratch), NOT in `p.state.overlay_widgets`: the
> panel trait is deliberately stale for the whole stroke, so any unrelated
> `save_changes()` re-fires `change:panel_<id>_json` and would replace `p.state`
> — wiping a stroke held there (a `pointer_leave` at the panel edge is enough).
> `drawOverlay2d` prefers the scratch; the mouseup handler calls `_brushCommit`
> and the existing generic branch pushes + emits exactly ONCE per stroke.

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
st.display_min/max, st.raw_min/max, st.raw_is_int, st.scale_mode
st.detail_b64, st.detail_region/width/height/seq, st.detail_min/max/is_int
st.readout_visible, st.probe_ms, st.probe_x/probe_y/probe_value
st.colormap_data    [[r,g,b], ...] × 256
st.x_axis, st.y_axis, st.axis_visible
st.markers, st.overlay_widgets, st.overlay_mask_b64/_color/_alpha
st.title_size, st.x_label_size, st.y_label_size, st.tick_size,
st.colorbar_label_size            (label font sizes; optional)
```

| Function | Line | Purpose |
|----------|------|---------|
| **`_imgFitRect(iw,ih,cw,ch)`** | **2384** | Largest rect of aspect `iw:ih` centred in `cw×ch`; all 2-D coordinate functions derive from this |
| `draw2d(p)` | 2713 | Main render: `_resizePanelDOM` → decode → LUT → ImageBitmap → blit; then mask, axes, scale bar, colorbar, overlay, markers |
| `drawScaleBar2d(p)` | 2908 | Physical scale bar |
| `_rawBand(st)` / `_buildLut32(st)` | 2433 / 2440 | The quantisation band the u8 bytes were encoded over, then the 256-entry LUT built from it. `_rawBand` mirrors Python `_tile_quant_clim`: a DEGENERATE band (`raw_max <= raw_min`) is UNSET and falls back to `display_min/max`. Both render paths and the colorbar go through it — honouring a `(0, 0)` band paints solid black |
| `drawColorbar2d(p)` | 3188 | Gradient strip + min/max marks (band-relative, via `_rawBand`) + rotated label centred in the `_cbWidth` gutter |
| `_drawAxes2d(p)` | 3242 | Ticks (edge labels nudged inward both axes), axis labels + title via `_drawTex` |
| `drawOverlay2d(p)` / `drawMarkers2d(p)` | 3395 / 3559 | Widgets / marker groups |

Zoom model: at `zoom=1` the whole image fills the fit-rect; at `zoom=Z>1` a
`1/Z` region fills it.  `_imgToCanvas2d` / `_canvasToImg2d` must stay exact
inverses of the blit geometry.

### Hover readout

Visibility: `st.readout_visible` (Python, authoritative) AND `p.readoutHidden` (the
viewer's `v` key — kept off the state so a per-frame push can't undo it).

`_updateStatus2d(p)` composes it from `p.mouseX/mouseY` and is called from BOTH the
`mousemove` handler in `_attachEvents2d` and the `change:panel_<id>_json` observer —
the latter because a probe answer landing under a stationary cursor has no mousemove
to piggyback on. It writes `p.statusBar` (unless `st.readout_visible === false`) and
hands `_readoutInfo2d`'s payload to the host via `_notifyReadout`
(`mount()`'s `opts.onReadout` + an `apl:readout` CustomEvent bubbling off `el`), so an
embedding app can render the readout in its own chrome with the pill switched off.

Content: physical `x:`/`y:` in `st.units`, the pixel index `[ix, iy]`, and the pixel
VALUE — `v:<value>` for a scalar image, `rgb:r,g,b` for `st.is_rgb`.

Value precision, in order of preference:

1. **`st.probe_value`** — the exact value Python answered for `st.probe_x/probe_y`.
   `_armValueProbe` emits a `value_probe` event after the cursor dwells `st.probe_ms`
   on a pixel (once per pixel, never per move); `Plot2D._answer_value_probe` answers from
   the array/backend. Ignored unless it matches the pixel now under the cursor.
2. **Inverted codes** — with `raw_is_int`/`detail_is_int` and a band spanning ≤ 255
   levels, `_codeToValue` recovers the exact integer from the byte (see its comment).
3. **Quantised estimate** — `raw_min + code/255*(raw_max-raw_min)`, resolving the
   band to `range/255`. This is what a kernel-less page (`save_html`) always shows.

`_pixelValue2d` reads the codes from the SAME bytes the blit draws — including the
detail tile's native pixels above `zoom=1`, where the base is a downsampled overview
— so the readout always names the source actually on screen.

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
- **Surface textures** (`Plot3D.set_texture`, `geom_type 'surface'`):
  `st.texture_url` (a `data:` URL) + `st.texture_uv_b64` (float32 per-vertex
  `(u,v)`) ride the geom channel; `texture_alpha` / `texture_shade` /
  `texture_cull` are light view fields. `_texEnsure(p, url)` decodes into
  `p._3dTex` via an `Image` — asynchronous, so the first frame draws the
  colormapped surface and the `onload` calls `_redrawPanel`. Each triangle is
  then clipped and painted with an affine `drawImage` mapping texel space onto
  the screen triangle (`ctx.transform`, **not** `setTransform` — the panel's
  DPR scale must survive). Three things are easy to get wrong here:
  - **Seams.** Neighbours each cover ~half the pixels on a shared edge, so
    source-over leaves a mesh of background hairlines. Triangles are grown by
    `_TEX_EXPAND` so they overlap — offsetting the three **edges** (a miter,
    `_miter()`, capped at `_TEX_MITER_MAX`), never pushing vertices away from
    the centroid: for the slivers a quad-split grid makes at a sphere's limb
    the centroid sits on the long edges and barely moves them.
    `test_no_seams_between_neighbouring_triangles` guards this.
  - **`alpha < 1`.** Because the triangles overlap, drawing them translucent
    double-composites every overlap into a scaly grid. The surface is instead
    built opaque on a cached `p._3dTexOff` OffscreenCanvas (same DPR
    transform) and blitted once at `texture_alpha`.
  - **Shading.** `texture_shade` fills the clip black then draws the texture at
    `globalAlpha = bright`, rather than darkening with a second translucent
    pass (which would double-darken the overlaps). `bright` is Lambert against
    a *camera-facing* normal (flipped when it points into the screen), so it
    never depends on the grid's winding.

  A flat "sample one texel per small triangle" fast path was tried and removed:
  it is ~3× cheaper per triangle but makes neighbours differ in colour, which
  the seam overlap then widens into a visible herringbone. On Canvas2D,
  textures therefore want a **coarse** grid (the image carries the detail) —
  ~2k triangles orbits at ~7 ms/frame, ~32k at ~350 ms. **The WebGPU path
  below removes that constraint entirely.**
- **Textured surfaces on WebGPU** (`_GPU_SURFACE_WGSL`, `_gpuInitSurfacePanel`
  / `_gpuUploadSurface` / `_gpuDrawSurface`): indexed triangles with per-vertex
  UVs and smooth normals, depth-tested, above `GPU_SURFACE_THRESHOLD` (2000
  faces) — measured 9k triangles 54 ms → 0.4 ms, 160k triangles 1.75 s →
  2.4 ms. Everything the Canvas2D path has to fake is free here: the depth
  buffer replaces the per-frame painter's sort *and* makes `cull_backfaces`
  unnecessary (`cullMode: 'none'` is correct for open and closed surfaces
  alike); shared vertices mean no seams, so no miter expansion; and Lambert
  runs per PIXEL against an interpolated normal. Normals are accumulated per
  vertex at upload — `norm()` scales all axes by the same `2/maxR`, so a
  data-space normal only needs the camera rotation (passed as `rot0..rot2`) to
  reach view space. `_gpuWanted(st, texReady)` gates it: only textured
  surfaces, and only once the `<img>` has decoded. **`texture_alpha < 1` stays
  on Canvas2D** — the overlapping-triangle composite that makes a translucent
  skin look right has no cheap depth-buffer equivalent.
  - **Mipmaps are mandatory**, not a nicety: without them a 1440×720 texture
    minified onto a 300 px sphere aliases into sparkling noise, visibly worse
    than Canvas2D (which gets mip-like filtering free from `drawImage` +
    `imageSmoothingQuality`). WebGPU has no built-in mipmapper, so
    `_gpuGenerateMips` downsamples level by level with a fullscreen-triangle
    blit (`_GPU_MIP_WGSL`, pipeline cached per device+format).
  - **Diagnosing "why is this on Canvas2D?"** — `draw3d` records
    `globalThis.__apl_gpu3d[panelId]` every frame (`{geom, gpu, wanted,
    texUrl, texReady, faces, mode, pw, ph, hasNavGpu}`), mirroring
    `__apl_gpu2d`. It is the only way after the fact to tell "no adapter" from
    "texture still decoding" from "panel had zero size at init" — and from "the
    page is serving a stale inlined renderer", which is what a `make html`
    without `make clean` produces (see AGENTS.md).
  - **`_gpuMatrix`'s clip.z sign matters.** It must INCREASE with depth into
    the screen for `depthCompare: 'less'` against a 1.0 clear to keep the
    nearest fragment. It was originally negated, which inverted every
    depth-tested GPU draw — scatter painted far points over near ones, and a
    textured sphere rendered inside-out (you saw the far hemisphere). Voxels
    never caught it because they disable depth writes. Pinned by
    `tests/test_plot3d/test_gpu_depth.py`.
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

## PNG export (`exportPNG` / `exportCanvas`)

`render()` RETURNS an internal API object `{ panels, exportPNG, exportCanvas,
registerExportAction, unregisterExportAction, calloutCanvas, _drawCallouts,
figMarkerCanvas, _drawFigureMarkers, _gpuDisposeImagePanel, _gpuDisposePanel }`
(anywidget ignores render()'s return; `mount()` captures it). The mount handle
re-exposes `exportPNG`, `exportCanvas`, `registerExportAction` and
`unregisterExportAction`.

```
exportPNG({ scale=1, includeWidgets=false, panelId=null,
            source='view'|'full'|'native', theme='current'|'light'|'dark' })
  → Promise<{dataUrl, width, height}>
exportCanvas(same opts) → {canvas, width, height}   // synchronous, throws
```

| Function | Line | Purpose |
|----------|------|---------|
| `_cssScale` | 9918 | inverse of `_applyScale`'s `transform:scale()` |
| `_panelBox` | 9929 | the element whose rect bounds one panel |
| `_neutralizeView` / `_restoreView` | 9938 / 9963 | transient whole-extent view |
| `_nativeGeom` / `_nativeGuard` | 9978 / 9993 | native size + why-not message |
| `_withNativeSize` | 10018 | resize → redraw → run → restore |
| `_compositeCanvas` | 10042 | the compositor (`_drawEl` / `_drawPanel` …) |
| `exportCanvas` / `exportPNG` | 10238 / 10292 | orchestrator / data-URL wrapper |

**The whole pipeline is ONE synchronous task** — theme swap, view reset, native
resize, composite, restore — so the browser never paints an intermediate state
and nothing flickers. This is only possible because the draw path is fully
synchronous (no `createImageBitmap`, no rAF in the draw functions).

### `theme`

Swap the closure's `theme`, `redrawAll()`, composite, restore, `redrawAll()`.
**No CSS work is needed**: `drawImage` copies a canvas's backing store and never
its CSS `background`, and every draw function fills its own bitmap with theme
colours (`_blit2d` → `theme.bgCanvas`, `_drawAxes2d` → `theme.axisBg`, `draw3d`
/ `draw1d` / `drawBar` → `theme.bgPlot`, `_compositeCanvas` → `theme.bg`). The
inline CSS set at DOM-creation time IS stale during the swap, but is never
painted. No cache is theme-keyed (`blitCache` keys on bytes+LUT, `_lutKey` has
no theme term), so nothing survives the redraw.

### `source`

- **`view`** — as displayed. Zoom, pan and contrast exactly as on screen.
- **`full`** — `_neutralizeView` resets 2-D `zoom`/`center_x`/`center_y`, 1-D
  `view_x0`/`view_x1`, 3-D `zoom` (NOT azimuth/elevation — orientation is
  content the user chose). Bar has no view state. It also **clears the detail
  tile**: a tile covers only the pre-reset region, so leaving it in place lets
  `_blit2d` stretch that sub-region over the whole fit-rect.
  Nothing is written to the model — shared-axis propagation
  (`_propagateZoom2d` / `_propagateView1d`) only runs from event handlers, and
  `_emitViewChanged` early-returns while `_exporting`.
- **`native`** — ONE 2-D panel at one output pixel per data pixel, WITH its
  axes, colorbar, title, markers and widgets. `_withNativeSize` inverts the
  gutter math at the top of `_resizePanelDOM` (keep the two in step), sets
  `p._dprOv = 1` so the backing store is exact data pixels, forces
  `st.gpu_mode='off'` (a native-size WebGPU surface would reconfigure to a
  buffer far larger than the display), then `_resizePanelDOM` + `_redrawPanel`
  do all the work — decorations come along for free. Composited at
  `outScale = 1`.
  Refused (with a message naming the way out) for a non-2-D panel, a missing
  `panelId`, an empty panel, a size over `EXPORT_MAX_SIDE` (16384) /
  `EXPORT_MAX_AREA` (2^28), and — importantly — for a **tiled** panel:
  `TILE_THRESHOLD` is 1024 and `tile='auto'` is the default, so any image large
  enough to want a native export holds only an overview + one detail tile in the
  browser. That case must go through `fig.savefig(path, source='native')`,
  which re-encodes the backend at full resolution into the snapshot
  (`_export._temporarily_untiled`) and then runs this same native render
  headless.

### `panelId`

Changes **only the origin and the extent**; every draw loop is untouched and the
smaller output canvas clips the rest. So a panel export is by construction the
matching sub-rectangle of the figure export — overlapping insets and callout
leaders that cross into the panel included. Pinned by
`TestPanelCrop::test_panel_export_matches_the_figure_sub_rectangle`.

### Compositing details

- **WebGPU hazard first**: a WebGPU canvas's drawing buffer is only valid right
  after its render pass, so `_compositeCanvas` force-calls `draw2d(p)` on every
  active-GPU 2-D panel and `draw3d(p)` on every active-GPU 3-D panel, THEN
  composites in the SAME synchronous task.
- **`_cssScale`**: `_applyScale` shrinks `outerDiv` with `transform:scale(s)`
  whenever the figure is wider than its container — the normal Jupyter case for
  a wide figure. `getBoundingClientRect()` then reports VISUAL px while the
  extent comes from `fig_width`/`fig_height` (native px), so every rect delta is
  multiplied by `1/s`, read straight off the computed transform matrix (NOT off
  `offsetWidth`/rect — a native export resizes a panel mid-flight, which would
  corrupt a layout-derived ratio). Without this the panels composite into the
  top-left corner of an otherwise blank canvas; see
  `TestCssScale::test_export_fills_the_canvas_when_the_figure_is_css_scaled`.
- **Extent**: figure = `fig_width/height + 2×8 px` gridDiv padding (NOT the
  measured `gridDiv` width — a bare `mount()` page has no `.apl-outer`
  inline-block CSS, so the container can stretch); panel = the wrapper's own
  rect (it is explicitly sized `pw×ph` and cannot stretch). **Origin**: the
  corresponding element's top-left.
- **Per-panel z-order** (`_drawEl` positions each canvas by its
  `getBoundingClientRect()` relative to the root): gpuCanvas (z0) → plotCanvas
  (z1) → x/yAxisCanvas → cbCanvas → [overlayCanvas z5 only if `includeWidgets`,
  redrawn onto a scratch canvas with handles suppressed] → markersCanvas (z6) →
  scaleBar (z7) → titleCanvas (z8). Grid panels first, then insets — each titled
  inset's title bar text drawn directly (`_drawInsetTitle`; the title bar is
  plain DOM, so `_drawEl` never captures it) — then the figure-level
  `calloutCanvas` and `figMarkerCanvas` last. Status bars / stats overlays are
  excluded.
- **Coordinate snapping** (`_drawEl`): `dx`/`dy` are `Math.round()`ed from the
  element's `left`/`top`, and `dw`/`dh` are the ROUNDED `right`/`bottom` edge
  minus the rounded `dx`/`dy` — never `Math.round(width)` directly. This makes
  two elements that share a CSS edge round that edge to the *same* output pixel
  on both sides; without it a fractional effective scale produced a 1 px
  background-coloured seam at the join. See
  `TestExportMultiPanel::test_fractional_scale_no_seam_between_panels`.

## Export UI: menu, clipboard, download, registry

| Function | Line | Purpose |
|----------|------|---------|
| `_toast` | 10326 | transient bottom-centre message |
| `_copyCanvas` | 10361 | clipboard write + feature detection |
| `_showPngPreview` | 10385 | framed-document download fallback |
| `_downloadCanvas` | 10420 | `<a download>` or the preview |
| `registerExportAction` | 10451 | downstream extension point |
| `_menuRows` / `_openMenu` | 10504 / 10563 | menu model / DOM |
| `_panelAtPoint` | 10673 | hit test (insets first — they sit on top) |

- **An `exportBtn` badge (⤓, beside the help badge) opens the same menu on an
  ordinary left click.** Hosts — JupyterLab, PyCharm, VS Code — install their own
  `contextmenu` and keyboard handlers and may swallow a right-click or Ctrl/Cmd+C
  before the page sees it, so the badge is the route that always works. Its
  `mousedown` calls `preventDefault()` so it does not steal focus from the
  hovered panel, which is what `_focusedPanelId()` uses to scope the menu.
- **The `contextmenu` and Ctrl+C listeners are on `outerDiv`, not on each
  `overlayCanvas`.** This deliberately differs from every other input handler:
  `overlayCanvas` is positioned at `imgX/imgY` with size `imgW×imgH`, so it
  covers only the *image area* — the axis gutters (`PAD_L` 58, `PAD_B` 42), the
  colorbar and the title strip are NOT under it, and a per-overlay listener
  would silently do nothing on 30-40 % of a panel with physical axes.
- **Ctrl/Cmd+C** is panel-scoped when a panel's `overlayCanvas` is
  `document.activeElement` (mouseenter focuses it), figure-scoped otherwise.
  Bound to `outerDiv` rather than `document` so it never hijacks Ctrl+C for the
  surrounding notebook.
- **Modifier guard**: the per-panel keydown handlers now `return` on
  `ctrl/meta/alt` AFTER the unconditional `key_down` emit. Before this, Ctrl+C
  toggled the colorbar and Cmd+S (JupyterLab's save) flipped the colour scale to
  symlog, because both matched on the bare letter.
- **Two save entries.** *Save PNG…* is `<a download>` — no prompt. *Save as…*
  (only listed when `_canPickFile()`) uses `showSaveFilePicker`, which hands the
  page a PERSISTENT writable handle and therefore triggers Chrome's
  file-editing permission prompt — too much for a plain save, right when the
  user asked to choose a folder. A dialog the user closed and one that never
  opened *both* reject with `AbortError`, so the name cannot separate them; one
  that never rendered returns in well under `PICKER_MIN_MS` (250 ms), which is
  the discriminator.
- **Download fallback**: a sandboxed frame without `allow-downloads` makes
  `a.click()` a SILENT no-op — no exception, no event, nothing to feature
  detect. `window.self !== window.top` is the one checkable condition that
  separates the reliable case (JupyterLab / Notebook 7 render inline; a
  `save_html` page opened directly is top-level) from the unreliable one (VS
  Code webviews, `_repr_html_` iframes, nbconvert output). When framed, the
  result is posted to the parent under the existing
  `anyplotlib_export_png_result` message AND shown as an in-figure preview whose
  caption points at the browser's own "Save image as…", which needs no
  permission and is never blocked.
- **Clipboard**: gated on `isSecureContext && navigator.clipboard &&
  ClipboardItem && clipboard.write`. The Blob is built SYNCHRONOUSLY from the
  data URL (not via the async `toBlob` callback) so the write stays inside the
  user-gesture task. The `_repr_html_` iframes carry `allow="clipboard-write"`,
  without which Chrome blocks the write in an opaque-origin frame.
- **Registry**: `registerExportAction({id, label, group, scope:'panel'|
  'figure'|'both', order, enabled, handler})` returns an unregister function.
  `handler(ctx)` receives `{panelId, kind, isInset, state, theme, themeName,
  figure, exportPNG, exportCanvas, downloadPNG, copyPNG, toast, model, event}`.

Test hooks: `__apl_menuItems`, `__apl_toastText`, `__apl_menuTheme`,
`__apl_previewOpen`, `__apl_nativeLimits`, `__apl_nativeGuard`.

Tests: `tests/test_embed/test_export_png.py` (the pre-existing contract),
`test_export_sources.py` (panelId / source / theme / CSS scale),
`test_export_menu.py` (menu, clipboard, download, registry),
`test_savefig.py` (the Python entry point + view reconciliation).

The standalone HTML template (`_repr_utils.build_standalone_html`) captures
render()'s api into `_aplRenderApi`, **also assigns it to `window._aplRenderApi`**
(module scope is not global scope, so `page.evaluate` — and therefore
`Figure.savefig` — cannot reach it otherwise), and adds a `message` listener:
`{type:'anyplotlib_export_png', requestId, opts}` → `exportPNG(opts)` → replies
`{type:'anyplotlib_export_png_result', requestId, dataUrl, width, height}` (or
`{…, error}`) to `event.source` (targetOrigin `'*'`). `opts` is forwarded
verbatim, so the new fields work over that channel too.

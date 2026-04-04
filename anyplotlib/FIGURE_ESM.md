# FIGURE_ESM.md — Navigator for `figure_esm.js`

`figure_esm.js` is **~2 810 lines** and one big closure. Everything lives inside
`function render({ model, el })` so that all helpers share the same scope
(`theme`, `PAD_*`, `panels` Map, etc.).  This document is a line-numbered map
so you can jump straight to the relevant section without reading the whole file.

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
         A 256×256 image in an 800×333 canvas occupies a 333×333 fit-rect
         starting at x=233.5; bgCanvas colour shows on either side.

Rule 4 – Zoom is relative to the fit-rect.
         zoom=1 → fit-rect exactly filled by the whole image.
         zoom=Z → a 1/Z portion of the image fills the fit-rect.
         The fit-rect position never changes; only which part of the
         image is drawn inside it changes with zoom/pan.
```

---

## Quick-reference: line ranges

| Section | Lines |
|---------|-------|
| Shared constants (`PAD_*`) | 9–14 |
| Theme (dark/light detection) | 15–51 |
| Shared math helpers | 53–84 |
| Outer DOM setup + tooltip | 85–131 |
| Per-panel state map + guards | 128–131 |
| **Layout engine** | 132–458 |
| **2D drawing** | 459–956 |
| **3D drawing** | 957–1159 |
| Event-emission helper | 1160–1171 |
| 3D event handlers | 1172–1238 |
| **1D drawing** | 1239–1497 |
| Marker hit-test helpers | 1498–1617 |
| Panel-level event dispatch | 1618–1635 |
| `_canvasToImg2d` | 1626–1635 |
| 2D event handlers | 1636–1805 |
| 1D event handlers | 1806–1909 |
| 2D overlay widget hit-test & drag | 1910–2077 |
| 1D overlay widget drag | 2078–2131 |
| Shared-axis propagation | 2132–2172 |
| Figure-level resize | 2173–2342 |
| **Bar chart drawing + events** | 2343–2697 |
| Generic redraw + RedrawAll | 2698–2710 |
| ResizeObserver (cell-fit) | 2711–2801 |
| Model listeners + initial render | 2802–2812 |

---

## Section-by-section detail

### Shared closure constants (lines 9–14)
```
PAD_L=58  PAD_R=12  PAD_T=12  PAD_B=42
```
All panel kinds use the **same** padding so axes align across rows/columns.
The inner plot rectangle is `[PAD_L, PAD_T] → [pw-PAD_R, ph-PAD_B]`.

---

### Theme (lines 15–51)
- **`_isDarkBg(node)`** — walks the DOM tree to detect a dark background.
- **`_makeTheme(dark)`** — returns a theme object with keys:
  `bg`, `bgPlot`, `bgCanvas`, `border`, `axisBg`, `axisStroke`,
  `gridStroke`, `tickStroke`, `tickText`, `unitText`, `dark`.
- `theme` is a module-level `let`; refreshed on OS media-query changes and
  JupyterLab / VS Code theme mutations via `MutationObserver`.

---

### Shared math helpers (lines 53–84)
| Function | Purpose |
|----------|---------|
| `findNice(t)` | Round a range to a clean tick interval (1/2/2.5/5/10 × 10ⁿ) |
| `fmtVal(v)` | Format an axis number (0, exponential, fixed, etc.) |
| `_axisValToFrac(arr, val)` | Data value → [0,1] fraction along an axis array (binary-search) |
| `_axisFracToVal(arr, frac)` | Inverse of the above |

---

### Outer DOM (lines 85–131)
```
outerDiv          position:relative wrapper around everything
  gridDiv         CSS grid; columns/rows set by applyLayout()
  resizeHandle    bottom-right drag handle (figure-level resize)
  tooltip div     shared hover tooltip (created lazily by _showTooltip)
```
- **`_showTooltip(text, cx, cy)`** — shows/hides a fixed tooltip.
- **`panels`** — `Map<id, p>` storing every live panel object.
- **`_suppressLayoutUpdate`** — boolean guard preventing re-entry during resize.

---

### Layout engine (lines 132–458)

#### `applyLayout()` (line 133)
Reads `layout_json`. Builds CSS grid tracks from `panel_specs[].panel_width/height`.
Creates panels that don't exist yet, resizes existing ones, removes stale ones.

#### `_createPanelDOM(id, kind, pw, ph, spec)` (line 171)
Builds all canvas/DOM elements for one panel, stores the **`p` object** in
`panels`, subscribes to `change:panel_{id}_json`, runs the initial draw.

**DOM structure by kind:**
| kind | elements |
|------|----------|
| `'2d'` | `plotWrap > plotCanvas + overlayCanvas + markersCanvas + yAxisCanvas + xAxisCanvas + cbCanvas + scaleBar + statusBar` |
| `'3d'` | `wrap3 > plotCanvas + overlayCanvas + markersCanvas + statusBar` |
| `'1d'` / `'bar'` | `wrap > plotCanvas + overlayCanvas + markersCanvas + statusBar` |

#### `_resizePanelDOM(id, pw, ph)` (line 342)
Updates `canvas.width / canvas.height` (DPR-scaled) for every canvas in the panel.

#### The `p` (panel) object — all fields
```js
p.id, p.kind, p.pw, p.ph
p.state          // parsed JSON from panel_{id}_json (full plot state dict)
p.plotCanvas, p.plotCtx          // main image / plot canvas
p.overlayCanvas, p.ovCtx         // interactive overlay widgets
p.markersCanvas, p.mkCtx         // static markers (pointer-events:none)
p.xAxisCanvas, p.yAxisCanvas, p.xCtx, p.yCtx  // 2D only
p.cbCanvas, p.cbCtx              // 2D only — colorbar
p.scaleBar                       // 2D only — scale-bar canvas
p.statusBar                      // coordinate readout div
p.plotWrap                       // 2D only — positioned wrapper div
p.blitCache      // { bitmap, bytesKey, lutKey, w, h } — ImageBitmap cache
p.ovDrag         // active 1D/bar widget drag state or null
p.ovDrag2d       // active 2D widget drag state or null
p.isPanning      // bool
p._hoverSi, p._hoverI, p._hovBar
```

---

### 2D drawing (lines 459–956)

All 2D state lives in `p.state`. Key fields:
```
st.image_b64       base-64-encoded Uint8 raw pixel bytes
st.image_width/height
st.zoom            1.0 = fit-rect filled; Z > 1 = zoomed in Z×
st.center_x/y      normalised (0–1) image centre of the viewed region
st.display_min/max  clamp range for LUT
st.raw_min/max      histogram-stretch range
st.scale_mode       'linear' | 'log' | 'symlog'
st.colormap_data    [[r,g,b], ...] × 256
st.show_axes, st.x_axis, st.y_axis
st.scale_bar, st.colorbar
st.markers, st.overlay_widgets
st.share_axes
```

| Function | Lines | Purpose |
|----------|-------|---------|
| **`_imgFitRect(iw,ih,cw,ch)`** | **465** | **Returns `{x,y,w,h,s}` — the largest rect of aspect `iw:ih` centred in `cw×ch`. `s` = canvas-px per image-px. All 2-D coordinate functions derive from this.** |
| `_buildLut32(st)` | 471 | Build 256-entry `Uint32Array` LUT from colormap + scale mode |
| `_lutKey(st)` | 499 | String cache key (invalidates when colormap/range changes) |
| `_imgToCanvas2d(ix,iy,st,pw,ph)` | 503 | Image pixel → canvas pixel. **zoom≥1**: uses pan/crop formula. **zoom<1**: maps through the centred-shrink geometry (`dstX = x+(w-w·zoom)/2`) — must match `_blit2d` exactly. |
| `_imgScale2d(st,pw,ph)` | 514 | Returns `_imgFitRect(…).s * zoom` — canvas-px per image-px at current zoom |
| `_blit2d(bitmap,st,pw,ph,ctx)` | 518 | **Contain render**: clears canvas to `bgCanvas`, draws image inside fit-rect. zoom≥1 → crops + fills fit-rect; zoom<1 → shrinks fit-rect proportionally (centred) |
| `draw2d(p)` | 540 | Main 2D render: decode bytes → LUT → ImageBitmap → `_blit2d`; then axes, scale bar, colorbar, overlay, markers |
| `drawScaleBar2d(p)` | 587 | Physical scale bar using `fr.w` (fit-rect width) for pixel sizing |
| `drawColorbar2d(p)` | 663 | Colorbar strip with gradient + tick labels |
| `_drawAxes2d(p)` | 705 | Tick marks + labels on `xAxisCanvas` / `yAxisCanvas` |
| `drawOverlay2d(p)` | 805 | Draw `overlay_widgets` onto `overlayCanvas` |
| `_drawHandle2d(ctx,x,y,color)` | 855 | Single drag-handle square |
| `drawMarkers2d(p,hoverState)` | 860 | Render all marker groups onto `markersCanvas` |

#### Zoom model (Rule 4 in detail)
`_imgFitRect(iw, ih, cw, ch)` is computed once per draw and shared by all
geometry functions.  At `zoom=1` the entire image fills the fit-rect exactly.
At `zoom=Z>1` a `iw/Z × ih/Z` pixel region of the image fills the fit-rect.

**`_blit2d`** (line 518):
```
zoom ≥ 1  →  ctx.drawImage(bitmap, srcX, srcY, visW, visH,  fr.x, fr.y, fr.w, fr.h)
zoom < 1  →  ctx.drawImage(bitmap,   0,   0,  iw,  ih,   centredShrink...)
```
Background (`bgCanvas` colour) is always visible outside the fit-rect,
so letterboxing/pillarboxing is correct at all zoom levels.

---

### 3D drawing (lines 957–1159)
Orthographic projection. State fields: `st.vertices`, `st.faces`,
`st.face_values`, `st.colormap_data`, `st.azimuth`, `st.elevation`, `st.scale`.

| Function | Lines | Purpose |
|----------|-------|---------|
| `_rot3(az,el)` | 959 | 3×3 rotation matrix |
| `_applyRot(R,v)` | 972 | Rotate a 3-vector |
| `_project3(rv,cx,cy,scale)` | 980 | Orthographic 3D→2D |
| `_colourFromLut(lut,t)` | 985 | `t∈[0,1]` → `'#rrggbb'` |
| `draw3d(p)` | 993 | Sort triangles, fill + stroke, draw axis labels |

---

### Event emission helper (lines 1160–1171)
```js
_emitEvent(panelId, eventType, widgetId, extraData)
```
Writes to `model.event_json` + `save_changes()`.
`eventType`: `'on_changed'` | `'on_release'` | `'on_click'`.

---

### 3D event handlers (lines 1172–1238)
- **`_attachEvents3d(p)`** — drag → azimuth/elevation; scroll → zoom.

---

### 1D drawing (lines 1239–1497)

| Function | Lines | Purpose |
|----------|-------|---------|
| `_plotRect1d(pw,ph)` | 1241 | `{x,y,w,h}` of the plot rectangle |
| `_xToFrac1d` / `_fracToX1d` | 1243/1252 | x data ↔ [0,1] fraction |
| `_fracToPx1d`, `_valToPy1d` | 1257/1258 | fraction/value → canvas px |
| `draw1d(p)` | 1260 | Main 1D render: series, axes, ticks, grid |
| `drawOverlay1d(p)` | 1383 | Overlay widgets on `overlayCanvas` |
| `drawMarkers1d(p,hoverState)` | 1424 | Marker groups for 1D panels |

---

### Marker hit-test helpers (lines 1498–1617)
| Function | Lines | Purpose |
|----------|-------|---------|
| `_markerHitTest2d(mx,my,st,pw,ph)` | 1503 | → `{si,i}` hit marker for 2D; uses `_imgFitRect` via `_imgToCanvas2d` |
| `_markerHitTest1d(mx,my,p)` | 1571 | → `{si,i}` hit marker for 1D |

---

### Panel-level event handlers (lines 1618–1805)
- **`_attachPanelEvents(p)`** (line 1619) — dispatches to kind-specific attach fn.
- **`_canvasToImg2d(px,py,st,pw,ph)`** (line 1626) — inverts `_imgToCanvas2d` exactly;
  uses the zoom≥1 pan/crop formula or the zoom<1 centred-shrink inverse so both
  directions are always consistent with `_blit2d`.
- **`_attachEvents2d(p)`** (line 1636) — 2D mouse events:
  - **Wheel zoom** — calls `_canvasToImg2d` to find the image-space anchor
    before zoom; recomputes `center_x/y` via `_imgFitRect` so the same image
    point stays under the cursor after the zoom change.
  - **Pan** — drag delta divided by `fr.w/fr.h` (fit-rect dimensions, not
    canvas dimensions) so pan speed is proportional to the visible image region.
  - Widget drag, marker hover, status bar, keyboard shortcuts (r/c/l/s).
- **`_attachEvents1d(p)`** (line 1806) — scroll zoom on `view_x0/x1`, pan,
  widget drag, marker hover, status bar.

---

### 2D / 1D Overlay Widget Drag (lines 1910–2131)
| Function | Lines | Purpose |
|----------|-------|---------|
| `_ovHitTest2d(mx,my,p)` | 1921 | Find 2D widget under cursor; scale via `_imgScale2d(st,imgW,imgH)` |
| `_pointInPolygon2d(…)` | 1992 | Polygon hit-test in image space |
| `_doDrag2d(e,p)` | 2002 | Drag 2D widgets; uses `_canvasToImg2d` for coordinates |
| `_canvasXToFrac1d(px,x0,x1,r)` | 2078 | Canvas x → axis fraction |
| `_ovHitTest1d(mx,my,p)` | 2080 | Find 1D widget under cursor |
| `_doDrag1d(e,p)` | 2107 | Drag 1D widgets |

---

### Shared-axis propagation (lines 2132–2172)
- **`_getShareGroups()`** — groups panels by `st.share_axes`.
- **`_propagateZoom2d(srcPanel)`** — copies `zoom/center_x/center_y` to share group.
- **`_propagateView1d(srcPanel)`** — copies `x0/x1/y_min/y_max` to share group.

---

### Figure-level resize (lines 2173–2342)
- **`_applyFigResizeDOM(nfw,nfh)`** (line 2193) — pure proportional scaling of
  all panel tracks (`col_px = nfw * ratio / sum`); **no aspect-lock loop**.
  CSS-only resize (no canvas buffer clear) for smooth live drag.
- **`_resizePanelCSS(id,pw,ph)`** (line 2235) — updates CSS + element positions.
- **`_applyFigResize(nfw,nfh)`** (line 2286) — full resize: DOM + pixel buffers + redraw.

---

### Bar chart (lines 2803–2970)

State fields:
```
st.values        [[g0,g1,...], ...]  always 2-D (N×G) list; G=1 for ungrouped
st.groups        int — number of bar groups per category slot (≥1)
st.x_centers, st.x_labels
st.bar_color, st.bar_colors   (ungrouped: per-bar colours)
st.group_colors  list[str], length G — colour per group; overrides bar_color
st.group_labels  list[str], length G — legend labels (shown when groups > 1)
st.bar_width     fraction of slot occupied by all bars in the slot (0–1)
st.orient        'v' (default) | 'h'
st.baseline      value-axis root; skipped for log scale
st.log_scale     bool — logarithmic value axis; non-positive values clamped to 1e-10
st.data_min/max  current visible value-axis range
st.x_axis, st.view_x0/x1   widget coordinate system (category axis)
st.overlay_widgets
```

| Function | Lines | Purpose |
|----------|-------|---------|
| `_barGeom(st,r)` | ~2808 | Per-bar geometry: slot/group pixel sizes, `xToPx`/`yToPx`, `groupOffsetPx(g)`, `getVal(i,g)`, log-scale coordinate mappers, `basePx` |
| `drawBar(p)` | ~2870 | **Main bar render**: log/linear grid, grouped bars (clipped), value labels, axis borders, log/linear ticks, group legend |
| `_attachEventsBar(p)` | ~2977 | **Full interaction**: widget drag, hover/tooltip (shows group label), `on_click` (emits `bar_index`, `group_index`, `value`, `group_value`), keyboard |

#### `_barGeom` — grouped geometry

For *G* groups per category and bar-width fraction *w*:
```
slotPx  = (r.w or r.h) / n              — pixel width of one category slot
barPx   = slotPx * w / G               — pixel width of a single bar
groupOffsetPx(g) = (g - (G-1)/2) * barPx  — centre offset for group g
```
`getVal(i, g)` reads from `st.values[i][g]` (2-D) or legacy `st.values[i]`
(scalar) so old 1-D state still renders correctly.

#### Log scale

When `st.log_scale` is true `yToPx`/`xToPx` use `Math.log10` internally:
```js
lv = Math.log10(Math.max(1e-10, v))
py = r.y + r.h - ((lv - lMin) / (lMax - lMin)) * r.h
```
Grid lines: faint minor lines at 2×, 3×, 5× per decade; full-opacity major
lines at each power of 10.  Tick labels use superscript notation (`10^N`).

#### Bar zoom/pan model (unchanged)
Unlike 1D (which zooms `view_x0/x1`), bar zooms/pans the **value axis** by
modifying `st.data_min`/`st.data_max` directly.  `view_x0/x1` stays fixed
at 0/1 so overlay widgets keep correct positions throughout.

#### `on_click` event payload
```js
{ bar_index, group_index, value, group_value, x_center, x_label }
```
`group_index` is always 0 for ungrouped charts.  `group_value` equals
`value` (alias for convenience).


---

### Generic redraw (lines 2698–2710)
```js
_redrawPanel(p)  →  draw2d / draw3d / drawBar / draw1d  based on p.kind
redrawAll()      →  _redrawPanel for every panel
```

---

### ResizeObserver — cell-fit (lines 2711–2801)
Watches `el`. If cell is narrower than the widget, scales figure down,
persists into `layout_json`. 150 ms debounce; `_roActive` re-entry guard.

---

### Model listeners + initial render (lines 2802–2812)
```js
model.on('change:layout_json')              → applyLayout() + redrawAll()
model.on('change:fig_width/height')         → applyLayout() + redrawAll()
model.on('change:event_json')               → Python→JS widget position push
                                              (only when msg.source === 'python')
applyLayout()   ← initial call
```

---

## Key data flows

```
Python push:
  plot._push() → figure._push(id) → panel_{id}_json trait changes
  → model.on('change:panel_{id}_json') → p.state = JSON.parse(...)
  → _redrawPanel(p)

JS → Python (widget drag):
  _doDrag2d / _doDrag1d → updates p.state.overlay_widgets in-place
  → _emitEvent(id, 'on_changed', widgetId, {…})
  → model.set('event_json', …) + save_changes()
  → Python Figure._on_event() → CallbackRegistry.fire()

JS → Python (3D rotate / zoom):
  _attachEvents3d → model.set('panel_{id}_json', …) + save_changes()

Python → JS (set widget position from Python):
  figure.move_widget(…) → event_json with source:'python'
  → model.on('change:event_json') patches overlay_widgets + redraws
```

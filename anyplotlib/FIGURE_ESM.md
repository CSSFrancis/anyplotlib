# FIGURE_ESM.md — Navigator for `figure_esm.js`

`figure_esm.js` is **~4,640 lines** and one big closure. Everything lives inside
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
| **3D drawing**: `draw3d` | 1833 |
| Event emission `_emitEvent` | 2031 |
| 3D event handlers `_attachEvents3d` | 2059 |
| **1D drawing**: `draw1d` | 2177 |
| `drawOverlay1d` / `drawMarkers1d` | 2516 / 2586 |
| Marker hit-test `_markerHitTest2d` | 2787 |
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
Also creates/updates inset panels from `inset_specs`.

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

## 3D drawing (line 1833)
Orthographic projection; geometry b64-decoded and cached.  `draw3d` sorts
triangles, draws axes with per-axis `_drawTex` labels (`x/y/z_label_size`).

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

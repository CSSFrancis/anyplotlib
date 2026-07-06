# Large-image WebGPU 2D rendering + binary transport — scoping document

Status: **Phase 0 + core Phase 1/2 DONE, hardware-verified** (2026-07-06). Branch:
`feat/webgpu-2d-images`. Owner: @CSSFrancis

## DONE (verified on an NVIDIA Pascal GPU via the SpyDE Electron consumer)
- **WebGPU 2-D image render path**: a `gpuCanvas` below `plotCanvas`; the normalized
  uint8 frame → R8 texture, the 256-entry colormap → a 256×1 RGBA LUT texture, a
  fullscreen-quad WGSL fragment shader re-stretches by clim (dmin/dmax uniform) and
  samples the LUT. Replaces the 64M-iteration Canvas2D atob+LUT loop with one GPU draw.
- **Reuses the 3D contract**: the `_gpuDevice()` singleton, first-frame-canvas-then-
  async-swap, `device.lost` → permanent Canvas2D fallback (extended to 2-D panels).
- **API**: `imshow(..., gpu="auto"|True|False)` → `gpu_mode`; `GPU_IMAGE_THRESHOLD`
  (~1 Mpx) auto-gate; `plot.gpu_active` echo via the `gpu_status` event.
- **Fallback intact**: RGB images, sub-threshold images, `gpu=False`, and no-device
  all render on Canvas2D (anyplotlib suite green; the DOM keeps `plotCanvas` first so
  `querySelector('canvas')` still resolves the image canvas).
- **Correctness (review-hardened)**: the shader is a plain IDENTITY LUT lookup —
  `_buildLut32` already bakes clim + scale_mode into the LUT, so the shader must NOT
  re-apply the window (an earlier version double-applied clim; correct only at
  full-range, wrong for any narrowed contrast/log/symlog — fixed). A zoomed/panned
  view falls back to Canvas2D so the base image stays registered with the axes/
  overlays (the GPU quad is full-extent). Nearest sampling on both textures matches
  Canvas2D's `imageSmoothingEnabled=false` pixel-for-pixel.
- **Verification**: `__apl_gpuReadback` renders the active panel to an OFFSCREEN
  texture (the live swapchain reads black under automation) and copies it to CPU.
  On a real 4k movie frame: min 0 / max 255 / 96% non-black / correct gray values.
  A **narrowed clim [0.3,0.7]** matches the numpy windowed-colormap to meanDiff
  0.65/255 (regression guard for the double-apply bug; `tests/_gpu_clim_check.cjs`).
  Movie scrub + playback re-upload the texture per frame and stay correct (5/5
  scrub, 5 distinct played frames). GPU resources are freed on panel close / figure
  dispose / device loss (no leak on repeated large-image open/close).

## DEFERRED (documented; not blockers now)
- **Mipmaps** (smooth downscale-on-zoom): the sampler uses `minFilter:'linear'`
  without a mip chain. Marginal here because LOD already caps the uploaded texture
  near display size; matters for deep zoom-out. Needs an R8 render-based mip chain.
- **Binary pixel transport** (base64-in-JSON → binary buffer): the Phase-0 headline,
  but LOD decimation already cut the shipped payload ~35× (≤1536 px, ~2 MB not
  ~85 MB) and the GPU shader removed the render cost, so this is now an incremental
  transport optimization spanning Jupyter/Pyodide/standalone/Electron — do it with
  the multi-environment verification it needs.

Prerequisite reading: `WEBGPU_PLAN.md` (the 3D points/voxels WebGPU path this extends),
`anyplotlib/FIGURE_ESM.md` (the `figure_esm.js` section map), `AGENTS.md` (repo conventions).
Prerequisite reading: `WEBGPU_PLAN.md` (the 3D points/voxels WebGPU path this extends),
`anyplotlib/FIGURE_ESM.md` (the `figure_esm.js` section map), `AGENTS.md` (repo conventions).

This extends the repo's existing hardware-verified `WEBGPU_PLAN.md` (3D instanced points +
voxels) to **2D large images**, deliberately lifting that doc's "No 2D pipeline changes"
non-goal (§2). Motivating consumer: a SpyDE in-situ movie viewer that must scrub/play through
8k×8k image frames smoothly.

## 1. Goal

Render **large 2D image frames** (up to 8k×8k) interactively — smooth scrub/playback of a
frame stream and smooth zoom — by moving the 2D image path from Canvas2D to **WebGPU** (texture
upload + WGSL colormap LUT + mipmap downscale) and moving the pixel bytes off **base64-in-JSON**
onto a **binary transport**.

| Workload | Today (Canvas2D) | Target (WebGPU) |
|---|---|---|
| 8k×8k frame colormap+draw | ~64M-iter JS LUT loop → OffscreenCanvas | shader LUT, **<5 ms** |
| Scrub (new frame/tick) | ~85 MB base64/frame + full rebuild | binary uint8 + texture upload, **≥15–30 fps** |
| Zoom-in on a still | re-blit from OffscreenCanvas | GPU **mipmap**, **60 fps** |

## 2. Non-goals

- **Not** replacing Canvas2D for images — it stays the universal baseline, the fallback, the
  small-image path, and the fully-CI-tested path. Default behaviour for small images is
  byte-identical to today.
- No WebGL2, no three.js, no bundler — raw WebGPU + inline WGSL, mirroring `WEBGPU_PLAN.md`.
- 1D lines / bars stay Canvas2D. Only the 2D **image** path is affected.

## 3. Coverage & the fallback contract

Inherited verbatim from `WEBGPU_PLAN.md` §3: WebGPU is a progressive enhancement. `navigator.gpu`
present → `requestAdapter()` resolves → device created → *then* a panel may switch. Any failure at
any point (including mid-session device loss) lands on the Canvas2D path silently and permanently
for that session. **A figure must never render nothing because GPU was attempted.**

## 4. Reuse (do NOT rebuild)

- **Device singleton + fallback state machine**: `_gpuDevice()` (`figure_esm.js` ~L1955,
  module-level `_gpuDevicePromise`), the `p._gpu ∈ {pending,active,unavailable}` per-panel state,
  the "first frame always Canvas2D → swap on device resolve" pattern, and `device.lost` → permanent
  per-session Canvas2D. All proven by the 3D path — the 2D image path plugs into the exact same
  machinery.
- **The `gpuCanvas`-below-`plotCanvas` split**: decorations (axes, ticks, colorbar, scale bar,
  overlay mask, markers, widgets) keep drawing on the 2D `plotCanvas` **verbatim** — only the image
  raster moves to `gpuCanvas`. Mirrors `WEBGPU_PLAN.md` §4.3.
- **`gpu_mode` / `_gpu_active` plumbing**: the state field + echo already exist (`st.gpu_mode`,
  ~L1998). Add an image-megapixel `GPU_IMAGE_THRESHOLD` alongside the existing point threshold.
- **The zoom/letterbox model**: `_imgFitRect` (~L1262) — the GPU draw honors the same fit-rect /
  `zoom` semantics; no new zoom math.
- **The colormap LUT**: `_build_colormap_lut` (`_utils.py:118`) → `st.colormap_data`
  ([[r,g,b]×256]) already ships to JS. Upload it as a 256×1 texture; the shader samples it.
- **The normalized payload**: `set_data` already produces `img_u8` (single-channel uint8 via
  `_normalize_image`, `_utils.py:82`) + `display_min/max` (clim) + `raw_min/max`. The WebGPU path
  uploads that **same uint8** (8× smaller than raw float64; keeps current visual behaviour) as an
  **R8 texture**; the shader does the clim re-stretch + LUT — exactly what the JS loop at
  `draw2d` L1379–1381 does today, but on the GPU.

## 5. The function being replaced

`draw2d` (`figure_esm.js` ~L1344): today it `atob`-decodes `image_b64`, runs a per-pixel LUT loop
(L1379–1381, 64M iters at 8k) into an `OffscreenCanvas` 2D context, caches the bitmap in
`blitCache`, and `_blit2d`-down-blits to the panel. The WebGPU path replaces the decode+LUT+blit
with: upload R8 texture → WGSL fragment shader (clim uniform + LUT texture) → mipmapped textured
quad over the `_imgFitRect`. `blitCache`'s "bytes unchanged → reuse" logic maps to "texture
unchanged → skip re-upload". Canvas2D `draw2d` remains as the fallback when `p._gpu !== 'active'`.

## 6. Binary transport (generalize `WEBGPU_PLAN.md` §4.7 to images)

Today `set_data` → `_encode_bytes(img_u8)` → `image_b64` string on the `panel_<id>_geom` trait
(base64-in-JSON). Change: send the raw `img_u8` **bytes** as an anywidget **binary buffer**
(`_repr_utils._widget_state` already handles `bytes`; the geom-trait split already isolates heavy
keys — `FIGURE_ESM.md` ~L237), with a small JSON header (`image_width/height`, `display_min/max`,
`raw_min/max`, dtype, an optional `lod` level). Keep base64 for **small images and the
standalone/Pyodide/`save_html` paths** (no binary channel there). Keep `FigureBridge` (`embed.py`)
transport-agnostic so an Electron embed can supply an even faster channel (shared memory / a
transferable `ArrayBuffer`) without the library caring. JS: pick up the binary buffer, upload to
the GPU texture; on the Canvas2D fallback, build the `ImageData` from the same bytes (no atob).

## 7. API surface

- `Axes.imshow(..., gpu="auto"|True|False)` and `Plot2D.set_data(..., gpu=...)` — mirror
  `scatter3d`/`voxels`. Default `"auto"`: attempt WebGPU only above `GPU_IMAGE_THRESHOLD`
  (initial ~4 megapixels — below it Canvas2D is already instant). `True` forces an attempt (still
  falls back); `False` never attempts.
- `plot.gpu_active` — bool echo after first render (reuse `_gpu_active`).
- Optional `set_data(..., lod=k)` affordance so a consumer can mark a frame as decimated (scrub)
  vs full-res (settle); at minimum, an uploaded full-res texture gets **free** GPU downscale-on-zoom
  via mipmaps, so LOD-on-zoom needs no consumer work.

## 8. Phases (with decision gates, mirroring WEBGPU_PLAN.md style)

### Phase 0 — Binary transport + minimal GPU texture-blit (risk-retire; do first)

Add the binary image trait + header (keep b64 fallback). Add a minimal WebGPU 2D image pipeline:
R8 texture + 256×1 LUT texture + clim uniform + a textured quad over `_imgFitRect`, **no mipmaps
yet**. Verify a single static 8k image renders identically to Canvas2D via **offscreen-texture
readback** (the 3D path's proven test method — the WebGPU swapchain doesn't snapshot reliably under
automation, per `FIGURE_ESM.md` ~L256).

**Gate A:** GPU image matches Canvas2D within tolerance on a real GPU, and `gpu=False`/adapter-absent
renders identically via Canvas2D (automated).

### Phase 1 — Mipmaps + zoom + scrub

Generate mipmaps on upload; sample with trilinear filtering so zoom-out/downscale is smooth and
zoom-in honors `_imgFitRect`. Wire the scrub path: new bytes → texture re-upload (reuse
`blitCache`-style "unchanged → skip").

**Acceptance:** 8k still zooms at 60 fps; a frame stream scrubs ≥15–30 fps on a real GPU; benchmark
`js_gpu_image_8k` recorded.

### Phase 2 — API + fallback hardening + tests

`gpu="auto"|True|False` on `imshow`/`set_data`, `GPU_IMAGE_THRESHOLD`, `plot.gpu_active`, optional
`lod=`. Canvas2D-parity tests in the normal suite (assert `_gpu_active` false + pixel parity when
GPU absent); flagged headless-GPU smoke job (skip-on-null-adapter); `upcoming_changes/*.rst`
towncrier fragment.

**Gate B:** full fallback matrix green (adapter-absent, mid-session device loss via forced
`device.destroy()`, `gpu=False`) + real-GPU image benchmark, before this is released.

### Phase 3 (gated) — raw-float precision path

If uint8 quantization proves visibly lossy for scientific contrast adjustment, add an optional R32F
texture upload (raw floats, 4× bytes) with the clim applied in-shader over true data range. Only
build on a concrete need (Gate C).

## 9. Biggest risks / do-not-break

- **The 3D WebGPU path and the Canvas2D 2D path must not regress** — the 2D image GPU path is
  additive and plugs into the shared `_gpuDevice()` singleton; keep the device/fallback code shared,
  not forked.
- **Canvas2D stays the default + fallback forever** — no figure may render nothing because GPU was
  attempted (the `WEBGPU_PLAN.md` §3 contract).
- **Automation can't snapshot the WebGPU swapchain** — test via offscreen-texture readback or state
  echo, not screenshot diffing of the live canvas (per `FIGURE_ESM.md`).
- **Small-image / standalone / Pyodide paths unchanged** — binary transport is large-image-only;
  b64 remains for the rest.
- Repo norms (`AGENTS.md`): OO API only, state in `_state` dicts (no new traitlets on Plot2D — the
  Figure adds panel traits dynamically), end every `_state` mutation with `_push()`, `uv run
  pytest`, `uv run playwright install chromium` first, add the towncrier fragment.

## 10. Verify

`uv run pytest` (Canvas2D parity + fallback in the normal suite); the flagged GPU smoke job;
offscreen-readback comparison GPU-vs-Canvas2D on a large image; `js_gpu_image_8k` benchmark on a
real-GPU machine; a manual Electron-embed pass (the real consumer) once SpyDE pins the new version.

## 11. API sketch

```python
# Python
plot = ax.imshow(frame, gpu="auto")     # auto-attempt WebGPU above GPU_IMAGE_THRESHOLD
plot.set_data(next_frame, clim=(lo, hi))  # scrub: binary bytes → texture re-upload
plot.set_data(decimated, lod=2)          # scrub-time LOD hint (optional)
plot.gpu_active                          # bool, after first render echo
```

```js
// JS internals (figure_esm.js)
_gpuDevice()                 // existing module singleton → Promise<GPUDevice|null>
p._gpu                       // 'pending' | 'active' | 'unavailable' (existing)
_buildImagePipeline(device, p)   // NEW: R8 sampled texture + LUT texture + clim uniform
_drawGpu2d(p)                    // NEW: image raster on gpuCanvas; decorations still 2D via draw2d
```

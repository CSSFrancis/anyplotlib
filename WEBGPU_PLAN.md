# WebGPU-on-demand rendering — scoping document

Status: **Phases 1–2 prototyped & hardware-verified** (2026-06-13).
Instanced points (Phase 1) and voxels (Phase 2) render on the GPU with
canvas fallback; projection + shaders validated on an NVIDIA Pascal GPU via
offscreen-texture readback. Remaining: binary-trait transport for >200k
payloads, the flagged CI smoke job, and Phase 3 (OIT translucency).
Owner: @CSSFrancis
Prerequisite reading: `anyplotlib/FIGURE_ESM.md` (3D drawing, voxels, plane widgets)

## 1. Goal

Render **large point clouds and voxel volumes** interactively — targets:

| Workload | Today (Canvas2D) | Target (WebGPU) |
|---|---|---|
| `scatter3d` points | ~50k usable | **1M @ ≥30fps** |
| `voxels` cubes | ~10k (≤30k after Phase 0) | **500k @ ≥30fps** |
| Plane-drag re-slice | O(N) re-blit | **uniform update, 60fps at any N** |

…without causing problems: every figure must keep working everywhere it works
today (Jupyter, Pyodide docs, Electron embed, headless CI), with no new JS
dependencies and no behaviour change for users below the GPU threshold.

## 2. Non-goals

- **Not** replacing Canvas2D — it remains the universal baseline, the
  fallback, the small-N path, and the fully-CI-tested path, forever.
- **No WebGL2** — we go straight to WebGPU; maintaining three paths is worse
  than two. (Decided 2026-06: choosing in 2026, not 2023.)
- **No three.js / no bundler** — raw WebGPU API, WGSL shaders as inline
  strings in the single-file ESM.
- **No 2D pipeline changes** — images/lines/bars stay Canvas2D.
- **No WebGPU compute in early phases** (see Phase 4).

## 3. Coverage & the fallback contract

As of mid-2026: Chromium Win/Mac/Android and Electron ✓ (since 2023/24),
Safari ≥26 ✓ (Sept 2025), Firefox Windows ✓ / macOS recent / Linux rolling
out, Chrome Linux driver-dependent. Weak populations for *our* users: Linux
workstations, remote-desktop/VM sessions (no adapter even in supporting
browsers), older Safari. Estimated 15–25 % of scientific users today.

**Contract:** WebGPU is a progressive enhancement. `navigator.gpu` present
→ `requestAdapter()` resolves → device created → *then* a panel may switch.
Any failure at any point (including mid-session device loss) lands on the
Canvas2D path silently and permanently for that session. A figure must never
render nothing because GPU was attempted.

## 4. Architecture

### 4.1 Activation policy

- Python: `gpu="auto" | True | False` kwarg on `scatter3d()` / `voxels()`
  → state field `gpu_mode`. Default `"auto"`.
- JS (`auto`): attempt WebGPU only when `vertices_count > GPU_THRESHOLD`
  (initial: 20 000 — at/below this Canvas2D is already smooth, so the
  fallback population loses nothing). `True` forces an attempt at any count
  (still falls back); `False` never attempts.

### 4.2 Device lifecycle (the async-init problem)

- One **module-level singleton** `_gpuDevicePromise` (adapter + device
  requested once per page, on first demand).
- Per-panel state `p._gpu ∈ {undefined, 'pending', 'active', 'unavailable'}`.
- First frame is ALWAYS Canvas2D (render() stays synchronous). When the
  device promise resolves, the panel builds its buffers/pipeline, flips to
  `'active'`, and redraws; on rejection → `'unavailable'`.
- `device.lost.then(...)`: mark every GPU panel `'unavailable'`, drop GPU
  resources, redraw via Canvas2D. Never re-attempt within the session.

### 4.3 Canvas split — decorations stay 2D

Add one `gpuCanvas` to the 3D panel stack, *below* `plotCanvas`:

```
gpuCanvas      (WebGPU)   geometry only: instanced points / cubes
plotCanvas     (2D ctx)   axes, ticks, labels (_drawTex), reference sphere,
                          plane-widget quads, highlight — unchanged code,
                          drawn on a now-transparent background
overlayCanvas / markersCanvas / statusBar — unchanged
```

This is the key cost-control decision: **all decoration, label, TeX, sphere,
plane-widget, and highlight code is reused verbatim**; only the instanced
geometry moves to the GPU. The camera matrix is shared (same turntable
`_rot3` semantics → one orthographic view-projection matrix uniform).

### 4.4 Pipelines

- **Points**: instanced screen-facing quads (point_size px), per-instance
  position (f32×3) + colour (unorm8×4). Fragment discards outside the disc.
- **Voxels**: one 36-vertex cube, instanced; per-instance position + colour.
  Per-face shading via vertex normals (match the 0.82/0.68/1.0 canvas look).
  Depth buffer → **no sorting at all**.
- **Slice emphasis & planes as uniforms**: plane axis/position/count go into
  a uniform buffer; the fragment shader computes emphasis
  (`|pos[axis] − plane| ≤ size/2`). Plane drags therefore re-render with a
  **uniform write only** — no geometry re-upload, no Python round-trip
  needed for the visual.
- Wire format already fits: `vertices_b64` (f32) and `point_colors_b64` (u8)
  upload to GPUBuffers unchanged.

### 4.5 Transparency strategy

- Phase 1–2 GPU mode is **opaque** (depth-tested). For ≥100k elements this
  reads *better* than alpha soup; it differs visually from the canvas
  translucent look — documented, and `voxel_alpha` still applies on the
  canvas path.
- Phase 3 adds weighted-blended OIT (two extra render targets + composite
  pass) to restore the translucent-volume aesthetic at scale. Gate: only
  build if genuinely needed after using opaque mode in practice.

### 4.6 Capability feedback → adaptive budgets (Python)

JS reports the outcome once per panel via the existing state echo: a
`_gpu_active: true|false` field written into the panel state (no new event
type needed). Python exposes `plot.gpu_active`. The resampling helper
(Phase 0) uses it: send full-resolution boundary voxels to GPU clients,
auto-stride to ≤20k for canvas clients. **No client ever receives a payload
it can't render.**

### 4.7 Payload reality check (often the real bottleneck)

1M points = 12 MB f32 → ~16 MB as b64-in-JSON through the comm. Phase 2
includes moving large geometry to **binary traits** (ipywidgets/anywidget
support binary buffers; `_repr_utils._widget_state` already handles `bytes`)
with b64 kept for small payloads and the standalone/Pyodide paths. Without
this, the wire — not the GPU — caps practical sizes around ~200k points.

## 5. Phases

### Phase 0 — Canvas cheats + resampling API (no GPU code; do first)
*~2–3 days. Worth shipping regardless of WebGPU.*

1. Interaction LOD: stride the draw set 2–4× while a drag is active; full
   set on release/settle.
2. Analytic back-to-front order for grid voxels (camera octant → lexicographic
   traversal; kills the O(n log n) sort).
3. Layered plane-drag cache: bake the translucent base cloud to a bitmap;
   redraw only the emphasized slice voxels per drag frame.
4. `Axes.voxels_from_volume(vol, *, max_voxels=15000, mode="boundary"|"stride",
   colors=...)` — formalises the explorer example's hand-rolled extraction.

**Acceptance:** 25–30k voxels orbit smoothly on canvas (bench: orbit ≤35 ms
software); plane drag ≤10 ms at 20k; new benchmarks committed.

### Phase 1 — GPU infrastructure + instanced points
*~4–5 days. The risk-retiring phase.*

Device singleton, `gpuCanvas` stack integration, async swap, device-lost
fallback, `gpu_mode`/`_gpu_active` plumbing, instanced point pipeline.

**Acceptance:**
- 1M points orbit ≥30fps on a real GPU (manual + flagged CI job).
- Kill switch verified: adapter-absent, mid-session device loss, and
  `gpu=False` all render identically to today via canvas (automated).
- Embedding `mount()` and the Pyodide docs page work in GPU mode
  (verify WebGPU inside the gallery iframes — srcdoc/permission policy).

### Phase 2 — Instanced voxels + shader slice emphasis + binary traits
*~3–4 days.*

Cube pipeline, plane uniforms (emphasis in-shader), plane-drag = uniform
update, binary-trait transport for large buffers.

**Acceptance:** 500k cubes orbit ≥30fps; plane drag 60fps at 500k; voxel
grain explorer runs a 192³-extracted volume (~150k boundary voxels) live.

### Phase 3 — Translucency (weighted-blended OIT) *(gated)*
*~4–6 days. Only if opaque mode proves insufficient in real use.*

**Acceptance:** GPU translucent render within visual tolerance of the canvas
look at N ≤ 4k (screenshot comparison), correct at 500k.

### Phase 4 — Future options *(not scoped)*
GPU compute culling/LOD, surfaces/lines on GPU, picking via ID buffer.

## 6. Testing & CI strategy

- **Canvas path keeps 100 % of today's coverage** and remains the default CI
  matrix — GPU never reduces existing test fidelity.
- New **flagged headless GPU smoke job** (ubuntu): Chromium with
  `--enable-unsafe-webgpu --enable-features=Vulkan` on lavapipe/SwiftShader-
  Vulkan; tests `pytest.skip` cleanly when `requestAdapter()` yields null so
  the job can never hard-fail on runner GPU availability.
- Fallback tests run in the NORMAL suite (no flags): assert `_gpu_active`
  is false and rendering matches canvas baselines when GPU is absent —
  this is the path that protects "no problems".
- Benchmarks: `js_gpu_points_1M`, `js_gpu_voxels_500k` added to the existing
  hardware-gated baseline framework (recorded on a real-GPU machine).
- Phase 3 parity: SSIM-style screenshot comparison GPU vs canvas at small N.

## 7. Risks

| Risk | Severity | Mitigation |
|---|---|---|
| Async init race / blank first paint | High | First frame always canvas; swap on resolve; `'pending'` state |
| CI has no GPU adapter | High | Skip-on-unavailable smoke job; canvas keeps full coverage |
| Device lost mid-session | Med | Permanent per-session fallback; tested by forcing `device.destroy()` |
| Comm payload size (≥200k pts) | High | Phase 2 binary traits; capability-aware resampling caps payloads |
| Opaque-vs-translucent visual surprise | Med | Document; Phase 3 OIT; `gpu=False` escape hatch |
| WebGPU inside docs iframes (permission policy) | Med | Verify in Phase 1 acceptance; fall back if blocked |
| Safari/WGSL implementation quirks | Low-Med | Stick to core WGSL, no extensions; manual Safari pass per phase |
| Two render paths drift apart | Med | Shared camera/constants; parity screenshots; FIGURE_ESM.md section per path |

## 8. Decision gates

- **Gate A (after Phase 0):** if resampled canvas + linked slices satisfies
  the 512×512×300 workflow in practice, pause here — GPU work is demand-
  driven, not speculative.
- **Gate B (after Phase 1):** confirmed-working fallback matrix + real-GPU
  point benchmark before any voxel pipeline work.
- **Gate C (before Phase 3):** a concrete use case that opaque mode cannot
  serve.

## 9. API sketch

```python
# Python
plot = ax.voxels_from_volume(gid_volume, max_voxels=15_000,
                             mode="boundary", colors=grain_rgb)   # Phase 0
plot = ax.voxels(x, y, z, colors=c, gpu="auto")                    # Phase 2
plot.gpu_active          # bool, after first render echo
plot = ax.scatter3d(x, y, z, colors=c, gpu=True)                   # Phase 1
```

```js
// JS internals (figure_esm.js)
_gpuDevice()             // module singleton → Promise<GPUDevice|null>
p._gpu                   // 'pending' | 'active' | 'unavailable'
_buildPointPipeline(device, p) / _buildVoxelPipeline(device, p)
_drawGpu3d(p)            // geometry; decorations still drawn by draw3d's 2D code
```

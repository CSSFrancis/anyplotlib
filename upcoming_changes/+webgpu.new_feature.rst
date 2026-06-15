3-D ``scatter3d`` and ``voxels`` now render on the GPU via WebGPU when
available, as a transparent progressive enhancement: a ``gpu="auto"`` kwarg
(default) uses instanced WebGPU rendering above ~20k points / ~8k voxels and
falls back to Canvas2D otherwise or whenever a GPU is unavailable (no
``navigator.gpu``, null adapter, or device loss) — query the actual path via
``plot.gpu_active``.  Voxel slice emphasis and per-face shading are GPU
uniforms, so dragging a ``PlaneWidget`` re-renders without re-uploading
geometry.  Decorations (axes, labels, sphere, planes, highlight) always
render on the 2-D canvas, so visuals are identical to the fallback.  No new
JavaScript dependencies (raw WebGPU + inline WGSL).
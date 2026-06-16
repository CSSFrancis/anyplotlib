Fixed large voxel volumes (e.g. a 256³ grain explorer) rendering "empty" —
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

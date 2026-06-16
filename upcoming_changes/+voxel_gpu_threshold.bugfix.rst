Fixed large voxel volumes (e.g. a 256³ grain explorer) rendering as a sparse
scatter of "floating" cubes instead of solid slice slabs.  The Phase-1 WebGPU
voxel path is not hardware-verified in CI (headless Chromium exposes no WebGPU
adapter) and could leave a see-through volume on real GPUs; the auto threshold
for handing voxels to the GPU was raised so mid-size volumes stay on the
depth-sorted, visual-regression-tested Canvas2D path.  The GPU voxel path also
no longer back-face culls (cube winding isn't guaranteed under the projection's
row-swap, which dropped faces) and now keys its colour buffer on the colours,
so ``set_point_colors`` recolours voxels live.

Voxel rendering is ~2–3× faster: cubes render once per (colour, emphasis)
into sprites and are blitted per voxel with typed-array projection and
integer-snapped draws; camera-static redraws (plane-widget drags) reuse a
cached projection/depth-sort.  3-D interaction no longer double-draws —
self-originated model writes skip the panel-listener echo.  New voxel
benchmarks (``test_bench_voxels_orbit`` / ``_reblit``) guard the budget
(~3–6 µs/cube), and ``voxels()`` warns above ~20k cubes with downsampling
guidance for large volumes (e.g. 512×512×300 tomograms).  Local docs builds
now rebuild the Pyodide wheel when sources are newer, so the ⚡ interactive
mode never runs stale code.

"""
GPU-accelerated voxels
======================

:meth:`~anyplotlib.Axes.voxels` renders shaded translucent cubes for a
volumetric field.  With ``gpu="auto"`` (the default) anyplotlib uses WebGPU
instancing when a GPU is available and the cube count is large, so hundreds of
thousands of voxels stay interactive; otherwise it falls back to the Canvas2D
path.  Read :attr:`~anyplotlib.Plot3D.gpu_active` after the first frame to see
which path was chosen.

Here we build a dense spherical shell — enough cubes that the WebGPU path
kicks in — and drop a draggable :class:`~anyplotlib.PlaneWidget` through it as
a slice selector.
"""
import numpy as np
import anyplotlib as apl

# %%
# Build a volumetric field
# ------------------------
# Voxel *centres* are passed as three flat coordinate arrays (not a dense 3-D
# grid), so you only send the cubes you actually want drawn.  We keep the
# voxels inside a spherical shell and colour them by radius.

N = 64
g = np.arange(N)
Z, Y, X = np.meshgrid(g, g, g, indexing="ij")
r = np.sqrt((X - N / 2) ** 2 + (Y - N / 2) ** 2 + (Z - N / 2) ** 2)
shell = (r > N * 0.30) & (r < N * 0.42)   # a hollow sphere

xs, ys, zs = X[shell], Y[shell], Z[shell]
print(f"{xs.size:,} voxels")  # tens of thousands → GPU path under gpu='auto'

# Colour by radius with the viridis-ish default cycle mapped through intensity.
t = (r[shell] - r[shell].min()) / (np.ptp(r[shell]) + 1e-9)
colors = np.stack([0.2 + 0.8 * t, 0.4 * np.ones_like(t), 1.0 - 0.8 * t], axis=1)

fig, ax = apl.subplots(1, 1, figsize=(560, 520))
vol = ax.voxels(
    xs, ys, zs, colors=colors,
    size=1.0, alpha=0.35,
    bounds=((0, N - 1),) * 3,
    azimuth=-55, elevation=28, zoom=1.1,
    gpu="auto",                 # WebGPU when available, Canvas2D otherwise
)
vol.set_title("Spherical shell — drag to rotate, scroll to zoom")

# %%
# Add a slice-selector plane
# --------------------------
# A :class:`~anyplotlib.PlaneWidget` is a draggable axis-aligned plane.  Voxels
# lying on it render more opaque, so the current slice pops out of the
# translucent volume.  Drag it along z in the browser, or move it from Python.

plane = vol.add_widget("plane", axis="z", position=N // 2,
                       color="#40c4ff", alpha=0.18)


@plane.add_event_handler("pointer_move")
def _on_slice(event):
    # Fires while the plane is dragged; pw.position holds the live slice index.
    print("slice at z =", round(plane.position, 1))


fig.set_help(
    "Drag: rotate · Scroll: zoom · R: reset view\n"
    "Drag the blue plane to slide the z-slice through the shell."
)

fig  # Interactive

# %%
# Which render path ran?
# ----------------------
# ``gpu_active`` is populated once the browser reports back after the first
# frame.  It is ``True`` when the WebGPU instanced path is live, ``False`` on
# the Canvas2D fallback, and ``None`` before the first frame (as when this
# gallery page is built headlessly).  Force a path with ``gpu=True`` /
# ``gpu=False`` if you need determinism.

print("gpu_active:", vol.gpu_active)

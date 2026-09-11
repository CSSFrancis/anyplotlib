"""
3D Plane Widget
===============

A draggable axis-aligned plane in a 3-D panel, rendered as a translucent quad
spanning the panel's bounds.  Drag it in the browser to slide it along its
normal — ideal as a slice selector through a volume or point cloud.  Add it
with ``plot.add_widget("plane", axis=..., position=...)``.
"""
import numpy as np
import anyplotlib as apl

# %%
# A point cloud to slice
# ----------------------
# A Gaussian blob of points; the plane widget will pick out a z-slab.

rng = np.random.default_rng(0)
n = 4000
pts = rng.normal(0, 8, size=(n, 3)) + 24    # centred in a 0..48 box
xs, ys, zs = pts[:, 0], pts[:, 1], pts[:, 2]

fig, ax = apl.subplots(1, 1, figsize=(520, 500))
cloud = ax.scatter3d(xs, ys, zs, color="#4fc3f7", point_size=3,
                     x_label="x", y_label="y", z_label="z")

plane = cloud.add_widget("plane", axis="z", position=24,
                         color="#40c4ff", alpha=0.15)

fig

# %%
# Read the slice position on drag
# -------------------------------
# ``pointer_move`` fires as the plane slides; ``plane.position`` is the current
# location along its normal.  You can also move it from Python with
# ``plane.set(position=...)``.


@plane.add_event_handler("pointer_move")
def _on_drag(event):
    print("z-slice at", round(plane.position, 1))


fig.set_help("Drag the blue plane along z to move the slice.")

fig  # Interactive

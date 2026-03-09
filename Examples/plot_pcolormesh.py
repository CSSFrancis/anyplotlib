"""
pcolormesh — non-linear axes
============================

Demonstrate :meth:`~viewer.figure_plots.Axes.pcolormesh` with non-uniform
(log-spaced) x-edges and irregularly-spaced y-edges, mirroring
``matplotlib.axes.Axes.pcolormesh``.

The key difference from :meth:`~viewer.figure_plots.Axes.imshow` is that
``pcolormesh`` takes **edge** arrays (length N+1 and M+1 for an (M, N) data
array) rather than centre arrays.  This enables fully non-linear axes where
each cell can have a different width/height in data coordinates.
"""
import numpy as np
import viewer as vw

rng = np.random.default_rng(42)

# ── Data: 32 rows × 48 columns ───────────────────────────────────────────────
M, N = 32, 48
data = np.sin(np.linspace(0, 3 * np.pi, N)) + np.cos(np.linspace(0, 2 * np.pi, M))[:, None]
data += rng.normal(scale=0.15, size=(M, N))

# ── Non-uniform edges ─────────────────────────────────────────────────────────
# x: log-spaced between 0.1 and 100  (N+1 edges)
x_edges = np.logspace(-1, 2, N + 1)

# y: irregular spacing — dense in the middle, coarse at the ends (M+1 edges)
y_centres = np.concatenate([
    np.linspace(0, 40, M // 4, endpoint=False),
    np.linspace(40, 60, M // 2, endpoint=False),
    np.linspace(60, 100, M // 4),
])
y_edges = np.concatenate([[y_centres[0] - (y_centres[1] - y_centres[0]) / 2],
                           (y_centres[:-1] + y_centres[1:]) / 2,
                           [y_centres[-1] + (y_centres[-1] - y_centres[-2]) / 2]])

# ── Plot ──────────────────────────────────────────────────────────────────────
fig, ax = vw.subplots(1, 1, figsize=(560, 460))
mesh = ax.pcolormesh(data, x_edges=x_edges, y_edges=y_edges, units="arb.")
mesh.set_colormap("viridis")
fig

# %%
# Add point markers in physical coordinates
# -----------------------------------------
# Marker coordinates are in the same physical (data) space as the edges.
# Only ``add_circles`` and ``add_lines`` are available on a pcolormesh panel.

pts = np.array([[1.0, 20.0], [10.0, 50.0], [50.0, 80.0], [90.0, 45.0]])
mesh.add_circles(pts, name="peaks", radius=3,
                 edgecolors="#ff1744", facecolors="#ff174433",
                 labels=["A", "B", "C", "D"])
fig

# %%
# Add line-segment markers
# ------------------------
segs = [
    [[1.0, 20.0], [10.0, 50.0]],
    [[10.0, 50.0], [50.0, 80.0]],
]
mesh.add_lines(segs, name="path", edgecolors="#00e5ff", linewidths=2.0)
fig


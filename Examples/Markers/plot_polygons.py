"""
Polygons
========

Draw closed polygons on a 2-D image with
:meth:`~anyplotlib.figure_plots.Plot2D.add_polygons`.
Use ``markers["polygons"]["name"].set(...)`` to update them live.
"""
import numpy as np
import anyplotlib as vw

rng  = np.random.default_rng(5)
data = rng.standard_normal((128, 128)).cumsum(0).cumsum(1)
data = (data - data.min()) / (data.max() - data.min())
xy   = np.linspace(0, 10, 128)

fig, ax = vw.subplots(1, 1, figsize=(460, 460))
v = ax.imshow(data, axes=[xy, xy], units="nm")

triangle = [[64.0, 10.0], [100.0, 60.0], [28.0, 60.0]]
hexagon  = [[64.0 + 28 * np.cos(np.radians(60 * k)),
             95.0 + 28 * np.sin(np.radians(60 * k))]
            for k in range(6)]
v.add_polygons([triangle, hexagon], name="shapes",
               edgecolors="#69f0ae", facecolors="#69f0ae22",
               linewidths=2.0,
               label="shapes", labels=["triangle", "hexagon"])

fig

# %%
# Live update
# -----------
# Change the stroke and fill colour of every polygon at once.

v.markers["polygons"]["shapes"].set(edgecolors="#e040fb",
                                    facecolors="#e040fb33")
fig

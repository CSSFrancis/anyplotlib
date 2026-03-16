"""
Ellipses
========

Draw ellipses on a 2-D image with
:meth:`~anyplotlib.figure_plots.Plot2D.add_ellipses`.
Use ``markers["ellipses"]["name"].set(...)`` to update them live.
"""
import numpy as np
import anyplotlib as vw

rng  = np.random.default_rng(2)
data = rng.standard_normal((128, 128)).cumsum(0).cumsum(1)
data = (data - data.min()) / (data.max() - data.min())
xy   = np.linspace(0, 10, 128)

fig, ax = vw.subplots(1, 1, figsize=(460, 460))
v = ax.imshow(data, axes=[xy, xy], units="nm")

centres = np.array([[32.0, 32.0], [64.0, 96.0], [96.0, 48.0]])
v.add_ellipses(centres, widths=30, heights=14,
               angles=[0.0, 45.0, 90.0],
               name="grains",
               edgecolors="#ff9100", facecolors="#ff910033",
               label="grains", labels=["A", "B", "C"])

fig

# %%
# Live update
# -----------
# Resize all ellipses and change colour in one call.

v.markers["ellipses"]["grains"].set(widths=38, heights=18,
                                    edgecolors="#69f0ae",
                                    facecolors="#69f0ae33")
fig

"""
Squares
=======

Draw squares on a 2-D image with
:meth:`~anyplotlib.figure_plots.Plot2D.add_squares`.
Use ``markers["squares"]["name"].set(...)`` to update them live.
"""
import numpy as np
import anyplotlib as vw

rng  = np.random.default_rng(6)
data = rng.standard_normal((128, 128)).cumsum(0).cumsum(1)
data = (data - data.min()) / (data.max() - data.min())
xy   = np.linspace(0, 10, 128)

fig, ax = vw.subplots(1, 1, figsize=(460, 460))
v = ax.imshow(data, axes=[xy, xy], units="nm")

centres = np.array([[32.0, 32.0], [64.0, 64.0], [96.0, 96.0],
                    [32.0, 96.0], [96.0, 32.0]])
v.add_squares(centres, widths=20,
              angles=[0, 15, 30, 45, 60],
              name="tiles",
              edgecolors="#00e5ff", facecolors="#00e5ff22",
              label="tiles", labels=[f"T{i}" for i in range(5)])
fig

# %%
# Live update
# -----------
# Increase size and swap colour.

v.markers["squares"]["tiles"].set(widths=26,
                                  edgecolors="#e040fb",
                                  facecolors="#e040fb22")
fig

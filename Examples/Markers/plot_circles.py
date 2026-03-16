"""
Circles
=======

Mark circular features on a 2-D image with
:meth:`~anyplotlib.figure_plots.Plot2D.add_circles`.
Use ``markers["circles"]["name"].set(...)`` to update them live.
"""
import numpy as np
import anyplotlib as vw

rng  = np.random.default_rng(0)
data = rng.standard_normal((128, 128)).cumsum(0).cumsum(1)
data = (data - data.min()) / (data.max() - data.min())
xy   = np.linspace(0, 10, 128)

fig, ax = vw.subplots(1, 1, figsize=(460, 460))
v = ax.imshow(data, axes=[xy, xy], units="nm")

centres = rng.uniform(15, 113, (8, 2))
v.add_circles(centres, name="spots", radius=10,
              edgecolors="#ff1744", facecolors="#ff174433",
              labels=[f"#{i}" for i in range(8)])

fig

# %%
# Live update
# -----------
# Call ``.set()`` on the marker group to push any change immediately.

v.markers["circles"]["spots"].set(radius=16, edgecolors="#ffcc00",
                                  facecolors="#ffcc0033")
fig

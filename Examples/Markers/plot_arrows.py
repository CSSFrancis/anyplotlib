"""
Arrows
======

Draw vector arrows on a 2-D image with
:meth:`~anyplotlib.figure_plots.Plot2D.add_arrows`.
Use ``markers["arrows"]["name"].set(...)`` to update them live.
"""
import numpy as np
import anyplotlib as vw

rng  = np.random.default_rng(3)
data = rng.standard_normal((128, 128)).cumsum(0).cumsum(1)
data = (data - data.min()) / (data.max() - data.min())
xy   = np.linspace(0, 10, 128)

fig, ax = vw.subplots(1, 1, figsize=(460, 460))
v = ax.imshow(data, axes=[xy, xy], units="nm")

tails = rng.uniform(15, 100, (8, 2))
U     = rng.uniform(-18, 18, 8)
V     = rng.uniform(-18, 18, 8)
v.add_arrows(tails, U, V, name="flow",
             edgecolors="#76ff03", linewidths=2.0,
             label="flow vectors")

fig

# %%
# Live update
# -----------
# Change colour and width of every arrow in the group at once.

v.markers["arrows"]["flow"].set(edgecolors="#ff9100", linewidths=2.5)
fig

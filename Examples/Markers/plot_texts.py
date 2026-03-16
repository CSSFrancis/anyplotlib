"""
Text Labels
===========

Place text annotations on a 2-D image with
:meth:`~anyplotlib.figure_plots.Plot2D.add_texts`.
Use ``markers["texts"]["name"].set(...)`` to update them live.
"""
import numpy as np
import anyplotlib as vw

rng  = np.random.default_rng(7)
data = rng.standard_normal((128, 128)).cumsum(0).cumsum(1)
data = (data - data.min()) / (data.max() - data.min())
xy   = np.linspace(0, 10, 128)

fig, ax = vw.subplots(1, 1, figsize=(460, 460))
v = ax.imshow(data, axes=[xy, xy], units="nm")

v.add_texts([[4.0, 4.0], [4.0, 116.0], [88.0, 4.0], [88.0, 116.0]],
            ["TL", "BL", "TR", "BR"],
            name="corners",
            color="#ffeb3b", fontsize=12,
            label="corners")

fig

# %%
# Live update
# -----------
# Change colour and font size of all labels at once.

v.markers["texts"]["corners"].set(color="#e040fb", fontsize=14)
fig

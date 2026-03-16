"""
Line Segments
=============

Draw line segments on a 2-D image with
:meth:`~anyplotlib.figure_plots.Plot2D.add_lines`.
Use ``markers["lines"]["name"].set(...)`` to update them live.
"""
import numpy as np
import anyplotlib as vw

rng  = np.random.default_rng(4)
data = rng.standard_normal((128, 128)).cumsum(0).cumsum(1)
data = (data - data.min()) / (data.max() - data.min())
xy   = np.linspace(0, 10, 128)

fig, ax = vw.subplots(1, 1, figsize=(460, 460))
v = ax.imshow(data, axes=[xy, xy], units="nm")

segments = np.array([
    [[ 10.0,  10.0], [118.0,  10.0]],
    [[118.0,  10.0], [118.0, 118.0]],
    [[118.0, 118.0], [ 10.0, 118.0]],
    [[ 10.0, 118.0], [ 10.0,  10.0]],
    [[ 10.0,  10.0], [118.0, 118.0]],
])
v.add_lines(segments, name="frame",
            edgecolors="#00e5ff", linewidths=1.5,
            label="frame",
            labels=["top", "right", "bottom", "left", "diagonal"])
fig

# %%
# Live update
# -----------
# Update stroke colour and width for all segments at once.

v.markers["lines"]["frame"].set(edgecolors="#ff9100", linewidths=2.5)
fig

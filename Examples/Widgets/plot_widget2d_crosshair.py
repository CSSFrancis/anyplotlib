"""
2D Crosshair Widget
====================

A draggable crosshair overlay that snaps to a single ``[x, y]`` position
on a 2-D image panel.
"""
import numpy as np
import anyplotlib as vw

rng  = np.random.default_rng(3)
data = rng.standard_normal((128, 128)).cumsum(0).cumsum(1)
data = (data - data.min()) / (data.max() - data.min())
xy   = np.linspace(0, 10, 128)

fig, ax = vw.subplots(1, 1, figsize=(460, 460))
v = ax.imshow(data, axes=[xy, xy], units="nm")

v.add_widget("crosshair", color="#69f0ae", cx=64, cy=64)
fig


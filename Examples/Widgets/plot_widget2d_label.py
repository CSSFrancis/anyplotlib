"""
2D Label Widget
================

A draggable text label overlay on a 2-D image panel.
Specify position with ``x``, ``y`` (pixel coordinates), ``text``,
and ``fontsize``.
"""
import numpy as np
import viewer as vw

rng  = np.random.default_rng(5)
data = rng.standard_normal((128, 128)).cumsum(0).cumsum(1)
data = (data - data.min()) / (data.max() - data.min())
xy   = np.linspace(0, 10, 128)

fig, ax = vw.subplots(1, 1, figsize=(460, 460))
v = ax.imshow(data, axes=[xy, xy], units="nm")

v.add_widget("label", color="#ff1744", x=10, y=10,
             text="Region A", fontsize=14)
fig

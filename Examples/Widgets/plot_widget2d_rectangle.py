"""
2D Rectangle Widget
====================

A draggable, resizable rectangle overlay on a 2-D image panel.
Add it with :meth:`~viewer.figure_plots.Plot2D.add_widget` using
``kind="rectangle"``.
"""
import numpy as np
import viewer as vw

rng  = np.random.default_rng(1)
data = rng.standard_normal((128, 128)).cumsum(0).cumsum(1)
data = (data - data.min()) / (data.max() - data.min())
xy   = np.linspace(0, 10, 128)

fig, ax = vw.subplots(1, 1, figsize=(460, 460))
v = ax.imshow(data, axes=[xy, xy], units="nm")

v.add_widget("rectangle", color="#ffeb3b", x=24, y=24, w=80, h=60)
fig


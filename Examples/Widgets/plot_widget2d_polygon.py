"""
2D Polygon Widget
==================

A draggable polygon overlay whose individual vertices can be repositioned.
Pass ``vertices`` as a list of ``[x, y]`` pixel coordinates.
"""
import numpy as np
import anyplotlib as vw

rng  = np.random.default_rng(4)
data = rng.standard_normal((128, 128)).cumsum(0).cumsum(1)
data = (data - data.min()) / (data.max() - data.min())
xy   = np.linspace(0, 10, 128)

fig, ax = vw.subplots(1, 1, figsize=(460, 460))
v = ax.imshow(data, axes=[xy, xy], units="nm")

v.add_widget("polygon", color="#ff9100",
             vertices=[[32, 16], [96, 16], [112, 80],
                       [64, 112], [16, 80]])
fig


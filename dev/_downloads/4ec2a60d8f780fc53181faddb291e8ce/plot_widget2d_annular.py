"""
2D Annular Widget
==================

A draggable annular (ring) overlay for selecting a radial band on a 2-D image.
Drag the inner or outer ring to adjust the radii.
"""
import numpy as np
import anyplotlib as vw

rng  = np.random.default_rng(2)
data = rng.standard_normal((128, 128)).cumsum(0).cumsum(1)
data = (data - data.min()) / (data.max() - data.min())
xy   = np.linspace(0, 10, 128)

fig, ax = vw.subplots(1, 1, figsize=(460, 460))
v = ax.imshow(data, axes=[xy, xy], units="nm")

v.add_widget("annular", color="#00e5ff", cx=64, cy=64, r_outer=40, r_inner=20)

fig

"""
Rectangles
==========
Draw bounding boxes on a 2-D image with
:meth:`~anyplotlib.figure_plots.Plot2D.add_rectangles`.
"""
import numpy as np
import anyplotlib as vw
rng  = np.random.default_rng(1)
data = rng.standard_normal((128, 128)).cumsum(0).cumsum(1)
data = (data - data.min()) / (data.max() - data.min())
xy   = np.linspace(0, 10, 128)
fig, ax = vw.subplots(1, 1, figsize=(460, 460))
v = ax.imshow(data, axes=[xy, xy], units="nm")
centres = rng.uniform(20, 108, (5, 2))
v.add_rectangles(centres, widths=22, heights=14, name="boxes",
                 edgecolors="#00e5ff", facecolors="#00e5ff22",
                 labels=[f"R{i}" for i in range(5)])
fig
# %%
# Live update
# -----------
v.markers["rectangles"]["boxes"].set(widths=30, heights=20,
                                     edgecolors="#ff9100",
                                     facecolors="#ff910033")
fig

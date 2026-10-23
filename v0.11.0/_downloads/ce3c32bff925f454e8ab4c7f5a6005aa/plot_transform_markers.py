"""
Coordinate transforms — pin markers to the axes or the screen
=============================================================

Every ``add_*`` marker method takes a ``transform`` that decides which
coordinate system its positions live in:

- ``"data"`` (default) — data coordinates; the marker moves and scales with
  zoom / pan, staying glued to the underlying data.
- ``"axes"`` — axes-normalised ``(0, 0)`` bottom-left … ``(1, 1)`` top-right;
  the marker stays in the same corner of the panel no matter how you zoom.
- ``"display"`` — raw CSS pixels within the panel; a fixed-size decoration.

The ``"axes"`` and ``"display"`` transforms are how you build overlays that
should *not* track the data — a navigation index in the corner, a scale bar, a
persistent legend chip.
"""
import numpy as np
import anyplotlib as apl

rng  = np.random.default_rng(1)
data = rng.standard_normal((128, 128)).cumsum(0).cumsum(1)
data = (data - data.min()) / (data.max() - data.min())
xy   = np.linspace(0, 10, 128)

fig, ax = apl.subplots(1, 1, figsize=(480, 480))
v = ax.imshow(data, axes=[xy, xy], units="nm")

# Data-anchored label — sits at (5, 5) in nm and rides along on zoom/pan.
v.add_texts(offsets=[(5, 5)], texts=["feature @ (5, 5)"],
            color="#ffffff", fontsize=12, name="data_label")

# Axes-anchored index — stays pinned to the top-left corner of the panel
# regardless of zoom (0, 1 = top-left in axes fractions).
v.add_texts(offsets=[(0.04, 0.96)], texts=["frame 3 / 20"],
            transform="axes", color="#ffd54f", fontsize=13, name="nav_index")

fig

# %%
# Try it
# ------
# Zoom into the image: the white ``feature`` label moves with the data, while
# the yellow ``frame 3 / 20`` index stays locked to the corner — because it is
# positioned in ``"axes"`` coordinates.

fig.set_help("Zoom in: the corner index stays put; the data label moves.")

fig  # Interactive

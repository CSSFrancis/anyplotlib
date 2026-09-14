"""
Aspect Ratio Control
====================

:meth:`~anyplotlib.Plot2D.set_aspect` constrains the displayed image canvas so
that one unit on the x-axis occupies the same number of pixels as one unit on
the y-axis.

Three modes are shown:

1. **Default** — the image fills the panel exactly (no constraint).
2. ``set_aspect("equal")`` — forces a 1 : 1 pixel-per-unit ratio.  A square
   array is displayed as a square image regardless of panel dimensions.
3. ``set_aspect(2.0)`` — makes the canvas twice as wide as it is tall.

The scale bar, axis ticks, and colorbar all update automatically when the
canvas is resized by ``set_aspect``.
"""
import numpy as np
import anyplotlib as apl

rng = np.random.default_rng(0)

# ── Synthetic calibrated image ────────────────────────────────────────────────
N = 64
x = np.linspace(0, 10, N)   # nm
y = np.linspace(0, 10, N)
XX, YY = np.meshgrid(x, y)
data = (np.sin(XX) * np.cos(YY) + 0.2 * rng.standard_normal((N, N))).astype(np.float32)

# ── 1. Default (no aspect constraint) ────────────────────────────────────────
# %%
# Default — no aspect constraint
# --------------------------------
# The image stretches to fill the full panel area.

fig1, ax1 = apl.subplots(1, 1, figsize=(420, 340))
plot1 = ax1.imshow(data, axes=[x, y], units="nm", cmap="viridis")
plot1.set_title("Default (no constraint)")
plot1.set_xlabel("x (nm)")
plot1.set_ylabel("y (nm)")

fig1  # Interactive

# ── 2. Equal aspect ratio ─────────────────────────────────────────────────────
# %%
# Equal aspect ratio
# ------------------
# ``set_aspect("equal")`` (or equivalently ``set_aspect(1.0)``) ensures that
# one nm on the x-axis occupies the same number of canvas pixels as one nm on
# the y-axis.  The canvas height adjusts to be equal to the canvas width.

fig2, ax2 = apl.subplots(1, 1, figsize=(420, 340))
plot2 = ax2.imshow(data, axes=[x, y], units="nm", cmap="viridis")
plot2.set_aspect("equal")
plot2.set_title("set_aspect('equal')")
plot2.set_xlabel("x (nm)")
plot2.set_ylabel("y (nm)")

fig2  # Interactive

# ── 3. Explicit ratio ─────────────────────────────────────────────────────────
# %%
# Explicit ratio (2 : 1)
# -----------------------
# ``set_aspect(2.0)`` makes the canvas twice as wide as it is tall.  Useful
# when the physical x and y scales differ (e.g. a time-series scan where one
# axis is faster than the other).

fig3, ax3 = apl.subplots(1, 1, figsize=(420, 340))
plot3 = ax3.imshow(data, axes=[x, y], units="nm", cmap="inferno")
plot3.set_aspect(2.0)
plot3.set_title("set_aspect(2.0)")
plot3.set_xlabel("x (nm)")
plot3.set_ylabel("y (nm)")

fig3  # Interactive

"""
2D Image
========

Display a 2-D image with physical axes using
:meth:`~anyplotlib.figure_plots.Axes.imshow`.
The image is a synthetic STEM-like diffraction pattern with a physical
length scale in nanometres.  Circle markers highlight the first-order
diffraction spots, and an annular integration widget is placed over the
central beam.  Pan and zoom with the mouse; press **R** to reset the view,
**H** to toggle the histogram, **L** / **S** to cycle colour-scale modes.
"""
import numpy as np
import anyplotlib as vw


rng = np.random.default_rng(1)

# ── Synthetic diffraction pattern ─────────────────────────────────────────────
N = 256
x = np.linspace(-5, 5, N)   # physical axis in nm
y = np.linspace(-5, 5, N)
XX, YY = np.meshgrid(x, y)
R = np.sqrt(XX ** 2 + YY ** 2)


def _ring(r, r0, width, amp):
    return amp * np.exp(-0.5 * ((r - r0) / width) ** 2)


image = (
    _ring(R, 0.0, 0.30, 1.00)    # central spot
    + _ring(R, 2.1, 0.15, 0.55)  # first-order ring
    + _ring(R, 4.2, 0.15, 0.25)  # second-order ring
    + rng.normal(scale=0.04, size=(N, N))
)

# ── Plot ──────────────────────────────────────────────────────────────────────
fig, ax = vw.subplots(1, 1, figsize=(500, 500))
v = ax.imshow(image, axes=[x, y], units="nm")
v.set_colormap("inferno")

# ── First-order spot markers ──────────────────────────────────────────────────
# imshow axes are centre arrays: pixel = (phys - x[0]) / (x[1] - x[0])
dx = x[1] - x[0]


def phys_to_px(val):
    return (np.asarray(val) - x[0]) / dx


spot_nm = np.array([[ 2.1,  0.0], [-2.1,  0.0],
                    [ 0.0,  2.1], [ 0.0, -2.1]])
spot_px = np.column_stack([phys_to_px(spot_nm[:, 0]),
                           phys_to_px(spot_nm[:, 1])])
v.add_circles(spot_px, name="spots", radius=7,
              edgecolors="#00e5ff", facecolors="#00e5ff22",
              labels=["g1", "g1_bar", "g2", "g2_bar"])

# ── Annular integration widget ────────────────────────────────────────────────
cx = cy = float(phys_to_px(0.0))
v.add_widget("annular", color="#ffcc00",
             cx=cx, cy=cy,
             r_outer=float(phys_to_px(2.8) - phys_to_px(0.0)),
             r_inner=float(phys_to_px(1.2) - phys_to_px(0.0)))

fig

# %%
# Adjust display range and colour map
# ------------------------------------
# :meth:`~anyplotlib.figure_plots.Plot2D.set_clim` clips the colour scale;
# :meth:`~anyplotlib.figure_plots.Plot2D.set_colormap` switches the palette.

v.set_clim(vmin=0.0, vmax=0.8)
v.set_colormap("viridis")

fig

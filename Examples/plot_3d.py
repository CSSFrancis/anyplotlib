"""
3D Plotting
===========
Demonstrate the three 3-D geometry types supported by
:meth:`~anyplotlib.figure_plots.Axes.plot_surface`,
:meth:`~anyplotlib.figure_plots.Axes.scatter3d`, and
:meth:`~anyplotlib.figure_plots.Axes.plot3d`.
Drag to rotate, scroll to zoom, press **R** to reset the view.
"""
import numpy as np
import anyplotlib as vw
# ── Surface ───────────────────────────────────────────────────────────────────
x = np.linspace(-3, 3, 60)
y = np.linspace(-3, 3, 60)
XX, YY = np.meshgrid(x, y)
ZZ = np.sin(np.sqrt(XX**2 + YY**2))
fig, ax = vw.subplots(1, 1, figsize=(520, 480))
surf = ax.plot_surface(XX, YY, ZZ,
                       colormap="viridis",
                       x_label="x", y_label="y", z_label="sin(r)")
fig
# %%
# Scatter plot
# ------------
rng = np.random.default_rng(1)
n = 300
theta = rng.uniform(0, 2 * np.pi, n)
phi   = rng.uniform(0, np.pi, n)
r     = rng.uniform(0.6, 1.0, n)
xs = r * np.sin(phi) * np.cos(theta)
ys = r * np.sin(phi) * np.sin(theta)
zs = r * np.cos(phi)
fig2, ax2 = vw.subplots(1, 1, figsize=(480, 480))
sc = ax2.scatter3d(xs, ys, zs,
                   color="#4fc3f7", point_size=3,
                   x_label="x", y_label="y", z_label="z")
fig2
# %%
# 3-D line — parametric helix
# ----------------------------
t  = np.linspace(0, 4 * np.pi, 300)
hx = np.cos(t)
hy = np.sin(t)
hz = t / (4 * np.pi)
fig3, ax3 = vw.subplots(1, 1, figsize=(480, 480))
ln = ax3.plot3d(hx, hy, hz,
                color="#ff7043", linewidth=2,
                x_label="cos t", y_label="sin t", z_label="t")
fig3
# %%
# Update the surface data live
# ----------------------------
# Call :meth:`~anyplotlib.figure_plots.Plot3D.update` to replace the geometry
# without recreating the panel.
ZZ2 = np.cos(np.sqrt(XX**2 + YY**2))
surf.update(XX, YY, ZZ2)
surf.set_colormap("plasma")
surf.set_view(azimuth=30, elevation=40)
fig

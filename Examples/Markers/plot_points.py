"""
Points
======
Draw point markers on a 1-D plot with
:meth:`~anyplotlib.figure_plots.Plot1D.add_points`.
Use ``markers["points"]["name"].set(...)`` to update them live.
"""
import numpy as np
import anyplotlib as vw
x      = np.linspace(0, 4 * np.pi, 512)
signal = np.sin(x)
fig, ax = vw.subplots(1, 1, figsize=(560, 300))
v = ax.plot(signal, axes=[x], units="rad")
peak_x  = np.array([np.pi / 2, 5 * np.pi / 2, 9 * np.pi / 2])
offsets = np.column_stack([peak_x, np.sin(peak_x)])
v.add_points(offsets, name="peaks",
             edgecolors="#ff1744", facecolors="#ff174433", sizes=8,
             label="peaks", labels=["P1", "P2", "P3"])
fig
# %%
# Live update
# -----------
v.markers["points"]["peaks"].set(sizes=12, edgecolors="#ffcc00",
                                 facecolors="#ffcc0033")
fig

"""
Twinned (secondary) y-axis
==========================

Overlay two series that live on very different scales on a single
:class:`~anyplotlib.Plot1D` panel, each with its own y-axis.  Enable the
right-hand axis with :meth:`~anyplotlib.Plot1D.add_right_axis`, then add curves
to it with ``add_line(..., axis="right")`` — they are scaled and labelled
independently of the left axis.
"""
import numpy as np
import anyplotlib as apl

x = np.linspace(0, 10, 400)
signal = np.sin(x)                      # left axis: −1 … 1
temperature = 300 + 350 * np.cos(x / 2)  # right axis: ~ −50 … 650

fig, ax = apl.subplots(1, 1, figsize=(560, 360))
plot = ax.plot(signal, axes=[x], color="#4fc3f7", label="signal")
plot.set_ylabel("Amplitude")

# %%
# Add the secondary axis
# ----------------------
# ``add_right_axis`` turns on the right-hand y-axis; ``axis="right"`` anchors
# the new curve to it.  The left axis stays fixed at −1 … 1 while the right
# axis auto-scales to the temperature range.

plot.add_right_axis(color="#e05a2b")
plot.add_line(temperature, x_axis=x, color="#e05a2b",
              axis="right", label="temperature")
plot.set_right_ylabel("Temperature (K)")

fig

# %%
# Pin the secondary range
# -----------------------
# By default the right axis auto-scales to its lines.  Call
# :meth:`~anyplotlib.Plot1D.set_right_ylim` to fix it explicitly (for example
# to line two datasets up at a shared reference level).

plot.set_right_ylim(0, 700)

fig

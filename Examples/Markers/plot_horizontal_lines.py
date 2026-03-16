"""
Horizontal Lines
================

Draw static horizontal threshold lines on a 1-D plot with
:meth:`~anyplotlib.figure_plots.Plot1D.add_hlines`.
Use ``markers["hlines"]["name"].set(...)`` to update them live.
"""
import numpy as np
import anyplotlib as vw

x      = np.linspace(0, 4 * np.pi, 512)
signal = np.sin(x)

fig, ax = vw.subplots(1, 1, figsize=(560, 300))
v = ax.plot(signal, axes=[x], units="rad")

v.add_hlines([0.5, 0.0, -0.5], name="thresholds",
             color="#69f0ae", linewidths=1.5,
             label="thresholds", labels=["+0.5", "zero", "-0.5"])

fig

# %%
# Live update
# -----------

v.markers["hlines"]["thresholds"].set(color="#ff1744", linewidths=2.0)
fig

"""
Vertical Lines
==============
Draw read-only vertical lines on a 1-D plot with
:meth:`~anyplotlib.figure_plots.Plot1D.add_vlines`.
Use ``markers["vlines"]["name"].set(...)`` to update them live.
"""
import numpy as np
import anyplotlib as vw
x = np.linspace(0, 4 * np.pi, 512)
signal = np.sin(x)
fig, ax = vw.subplots(1, 1, figsize=(560, 300))
v = ax.plot(signal, axes=[x], units="rad")
v.add_vlines([np.pi, 2 * np.pi, 3 * np.pi], name="pi_mult",
             color="#00e5ff", linewidths=1.5,
             label="pi multiples", labels=["pi", "2pi", "3pi"])
fig
# %%
# Live update
# -----------
v.markers["vlines"]["pi_mult"].set(color="#ff9100", linewidths=2.0)
fig

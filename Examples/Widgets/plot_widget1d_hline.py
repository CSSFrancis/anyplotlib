"""
1D Horizontal Line Widget
==========================

A draggable horizontal line on a 1-D plot panel.
Add it with :meth:`~viewer.figure_plots.Plot1D.add_hline_widget`.
Drag the line up or down to change the selected y value.
"""
import numpy as np
import viewer as vw

x      = np.linspace(0, 4 * np.pi, 512)
signal = np.sin(x)

fig, ax = vw.subplots(1, 1, figsize=(560, 300))
v = ax.plot(signal, axes=[x], units="rad")

v.add_hline_widget(y=0.5, color="#69f0ae")
fig


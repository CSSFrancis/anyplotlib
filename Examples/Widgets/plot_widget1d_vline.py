"""
1D Vertical Line Widget
========================

A draggable vertical line on a 1-D plot panel.
Add it with :meth:`~viewer.figure_plots.Plot1D.add_vline_widget`.
Drag the line left or right to change the selected x position.
"""
import numpy as np
import viewer as vw

x      = np.linspace(0, 4 * np.pi, 512)
signal = np.sin(x)

fig, ax = vw.subplots(1, 1, figsize=(560, 300))
v = ax.plot(signal, axes=[x], units="rad")

v.add_vline_widget(x=np.pi, color="#e040fb")
fig

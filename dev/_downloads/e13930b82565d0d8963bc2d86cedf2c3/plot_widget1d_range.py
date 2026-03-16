"""
1D Range Widget
================

A draggable range selector on a 1-D plot panel with two handles.
Add it with :meth:`~anyplotlib.figure_plots.Plot1D.add_range_widget`.
Drag either handle to resize the selected interval, or drag the band
to move it.
"""
import numpy as np
import anyplotlib as vw

x      = np.linspace(0, 4 * np.pi, 512)
signal = np.sin(x)

fig, ax = vw.subplots(1, 1, figsize=(560, 300))
v = ax.plot(signal, axes=[x], units="rad")

v.add_range_widget(x0=np.pi, x1=2 * np.pi, color="#ffeb3b")

fig

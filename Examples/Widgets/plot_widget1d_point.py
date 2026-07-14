"""
1D Point Widget
===============

A free-moving ``(x, y)`` control point on a 1-D panel, with an optional
crosshair.  Unlike the vertical / horizontal line widgets it moves in both
directions, so it is handy as a draggable data cursor or a control handle for
an interactive fit.  Add it with :meth:`~anyplotlib.Plot1D.add_point_widget`.
"""
import numpy as np
import anyplotlib as apl

x = np.linspace(0, 4 * np.pi, 400)
y = np.sin(x) * np.exp(-x / 12)

fig, ax = apl.subplots(1, 1, figsize=(560, 340))
plot = ax.plot(y, axes=[x], color="#4fc3f7")

point = plot.add_point_widget(x=3.0, y=0.5, color="#ff1744",
                              show_crosshair=True)

fig

# %%
# Snap the point onto the curve
# -----------------------------
# A ``pointer_move`` handler fires while the point is dragged.  Here we read
# ``point.x``, look up the nearest sample, and push the point back onto the
# curve with :meth:`~anyplotlib.Widget.set` — a one-line "snap to data" cursor.


@point.add_event_handler("pointer_move")
def _snap(event):
    i = int(np.clip(np.searchsorted(x, point.x), 0, len(x) - 1))
    point.set(y=float(y[i]))


fig.set_help("Drag the point — it snaps onto the curve as you move it.")

fig  # Interactive

"""
2D Arrow Widget
===============

A draggable arrow overlay on a 2-D image panel.  The tail sits at ``(x, y)``
and the head at ``(x + u, y + v)`` in data coordinates.  Drag the body to move
the whole arrow; drag the head handle to re-aim it (updating ``u`` / ``v``).
Add it with :meth:`~anyplotlib.Plot2D.add_arrow_widget`.
"""
import numpy as np
import anyplotlib as apl

rng  = np.random.default_rng(3)
data = rng.standard_normal((128, 128)).cumsum(0).cumsum(1)
data = (data - data.min()) / (data.max() - data.min())
xy   = np.linspace(0, 10, 128)

fig, ax = apl.subplots(1, 1, figsize=(460, 460))
v = ax.imshow(data, axes=[xy, xy], units="nm")

arrow = v.add_arrow_widget(x=2.0, y=2.0, u=5.0, v=4.0,
                           color="#ff1744", linewidth=2)

fig

# %%
# React to drags
# --------------
# Register a ``pointer_move`` handler to read the live geometry while the arrow
# is dragged or re-aimed (there is no ``on_changed`` method — the event system
# is the API).  Read ``arrow.x/y/u/v`` inside the handler.


@arrow.add_event_handler("pointer_move")
def _report(event):
    print(f"tail=({arrow.x:.1f}, {arrow.y:.1f})  vector=({arrow.u:.1f}, {arrow.v:.1f})")


fig.set_help("Drag the arrow body to move it; drag the head to re-aim it.")

fig  # Interactive

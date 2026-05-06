"""
Draggable Point Widget
======================

Demonstrates the :class:`~anyplotlib.widgets.PointWidget` on a 1-D panel.

A smooth curve ``f(x) = sin(x) · e^(−x/6)`` is shown together with a
cyan control point that the user can drag freely inside the plot area.

**Interaction**

* **Drag the point** anywhere inside the plot — the widget reports its
  data-space ``(x, y)`` position on every frame via the
  :meth:`~anyplotlib.widgets.Widget.on_changed` callback.
* **Release** — the :meth:`~anyplotlib.widgets.Widget.on_release` callback
  snaps the point's y-coordinate to the curve value at the dragged x
  and draws the **tangent line** through that point.

**What is computed on release**

Given the dragged x position *xq*, the code evaluates:

* **Curve value**: ``yq = f(xq)``
* **Derivative** (central finite difference): ``dy/dx ≈ [f(xq+h) − f(xq−h)] / 2h``
* **Tangent line**: ``y_tan(x) = yq + slope · (x − xq)``

The tangent line is added with :meth:`~anyplotlib.figure_plots.Plot1D.add_line`
and the previous one is removed, so only one tangent is shown at a time.

.. note::
   Move the point to an interesting part of the curve (e.g. a local maximum)
   and release — the tangent will be horizontal there.
"""

import numpy as np
import anyplotlib as vw

# ── Curve ──────────────────────────────────────────────────────────────────
x = np.linspace(0.0, 4.0 * np.pi, 512)

def f(t):
    return np.sin(t) * np.exp(-t / 6.0)

def df(t, h=1e-5):
    """Central finite-difference derivative of f."""
    return (f(t + h) - f(t - h)) / (2.0 * h)

y = f(x)

# ── Figure ─────────────────────────────────────────────────────────────────
fig, ax = vw.subplots(figsize=(680, 340))
plot = ax.plot(y, axes=[x], units="rad",
               color="#4fc3f7", linewidth=2.0, label="f(x)")

# ── Initial point widget — placed at the first local maximum ───────────────
x0_init = float(x[np.argmax(y)])
y0_init = float(np.max(y))
pt = plot.add_point_widget(x0_init, y0_init, color="#00e5ff")

# Track the current tangent line handle so we can replace it
_tangent_line: "vw.Line1D | None" = None  # type: ignore[name-defined]

def _draw_tangent(xq: float) -> None:
    """Snap point to curve, compute slope, draw tangent overlay."""
    global _tangent_line

    # Evaluate curve and slope at xq
    yq    = float(f(xq))
    slope = float(df(xq))

    # Snap the widget y to the curve (visual feedback)
    pt._data["y"] = yq
    pt._push_fn()

    # Tangent line spans the full visible x range
    x_tan = np.array([float(x[0]), float(x[-1])])
    y_tan = yq + slope * (x_tan - xq)

    # Replace previous tangent
    if _tangent_line is not None:
        _tangent_line.remove()
    _tangent_line = plot.add_line(
        y_tan, x_axis=x_tan,
        color="#ff7043", linewidth=1.5,
        linestyle="dashed",
        label=f"slope = {slope:+.3f}",
    )

# Draw the tangent at the initial position
_draw_tangent(x0_init)


# ── Callbacks ──────────────────────────────────────────────────────────────

@pt.on_changed
def _live(event):
    """Every drag frame — print the current widget position."""
    print(f"  dragging  x={event.x:.4f}  y={event.y:.4f}", end="\r")


@pt.on_release
def _settled(event):
    """On mouse-up — snap y to the curve and refresh the tangent line."""
    print(f"  released  x={event.x:.4f}                    ")
    _draw_tangent(event.x)


fig  # Interactive


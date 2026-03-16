"""
Bar Chart
=========

Demonstrate :meth:`~anyplotlib.figure_plots.Axes.bar` with vertical and
horizontal orientations, per-bar colours, category labels, and live data
updates via :meth:`~anyplotlib.figure_plots.PlotBar.update`.

Three separate figures are shown:

1. **Vertical bar chart** – monthly sales data with a uniform colour.
2. **Horizontal bar chart** – ranked items with per-bar colours and value
   labels.
3. **Side-by-side comparison** – two panels sharing the same figure; one
   panel updates its data to show a different quarter.
"""
import numpy as np
import anyplotlib as vw

rng = np.random.default_rng(7)

# ── 1. Vertical bar chart — monthly sales ────────────────────────────────────
months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
sales = np.array([42, 55, 48, 63, 71, 68, 74, 81, 66, 59, 52, 78],
                 dtype=float)

fig1, ax1 = vw.subplots(1, 1, figsize=(640, 340))
bar1 = ax1.bar(
    sales,
    x_labels=months,
    color="#4fc3f7",
    bar_width=0.6,
    show_values=True,
    units="Month",
    y_units="Units sold",
)
fig1

# %%
# Horizontal bar chart — ranked items
# -------------------------------------
# Set ``orient="h"`` for a horizontal layout.  Pass a list of CSS colours to
# ``colors`` to give each bar its own colour, and use ``show_values=True`` to
# annotate each bar with its numeric value.

categories = ["NumPy", "SciPy", "Matplotlib", "Pandas", "Scikit-learn",
              "PyTorch", "TensorFlow", "JAX", "Polars", "Dask"]
scores = np.array([95, 88, 91, 87, 83, 79, 76, 72, 68, 65], dtype=float)

palette = [
    "#ef5350", "#ec407a", "#ab47bc", "#7e57c2", "#42a5f5",
    "#26c6da", "#26a69a", "#66bb6a", "#d4e157", "#ffa726",
]

fig2, ax2 = vw.subplots(1, 1, figsize=(540, 400))
bar2 = ax2.bar(
    scores,
    x_labels=categories,
    orient="h",
    colors=palette,
    bar_width=0.65,
    show_values=True,
    y_units="Popularity score",
)
fig2

# %%
# Side-by-side comparison — update data live
# -------------------------------------------
# Place two :class:`~anyplotlib.figure_plots.PlotBar` panels in one
# :func:`~anyplotlib.figure_plots.subplots` figure.  Call
# :meth:`~anyplotlib.figure_plots.PlotBar.update` to swap in Q2 data for the
# right panel, demonstrating how the axis range re-calculates automatically.

quarters = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
            "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

q1 = np.array([42, 55, 48, 63, 71, 68, 74, 81, 66, 59, 52, 78], dtype=float)
q2 = np.array([58, 61, 70, 75, 69, 83, 90, 88, 77, 64, 71, 95], dtype=float)

fig3, (ax_left, ax_right) = vw.subplots(1, 2, figsize=(820, 320))

bar_left = ax_left.bar(
    q1,
    x_labels=quarters,
    color="#4fc3f7",
    bar_width=0.6,
    show_values=False,
    y_units="Q1 sales",
)

bar_right = ax_right.bar(
    q1,                        # start with Q1 …
    x_labels=quarters,
    color="#ff7043",
    bar_width=0.6,
    show_values=False,
    y_units="Q2 sales",
)

# Swap in Q2 data — range is recalculated automatically
bar_right.update(q2)

fig3

# %%
# Mutate colours and annotations at runtime
# ------------------------------------------
# :meth:`~anyplotlib.figure_plots.PlotBar.set_color` repaints all bars with a
# single CSS colour.
# :meth:`~anyplotlib.figure_plots.PlotBar.set_show_values` toggles the
# in-bar value annotations.

bar1.set_color("#ff7043")
bar1.set_show_values(False)
fig1


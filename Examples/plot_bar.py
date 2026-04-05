"""
Bar Chart
=========

Demonstrate :meth:`~anyplotlib.figure_plots.Axes.bar` with:

* **Matplotlib-aligned API** — ``ax.bar(x, height, width, bottom, …)``
* Vertical and horizontal orientations, per-bar colours, category labels
* **Grouped bars** — pass a 2-D *height* array ``(N, G)``
* **Log-scale value axis** — ``log_scale=True``
* Live data updates via :meth:`~anyplotlib.figure_plots.PlotBar.set_data`
"""
import numpy as np
import anyplotlib as vw

rng = np.random.default_rng(7)

# ── 1. Vertical bar chart — monthly sales ────────────────────────────────────
# The first positional argument is now *x* (positions or labels), matching
# ``matplotlib.pyplot.bar(x, height, width=0.8, bottom=0.0, ...)``.
months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
sales = np.array([42, 55, 48, 63, 71, 68, 74, 81, 66, 59, 52, 78],
                 dtype=float)

fig1, ax1 = vw.subplots(1, 1, figsize=(640, 340))
bar1 = ax1.bar(
    months,           # x  — category strings become x_labels automatically
    sales,            # height
    width=0.6,
    color="#4fc3f7",
    show_values=True,
    units="Month",
    y_units="Units sold",
)
fig1

# %%
# Horizontal bar chart — ranked items
# -------------------------------------
# Set ``orient="h"`` for a horizontal layout.  Pass a list of CSS colours
# to ``colors`` to give each bar its own colour.

categories = ["NumPy", "SciPy", "Matplotlib", "Pandas", "Scikit-learn",
              "PyTorch", "TensorFlow", "JAX", "Polars", "Dask"]
scores = np.array([95, 88, 91, 87, 83, 79, 76, 72, 68, 65], dtype=float)

palette = [
    "#ef5350", "#ec407a", "#ab47bc", "#7e57c2", "#42a5f5",
    "#26c6da", "#26a69a", "#66bb6a", "#d4e157", "#ffa726",
]

fig2, ax2 = vw.subplots(1, 1, figsize=(540, 400))
bar2 = ax2.bar(
    categories,
    scores,
    orient="h",
    colors=palette,
    width=0.65,
    show_values=True,
    y_units="Popularity score",
)
fig2

# %%
# Grouped bar chart — quarterly comparison
# -----------------------------------------
# Pass a 2-D *height* array of shape ``(N, G)`` to draw *G* bars side by
# side for each category.  Provide ``group_labels`` to show a legend and
# ``group_colors`` to customise each group's colour.

quarters = ["Jan", "Feb", "Mar", "Apr", "May", "Jun"]
q_data = np.array([
    [42, 58, 51],   # Jan — Q1, Q2, Q3
    [55, 61, 59],   # Feb
    [48, 70, 65],   # Mar
    [63, 75, 71],   # Apr
    [71, 69, 80],   # May
    [68, 83, 77],   # Jun
], dtype=float)     # shape (6, 3) → 6 categories, 3 groups

fig3, ax3 = vw.subplots(1, 1, figsize=(680, 340))
bar3 = ax3.bar(
    quarters,
    q_data,
    width=0.8,
    group_labels=["Q1", "Q2", "Q3"],
    group_colors=["#4fc3f7", "#ff7043", "#66bb6a"],
    show_values=False,
    y_units="Sales",
)
fig3

# %%
# Log-scale value axis
# ---------------------
# Set ``log_scale=True`` for a logarithmic value axis.  Non-positive values
# are clamped to ``1e-10`` — no error is raised.  Tick marks are placed at
# each decade (10⁰, 10¹, 10², …) with faint minor gridlines at 2×, 3×, 5×
# multiples.

log_labels = ["A", "B", "C", "D", "E"]
log_vals   = np.array([1, 10, 100, 1_000, 10_000], dtype=float)

fig4, ax4 = vw.subplots(1, 1, figsize=(500, 340))
bar4 = ax4.bar(
    log_labels,
    log_vals,
    log_scale=True,
    color="#ab47bc",
    show_values=True,
    y_units="Count (log scale)",
)
fig4

# %%
# Side-by-side comparison — update data live
# -------------------------------------------
# Place two :class:`~anyplotlib.figure_plots.PlotBar` panels in one figure.
# Call :meth:`~anyplotlib.figure_plots.PlotBar.set_data` to swap in Q2 data —
# the value-axis range recalculates automatically.

q1 = np.array([42, 55, 48, 63, 71, 68, 74, 81, 66, 59, 52, 78], dtype=float)
q2 = np.array([58, 61, 70, 75, 69, 83, 90, 88, 77, 64, 71, 95], dtype=float)
all_months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

fig5, (ax_left, ax_right) = vw.subplots(1, 2, figsize=(820, 320))
bar_left = ax_left.bar(
    all_months, q1, width=0.6,
    color="#4fc3f7", show_values=False, y_units="Q1 sales",
)
bar_right = ax_right.bar(
    all_months, q1, width=0.6,
    color="#ff7043", show_values=False, y_units="Q2 sales",
)
bar_right.set_data(q2)    # swap in Q2 — axis range recalculates automatically

fig5

# %%
# Mutate colours, annotations, and scale at runtime
# --------------------------------------------------
# :meth:`~anyplotlib.figure_plots.PlotBar.set_color` repaints all bars,
# :meth:`~anyplotlib.figure_plots.PlotBar.set_show_values` toggles labels,
# :meth:`~anyplotlib.figure_plots.PlotBar.set_log_scale` switches the
# value-axis between linear and logarithmic.

bar1.set_color("#ff7043")
bar1.set_show_values(False)
fig1

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
# :meth:`~anyplotlib.figure_plots.PlotBar.set_data` to swap in Q2 data for the
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
bar_right.set_data(q2)

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


"""
1D Line Styles
==============

Demonstrates the line-style, opacity, and per-point marker parameters
available on :meth:`~anyplotlib.figure_plots.Axes.plot` and
:meth:`~anyplotlib.figure_plots.Plot1D.add_line`.

Four separate figures are shown:

1. **Linestyles** – all four dash patterns on one panel with a legend.
2. **Alpha (transparency)** – two overlapping sine waves, each at 40 % opacity.
3. **Marker symbols** – all seven supported symbols, each on its own offset
   curve.
4. **Combined** – dashed + semi-transparent + circle-marker overlay on a solid
   primary line; demonstrates post-construction setters.
"""
import numpy as np
import anyplotlib as vw

t256 = np.linspace(0.0, 2.0 * np.pi, 256)   # dense — good for dashes / alpha
t24  = np.linspace(0.0, 2.0 * np.pi,  24)   # sparse — makes markers visible

# ── 1. Linestyles ─────────────────────────────────────────────────────────────
fig1, ax1 = vw.subplots(1, 1, figsize=(580, 300))

plot1 = ax1.plot(np.sin(t256),         color="#4fc3f7", linewidth=2,
                 linestyle="solid",    label="solid")
plot1.add_line(np.sin(t256) + 0.6,    color="#ff7043", linewidth=2,
               linestyle="dashed",    label="dashed  (\"--\")")
plot1.add_line(np.sin(t256) + 1.2,    color="#aed581", linewidth=2,
               linestyle="dotted",    label="dotted  (\":\")")
plot1.add_line(np.sin(t256) + 1.8,    color="#ce93d8", linewidth=2,
               linestyle="dashdot",   label="dashdot (\"-.\")")

fig1

# %%
# The ``ls`` shorthand
# --------------------
# Each linestyle has a single-character (or two-character) shorthand that
# matches the matplotlib convention:
#
# * ``"-"``  → ``"solid"``
# * ``"--"`` → ``"dashed"``
# * ``":"``  → ``"dotted"``
# * ``"-."`` → ``"dashdot"``
#
# The shorthands work on both :meth:`~anyplotlib.figure_plots.Axes.plot`
# and :meth:`~anyplotlib.figure_plots.Plot1D.add_line`:

fig2a, ax2a = vw.subplots(1, 1, figsize=(440, 220))
p = ax2a.plot(np.sin(t256), ls="-",  color="#4fc3f7", label='ls="-"')
p.add_line(np.sin(t256) + 0.8, ls="--", color="#ff7043", label='ls="--"')
p.add_line(np.sin(t256) + 1.6, ls=":",  color="#aed581", label='ls=":"')
fig2a

# %%
# Alpha (opacity)
# ---------------
# ``alpha`` controls line opacity on a 0–1 scale.  Values below 1 let
# overlapping curves show through each other — useful for comparing signals
# that share the same amplitude range.

fig2, ax2 = vw.subplots(1, 1, figsize=(580, 300))

plot2 = ax2.plot(np.sin(t256), color="#4fc3f7", alpha=0.4, linewidth=3,
                 label="sin  α=0.4")
plot2.add_line(np.cos(t256),   color="#ff7043", alpha=0.4, linewidth=3,
               label="cos  α=0.4")

fig2

# %%
# Marker symbols
# --------------
# Set ``marker`` to place a symbol at every data point.  Use a **sparse**
# x-axis (few points) so the individual markers are legible.
# ``markersize`` is the radius (circles / diamonds) or half-side-length
# (squares, triangles) in canvas pixels.
#
# Supported symbols:
#
# * ``"o"``  — circle
# * ``"s"``  — square
# * ``"^"``  — triangle-up
# * ``"v"``  — triangle-down
# * ``"D"``  — diamond
# * ``"+"``  — plus (stroke-only)
# * ``"x"``  — cross (stroke-only)
# * ``"none"`` — no marker (default)

SYMBOLS = [
    ("o", "#4fc3f7"),
    ("s", "#ff7043"),
    ("^", "#aed581"),
    ("v", "#ce93d8"),
    ("D", "#ffcc02"),
    ("+", "#80cbc4"),
    ("x", "#ef9a9a"),
]

fig3, ax3 = vw.subplots(1, 1, figsize=(580, 380))

plot3 = ax3.plot(
    np.sin(t24) + (0 - 3) * 0.9,
    color=SYMBOLS[0][1], linewidth=1.5,
    marker=SYMBOLS[0][0], markersize=5,
    label=f'marker="{SYMBOLS[0][0]}"',
)
for i, (sym, col) in enumerate(SYMBOLS[1:], 1):
    plot3.add_line(
        np.sin(t24) + (i - 3) * 0.9,
        color=col, linewidth=1.5,
        marker=sym, markersize=5,
        label=f'marker="{sym}"',
    )

fig3

# %%
# Combined — linestyle + alpha + marker
# --------------------------------------
# All three style parameters can be combined freely on the same line or on
# separate overlay lines.

fig4, ax4 = vw.subplots(1, 1, figsize=(580, 300))

# Dense solid primary line
plot4 = ax4.plot(np.sin(t256), color="#4fc3f7", linewidth=2,
                 label="sin (solid)")

# Sparse dashed overlay with circle markers and reduced opacity
plot4.add_line(np.cos(t24), color="#ff7043", linewidth=2,
               linestyle="dashed", alpha=0.75,
               marker="o", markersize=5,
               label="cos (dashed, α=0.75, marker='o')")

fig4

# %%
# Post-construction setters
# -------------------------
# Every primary-line style property has a matching setter method.  These
# mutate ``_state`` and push the change to the canvas immediately — no
# need to recreate the panel.

fig5, ax5 = vw.subplots(1, 1, figsize=(440, 220))
plot5 = ax5.plot(np.sin(t256), color="#4fc3f7", linewidth=1.5)

# Change style via setters
plot5.set_color("#ff7043")
plot5.set_linewidth(2.5)
plot5.set_linestyle("dashdot")   # equivalent: plot5.set_linestyle("-.")
plot5.set_alpha(0.8)
plot5.set_marker("o", markersize=5)

fig5


"""
1D Spectra
==========

Plot a 1-D spectrum with a physical x-axis (energy in eV) using
:meth:`~anyplotlib.figure_plots.Axes.plot`.

The spectrum contains a broad background and three Gaussian peaks.
Circle markers highlight the peak positions using
:meth:`~anyplotlib.figure_plots.Plot1D.add_points`, and a range widget
selects a region of interest.  A model fit is overlaid with a dashed line,
and the background component is shown as a semi-transparent dotted curve with
diamond markers.

Pan and zoom with the mouse; press **R** to reset the view.
"""
import numpy as np
import anyplotlib as vw

rng = np.random.default_rng(0)

# ── Synthetic XPS-style spectrum ──────────────────────────────────────────────
energy = np.linspace(280, 295, 512)          # binding energy axis (eV)

def gaussian(x, mu, sigma, amp):
    return amp * np.exp(-0.5 * ((x - mu) / sigma) ** 2)

background = 0.4 * np.exp(-0.08 * (energy - 280))

# Background + three peaks (C 1s region)
spectrum = (
    background
    + gaussian(energy, 284.8, 0.4, 1.0)      # C–C / C–H
    + gaussian(energy, 286.2, 0.4, 0.35)     # C–O
    + gaussian(energy, 288.0, 0.4, 0.18)     # C=O
    + rng.normal(scale=0.015, size=len(energy))
)

# ── Plot ──────────────────────────────────────────────────────────────────────
fig, ax = vw.subplots(1, 1, figsize=(620, 340))
v = ax.plot(spectrum, axes=[energy], units="eV", y_units="Intensity (a.u.)",
            color="#4fc3f7", linewidth=1.5)

# ── Peak markers (add_points collection) ──────────────────────────────────────
peak_energies = np.array([284.8, 286.2, 288.0])
peak_offsets  = np.column_stack([
    peak_energies,
    np.interp(peak_energies, energy, spectrum),
])
v.add_points(peak_offsets, name="peaks",
             sizes=7, color="#ff1744", facecolors="#ff174433",
             labels=["C\u2013C", "C\u2013O", "C=O"])

# ── Region-of-interest widget ─────────────────────────────────────────────────
v.add_range_widget(x0=285.8, x1=288.8, color="#00e5ff")

fig

# %%
# Overlay a model fit — linestyle and alpha
# -----------------------------------------
# Use :meth:`~anyplotlib.figure_plots.Plot1D.add_line` to overlay additional
# curves.  Here the noiseless model fit is drawn as a **dashed** line so it
# is visually distinct from the noisy measured spectrum.  The ``alpha``
# parameter makes the fit semi-transparent so the data underneath remains
# readable.
#
# The y-axis range is expanded automatically to accommodate any overlay line
# whose values fall outside the current bounds.

fit = (
    background
    + gaussian(energy, 284.8, 0.4, 1.0)
    + gaussian(energy, 286.2, 0.4, 0.35)
    + gaussian(energy, 288.0, 0.4, 0.18)
)
v.add_line(fit, x_axis=energy,
           color="#ffcc00", linewidth=2.0,
           linestyle="dashed", alpha=0.85,
           label="fit")

fig

# %%
# Background component — dotted line with markers
# ------------------------------------------------
# Draw the exponential background component as a **dotted** curve.  Passing
# ``marker="D"`` places a diamond at every data point (useful when the line
# is sparse or when you want to emphasise individual sample positions).
# ``markersize`` controls the half-size of the symbol in pixels.

# Sub-sample to keep the marker plot readable
step = 32
v.add_line(background[::step], x_axis=energy[::step],
           color="#ce93d8", linewidth=1.2,
           linestyle="dotted", alpha=0.9,
           marker="D", markersize=3,
           label="background")

fig

# %%
# Post-construction setters
# -------------------------
# All primary-line style properties can be changed after the panel is created
# without rebuilding it.  This is useful in interactive notebooks where you
# want to tweak the appearance of the main trace.

v.set_alpha(0.9)          # slightly reduce primary-line opacity
v.set_linewidth(2.0)      # thicker stroke for the main spectrum

fig

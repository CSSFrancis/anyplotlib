"""
1D Spectra
==========

Plot a 1-D spectrum with a physical x-axis (energy in eV) using
:meth:`~anyplotlib.figure_plots.Axes.plot`.

The spectrum contains a broad background and three Gaussian peaks.
Circle markers highlight the peak positions, and a range widget
selects a region of interest.  Pan and zoom with the mouse; press **R**
to reset the view.
"""
import numpy as np
import anyplotlib as vw

rng = np.random.default_rng(0)

# ── Synthetic XPS-style spectrum ──────────────────────────────────────────────
energy = np.linspace(280, 295, 512)          # binding energy axis (eV)

def gaussian(x, mu, sigma, amp):
    return amp * np.exp(-0.5 * ((x - mu) / sigma) ** 2)

# Background + three peaks (C 1s region)
spectrum = (
    0.4 * np.exp(-0.08 * (energy - 280))     # exponential background
    + gaussian(energy, 284.8, 0.4, 1.0)      # C–C / C–H
    + gaussian(energy, 286.2, 0.4, 0.35)     # C–O
    + gaussian(energy, 288.0, 0.4, 0.18)     # C=O
    + rng.normal(scale=0.015, size=len(energy))
)

# ── Plot ──────────────────────────────────────────────────────────────────────
fig, ax = vw.subplots(1, 1, figsize=(620, 320))
v = ax.plot(spectrum, axes=[energy], units="eV", y_units="Intensity (a.u.)")

# ── Peak markers ──────────────────────────────────────────────────────────────
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
# Overlay a second spectrum
# -------------------------
# Use :meth:`~anyplotlib.figure_plots.Plot1D.add_line` to overlay additional
# curves — useful for comparing reference spectra or fits.

fit = (
    0.4 * np.exp(-0.08 * (energy - 280))
    + gaussian(energy, 284.8, 0.4, 1.0)
    + gaussian(energy, 286.2, 0.4, 0.35)
    + gaussian(energy, 288.0, 0.4, 0.18)
)
v.add_line(fit, x_axis=energy, color="#ffcc00", linewidth=1.5, label="fit")

fig

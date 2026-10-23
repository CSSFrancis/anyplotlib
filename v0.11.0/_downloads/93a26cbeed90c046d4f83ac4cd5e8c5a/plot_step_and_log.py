"""
Step lines and log-scale spectra
================================

Two 1-D options that suit spectral data: a **mid-riser step** line (constant
within each bin, jumping at bin midpoints) via ``linestyle="step-mid"``, and a
**logarithmic y-axis** via :meth:`~anyplotlib.Axes.semilogy` (or
``ax.plot(..., yscale="log")``).
"""
import numpy as np
import anyplotlib as apl

# A noisy binned spectrum.
rng = np.random.default_rng(0)
energy = np.linspace(0, 20, 60)
counts = (np.exp(-(energy - 6) ** 2 / 4) * 1000
          + np.exp(-(energy - 13) ** 2 / 8) * 400
          + rng.uniform(0, 20, energy.size))

# %%
# Step line
# ---------
# ``linestyle="step-mid"`` draws a horizontal segment centred on each x value
# with vertical risers between them — the standard way to show histogram-like
# spectra without implying interpolation between channels.

fig, ax = apl.subplots(1, 1, figsize=(560, 340))
ax.plot(counts, axes=[energy], color="#4fc3f7",
        linestyle="step-mid", label="counts")

fig

# %%
# Log y-axis
# ----------
# ``semilogy`` is shorthand for a log y-scale, which brings out the small
# secondary peak that the linear plot flattens.  Combine it with the step line
# for a classic spectroscopy view.

fig2, ax2 = apl.subplots(1, 1, figsize=(560, 340))
ax2.semilogy(counts, axes=[energy], color="#ff7043", linestyle="step-mid")

fig2

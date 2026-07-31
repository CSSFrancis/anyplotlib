"""
Label Sizes and Scientific (TeX) Formatting
===========================================

Axis labels, titles, and the colorbar label accept an optional ``fontsize``
(in CSS pixels) and support a small TeX subset inside ``$...$`` for
scientific notation — superscripts, subscripts, Greek letters, and common
symbols — rendered directly on the canvas with no MathJax dependency:

* ``$10^{-3}$``, ``$x^2$`` — exponents
* ``$E_F$``, ``$k_{B}T$`` — subscripts
* ``$\\alpha$ … $\\Omega$``, ``\\mu``, ``\\Delta`` — Greek letters
* ``\\times``, ``\\pm``, ``\\AA``, ``\\degree``, ``\\propto``, ``\\partial`` — symbols
* ``$\\mathrm{...}$`` — upright text inside math
"""
import numpy as np
import anyplotlib as apl

rng = np.random.default_rng(7)

fig, (ax_img, ax_spec) = apl.subplots(1, 2, figsize=(880, 380))

# ── 2-D panel: diffraction-style image with TeX axis labels ────────────────
data = rng.standard_normal((128, 128)).cumsum(0).cumsum(1)
q = np.linspace(-2.5, 2.5, 128)
img = ax_img.imshow(data, axes=[q, q], units="")
img.set_title(r"$|F(q)|^2$", fontsize=12)
img.set_xlabel(r"$q_x$ ($\AA^{-1}$)", fontsize=13)
img.set_ylabel(r"$q_y$ ($\AA^{-1}$)", fontsize=13)
img.set_colorbar_visible(True)
img.set_colorbar_label(r"Counts $\times 10^{3}$")

# ── 1-D panel: spectrum with sized, TeX-formatted labels ───────────────────
energy = np.linspace(0, 3, 512)
spectrum = np.exp(-((energy - 1.2) / 0.15) ** 2) + 0.05 * rng.random(512)
spec = ax_spec.plot(spectrum, axes=[energy], color="#ff7043")
spec.set_title(r"Plasmon peak near $E_p$", fontsize=12)
spec.set_xlabel(r"$\Delta E$ (eV)", fontsize=12)
spec.set_ylabel(r"Intensity ($10^{-3}$ counts)", fontsize=12)
spec.set_tick_label_size(11)

fig

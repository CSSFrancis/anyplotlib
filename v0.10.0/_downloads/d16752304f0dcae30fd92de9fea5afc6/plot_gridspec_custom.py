"""
Custom Grid Layouts with GridSpec
==================================

:class:`~anyplotlib.GridSpec` lets you build multi-panel figures where panels
have different sizes and span multiple grid cells.  This gallery shows the most
common patterns.

All examples use the **bare** ``Figure + GridSpec`` workflow — the figure's
grid dimensions are inferred automatically from the GridSpec the first time
``add_subplot`` is called.

Overview
--------

1. **Side-by-side spectra** — two equal 1-D panels in one row (``1×2`` grid).
2. **Image + spectra** — image spanning full width, two spectra below
   (``2×2`` grid with ``height_ratios=[3, 1]``).
3. **Image + histogram** — classic EM layout: large image on top, thin
   histogram strip below (``2×1`` grid with ``height_ratios=[3, 1]``).
4. **Three-column** — three equal columns in a single row (``1×3`` grid).
5. **Asymmetric widths** — wide overview left, narrow detail right
   (``1×2`` grid with ``width_ratios=[2, 1]``).
6. **Complex** — spanning top panel plus two bottom panels (``2×2`` grid).
"""
import numpy as np
import anyplotlib as apl

rng = np.random.default_rng(42)
t   = np.linspace(0.0, 2.0 * np.pi, 512)

# ── 1. Side-by-side spectra (1×2, equal widths) ───────────────────────────────
# %%
# Side-by-side spectra
# --------------------
# The simplest multi-panel case: two 1-D spectra in one row.  Each panel
# receives exactly half the figure width with a full-height inner plot area.
# Both panels share the same height so their axes baselines align visually.

gs1 = apl.GridSpec(1, 2)
fig1 = apl.Figure(figsize=(720, 280))

sp_left  = fig1.add_subplot(gs1[0, 0]).plot(
    np.sin(t) + rng.normal(scale=0.05, size=len(t)),
    color="#4fc3f7", label="channel A")

sp_right = fig1.add_subplot(gs1[0, 1]).plot(
    np.cos(t) + rng.normal(scale=0.05, size=len(t)),
    color="#ff7043", label="channel B")

fig1  # Interactive

# ── 2. Image + two spectra (2×2, height_ratios=[3, 1]) ────────────────────────
# %%
# Image on top, two spectra below
# --------------------------------
# A ``2×2`` grid with ``height_ratios=[3, 1]`` puts a wide image in the upper
# three-quarters and two comparison spectra side-by-side in the lower quarter.
#
# The spanning subplot ``gs2[0, :]`` covers all columns in row 0, so the image
# gets the full figure width.

N = 128
x = np.linspace(-4, 4, N)
y = np.linspace(-4, 4, N)
XX, YY = np.meshgrid(x, y)
image = np.exp(-(XX**2 + YY**2) / 4) + 0.3 * np.exp(-((XX - 2)**2 + YY**2) / 1)
image += rng.normal(scale=0.03, size=image.shape)

gs2  = apl.GridSpec(2, 2, height_ratios=[3, 1])
fig2 = apl.Figure(figsize=(640, 560))

fig2.add_subplot(gs2[0, :]).imshow(image.astype(np.float32), cmap="inferno")

row_profile = image[N // 2, :]
col_profile = image[:, N // 2]

fig2.add_subplot(gs2[1, 0]).plot(
    row_profile, axes=[x], units="nm",
    color="#4fc3f7", label="row profile")

fig2.add_subplot(gs2[1, 1]).plot(
    col_profile, axes=[y], units="nm",
    color="#ff7043", label="col profile")

fig2  # Interactive

# ── 3. Image + histogram (2×1, height_ratios=[3, 1]) ──────────────────────────
# %%
# Image + histogram strip
# -----------------------
# A ``2×1`` grid with ``height_ratios=[3, 1]`` is the classic layout for
# showing an image with its intensity histogram below.  The image occupies
# three-quarters of the height; the histogram strip the remaining quarter.

gs3  = apl.GridSpec(2, 1, height_ratios=[3, 1])
fig3 = apl.Figure(figsize=(500, 600))

fig3.add_subplot(gs3[0, 0]).imshow(image.astype(np.float32), cmap="viridis")

counts, edges = np.histogram(image.ravel(), bins=64)
bin_centers   = 0.5 * (edges[:-1] + edges[1:])
fig3.add_subplot(gs3[1, 0]).plot(
    counts.astype(float), axes=[bin_centers],
    color="#aed581", label="histogram")

fig3  # Interactive

# ── 4. Three equal columns (1×3) ──────────────────────────────────────────────
# %%
# Three-column layout
# -------------------
# A ``1×3`` grid gives three equal panels that are easy to compare visually.
# Useful for showing the same quantity at three different conditions or times.

gs4  = apl.GridSpec(1, 3)
fig4 = apl.Figure(figsize=(900, 240))

spectra = [
    np.sin(t * (i + 1)) + rng.normal(scale=0.08, size=len(t))
    for i in range(3)
]
colors = ["#4fc3f7", "#ff7043", "#aed581"]
labels = ["f₁", "f₂", "f₃"]

for i, (data, color, label) in enumerate(zip(spectra, colors, labels)):
    fig4.add_subplot(gs4[0, i]).plot(data, color=color, label=label)

fig4  # Interactive

# ── 5. Asymmetric widths (1×2, width_ratios=[2, 1]) ──────────────────────────
# %%
# Asymmetric column widths
# ------------------------
# ``width_ratios=[2, 1]`` makes the left panel twice as wide as the right.
# A common use-case is a broad overview spectrum on the left and a zoomed
# detail region on the right.

energy = np.linspace(280, 295, 1024)
peak   = np.exp(-0.5 * ((energy - 284.8) / 0.3)**2)
peak2  = 0.35 * np.exp(-0.5 * ((energy - 286.2) / 0.3)**2)
spectrum = peak + peak2 + 0.1 * np.exp(-0.05 * (energy - 280)) \
           + rng.normal(scale=0.01, size=len(energy))

gs5  = apl.GridSpec(1, 2, width_ratios=[2, 1])
fig5 = apl.Figure(figsize=(720, 260))

fig5.add_subplot(gs5[0, 0]).plot(
    spectrum, axes=[energy], units="eV",
    color="#4fc3f7", label="survey")

mask  = (energy >= 283.5) & (energy <= 286.5)
fig5.add_subplot(gs5[0, 1]).plot(
    spectrum[mask], axes=[energy[mask]], units="eV",
    color="#ff7043", label="detail")

fig5  # Interactive

# ── 6. Complex layout: spanning top + two bottom (2×2, height_ratios=[2, 1]) ──
# %%
# Complex layout: spanning top panel
# -----------------------------------
# A ``2×2`` grid where ``gs6[0, :]`` spans both columns creates a wide panel
# on top (e.g. a summed spectrum) with two comparison panels below it.
# ``height_ratios=[2, 1]`` gives the top panel twice the height of each bottom
# panel.

summed = spectrum + rng.normal(scale=0.02, size=len(energy))
diff1  = rng.normal(scale=0.05, size=len(energy))
diff2  = rng.normal(scale=0.05, size=len(energy))

gs6  = apl.GridSpec(2, 2, height_ratios=[2, 1])
fig6 = apl.Figure(figsize=(720, 480))

fig6.add_subplot(gs6[0, :]).plot(
    summed, axes=[energy], units="eV",
    color="#4fc3f7", label="summed")

fig6.add_subplot(gs6[1, 0]).plot(
    diff1, axes=[energy], units="eV",
    color="#ff7043", label="Δ channel 1")

fig6.add_subplot(gs6[1, 1]).plot(
    diff2, axes=[energy], units="eV",
    color="#aed581", label="Δ channel 2")

fig6  # Interactive

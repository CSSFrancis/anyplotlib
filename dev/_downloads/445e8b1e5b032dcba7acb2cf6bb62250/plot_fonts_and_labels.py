"""
Fonts and Labels
================

All text in anyplotlib — titles, axis labels, the colorbar label and
``texts`` markers — is drawn straight onto the canvas.  Sizes are CSS
pixels, and strings may use a small TeX subset inside ``$...$``.

This example walks through the options for text markers added with
:meth:`~anyplotlib.plot2d.Plot2D.add_texts`: size, weight, outline,
rotation, anchor alignment and math, plus the panel's own labels.
"""
import numpy as np
import anyplotlib as apl

rng = np.random.default_rng(11)
# A busy, non-square image: 180 rows x 260 columns.
data = rng.standard_normal((180, 260)).cumsum(0).cumsum(1)
data = (data - data.min()) / np.ptp(data)
# Calibrated axes so the panel shows ticks and axis labels.  Marker offsets
# below stay in image pixels (column, row).
x_nm = np.arange(260) * 0.05
y_nm = np.arange(180) * 0.05


def panel(title):
    fig, ax = apl.subplots(1, 1, figsize=(560, 420))
    plot = ax.imshow(data, axes=[x_nm, y_nm], units="nm", cmap="gray")
    plot.set_title(title, fontsize=14)
    return fig, plot


# %%
# Panel labels
# ------------
# Titles, axis labels and the colorbar label take an optional ``fontsize``
# and the same ``$...$`` markup as text markers.

fig, v = panel(r"Panel labels: $\lambda$ = 2.5 $\AA$")
v.set_xlabel(r"$x$ (nm)", fontsize=13)
v.set_ylabel(r"$y$ (nm)", fontsize=13)
v.set_colorbar_visible(True)
v.set_colorbar_label(r"Intensity ($\times 10^{3}$)", fontsize=11)
v.set_tick_label_size(11)
fig

# %%
# Size and weight
# ---------------
# ``fontsize`` and ``fontweight`` apply to the whole group, so labels that
# differ in either go in separate groups.

fig, v = panel("Size and weight")
for i, (size, weight) in enumerate([(12, "normal"), (16, "normal"),
                                    (16, "bold"), (24, "bold")]):
    v.add_texts([[12, 20 + 38 * i]], [f"{size} px {weight}"],
                name=f"size{i}", color="#ffeb3b",
                fontsize=size, fontweight=weight)
fig

# %%
# Outline for legibility
# ----------------------
# Over a busy image a label can vanish into the background.  An
# ``outline_color`` strokes a halo under the fill; ``outline_width`` sets
# its thickness in pixels.

fig, v = panel("Outline (halo)")
v.add_texts([[12, 40]], ["no outline"], name="plain",
            color="#ffffff", fontsize=20, fontweight="bold")
v.add_texts([[12, 100]], ["outline_color='black'"], name="halo",
            color="#ffffff", fontsize=20, fontweight="bold",
            outline_color="#000000", outline_width=4)
fig

# %%
# Rotation
# --------
# ``rotation`` is in **radians** (matplotlib's ``TextCollection``
# convention) and turns the label counter-clockwise about its anchor point.

fig, v = panel("Rotation about the anchor")
anchor = [40, 165]
v.add_points([anchor], name="anchor", sizes=4, color="#ff1744",
             facecolors="#ff1744")
for deg in (0, 45, 90):
    # Leading spaces push the text off the anchor dot.
    v.add_texts([anchor], [f"   rotation = {deg}\N{DEGREE SIGN}"],
                name=f"rot{deg}", color="#00e5ff", fontsize=16,
                outline_color="#000000", rotation=np.deg2rad(deg),
                verticalalignment="center")
fig

# %%
# Alignment
# ---------
# ``horizontalalignment`` (``"left"``, ``"center"``, ``"right"``) and
# ``verticalalignment`` (``"top"``, ``"center"``, ``"bottom"``,
# ``"baseline"``) choose which point of the text sits on the anchor.  The
# defaults, ``"left"`` and ``"top"``, hang the label below and to the right.

fig, v = panel("horizontal / vertical alignment")
cols = {"left": 45, "center": 130, "right": 215}
rows = {"top": 40, "center": 90, "bottom": 140}
for ha, x in cols.items():
    for va, y in rows.items():
        v.add_points([[x, y]], name=f"pt-{ha}-{va}", sizes=3,
                     color="#ff1744", facecolors="#ff1744")
        v.add_texts([[x, y]], [f"{ha}/{va}"], name=f"txt-{ha}-{va}",
                    color="#ffeb3b", fontsize=13, outline_color="#000000",
                    horizontalalignment=ha, verticalalignment=va)
fig

# %%
# Math in labels
# --------------
# Text with an even number of ``$`` signs is typeset: superscripts,
# subscripts, Greek letters and ``\mathrm{}`` for upright text.  Weight and
# outline still apply.  As in matplotlib, a string with a single (odd)
# ``$`` is plain text, so prices and shell prompts draw as written.

fig, v = panel("TeX in text markers")
v.add_texts([[12, 25]], [r"$\mathrm{Fe} K_{\alpha}$ edge"], name="edge",
            color="#ffeb3b", fontsize=18, outline_color="#000000")
v.add_texts([[12, 65]], [r"$\sigma$ = $10^{-3}$ nm$^{-1}$"],
            name="sigma", color="#ffeb3b", fontsize=18, fontweight="bold",
            outline_color="#000000")
v.add_texts([[12, 105]], [r"$\Delta E \approx$ 1.2 eV"],
            name="delta", color="#00e5ff", fontsize=18,
            outline_color="#000000")
v.add_texts([[12, 145]], ["Plain text: $5 each"], name="plain",
            color="#ffffff", fontsize=16, outline_color="#000000")
fig

# %%
# Live update
# -----------
# Every option can change after the label is drawn with ``set(...)``.

v.markers["texts"]["edge"].set(fontsize=22, fontweight="bold",
                               rotation=np.deg2rad(-8))
fig

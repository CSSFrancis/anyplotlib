"""
Subplot Spacing with subplots_adjust
=====================================

:meth:`~anyplotlib.Figure.subplots_adjust` controls the gap between panels in
a multi-panel figure.

* **hspace** — vertical gap as a fraction of the mean row height.
  ``hspace=0.15`` adds 15 % of the average row height as space between rows.
* **wspace** — horizontal gap as a fraction of the mean column width.
  ``wspace=0.10`` adds 10 % of the average column width as space between
  columns.

Both values default to ``0.0`` (panels are flush with no gap).

The examples below compare default flush spacing against adjusted spacing on
the same 2 × 2 grid.
"""
import numpy as np
import anyplotlib as apl

rng = np.random.default_rng(42)
t   = np.linspace(0, 2 * np.pi, 512)

COLORS  = ["#4fc3f7", "#ff7043", "#aed581", "#ffd54f"]
LABELS  = ["α", "β", "γ", "δ"]
SIGNALS = [
    np.sin(t * (i + 1)) + rng.normal(scale=0.08, size=len(t))
    for i in range(4)
]


def _fill_grid(fig):
    """Add four 1-D spectra to a 2×2 Figure."""
    import anyplotlib as _apl
    gs = _apl.GridSpec(2, 2)
    positions = [(0, 0), (0, 1), (1, 0), (1, 1)]
    for idx, (r, c) in enumerate(positions):
        ax = fig.add_subplot(gs[r, c])
        ax.plot(SIGNALS[idx], color=COLORS[idx], label=LABELS[idx])


# ── 1. Default spacing (flush) ────────────────────────────────────────────────
# %%
# Default spacing — panels flush
# --------------------------------
# Without calling ``subplots_adjust`` the panels abut each other with no gap.

fig1 = apl.Figure(2, 2, figsize=(680, 480))
_fill_grid(fig1)

fig1  # Interactive

# ── 2. Vertical gap only (hspace) ────────────────────────────────────────────
# %%
# Vertical gap only — hspace=0.15
# ---------------------------------
# ``subplots_adjust(hspace=0.15)`` inserts a vertical gap equal to 15 % of
# the mean row height between the two rows.

fig2 = apl.Figure(2, 2, figsize=(680, 480))
_fill_grid(fig2)
fig2.subplots_adjust(hspace=0.15)

fig2  # Interactive

# ── 3. Horizontal gap only (wspace) ──────────────────────────────────────────
# %%
# Horizontal gap only — wspace=0.10
# -----------------------------------
# ``subplots_adjust(wspace=0.10)`` inserts a horizontal gap equal to 10 % of
# the mean column width between the two columns.

fig3 = apl.Figure(2, 2, figsize=(680, 480))
_fill_grid(fig3)
fig3.subplots_adjust(wspace=0.10)

fig3  # Interactive

# ── 4. Both gaps ─────────────────────────────────────────────────────────────
# %%
# Both hspace and wspace
# -----------------------
# Combine both arguments to add space in both directions.

fig4 = apl.Figure(2, 2, figsize=(680, 480))
_fill_grid(fig4)
fig4.subplots_adjust(hspace=0.15, wspace=0.10)

fig4  # Interactive

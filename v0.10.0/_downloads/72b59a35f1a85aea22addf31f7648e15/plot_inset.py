"""
Inset Plots
===========

Floating informational sub-plots that overlay the main figure — useful for
displaying supplementary data alongside a primary image, as seen in orientation
mapping, phase analysis, and similar workflows.

Each inset has a **title bar** with two buttons:

* **−** (minimize) — collapses the inset to its title bar only.
* **⤢** (maximize) — expands the inset to ~72 % of the figure, centred.
  Click **⤡** to restore.

Multiple insets sharing the same ``corner`` auto-stack so they never overlap
in the minimised or normal state.

Python-side state can also be set programmatically::

    inset.minimize()
    inset.maximize()
    inset.restore()
    print(inset.inset_state)  # "normal" | "minimized" | "maximized"
"""

import numpy as np
import anyplotlib as apl

rng = np.random.default_rng(42)

# ── Helpers — synthetic data ──────────────────────────────────────────────────

def _diffraction(N=256):
    """Simulated diffraction pattern (Gaussian rings)."""
    y, x = np.ogrid[-N//2:N//2, -N//2:N//2]
    r = np.hypot(x, y)
    img = np.zeros((N, N))
    for r0, sigma, amp in [(40, 6, 1.0), (80, 8, 0.6), (120, 10, 0.3)]:
        img += amp * np.exp(-((r - r0) ** 2) / (2 * sigma ** 2))
    img += rng.normal(0, 0.04, img.shape)
    return img

def _phase_map(N=128):
    """Fake two-phase orientation map."""
    img = rng.integers(0, 4, (N, N), dtype=np.uint8)
    # blob of phase 2 in the centre
    cy, cx = N // 2, N // 2
    yy, xx = np.ogrid[:N, :N]
    img[((yy - cy)**2 + (xx - cx)**2) < (N // 4)**2] = np.uint8(5)
    return img.astype(float)

def _pole_figure(N=96):
    """Simulated pole-figure intensity (radial Gaussian blob)."""
    y, x = np.ogrid[-N//2:N//2, -N//2:N//2]
    r = np.hypot(x, y)
    return np.exp(-(r ** 2) / (2 * (N // 6) ** 2)) + rng.normal(0, 0.02, (N, N))

def _virtual_adf(N=128):
    """Annular dark-field signal for a simple lattice."""
    y, x = np.mgrid[:N, :N]
    return (np.sin(y * 0.4) * np.cos(x * 0.4)) ** 2 + rng.normal(0, 0.05, (N, N))

# ── Build figure ──────────────────────────────────────────────────────────────

fig, ax = apl.subplots(1, 1, figsize=(660, 500))

# Primary large image: diffraction pattern
main = ax.imshow(_diffraction(256), cmap="inferno")

# ── Inset 1: phase map (top-right) ───────────────────────────────────────────
inset_phase = fig.add_inset(0.27, 0.27, corner="top-right", title="Phase Map")
inset_phase.imshow(_phase_map(128), cmap="tab10")

# ── Inset 2: pole figure — stacks below inset 1 in the same corner ────────────
inset_pole = fig.add_inset(0.27, 0.27, corner="top-right", title="Pole Figure")
inset_pole.imshow(_pole_figure(96), cmap="hot")

# ── Inset 3: virtual ADF (bottom-left) ────────────────────────────────────────
inset_adf = fig.add_inset(0.27, 0.27, corner="bottom-left", title="Virtual ADF")
inset_adf.imshow(_virtual_adf(128), cmap="gray")

# ── Inset 4: 1-D line profile (bottom-right) ─────────────────────────────────
x_nm  = np.linspace(0, 10, 256)
profile = np.sin(x_nm * 3.5) * np.exp(-x_nm * 0.18) + rng.normal(0, 0.05, 256)

inset_line = fig.add_inset(0.30, 0.22, corner="bottom-right", title="Line Profile")
inset_line.plot(profile, axes=[x_nm], units="nm", color="#4fc3f7", linewidth=1.5)

fig


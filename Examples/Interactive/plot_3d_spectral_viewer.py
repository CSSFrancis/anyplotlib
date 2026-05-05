"""
Interactive 3D Spectral Viewer
==============================

A side-by-side viewer for a 3-D ``(y, x, energy)`` dataset.

* **Left panel** — 2-D projection image (sum over the energy axis).
  A draggable crosshair ROI selects the pixel whose spectrum appears on
  the right.  Press **i** to switch to an 8 × 8-pixel rectangle ROI
  that integrates the enclosed area; press **i** again to revert.
* **Right panel** — 1-D spectrum extracted at the current ROI.  Press
  **s** to overlay an energy-span widget; on release the 2-D image
  recomputes as the sum over the selected energy window.  Press **s**
  again to remove the span and restore the full-sum image.

**Key bindings**

.. list-table::
   :header-rows: 1
   :widths: 10 10 80

   * - Panel
     - Key
     - Action
   * - Image
     - ``i``
     - Toggle crosshair / 8x8-px rectangle ROI.
       Rectangle snaps to the pixel grid and integrates the spectrum live.
       Press again to revert.
   * - Spectrum
     - ``s``
     - Add/remove an energy-span filter.
       The 2-D image updates on release to show the sum over the selected
       energy window.  Press again to restore the full-sum image.
   * - Both
     - ``r``
     - Reset zoom / pan.
"""

import numpy as np
import anyplotlib as vw

# ── Synthetic (NY, NX, NE) dataset ─────────────────────────────────────────
rng = np.random.default_rng(7)

NY, NX, NE = 64, 64, 256
energy = np.linspace(100, 900, NE)          # physical energy axis (eV)

yy, xx = np.mgrid[0:NY, 0:NX]              # spatial index grids


def _gauss2d(cx, cy, sigma):
    return np.exp(-((xx - cx) ** 2 + (yy - cy) ** 2) / (2 * sigma ** 2))


def _gauss1d(e, mu, sigma):
    return np.exp(-0.5 * ((e - mu) / sigma) ** 2)


# Three Gaussian peaks with spatially-varying amplitudes
_peaks = [
    dict(e_mu=280.0, e_sig=18.0, cx=18, cy=18, sig2d=14),
    dict(e_mu=500.0, e_sig=22.0, cx=46, cy=20, sig2d=13),
    dict(e_mu=710.0, e_sig=28.0, cx=32, cy=48, sig2d=16),
]

data = np.zeros((NY, NX, NE), dtype=np.float32)
for _p in _peaks:
    _amp = _gauss2d(_p["cx"], _p["cy"], _p["sig2d"])          # (NY, NX)
    _sp  = _gauss1d(energy,   _p["e_mu"],  _p["e_sig"])       # (NE,)
    data += (_amp[:, :, np.newaxis] * _sp[np.newaxis, np.newaxis, :]).astype(np.float32)

data += rng.normal(scale=0.02, size=data.shape).astype(np.float32)

img_full = data.sum(axis=-1).astype(float)   # full-energy projection (NY, NX)

# Initial ROI centre
CX0, CY0 = NX // 2, NY // 2

# ── Figure layout ───────────────────────────────────────────────────────────
fig, (ax_img, ax_spec) = vw.subplots(
    1, 2,
    figsize=(950, 460),
    help=(
        "Image  — drag crosshair to pick a spectrum\n"
        "       — press i: toggle crosshair / 8×8 rectangle ROI\n"
        "Spectrum — press s: add/remove energy-span filter"
    ),
)

# ── Left: 2-D projection image ──────────────────────────────────────────────
v_img = ax_img.imshow(img_full)
v_img.set_colormap("viridis")

# ── Right: 1-D spectrum at initial position ─────────────────────────────────
v_spec = ax_spec.plot(
    data[CY0, CX0, :].astype(float),
    axes=[energy],
    units="eV",
    y_units="Intensity (a.u.)",
    color="#4fc3f7",
    linewidth=1.5,
)

# ── Shared state (lists so closures can mutate them) ────────────────────────
wid      = [None]    # active 2-D ROI widget
mode     = ["crosshair"]  # "crosshair" or "rectangle"
span_wid = [None]    # active energy-span widget (or None)
_syncing = [False]   # echo-loop guard for rectangle snap

ROI_PX = 8           # rectangle ROI fixed size (pixels)


# ── Helpers ─────────────────────────────────────────────────────────────────

def _snap_rect(x_raw, y_raw):
    """Snap top-left corner to the nearest integer pixel, clamped to bounds."""
    x0 = int(np.clip(round(float(x_raw)), 0, NX - ROI_PX))
    y0 = int(np.clip(round(float(y_raw)), 0, NY - ROI_PX))
    return x0, y0


def _wire_crosshair(w):
    """Register on_changed: update spectrum on every drag frame."""
    @w.on_changed
    def _ch_moved(event):
        cx = int(np.clip(round(event.data.get("cx", CX0)), 0, NX - 1))
        cy = int(np.clip(round(event.data.get("cy", CY0)), 0, NY - 1))
        v_spec.set_data(data[cy, cx, :].astype(float), x_axis=energy)


def _wire_rectangle(w):
    """Register on_changed: snap widget to grid, integrate 8×8 region live."""
    @w.on_changed
    def _rect_moved(event):
        if _syncing[0]:
            return
        _syncing[0] = True
        try:
            x0, y0 = _snap_rect(
                event.data.get("x", CX0 - ROI_PX // 2),
                event.data.get("y", CY0 - ROI_PX // 2),
            )
            # Push snapped, fixed-size position back so the widget visually
            # snaps to the pixel grid and stays exactly 8×8.
            w.set(x=float(x0), y=float(y0), w=float(ROI_PX), h=float(ROI_PX))
            spec = data[y0:y0 + ROI_PX, x0:x0 + ROI_PX, :].mean(axis=(0, 1))
            v_spec.set_data(spec.astype(float), x_axis=energy)
        finally:
            _syncing[0] = False


# ── Install initial crosshair ────────────────────────────────────────────────
wid[0] = v_img.add_widget(
    "crosshair",
    cx=float(CX0), cy=float(CY0),
    color="#69f0ae",
)
_wire_crosshair(wid[0])


# ── "i" — toggle crosshair ↔ 8×8 rectangle ─────────────────────────────────
@v_img.on_key('i')
def _toggle_roi(event):
    cur = wid[0]
    v_img.remove_widget(cur)          # remove old widget (Python ref still valid)

    if mode[0] == "crosshair":
        # Preserve crosshair centre as rectangle anchor
        cx_cur = float(cur.get("cx", CX0))
        cy_cur = float(cur.get("cy", CY0))
        x0, y0 = _snap_rect(cx_cur - ROI_PX / 2, cy_cur - ROI_PX / 2)
        new_w = v_img.add_widget(
            "rectangle",
            x=float(x0), y=float(y0),
            w=float(ROI_PX), h=float(ROI_PX),
            color="#ffeb3b",
        )
        _wire_rectangle(new_w)
        wid[0]  = new_w
        mode[0] = "rectangle"
    else:
        # Restore crosshair at centre of old rectangle
        rx = float(cur.get("x", CX0 - ROI_PX // 2))
        ry = float(cur.get("y", CY0 - ROI_PX // 2))
        cx_cur = rx + ROI_PX / 2
        cy_cur = ry + ROI_PX / 2
        new_w = v_img.add_widget(
            "crosshair",
            cx=float(np.clip(cx_cur, 0, NX - 1)),
            cy=float(np.clip(cy_cur, 0, NY - 1)),
            color="#69f0ae",
        )
        _wire_crosshair(new_w)
        wid[0]  = new_w
        mode[0] = "crosshair"


# ── "s" (spectrum panel) — add / remove energy-span filter ──────────────────
@v_spec.on_key('s')
def _toggle_span(event):
    if span_wid[0] is None:
        # Place span at 35 %–65 % of the energy range by default
        e0 = float(energy[int(NE * 0.35)])
        e1 = float(energy[int(NE * 0.65)])
        sw = v_spec.add_range_widget(x0=e0, x1=e1, color="#ff7043")
        span_wid[0] = sw

        @sw.on_release
        def _span_released(ev):
            x0_e = ev.data.get("x0", float(energy[0]))
            x1_e = ev.data.get("x1", float(energy[-1]))
            if x0_e > x1_e:
                x0_e, x1_e = x1_e, x0_e
            mask = (energy >= x0_e) & (energy <= x1_e)
            new_img = data[..., mask].sum(axis=-1).astype(float) if mask.any() else img_full
            v_img.set_data(new_img)
    else:
        v_spec.remove_widget(span_wid[0])
        span_wid[0] = None
        v_img.set_data(img_full)      # restore full-energy projection


fig  # Interactive


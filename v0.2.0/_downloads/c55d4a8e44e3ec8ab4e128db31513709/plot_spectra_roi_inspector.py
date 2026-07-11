"""
ROI-to-spectrum inspector for a 3-D EDS hyperspectral dataset.
==============================================================

A synthetic ``(256, 256, 300)`` EDS datacube — one 300-channel
spectrum per scan position.  Four rectangular ROIs overlay the
total-counts image (HAADF proxy).  Entering an ROI **sums all spectra
within the rectangle** (spatial sum over every scan position in the
box) and displays the result in the top-right panel.  Draggable
coloured range widgets on the spectrum define the integration window
for each element; each bar height is the **channel sum of the ROI
spectrum within that window**.

**Interaction**

* **Move cursor inside an ROI** — spatially sums the spectra of all
  scan positions inside the box; updates the line plot and bars live.
* **Drag an ROI rectangle** — repositions the ROI on the image.
* **Release drag** — recomputes the spatial sum spectrum for the new
  position.
* **Drag a coloured range widget** on the spectrum — adjusts the
  integration window for that element; bar heights update on every
  drag frame.
"""
import numpy as np
import anyplotlib as apl


# ── synthetic 3-D hyperspectral datacube ──────────────────────────────────────
# Shape: (NY, NX, NC).  dataset[y, x, :] is the 300-channel EDS spectrum at
# scan position (x, y).  Each pixel is an independent Poisson draw from the
# expected spectrum for its phase.

NY, NX, NC = 256, 256, 300
ENERGY = np.linspace(0.1, 3.0, NC)   # keV

EDS_ELEMENTS = ["O", "Fe", "Al", "Si"]
_EDS_EV      = [0.525, 0.710, 1.487, 1.740]   # characteristic keV
_EDS_WIN     = [(0.45, 0.61), (0.64, 0.80), (1.40, 1.58), (1.65, 1.83)]
_EDS_SIGMA   = 0.025
_EDS_COLORS  = ["#ff8a65", "#ba68c8", "#4fc3f7", "#aed581"]

_PEAKS = np.array([
    np.exp(-0.5 * ((ENERGY - ev) / _EDS_SIGMA) ** 2)
    for ev in _EDS_EV
])   # shape (4, NC)

# Per-phase element weight vectors [O, Fe, Al, Si] and expected total
# counts per pixel (determines peak-to-background ratio and brightness).
_PHASE_DEFS = [
    dict(weights=[0.10, 0.05, 0.65, 0.20], counts=80),    # 0 Matrix
    dict(weights=[0.05, 0.08, 0.12, 0.75], counts=200),   # 1 Precipitate A
    dict(weights=[0.12, 0.60, 0.18, 0.10], counts=150),   # 2 Precipitate B
    dict(weights=[0.62, 0.12, 0.18, 0.08], counts=110),   # 3 Grain Boundary
]


def _expected_spectrum(phase_idx: int) -> np.ndarray:
    p = _PHASE_DEFS[phase_idx]
    bkg  = 3.0 * np.exp(-ENERGY / 0.8)
    spec = bkg + (_PEAKS * np.array(p["weights"])[:, None]).sum(axis=0) * p["counts"]
    return np.clip(spec, 0, None).astype(np.float64)


def _make_dataset(rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
    phases = np.zeros((NY, NX), dtype=np.int8)   # 0 = Matrix

    # Precipitate A (Si-rich) — cluster in top-left quadrant
    for cx, cy, r in [(60, 60, 30), (75, 50, 22), (45, 75, 20)]:
        ys, xs = np.ogrid[:NY, :NX]
        phases[(xs - cx) ** 2 + (ys - cy) ** 2 < r ** 2] = 1

    # Precipitate B (Fe-rich) — cluster in bottom-right quadrant
    for cx, cy, r in [(195, 195, 27), (180, 210, 20), (210, 180, 17)]:
        ys, xs = np.ogrid[:NY, :NX]
        phases[(xs - cx) ** 2 + (ys - cy) ** 2 < r ** 2] = 2

    # Grain boundary — thin horizontal band
    phases[120:135, :] = 3

    dataset = np.empty((NY, NX, NC), dtype=np.float32)
    flat    = dataset.reshape(-1, NC)
    phases_flat = phases.ravel()
    for pidx, pdef in enumerate(_PHASE_DEFS):
        sel = phases_flat == pidx
        n   = int(sel.sum())
        if n == 0:
            continue
        lam = _expected_spectrum(pidx)
        flat[sel] = rng.poisson(lam, size=(n, NC)).astype(np.float32)

    return dataset, phases


rng     = np.random.default_rng(99)
dataset, _phase_map = _make_dataset(rng)

# Total-counts image used as the HAADF-proxy display image
_display_img = dataset.sum(axis=2)


# ── ROI definitions (r0, r1, c0, c1) in scan-pixel coordinates ────────────────

ROIS: dict[str, tuple[int, int, int, int]] = {
    "Matrix":         ( 25, 100, 155, 230),
    "Precipitate A":  ( 25, 100,  25, 100),
    "Precipitate B":  (155, 230, 155, 230),
    "Grain Boundary": (115, 140,  25, 230),
}
_ROI_COLORS: dict[str, str] = {
    "Matrix":         "#4fc3f7",
    "Precipitate A":  "#aed581",
    "Precipitate B":  "#ff8a65",
    "Grain Boundary": "#ba68c8",
}


def _sum_spectrum(r0: int, r1: int, c0: int, c1: int) -> np.ndarray:
    """Spatial sum of all spectra within the ROI box."""
    r0 = max(0, min(NY - 1, r0));  r1 = max(1, min(NY, r1))
    c0 = max(0, min(NX - 1, c0));  c1 = max(1, min(NX, c1))
    return dataset[r0:r1, c0:c1, :].sum(axis=(0, 1))


def _roi_at(x: float, y: float) -> str | None:
    for name, (r0, r1, c0, c1) in ROIS.items():
        if c0 <= x <= c1 and r0 <= y <= r1:
            return name
    return None


# ── layout ─────────────────────────────────────────────────────────────────────

fig = apl.Figure(figsize=(1100, 560))
gs  = apl.GridSpec(2, 2, width_ratios=[1, 1], height_ratios=[1, 1])

ax_img  = fig.add_subplot(gs[:, 0])   # total-counts image — left column
ax_spec = fig.add_subplot(gs[0, 1])   # ROI sum spectrum   — top right
ax_bar  = fig.add_subplot(gs[1, 1])   # element bar chart  — bottom right

img_plot = ax_img.imshow(_display_img, cmap="gray")

_init_spec = _sum_spectrum(*ROIS["Matrix"]).astype(np.float32)
spec_plot  = ax_spec.plot(_init_spec, axes=[ENERGY],
                          color=_ROI_COLORS["Matrix"], linewidth=1.5,
                          units="keV", y_units="counts")
bar_plot   = ax_bar.bar(EDS_ELEMENTS, [0.0] * 4)


# ── ROI rectangle overlays on the image ───────────────────────────────────────

_roi_widgets: dict[str, object] = {}
for roi_name, (r0, r1, c0, c1) in ROIS.items():
    w = img_plot.add_widget(
        "rectangle",
        x=float(c0), y=float(r0),
        w=float(c1 - c0), h=float(r1 - r0),
        color=_ROI_COLORS[roi_name],
    )
    _roi_widgets[roi_name] = w

status_label = img_plot.add_widget(
    "label", x=4, y=248, text="Move cursor into an ROI",
    color="#ffffff", fontsize=10,
)


# ── adjustable range widgets on the spectrum ───────────────────────────────────

range_widgets: dict[str, object] = {}
for elem, (lo, hi), color in zip(EDS_ELEMENTS, _EDS_WIN, _EDS_COLORS):
    range_widgets[elem] = spec_plot.add_range_widget(lo, hi, color=color)

_current_spectrum: list[np.ndarray] = [_init_spec.copy()]


def _channel_sum(x0: float, x1: float) -> float:
    """Sum of ROI spectrum counts within the energy window [x0, x1]."""
    mask = (ENERGY >= x0) & (ENERGY <= x1)
    return float(_current_spectrum[0][mask].sum()) if mask.any() else 0.0


def _update_bars() -> None:
    heights = np.array([
        _channel_sum(range_widgets[e].x0, range_widgets[e].x1)
        for e in EDS_ELEMENTS
    ])
    max_h = heights.max() or 1.0
    bar_plot.set_data((heights / max_h).tolist())


for _rw in range_widgets.values():
    _rw.add_event_handler(lambda event: _update_bars(), "pointer_move")
    _rw.add_event_handler(lambda event: _update_bars(), "pointer_up")

_update_bars()


# ── update helper ──────────────────────────────────────────────────────────────

_current_roi: list[str | None] = [None]
_roi_dragging = False


def _update_for_roi(roi_name: str) -> None:
    _current_roi[0] = roi_name
    r0, r1, c0, c1 = ROIS[roi_name]
    _current_spectrum[0] = _sum_spectrum(r0, r1, c0, c1).astype(np.float32)
    spec_plot.set_data(_current_spectrum[0], x_axis=ENERGY)
    spec_plot.set_color(_ROI_COLORS[roi_name])
    _update_bars()
    n_pixels = (r1 - r0) * (c1 - c0)
    status_label.set(text=f"ROI: {roi_name}  ({n_pixels} px)")


# ── event handlers ─────────────────────────────────────────────────────────────

def _on_move(event) -> None:
    if _roi_dragging or event.xdata is None or event.ydata is None:
        return
    roi_name = _roi_at(event.xdata, event.ydata)
    if roi_name is None or roi_name == _current_roi[0]:
        return
    _update_for_roi(roi_name)


def _on_enter(event) -> None:
    status_label.set(text="Move cursor into an ROI")


def _on_leave(event) -> None:
    status_label.set(text="Move cursor over image to inspect")
    _current_roi[0] = None


img_plot.add_event_handler(_on_move,  "pointer_move")
img_plot.add_event_handler(_on_enter, "pointer_enter")
img_plot.add_event_handler(_on_leave, "pointer_leave")

for roi_name, widget in _roi_widgets.items():
    def _make_drag_handler():
        def _on_drag(event) -> None:
            global _roi_dragging
            _roi_dragging = True
        return _on_drag

    def _make_release_handler(name, wgt):
        def _on_release(event) -> None:
            global _roi_dragging
            _roi_dragging = False
            x, y, w, h = wgt.x, wgt.y, wgt.w, wgt.h
            ROIS[name] = (int(y), int(y + h), int(x), int(x + w))
            _update_for_roi(name)
        return _on_release

    widget.add_event_handler(_make_drag_handler(), "pointer_move")
    widget.add_event_handler(_make_release_handler(roi_name, widget), "pointer_up")

fig.set_help(
    "Move cursor inside an ROI: spatial sum spectrum + bars\n"
    "Drag ROI rectangle: repositions ROI; release recomputes\n"
    "Drag a coloured range widget: adjust element integration window"
)

fig  # Interactive

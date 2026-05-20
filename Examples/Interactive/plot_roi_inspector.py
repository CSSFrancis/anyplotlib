"""
ROI-to-spectrum inspector for a multi-phase STEM image.
========================================================

Four rectangular ROIs overlay a synthetic 512×512 STEM image.  Moving
the cursor inside any ROI recomputes the average EDS-like spectrum for
that region and refreshes both the continuous spectrum line plot and the
per-element bar chart in real time.  Integration windows are shown as
coloured spans on the spectrum.

**Interaction**

* **Move cursor inside an ROI** — updates the EDS spectrum and bar
  chart live as the cursor crosses ROI boundaries.
* **Drag an ROI rectangle** — repositions the ROI on the image.
* **Release drag** — recomputes the spectrum for the new position.
"""
import numpy as np
import anyplotlib as apl


# ── synthetic data ─────────────────────────────────────────────────────────────

def _make_multiphase_image(rng: np.random.Generator) -> np.ndarray:
    img = rng.normal(30, 6, (512, 512)).astype(np.float32)

    for cx, cy, r in [(120, 120, 60), (150, 100, 45), (90, 150, 40)]:
        ys, xs = np.ogrid[:512, :512]
        mask = (xs - cx) ** 2 + (ys - cy) ** 2 < r ** 2
        img[mask] = rng.normal(160, 12, mask.sum())

    for cx, cy, r in [(390, 390, 55), (360, 420, 40), (420, 360, 35)]:
        ys, xs = np.ogrid[:512, :512]
        mask = (xs - cx) ** 2 + (ys - cy) ** 2 < r ** 2
        img[mask] = rng.normal(110, 10, mask.sum())

    img[240:270, :] = rng.normal(70, 8, (30, 512))

    return np.clip(img, 0, 255).astype(np.float32)


rng = np.random.default_rng(99)
image = _make_multiphase_image(rng)


# ── EDS energy axis and element definitions ────────────────────────────────────

EDS_ENERGY   = np.linspace(0.1, 3.0, 600)   # keV
EDS_ELEMENTS = ["O", "Fe", "Al", "Si"]
_EDS_EV      = [0.525, 0.710, 1.487, 1.740]  # characteristic keV
_EDS_WIN     = [(0.45, 0.61), (0.64, 0.80), (1.40, 1.58), (1.65, 1.83)]
_EDS_SIGMA   = 0.028                          # peak width (keV)
_EDS_COLORS  = ["#ff8a65", "#ba68c8", "#4fc3f7", "#aed581"]

_PEAKS = np.array([
    np.exp(-0.5 * ((EDS_ENERGY - ev) / _EDS_SIGMA) ** 2)
    for ev in _EDS_EV
])

ROIS: dict[str, tuple[int, int, int, int]] = {
    "Matrix":         (50,  200, 50,  200),
    "Precipitate A":  (50,  200, 310, 460),
    "Precipitate B":  (310, 460, 50,  200),
    "Grain Boundary": (240, 270, 50,  460),
}
_ROI_WEIGHTS: dict[str, np.ndarray] = {
    "Matrix":         np.array([0.10, 0.05, 0.65, 0.20]),
    "Precipitate A":  np.array([0.05, 0.08, 0.12, 0.75]),
    "Precipitate B":  np.array([0.12, 0.60, 0.18, 0.10]),
    "Grain Boundary": np.array([0.62, 0.12, 0.18, 0.08]),
}
_ROI_COLORS: dict[str, str] = {
    "Matrix":         "#4fc3f7",
    "Precipitate A":  "#aed581",
    "Precipitate B":  "#ff8a65",
    "Grain Boundary": "#ba68c8",
}

_NOISE_RNG = np.random.default_rng(7)


def _eds_spectrum(roi_name: str) -> np.ndarray:
    r0, r1, c0, c1 = ROIS[roi_name]
    mean_val = float(image[r0:r1, c0:c1].mean()) / 255.0
    weights = _ROI_WEIGHTS[roi_name]
    spectrum = (_PEAKS * weights[:, None]).sum(axis=0) * mean_val
    spectrum += _NOISE_RNG.normal(0, 0.002, len(EDS_ENERGY))
    return np.clip(spectrum, 0, None)


def _eds_bars(spectrum: np.ndarray) -> np.ndarray:
    bars = np.array([
        spectrum[(EDS_ENERGY >= lo) & (EDS_ENERGY <= hi)].mean()
        for lo, hi in _EDS_WIN
    ])
    return bars / (bars.max() or 1.0)


def _roi_at(x: float, y: float) -> str | None:
    for name, (r0, r1, c0, c1) in ROIS.items():
        if c0 <= x <= c1 and r0 <= y <= r1:
            return name
    return None


# ── layout ─────────────────────────────────────────────────────────────────────

fig = apl.Figure(figsize=(1100, 560))
gs  = apl.GridSpec(2, 2, width_ratios=[1, 1], height_ratios=[1, 1])

ax_img  = fig.add_subplot(gs[:, 0])   # image — left column, full height
ax_spec = fig.add_subplot(gs[0, 1])   # EDS spectrum — top right
ax_bar  = fig.add_subplot(gs[1, 1])   # bar chart    — bottom right

img_plot  = ax_img.imshow(image, cmap="gray")

_init_spec = _eds_spectrum("Matrix")
spec_plot  = ax_spec.plot(_init_spec, axes=[EDS_ENERGY], color="#4fc3f7", linewidth=1.5)

_init_bars = _eds_bars(_init_spec)
bar_plot   = ax_bar.bar(EDS_ELEMENTS, _init_bars.tolist())


# ── ROI rectangle overlays ─────────────────────────────────────────────────────

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
    "label", x=10, y=498, text="Move cursor into an ROI",
    color="#ffffff", fontsize=10,
)

# Coloured integration-window spans on the spectrum (permanent)
for i, (lo, hi) in enumerate(_EDS_WIN):
    spec_plot.add_span(lo, hi, axis="x", color=f"{_EDS_COLORS[i]}44")

_current_roi: list[str | None] = [None]
_roi_dragging = False


# ── update helpers ─────────────────────────────────────────────────────────────

def _update_for_roi(roi_name: str) -> None:
    _current_roi[0] = roi_name
    spectrum = _eds_spectrum(roi_name)
    bars     = _eds_bars(spectrum)
    spec_plot.set_data(spectrum, x_axis=EDS_ENERGY)
    spec_plot.set_color(_ROI_COLORS[roi_name])
    bar_plot.set_data(bars.tolist())
    r0, r1, c0, c1 = ROIS[roi_name]
    mean_val = float(image[r0:r1, c0:c1].mean())
    status_label.set(text=f"ROI: {roi_name}  mean={mean_val:.0f}")


# ── event handlers ─────────────────────────────────────────────────────────────

def _on_move(event) -> None:
    if _roi_dragging or event.xdata is None or event.ydata is None:
        return
    roi_name = _roi_at(event.xdata, event.ydata)
    if roi_name is None:
        return
    if roi_name != _current_roi[0]:
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
    "Move cursor inside an ROI: live spectrum + bar update\n"
    "Drag ROI rectangle: repositions ROI\n"
    "Release drag: recomputes spectrum"
)

fig  # Interactive

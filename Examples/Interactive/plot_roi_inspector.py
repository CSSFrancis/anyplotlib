"""
ROI-to-spectrum inspector for a multi-phase STEM image.

Four rectangular ROIs are drawn on the image.  Entering the image panel
activates a pixel inspector in the status label.  Hovering over an ROI for
350 ms computes the mean EDS-like spectrum for that region and updates the bar
chart.  Dragging an ROI pauses spectrum recomputation to avoid backlog;
releasing triggers one final recompute.
"""
import numpy as np
import anyplotlib as apl


# ── synthetic data ─────────────────────────────────────────────────────────────

def _make_multiphase_image(rng: np.random.Generator) -> np.ndarray:
    img = rng.normal(30, 6, (512, 512)).astype(np.float32)

    # Precipitate A (bright)
    for cx, cy, r in [(120, 120, 60), (150, 100, 45), (90, 150, 40)]:
        ys, xs = np.ogrid[:512, :512]
        mask = (xs - cx) ** 2 + (ys - cy) ** 2 < r ** 2
        img[mask] = rng.normal(160, 12, mask.sum())

    # Precipitate B (medium)
    for cx, cy, r in [(390, 390, 55), (360, 420, 40), (420, 360, 35)]:
        ys, xs = np.ogrid[:512, :512]
        mask = (xs - cx) ** 2 + (ys - cy) ** 2 < r ** 2
        img[mask] = rng.normal(110, 10, mask.sum())

    # Grain boundary (thin horizontal band, rows 240-270)
    img[240:270, :] = rng.normal(70, 8, (30, 512))

    return np.clip(img, 0, 255).astype(np.float32)


def _mean_eds(img_patch: np.ndarray) -> np.ndarray:
    """4-channel EDS intensity proportional to local image value + noise."""
    mean_val = float(img_patch.mean())
    rng_local = np.random.default_rng(int(mean_val * 1000) % (2**31))
    weights = np.array([0.40, 0.25, 0.20, 0.15])
    spectrum = weights * mean_val + rng_local.normal(0, 2, 4)
    return np.clip(spectrum / 255.0, 0, 1)


rng = np.random.default_rng(99)
image = _make_multiphase_image(rng)

ROIS: dict[str, tuple[int, int, int, int]] = {
    "Matrix":        (50,  200, 50,  200),
    "Precipitate A": (50,  200, 310, 460),
    "Precipitate B": (310, 460, 50,  200),
    "Grain Boundary":(240, 270, 50,  460),
}

EDS_ELEMENTS = ["Al", "Si", "Fe", "O"]
_PLACEHOLDER = np.array([0.0, 0.0, 0.0, 0.0])


# ── helpers ────────────────────────────────────────────────────────────────────

def _roi_at(x: float, y: float) -> str | None:
    for name, (r0, r1, c0, c1) in ROIS.items():
        if c0 <= x <= c1 and r0 <= y <= r1:
            return name
    return None


# ── figure ─────────────────────────────────────────────────────────────────────

fig, (ax_img, ax_spec) = apl.subplots(1, 2, figsize=(1000, 520))

img_plot = ax_img.imshow(image, cmap="gray")
spec_plot = ax_spec.bar(EDS_ELEMENTS, _PLACEHOLDER)

# ROI rectangle widgets
_roi_widgets: dict[str, object] = {}
_ROI_COLORS = {"Matrix": "#4fc3f7", "Precipitate A": "#aed581",
               "Precipitate B": "#ff8a65", "Grain Boundary": "#ba68c8"}

for roi_name, (r0, r1, c0, c1) in ROIS.items():
    w = img_plot.add_widget(
        "rectangle",
        x=float(c0), y=float(r0),
        w=float(c1 - c0), h=float(r1 - r0),
        color=_ROI_COLORS[roi_name],
    )
    _roi_widgets[roi_name] = w

status_label = img_plot.add_widget(
    "label", x=10, y=498, text="Move cursor over image to inspect",
    color="#ffffff", fontsize=10,
)

_roi_dragging = False


# ── spectrum update ─────────────────────────────────────────────────────────────

def _update_spectrum(roi_name: str) -> None:
    r0, r1, c0, c1 = ROIS[roi_name]
    patch = image[r0:r1, c0:c1]
    eds = _mean_eds(patch)
    spec_plot.set_data(eds)
    print(f"ROI '{roi_name}': Al={eds[0]:.3f}  Si={eds[1]:.3f}  Fe={eds[2]:.3f}  O={eds[3]:.3f}")


# ── event handlers ─────────────────────────────────────────────────────────────

def _on_enter(event) -> None:
    status_label.set(text="Pixel: —  Intensity: —")


def _on_leave(event) -> None:
    status_label.set(text="Move cursor over image to inspect")


def _on_move(event) -> None:
    if event.xdata is None or event.ydata is None:
        return
    x = int(np.clip(round(event.xdata), 0, 511))
    y = int(np.clip(round(event.ydata), 0, 511))
    intensity = float(image[y, x])
    status_label.set(text=f"Pixel: ({x}, {y})  Intensity: {intensity:.0f}")


def _on_settled(event) -> None:
    if _roi_dragging or event.xdata is None or event.ydata is None:
        return
    roi_name = _roi_at(event.xdata, event.ydata)
    if roi_name is None:
        status_label.set(text="No ROI at cursor position")
        return
    with img_plot.hold_events("pointer_settled"):
        _update_spectrum(roi_name)


img_plot.add_event_handler(_on_enter, "pointer_enter")
img_plot.add_event_handler(_on_leave, "pointer_leave")
img_plot.add_event_handler(_on_move, "pointer_move")
img_plot.add_event_handler(_on_settled, "pointer_settled", ms=350)

# ROI widget drag handlers
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
            _update_spectrum(name)
        return _on_release

    widget.add_event_handler(_make_drag_handler(), "pointer_move")
    widget.add_event_handler(_make_release_handler(roi_name, widget), "pointer_up")

fig.set_help(
    "Move cursor over image: inspect pixel\n"
    "Dwell 350 ms inside ROI: compute EDS spectrum\n"
    "Drag ROI rectangle: repositions ROI\n"
    "Release drag: recomputes spectrum"
)

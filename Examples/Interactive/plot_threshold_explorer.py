"""
Live intensity thresholding on a multi-phase STEM image.

Scroll the mouse wheel over the image to adjust the threshold (2 counts per
tick).  Click a histogram bar to jump the threshold to that bin's upper edge.
Dwell (400 ms) over the image to inspect pixel intensity.  The threshold mask
is shown as a red overlay; the histogram always has a vertical line at the
current threshold.
"""
import numpy as np
import anyplotlib as apl


# ── synthetic data ─────────────────────────────────────────────────────────────

def _make_multiphase_image(rng: np.random.Generator) -> np.ndarray:
    img = rng.normal(20, 5, (512, 512)).astype(np.float32)

    # Grain A — 6 large blobs
    for _ in range(6):
        cx, cy = rng.integers(60, 452, size=2)
        r = rng.integers(40, 80)
        ys, xs = np.ogrid[:512, :512]
        mask = (xs - cx) ** 2 + (ys - cy) ** 2 < r ** 2
        img[mask] = rng.normal(80, 8, mask.sum())

    # Grain B — 8 smaller blobs
    for _ in range(8):
        cx, cy = rng.integers(40, 472, size=2)
        r = rng.integers(15, 35)
        ys, xs = np.ogrid[:512, :512]
        mask = (xs - cx) ** 2 + (ys - cy) ** 2 < r ** 2
        img[mask] = rng.normal(130, 10, mask.sum())

    # Voids — 12 dark circular regions
    for _ in range(12):
        cx, cy = rng.integers(20, 492, size=2)
        r = rng.integers(8, 20)
        ys, xs = np.ogrid[:512, :512]
        mask = (xs - cx) ** 2 + (ys - cy) ** 2 < r ** 2
        img[mask] = rng.normal(5, 2, mask.sum())

    return np.clip(img, 0, 255).astype(np.float32)


rng = np.random.default_rng(13)
image = _make_multiphase_image(rng)

NBINS = 32
counts, bin_edges = np.histogram(image, bins=NBINS, range=(0, 255))
bin_centers = 0.5 * (bin_edges[:-1] + bin_edges[1:])
x_labels = [f"{int(v)}" for v in bin_centers]

threshold = 100.0


# ── figure ─────────────────────────────────────────────────────────────────────

fig, (ax_img, ax_hist) = apl.subplots(1, 2, figsize=(900, 500))

img_plot = ax_img.imshow(image, cmap="gray")
hist_plot = ax_hist.bar(x_labels, counts.astype(float))

# Track the threshold vline widget so we can remove/replace it
_thresh_widget = None


def _pct_above(thresh: float) -> float:
    return 100.0 * float((image >= thresh).sum()) / image.size


def _update_display(thresh: float) -> None:
    global threshold, _thresh_widget
    threshold = float(np.clip(thresh, 0, 255))
    mask = image >= threshold
    img_plot.set_overlay_mask(mask, color="#ff0000", alpha=0.35)
    # Remove old threshold line widget and add a new one
    if _thresh_widget is not None:
        try:
            hist_plot.remove_widget(_thresh_widget)
        except KeyError:
            pass
    _thresh_widget = hist_plot.add_vline_widget(threshold, color="#ffeb3b")
    pct = _pct_above(threshold)
    print(f"Threshold: {threshold:.0f}  |  {pct:.1f}% above")


_update_display(threshold)

info_label = img_plot.add_widget("label", x=10, y=490, text="", color="#ffeb3b", fontsize=11)


# ── event handlers ─────────────────────────────────────────────────────────────

def _on_wheel(event) -> None:
    delta = -2.0 * np.sign(event.dy) if event.dy != 0 else 0.0
    _update_display(threshold + delta)


def _on_bar_click(event) -> None:
    idx = event.bar_index
    if idx is None:
        return
    new_thresh = float(bin_edges[idx + 1])
    _update_display(new_thresh)


def _on_settled(event) -> None:
    x = int(np.clip(round(event.xdata), 0, 511))
    y = int(np.clip(round(event.ydata), 0, 511))
    intensity = float(image[y, x])
    info_label.set(text=f"px ({x}, {y}): {intensity:.0f}", x=10, y=490)


img_plot.add_event_handler(_on_wheel, "wheel")
img_plot.add_event_handler(_on_settled, "pointer_settled", ms=400, delta=4)
hist_plot.add_event_handler(_on_bar_click, "pointer_down")

fig.set_help(
    "Scroll over image: adjust threshold ±2\n"
    "Click histogram bar: jump to bin upper edge\n"
    "Dwell 400 ms over image: inspect pixel intensity"
)

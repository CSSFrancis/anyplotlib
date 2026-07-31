"""
HAADF STEM nanoparticle picker.
=================================

Synthetic HAADF-STEM image with 18 Gaussian nanoparticles on a Poisson
noise background.  Candidate peaks are detected automatically using a
7×7 local-maximum filter and marked with small grey circles.

**Interaction**

* **Dwell 300 ms** over a candidate — shows the sub-pixel centroid,
  peak intensity, and estimated FWHM in a floating label.
* **Double-click** — confirms the pick (green ring).
* **Shift+double-click** — marks the pick as uncertain (orange ring).
* **Delete / Backspace** — removes the confirmed pick nearest the
  cursor.
* **c** — clears all picks.
"""
import numpy as np
import anyplotlib as apl


# ── synthetic data ─────────────────────────────────────────────────────────────

def _make_stem_image(rng: np.random.Generator) -> np.ndarray:
    img = rng.poisson(lam=5, size=(512, 512)).astype(np.float32)
    for _ in range(18):
        cx, cy = rng.integers(30, 482, size=2)
        sigma = rng.uniform(4, 9)
        peak = rng.uniform(80, 200)
        r = int(np.ceil(3 * sigma))
        y0, y1 = max(0, cy - r), min(512, cy + r + 1)
        x0, x1 = max(0, cx - r), min(512, cx + r + 1)
        ys = np.arange(y0, y1)[:, None]
        xs = np.arange(x0, x1)[None, :]
        img[y0:y1, x0:x1] += peak * np.exp(
            -((xs - cx) ** 2 + (ys - cy) ** 2) / (2 * sigma ** 2)
        )
    return np.clip(img, 0, 255).astype(np.float32)


def _find_candidates(img: np.ndarray) -> list[tuple[int, int]]:
    """Local maxima via 7x7 sliding-window max filter (pure NumPy)."""
    from numpy.lib.stride_tricks import sliding_window_view
    pad = 3
    padded = np.pad(img, pad, mode="edge")
    windows = sliding_window_view(padded, (7, 7))
    local_max = windows.max(axis=(-2, -1))
    mask = (img == local_max) & (img > 20)
    ys, xs = np.where(mask)
    return list(zip(xs.tolist(), ys.tolist()))


def _parabolic_centroid(img: np.ndarray, r: int, c: int) -> tuple[float, float]:
    def _delta(left, center, right):
        denom = 2 * (2 * center - left - right)
        return 0.0 if abs(denom) < 1e-6 else (right - left) / denom

    dc = _delta(float(img[r, c - 1]), float(img[r, c]), float(img[r, c + 1]))
    dr = _delta(float(img[r - 1, c]), float(img[r, c]), float(img[r + 1, c]))
    return c + dc, r + dr


def _gaussian_fwhm(profile: np.ndarray) -> float:
    p = np.clip(profile.astype(float), 1e-6, None)
    peak_idx = int(np.argmax(p))
    if peak_idx == 0 or peak_idx >= len(p) - 1:
        return 2.0
    try:
        a, b, c_ = np.log(p[peak_idx - 1]), np.log(p[peak_idx]), np.log(p[peak_idx + 1])
        sigma = np.sqrt(-1.0 / (2 * (a + c_ - 2 * b)))
    except Exception:
        return 2.0
    return 2.355 * abs(sigma)


def _safe_remove(plot, marker_type: str, name: str) -> None:
    try:
        plot.remove_marker(marker_type, name)
    except KeyError:
        pass


# ── build data ─────────────────────────────────────────────────────────────────

rng = np.random.default_rng(42)
image = _make_stem_image(rng)
candidates = _find_candidates(image)

# ── figure ─────────────────────────────────────────────────────────────────────

fig, ax = apl.subplots(1, 1, figsize=(640, 640))
plot = ax.imshow(image, cmap="gray")

if candidates:
    cand_arr = np.array(candidates, dtype=float)
    plot.add_circles(cand_arr, name="candidates", radius=6,
                     facecolors="none", edgecolors="#555555")

info_label = plot.add_widget("label", x=10, y=10, text="", color="#00e5ff", fontsize=11)

picks: list[dict] = []


# ── helpers ────────────────────────────────────────────────────────────────────

def _redraw_picks() -> None:
    _safe_remove(plot, "circles", "picks_certain")
    _safe_remove(plot, "circles", "picks_uncertain")
    certain = [p for p in picks if not p["uncertain"]]
    uncertain = [p for p in picks if p["uncertain"]]
    if certain:
        arr = np.array([[p["cx"], p["cy"]] for p in certain])
        plot.add_circles(arr, name="picks_certain", radius=10,
                         facecolors="none", edgecolors="#00ff88")
    if uncertain:
        arr = np.array([[p["cx"], p["cy"]] for p in uncertain])
        plot.add_circles(arr, name="picks_uncertain", radius=10,
                         facecolors="none", edgecolors="#ff9100")


def _nearest_candidate(x: float, y: float, max_dist: float = 12.0):
    best, best_d = None, max_dist
    for cx, cy in candidates:
        d = float(np.hypot(cx - x, cy - y))
        if d < best_d:
            best, best_d = (cx, cy), d
    return best


def _nearest_pick_idx(x: float, y: float) -> int | None:
    if not picks:
        return None
    dists = [float(np.hypot(p["cx"] - x, p["cy"] - y)) for p in picks]
    return int(np.argmin(dists))


def _inspect(cx_f: float, cy_f: float) -> tuple[float, float, float, float]:
    """Return (sub_cx, sub_cy, intensity, fwhm) for the pixel at (cx_f, cy_f)."""
    r = int(np.clip(round(cy_f), 4, 507))
    c = int(np.clip(round(cx_f), 4, 507))
    sub_cx, sub_cy = _parabolic_centroid(image, r, c)
    intensity = float(image[r, c])
    row_profile = image[r, max(0, c - 4):min(512, c + 5)]
    col_profile = image[max(0, r - 4):min(512, r + 5), c]
    fwhm = (_gaussian_fwhm(row_profile) + _gaussian_fwhm(col_profile)) / 2
    return sub_cx, sub_cy, intensity, fwhm


# ── event handlers ─────────────────────────────────────────────────────────────

def _on_settled(event) -> None:
    if event.xdata is None or event.ydata is None:
        return
    hit = _nearest_candidate(event.xdata, event.ydata)
    if hit is None:
        info_label.set(text="")
        return
    hx, hy = hit
    sub_cx, sub_cy, intensity, fwhm = _inspect(hx, hy)
    info_label.set(
        text=f"centroid ({sub_cx:.1f}, {sub_cy:.1f})\npeak {intensity:.0f}\nFWHM {fwhm:.2f} px",
        x=hx + 12,
        y=hy - 30,
    )


def _on_double_click(event) -> None:
    if event.xdata is None or event.ydata is None:
        return
    hit = _nearest_candidate(event.xdata, event.ydata)
    if hit is None:
        return
    sub_cx, sub_cy, intensity, fwhm = _inspect(*hit)
    uncertain = "shift" in event.modifiers
    picks.append({"cx": sub_cx, "cy": sub_cy, "intensity": intensity,
                  "fwhm": fwhm, "uncertain": uncertain})
    _redraw_picks()
    tag = "uncertain" if uncertain else "certain"
    print(f"Pick #{len(picks)} [{tag}]: ({sub_cx:.1f}, {sub_cy:.1f})  "
          f"peak={intensity:.0f}  FWHM={fwhm:.2f} px")


def _on_key(event) -> None:
    if event.key in ("Delete", "Backspace"):
        x = event.xdata if event.xdata is not None else 256.0
        y = event.ydata if event.ydata is not None else 256.0
        idx = _nearest_pick_idx(x, y)
        if idx is not None:
            picks.pop(idx)
            _redraw_picks()
    elif event.key == "c":
        picks.clear()
        _redraw_picks()


plot.add_event_handler(_on_settled, "pointer_settled", ms=300, delta=6)
plot.add_event_handler(_on_double_click, "double_click")
plot.add_event_handler(_on_key, "key_down")

fig.set_help(
    "Dwell 300 ms: inspect peak\n"
    "Double-click: confirm pick (green)\n"
    "Shift+double-click: uncertain pick (orange)\n"
    "Delete / Backspace: remove nearest pick\n"
    "c: clear all picks"
)

fig  # interactive

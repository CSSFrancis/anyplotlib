"""
tests/test_benchmarks.py
========================

JS render-time benchmarks driven by headless Chromium (Playwright).

Each test opens the widget HTML in a real browser, drives N render cycles via
``window._aplModel`` mutations paced by ``requestAnimationFrame``, and reads
back the ``window._aplTiming[panel_id]`` dict that ``_recordFrame()`` in
``figure_esm.js`` maintains.

Workflow
--------
Generate / refresh baselines (first run or after intentional perf change)::

    uv run pytest tests/test_benchmarks.py --update-benchmarks -v

Normal CI run (fails on >50 % regression vs baseline)::

    uv run pytest tests/test_benchmarks.py -v

Include slow 4K²/8K² image scenarios::

    uv run pytest tests/test_benchmarks.py --run-slow -v

What is timed
-------------
``_recordFrame(p)`` is called at the *entry* of every draw function
(``draw2d`` / ``draw1d`` / ``draw3d`` / ``drawBar``) before the async
``createImageBitmap`` call is queued.  It timestamps when the CPU *starts*
a render, so successive timestamps measure the **inter-trigger interval** —
how quickly the main JS thread can process one data push and begin the next.

Each bench cycle slightly nudges ``display_min`` (2D / mesh) or ``view_x0``
(1D / bar) so the JS blit-cache is always invalidated and the full
decode → LUT → render path runs on every frame.

Interaction benchmarks fire real Playwright mouse events (mousemove / wheel)
rather than model mutations, giving more realistic timings for pan/zoom paths
at the cost of higher variance.

Regression threshold
--------------------
A test fails when ``mean_ms > baseline_mean_ms * 1.5`` (50 % slower).
A warning is printed when ``mean_ms > baseline_mean_ms * 1.25`` (25 % slower).
"""
from __future__ import annotations

import datetime
import json
import platform
import socket
import warnings
import pathlib

import numpy as np
import pytest

import anyplotlib as apl
from tests.conftest import _run_bench

# ── constants ────────────────────────────────────────────────────────────────
BASELINES_PATH = pathlib.Path(__file__).parent / "benchmarks" / "baselines.json"

# Regression thresholds (ratio relative to stored baseline mean_ms).
FAIL_RATIO = 2.00 # >100 % slower  → test failure
WARN_RATIO = 1.25   # >25 % slower  → warning only

# Grid padding added by gridDiv (mirrors figure_esm.js)
_GRID_PAD = 8
_PAD_L, _PAD_R, _PAD_T, _PAD_B = 58, 12, 12, 42


# ── helpers ───────────────────────────────────────────────────────────────────

def _load_baselines() -> dict:
    if BASELINES_PATH.exists():
        return json.loads(BASELINES_PATH.read_text())
    return {}


def _save_baselines(data: dict) -> None:
    BASELINES_PATH.parent.mkdir(parents=True, exist_ok=True)
    BASELINES_PATH.write_text(json.dumps(data, indent=2))


def _check_or_update(name: str, timing: dict, update: bool,
                     fail_ratio: float = FAIL_RATIO,
                     warn_ratio: float = WARN_RATIO) -> None:
    """Assert timing is within threshold of stored baseline, or write it.

    Parameters
    ----------
    name        : benchmark key stored in baselines.json
    timing      : dict returned by ``_run_bench`` or the interaction page.evaluate
    update      : when True, write the current result as the new baseline
    fail_ratio  : ratio of mean_ms/baseline_mean_ms above which the test fails.
                  Data-push benchmarks use FAIL_RATIO (1.5×); interaction
                  benchmarks use 2.5× because Playwright mouse-event timing
                  is more variable under OS scheduler load.
    warn_ratio  : ratio above which a warning (not failure) is emitted.
    """
    if timing is None:
        pytest.skip(f"[{name}] No timing data returned (panel not found?)")

    baselines = _load_baselines()

    if update:
        baselines[name] = {
            "mean_ms":    round(timing["mean_ms"],    2),
            "min_ms":     round(timing["min_ms"],     2),
            "max_ms":     round(timing["max_ms"],     2),
            "fps":        round(timing["fps"],        2),
            "n":          timing["count"],
            "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
        # Refresh meta host / timestamp whenever any baseline is updated.
        meta = baselines.setdefault("_meta", {})
        meta["updated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        meta["host"] = socket.gethostname()
        _save_baselines(baselines)
        pytest.skip(f"[{name}] Baseline updated: mean={timing['mean_ms']:.2f} ms "
                    f"fps={timing['fps']:.1f}")

    if name not in baselines:
        pytest.skip(
            f"[{name}] No baseline — run with --update-benchmarks to create one"
        )

    baseline = baselines[name]
    ratio = timing["mean_ms"] / baseline["mean_ms"]

    if ratio > fail_ratio:
        pytest.fail(
            f"[{name}] REGRESSION: mean {timing['mean_ms']:.2f} ms vs "
            f"baseline {baseline['mean_ms']:.2f} ms ({ratio:.2f}×)"
        )
    if ratio > warn_ratio:
        warnings.warn(
            f"[{name}] Perf degraded: mean {timing['mean_ms']:.2f} ms vs "
            f"baseline {baseline['mean_ms']:.2f} ms ({ratio:.2f}×)",
            stacklevel=2,
        )


# ── 2D imshow benchmarks ──────────────────────────────────────────────────────

# Sizes below 4096² run in the fast CI suite.
# 4096² and 8192² require --run-slow.
_IMSHOW_SIZES = [
    (64,   64,   False),
    (256,  256,  False),
    (512,  512,  False),
    (1024, 1024, False),
    (2048, 2048, False),
    (4096, 4096, True),   # slow
    (8192, 8192, True),   # slow
]


@pytest.mark.parametrize(
    "h,w,is_slow",
    _IMSHOW_SIZES,
    ids=[f"{h}x{w}" for h, w, _ in _IMSHOW_SIZES],
)
def test_bench_imshow(h, w, is_slow, bench_page, update_benchmarks, run_slow):
    """Render-time benchmark: imshow with {h}×{w} image data."""
    if is_slow and not run_slow:
        pytest.skip(f"Skipping {h}×{w} in fast CI — pass --run-slow to include")

    rng = np.random.default_rng(0)
    # Use a panel canvas that's large enough to always letterbox the image.
    canvas_px = min(max(h, 320), 640)
    fig, ax = apl.subplots(1, 1, figsize=(canvas_px, canvas_px))
    plot = ax.imshow(rng.uniform(size=(h, w)).astype(np.float32))
    panel_id = plot._id

    page = bench_page(fig)

    # For large images the rAF loop needs more time.
    timeout_ms = max(120_000, h * w // 500)

    timing = _run_bench(
        page, panel_id,
        perturb_field="display_min",
        perturb_delta=1e-4,
        n_warmup=3,
        n_samples=15,
        timeout=timeout_ms,
    )

    _check_or_update(f"js_imshow_{h}x{w}", timing, update_benchmarks)


# ── 1D plot benchmarks ────────────────────────────────────────────────────────

_PLOT1D_SIZES = [100, 1_000, 10_000, 100_000]


@pytest.mark.parametrize("n_pts", _PLOT1D_SIZES, ids=[str(n) for n in _PLOT1D_SIZES])
def test_bench_plot1d(n_pts, bench_page, update_benchmarks):
    """Render-time benchmark: plot1d with {n_pts} points."""
    rng = np.random.default_rng(1)
    fig, ax = apl.subplots(1, 1, figsize=(640, 320))
    plot = ax.plot(np.cumsum(rng.standard_normal(n_pts)))
    panel_id = plot._id

    page = bench_page(fig)

    timing = _run_bench(
        page, panel_id,
        perturb_field="view_x0",
        perturb_delta=1e-5,
        n_warmup=3,
        n_samples=15,
    )

    _check_or_update(f"js_plot1d_{n_pts}pts", timing, update_benchmarks)


# ── pcolormesh benchmarks ─────────────────────────────────────────────────────

_MESH_SIZES = [32, 128, 256]


@pytest.mark.parametrize("n", _MESH_SIZES, ids=[f"{n}x{n}" for n in _MESH_SIZES])
def test_bench_pcolormesh(n, bench_page, update_benchmarks):
    """Render-time benchmark: pcolormesh with {n}×{n} grid."""
    rng = np.random.default_rng(2)
    xe = np.linspace(0.0, 1.0, n + 1)
    ye = np.linspace(0.0, 1.0, n + 1)
    Z  = rng.uniform(size=(n, n)).astype(np.float32)

    fig, ax = apl.subplots(1, 1, figsize=(480, 480))
    plot = ax.pcolormesh(Z, x_edges=xe, y_edges=ye)
    panel_id = plot._id

    page = bench_page(fig)

    timing = _run_bench(
        page, panel_id,
        perturb_field="display_min",
        perturb_delta=1e-4,
        n_warmup=3,
        n_samples=15,
    )

    _check_or_update(f"js_pcolormesh_{n}x{n}", timing, update_benchmarks)


# ── 3D surface benchmark ──────────────────────────────────────────────────────

def test_bench_plot3d(bench_page, update_benchmarks):
    """Render-time benchmark: 3D surface (rotation interaction path)."""
    x = np.linspace(-2.0, 2.0, 48)
    y = np.linspace(-2.0, 2.0, 48)
    X, Y = np.meshgrid(x, y)
    Z = np.sin(np.sqrt(X**2 + Y**2))

    fig, ax = apl.subplots(1, 1, figsize=(480, 480))
    plot = ax.plot_surface(X, Y, Z, colormap="viridis")
    panel_id = plot._id

    page = bench_page(fig)

    # 3D state uses azimuth / elevation rather than display_min.
    timing = _run_bench(
        page, panel_id,
        perturb_field="azimuth",
        perturb_delta=0.5,
        n_warmup=3,
        n_samples=15,
    )

    _check_or_update("js_plot3d_48x48", timing, update_benchmarks)


# ── bar chart benchmark ───────────────────────────────────────────────────────

@pytest.mark.parametrize("n_bars", [10, 100], ids=["10bars", "100bars"])
def test_bench_bar(n_bars, bench_page, update_benchmarks):
    """Render-time benchmark: bar chart with {n_bars} bars."""
    rng = np.random.default_rng(3)
    fig, ax = apl.subplots(1, 1, figsize=(640, 320))
    plot = ax.bar(rng.uniform(size=n_bars))
    panel_id = plot._id

    page = bench_page(fig)

    timing = _run_bench(
        page, panel_id,
        perturb_field="data_min",
        perturb_delta=1e-4,
        n_warmup=3,
        n_samples=15,
    )

    _check_or_update(f"js_bar_{n_bars}bars", timing, update_benchmarks)


# ── interaction: 2D pan ───────────────────────────────────────────────────────

def test_bench_interaction_2d_pan(bench_page, update_benchmarks):
    """Interaction benchmark: 2D pan drag (20 mousemove events on 512² image)."""
    rng = np.random.default_rng(4)
    fig, ax = apl.subplots(1, 1, figsize=(512 + _PAD_L + _PAD_R,
                                          512 + _PAD_T + _PAD_B))
    plot = ax.imshow(rng.uniform(size=(512, 512)).astype(np.float32))
    panel_id = plot._id

    page = bench_page(fig)

    # Canvas-space origin of the image area (grid padding + axis padding).
    img_x0 = _GRID_PAD + _PAD_L
    img_y0 = _GRID_PAD + _PAD_T

    # Drag from centre of the image area across ~1/4 of its width.
    cx = img_x0 + 256
    cy = img_y0 + 256

    # Warm up: one full drag pass discarded.
    page.mouse.move(cx, cy)
    page.mouse.down()
    page.mouse.move(cx - 64, cy, steps=5)
    page.mouse.move(cx,      cy, steps=5)
    page.mouse.up()

    # Reset timing buffer before the measured run.
    page.evaluate(
        f"() => {{ if (window._aplTiming) delete window._aplTiming['{panel_id}']; }}"
    )

    # Measured run: 20 individual mousemove steps (each triggers draw2d).
    page.mouse.move(cx, cy)
    page.mouse.down()
    page.mouse.move(cx - 128, cy, steps=20)
    page.mouse.up()

    # Allow the last few async ImageBitmap creations to settle.
    page.evaluate(
        "() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))"
    )

    timing = page.evaluate(f"() => window._aplTiming && window._aplTiming['{panel_id}']")
    _check_or_update("js_interaction_2d_pan", timing, update_benchmarks,
                     fail_ratio=2.5, warn_ratio=1.75)

def test_bench_interaction_2d_zoom(bench_page, update_benchmarks):
    """Interaction benchmark: 2D wheel zoom (20 wheel events on 512² image)."""
    rng = np.random.default_rng(5)
    fig, ax = apl.subplots(1, 1, figsize=(512 + _PAD_L + _PAD_R,
                                          512 + _PAD_T + _PAD_B))
    plot = ax.imshow(rng.uniform(size=(512, 512)).astype(np.float32))
    panel_id = plot._id

    page = bench_page(fig)

    cx = _GRID_PAD + _PAD_L + 256
    cy = _GRID_PAD + _PAD_T + 256

    # Warm up.
    for _ in range(3):
        page.mouse.wheel(0, 120)
    page.evaluate(
        f"() => {{ if (window._aplTiming) delete window._aplTiming['{panel_id}']; }}"
    )

    # Measured: 20 zoom-in wheel ticks.
    for _ in range(20):
        page.mouse.move(cx, cy)
        page.mouse.wheel(0, -120)

    page.evaluate(
        "() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))"
    )

    timing = page.evaluate(f"() => window._aplTiming && window._aplTiming['{panel_id}']")
    _check_or_update("js_interaction_2d_zoom", timing, update_benchmarks,
                     fail_ratio=2.5, warn_ratio=1.75)

def test_bench_interaction_1d_pan(bench_page, update_benchmarks):
    """Interaction benchmark: 1D pan drag (20 mousemove events, 10K points)."""
    rng = np.random.default_rng(6)
    pw, ph = 640, 320
    fig, ax = apl.subplots(1, 1, figsize=(pw, ph))
    plot = ax.plot(np.cumsum(rng.standard_normal(10_000)))
    panel_id = plot._id

    page = bench_page(fig)

    # Plot rect x-centre in page space.
    cx = _GRID_PAD + _PAD_L + (pw - _PAD_L - _PAD_R) // 2
    cy = _GRID_PAD + _PAD_T + (ph - _PAD_T - _PAD_B) // 2

    # Warm up.
    page.mouse.move(cx, cy)
    page.mouse.down()
    page.mouse.move(cx - 60, cy, steps=5)
    page.mouse.move(cx,      cy, steps=5)
    page.mouse.up()
    page.evaluate(
        f"() => {{ if (window._aplTiming) delete window._aplTiming['{panel_id}']; }}"
    )

    # Measured: 20 steps.
    page.mouse.move(cx, cy)
    page.mouse.down()
    page.mouse.move(cx - 120, cy, steps=20)
    page.mouse.up()

    page.evaluate(
        "() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))"
    )

    timing = page.evaluate(f"() => window._aplTiming && window._aplTiming['{panel_id}']")
    _check_or_update("js_interaction_1d_pan", timing, update_benchmarks,
                     fail_ratio=2.5, warn_ratio=1.75)



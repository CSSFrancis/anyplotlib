"""
tests/test_benchmarks_py.py
============================

Pure-Python serialisation benchmarks — no browser, no Playwright required.

Measures each stage of the Python → JS data pipeline independently so
regressions in serialisation code are caught separately from JS render
regressions.

Pipeline stages timed
---------------------
1. ``_normalize_image(data)``       — NumPy cast + min/max + scale + uint8
2. ``Plot2D._encode_bytes(img_u8)`` — base64.b64encode
3. ``json.dumps(plot.to_state_dict())`` — full end-to-end (2D and 1D)
4. ``plot.update(data)``            — complete Python-side round-trip

Workflow
--------
Generate / refresh baselines::

    uv run pytest tests/test_benchmarks_py.py --update-benchmarks -v

Normal CI run::

    uv run pytest tests/test_benchmarks_py.py -v

Include slow 4096²/8192² scenarios::

    uv run pytest tests/test_benchmarks_py.py --run-slow -v

Regression threshold
--------------------
Fails when ``min_ms > baseline_min_ms * 1.3`` (30 % slower than best
recorded).  Pure-Python is deterministic enough for this tighter threshold
compared with the JS/browser suite (50 %).
"""
from __future__ import annotations

import datetime
import json
import socket
import timeit
import warnings
import pathlib

import numpy as np
import pytest

import anyplotlib as apl
from anyplotlib.figure_plots import _normalize_image, Plot2D

BASELINES_PATH = pathlib.Path(__file__).parent / "benchmarks" / "baselines.json"

FAIL_RATIO = 1.30
WARN_RATIO = 1.15

# timeit settings: REPEATS independent runs of NUMBER executions each.
# We take min() over REPEATS to remove OS scheduling jitter.
REPEATS = 5
NUMBER  = 3


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _load_baselines() -> dict:
    if BASELINES_PATH.exists():
        return json.loads(BASELINES_PATH.read_text())
    return {}


def _save_baselines(data: dict) -> None:
    BASELINES_PATH.parent.mkdir(parents=True, exist_ok=True)
    BASELINES_PATH.write_text(json.dumps(data, indent=2))


def _timeit_ms(stmt, *, number: int = NUMBER, repeats: int = REPEATS) -> dict:
    """Time *stmt* (zero-arg callable) and return min/mean/max stats in ms."""
    raw = timeit.repeat(stmt=stmt, number=number, repeat=repeats, globals=None)
    per_call = [t / number * 1000 for t in raw]
    return {
        "min_ms":  round(min(per_call),  3),
        "mean_ms": round(sum(per_call) / len(per_call), 3),
        "max_ms":  round(max(per_call),  3),
        "n":       repeats * number,
    }


def _check_or_update(name: str, timing: dict, update: bool) -> None:
    """Assert *timing* is within threshold of the stored baseline, or write it."""
    baselines = _load_baselines()

    if update:
        baselines[name] = {
            **timing,
            "updated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
        meta = baselines.setdefault("_meta", {})
        meta["updated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        meta["host"]       = socket.gethostname()
        _save_baselines(baselines)
        pytest.skip(f"[{name}] Baseline updated: min={timing['min_ms']:.3f} ms")

    if name not in baselines:
        pytest.skip(
            f"[{name}] No baseline — run with --update-benchmarks to create one"
        )

    baseline = baselines[name]
    ratio    = timing["min_ms"] / baseline["min_ms"]

    if ratio > FAIL_RATIO:
        pytest.fail(
            f"[{name}] REGRESSION: min {timing['min_ms']:.3f} ms vs "
            f"baseline {baseline['min_ms']:.3f} ms ({ratio:.2f}×)"
        )
    if ratio > WARN_RATIO:
        warnings.warn(
            f"[{name}] Perf degraded: min {timing['min_ms']:.3f} ms vs "
            f"baseline {baseline['min_ms']:.3f} ms ({ratio:.2f}×)",
            stacklevel=2,
        )


# ---------------------------------------------------------------------------
# Parametrisation tables
# ---------------------------------------------------------------------------

_IMSHOW_SIZES = [
    (64,   64,   False),
    (256,  256,  False),
    (512,  512,  False),
    (1024, 1024, False),
    (2048, 2048, False),
    (4096, 4096, True),   # slow — requires --run-slow
    (8192, 8192, True),   # slow — requires --run-slow
]

_PLOT1D_SIZES = [100, 1_000, 10_000, 100_000]


# ---------------------------------------------------------------------------
# Stage 1: _normalize_image
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "h,w,is_slow", _IMSHOW_SIZES,
    ids=[f"{h}x{w}" for h, w, _ in _IMSHOW_SIZES],
)
def test_bench_py_normalize(h, w, is_slow, update_benchmarks, run_slow):
    """Python: ``_normalize_image`` for a ``{h}×{w}`` float32 array."""
    if is_slow and not run_slow:
        pytest.skip(f"Skipping {h}x{w} — pass --run-slow to include")

    rng  = np.random.default_rng(0)
    data = rng.uniform(size=(h, w)).astype(np.float32)

    timing = _timeit_ms(stmt=lambda: _normalize_image(data))
    _check_or_update(f"py_normalize_{h}x{w}", timing, update_benchmarks)


# ---------------------------------------------------------------------------
# Stage 2: _encode_bytes (base64)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "h,w,is_slow", _IMSHOW_SIZES,
    ids=[f"{h}x{w}" for h, w, _ in _IMSHOW_SIZES],
)
def test_bench_py_encode(h, w, is_slow, update_benchmarks, run_slow):
    """Python: ``_encode_bytes`` (base64) for a ``{h}×{w}`` uint8 array."""
    if is_slow and not run_slow:
        pytest.skip(f"Skipping {h}x{w} — pass --run-slow to include")

    rng    = np.random.default_rng(1)
    img_u8, _, _ = _normalize_image(rng.uniform(size=(h, w)).astype(np.float32))

    timing = _timeit_ms(stmt=lambda: Plot2D._encode_bytes(img_u8))
    _check_or_update(f"py_encode_{h}x{w}", timing, update_benchmarks)


# ---------------------------------------------------------------------------
# Stage 3: json.dumps(to_state_dict()) — 2D
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "h,w,is_slow", _IMSHOW_SIZES,
    ids=[f"{h}x{w}" for h, w, _ in _IMSHOW_SIZES],
)
def test_bench_py_serialize_2d(h, w, is_slow, update_benchmarks, run_slow):
    """Python: ``json.dumps(plot.to_state_dict())`` for a ``{h}×{w}`` imshow."""
    if is_slow and not run_slow:
        pytest.skip(f"Skipping {h}x{w} — pass --run-slow to include")

    rng = np.random.default_rng(2)
    fig, ax = apl.subplots(1, 1, figsize=(min(h, 640), min(w, 640)))
    plot    = ax.imshow(rng.uniform(size=(h, w)).astype(np.float32))

    timing = _timeit_ms(stmt=lambda: json.dumps(plot.to_state_dict()))
    _check_or_update(f"py_serialize_2d_{h}x{w}", timing, update_benchmarks)


# ---------------------------------------------------------------------------
# Stage 3 (1D): json.dumps(to_state_dict())
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "n_pts", _PLOT1D_SIZES,
    ids=[str(n) for n in _PLOT1D_SIZES],
)
def test_bench_py_serialize_1d(n_pts, update_benchmarks):
    """Python: ``json.dumps(plot.to_state_dict())`` for a ``{n_pts}``-point 1D plot."""
    rng = np.random.default_rng(3)
    fig, ax = apl.subplots(1, 1, figsize=(640, 320))
    plot    = ax.plot(np.cumsum(rng.standard_normal(n_pts)))

    timing = _timeit_ms(stmt=lambda: json.dumps(plot.to_state_dict()))
    _check_or_update(f"py_serialize_1d_{n_pts}pts", timing, update_benchmarks)


# ---------------------------------------------------------------------------
# Full plot.update() round-trip (normalize + encode + build_lut + push)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "h,w,is_slow", _IMSHOW_SIZES,
    ids=[f"{h}x{w}" for h, w, _ in _IMSHOW_SIZES],
)
def test_bench_py_update_2d(h, w, is_slow, update_benchmarks, run_slow):
    """Python: full ``plot.update(data)`` round-trip for a ``{h}×{w}`` image.

    Covers the complete Python-side cost of a live data refresh:
    ``_normalize_image`` + ``_encode_bytes`` + ``_build_colormap_lut``
    + state-dict assembly + ``json.dumps`` (via ``Figure._push``).
    """
    if is_slow and not run_slow:
        pytest.skip(f"Skipping {h}x{w} — pass --run-slow to include")

    rng = np.random.default_rng(4)
    fig, ax = apl.subplots(1, 1, figsize=(min(h, 640), min(w, 640)))
    plot    = ax.imshow(rng.uniform(size=(h, w)).astype(np.float32))

    # Pre-generate frames so random array creation is excluded from timing.
    frames = [rng.uniform(size=(h, w)).astype(np.float32) for _ in range(NUMBER)]
    idx    = [0]

    def _one_update():
        plot.update(frames[idx[0] % len(frames)])
        idx[0] += 1

    timing = _timeit_ms(stmt=_one_update)
    _check_or_update(f"py_update_2d_{h}x{w}", timing, update_benchmarks)



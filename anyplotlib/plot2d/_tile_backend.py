"""Pluggable tile backend for large-image display.

A ``TileBackend`` OWNS the source data (an ndarray, a lazy/dask array, a GPU-resident
tensor, a remote store …) and answers two things:

  * the LOGICAL geometry of the full image — ``full_shape`` (H, W), ``dtype``,
    ``origin``, and a data-space ``extent`` — so anyplotlib can set up the axes/aspect
    WITHOUT ever holding the whole array;
  * ``sample(x0, x1, y0, y1, out_w, out_h, method)`` — downsample (or upsample) the
    logical region ``[y0:y1, x0:x1]`` to an ``(out_h, out_w)`` tile.

anyplotlib owns the zoom/pan → re-tile lifecycle and calls ``sample`` for the visible
region at the panel's resolution. Swap the backend to change WHERE/HOW tiles are
computed (GPU+torch for a fast mean, dask/zarr for out-of-core, an app's chunk cache)
without touching that lifecycle.

The default :class:`NumpyTileBackend` covers an in-memory ndarray. anyplotlib keeps no
hard dependency on torch/dask — a GPU/lazy backend is a separate class implementing the
same ``Protocol`` that the consumer (or an optional extra) provides.
"""
from __future__ import annotations

import math
from typing import Protocol, runtime_checkable

import numpy as np


@runtime_checkable
class TileBackend(Protocol):
    """Source of tiled large-image data. Owns the array; anyplotlib never holds it."""

    @property
    def full_shape(self) -> "tuple[int, int]":
        """(H, W) of the full LOGICAL image in pixels."""
        ...

    @property
    def dtype(self) -> np.dtype:
        """Source element dtype (anyplotlib quantises tiles to uint8 for display)."""
        ...

    @property
    def origin(self) -> str:
        """``"upper"`` (row 0 at top) or ``"lower"`` (row 0 at bottom)."""
        ...

    def extent(self) -> "tuple[float, float, float, float] | None":
        """Data-space ``(x0, x1, y0, y1)`` the image spans, or ``None`` for pixel
        coordinates (``(0, W, 0, H)``)."""
        ...

    def sample(self, x0: int, x1: int, y0: int, y1: int,
               out_w: int, out_h: int, method: str = "mean") -> np.ndarray:
        """Return the logical region ``[y0:y1, x0:x1]`` resampled to ``(out_h,
        out_w)`` via ``method`` (``"mean"|"subsample"|"max"``) as a 2-D ndarray."""
        ...


# ── Integer-friendly area reductions (shared by the numpy backend) ─────────────

def _acc_dtype(dtype: np.dtype, n: int) -> np.dtype:
    """Accumulator dtype for a box sum of ``n`` elements of ``dtype``.

    Integers get the narrowest same-SIGNEDNESS integer that cannot wrap over ``n``
    terms. A blanket ``uint32`` is wrong twice over: it reads a negative ``int16``
    as ~4.3e9, and it silently overflows on anything wider than 16 bits. Floats
    accumulate at their own width but never below float32 — the result is quantised
    to 8-bit tile bytes, so a float64 accumulator over a float32 frame buys
    precision the output cannot express and pays a cast of the whole region for it.

    The float32 sum does bound what a float32 frame may hold: ``n`` terms overflow
    to inf past ``float32.max / n`` (~5e36 for the default 64-pixel block). A frame
    that large cannot survive the 8-bit quantisation downstream either, and float64
    input — where that dynamic range actually turns up — keeps its own width."""
    if dtype.kind in "bui":
        hi = 1 if dtype.kind == "b" else int(np.iinfo(dtype).max)
        lo = -int(np.iinfo(dtype).min) if dtype.kind == "i" else 0
        need = int(n) * max(hi, lo)
        for cand in (np.int32, np.int64) if dtype.kind == "i" else (np.uint32, np.uint64):
            if need <= np.iinfo(cand).max:
                return np.dtype(cand)
        return np.dtype(np.float64)   # absurdly large block; float64 still beats wrapping
    return np.promote_types(dtype, np.float32)


def _box_reduce(region: np.ndarray, out_h: int, out_w: int, op: str) -> np.ndarray:
    """Reduce ``region`` (2-D) to ``(out_h, out_w)`` by a block ``op`` ("mean"|"max").

    Fast path (region divisible by the stride): TWO vectorised reshape-reduces in an
    accumulator sized by :func:`_acc_dtype` (no full float cast of the source — the
    cast of a 16 MP uint16 frame alone is ~34 ms). Collapsing whole ROWS first and
    then the contiguous column blocks walks memory in order on both passes; the one
    ``sum(axis=(1, 3))`` it replaces reduced a strided axis and a contiguous one
    together, which defeats numpy's fast inner loops and cost ~4x as long on an
    8192² float32 frame. Ragged path (non-divisible): a strided-accumulate box filter
    with a per-cell count, so the last partial block is reduced over only its valid
    pixels. Either way the grid is nearest-resized to the exact (out_h, out_w) the
    caller asked for."""
    h, w = region.shape
    sy = max(1, h // out_h)
    sx = max(1, w // out_w)

    if h % sy == 0 and w % sx == 0:
        gh, gw = h // sy, w // sx
        if op == "max":
            return _nearest_resize(region.reshape(gh, sy, gw, sx).max(axis=(1, 3)),
                                   out_h, out_w)
        acc = _acc_dtype(region.dtype, sy * sx)
        rows = region.reshape(gh, sy, w).sum(axis=1, dtype=acc)
        out = (rows.reshape(gh, gw, sx).sum(axis=2, dtype=acc)
               .astype(np.float32) / (sy * sx))
        return _nearest_resize(out, out_h, out_w)

    # Ragged → strided accumulate with a per-cell count (handles the partial block).
    gh = math.ceil(h / sy)
    gw = math.ceil(w / sx)
    if op == "max":
        acc = None
        for dy in range(sy):
            for dx in range(sx):
                sub = region[dy::sy, dx::sx]
                sh, sw = sub.shape
                if acc is None:
                    acc = np.zeros((gh, gw), region.dtype)
                    acc[:sh, :sw] = sub
                else:
                    np.maximum(acc[:sh, :sw], sub, out=acc[:sh, :sw])
        out = acc
    else:
        acc = np.zeros((gh, gw), _acc_dtype(region.dtype, sy * sx))
        cnt = np.zeros((gh, gw), np.uint32)
        for dy in range(sy):
            for dx in range(sx):
                sub = region[dy::sy, dx::sx]
                sh, sw = sub.shape
                acc[:sh, :sw] += sub
                cnt[:sh, :sw] += 1
        out = acc.astype(np.float32) / cnt
    return _nearest_resize(out, out_h, out_w)


def _nearest_resize(a: np.ndarray, out_h: int, out_w: int) -> np.ndarray:
    """Nearest-neighbour resize a 2-D array to ``(out_h, out_w)`` (up or down)."""
    h, w = a.shape
    if (h, w) == (out_h, out_w):
        return a
    yi = (np.arange(out_h) * h // max(1, out_h)).clip(0, h - 1)
    xi = (np.arange(out_w) * w // max(1, out_w)).clip(0, w - 1)
    return a[yi][:, xi]


class NumpyTileBackend:
    """Default :class:`TileBackend` over an in-memory ndarray."""

    def __init__(self, array: np.ndarray, extent=None, origin: str = "upper") -> None:
        a = np.asarray(array)
        if a.ndim != 2:
            raise ValueError(f"NumpyTileBackend needs a 2-D array, got {a.shape}")
        self._a = a
        self._extent = tuple(float(v) for v in extent) if extent is not None else None
        self._origin = origin

    # The tiling lifecycle can swap the frame in place (e.g. a movie navigator) so a
    # zoom re-tiles from the current frame without rebuilding the plot.
    def set_array(self, array: np.ndarray) -> None:
        a = np.asarray(array)
        if a.ndim != 2:
            raise ValueError(f"NumpyTileBackend needs a 2-D array, got {a.shape}")
        self._a = a

    @property
    def full_shape(self):
        return self._a.shape

    @property
    def dtype(self):
        return self._a.dtype

    @property
    def origin(self):
        return self._origin

    def extent(self):
        return self._extent

    def sample(self, x0, x1, y0, y1, out_w, out_h, method="mean"):
        h, w = self._a.shape
        x0 = int(max(0, min(w, x0))); x1 = int(max(x0 + 1, min(w, x1)))
        y0 = int(max(0, min(h, y0))); y1 = int(max(y0 + 1, min(h, y1)))
        out_w = int(max(1, out_w)); out_h = int(max(1, out_h))
        region = self._a[y0:y1, x0:x1]
        if method == "subsample":
            sy = max(1, (y1 - y0) // out_h)
            sx = max(1, (x1 - x0) // out_w)
            return _nearest_resize(region[::sy, ::sx], out_h, out_w)
        if method == "max":
            return _box_reduce(region, out_h, out_w, "max")
        # "mean" (default)
        return _box_reduce(region, out_h, out_w, "mean")


def as_tile_backend(source, *, extent=None, origin="upper") -> TileBackend:
    """Coerce ``source`` to a TileBackend: pass a backend through; wrap an ndarray in
    a :class:`NumpyTileBackend`."""
    if isinstance(source, TileBackend) and not isinstance(source, np.ndarray):
        return source
    return NumpyTileBackend(np.asarray(source), extent=extent, origin=origin)

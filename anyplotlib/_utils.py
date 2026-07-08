"""
_utils.py
=========
Shared low-level utilities used across plot subpackages.
"""

from __future__ import annotations

import functools

import numpy as np

_LINESTYLE_ALIASES: dict[str, str] = {
    "-":         "solid",
    "--":        "dashed",
    ":":         "dotted",
    "-.":        "dashdot",
    "solid":     "solid",
    "dashed":    "dashed",
    "dotted":    "dotted",
    "dashdot":   "dashdot",
    "step-mid":  "step-mid",
    "steps-mid": "step-mid",
}


def _arr_to_b64(arr: np.ndarray, dtype) -> str:
    """Encode a NumPy array as base-64 (little-endian raw bytes).

    Uses little-endian byte order so the result is compatible with
    JavaScript's ``Float64Array`` / ``Float32Array`` / ``Int32Array``
    on all modern platforms (x86, ARM).
    """
    import base64
    le_dtype = np.dtype(dtype).newbyteorder("<")
    return base64.b64encode(np.asarray(arr).astype(le_dtype).tobytes()).decode("ascii")


def _norm_linestyle(ls: str) -> str:
    """Normalise a linestyle name or shorthand to its canonical form.

    Accepted values
    ---------------
    ``"solid"`` / ``"-"``,  ``"dashed"`` / ``"--"``,
    ``"dotted"`` / ``":"``,  ``"dashdot"`` / ``"-."``.

    Raises
    ------
    ValueError
        If *ls* is not a recognised name or shorthand.
    """
    canonical = _LINESTYLE_ALIASES.get(ls)
    if canonical is None:
        raise ValueError(
            f"Unknown linestyle {ls!r}. Expected one of: "
            "'solid', 'dashed', 'dotted', 'dashdot', 'step-mid' (alias: 'steps-mid') "
            "or shorthands '-', '--', ':', '-.'."
        )
    return canonical


def _to_rgba_u8(data: np.ndarray) -> np.ndarray:
    """Convert an (H, W, 3|4) colour array to uint8 RGBA.

    Floats are interpreted as 0–1 (scaled ×255) when the max is ≤ 1,
    otherwise as 0–255 and clipped.  A missing alpha channel becomes 255.
    """
    data = np.asarray(data)
    if data.ndim != 3 or data.shape[2] not in (3, 4):
        raise ValueError(f"expected (H, W, 3|4) colour array, got {data.shape}")
    if data.dtype != np.uint8:
        arr = data.astype(np.float64)
        if arr.max() <= 1.0:
            arr = arr * 255.0
        data = np.clip(arr, 0, 255).astype(np.uint8)
    if data.shape[2] == 3:
        rgba = np.empty((*data.shape[:2], 4), dtype=np.uint8)
        rgba[..., :3] = data
        rgba[..., 3] = 255
        return rgba
    return np.ascontiguousarray(data)


def _normalize_image(data: np.ndarray, clim: "tuple | None" = None):
    """Normalise data to uint8, returning (img_u8, vmin, vmax) where vmin/vmax are
    the QUANTISATION endpoints the 8-bit codes span (the caller stores them as
    raw_min/raw_max so the renderer can reconstruct each code's value).

    When ``clim=(lo, hi)`` is given, quantise over THAT range instead of the raw
    data min/max, clipping outliers to 0/255. This is what makes a single hot pixel
    (or the saturating zero-order beam) NOT crush the real signal: without it the
    256 codes are stretched across the full data range, so a 60000-count hot pixel
    over a 0-4000 signal leaves the signal only ~12 distinct codes (≈3.5-bit) before
    it ever reaches the display window; clipping to the robust display range instead
    gives the signal the full 256 codes and just saturates the outlier. When no
    clim is given the behaviour is unchanged (quantise over raw min/max).

    Uses float32 for the rescale when the data range is small enough that float32's
    ~7 significant digits don't lose low bits (the common case: uint8/uint16 movie
    frames), else float64. float32 halves the memory bandwidth of the subtract/
    divide/multiply passes (~60ms → ~27ms on a 2048² frame — this runs every movie
    frame) with a byte-identical result. vmin/vmax are always returned as full-
    precision Python floats."""
    if clim is not None:
        vmin, vmax = float(clim[0]), float(clim[1])
    else:
        vmin = float(np.nanmin(data))
        vmax = float(np.nanmax(data))
    if vmax <= vmin:
        return np.zeros(data.shape, dtype=np.uint8), vmin, vmax
    # float32 is safe when |values| and the span are within its ~1.6e7 exact-integer
    # range with headroom; a huge-magnitude float source keeps float64 to avoid
    # banding. (subtract of two near-equal large float32s loses precision.)
    span = vmax - vmin
    use32 = (max(abs(vmin), abs(vmax)) < 1e6) and (span > 1e-6)
    dt = np.float32 if use32 else np.float64
    img = data.astype(dt, copy=False)
    buf = np.empty_like(img)
    np.subtract(img, dt(vmin), out=buf)
    np.divide(buf, dt(span), out=buf)
    np.multiply(buf, dt(255.0), out=buf)
    # Clip into [0, 255] BEFORE the uint8 cast so out-of-clim values saturate
    # instead of wrapping (a hot pixel above vmax would otherwise overflow uint8).
    np.clip(buf, 0.0, 255.0, out=buf)
    return buf.astype(np.uint8), vmin, vmax


# Mapping from common matplotlib colormap names to their nearest colorcet
# equivalents so callers can keep using familiar names without any matplotlib
# dependency.
_CMAP_ALIASES: dict[str, str] = {
    "viridis":       "bmy",       # blue→magenta→yellow, perceptually uniform
    "plasma":        "fire",      # warm sequential (dark→bright)
    "inferno":       "kb",        # dark→blue→white
    "magma":         "kbc",       # dark→blue→cyan sequential
    "cividis":       "bgy",        # accessible, blue→green→yellow sequential
    "hot":           "fire",
    "afmhot":        "fire",
    "jet":           "rainbow4",
    "hsv":           "rainbow4",
    "nipy_spectral": "rainbow4",
    "RdBu":          "coolwarm",
    "bwr":           "cwr",       # blue→white→red diverging
    "seismic":       "coolwarm",
}


@functools.lru_cache(maxsize=64)
def _build_colormap_lut(name: str) -> list:
    """Return a 256-entry ``[[r, g, b], ...]`` LUT for the named colormap.

    CACHED (lru_cache) — it's a pure function of ``name`` but costs ~100 ms
    (colorcet lookup + 256 hex parses), and it was being rebuilt on EVERY frame of
    a movie scrub even though the colormap doesn't change. The returned list is
    treated as read-only by callers (they JSON-serialise it); do NOT mutate it.

    Priority order:

    1. **colorcet** — preferred; common matplotlib names are remapped via
       :data:`_CMAP_ALIASES` so callers can use ``"viridis"`` etc.
    2. **matplotlib** — fallback when colorcet is not installed (e.g. in
       Pyodide before micropip finishes, or in minimal test environments).
    3. **Built-in gray ramp** — final fallback for unknown names.
    """
    # ── 1. Try colorcet ───────────────────────────────────────────────────
    try:
        import colorcet as cc
        resolved = _CMAP_ALIASES.get(name, name)
        palette  = cc.palette.get(resolved)
        if palette is not None:
            n   = len(palette)
            lut: list = []
            for i in range(256):
                h = palette[int(round(i * (n - 1) / 255))].lstrip("#")
                lut.append([int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)])
            return lut
    except Exception:
        pass

    # ── 2. Try matplotlib ─────────────────────────────────────────────────
    try:
        import matplotlib
        import numpy as _np
        cmap = matplotlib.colormaps[name]
        rgba = cmap(_np.linspace(0, 1, 256))
        return [[int(r * 255), int(g * 255), int(b * 255)]
                for r, g, b, _ in rgba]
    except Exception:
        pass

    # ── 3. Gray ramp fallback ─────────────────────────────────────────────
    return [[v, v, v] for v in range(256)]


def _resample_mesh(data: np.ndarray, x_edges, y_edges) -> np.ndarray:
    """Resample a mesh to a regular pixel grid via nearest-neighbour lookup.

    For uniform edges this is an identity operation.  For non-uniform edges
    (e.g. log-spaced) it maps each uniform output pixel to the nearest input
    cell, producing a visually correct linear-axis image.

    Parameters
    ----------
    data    : ndarray, shape (M, N) — one value per mesh cell.
    x_edges : array-like, length N+1 — column edge coordinates.
    y_edges : array-like, length M+1 — row edge coordinates.

    Returns
    -------
    ndarray, shape (M, N)
    """
    rows, cols = data.shape
    x_edges = np.asarray(x_edges, dtype=float)
    y_edges = np.asarray(y_edges, dtype=float)

    # Cell centres
    x_c = (x_edges[:-1] + x_edges[1:]) / 2.0
    y_c = (y_edges[:-1] + y_edges[1:]) / 2.0

    # Uniform sample points (same count as original cells)
    x_samp = np.linspace(x_c[0], x_c[-1], cols)
    y_samp = np.linspace(y_c[0], y_c[-1], rows)

    # Nearest-neighbour cell lookup via edge-sorted searchsorted
    xi = np.searchsorted(x_edges, x_samp) - 1
    xi = np.clip(xi, 0, cols - 1)
    yi = np.searchsorted(y_edges, y_samp) - 1
    yi = np.clip(yi, 0, rows - 1)

    return data[np.ix_(yi, xi)]

"""
_utils.py
=========
Shared low-level utilities used across plot subpackages.
"""

from __future__ import annotations

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


def _normalize_image(data: np.ndarray):
    """Normalise data to uint8, returning (img_u8, vmin, vmax)."""
    img = data.astype(np.float64, copy=False)
    vmin = float(np.nanmin(img))
    vmax = float(np.nanmax(img))
    if vmax > vmin:
        buf = np.empty_like(img)
        np.subtract(img, vmin, out=buf)
        np.divide(buf, vmax - vmin, out=buf)
        np.multiply(buf, 255.0, out=buf)
        img_u8 = buf.astype(np.uint8)
    else:
        img_u8 = np.zeros(data.shape, dtype=np.uint8)
    return img_u8, vmin, vmax


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


def _build_colormap_lut(name: str) -> list:
    """Return a 256-entry ``[[r, g, b], ...]`` LUT for the named colormap.

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

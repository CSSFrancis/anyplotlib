"""
figure_plots.py
===============

Pure-Python plot objects returned by Axes.imshow() / Axes.plot().

These are NOT anywidget subclasses.  They hold all state in plain dicts and
push changes into the parent Figure's per-panel traitlet via _push().

Public classes
--------------
GridSpec        – describes a grid layout (nrows x ncols, ratios).
SubplotSpec     – a slice of a GridSpec (row/col spans).
Axes            – a grid cell; .imshow() / .plot() return a plot object.
Plot2D          – 2-D image panel, full Viewer2D-compatible API.
Plot1D          – 1-D line panel, full Viewer1D-compatible API.
"""

from __future__ import annotations

import uuid as _uuid
import numpy as np
from typing import Callable

from anyplotlib.markers import MarkerRegistry
from anyplotlib.callbacks import CallbackRegistry
from anyplotlib.widgets import (
    Widget,
    RectangleWidget, CircleWidget, AnnularWidget,
    CrosshairWidget, PolygonWidget, LabelWidget,
    VLineWidget as _VLineWidget,
    HLineWidget as _HLineWidget,
    RangeWidget as _RangeWidget,
    PointWidget as _PointWidget,
)

__all__ = ["GridSpec", "SubplotSpec", "Axes", "InsetAxes", "Line1D", "Plot1D", "Plot2D",
           "PlotMesh", "Plot3D", "PlotBar", "_plot_kind", "_resample_mesh", "_norm_linestyle"]


# ---------------------------------------------------------------------------
# Linestyle normalisation
# ---------------------------------------------------------------------------

_LINESTYLE_ALIASES: dict[str, str] = {
    "-":        "solid",
    "--":       "dashed",
    ":":        "dotted",
    "-.":       "dashdot",
    "solid":    "solid",
    "dashed":   "dashed",
    "dotted":   "dotted",
    "dashdot":  "dashdot",
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
            "'solid', 'dashed', 'dotted', 'dashdot', "
            "or shorthands '-', '--', ':', '-.'."
        )
    return canonical


# ---------------------------------------------------------------------------
# GridSpec / SubplotSpec
# ---------------------------------------------------------------------------

class SubplotSpec:
    """Describes which grid cells a subplot occupies."""

    def __init__(self, gs: "GridSpec", row_start: int, row_stop: int,
                 col_start: int, col_stop: int):
        self._gs = gs
        self.row_start = row_start
        self.row_stop  = row_stop
        self.col_start = col_start
        self.col_stop  = col_stop

    def __repr__(self) -> str:
        return (f"SubplotSpec(rows={self.row_start}:{self.row_stop}, "
                f"cols={self.col_start}:{self.col_stop})")


class GridSpec:
    """Define a grid of subplot cells.

    Parameters
    ----------
    nrows, ncols : int
        Grid dimensions.
    width_ratios : list of float, optional
        Relative column widths (length ncols).  Defaults to equal widths.
    height_ratios : list of float, optional
        Relative row heights (length nrows).  Defaults to equal heights.

    Examples
    --------
    >>> gs = GridSpec(2, 3, width_ratios=[2, 1, 1])
    >>> spec = gs[0, :]          # top row spanning all columns
    >>> spec = gs[1, 1:3]        # bottom-right 2 columns
    """

    def __init__(self, nrows: int, ncols: int, *,
                 width_ratios: list | None = None,
                 height_ratios: list | None = None):
        self.nrows = nrows
        self.ncols = ncols
        self.width_ratios  = list(width_ratios)  if width_ratios  else [1] * ncols
        self.height_ratios = list(height_ratios) if height_ratios else [1] * nrows
        if len(self.width_ratios)  != ncols:
            raise ValueError("len(width_ratios) must equal ncols")
        if len(self.height_ratios) != nrows:
            raise ValueError("len(height_ratios) must equal nrows")

    def __getitem__(self, key) -> SubplotSpec:
        """Return a SubplotSpec for the given (row, col) index or slice pair.

        Matches matplotlib's GridSpec indexing exactly:
        - Integer index ``i`` selects a single row or column (negative indices
          count from the end, just like Python lists).
        - Slice ``start:stop`` selects rows/columns ``start`` up to (but not
          including) ``stop``.  The full-span slice ``:`` selects all rows or
          columns.
        - Step values other than 1 (or None) raise ``ValueError``.
        - Out-of-range or empty slices raise ``IndexError``.
        """
        if not isinstance(key, tuple) or len(key) != 2:
            raise IndexError("GridSpec requires a (row, col) index or slice pair")
        row_idx, col_idx = key

        def _resolve(idx, n, axis_name):
            if isinstance(idx, int):
                i = idx if idx >= 0 else n + idx
                if not (0 <= i < n):
                    raise IndexError(
                        f"{axis_name} index {idx} is out of bounds for size {n}"
                    )
                return i, i + 1
            if isinstance(idx, slice):
                start, stop, step = idx.indices(n)
                if step != 1:
                    raise ValueError(
                        f"GridSpec slices must have step 1 (got {step})"
                    )
                if start >= stop:
                    raise IndexError(
                        f"GridSpec slice {idx} produces an empty span on axis of size {n}"
                    )
                return start, stop
            raise IndexError(f"Invalid GridSpec index: {idx!r}")

        r0, r1 = _resolve(row_idx, self.nrows, "row")
        c0, c1 = _resolve(col_idx, self.ncols, "col")
        return SubplotSpec(self, r0, r1, c0, c1)

    def __repr__(self) -> str:
        return f"GridSpec({self.nrows}, {self.ncols})"


# ---------------------------------------------------------------------------
# Axes — grid cell container
# ---------------------------------------------------------------------------

class Axes:
    """A single grid cell in a Figure.

    Returned by Figure.add_subplot() and Figure.subplots().
    Call .imshow() or .plot() to attach a data plot and get back
    a Plot2D or Plot1D object.
    """

    def __init__(self, fig: "Figure", spec: SubplotSpec):  # noqa: F821
        self._fig  = fig
        self._spec = spec
        self._plot: "Plot1D | Plot2D | None" = None

    # ------------------------------------------------------------------
    def imshow(self, data: np.ndarray,
               axes: list | None = None,
               units: str = "px",
               cmap: str | None = None,
               vmin: float | None = None,
               vmax: float | None = None,
               origin: str = "upper") -> "Plot2D":
        """Attach a 2-D image to this axes cell.

        Parameters
        ----------
        data : np.ndarray, shape (H, W) or (H, W, C)
            Image data.  RGB/RGBA arrays use only the first channel.
        axes : [x_axis, y_axis], optional
            Physical coordinate arrays for each axis.
        units : str, optional
            Axis units label.  Default ``"px"``.
        cmap : str, optional
            Colormap name (e.g. ``"viridis"``, ``"inferno"``).
            Defaults to ``"gray"``.
        vmin, vmax : float, optional
            Colormap clipping limits in data units.  Values outside this
            range are clamped to the colormap endpoints.  Defaults to the
            data min / max.
        origin : ``"upper"`` | ``"lower"``, optional
            Where row 0 of the array is placed.  ``"upper"`` (default)
            puts row 0 at the top, matching the usual image convention.
            ``"lower"`` puts row 0 at the bottom, matching the matplotlib
            convention for matrices / scientific plots.

        Returns
        -------
        Plot2D
        """
        x_axis = axes[0] if axes and len(axes) > 0 else None
        y_axis = axes[1] if axes and len(axes) > 1 else None
        plot = Plot2D(data, x_axis=x_axis, y_axis=y_axis, units=units,
                      cmap=cmap, vmin=vmin, vmax=vmax, origin=origin)
        self._attach(plot)
        return plot

    def pcolormesh(self, data: np.ndarray,
                   x_edges=None, y_edges=None,
                   units: str = "") -> "PlotMesh":
        """Attach a 2-D mesh to this axes cell using edge coordinates.

        Follows the matplotlib pcolormesh convention: x_edges and y_edges
        are the cell *edge* coordinates, so they have length N+1 and M+1
        respectively for an (M, N) data array.

        Parameters
        ----------
        data : np.ndarray  shape (M, N)
        x_edges : array-like, length N+1, optional
            Column edge coordinates.  Defaults to ``np.arange(N+1)``.
        y_edges : array-like, length M+1, optional
            Row edge coordinates.  Defaults to ``np.arange(M+1)``.
        units : str, optional

        Returns
        -------
        PlotMesh
        """
        plot = PlotMesh(data, x_edges=x_edges, y_edges=y_edges, units=units)
        self._attach(plot)
        return plot

    def plot_surface(self, X, Y, Z, *,
                     colormap: str = "viridis",
                     x_label: str = "x", y_label: str = "y", z_label: str = "z",
                     azimuth: float = -60.0, elevation: float = 30.0,
                     zoom: float = 1.0) -> "Plot3D":
        """Attach a 3-D surface to this axes cell.

        Parameters
        ----------
        X, Y, Z : array-like
            2-D grid arrays of the same shape (e.g. from ``np.meshgrid``),
            or 1-D centre arrays for X/Y with a 2-D Z.
        colormap : str, optional  Matplotlib colormap name.  Default ``'viridis'``.
        x_label, y_label, z_label : str, optional  Axis labels.
        azimuth, elevation : float, optional  Initial camera angles in degrees.
        zoom : float, optional  Initial zoom factor.

        Returns
        -------
        Plot3D
        """
        plot = Plot3D("surface", X, Y, Z, colormap=colormap,
                      x_label=x_label, y_label=y_label, z_label=z_label,
                      azimuth=azimuth, elevation=elevation, zoom=zoom)
        self._attach(plot)
        return plot

    def scatter3d(self, x, y, z, *,
                  color: str = "#4fc3f7",
                  point_size: float = 4.0,
                  x_label: str = "x", y_label: str = "y", z_label: str = "z",
                  azimuth: float = -60.0, elevation: float = 30.0,
                  zoom: float = 1.0) -> "Plot3D":
        """Attach a 3-D scatter plot to this axes cell.

        Parameters
        ----------
        x, y, z : array-like, shape (N,)  Point coordinates.
        color : str, optional  CSS colour for all points.
        point_size : float, optional  Radius of each point in pixels.
        x_label, y_label, z_label : str, optional  Axis labels.
        azimuth, elevation : float, optional  Initial camera angles in degrees.
        zoom : float, optional  Initial zoom factor.

        Returns
        -------
        Plot3D
        """
        plot = Plot3D("scatter", x, y, z, color=color, point_size=point_size,
                      x_label=x_label, y_label=y_label, z_label=z_label,
                      azimuth=azimuth, elevation=elevation, zoom=zoom)
        self._attach(plot)
        return plot

    def plot3d(self, x, y, z, *,
               color: str = "#4fc3f7",
               linewidth: float = 1.5,
               x_label: str = "x", y_label: str = "y", z_label: str = "z",
               azimuth: float = -60.0, elevation: float = 30.0,
               zoom: float = 1.0) -> "Plot3D":
        """Attach a 3-D line plot to this axes cell.

        Parameters
        ----------
        x, y, z : array-like, shape (N,)  Point coordinates along the line.
        color : str, optional  CSS colour.
        linewidth : float, optional  Stroke width in pixels.
        x_label, y_label, z_label : str, optional  Axis labels.
        azimuth, elevation : float, optional  Initial camera angles in degrees.
        zoom : float, optional  Initial zoom factor.

        Returns
        -------
        Plot3D
        """
        plot = Plot3D("line", x, y, z, color=color, linewidth=linewidth,
                      x_label=x_label, y_label=y_label, z_label=z_label,
                      azimuth=azimuth, elevation=elevation, zoom=zoom)
        self._attach(plot)
        return plot

    def plot(self, data: np.ndarray,
             axes: list | None = None,
             units: str = "px",
             y_units: str = "",
             color: str = "#4fc3f7",
             linewidth: float = 1.5,
             linestyle: str = "solid",
             ls: str | None = None,
             alpha: float = 1.0,
             marker: str = "none",
             markersize: float = 4.0,
             label: str = "") -> "Plot1D":
        """Attach a 1-D line to this axes cell.

        Parameters
        ----------
        data : array-like, shape (N,)
            Y values.  Must be 1-D.
        axes : list, optional
            ``[x_axis]`` — a one-element list containing the x-coordinates
            (shape ``(N,)``).  If omitted the x-axis defaults to
            ``0, 1, …, N-1``.
        units : str, optional
            Label for the x-axis (e.g. ``"eV"``, ``"s"``).  Default
            ``"px"``.
        y_units : str, optional
            Label for the y-axis.  Default ``""`` (no label).
        color : str, optional
            CSS colour string for the line (hex, ``rgb()``, named colour,
            etc.).  Default ``"#4fc3f7"``.
        linewidth : float, optional
            Stroke width in pixels.  Default ``1.5``.
        linestyle : str, optional
            Dash pattern.  Accepted values: ``"solid"`` (``"-"``),
            ``"dashed"`` (``"--"``), ``"dotted"`` (``":"``),
            ``"dashdot"`` (``"-."``) .  Default ``"solid"``.
        ls : str, optional
            Short alias for *linestyle*.  Takes precedence if both are given.
        alpha : float, optional
            Line opacity in the range 0–1.  Default ``1.0`` (fully opaque).
        marker : str, optional
            Per-point marker symbol.  Supported values: ``"o"`` (circle),
            ``"s"`` (square), ``"^"`` (triangle-up), ``"v"`` (triangle-down),
            ``"D"`` (diamond), ``"+"`` (plus), ``"x"`` (cross),
            ``"none"`` (no markers).  Default ``"none"``.
        markersize : float, optional
            Marker radius / half-side in pixels.  Default ``4.0``.
        label : str, optional
            Legend label.  A legend is only drawn when at least one line has
            a non-empty label.  Default ``""`` (no legend entry).

        Returns
        -------
        Plot1D
            Live plot object.  Call methods on it to update data, add
            overlays, register callbacks, etc.

        Examples
        --------
        Basic sine wave with a physical x-axis::

            import numpy as np
            import anyplotlib as vw

            x = np.linspace(0, 4 * np.pi, 512)
            fig, ax = vw.subplots(1, 1, figsize=(620, 320))
            v = ax.plot(np.sin(x), axes=[x], units="rad",
                        color="#ff7043", linewidth=2, label="sin")
            v  # display in a Jupyter cell

        Dashed line with semi-transparent markers::

            v = ax.plot(data, linestyle="dashed", alpha=0.7,
                        marker="o", markersize=4)

        Overlay a second curve with :meth:`Plot1D.add_line`::

            v.add_line(np.cos(x), x_axis=x, color="#aed581", label="cos")
        """
        x_axis = axes[0] if axes and len(axes) > 0 else None
        plot = Plot1D(data, x_axis=x_axis, units=units, y_units=y_units,
                     color=color, linewidth=linewidth,
                     linestyle=ls if ls is not None else linestyle,
                     alpha=alpha, marker=marker, markersize=markersize,
                     label=label)
        self._attach(plot)
        return plot

    def bar(self, x, height=None, width: float = 0.8, bottom: float = 0.0, *,
            align: str = "center",
            color: str = "#4fc3f7",
            colors=None,
            orient: str = "v",
            log_scale: bool = False,
            group_labels=None,
            group_colors=None,
            show_values: bool = False,
            units: str = "",
            y_units: str = "",
            # ── legacy backward-compat kwargs ──────────────────────────────
            x_labels=None,
            x_centers=None,
            bar_width=None,
            baseline=None,
            values=None) -> "PlotBar":
        """Attach a bar chart to this axes cell.

        Signature mirrors ``matplotlib.pyplot.bar``::

            ax.bar(x, height, width=0.8, bottom=0.0, ...)

        Parameters
        ----------
        x : array-like of str or numeric
            Bar positions.  Strings become category labels with auto-numeric
            centres; numbers are used directly as bar centres.
        height : array-like, shape ``(N,)`` or ``(N, G)``, optional
            Bar heights.  Pass a 2-D array to draw *G* grouped bars per
            category.  If omitted *x* is treated as the heights and positions
            are generated automatically (backward-compatible call form).
        width : float, optional
            Bar width as a fraction of the category slot (0–1).  Default ``0.8``.
        bottom : float, optional
            Value at which bars are rooted (baseline).  Default ``0``.
        align : ``"center"`` | ``"edge"``, optional
            Alignment of the bar relative to its *x* position.  Currently only
            ``"center"`` is rendered; stored for future use.
        color : str, optional
            Single CSS colour applied to every bar.  Default ``"#4fc3f7"``.
        colors : list of str, optional
            Per-bar colour list (ungrouped) or ignored when *group_colors* is set.
        orient : ``"v"`` | ``"h"``, optional
            Vertical (default) or horizontal orientation.
        log_scale : bool, optional
            Use a logarithmic value axis.  Non-positive values are clamped to
            ``1e-10`` for display.  Default ``False``.
        group_labels : list of str, optional
            Legend labels for each group in a grouped bar chart.
        group_colors : list of str, optional
            CSS colours per group.  Defaults to a built-in palette.
        show_values : bool, optional
            Draw the numeric value above / beside each bar.
        units : str, optional
            Label for the categorical axis.
        y_units : str, optional
            Label for the value axis.

        Backward-compatible keyword aliases
        ------------------------------------
        ``values``    → ``height``
        ``x_centers`` → ``x``
        ``bar_width``  → ``width``
        ``baseline``   → ``bottom``
        ``x_labels``   → strings passed via ``x``

        Returns
        -------
        PlotBar
        """
        # ── legacy backward-compat resolution ─────────────────────────────
        if height is None:
            if values is not None:
                height = values
            else:
                height = x
                x = None
        if baseline is not None:
            bottom = baseline
        if bar_width is not None:
            width = bar_width

        plot = PlotBar(x, height, width=width, bottom=bottom,
                       align=align, color=color, colors=colors,
                       orient=orient, log_scale=log_scale,
                       group_labels=group_labels, group_colors=group_colors,
                       show_values=show_values, units=units, y_units=y_units,
                       x_labels=x_labels, x_centers=x_centers)
        self._attach(plot)
        return plot

    def _attach(self, plot: "Plot1D | Plot2D | PlotMesh | Plot3D | PlotBar") -> None:
        """Register a plot on this axes (replace any previous plot)."""
        # Allocate a panel id if needed; reuse if replacing
        if self._plot is not None:
            panel_id = self._plot._id
        else:
            panel_id = str(_uuid.uuid4())[:8]
        plot._id  = panel_id
        plot._fig = self._fig
        self._plot = plot
        self._fig._register_panel(self, plot)

    def __repr__(self) -> str:
        kind = type(self._plot).__name__ if self._plot else "empty"
        return f"Axes(rows={self._spec.row_start}:{self._spec.row_stop}, cols={self._spec.col_start}:{self._spec.col_stop}, {kind})"


# ---------------------------------------------------------------------------
# Shared normalisation helpers (duplicated from Viewer2D to keep standalone)
# ---------------------------------------------------------------------------

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

    Uses **colorcet** exclusively.  Common matplotlib colormap names are
    transparently remapped via :data:`_CMAP_ALIASES` so callers can keep
    using names like ``"viridis"`` or ``"hot"`` without any matplotlib
    dependency.  Falls back to a plain gray ramp for unknown names.
    """
    import colorcet as cc

    resolved = _CMAP_ALIASES.get(name, name)
    palette = cc.palette.get(resolved)

    if palette is None:
        # Unknown name → linear gray ramp
        return [[v, v, v] for v in range(256)]

    n = len(palette)
    lut: list = []
    for i in range(256):
        h = palette[int(round(i * (n - 1) / 255))].lstrip("#")
        lut.append([int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)])
    return lut


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


# ---------------------------------------------------------------------------
# Plot2D
# ---------------------------------------------------------------------------

class Plot2D:
    """2-D image plot panel.

    Not an anywidget.  Holds state in ``_state`` dict; every mutation calls
    ``_push()`` which writes to the parent Figure's panel trait.

    The marker API follows matplotlib conventions:
        plot.add_circles(offsets, name="g1", facecolors="#f00", radius=5)
        plot.markers["circles"]["g1"].set(radius=8)
    """

    def __init__(self, data: np.ndarray,
                 x_axis=None, y_axis=None, units: str = "px",
                 cmap: str | None = None,
                 vmin: float | None = None,
                 vmax: float | None = None,
                 origin: str = "upper"):
        self._id:  str = ""       # assigned by Axes._attach
        self._fig: object = None  # assigned by Axes._attach

        _valid_origins = ("upper", "lower")
        if origin not in _valid_origins:
            raise ValueError(
                f"origin must be one of {_valid_origins!r}, got {origin!r}"
            )
        self._origin: str = origin

        data = np.asarray(data)
        if data.ndim == 3:
            data = data[:, :, 0]
        if data.ndim != 2:
            raise ValueError(f"data must be 2-D (H x W), got {data.shape}")

        h, w = data.shape

        # origin='lower' — row 0 at the bottom, matching matplotlib's matrix
        # convention.  Flip the data so our renderer (which always draws row 0
        # at the top) shows the correct orientation, and reverse the y-axis so
        # tick values increase upward.
        if origin == "lower":
            data = np.flipud(data)

        self._data: np.ndarray = data.astype(float)

        x_axis_given = x_axis is not None
        y_axis_given = y_axis is not None
        if x_axis is None:
            x_axis = np.arange(w, dtype=float)
        if y_axis is None:
            y_axis = np.arange(h, dtype=float)
        x_axis = np.asarray(x_axis, dtype=float)
        y_axis = np.asarray(y_axis, dtype=float)

        if origin == "lower":
            y_axis = y_axis[::-1]

        img_u8, raw_vmin, raw_vmax = _normalize_image(data)
        self._raw_u8   = img_u8
        self._raw_vmin = raw_vmin
        self._raw_vmax = raw_vmax

        cmap_name = cmap if cmap is not None else "gray"
        cmap_lut  = _build_colormap_lut(cmap_name)

        # vmin/vmax clip the colormap in data units; default to the full range.
        disp_min = float(vmin) if vmin is not None else raw_vmin
        disp_max = float(vmax) if vmax is not None else raw_vmax

        # Compute physical pixel scale (data-units per pixel) from axis arrays
        scale_x = float(abs(x_axis[-1] - x_axis[0]) / max(w - 1, 1)) if len(x_axis) >= 2 else 1.0
        scale_y = float(abs(y_axis[-1] - y_axis[0]) / max(h - 1, 1)) if len(y_axis) >= 2 else 1.0

        self._state: dict = {
            "kind":              "2d",
            "is_mesh":           False,
            "has_axes":          x_axis_given or y_axis_given,
            "image_b64":         self._encode_bytes(img_u8),
            "image_width":       w,
            "image_height":      h,
            "x_axis":            x_axis.tolist(),
            "y_axis":            y_axis.tolist(),
            "units":             units,
            "scale_x":           scale_x,
            "scale_y":           scale_y,
            "display_min":       disp_min,
            "display_max":       disp_max,
            "raw_min":           raw_vmin,
            "raw_max":           raw_vmax,
            "show_colorbar":     False,
            "log_scale":         False,
            "scale_mode":        "linear",
            "colormap_name":     cmap_name,
            "colormap_data":     cmap_lut,
            "zoom":              1.0,
            "center_x":          0.5,
            "center_y":          0.5,
            "overlay_widgets":   [],
            "markers":           [],
            "registered_keys":   [],
            # Transparent mask overlay (set via set_overlay_mask)
            "overlay_mask_b64":   "",
            "overlay_mask_color": "#ff4444",
            "overlay_mask_alpha": 0.4,
            # Set True when Python explicitly changes view; JS uses it to
            # decide whether to preserve the current frontend zoom/pan state.
            "_view_from_python":  False,
        }

        self.markers = MarkerRegistry(self._push_markers,
                                      allowed=MarkerRegistry._KNOWN_2D)
        self.callbacks = CallbackRegistry()
        self._widgets: dict[str, Widget] = {}

    @staticmethod
    def _encode_bytes(arr: np.ndarray) -> str:
        import base64
        return base64.b64encode(arr.tobytes()).decode("ascii")

    def _push(self) -> None:
        """Serialise _state + markers and write to Figure trait."""
        if self._fig is None:
            return
        self._state["overlay_widgets"] = [w.to_dict() for w in self._widgets.values()]
        self._fig._push(self._id)

    def _push_markers(self) -> None:
        """Called by MarkerRegistry whenever markers change."""
        self._state["markers"] = self.markers.to_wire_list()
        self._push()

    def to_state_dict(self) -> dict:
        """Return a JSON-serialisable copy of the current state."""
        d = dict(self._state)
        d["overlay_widgets"] = [w.to_dict() for w in self._widgets.values()]
        d["markers"] = self.markers.to_wire_list()
        return d

    # ------------------------------------------------------------------
    # Data
    # ------------------------------------------------------------------
    @property
    def data(self) -> np.ndarray:
        """The image data in the original user coordinate system (read-only).

        Returns a float64 copy with ``writeable=False``.  To replace the
        data call :meth:`set_data`.
        """
        arr = np.flipud(self._data).copy() if self._origin == "lower" else self._data.copy()
        arr.flags.writeable = False
        return arr

    def set_data(self, data: np.ndarray,
               x_axis=None, y_axis=None, units: str | None = None) -> None:
        """Replace the image data.

        The ``origin`` supplied at construction is automatically re-applied
        so the new data is displayed with the same orientation.
        """
        data = np.asarray(data)
        if data.ndim == 3:
            data = data[:, :, 0]
        if data.ndim != 2:
            raise ValueError(f"data must be 2-D, got {data.shape}")
        h, w = data.shape

        if self._origin == "lower":
            data = np.flipud(data)

        self._data = data.astype(float)
        img_u8, vmin, vmax = _normalize_image(data)
        self._raw_u8, self._raw_vmin, self._raw_vmax = img_u8, vmin, vmax

        if x_axis is not None:
            self._state["x_axis"] = np.asarray(x_axis, float).tolist()
            self._state["image_width"] = w
            self._state["has_axes"] = True
        if y_axis is not None:
            ya = np.asarray(y_axis, float)
            if self._origin == "lower":
                ya = ya[::-1]
            self._state["y_axis"] = ya.tolist()
            self._state["image_height"] = h
            self._state["has_axes"] = True
        if units is not None:
            self._state["units"] = units

        self._state.update({
            "image_b64":    self._encode_bytes(img_u8),
            "image_width":  w,
            "image_height": h,
            "display_min":  vmin,
            "display_max":  vmax,
            "raw_min":      vmin,
            "raw_max":      vmax,
            "colormap_data": _build_colormap_lut(self._state["colormap_name"]),
        })
        self._push()

    def set_overlay_mask(self, mask: "np.ndarray | None",
                         color: str = "#ff4444",
                         alpha: float = 0.4) -> None:
        """Set (or clear) a transparent boolean mask drawn over the image.

        The mask is composited client-side in the browser at *alpha* opacity
        using *color* for all ``True`` pixels.  Call with ``mask=None`` to
        remove any existing overlay.

        Parameters
        ----------
        mask : ndarray of shape (H, W), bool or uint8, or None
            Boolean array aligned to the image data.  ``True`` / non-zero
            pixels are filled with *color* at transparency *alpha*.
            Pass ``None`` to clear the overlay.
        color : str, optional
            CSS hex colour for the overlay, e.g. ``"#ff4444"``.  Default red.
            Must be in ``#RRGGBB`` format.
        alpha : float, optional
            Opacity in [0, 1].  Default 0.4 (40 % opaque).
        """
        import base64, re
        # Validate color format
        if not re.fullmatch(r'#[0-9a-fA-F]{6}', color):
            raise ValueError(
                f"color must be a CSS hex colour in '#RRGGBB' format, got {color!r}"
            )
        # Clamp alpha to [0, 1]
        alpha = float(alpha)
        if not (0.0 <= alpha <= 1.0):
            raise ValueError(f"alpha must be in [0, 1], got {alpha!r}")
        if mask is None:
            self._state["overlay_mask_b64"]   = ""
            self._state["overlay_mask_color"] = color
            self._state["overlay_mask_alpha"] = alpha
        else:
            arr = np.asarray(mask)
            if arr.shape != (self._state["image_height"], self._state["image_width"]):
                raise ValueError(
                    f"mask shape {arr.shape} does not match image "
                    f"({self._state['image_height']} x {self._state['image_width']})"
                )
            # For origin='lower' the image data was flipped; flip mask to match.
            if self._origin == "lower":
                arr = np.flipud(arr)
            # Convert to uint8: True/non-zero → 255, False/zero → 0
            u8 = (np.asarray(arr, dtype=bool).view(np.uint8) * 255).astype(np.uint8)
            self._state["overlay_mask_b64"]   = base64.b64encode(u8.tobytes()).decode("ascii")
            self._state["overlay_mask_color"] = color
            self._state["overlay_mask_alpha"] = alpha
        self._push()

    # ------------------------------------------------------------------
    # Display settings
    # ------------------------------------------------------------------
    def set_colormap(self, name: str) -> None:
        self._state["colormap_name"] = name
        self._state["colormap_data"] = _build_colormap_lut(name)
        self._push()

    def set_clim(self, vmin=None, vmax=None) -> None:
        if vmin is not None:
            self._state["display_min"] = float(vmin)
        if vmax is not None:
            self._state["display_max"] = float(vmax)
        self._push()

    def set_scale_mode(self, mode: str) -> None:
        valid = ("linear", "log", "symlog")
        if mode not in valid:
            raise ValueError(f"mode must be one of {valid}")
        self._state["scale_mode"] = mode
        self._push()

    @property
    def colormap_name(self) -> str:
        return self._state["colormap_name"]

    @colormap_name.setter
    def colormap_name(self, name: str) -> None:
        self.set_colormap(name)

    # ------------------------------------------------------------------
    # Overlay Widgets
    # ------------------------------------------------------------------
    def add_widget(self, kind: str, color: str = "#00e5ff", **kwargs) -> Widget:
        kind = kind.lower()
        valid = ("circle", "rectangle", "annular", "polygon", "label", "crosshair")
        if kind not in valid:
            raise ValueError(f"kind must be one of {valid}")
        iw, ih = self._state["image_width"], self._state["image_height"]

        def _f(k, default): return float(kwargs.get(k, default))
        def _i(k, default): return int(kwargs.get(k, default))

        if kind == "circle":
            widget = CircleWidget(lambda: None,
                                  cx=_f("cx", iw / 2), cy=_f("cy", ih / 2),
                                  r=_f("r", iw * 0.1), color=color)
        elif kind == "rectangle":
            widget = RectangleWidget(lambda: None,
                                     x=_f("x", iw * 0.25), y=_f("y", ih * 0.25),
                                     w=_f("w", iw * 0.5), h=_f("h", ih * 0.5),
                                     color=color)
        elif kind == "annular":
            r_outer = _f("r_outer", iw * 0.2)
            r_inner = _f("r_inner", iw * 0.1)
            widget = AnnularWidget(lambda: None,
                                   cx=_f("cx", iw / 2), cy=_f("cy", ih / 2),
                                   r_outer=r_outer, r_inner=r_inner, color=color)
        elif kind == "polygon":
            raw = kwargs.get("vertices", [[iw * .25, ih * .25], [iw * .75, ih * .25],
                                          [iw * .75, ih * .75], [iw * .25, ih * .75]])
            widget = PolygonWidget(lambda: None, vertices=raw, color=color)
        elif kind == "crosshair":
            widget = CrosshairWidget(lambda: None,
                                     cx=_f("cx", iw / 2), cy=_f("cy", ih / 2),
                                     color=color)
        else:  # label
            widget = LabelWidget(lambda: None,
                                 x=_f("x", iw * 0.1), y=_f("y", ih * 0.1),
                                 text=str(kwargs.get("text", "Label")),
                                 fontsize=_i("fontsize", 14), color=color)

        # Replace the temporary push_fn with a targeted one now that
        # we have both the widget's _id and the plot's _id.
        plot_ref = self
        wid_id   = widget._id
        def _targeted_push():
            if plot_ref._fig is not None:
                fields = {k: v for k, v in widget._data.items()
                          if k not in ("id", "type")}
                plot_ref._fig._push_widget(plot_ref._id, wid_id, fields)
        widget._push_fn = _targeted_push

        self._widgets[widget.id] = widget
        self._push()       # full panel push once so JS knows about the widget
        return widget

    def get_widget(self, wid) -> Widget:
        """Return the Widget object by ID string or Widget instance."""
        if isinstance(wid, Widget):
            wid = wid.id
        try:
            return self._widgets[wid]
        except KeyError:
            raise KeyError(wid)

    def remove_widget(self, wid) -> None:
        """Remove a widget by ID string or Widget instance."""
        if isinstance(wid, Widget):
            wid = wid.id
        if wid not in self._widgets:
            raise KeyError(wid)
        del self._widgets[wid]
        self._push()

    def list_widgets(self) -> list:
        return list(self._widgets.values())

    def clear_widgets(self) -> None:
        self._widgets.clear()
        self._push()

    # ------------------------------------------------------------------
    # Callback API  (Plot2D)
    # ------------------------------------------------------------------
    def on_changed(self, fn: Callable) -> Callable:
        """Decorator: fires on every pan/zoom/drag frame on this panel."""
        cid = self.callbacks.connect("on_changed", fn)
        fn._cid = cid
        return fn

    def on_release(self, fn: Callable) -> Callable:
        """Decorator: fires once when pan/zoom/drag settles on this panel."""
        cid = self.callbacks.connect("on_release", fn)
        fn._cid = cid
        return fn

    def on_click(self, fn: Callable) -> Callable:
        """Decorator: fires on click on this panel."""
        cid = self.callbacks.connect("on_click", fn)
        fn._cid = cid
        return fn

    def on_key(self, key_or_fn=None) -> Callable:
        """Register a key-press handler for this panel.

        Two call forms are supported::

            @plot.on_key('q')          # fires only when 'q' is pressed
            def handler(event): ...

            @plot.on_key               # fires for every registered key
            def handler(event): ...

        The event carries: ``key``, ``mouse_x``, ``mouse_y``, ``phys_x``,
        and ``last_widget_id``.

        .. note::
            Registered keys take priority over the built-in **r** (reset view)
            shortcut.
        """
        if callable(key_or_fn):
            return self._connect_on_key(None, key_or_fn)
        key = key_or_fn
        def _decorator(fn):
            return self._connect_on_key(key, fn)
        return _decorator

    def _connect_on_key(self, key, fn) -> Callable:
        if key is None:
            if '*' not in self._state['registered_keys']:
                self._state['registered_keys'].append('*')
                self._push()
            cid = self.callbacks.connect("on_key", fn)
        else:
            if key not in self._state['registered_keys']:
                self._state['registered_keys'].append(key)
                self._push()
            def _wrapped(event):
                if event.data.get('key') == key:
                    fn(event)
            cid = self.callbacks.connect("on_key", _wrapped)
            _wrapped._cid = cid
        fn._cid = cid
        return fn

    def disconnect(self, cid: int) -> None:
        """Remove the callback registered under integer *cid*."""
        self.callbacks.disconnect(cid)

    # ------------------------------------------------------------------
    # View control
    # ------------------------------------------------------------------
    def set_view(self,
                 x0: float | None = None, x1: float | None = None,
                 y0: float | None = None, y1: float | None = None) -> None:
        """Set the viewport to a data-space rectangle.

        Parameters
        ----------
        x0, x1 : float, optional
            Horizontal data-space range to show.  If omitted the full
            x-extent is used for zoom calculation.
        y0, y1 : float, optional
            Vertical data-space range to show.  If omitted the full
            y-extent is used for zoom calculation.

        Translates the requested rectangle into the ``zoom`` / ``center_x``
        / ``center_y`` state values used by the 2-D JS renderer.
        """
        xarr = np.asarray(self._state["x_axis"])
        yarr = np.asarray(self._state["y_axis"])
        if len(xarr) < 2 or len(yarr) < 2:
            return

        xmin, xmax = float(xarr[0]), float(xarr[-1])
        ymin, ymax = float(yarr[0]), float(yarr[-1])
        x_span = xmax - xmin or 1.0
        y_span = ymax - ymin or 1.0

        zoom_candidates = []

        if x0 is not None and x1 is not None:
            fx0 = max(0.0, min(1.0, (float(x0) - xmin) / x_span))
            fx1 = max(0.0, min(1.0, (float(x1) - xmin) / x_span))
            if fx1 > fx0:
                self._state["center_x"] = (fx0 + fx1) / 2.0
                zoom_candidates.append(1.0 / (fx1 - fx0))

        if y0 is not None and y1 is not None:
            fy0 = max(0.0, min(1.0, (float(y0) - ymin) / y_span))
            fy1 = max(0.0, min(1.0, (float(y1) - ymin) / y_span))
            if fy1 > fy0:
                self._state["center_y"] = (fy0 + fy1) / 2.0
                zoom_candidates.append(1.0 / (fy1 - fy0))

        if zoom_candidates:
            self._state["zoom"] = min(zoom_candidates)
        self._state["_view_from_python"] = True
        self._push()
        self._state["_view_from_python"] = False

    def reset_view(self) -> None:
        """Reset pan and zoom to show the full image."""
        self._state["zoom"]     = 1.0
        self._state["center_x"] = 0.5
        self._state["center_y"] = 0.5
        self._state["_view_from_python"] = True
        self._push()
        self._state["_view_from_python"] = False

    # ------------------------------------------------------------------
    # Marker API  (matplotlib-style kwargs → MarkerRegistry)
    # ------------------------------------------------------------------
    def _add_marker(self, mtype: str, name: str | None, **kwargs) -> "MarkerGroup":  # noqa: F821
        return self.markers.add(mtype, name, **kwargs)

    def add_circles(self, offsets, name=None, *, radius=5,
                    facecolors=None, edgecolors="#ff0000",
                    linewidths=1.5, alpha=0.3,
                    hover_edgecolors=None, hover_facecolors=None,
                    labels=None, label=None) -> "MarkerGroup":  # noqa: F821
        """Add circle markers at (x, y) positions in data coordinates."""
        return self._add_marker("circles", name, offsets=offsets, radius=radius,
                                facecolors=facecolors, edgecolors=edgecolors,
                                linewidths=linewidths, alpha=alpha,
                                hover_edgecolors=hover_edgecolors,
                                hover_facecolors=hover_facecolors,
                                labels=labels, label=label)

    def add_points(self, offsets, name=None, *, sizes=5,
                   color="#ff0000", facecolors=None,
                   linewidths=1.5, alpha=0.3,
                   hover_edgecolors=None, hover_facecolors=None,
                   labels=None, label=None) -> "MarkerGroup":  # noqa: F821
        """Add point markers at (x, y) positions in data coordinates."""
        return self._add_marker("circles", name, offsets=offsets, radius=sizes,
                                edgecolors=color, facecolors=facecolors,
                                linewidths=linewidths, alpha=alpha,
                                hover_edgecolors=hover_edgecolors,
                                hover_facecolors=hover_facecolors,
                                labels=labels, label=label)

    def add_hlines(self, y_values, name=None, *,
                   color="#ff0000", linewidths=1.5,
                   hover_edgecolors=None,
                   labels=None, label=None) -> "MarkerGroup":  # noqa: F821
        """Add static horizontal lines at the given y positions."""
        return self._add_marker("hlines", name, offsets=y_values,
                                color=color, linewidths=linewidths,
                                hover_edgecolors=hover_edgecolors,
                                labels=labels, label=label)

    def add_vlines(self, x_values, name=None, *,
                   color="#ff0000", linewidths=1.5,
                   hover_edgecolors=None,
                   labels=None, label=None) -> "MarkerGroup":  # noqa: F821
        """Add static vertical lines at the given x positions."""
        return self._add_marker("vlines", name, offsets=x_values,
                                color=color, linewidths=linewidths,
                                hover_edgecolors=hover_edgecolors,
                                labels=labels, label=label)

    def add_arrows(self, offsets, U, V, name=None, *,
                   edgecolors="#ff0000", linewidths=1.5,
                   hover_edgecolors=None,
                   labels=None, label=None) -> "MarkerGroup":  # noqa: F821
        return self._add_marker("arrows", name, offsets=offsets, U=U, V=V,
                                edgecolors=edgecolors, linewidths=linewidths,
                                hover_edgecolors=hover_edgecolors,
                                labels=labels, label=label)

    def add_ellipses(self, offsets, widths, heights, name=None, *,
                     angles=0, facecolors=None, edgecolors="#ff0000",
                     linewidths=1.5, alpha=0.3,
                     hover_edgecolors=None, hover_facecolors=None,
                     labels=None, label=None) -> "MarkerGroup":  # noqa: F821
        return self._add_marker("ellipses", name, offsets=offsets,
                                widths=widths, heights=heights, angles=angles,
                                facecolors=facecolors, edgecolors=edgecolors,
                                linewidths=linewidths, alpha=alpha,
                                hover_edgecolors=hover_edgecolors,
                                hover_facecolors=hover_facecolors,
                                labels=labels, label=label)

    def add_lines(self, segments, name=None, *,
                  edgecolors="#ff0000", linewidths=1.5,
                  hover_edgecolors=None,
                  labels=None, label=None) -> "MarkerGroup":  # noqa: F821
        return self._add_marker("lines", name, segments=segments,
                                edgecolors=edgecolors, linewidths=linewidths,
                                hover_edgecolors=hover_edgecolors,
                                labels=labels, label=label)

    def add_rectangles(self, offsets, widths, heights, name=None, *,
                       angles=0, facecolors=None, edgecolors="#ff0000",
                       linewidths=1.5, alpha=0.3,
                       hover_edgecolors=None, hover_facecolors=None,
                       labels=None, label=None) -> "MarkerGroup":  # noqa: F821
        return self._add_marker("rectangles", name, offsets=offsets,
                                widths=widths, heights=heights, angles=angles,
                                facecolors=facecolors, edgecolors=edgecolors,
                                linewidths=linewidths, alpha=alpha,
                                hover_edgecolors=hover_edgecolors,
                                hover_facecolors=hover_facecolors,
                                labels=labels, label=label)

    def add_squares(self, offsets, widths, name=None, *,
                    angles=0, facecolors=None, edgecolors="#ff0000",
                    linewidths=1.5, alpha=0.3,
                    hover_edgecolors=None, hover_facecolors=None,
                    labels=None, label=None) -> "MarkerGroup":  # noqa: F821
        return self._add_marker("squares", name, offsets=offsets,
                                widths=widths, angles=angles,
                                facecolors=facecolors, edgecolors=edgecolors,
                                linewidths=linewidths, alpha=alpha,
                                hover_edgecolors=hover_edgecolors,
                                hover_facecolors=hover_facecolors,
                                labels=labels, label=label)

    def add_polygons(self, vertices_list, name=None, *,
                     facecolors=None, edgecolors="#ff0000",
                     linewidths=1.5, alpha=0.3,
                     hover_edgecolors=None, hover_facecolors=None,
                     labels=None, label=None) -> "MarkerGroup":  # noqa: F821
        return self._add_marker("polygons", name, vertices_list=vertices_list,
                                facecolors=facecolors, edgecolors=edgecolors,
                                linewidths=linewidths, alpha=alpha,
                                hover_edgecolors=hover_edgecolors,
                                hover_facecolors=hover_facecolors,
                                labels=labels, label=label)

    def add_texts(self, offsets, texts, name=None, *,
                  color="#ff0000", fontsize=12,
                  hover_edgecolors=None,
                  labels=None, label=None) -> "MarkerGroup":  # noqa: F821
        return self._add_marker("texts", name, offsets=offsets, texts=texts,
                                color=color, fontsize=fontsize,
                                hover_edgecolors=hover_edgecolors,
                                labels=labels, label=label)

    def remove_marker(self, marker_type: str, name: str) -> None:
        """Remove a named marker collection by type and name.

        Parameters
        ----------
        marker_type : str
            Collection type, e.g. ``"points"``, ``"vlines"``.
        name : str
            The name used when the collection was created.
        """
        self.markers.remove(marker_type, name)

    def clear_markers(self) -> None:
        """Remove all marker collections from this panel."""
        self.markers.clear()

    def list_markers(self) -> list:
        """Return a summary list of all marker collections on this panel.

        Returns
        -------
        list of dict
            Each dict has keys ``"type"``, ``"name"``, and ``"n"``
            (number of markers in the collection).
        """
        out = []
        for mtype, td in self.markers._types.items():
            for name, g in td.items():
                out.append({"type": mtype, "name": name, "n": g._count()})
        return out

    def __repr__(self) -> str:
        w = self._state.get("image_width", "?")
        h = self._state.get("image_height", "?")
        cmap = self._state.get("colormap_name", "?")
        return f"Plot2D({w}\u00d7{h}, cmap={cmap!r})"


# ---------------------------------------------------------------------------
# PlotMesh  (pcolormesh-style 2-D panel)
# ---------------------------------------------------------------------------

class PlotMesh(Plot2D):
    """2-D mesh plot panel created by :meth:`Axes.pcolormesh`.

    Accepts cell *edge* arrays (length N+1 / M+1) rather than centre arrays,
    matches matplotlib's ``pcolormesh`` convention.  Only ``'circles'`` and
    ``'lines'`` markers are supported.
    """

    def __init__(self, data: np.ndarray,
                 x_edges=None, y_edges=None, units: str = ""):
        data = np.asarray(data)
        if data.ndim != 2:
            raise ValueError(f"data must be 2-D (M x N), got {data.shape}")
        rows, cols = data.shape

        if x_edges is None:
            x_edges = np.arange(cols + 1, dtype=float)
        if y_edges is None:
            y_edges = np.arange(rows + 1, dtype=float)
        x_edges = np.asarray(x_edges, dtype=float)
        y_edges = np.asarray(y_edges, dtype=float)

        if len(x_edges) != cols + 1:
            raise ValueError(
                f"x_edges must have length {cols + 1} for {cols} columns, "
                f"got {len(x_edges)}")
        if len(y_edges) != rows + 1:
            raise ValueError(
                f"y_edges must have length {rows + 1} for {rows} rows, "
                f"got {len(y_edges)}")

        # Resample to a regular pixel grid for display
        resampled = _resample_mesh(data, x_edges, y_edges)

        # Use cell centres to initialise the parent (axes will be replaced)
        x_c = (x_edges[:-1] + x_edges[1:]) / 2.0
        y_c = (y_edges[:-1] + y_edges[1:]) / 2.0
        super().__init__(resampled, x_axis=x_c, y_axis=y_c, units=units)

        # Override mesh-specific state
        self._state["is_mesh"]  = True
        self._state["has_axes"] = True
        # Store edges (not centres) so the JS renderer can place grid lines
        self._state["x_axis"] = x_edges.tolist()
        self._state["y_axis"] = y_edges.tolist()
        # Mesh panels have no fixed pixel scale
        self._state.pop("scale_x", None)
        self._state.pop("scale_y", None)

        # Restrict markers to circles + lines only
        self.markers = MarkerRegistry(self._push_markers,
                                      allowed=MarkerRegistry._KNOWN_MESH)

    # ------------------------------------------------------------------
    # Data
    # ------------------------------------------------------------------
    def set_data(self, data: np.ndarray,
               x_edges=None, y_edges=None, units: str | None = None) -> None:
        """Replace the mesh data (and optionally the edge arrays)."""
        data = np.asarray(data)
        if data.ndim != 2:
            raise ValueError(f"data must be 2-D, got {data.shape}")
        rows, cols = data.shape

        cur_xe = np.asarray(self._state["x_axis"], dtype=float)
        cur_ye = np.asarray(self._state["y_axis"], dtype=float)
        xe = np.asarray(x_edges, dtype=float) if x_edges is not None else cur_xe
        ye = np.asarray(y_edges, dtype=float) if y_edges is not None else cur_ye

        if len(xe) != cols + 1:
            raise ValueError(f"x_edges must have length {cols + 1}")
        if len(ye) != rows + 1:
            raise ValueError(f"y_edges must have length {rows + 1}")

        resampled = _resample_mesh(data, xe, ye)
        img_u8, vmin, vmax = _normalize_image(resampled)
        self._raw_u8, self._raw_vmin, self._raw_vmax = img_u8, vmin, vmax

        self._state.update({
            "image_b64":      self._encode_bytes(img_u8),
            "image_width":    cols,
            "image_height":   rows,
            "x_axis":         xe.tolist(),
            "y_axis":         ye.tolist(),
            "display_min":    vmin,
            "display_max":    vmax,
            "raw_min":        vmin,
            "raw_max":        vmax,
            "colormap_data":  _build_colormap_lut(self._state["colormap_name"]),
        })
        if units is not None:
            self._state["units"] = units
        self._push()


# ---------------------------------------------------------------------------
# _triangulate_grid helper + Plot3D
# ---------------------------------------------------------------------------

def _triangulate_grid(rows: int, cols: int) -> list:
    """Return a flat list of [i0, i1, i2] triangle indices for an (rows×cols) grid."""
    faces = []
    for r in range(rows - 1):
        for c in range(cols - 1):
            i = r * cols + c
            faces.append([i,       i + 1,       i + cols])
            faces.append([i + 1,   i + cols + 1, i + cols])
    return faces


class Plot3D:
    """3-D plot panel.

    Supports three geometry types matching matplotlib's 3-D Axes API:

    * ``'surface'``  – triangulated surface, Z-coloured via colormap.
    * ``'scatter'``  – point cloud, single colour.
    * ``'line'``     – connected line through 3-D points.

    Created by :meth:`Axes.plot_surface`, :meth:`Axes.scatter3d`,
    and :meth:`Axes.plot3d`.

    Not an anywidget.  Holds state in ``_state`` dict; every mutation
    calls ``_push()`` which writes to the parent Figure's panel trait.
    """

    def __init__(self, geom_type: str,
                 x, y, z, *,
                 colormap: str = "viridis",
                 color: str = "#4fc3f7",
                 point_size: float = 4.0,
                 linewidth: float = 1.5,
                 x_label: str = "x",
                 y_label: str = "y",
                 z_label: str = "z",
                 azimuth: float = -60.0,
                 elevation: float = 30.0,
                 zoom: float = 1.0):
        self._id:  str = ""
        self._fig: object = None

        geom_type = geom_type.lower()
        if geom_type not in ("surface", "scatter", "line"):
            raise ValueError("geom_type must be 'surface', 'scatter', or 'line'")

        x = np.asarray(x, dtype=float)
        y = np.asarray(y, dtype=float)
        z = np.asarray(z, dtype=float)

        if geom_type == "surface":
            # Accept 2-D grid arrays (meshgrid style) or 1-D flat arrays
            if x.ndim == 2 and y.ndim == 2 and z.ndim == 2:
                rows, cols = z.shape
                xf, yf, zf = x.ravel(), y.ravel(), z.ravel()
            elif x.ndim == 1 and y.ndim == 1 and z.ndim == 2:
                rows, cols = z.shape
                if len(x) != cols or len(y) != rows:
                    raise ValueError(
                        "For surface with 1-D x/y: x must have length ncols "
                        "and y must have length nrows")
                XX, YY = np.meshgrid(x, y)
                xf, yf, zf = XX.ravel(), YY.ravel(), z.ravel()
            else:
                raise ValueError(
                    "Surface x/y/z must be 2-D grids of the same shape, "
                    "or 1-D x/y centre arrays with 2-D z.")
            faces_list = _triangulate_grid(rows, cols)
        else:
            if x.ndim != 1 or y.ndim != 1 or z.ndim != 1:
                raise ValueError("scatter/line x, y, z must be 1-D arrays")
            if not (len(x) == len(y) == len(z)):
                raise ValueError("x, y, z must have the same length")
            xf, yf, zf = x, y, z
            faces_list = []

        # Normalised data bounds for the JS renderer (from raw arrays — fast)
        data_bounds = {
            "xmin": float(xf.min()), "xmax": float(xf.max()),
            "ymin": float(yf.min()), "ymax": float(yf.max()),
            "zmin": float(zf.min()), "zmax": float(zf.max()),
        }

        # Encode geometry as b64 (float32 saves 50 % wire size vs float64)
        verts_arr  = np.column_stack([xf, yf, zf]).astype(np.float32)   # (N, 3)
        zvals_arr  = zf.astype(np.float32)                                # (N,)
        faces_arr  = (np.asarray(faces_list, dtype=np.int32).reshape(-1, 3)
                      if faces_list else np.empty((0, 3), dtype=np.int32))

        cmap_lut = _build_colormap_lut(colormap)

        self._state: dict = {
            "kind":          "3d",
            "geom_type":     geom_type,
            "vertices_b64":  _arr_to_b64(verts_arr,  np.float32),
            "vertices_count": len(verts_arr),
            "faces_b64":     _arr_to_b64(faces_arr,  np.int32),
            "faces_count":   len(faces_arr),
            "z_values_b64":  _arr_to_b64(zvals_arr,  np.float32),
            "colormap_name": colormap,
            "colormap_data": cmap_lut,
            "color":         color,
            "point_size":    float(point_size),
            "linewidth":     float(linewidth),
            "x_label":       x_label,
            "y_label":       y_label,
            "z_label":       z_label,
            "azimuth":       float(azimuth),
            "elevation":     float(elevation),
            "zoom":          float(zoom),
            "data_bounds":   data_bounds,
            "registered_keys": [],
        }
        self.callbacks = CallbackRegistry()

    # ------------------------------------------------------------------
    def _push(self) -> None:
        if self._fig is None:
            return
        self._fig._push(self._id)

    def to_state_dict(self) -> dict:
        return dict(self._state)

    # ------------------------------------------------------------------
    # Callback API  (Plot3D)
    # ------------------------------------------------------------------
    def on_changed(self, fn: Callable) -> Callable:
        """Decorator: fires on every rotation/zoom frame."""
        cid = self.callbacks.connect("on_changed", fn)
        fn._cid = cid
        return fn

    def on_release(self, fn: Callable) -> Callable:
        """Decorator: fires once when rotation/zoom settles."""
        cid = self.callbacks.connect("on_release", fn)
        fn._cid = cid
        return fn

    def on_click(self, fn: Callable) -> Callable:
        """Decorator: fires on click on this panel."""
        cid = self.callbacks.connect("on_click", fn)
        fn._cid = cid
        return fn

    def on_key(self, key_or_fn=None) -> Callable:
        """Register a key-press handler for this panel.

        Two call forms are supported::

            @plot.on_key('q')          # fires only when 'q' is pressed
            def handler(event): ...

            @plot.on_key               # fires for every registered key
            def handler(event): ...

        The event carries: ``key``, ``mouse_x``, ``mouse_y``, and
        ``last_widget_id``.

        .. note::
            Registered keys take priority over the built-in **r** (reset view)
            shortcut.
        """
        if callable(key_or_fn):
            return self._connect_on_key(None, key_or_fn)
        key = key_or_fn
        def _decorator(fn):
            return self._connect_on_key(key, fn)
        return _decorator

    def _connect_on_key(self, key, fn) -> Callable:
        if key is None:
            if '*' not in self._state['registered_keys']:
                self._state['registered_keys'].append('*')
                self._push()
            cid = self.callbacks.connect("on_key", fn)
        else:
            if key not in self._state['registered_keys']:
                self._state['registered_keys'].append(key)
                self._push()
            def _wrapped(event):
                if event.data.get('key') == key:
                    fn(event)
            cid = self.callbacks.connect("on_key", _wrapped)
            _wrapped._cid = cid
        fn._cid = cid
        return fn

    def disconnect(self, cid: int) -> None:
        """Remove the callback registered under integer *cid*."""
        self.callbacks.disconnect(cid)

    # ------------------------------------------------------------------
    # Display settings
    # ------------------------------------------------------------------
    def set_colormap(self, name: str) -> None:
        """Set the surface colormap (ignored for scatter/line)."""
        self._state["colormap_name"] = name
        self._state["colormap_data"] = _build_colormap_lut(name)
        self._push()

    def set_view(self, azimuth: float | None = None,
                 elevation: float | None = None) -> None:
        """Set the camera azimuth (°) and/or elevation (°)."""
        if azimuth   is not None: self._state["azimuth"]   = float(azimuth)
        if elevation is not None: self._state["elevation"] = float(elevation)
        self._push()

    def set_zoom(self, zoom: float) -> None:
        self._state["zoom"] = float(zoom)
        self._push()

    def set_data(self, x, y, z) -> None:
        """Replace the geometry data."""
        # Re-run the same logic as __init__ for the stored geom_type
        geom_type = self._state["geom_type"]
        x = np.asarray(x, dtype=float)
        y = np.asarray(y, dtype=float)
        z = np.asarray(z, dtype=float)

        if geom_type == "surface":
            if x.ndim == 2 and y.ndim == 2 and z.ndim == 2:
                rows, cols = z.shape
                xf, yf, zf = x.ravel(), y.ravel(), z.ravel()
            elif x.ndim == 1 and y.ndim == 1 and z.ndim == 2:
                rows, cols = z.shape
                XX, YY = np.meshgrid(x, y)
                xf, yf, zf = XX.ravel(), YY.ravel(), z.ravel()
            else:
                raise ValueError("Surface x/y/z must be 2-D grids or 1-D+2-D.")
            faces_list = _triangulate_grid(rows, cols)
        else:
            xf, yf, zf = x.ravel(), y.ravel(), z.ravel()
            faces_list = []

        data_bounds = {
            "xmin": float(xf.min()), "xmax": float(xf.max()),
            "ymin": float(yf.min()), "ymax": float(yf.max()),
            "zmin": float(zf.min()), "zmax": float(zf.max()),
        }

        verts_arr = np.column_stack([xf, yf, zf]).astype(np.float32)
        zvals_arr = zf.astype(np.float32)
        faces_arr = (np.asarray(faces_list, dtype=np.int32).reshape(-1, 3)
                     if faces_list else np.empty((0, 3), dtype=np.int32))

        self._state.update({
            "vertices_b64":   _arr_to_b64(verts_arr, np.float32),
            "vertices_count": len(verts_arr),
            "faces_b64":      _arr_to_b64(faces_arr, np.int32),
            "faces_count":    len(faces_arr),
            "z_values_b64":   _arr_to_b64(zvals_arr, np.float32),
            "data_bounds":    data_bounds,
            "colormap_data":  _build_colormap_lut(self._state["colormap_name"]),
        })
        self._push()

    def __repr__(self) -> str:
        geom = self._state.get("geom_type", "?")
        n = len(self._state.get("vertices", []))
        return f"Plot3D(geom={geom!r}, n_vertices={n})"


# ---------------------------------------------------------------------------
# Line1D — per-line handle
# ---------------------------------------------------------------------------

class Line1D:
    """Handle to a single line on a :class:`Plot1D` panel.

    Returned by :meth:`Plot1D.add_line`.  Use it to update the line data,
    register hover/click callbacks scoped to just that line, or to remove
    it later.

    Attributes
    ----------
    id : str | None
        ``None`` for the primary line; an 8-character UUID string for
        overlay lines added with :meth:`Plot1D.add_line`.
    """

    def __init__(self, plot: "Plot1D", lid: str | None):
        self._plot = plot
        self._lid  = lid

    @property
    def id(self) -> str | None:
        return self._lid

    def __str__(self) -> str:
        return "" if self._lid is None else self._lid

    def __repr__(self) -> str:
        return f"Line1D(id={self._lid!r})"

    def __eq__(self, other) -> bool:
        if isinstance(other, Line1D):
            return self._lid == other._lid
        if isinstance(other, str):
            return self._lid == other
        return NotImplemented

    def __hash__(self) -> int:
        return hash(self._lid)

    # ------------------------------------------------------------------
    def on_hover(self, fn: Callable) -> Callable:
        """Decorator: fires when the cursor moves over *this* line only."""
        target_lid = self._lid
        def _filtered(event):
            if event.data.get("line_id") == target_lid:
                fn(event)
        cid = self._plot.callbacks.connect("on_line_hover", _filtered)
        _filtered._cid = cid
        fn._cid        = cid
        return fn

    def on_click(self, fn: Callable) -> Callable:
        """Decorator: fires when the user clicks on *this* line only."""
        target_lid = self._lid
        def _filtered(event):
            if event.data.get("line_id") == target_lid:
                fn(event)
        cid = self._plot.callbacks.connect("on_line_click", _filtered)
        _filtered._cid = cid
        fn._cid        = cid
        return fn

    def set_data(self, y: "np.ndarray", x_axis=None) -> None:
        """Update the y-data (and optionally x-axis) of this overlay line.

        The y-axis range is recomputed and the panel re-renders immediately.

        Parameters
        ----------
        y : array-like, shape (N,)
            New y values.  Must be 1-D.
        x_axis : array-like, shape (N,), optional
            New x coordinates.  If omitted the existing x-axis is kept.

        Raises
        ------
        ValueError
            If called on the primary line (use :meth:`Plot1D.set_data`
            instead), or if *y* is not 1-D.
        KeyError
            If this line has already been removed.
        """
        if self._lid is None:
            raise ValueError(
                "Cannot call set_data() on the primary line; "
                "use plot.set_data() instead."
            )
        y = np.asarray(y, dtype=float)
        if y.ndim != 1:
            raise ValueError("y must be 1-D")
        for entry in self._plot._state["extra_lines"]:
            if entry["id"] == self._lid:
                entry["data"] = y
                if x_axis is not None:
                    entry["x_axis"] = np.asarray(x_axis, dtype=float)
                break
        else:
            raise KeyError(self._lid)
        self._plot._recompute_data_range()
        self._plot._push()

    def remove(self) -> None:
        """Remove this overlay line from its parent plot."""
        if self._lid is None:
            raise ValueError("Cannot remove the primary line via Line1D.remove().")
        self._plot.remove_line(self._lid)


# ---------------------------------------------------------------------------
# Plot1D
# ---------------------------------------------------------------------------

class Plot1D:
    """1-D line plot panel returned by :meth:`Axes.plot`.

    All display state is stored in a plain ``_state`` dict.  Every mutation
    ends with :meth:`_push`, which serialises the state to the parent
    ``Figure`` trait so the JS renderer picks up the change immediately.

    Supported line properties
    -------------------------
    Set at construction time via :meth:`Axes.plot` or updated afterwards
    with the corresponding setter:

    .. list-table::
       :header-rows: 1
       :widths: 18 18 64

       * - Parameter
         - Default
         - Description
       * - ``color``
         - ``"#4fc3f7"``
         - CSS colour string for the primary line.
       * - ``linewidth``
         - ``1.5``
         - Stroke width in pixels.
       * - ``linestyle`` (``ls``)
         - ``"solid"``
         - Dash pattern: ``"solid"``, ``"dashed"``, ``"dotted"``,
           ``"dashdot"``.  Shorthands ``"-"``, ``"--"``, ``":"``,
           ``"-."`` also accepted.
       * - ``alpha``
         - ``1.0``
         - Line opacity (0 = transparent, 1 = fully opaque).
       * - ``marker``
         - ``"none"``
         - Per-point symbol: ``"o"`` (circle), ``"s"`` (square),
           ``"^"``/``"v"`` (triangles), ``"D"`` (diamond),
           ``"+"``/``"x"`` (stroke-only), or ``"none"``.
       * - ``markersize``
         - ``4.0``
         - Marker radius / half-side in pixels.
       * - ``label``
         - ``""``
         - Legend label (empty string = no legend entry).


    Public API summary
    ------------------

    **Data**
        :meth:`update` — replace y-data (and optionally the x-axis /
        units) without recreating the panel.

    **Overlay lines**
        :meth:`add_line` / :meth:`remove_line` / :meth:`clear_lines` —
        overlay additional curves on the same axes.

    **Shaded spans**
        :meth:`add_span` / :meth:`remove_span` / :meth:`clear_spans` —
        highlight a region along the x- or y-axis.

    **View control**
        :meth:`set_view` / :meth:`reset_view` — programmatic pan/zoom
        (users can also pan/zoom interactively with the mouse; press **R**
        to reset).

    **Interactive widgets**
        :meth:`add_vline_widget` / :meth:`add_hline_widget` /
        :meth:`add_range_widget` — draggable overlays that report their
        position back to Python via callbacks.  Manage them with
        :meth:`get_widget`, :meth:`remove_widget`, :meth:`list_widgets`,
        and :meth:`clear_widgets`.

    **Static marker collections**
        :meth:`add_points` / :meth:`add_circles` / :meth:`add_vlines` /
        :meth:`add_hlines` / :meth:`add_arrows` / :meth:`add_ellipses` /
        :meth:`add_lines` / :meth:`add_rectangles` / :meth:`add_squares` /
        :meth:`add_polygons` / :meth:`add_texts` — fixed overlays
        positioned at explicit data coordinates.  Access them via
        ``plot.markers[type][name]`` and manage with :meth:`remove_marker`,
        :meth:`clear_markers`, and :meth:`list_markers`.

    **Callbacks**
        :meth:`on_changed` / :meth:`on_release` / :meth:`on_click` /
        :meth:`on_key` — react to pan/zoom frames, mouse clicks, and
        key-presses.  Remove a handler with :meth:`disconnect`.
    """

    def __init__(self, data: np.ndarray,
                 x_axis=None,
                 units: str = "px",
                 y_units: str = "",
                 color: str = "#4fc3f7",
                 linewidth: float = 1.5,
                 linestyle: str = "solid",
                 alpha: float = 1.0,
                 marker: str = "none",
                 markersize: float = 4.0,
                 label: str = ""):
        self._id:  str = ""
        self._fig: object = None

        data = np.asarray(data, dtype=float)
        if data.ndim != 1:
            raise ValueError(f"data must be 1-D, got {data.shape}")
        n = len(data)
        if x_axis is None:
            x_axis = np.arange(n, dtype=float)
        x_axis = np.asarray(x_axis, dtype=float)
        if len(x_axis) != n:
            raise ValueError("x_axis length must match data length")

        dmin = float(np.nanmin(data))
        dmax = float(np.nanmax(data))
        pad  = (dmax - dmin) * 0.05 if dmax > dmin else 0.5
        dmin -= pad; dmax += pad

        self._state: dict = {
            "kind":             "1d",
            "data":             data,          # numpy float64 — encoded in to_state_dict()
            "x_axis":           x_axis,        # numpy float64 — encoded in to_state_dict()
            "units":            units,
            "y_units":          y_units,
            "data_min":         dmin,
            "data_max":         dmax,
            "view_x0":          0.0,
            "view_x1":          1.0,
            "line_color":       color,
            "line_linewidth":   float(linewidth),
            "line_linestyle":   _norm_linestyle(linestyle),
            "line_alpha":       float(alpha),
            "line_marker":      marker if marker is not None else "none",
            "line_markersize":  float(markersize),
            "line_label":       label,
            "extra_lines":      [],
            "spans":            [],
            "overlay_widgets":  [],
            "markers":          [],
            "registered_keys":  [],
        }

        self.markers = MarkerRegistry(self._push_markers,
                                      allowed=MarkerRegistry._KNOWN_1D)
        self.callbacks = CallbackRegistry()
        self._widgets: dict[str, Widget] = {}

    def _push(self) -> None:
        if self._fig is None:
            return
        self._state["overlay_widgets"] = [w.to_dict() for w in self._widgets.values()]
        self._fig._push(self._id)

    def _push_markers(self) -> None:
        self._state["markers"] = self.markers.to_wire_list()
        self._push()

    def to_state_dict(self) -> dict:
        d = dict(self._state)
        # Replace numpy arrays with b64-encoded strings for the wire format.
        data_arr  = d.pop("data")
        x_arr     = d.pop("x_axis")
        d["data_b64"]    = _arr_to_b64(data_arr,  np.float64)
        d["x_axis_b64"]  = _arr_to_b64(x_arr,     np.float64)
        d["data_length"] = len(data_arr)
        # Encode extra-line arrays too
        new_extra = []
        for ex in d["extra_lines"]:
            ex2 = dict(ex)
            ex2["data_b64"]   = _arr_to_b64(ex2.pop("data"),  np.float64)
            ex2["x_axis_b64"] = _arr_to_b64(
                np.asarray(ex2.pop("x_axis"), dtype=np.float64), np.float64)
            new_extra.append(ex2)
        d["extra_lines"]    = new_extra
        d["overlay_widgets"] = [w.to_dict() for w in self._widgets.values()]
        d["markers"]         = self.markers.to_wire_list()
        return d

    @property
    def line(self) -> "Line1D":
        """Handle for the primary line, enabling per-line callbacks.

        Returns a :class:`Line1D` with ``id=None`` so you can register
        hover / click handlers scoped to just the primary line::

            @plot.line.on_click
            def on_primary_click(event):
                print(f"primary line clicked at x={event.x:.3f}")
        """
        return Line1D(self, None)

    # ------------------------------------------------------------------
    # Data
    # ------------------------------------------------------------------
    @property
    def data(self) -> np.ndarray:
        """The primary line's y-data (read-only).

        Returns a float64 copy with ``writeable=False``.  To replace the
        data call :meth:`set_data`.
        """
        arr = self._state["data"].copy()
        arr.flags.writeable = False
        return arr

    def set_data(self, data: np.ndarray, x_axis=None,
               units: str | None = None, y_units: str | None = None) -> None:
        """Replace the primary line's y-data and optionally its x-axis / units.

        The y-axis range (``data_min`` / ``data_max``) is recomputed
        automatically.  The viewport is **not** reset — call
        :meth:`reset_view` explicitly if needed.

        Parameters
        ----------
        data : array-like, shape (N,)
            New y values.  Must be 1-D.
        x_axis : array-like, shape (N,), optional
            New x coordinates.  If omitted and the length of *data* matches
            the current x-axis, the existing x-axis is reused; otherwise it
            is reset to ``0, 1, …, N-1``.
        units : str, optional
            New x-axis label.  Unchanged if not supplied.
        y_units : str, optional
            New y-axis label.  Unchanged if not supplied.
        """
        data = np.asarray(data, dtype=float)
        if data.ndim != 1:
            raise ValueError(f"data must be 1-D, got {data.shape}")
        n = len(data)
        if x_axis is None:
            prev = self._state["x_axis"]          # already a numpy array
            x_axis = prev if len(prev) == n else np.arange(n, dtype=float)
        x_axis = np.asarray(x_axis, dtype=float)

        dmin = float(np.nanmin(data))
        dmax = float(np.nanmax(data))
        pad  = (dmax - dmin) * 0.05 if dmax > dmin else 0.5

        self._state["data"]    = data
        self._state["x_axis"]  = x_axis
        self._state["data_min"] = dmin - pad
        self._state["data_max"] = dmax + pad
        if units    is not None: self._state["units"]   = units
        if y_units  is not None: self._state["y_units"] = y_units
        self._push()

    def _recompute_data_range(self) -> None:
        """Recompute data_min/data_max across the primary line and all overlays.

        Called automatically whenever the set of lines changes so that every
        curve stays fully visible.
        """
        all_vals = [self._state["data"]]   # already a numpy float64 array
        for ex in self._state["extra_lines"]:
            d = ex.get("data")
            if d is not None and len(d):
                all_vals.append(d)
        combined = np.concatenate(all_vals)
        dmin = float(np.nanmin(combined))
        dmax = float(np.nanmax(combined))
        pad  = (dmax - dmin) * 0.05 if dmax > dmin else 0.5
        self._state["data_min"] = dmin - pad
        self._state["data_max"] = dmax + pad

    # ------------------------------------------------------------------
    # Extra lines
    # ------------------------------------------------------------------
    def add_line(self, data: np.ndarray, x_axis=None,
                 color: str = "#ffffff", linewidth: float = 1.5,
                 linestyle: str = "solid", ls: str | None = None,
                 alpha: float = 1.0,
                 marker: str = "none", markersize: float = 4.0,
                 label: str = "") -> "Line1D":
        """Overlay an additional curve on this panel.

        The y-axis range is automatically expanded to include the new data so
        all lines remain fully visible.

        Parameters
        ----------
        data : array-like, shape (N,)
            Y values for the new line.  Must be 1-D.
        x_axis : array-like, shape (N,), optional
            X coordinates.  Defaults to the primary line's x-axis.
        color : str, optional
            CSS colour string.  Default ``"#ffffff"``.
        linewidth : float, optional
            Stroke width in pixels.  Default ``1.5``.
        linestyle : str, optional
            Dash pattern: ``"solid"``, ``"dashed"``, ``"dotted"``,
            ``"dashdot"`` (or shorthands).  Default ``"solid"``.
        ls : str, optional
            Short alias for *linestyle*.
        alpha : float, optional
            Line opacity (0–1).  Default ``1.0``.
        marker : str, optional
            Per-point marker symbol (see :class:`Plot1D`).  Default
            ``"none"``.
        markersize : float, optional
            Marker radius / half-side in pixels.  Default ``4.0``.
        label : str, optional
            Legend label.  Default ``""`` (no legend entry).

        Returns
        -------
        Line1D
            A handle to the new overlay line.  Use it to register
            per-line hover/click callbacks or to remove the line later::

                line = v.add_line(fit, color="#ffcc00", label="fit")
                line.remove()                     # remove it
                @line.on_click                    # per-line click handler
                def clicked(event): ...
        """
        data = np.asarray(data, dtype=float)
        if data.ndim != 1:
            raise ValueError("data must be 1-D")
        xa = (np.asarray(x_axis, dtype=float) if x_axis is not None
              else self._state["x_axis"])
        lid = str(_uuid.uuid4())[:8]
        self._state["extra_lines"].append({
            "id":         lid,
            "data":       data,
            "x_axis":     xa,
            "color":      color,
            "linewidth":  float(linewidth),
            "linestyle":  _norm_linestyle(ls if ls is not None else linestyle),
            "alpha":      float(alpha),
            "marker":     marker if marker is not None else "none",
            "markersize": float(markersize),
            "label":      label,
        })
        self._recompute_data_range()
        self._push()
        return Line1D(self, lid)

    def remove_line(self, lid: "str | Line1D") -> None:
        """Remove an overlay line by its ID or :class:`Line1D` handle.

        The y-axis range is recomputed after removal.

        Parameters
        ----------
        lid : str or Line1D
            The value returned by :meth:`add_line`.

        Raises
        ------
        KeyError
            If *lid* does not match any overlay line.
        """
        if isinstance(lid, Line1D):
            lid = lid._lid
        before = len(self._state["extra_lines"])
        self._state["extra_lines"] = [
            e for e in self._state["extra_lines"] if e["id"] != lid]
        if len(self._state["extra_lines"]) == before:
            raise KeyError(lid)
        self._recompute_data_range()
        self._push()

    def clear_lines(self) -> None:
        """Remove all overlay lines, leaving the primary line intact.

        The y-axis range is recomputed after clearing.
        """
        self._state["extra_lines"] = []
        self._recompute_data_range()
        self._push()

    # ------------------------------------------------------------------
    # Spans
    # ------------------------------------------------------------------
    def add_span(self, v0: float, v1: float,
                 axis: str = "x", color: str | None = None) -> str:
        """Add a shaded span along the x- or y-axis.

        Parameters
        ----------
        v0, v1 : float
            Start and end of the span in data coordinates.
        axis : ``"x"`` | ``"y"``, optional
            Which axis the span runs along.  Default ``"x"``.
        color : str, optional
            CSS colour string (supports alpha, e.g.
            ``"rgba(255,200,0,0.2)"``).  Defaults to a theme-appropriate
            yellow tint.

        Returns
        -------
        str
            Span ID for use with :meth:`remove_span`.
        """
        sid = str(_uuid.uuid4())[:8]
        self._state["spans"].append({
            "id": sid, "v0": float(v0), "v1": float(v1),
            "axis": axis, "color": color,
        })
        self._push()
        return sid

    def remove_span(self, sid: str) -> None:
        """Remove a shaded span by its ID.

        Parameters
        ----------
        sid : str
            The ID returned by :meth:`add_span`.

        Raises
        ------
        KeyError
            If *sid* does not match any span.
        """
        before = len(self._state["spans"])
        self._state["spans"] = [
            s for s in self._state["spans"] if s["id"] != sid]
        if len(self._state["spans"]) == before:
            raise KeyError(sid)
        self._push()

    def clear_spans(self) -> None:
        """Remove all shaded spans."""
        self._state["spans"] = []
        self._push()

    # ------------------------------------------------------------------
    # Overlay Widgets
    # ------------------------------------------------------------------
    def add_vline_widget(self, x: float, color: str = "#00e5ff") -> _VLineWidget:
        """Add a draggable vertical-line overlay.

        Parameters
        ----------
        x : float
            Initial x position in data coordinates.
        color : str, optional
            CSS colour string.  Default ``"#00e5ff"``.

        Returns
        -------
        VLineWidget
            Widget object.  Register position callbacks with
            :meth:`on_changed` / :meth:`on_release`.
        """
        widget = _VLineWidget(lambda: None, x=float(x), color=color)
        plot_ref, wid_id = self, widget._id
        def _tp():
            if plot_ref._fig is not None:
                fields = {k: v for k, v in widget._data.items() if k not in ("id", "type")}
                plot_ref._fig._push_widget(plot_ref._id, wid_id, fields)
        widget._push_fn = _tp
        self._widgets[widget.id] = widget
        self._push()
        return widget

    def add_hline_widget(self, y: float, color: str = "#00e5ff") -> _HLineWidget:
        """Add a draggable horizontal-line overlay.

        Parameters
        ----------
        y : float
            Initial y position in data coordinates.
        color : str, optional
            CSS colour string.  Default ``"#00e5ff"``.

        Returns
        -------
        HLineWidget
            Widget object.  Register position callbacks with
            :meth:`on_changed` / :meth:`on_release`.
        """
        widget = _HLineWidget(lambda: None, y=float(y), color=color)
        plot_ref, wid_id = self, widget._id
        def _tp():
            if plot_ref._fig is not None:
                fields = {k: v for k, v in widget._data.items() if k not in ("id", "type")}
                plot_ref._fig._push_widget(plot_ref._id, wid_id, fields)
        widget._push_fn = _tp
        self._widgets[widget.id] = widget
        self._push()
        return widget

    def add_range_widget(self, x0: float, x1: float,
                         color: str = "#00e5ff",
                         style: str = "band",
                         y: float = 0.0,
                         _push: bool = True) -> _RangeWidget:
        """Add a draggable range overlay to this panel.

        Parameters
        ----------
        x0, x1 : float
            Initial left and right edges in data coordinates.
        color : str, optional
            CSS colour string.  Default ``"#00e5ff"``.
        style : {'band', 'fwhm'}, optional
            Visual style.  ``'band'`` (default) draws two vertical lines with
            a translucent fill.  ``'fwhm'`` draws two draggable circles
            connected by a dashed horizontal line at *y* (the half-maximum
            level), giving an ``o-------o`` FWHM indicator.
        y : float, optional
            Y-coordinate (data space) for the connecting line when
            ``style='fwhm'``.  Ignored when ``style='band'``.  Default 0.
        _push : bool, optional
            Push state to JS immediately. Set to ``False`` when adding
            several widgets at once; call :meth:`_push` manually afterward.

        Returns
        -------
        RangeWidget
            Widget object.  Register position callbacks with
            :meth:`on_changed` / :meth:`on_release`.
        """
        widget = _RangeWidget(lambda: None, x0=float(x0), x1=float(x1),
                              color=color, style=style, y=float(y))
        plot_ref, wid_id = self, widget._id
        def _tp():
            if plot_ref._fig is not None:
                fields = {k: v for k, v in widget._data.items() if k not in ("id", "type")}
                plot_ref._fig._push_widget(plot_ref._id, wid_id, fields)
        widget._push_fn = _tp
        self._widgets[widget.id] = widget
        if _push:
            self._push()
        return widget

    def add_point_widget(self, x: float, y: float,
                         color: str = "#00e5ff",
                         show_crosshair: bool = True,
                         _push: bool = True) -> _PointWidget:
        """Add a freely-draggable control point to this panel.

        Parameters
        ----------
        x : float
            Initial x position in data coordinates.
        y : float
            Initial y position in data coordinates (value axis).
        color : str, optional
            CSS colour string.  Default ``"#00e5ff"``.
        show_crosshair : bool, optional
            Draw dashed guide lines through the handle.  Default ``True``.
            Pass ``False`` for a plain dot with no guide lines.
        _push : bool, optional
            Push state to JS immediately. Set to ``False`` when adding
            several widgets at once; call :meth:`_push` manually afterward.

        Returns
        -------
        PointWidget
        """
        widget = _PointWidget(lambda: None, x=float(x), y=float(y), color=color,
                              show_crosshair=show_crosshair)
        plot_ref, wid_id = self, widget._id
        def _tp_point():
            if plot_ref._fig is not None:
                fields = {k: v for k, v in widget._data.items() if k not in ("id", "type")}
                plot_ref._fig._push_widget(plot_ref._id, wid_id, fields)
        widget._push_fn = _tp_point
        self._widgets[widget.id] = widget
        if _push:
            self._push()
        return widget

    def get_widget(self, wid) -> Widget:
        """Return the Widget object by ID string or Widget instance."""
        if isinstance(wid, Widget):
            wid = wid.id
        try:
            return self._widgets[wid]
        except KeyError:
            raise KeyError(wid)

    def remove_widget(self, wid) -> None:
        """Remove a widget by ID string or Widget instance."""
        if isinstance(wid, Widget):
            wid = wid.id
        if wid not in self._widgets:
            raise KeyError(wid)
        del self._widgets[wid]
        self._push()

    def list_widgets(self) -> list:
        """Return a list of all active widget objects on this panel."""
        return list(self._widgets.values())

    def clear_widgets(self) -> None:
        """Remove all interactive overlay widgets from this panel."""
        self._widgets.clear()
        self._push()

    # ------------------------------------------------------------------
    # Callback API  (Plot1D)
    # ------------------------------------------------------------------
    def on_changed(self, fn: Callable) -> Callable:
        """Decorator: fires on every drag/zoom frame on this panel."""
        cid = self.callbacks.connect("on_changed", fn)
        fn._cid = cid
        return fn

    def on_release(self, fn: Callable) -> Callable:
        """Decorator: fires once when drag/zoom settles on this panel."""
        cid = self.callbacks.connect("on_release", fn)
        fn._cid = cid
        return fn

    def on_click(self, fn: Callable) -> Callable:
        """Decorator: fires on click on this panel."""
        cid = self.callbacks.connect("on_click", fn)
        fn._cid = cid
        return fn

    def on_key(self, key_or_fn=None) -> Callable:
        """Register a key-press handler for this panel.

        Two call forms are supported::

            @plot.on_key('q')          # fires only when 'q' is pressed
            def handler(event): ...

            @plot.on_key               # fires for every registered key
            def handler(event): ...

        The event carries: ``key``, ``mouse_x``, ``mouse_y``, ``phys_x``,
        and ``last_widget_id``.

        .. note::
            Registered keys take priority over the built-in **r** (reset view)
            shortcut.
        """
        if callable(key_or_fn):
            return self._connect_on_key(None, key_or_fn)
        key = key_or_fn
        def _decorator(fn):
            return self._connect_on_key(key, fn)
        return _decorator

    def _connect_on_key(self, key, fn) -> Callable:
        if key is None:
            if '*' not in self._state['registered_keys']:
                self._state['registered_keys'].append('*')
                self._push()
            cid = self.callbacks.connect("on_key", fn)
        else:
            if key not in self._state['registered_keys']:
                self._state['registered_keys'].append(key)
                self._push()
            def _wrapped(event):
                if event.data.get('key') == key:
                    fn(event)
            cid = self.callbacks.connect("on_key", _wrapped)
            _wrapped._cid = cid
        fn._cid = cid
        return fn

    def disconnect(self, cid: int) -> None:
        """Remove the callback registered under integer *cid*."""
        self.callbacks.disconnect(cid)

    def on_line_hover(self, fn: Callable) -> Callable:
        """Decorator: fires when the cursor moves over *any* line on this panel.

        The event carries ``event.line_id`` (``None`` = primary line,
        str = overlay), ``event.x``, and ``event.y`` in data coordinates.
        For per-line filtering use :meth:`Line1D.on_hover` instead.
        """
        cid = self.callbacks.connect("on_line_hover", fn)
        fn._cid = cid
        return fn

    def on_line_click(self, fn: Callable) -> Callable:
        """Decorator: fires when the user clicks *any* line on this panel.

        The event carries the same fields as :meth:`on_line_hover`.
        For per-line filtering use :meth:`Line1D.on_click` instead.
        """
        cid = self.callbacks.connect("on_line_click", fn)
        fn._cid = cid
        return fn

    # ------------------------------------------------------------------
    # View control
    # ------------------------------------------------------------------
    def set_view(self, x0: float | None = None, x1: float | None = None) -> None:
        """Programmatically set the visible x range.

        Parameters
        ----------
        x0 : float, optional
            Left edge of the view in data coordinates.  ``None`` keeps the
            current left edge.
        x1 : float, optional
            Right edge of the view in data coordinates.  ``None`` keeps the
            current right edge.
        """
        xarr = np.asarray(self._state["x_axis"])
        if len(xarr) < 2:
            return
        xmin, xmax = float(xarr[0]), float(xarr[-1])
        span = xmax - xmin or 1.0
        f0 = 0.0 if x0 is None else max(0.0, min(1.0, (float(x0)-xmin)/span))
        f1 = 1.0 if x1 is None else max(0.0, min(1.0, (float(x1)-xmin)/span))
        self._state["view_x0"] = f0
        self._state["view_x1"] = f1
        self._push()

    def reset_view(self) -> None:
        """Reset the view to show the full x range of the primary line."""
        self._state["view_x0"] = 0.0
        self._state["view_x1"] = 1.0
        self._push()

    # ------------------------------------------------------------------
    # Primary-line property setters
    # ------------------------------------------------------------------

    def set_color(self, color: str) -> None:
        """Set the primary line colour.

        Parameters
        ----------
        color : str
            Any CSS colour string (hex, ``rgb()``, named colour, etc.).
        """
        self._state["line_color"] = color
        self._push()

    def set_linewidth(self, linewidth: float) -> None:
        """Set the primary line stroke width.

        Parameters
        ----------
        linewidth : float
            Stroke width in pixels.
        """
        self._state["line_linewidth"] = float(linewidth)
        self._push()

    def set_linestyle(self, linestyle: str) -> None:
        """Set the primary line dash pattern.

        Parameters
        ----------
        linestyle : str
            ``"solid"`` (``"-"``), ``"dashed"`` (``"--"``),
            ``"dotted"`` (``":"``), or ``"dashdot"`` (``"-."``)
        """
        self._state["line_linestyle"] = _norm_linestyle(linestyle)
        self._push()

    def set_alpha(self, alpha: float) -> None:
        """Set the primary line opacity.

        Parameters
        ----------
        alpha : float
            Opacity in the range 0 (transparent) to 1 (fully opaque).
        """
        self._state["line_alpha"] = float(alpha)
        self._push()

    def set_marker(self, marker: str, markersize: float | None = None) -> None:
        """Set the primary line per-point marker symbol.

        Parameters
        ----------
        marker : str
            ``"o"``, ``"s"``, ``"^"``, ``"v"``, ``"D"``, ``"+"``,
            ``"x"``, or ``"none"``.
        markersize : float, optional
            Marker radius / half-side in pixels.  Unchanged if not supplied.
        """
        self._state["line_marker"] = marker if marker is not None else "none"
        if markersize is not None:
            self._state["line_markersize"] = float(markersize)
        self._push()

    # ------------------------------------------------------------------
    # Marker API  (matplotlib-style kwargs → MarkerRegistry)
    # ------------------------------------------------------------------
    def _add_marker(self, mtype: str, name: str | None, **kwargs) -> "MarkerGroup":  # noqa: F821
        return self.markers.add(mtype, name, **kwargs)

    def add_circles(self, offsets, name=None, *, radius=5,
                    facecolors=None, edgecolors="#ff0000",
                    linewidths=1.5, alpha=0.3,
                    hover_edgecolors=None, hover_facecolors=None,
                    labels=None, label=None) -> "MarkerGroup":  # noqa: F821
        """Add circle markers at explicit (x, y) positions.

        On 1-D panels circles are rendered as filled/stroked discs; *radius*
        is in canvas pixels (not data units).

        Parameters
        ----------
        offsets : array-like, shape (N, 2)
            Marker positions as ``[[x0, y0], [x1, y1], …]`` in data
            coordinates.
        name : str, optional
            Registry key.  Auto-generated if omitted.
        radius : float or array-like, optional
            Radius in pixels.  Scalar or per-marker array.  Default ``5``.
        facecolors : str or None, optional
            Fill colour.  ``None`` = no fill.
        edgecolors : str, optional
            Stroke colour.  Default ``"#ff0000"``.
        linewidths : float, optional
            Stroke width in pixels.  Default ``1.5``.
        alpha : float, optional
            Fill opacity (0–1).  Default ``0.3``.
        hover_edgecolors, hover_facecolors : str, optional
            Colour overrides applied on mouse-hover.
        labels : list of str, optional
            Per-marker tooltip labels.
        label : str, optional
            Collection-level tooltip label.

        Returns
        -------
        MarkerGroup
            Live group object.  Call ``.set(**kwargs)`` to update in place.
        """
        # On 1-D panels the native type is "points" (radius maps to sizes).
        return self._add_marker("points", name, offsets=offsets, sizes=radius,
                                facecolors=facecolors, edgecolors=edgecolors,
                                linewidths=linewidths, alpha=alpha,
                                hover_edgecolors=hover_edgecolors,
                                hover_facecolors=hover_facecolors,
                                labels=labels, label=label)

    def add_points(self, offsets, name=None, *, sizes=5,
                   color="#ff0000", facecolors=None,
                   linewidths=1.5, alpha=0.3,
                   hover_edgecolors=None, hover_facecolors=None,
                   labels=None, label=None) -> "MarkerGroup":  # noqa: F821
        """Add point markers at (x, y) positions in data coordinates.

        Parameters
        ----------
        offsets : array-like, shape (N, 2)
            Marker positions as ``[[x0, y0], [x1, y1], …]``.
        name : str, optional
            Registry key.  Auto-generated if omitted.
        sizes : float or array-like, optional
            Radius in pixels.  Scalar or per-marker array.  Default ``5``.
        color : str, optional
            Stroke colour.  Default ``"#ff0000"``.
        facecolors : str or None, optional
            Fill colour.  ``None`` = no fill.
        linewidths : float, optional
            Stroke width in pixels.  Default ``1.5``.
        alpha : float, optional
            Fill opacity (0–1).  Default ``0.3``.
        hover_edgecolors, hover_facecolors : str, optional
            Colour overrides applied on mouse-hover.
        labels : list of str, optional
            Per-marker tooltip labels.
        label : str, optional
            Collection-level tooltip label.

        Returns
        -------
        MarkerGroup
        """
        return self._add_marker("points", name, offsets=offsets, sizes=sizes,
                                edgecolors=color, facecolors=facecolors,
                                linewidths=linewidths, alpha=alpha,
                                hover_edgecolors=hover_edgecolors,
                                hover_facecolors=hover_facecolors,
                                labels=labels, label=label)

    def add_hlines(self, y_values, name=None, *,
                   color="#ff0000", linewidths=1.5,
                   hover_edgecolors=None,
                   labels=None, label=None) -> "MarkerGroup":  # noqa: F821
        """Add static horizontal lines spanning the full x range.

        Parameters
        ----------
        y_values : array-like, shape (N,)
            Y positions of each line in data coordinates.
        name : str, optional
            Registry key.  Auto-generated if omitted.
        color : str, optional
            Line colour.  Default ``"#ff0000"``.
        linewidths : float, optional
            Stroke width in pixels.  Default ``1.5``.
        hover_edgecolors : str, optional
            Colour override applied on mouse-hover.
        labels : list of str, optional
            Per-line tooltip labels.
        label : str, optional
            Collection-level tooltip label.

        Returns
        -------
        MarkerGroup
        """
        return self._add_marker("hlines", name, offsets=y_values,
                                color=color, linewidths=linewidths,
                                hover_edgecolors=hover_edgecolors,
                                labels=labels, label=label)

    def add_vlines(self, x_values, name=None, *,
                   color="#ff0000", linewidths=1.5,
                   hover_edgecolors=None,
                   labels=None, label=None) -> "MarkerGroup":  # noqa: F821
        """Add static vertical lines spanning the full y range.

        Parameters
        ----------
        x_values : array-like, shape (N,)
            X positions of each line in data coordinates.
        name : str, optional
            Registry key.  Auto-generated if omitted.
        color : str, optional
            Line colour.  Default ``"#ff0000"``.
        linewidths : float, optional
            Stroke width in pixels.  Default ``1.5``.
        hover_edgecolors : str, optional
            Colour override applied on mouse-hover.
        labels : list of str, optional
            Per-line tooltip labels.
        label : str, optional
            Collection-level tooltip label.

        Returns
        -------
        MarkerGroup
        """
        return self._add_marker("vlines", name, offsets=x_values,
                                color=color, linewidths=linewidths,
                                hover_edgecolors=hover_edgecolors,
                                labels=labels, label=label)

    def add_arrows(self, offsets, U, V, name=None, *,
                   edgecolors="#ff0000", linewidths=1.5,
                   hover_edgecolors=None,
                   labels=None, label=None) -> "MarkerGroup":  # noqa: F821
        """Add arrow markers at explicit (x, y) positions.

        Parameters
        ----------
        offsets : array-like, shape (N, 2)
            Arrow tail positions as ``[[x0, y0], …]`` in data coordinates.
        U, V : array-like, shape (N,)
            X and Y components of each arrow vector (in data units).
        name : str, optional
            Registry key.  Auto-generated if omitted.
        edgecolors : str, optional
            Arrow colour.  Default ``"#ff0000"``.
        linewidths : float, optional
            Stroke width in pixels.  Default ``1.5``.
        hover_edgecolors : str, optional
            Colour override applied on mouse-hover.
        labels : list of str, optional
            Per-arrow tooltip labels.
        label : str, optional
            Collection-level tooltip label.

        Returns
        -------
        MarkerGroup
        """
        return self._add_marker("arrows", name, offsets=offsets, U=U, V=V,
                                edgecolors=edgecolors, linewidths=linewidths,
                                hover_edgecolors=hover_edgecolors,
                                labels=labels, label=label)

    def add_ellipses(self, offsets, widths, heights, name=None, *,
                     angles=0, facecolors=None, edgecolors="#ff0000",
                     linewidths=1.5, alpha=0.3,
                     hover_edgecolors=None, hover_facecolors=None,
                     labels=None, label=None) -> "MarkerGroup":  # noqa: F821
        """Add ellipse markers at explicit (x, y) positions.

        Parameters
        ----------
        offsets : array-like, shape (N, 2)
            Centre positions in data coordinates.
        widths, heights : float or array-like
            Full width and height of each ellipse in canvas pixels.
        name : str, optional
            Registry key.  Auto-generated if omitted.
        angles : float or array-like, optional
            Rotation angle(s) in degrees.  Default ``0``.
        facecolors : str or None, optional
            Fill colour.  ``None`` = no fill.
        edgecolors : str, optional
            Stroke colour.  Default ``"#ff0000"``.
        linewidths : float, optional
            Stroke width in pixels.  Default ``1.5``.
        alpha : float, optional
            Fill opacity (0–1).  Default ``0.3``.
        hover_edgecolors, hover_facecolors : str, optional
            Colour overrides applied on mouse-hover.
        labels : list of str, optional
            Per-marker tooltip labels.
        label : str, optional
            Collection-level tooltip label.

        Returns
        -------
        MarkerGroup
        """
        return self._add_marker("ellipses", name, offsets=offsets,
                                widths=widths, heights=heights, angles=angles,
                                facecolors=facecolors, edgecolors=edgecolors,
                                linewidths=linewidths, alpha=alpha,
                                hover_edgecolors=hover_edgecolors,
                                hover_facecolors=hover_facecolors,
                                labels=labels, label=label)

    def add_lines(self, segments, name=None, *,
                  edgecolors="#ff0000", linewidths=1.5,
                  hover_edgecolors=None,
                  labels=None, label=None) -> "MarkerGroup":  # noqa: F821
        """Add line-segment markers (static, not draggable).

        Parameters
        ----------
        segments : array-like, shape (N, 2, 2)
            Each segment is ``[[x0, y0], [x1, y1]]`` in data coordinates.
        name : str, optional
            Registry key.  Auto-generated if omitted.
        edgecolors : str, optional
            Line colour.  Default ``"#ff0000"``.
        linewidths : float, optional
            Stroke width in pixels.  Default ``1.5``.
        hover_edgecolors : str, optional
            Colour override applied on mouse-hover.
        labels : list of str, optional
            Per-segment tooltip labels.
        label : str, optional
            Collection-level tooltip label.

        Returns
        -------
        MarkerGroup
        """
        return self._add_marker("lines", name, segments=segments,
                                edgecolors=edgecolors, linewidths=linewidths,
                                hover_edgecolors=hover_edgecolors,
                                labels=labels, label=label)

    def add_rectangles(self, offsets, widths, heights, name=None, *,
                       angles=0, facecolors=None, edgecolors="#ff0000",
                       linewidths=1.5, alpha=0.3,
                       hover_edgecolors=None, hover_facecolors=None,
                       labels=None, label=None) -> "MarkerGroup":  # noqa: F821
        """Add rectangle markers at explicit (x, y) positions.

        Parameters
        ----------
        offsets : array-like, shape (N, 2)
            Centre positions in data coordinates.
        widths, heights : float or array-like
            Full width and height of each rectangle in canvas pixels.
        name : str, optional
            Registry key.  Auto-generated if omitted.
        angles : float or array-like, optional
            Rotation angle(s) in degrees.  Default ``0``.
        facecolors : str or None, optional
            Fill colour.  ``None`` = no fill.
        edgecolors : str, optional
            Stroke colour.  Default ``"#ff0000"``.
        linewidths : float, optional
            Stroke width in pixels.  Default ``1.5``.
        alpha : float, optional
            Fill opacity (0–1).  Default ``0.3``.
        hover_edgecolors, hover_facecolors : str, optional
            Colour overrides applied on mouse-hover.
        labels : list of str, optional
            Per-marker tooltip labels.
        label : str, optional
            Collection-level tooltip label.

        Returns
        -------
        MarkerGroup
        """
        return self._add_marker("rectangles", name, offsets=offsets,
                                widths=widths, heights=heights, angles=angles,
                                facecolors=facecolors, edgecolors=edgecolors,
                                linewidths=linewidths, alpha=alpha,
                                hover_edgecolors=hover_edgecolors,
                                hover_facecolors=hover_facecolors,
                                labels=labels, label=label)

    def add_squares(self, offsets, widths, name=None, *,
                    angles=0, facecolors=None, edgecolors="#ff0000",
                    linewidths=1.5, alpha=0.3,
                    hover_edgecolors=None, hover_facecolors=None,
                    labels=None, label=None) -> "MarkerGroup":  # noqa: F821
        """Add square markers at explicit (x, y) positions.

        Parameters
        ----------
        offsets : array-like, shape (N, 2)
            Centre positions in data coordinates.
        widths : float or array-like
            Side length of each square in canvas pixels.
        name : str, optional
            Registry key.  Auto-generated if omitted.
        angles : float or array-like, optional
            Rotation angle(s) in degrees.  Default ``0``.
        facecolors : str or None, optional
            Fill colour.  ``None`` = no fill.
        edgecolors : str, optional
            Stroke colour.  Default ``"#ff0000"``.
        linewidths : float, optional
            Stroke width in pixels.  Default ``1.5``.
        alpha : float, optional
            Fill opacity (0–1).  Default ``0.3``.
        hover_edgecolors, hover_facecolors : str, optional
            Colour overrides applied on mouse-hover.
        labels : list of str, optional
            Per-marker tooltip labels.
        label : str, optional
            Collection-level tooltip label.

        Returns
        -------
        MarkerGroup
        """
        return self._add_marker("squares", name, offsets=offsets,
                                widths=widths, angles=angles,
                                facecolors=facecolors, edgecolors=edgecolors,
                                linewidths=linewidths, alpha=alpha,
                                hover_edgecolors=hover_edgecolors,
                                hover_facecolors=hover_facecolors,
                                labels=labels, label=label)

    def add_polygons(self, vertices_list, name=None, *,
                     facecolors=None, edgecolors="#ff0000",
                     linewidths=1.5, alpha=0.3,
                     hover_edgecolors=None, hover_facecolors=None,
                     labels=None, label=None) -> "MarkerGroup":  # noqa: F821
        """Add polygon markers defined by explicit vertex lists.

        Parameters
        ----------
        vertices_list : list of array-like, each shape (K, 2)
            One polygon per element; each is a list of ``[x, y]`` vertices
            in data coordinates.
        name : str, optional
            Registry key.  Auto-generated if omitted.
        facecolors : str or None, optional
            Fill colour.  ``None`` = no fill.
        edgecolors : str, optional
            Stroke colour.  Default ``"#ff0000"``.
        linewidths : float, optional
            Stroke width in pixels.  Default ``1.5``.
        alpha : float, optional
            Fill opacity (0–1).  Default ``0.3``.
        hover_edgecolors, hover_facecolors : str, optional
            Colour overrides applied on mouse-hover.
        labels : list of str, optional
            Per-polygon tooltip labels.
        label : str, optional
            Collection-level tooltip label.

        Returns
        -------
        MarkerGroup
        """
        return self._add_marker("polygons", name, vertices_list=vertices_list,
                                facecolors=facecolors, edgecolors=edgecolors,
                                linewidths=linewidths, alpha=alpha,
                                hover_edgecolors=hover_edgecolors,
                                hover_facecolors=hover_facecolors,
                                labels=labels, label=label)

    def add_texts(self, offsets, texts, name=None, *,
                  color="#ff0000", fontsize=12,
                  hover_edgecolors=None,
                  labels=None, label=None) -> "MarkerGroup":  # noqa: F821
        """Add text annotations at explicit (x, y) positions.

        Parameters
        ----------
        offsets : array-like, shape (N, 2)
            Anchor positions in data coordinates.
        texts : list of str
            One string per position.
        name : str, optional
            Registry key.  Auto-generated if omitted.
        color : str, optional
            Text colour.  Default ``"#ff0000"``.
        fontsize : int, optional
            Font size in pixels.  Default ``12``.
        hover_edgecolors : str, optional
            Colour override applied on mouse-hover.
        labels : list of str, optional
            Per-annotation tooltip labels.
        label : str, optional
            Collection-level tooltip label.

        Returns
        -------
        MarkerGroup
        """
        return self._add_marker("texts", name, offsets=offsets, texts=texts,
                                color=color, fontsize=fontsize,
                                hover_edgecolors=hover_edgecolors,
                                labels=labels, label=label)

    def remove_marker(self, marker_type: str, name: str) -> None:
        """Remove a named marker collection by type and name.

        Parameters
        ----------
        marker_type : str
            Collection type, e.g. ``"points"``, ``"vlines"``.
        name : str
            The name used when the collection was created.
        """
        self.markers.remove(marker_type, name)

    def clear_markers(self) -> None:
        """Remove all marker collections from this panel."""
        self.markers.clear()

    def list_markers(self) -> list:
        """Return a summary list of all marker collections on this panel.

        Returns
        -------
        list of dict
            Each dict has keys ``"type"``, ``"name"``, and ``"n"``
            (number of markers in the collection).
        """
        out = []
        for mtype, td in self.markers._types.items():
            for name, g in td.items():
                out.append({"type": mtype, "name": name, "n": g._count()})
        return out

    def __repr__(self) -> str:
        n = len(self._state.get("data", []))
        color = self._state.get("line_color", "?")
        return f"Plot1D(n={n}, color={color!r})"


# ---------------------------------------------------------------------------
# _bar_x_axis helper
# ---------------------------------------------------------------------------

def _bar_x_axis(x_centers: np.ndarray) -> list:
    """Return a 2-element [x_left_edge, x_right_edge] list for a bar chart.

    The edges are half a slot-width outside the first/last bar centre so that
    a vline_widget at ``x_centers[i]`` renders at exactly the bar's centre
    pixel when used with ``_xToFrac1d`` / ``_fracToPx1d`` in the JS renderer.
    """
    n = len(x_centers)
    if n == 0:
        return [0.0, 1.0]
    if n == 1:
        return [float(x_centers[0]) - 0.5, float(x_centers[0]) + 0.5]
    slot = (float(x_centers[-1]) - float(x_centers[0])) / (n - 1)
    half = slot / 2.0
    return [float(x_centers[0]) - half, float(x_centers[-1]) + half]


# ---------------------------------------------------------------------------
# PlotBar
# ---------------------------------------------------------------------------

_LOG_CLAMP = 1e-10  # smallest positive value used when log_scale=True

_DEFAULT_GROUP_PALETTE = [
    "#4fc3f7", "#ff7043", "#66bb6a", "#ab47bc",
    "#ffa726", "#26c6da", "#ec407a", "#8d6e63",
]


def _bar_range(flat: np.ndarray, bottom: float, log_scale: bool):
    """Return ``(dmin, dmax)`` with padding for the value axis."""
    if log_scale:
        pos = flat[flat > 0]
        dmin = float(np.nanmin(pos)) if len(pos) else _LOG_CLAMP
        dmax = max(float(np.nanmax(flat)) if len(flat) else 1.0,
                   bottom if bottom > 0 else _LOG_CLAMP)
        if dmin <= 0:
            dmin = _LOG_CLAMP
        if dmax <= 0:
            dmax = 1.0
        dmax = 10 ** (np.log10(dmax) + 0.15)
        dmin = 10 ** (np.log10(dmin) - 0.15)
    else:
        dmin = min(bottom, float(np.nanmin(flat)) if len(flat) else 0.0)
        dmax = max(bottom, float(np.nanmax(flat)) if len(flat) else 1.0)
        pad = (dmax - dmin) * 0.07 if dmax > dmin else 0.5
        dmax += pad
        if dmin < bottom:
            dmin -= pad
    return dmin, dmax


class PlotBar:
    """Bar-chart plot panel.

    Not an anywidget.  Holds state in ``_state`` dict; every mutation calls
    ``_push()`` which writes to the parent Figure's panel trait.

    Supports grouped bars (pass a 2-D *height* array with shape ``(N, G)``),
    log-scale value axis, draggable overlay widgets, and hover/click callbacks.

    Created by :meth:`Axes.bar`.
    """

    def __init__(self, x, height=None, width: float = 0.8, bottom: float = 0.0, *,
                 align: str = "center",
                 color: str = "#4fc3f7",
                 colors=None,
                 orient: str = "v",
                 log_scale: bool = False,
                 group_labels=None,
                 group_colors=None,
                 show_values: bool = False,
                 units: str = "",
                 y_units: str = "",
                 # ── legacy backward-compat kwargs ──────────────────────
                 x_labels=None,
                 x_centers=None,
                 bar_width=None,
                 baseline=None,
                 values=None):
        self._id:  str = ""
        self._fig: object = None

        # ── legacy resolution ──────────────────────────────────────────
        if height is None:
            if values is not None:
                height = values
            else:
                height = x
                x = None
        if baseline is not None:
            bottom = baseline
        if bar_width is not None:
            width = bar_width

        # ── height (values) — 1-D or 2-D for grouped bars ─────────────
        height_arr = np.asarray(height, dtype=float)
        if height_arr.ndim == 1:
            groups = 1
            values_2d = height_arr.reshape(-1, 1)
        elif height_arr.ndim == 2:
            groups = height_arr.shape[1]
            values_2d = height_arr
        else:
            raise ValueError(
                f"height must be 1-D or 2-D, got shape {height_arr.shape}"
            )
        n = values_2d.shape[0]

        if orient not in ("v", "h"):
            raise ValueError("orient must be 'v' or 'h'")

        # ── x (positions or labels) ────────────────────────────────────
        _x_labels: list = []
        _x_centers: np.ndarray | None = None

        if x is not None:
            x_list = list(x)
            if x_list and isinstance(x_list[0], str):
                _x_labels = x_list
            else:
                _x_centers = np.asarray(x, dtype=float)

        # Legacy keyword overrides
        if x_labels is not None:
            _x_labels = list(x_labels)
        if x_centers is not None:
            _x_centers = np.asarray(x_centers, dtype=float)

        if _x_centers is None:
            _x_centers = np.arange(n, dtype=float)
        if len(_x_centers) != n:
            raise ValueError("x length must match height length")

        # ── data range ─────────────────────────────────────────────────
        flat = values_2d.ravel()
        dmin, dmax = _bar_range(flat, float(bottom), bool(log_scale))

        # ── group colours ──────────────────────────────────────────────
        if group_colors is None:
            gc_list = (
                [_DEFAULT_GROUP_PALETTE[i % len(_DEFAULT_GROUP_PALETTE)]
                 for i in range(groups)]
                if groups > 1 else []
            )
        else:
            gc_list = list(group_colors)

        x_axis = _bar_x_axis(_x_centers)

        self._state: dict = {
            "kind":          "bar",
            "values":        values_2d.tolist(),   # always (N, G) 2-D list
            "groups":        groups,
            "x_centers":     _x_centers.tolist(),
            "x_labels":      _x_labels,
            "bar_color":     color,
            "bar_colors":    list(colors) if colors is not None else [],
            "group_labels":  list(group_labels) if group_labels is not None else [],
            "group_colors":  gc_list,
            "bar_width":     float(width),
            "orient":        orient,
            "baseline":      float(bottom),
            "log_scale":     bool(log_scale),
            "show_values":   bool(show_values),
            "data_min":      dmin,
            "data_max":      dmax,
            "units":         units,
            "y_units":       y_units,
            # overlay-widget coordinate system (mirrors Plot1D)
            "x_axis":        x_axis,
            "view_x0":       0.0,
            "view_x1":       1.0,
            "overlay_widgets": [],
            "registered_keys": [],
        }
        self.callbacks = CallbackRegistry()
        self._widgets: dict[str, Widget] = {}

    # ------------------------------------------------------------------
    def _push(self) -> None:
        if self._fig is None:
            return
        self._state["overlay_widgets"] = [w.to_dict() for w in self._widgets.values()]
        self._fig._push(self._id)

    def to_state_dict(self) -> dict:
        d = dict(self._state)
        d["overlay_widgets"] = [w.to_dict() for w in self._widgets.values()]
        return d

    # ------------------------------------------------------------------
    # Data
    # ------------------------------------------------------------------
    def set_data(self, height, x=None, x_labels=None, *, x_centers=None) -> None:
        """Replace bar heights; recalculates the value-axis range automatically.

        Parameters
        ----------
        height : array-like, shape ``(N,)`` or ``(N, G)``
            New bar heights.  For grouped charts the group count *G* must
            match the original.
        x : array-like of numeric, optional
            New bar positions (replaces the stored ``x_centers``).  Also
            accepts the legacy keyword alias ``x_centers``.
        x_labels : list of str, optional
            New category labels.
        """
        height_arr = np.asarray(height, dtype=float)
        if height_arr.ndim == 1:
            values_2d = height_arr.reshape(-1, 1)
        elif height_arr.ndim == 2:
            expected_g = self._state.get("groups", 1)
            if height_arr.shape[1] != expected_g:
                raise ValueError(
                    f"Group count mismatch: expected {expected_g}, "
                    f"got {height_arr.shape[1]}"
                )
            values_2d = height_arr
        else:
            raise ValueError(
                f"height must be 1-D or 2-D, got shape {height_arr.shape}"
            )

        flat = values_2d.ravel()
        baseline = self._state["baseline"]
        log_scale = self._state.get("log_scale", False)
        dmin, dmax = _bar_range(flat, float(baseline), bool(log_scale))

        self._state["values"]   = values_2d.tolist()
        self._state["data_min"] = dmin
        self._state["data_max"] = dmax

        # Accept both `x` and legacy `x_centers` keyword
        _x = x if x is not None else x_centers
        if _x is not None:
            xc = np.asarray(_x, dtype=float)
            self._state["x_centers"] = xc.tolist()
            self._state["x_axis"]    = _bar_x_axis(xc)
        if x_labels is not None:
            self._state["x_labels"] = list(x_labels)
        self._push()

    # ------------------------------------------------------------------
    # Display settings
    # ------------------------------------------------------------------
    def set_color(self, color: str) -> None:
        """Set a single colour for all bars."""
        self._state["bar_color"] = color
        self._push()

    def set_colors(self, colors) -> None:
        """Set per-bar colours (list of CSS colour strings, length N)."""
        self._state["bar_colors"] = list(colors)
        self._push()

    def set_show_values(self, show: bool) -> None:
        """Show or hide in-bar value annotations."""
        self._state["show_values"] = bool(show)
        self._push()

    def set_log_scale(self, log_scale: bool) -> None:
        """Enable or disable a logarithmic value axis.

        When *log_scale* is ``True`` any non-positive values are clamped to
        ``1e-10`` for display; the data-range bounds are recalculated in
        log-space automatically.
        """
        self._state["log_scale"] = bool(log_scale)
        flat = np.asarray(self._state["values"]).ravel()
        baseline = self._state["baseline"]
        dmin, dmax = _bar_range(flat, float(baseline), bool(log_scale))
        self._state["data_min"] = dmin
        self._state["data_max"] = dmax
        self._push()

    # ------------------------------------------------------------------
    # Overlay Widgets
    # ------------------------------------------------------------------
    def add_vline_widget(self, x: float, color: str = "#00e5ff") -> _VLineWidget:
        """Add a draggable vertical line at data position *x*."""
        widget = _VLineWidget(lambda: None, x=float(x), color=color)
        plot_ref, wid_id = self, widget._id
        def _tp():
            if plot_ref._fig is not None:
                fields = {k: v for k, v in widget._data.items() if k not in ("id", "type")}
                plot_ref._fig._push_widget(plot_ref._id, wid_id, fields)
        widget._push_fn = _tp
        self._widgets[widget.id] = widget
        self._push()
        return widget

    def add_hline_widget(self, y: float, color: str = "#00e5ff") -> _HLineWidget:
        """Add a draggable horizontal line at value-axis position *y*."""
        widget = _HLineWidget(lambda: None, y=float(y), color=color)
        plot_ref, wid_id = self, widget._id
        def _tp():
            if plot_ref._fig is not None:
                fields = {k: v for k, v in widget._data.items() if k not in ("id", "type")}
                plot_ref._fig._push_widget(plot_ref._id, wid_id, fields)
        widget._push_fn = _tp
        self._widgets[widget.id] = widget
        self._push()
        return widget

    def add_range_widget(self, x0: float, x1: float,
                         color: str = "#00e5ff",
                         style: str = "band",
                         y: float = 0.0,
                         _push: bool = True) -> _RangeWidget:
        """Add a draggable range overlay. See :meth:`Plot1D.add_range_widget` for full docs."""
        widget = _RangeWidget(lambda: None, x0=float(x0), x1=float(x1),
                              color=color, style=style, y=float(y))
        plot_ref, wid_id = self, widget._id
        def _tp():
            if plot_ref._fig is not None:
                fields = {k: v for k, v in widget._data.items() if k not in ("id", "type")}
                plot_ref._fig._push_widget(plot_ref._id, wid_id, fields)
        widget._push_fn = _tp
        self._widgets[widget.id] = widget
        if _push:
            self._push()
        return widget

    def add_point_widget(self, x: float, y: float,
                         color: str = "#00e5ff",
                         show_crosshair: bool = True,
                         _push: bool = True) -> _PointWidget:
        """Add a freely-draggable control point to this panel."""
        widget = _PointWidget(lambda: None, x=float(x), y=float(y), color=color,
                              show_crosshair=show_crosshair)
        plot_ref, wid_id = self, widget._id
        def _tp():
            if plot_ref._fig is not None:
                fields = {k: v for k, v in widget._data.items() if k not in ("id", "type")}
                plot_ref._fig._push_widget(plot_ref._id, wid_id, fields)
        widget._push_fn = _tp
        self._widgets[widget.id] = widget
        if _push:
            self._push()
        return widget

    def get_widget(self, wid) -> Widget:
        """Return the Widget object by ID string or Widget instance."""
        if isinstance(wid, Widget):
            wid = wid.id
        try:
            return self._widgets[wid]
        except KeyError:
            raise KeyError(wid)

    def remove_widget(self, wid) -> None:
        """Remove a widget by ID string or Widget instance."""
        if isinstance(wid, Widget):
            wid = wid.id
        if wid not in self._widgets:
            raise KeyError(wid)
        del self._widgets[wid]
        self._push()

    def list_widgets(self) -> list:
        return list(self._widgets.values())

    def clear_widgets(self) -> None:
        self._widgets.clear()
        self._push()

    # ------------------------------------------------------------------
    # Callbacks
    # ------------------------------------------------------------------
    def on_click(self, fn: Callable) -> Callable:
        """Decorator: fires when the user clicks a bar.

        The :class:`~anyplotlib.callbacks.Event` has ``bar_index``,
        ``value``, ``x_center``, and ``x_label``.
        """
        cid = self.callbacks.connect("on_click", fn)
        fn._cid = cid
        return fn

    def on_changed(self, fn: Callable) -> Callable:
        """Decorator: fires on every drag frame (widget drag or hover)."""
        cid = self.callbacks.connect("on_changed", fn)
        fn._cid = cid
        return fn

    def on_release(self, fn: Callable) -> Callable:
        """Decorator: fires once when a widget drag settles."""
        cid = self.callbacks.connect("on_release", fn)
        fn._cid = cid
        return fn

    def on_key(self, key_or_fn=None) -> Callable:
        """Register a key-press handler for this panel.

        Two call forms are supported::

            @plot.on_key('q')          # fires only when 'q' is pressed
            def handler(event): ...

            @plot.on_key               # fires for every registered key
            def handler(event): ...

        The event carries: ``key``, ``mouse_x``, ``mouse_y``, and
        ``last_widget_id``.
        """
        if callable(key_or_fn):
            return self._connect_on_key(None, key_or_fn)
        key = key_or_fn
        def _decorator(fn):
            return self._connect_on_key(key, fn)
        return _decorator

    def _connect_on_key(self, key, fn) -> Callable:
        if key is None:
            if '*' not in self._state['registered_keys']:
                self._state['registered_keys'].append('*')
                self._push()
            cid = self.callbacks.connect("on_key", fn)
        else:
            if key not in self._state['registered_keys']:
                self._state['registered_keys'].append(key)
                self._push()
            def _wrapped(event):
                if event.data.get('key') == key:
                    fn(event)
            cid = self.callbacks.connect("on_key", _wrapped)
            _wrapped._cid = cid
        fn._cid = cid
        return fn

    def disconnect(self, cid: int) -> None:
        self.callbacks.disconnect(cid)

    def __repr__(self) -> str:
        n = len(self._state.get("values", []))
        orient = self._state.get("orient", "v")
        groups = self._state.get("groups", 1)
        if groups > 1:
            return f"PlotBar(n={n}, groups={groups}, orient={orient!r})"
        return f"PlotBar(n={n}, orient={orient!r})"


# ---------------------------------------------------------------------------
# _plot_kind — shared kind string for both layout serialisation and InsetAxes
# ---------------------------------------------------------------------------

def _plot_kind(plot) -> str:
    """Return the JS panel-kind string for a plot object.

    Used in ``Figure._push_layout()`` and ``InsetAxes.__repr__``.
    """
    if isinstance(plot, Plot3D):
        return "3d"
    if isinstance(plot, (Plot2D, PlotMesh)):
        return "2d"
    if isinstance(plot, PlotBar):
        return "bar"
    return "1d"


# ---------------------------------------------------------------------------
# InsetAxes — floating overlay sub-plot
# ---------------------------------------------------------------------------

_VALID_CORNERS = ("top-right", "top-left", "bottom-right", "bottom-left")


class InsetAxes(Axes):
    """A floating inset sub-plot that overlays the main Figure grid.

    Created via :meth:`Figure.add_inset`.  Supports the same plot-factory
    methods as :class:`Axes` (``imshow``, ``plot``, ``pcolormesh``, etc.).

    The inset is positioned at a corner of the figure and can be minimized
    (title bar only), maximized (expanded to fill ~72% of the figure), or
    restored to its normal size.

    Parameters
    ----------
    fig : Figure
    w_frac, h_frac : float
        Width and height as fractions of the figure dimensions (0–1).
    corner : str, optional
        One of ``"top-right"``, ``"top-left"``, ``"bottom-right"``,
        ``"bottom-left"``.  Default ``"top-right"``.
    title : str, optional
        Text shown in the inset title bar.  Default ``""``.

    Examples
    --------
    >>> fig, ax = apl.subplots(1, 1, figsize=(640, 480))
    >>> ax.imshow(data)
    >>> inset = fig.add_inset(0.3, 0.25, corner="top-right", title="Zoom")
    >>> inset.imshow(data[64:128, 64:128])
    """

    def __init__(self, fig, w_frac: float, h_frac: float, *,
                 corner: str = "top-right", title: str = ""):
        if corner not in _VALID_CORNERS:
            raise ValueError(
                f"corner must be one of {_VALID_CORNERS!r}, got {corner!r}"
            )
        # Pass a dummy SubplotSpec so Axes.__init__ doesn't fail — InsetAxes
        # never occupies a grid cell, only overlays the figure.
        super().__init__(fig, SubplotSpec(None, 0, 1, 0, 1))
        self.w_frac = w_frac
        self.h_frac = h_frac
        self.corner = corner
        self.title  = title
        self._inset_state: str = "normal"

    # ── state API ─────────────────────────────────────────────────────────

    @property
    def inset_state(self) -> str:
        """Current state: ``"normal"``, ``"minimized"``, or ``"maximized"``."""
        return self._inset_state

    def minimize(self) -> None:
        """Collapse the inset to its title bar only (idempotent)."""
        if self._inset_state == "minimized":
            return
        self._inset_state = "minimized"
        self._fig._push_layout()

    def maximize(self) -> None:
        """Expand the inset to ~72 % of the figure, centred (idempotent)."""
        if self._inset_state == "maximized":
            return
        self._inset_state = "maximized"
        self._fig._push_layout()

    def restore(self) -> None:
        """Return the inset to its normal corner position (idempotent)."""
        if self._inset_state == "normal":
            return
        self._inset_state = "normal"
        self._fig._push_layout()

    # ── internal ──────────────────────────────────────────────────────────

    def _attach(self, plot) -> None:
        """Register the plot on this inset via Figure._register_inset."""
        if self._plot is not None:
            panel_id = self._plot._id
        else:
            panel_id = str(_uuid.uuid4())[:8]
        plot._id  = panel_id
        plot._fig = self._fig
        self._plot = plot
        self._fig._register_inset(self, plot)

    def __repr__(self) -> str:
        kind = _plot_kind(self._plot) if self._plot else "empty"
        return (
            f"InsetAxes(corner={self.corner!r}, "
            f"size=({self.w_frac:.2f}, {self.h_frac:.2f}), "
            f"state={self._inset_state!r}, kind={kind!r})"
        )






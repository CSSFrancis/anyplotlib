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
)

__all__ = ["GridSpec", "SubplotSpec", "Axes", "Plot1D", "Plot2D", "PlotMesh", "Plot3D",
           "PlotBar", "_resample_mesh"]


# ---------------------------------------------------------------------------
# GridSpec / SubplotSpec
# ---------------------------------------------------------------------------

class SubplotSpec:
    """Describes which grid cells a subplot occupies.
    
    Parameters
    ----------
    gs : GridSpec
        Parent GridSpec instance.
    row_start : int
        Starting row index (0-based).
    row_stop : int
        Ending row index (exclusive).
    col_start : int
        Starting column index (0-based).
    col_stop : int
        Ending column index (exclusive).
    """

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

    Represents a single subplot cell within a grid layout. Use plotting methods
    like :meth:`imshow`, :meth:`plot`, :meth:`bar`, etc. to attach visualization
    to this axes.

    Returned by :func:`Figure.add_subplot` and :func:`Figure.subplots`.

    Parameters
    ----------
    fig : Figure
        Parent Figure instance.
    spec : SubplotSpec
        Layout specification (row/column spans).

    Notes
    -----
    Each Axes can hold at most one plot object at a time. Calling another plot
    method replaces the previous one.
    """

    def __init__(self, fig: "Figure", spec: SubplotSpec):  # noqa: F821
        self._fig  = fig
        self._spec = spec
        self._plot: "Plot1D | Plot2D | None" = None

    # ------------------------------------------------------------------
    def imshow(self, data: np.ndarray,
               axes: list | None = None,
               units: str = "px") -> "Plot2D":
        """Attach a 2-D image to this axes cell.

        Parameters
        ----------
        data : np.ndarray  shape (H, W) or (H, W, C)
        axes : [x_axis, y_axis], optional
        units : str, optional

        Returns
        -------
        Plot2D
        """
        x_axis = axes[0] if axes and len(axes) > 0 else None
        y_axis = axes[1] if axes and len(axes) > 1 else None
        plot = Plot2D(data, x_axis=x_axis, y_axis=y_axis, units=units)
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
             label: str = "") -> "Plot1D":
        """Attach a 1-D line to this axes cell.

        Parameters
        ----------
        data : np.ndarray  shape (N,)
        axes : [x_axis], optional
        units : str, optional
        y_units : str, optional
        color : str, optional
        linewidth : float, optional
        label : str, optional

        Returns
        -------
        Plot1D
        """
        x_axis = axes[0] if axes and len(axes) > 0 else None
        plot = Plot1D(data, x_axis=x_axis, units=units, y_units=y_units,
                     color=color, linewidth=linewidth, label=label)
        self._attach(plot)
        return plot

    def bar(self, values,
            x_labels=None,
            x_centers=None,
            color: str = "#4fc3f7",
            colors=None,
            bar_width: float = 0.7,
            orient: str = "v",
            baseline: float = 0.0,
            show_values: bool = False,
            units: str = "",
            y_units: str = "") -> "PlotBar":
        """Attach a bar chart to this axes cell.

        Parameters
        ----------
        values : array-like, shape (N,)
            Bar heights (vertical) or widths (horizontal).
        x_labels : list of str, optional
            Category labels for each bar.  Shown on the categorical axis
            instead of numeric tick values.
        x_centers : array-like, optional
            Numeric positions of bar centres.  Defaults to ``0, 1, … N-1``.
        color : str, optional
            Single CSS colour applied to every bar.  Default ``"#4fc3f7"``.
        colors : list of str, optional
            Per-bar colour list; overrides *color* where provided.
        bar_width : float, optional
            Bar width as a fraction of the slot width (0–1).  Default ``0.7``.
        orient : ``"v"`` | ``"h"``, optional
            Vertical (default) or horizontal orientation.
        baseline : float, optional
            Value at which bars are rooted.  Default ``0``.
        show_values : bool, optional
            Draw the numeric value above / beside each bar.
        units : str, optional
            Label for the categorical axis.
        y_units : str, optional
            Label for the value axis.

        Returns
        -------
        PlotBar
        """
        plot = PlotBar(values, x_labels=x_labels, x_centers=x_centers,
                       color=color, colors=colors, bar_width=bar_width,
                       orient=orient, baseline=baseline, show_values=show_values,
                       units=units, y_units=y_units)
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

    Not an anywidget. Holds state in ``_state`` dict; every mutation calls
    ``_push()`` which writes to the parent Figure's panel trait.

    The marker API follows matplotlib conventions::

        plot.add_circles(offsets, name="g1", facecolors="#f00", radius=5)
        plot.markers["circles"]["g1"].set(radius=8)  # live update

    Supports interactive 2-D draggable overlays (widgets) via :meth:`add_widget`.

    Parameters
    ----------
    data : ndarray, shape (H, W) or (H, W, C)
        Image data. If 3-D, only the first channel is used.
    x_axis : array-like, optional
        X-axis physical coordinates. Length must equal W (width).
    y_axis : array-like, optional
        Y-axis physical coordinates. Length must equal H (height).
    units : str, optional
        Label for the axes. Default ``"px"``.
    """

    def __init__(self, data: np.ndarray,
                 x_axis=None, y_axis=None, units: str = "px"):
        #...existing code...
        self._id:  str = ""       # assigned by Axes._attach
        self._fig: object = None  # assigned by Axes._attach

        data = np.asarray(data)
        if data.ndim == 3:
            data = data[:, :, 0]
        if data.ndim != 2:
            raise ValueError(f"data must be 2-D (H x W), got {data.shape}")

        h, w = data.shape
        x_axis_given = x_axis is not None
        y_axis_given = y_axis is not None
        if x_axis is None:
            x_axis = np.arange(w, dtype=float)
        if y_axis is None:
            y_axis = np.arange(h, dtype=float)
        x_axis = np.asarray(x_axis, dtype=float)
        y_axis = np.asarray(y_axis, dtype=float)

        img_u8, vmin, vmax = _normalize_image(data)
        self._raw_u8   = img_u8
        self._raw_vmin = vmin
        self._raw_vmax = vmax

        cmap_lut = _build_colormap_lut("gray")

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
            "display_min":       vmin,
            "display_max":       vmax,
            "raw_min":           vmin,
            "raw_max":           vmax,
            "show_colorbar":     False,
            "log_scale":         False,
            "scale_mode":        "linear",
            "colormap_name":     "gray",
            "colormap_data":     cmap_lut,
            "zoom":              1.0,
            "center_x":          0.5,
            "center_y":          0.5,
            "overlay_widgets":   [],
            "markers":           [],
            "registered_keys":   [],
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
    # Data update
    # ------------------------------------------------------------------
    def update(self, data: np.ndarray,
               x_axis=None, y_axis=None, units: str | None = None) -> None:
        """Replace the image data.

        Parameters
        ----------
        data : ndarray, shape (H, W) or (H, W, C)
            New image data. 3-D arrays use only the first channel.
        x_axis : array-like, optional
            New X-axis coordinates. Must match the new image width.
        y_axis : array-like, optional
            New Y-axis coordinates. Must match the new image height.
        units : str, optional
            Update the axes label. If not provided, keeps the current value.

        Raises
        ------
        ValueError
            If data is not 2-D.
        """
        data = np.asarray(data)
        if data.ndim == 3:
            data = data[:, :, 0]
        if data.ndim != 2:
            raise ValueError(f"data must be 2-D, got {data.shape}")
        h, w = data.shape
        img_u8, vmin, vmax = _normalize_image(data)
        self._raw_u8, self._raw_vmin, self._raw_vmax = img_u8, vmin, vmax

        if x_axis is not None:
            self._state["x_axis"] = np.asarray(x_axis, float).tolist()
            self._state["image_width"] = w
            self._state["has_axes"] = True
        if y_axis is not None:
            self._state["y_axis"] = np.asarray(y_axis, float).tolist()
            self._state["image_height"] = h
            self._state["has_axes"] = True
        if units is not None:
            self._state["units"] = units

        self._state.update({
            "image_b64":   self._encode_bytes(img_u8),
            "image_width":  w,
            "image_height": h,
            "display_min": vmin,
            "display_max": vmax,
            "raw_min":     vmin,
            "raw_max":     vmax,
            "colormap_data":  _build_colormap_lut(self._state["colormap_name"]),
        })
        self._push()

    # ------------------------------------------------------------------
    # Display settings
    # ------------------------------------------------------------------
    def set_colormap(self, name: str) -> None:
        """Set or update the colormap.

        Parameters
        ----------
        name : str
            Matplotlib-style colormap name. Common names include:
            "viridis", "plasma", "inferno", "magma", "cividis",
            "hot", "jet", "RdBu", "coolwarm", etc.
            Aliases to colorcet palettes are used internally for
            colormap independence.

        Notes
        -----
        The colormap is applied to surface Z-values (in Plot3D) or
        to intensity values (in Plot2D when used with set_clim).
        """
        self._state["colormap_name"] = name
        self._state["colormap_data"] = _build_colormap_lut(name)
        self._push()

    def set_clim(self, vmin=None, vmax=None) -> None:
        """Set the data range for display normalization.

        Parameters
        ----------
        vmin : float, optional
            Minimum data value to map to the colormap. If not provided,
            uses the current minimum.
        vmax : float, optional
            Maximum data value to map to the colormap. If not provided,
            uses the current maximum.

        Notes
        -----
        This controls the color range display without modifying the
        underlying data. Useful for emphasizing features in a specific
        intensity range.
        """
        if vmin is not None:
            self._state["display_min"] = float(vmin)
        if vmax is not None:
            self._state["display_max"] = float(vmax)
        self._push()

    def set_scale_mode(self, mode: str) -> None:
        """Set the axis scale mode (linear, logarithmic, or symmetric log).

        Parameters
        ----------
        mode : str
            One of ``"linear"``, ``"log"``, or ``"symlog"``.
            - ``"linear"``: standard linear scale.
            - ``"log"``: logarithmic scale (data must be positive).
            - ``"symlog"``: symmetric logarithmic scale (allows negative values).

        Raises
        ------
        ValueError
            If *mode* is not one of the valid options.
        """
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
        """Add an interactive overlay widget to this plot.

        Parameters
        ----------
        kind : str
            Widget type: ``"circle"``, ``"rectangle"``, ``"annular"``,
            ``"polygon"``, ``"label"``, or ``"crosshair"``.
        color : str, optional
            CSS colour for the widget outline/fill. Default ``"#00e5ff"``.
        **kwargs : dict
            Type-specific parameters:
            - circle: cx, cy, r (center x, y and radius)
            - rectangle: x, y, w, h (top-left corner and dimensions)
            - annular: cx, cy, r_outer, r_inner (center and radii)
            - polygon: vertices (list of [x, y] coordinates)
            - crosshair: cx, cy (center position)
            - label: x, y, text, fontsize (position, text, font size in pts)

        Returns
        -------
        Widget
            The created widget object. Register callbacks via
            ``@widget.on_changed`` or ``@widget.on_release``.

        Raises
        ------
        ValueError
            If *kind* is not recognized.

        Examples
        --------
        >>> plot.add_widget("circle", cx=100, cy=100, r=50, color="#ff0000")
        >>> plot.add_widget("crosshair", cx=64, cy=64)
        """
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
        """Decorator: fires on every pan/zoom/drag frame on this panel.

        Use this for high-frequency updates (e.g., live readout). Keep the
        handler fast to avoid blocking the UI.

        Parameters
        ----------
        fn : Callable
            Handler function receiving an Event with zoom, center_x, center_y.

        Returns
        -------
        Callable
            The decorated function.

        Examples
        --------
        >>> @plot.on_changed
        ... def update_readout(event):
        ...     print(f"zoom={event.zoom:.2f}")
        """
        cid = self.callbacks.connect("on_changed", fn)
        fn._cid = cid
        return fn

    def on_release(self, fn: Callable) -> Callable:
        """Decorator: fires once when pan/zoom/drag settles on this panel.

        Use this for expensive operations (e.g., recomputation).

        Parameters
        ----------
        fn : Callable
            Handler function receiving an Event with final zoom/position.

        Returns
        -------
        Callable
            The decorated function.
        """
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
        self._push()

    def reset_view(self) -> None:
        """Reset pan and zoom to show the full image."""
        self._state["zoom"]     = 1.0
        self._state["center_x"] = 0.5
        self._state["center_y"] = 0.5
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
        self.markers.remove(marker_type, name)

    def clear_markers(self) -> None:
        self.markers.clear()

    def list_markers(self) -> list:
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

class PlotBar:
    """Bar-chart plot panel.

    Not an anywidget.  Holds state in ``_state`` dict; every mutation calls
    ``_push()`` which writes to the parent Figure's panel trait.

    Supports draggable :class:`~anyplotlib.widgets.VLineWidget` and
    :class:`~anyplotlib.widgets.HLineWidget` overlays via
    :meth:`add_vline_widget` / :meth:`add_hline_widget`.

    Created by :meth:`Axes.bar`.
    """

    def __init__(self, values,
                 x_labels=None,
                 x_centers=None,
                 color: str = "#4fc3f7",
                 colors=None,
                 bar_width: float = 0.7,
                 orient: str = "v",
                 baseline: float = 0.0,
                 show_values: bool = False,
                 units: str = "",
                 y_units: str = ""):
        self._id:  str = ""
        self._fig: object = None

        values = np.asarray(values, dtype=float)
        n = len(values)
        if values.ndim != 1:
            raise ValueError(f"values must be 1-D, got shape {values.shape}")
        if orient not in ("v", "h"):
            raise ValueError("orient must be 'v' or 'h'")

        if x_centers is None:
            x_centers = np.arange(n, dtype=float)
        x_centers = np.asarray(x_centers, dtype=float)
        if len(x_centers) != n:
            raise ValueError("x_centers length must match values length")

        val_min = float(np.nanmin(values)) if n else 0.0
        val_max = float(np.nanmax(values)) if n else 1.0
        dmin = min(float(baseline), val_min)
        dmax = max(float(baseline), val_max)
        pad  = (dmax - dmin) * 0.07 if dmax > dmin else 0.5
        dmax += pad
        if dmin < float(baseline):
            dmin -= pad

        # Compute physical x-axis extent (left/right edges of the bar chart)
        # so that vline_widgets map to the correct pixel positions.
        x_axis = _bar_x_axis(x_centers)

        self._state: dict = {
            "kind":        "bar",
            "values":      values.tolist(),
            "x_centers":   x_centers.tolist(),
            "x_labels":    list(x_labels) if x_labels is not None else [],
            "bar_color":   color,
            "bar_colors":  list(colors) if colors is not None else [],
            "bar_width":   float(bar_width),
            "orient":      orient,
            "baseline":    float(baseline),
            "show_values": bool(show_values),
            "data_min":    dmin,
            "data_max":    dmax,
            "units":       units,
            "y_units":     y_units,
            # overlay-widget coordinate system (mirrors Plot1D)
            "x_axis":      x_axis,
            "view_x0":     0.0,
            "view_x1":     1.0,
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
    # Data update
    # ------------------------------------------------------------------
    def update(self, values, x_centers=None, x_labels=None) -> None:
        """Replace bar values; recalculates the value-axis range automatically."""
        values = np.asarray(values, dtype=float)
        if values.ndim != 1:
            raise ValueError(f"values must be 1-D, got shape {values.shape}")

        baseline = self._state["baseline"]
        dmin = min(float(baseline), float(np.nanmin(values)))
        dmax = max(float(baseline), float(np.nanmax(values)))
        pad  = (dmax - dmin) * 0.07 if dmax > dmin else 0.5
        dmax += pad
        if dmin < baseline:
            dmin -= pad

        self._state["values"]   = values.tolist()
        self._state["data_min"] = dmin
        self._state["data_max"] = dmax
        if x_centers is not None:
            xc = np.asarray(x_centers, dtype=float)
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

    # ------------------------------------------------------------------
    # Overlay Widgets
    # ------------------------------------------------------------------
    def add_vline_widget(self, x: float, color: str = "#00e5ff") -> _VLineWidget:
        """Add a draggable vertical line widget at x position.

        Parameters
        ----------
        x : float
            Initial x-coordinate (in data units).
        color : str, optional
            CSS colour for the line. Default ``"#00e5ff"``.

        Returns
        -------
        VLineWidget
            The widget. Register callbacks via ``@widget.on_changed``
            or ``@widget.on_release``.
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
        """Add a draggable horizontal line widget at y position.

        Parameters
        ----------
        y : float
            Initial y-coordinate (in data units).
        color : str, optional
            CSS colour for the line. Default ``"#00e5ff"``.

        Returns
        -------
        HLineWidget
            The widget. Register callbacks via ``@widget.on_changed``
            or ``@widget.on_release``.
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
                         color: str = "#00e5ff") -> _RangeWidget:
        """Add a draggable range (two connected vertical lines) widget.

        Parameters
        ----------
        x0, x1 : float
            Initial left and right x-coordinates (in data units).
        color : str, optional
            CSS colour for the lines. Default ``"#00e5ff"``.

        Returns
        -------
        RangeWidget
            The widget. Register callbacks via ``@widget.on_changed``
            or ``@widget.on_release``.

        Notes
        -----
        Dragging either line updates both x0 and x1 in the widget.
        """
        widget = _RangeWidget(lambda: None, x0=float(x0), x1=float(x1), color=color)
        plot_ref, wid_id = self, widget._id
        def _tp():
            if plot_ref._fig is not None:
                fields = {k: v for k, v in widget._data.items() if k not in ("id", "type")}
                plot_ref._fig._push_widget(plot_ref._id, wid_id, fields)
        widget._push_fn = _tp
        self._widgets[widget.id] = widget
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
    # Callback API  (Plot1D)
    # ------------------------------------------------------------------
    def on_changed(self, fn: Callable) -> Callable:
        """Decorator: fires on every drag/zoom frame on this panel.

        Use this for high-frequency updates (keep the handler fast).

        Parameters
        ----------
        fn : Callable
            Handler function receiving an Event.

        Returns
        -------
        Callable
            The decorated function.
        """
        cid = self.callbacks.connect("on_changed", fn)
        fn._cid = cid
        return fn

    def on_release(self, fn: Callable) -> Callable:
        """Decorator: fires once when drag/zoom settles on this panel.

        Use this for expensive operations.

        Parameters
        ----------
        fn : Callable
            Handler function receiving an Event.

        Returns
        -------
        Callable
            The decorated function.
        """
        cid = self.callbacks.connect("on_release", fn)
        fn._cid = cid
        return fn

    def on_click(self, fn: Callable) -> Callable:
        """Decorator: fires on click on this panel.

        Parameters
        ----------
        fn : Callable
            Handler function receiving an Event.

        Returns
        -------
        Callable
            The decorated function.
        """
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
    def set_view(self, x0: float | None = None, x1: float | None = None) -> None:
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
        self._state["view_x0"] = 0.0
        self._state["view_x1"] = 1.0
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
        """Add point markers at (x, y) positions in data coordinates."""
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
        self.markers.remove(marker_type, name)

    def clear_markers(self) -> None:
        self.markers.clear()

    def list_markers(self) -> list:
        out = []
        for mtype, td in self.markers._types.items():
            for name, g in td.items():
                out.append({"type": mtype, "name": name, "n": g._count()})
        return out

    def __repr__(self) -> str:
        n = len(self._state.get("values", []))
        orient = self._state.get("orient", "v")
        return f"PlotBar(n={n}, orient={orient!r})"








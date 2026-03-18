"""
figure_plots.py
===============

Pure-Python plot objects returned by Axes factory methods.

These are **not** anywidget subclasses.  Every plot object holds all of its
display state in a plain ``_state`` dict and propagates changes to the parent
Figure's per-panel traitlet via :meth:`_push`.

Architecture
------------
* **Python → JS (push):** any ``_state`` mutation ends with ``self._push()``
  → ``figure._push(panel_id)`` → serialises ``_state`` to JSON and writes
  the ``panel_{id}_json`` traitlet (``sync=True``) → JS re-renders.
* **JS → Python (events):** interaction events arrive via ``event_json``
  → ``Figure._on_event()`` → ``plot.callbacks.fire(event)``.

Public classes
--------------
GridSpec        – grid layout descriptor (nrows × ncols, optional ratios).
SubplotSpec     – a slice of a GridSpec (row/col spans).
Axes            – a single grid cell; factory methods return plot objects.
Plot2D          – 2-D image panel (imshow).
PlotMesh        – 2-D pcolormesh panel with edge-coordinate axes.
Plot1D          – 1-D line panel (plot).
Plot3D          – 3-D panel (surface / scatter / line).
PlotBar         – bar-chart panel.

Private helpers
---------------
_normalize_image    – scale float data to uint8 + record vmin/vmax.
_build_colormap_lut – build a 256-entry [[r,g,b],…] LUT from a cmap name.
_resample_mesh      – nearest-neighbour grid resample for non-uniform axes.
_triangulate_grid   – generate triangle indices for a rows×cols surface grid.
_bar_x_axis         – compute left/right x-axis edges for a bar chart.
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

    Returned by :meth:`GridSpec.__getitem__`; passed to
    :class:`Figure` when building a layout.

    Attributes
    ----------
    row_start, row_stop : int
        Half-open row span ``[row_start, row_stop)``.
    col_start, col_stop : int
        Half-open column span ``[col_start, col_stop)``.
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
    """A single grid cell in a :class:`Figure`.

    Returned by :func:`subplots` and :meth:`Figure.add_subplot`.
    Each ``Axes`` holds exactly one plot object at a time; calling a
    factory method a second time replaces the previous plot.

    Parameters
    ----------
    fig : Figure
        Parent Figure widget that owns this cell.
    spec : SubplotSpec
        Layout descriptor produced by a :class:`GridSpec` slice.

    Factory methods
    ---------------
    imshow(data, …)            → :class:`Plot2D`
    pcolormesh(data, …)        → :class:`PlotMesh`
    plot(data, …)              → :class:`Plot1D`
    bar(values, …)             → :class:`PlotBar`
    plot_surface(X, Y, Z, …)   → :class:`Plot3D`
    scatter3d(x, y, z, …)      → :class:`Plot3D`
    plot3d(x, y, z, …)         → :class:`Plot3D`
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
        data : np.ndarray, shape (H, W) or (H, W, C)
            Image data.  3-D arrays use only the first channel.
        axes : [x_axis, y_axis], optional
            Physical coordinate arrays.  ``axes[0]`` must have length W;
            ``axes[1]`` must have length H.  Defaults to pixel indices.
        units : str, optional
            Axis label string.  Default ``"px"``.

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
        data : np.ndarray, shape (N,)
            Y-values of the line.
        axes : [x_axis], optional
            ``axes[0]`` is the physical x-coordinate array (length N).
            Defaults to ``np.arange(N)``.
        units : str, optional
            Label for the x axis.  Default ``"px"``.
        y_units : str, optional
            Label for the y axis.  Default ``""``.
        color : str, optional
            CSS colour for the line.  Default ``"#4fc3f7"``.
        linewidth : float, optional
            Stroke width in pixels.  Default ``1.5``.
        label : str, optional
            Legend label.  Default ``""``.

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
    """2-D image plot panel created by :meth:`Axes.imshow`.

    Not an anywidget.  Holds all display state in a plain ``_state`` dict;
    every mutation calls :meth:`_push` which writes to the parent Figure's
    per-panel traitlet so the JS renderer re-draws.

    The marker API mirrors matplotlib conventions — keyword arguments use
    matplotlib names and are translated to the wire format internally::

        plot.add_circles(offsets, name="g1", facecolors="#f00", radius=5)
        plot.markers["circles"]["g1"].set(radius=8)   # live update

    Supports interactive draggable overlays (:class:`~anyplotlib.widgets.Widget`
    subclasses) via :meth:`add_widget`.

    Parameters
    ----------
    data : ndarray, shape (H, W) or (H, W, C)
        Image data.  3-D arrays use only the first channel.
    x_axis : array-like, length W, optional
        Physical x-coordinate array.  Defaults to ``np.arange(W)``.
    y_axis : array-like, length H, optional
        Physical y-coordinate array.  Defaults to ``np.arange(H)``.
    units : str, optional
        Axis label.  Default ``"px"``.
    """

    def __init__(self, data: np.ndarray,
                 x_axis=None, y_axis=None, units: str = "px"):
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
        """Replace the image data and optionally update axes / units.

        Parameters
        ----------
        data : ndarray, shape (H, W) or (H, W, C)
            New image data.  3-D arrays use only the first channel.
        x_axis : array-like, optional
            New x-coordinate array (length must match new image width).
        y_axis : array-like, optional
            New y-coordinate array (length must match new image height).
        units : str, optional
            New axis label.  Keeps the current value when not provided.

        Raises
        ------
        ValueError
            If *data* is not 2-D (or 3-D).
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
        """Set the colormap used to render the image data.

        Parameters
        ----------
        name : str
            Matplotlib-compatible colormap name, e.g. ``"viridis"``,
            ``"plasma"``, ``"hot"``, ``"RdBu"``.  Common names are
            remapped to colorcet equivalents internally; unknown names
            fall back to a linear grey ramp.
        """
        self._state["colormap_name"] = name
        self._state["colormap_data"] = _build_colormap_lut(name)
        self._push()

    def set_clim(self, vmin=None, vmax=None) -> None:
        """Set the data range mapped to the colormap (contrast / brightness).

        Parameters
        ----------
        vmin : float, optional
            Data value that maps to the bottom of the colormap.
            Keeps the current value when not provided.
        vmax : float, optional
            Data value that maps to the top of the colormap.
            Keeps the current value when not provided.

        Notes
        -----
        This adjusts *display* normalisation only — the underlying data
        is not modified.
        """
        if vmin is not None:
            self._state["display_min"] = float(vmin)
        if vmax is not None:
            self._state["display_max"] = float(vmax)
        self._push()

    def set_scale_mode(self, mode: str) -> None:
        """Set the intensity-axis scale applied before colormap mapping.

        Parameters
        ----------
        mode : str
            One of:

            ``"linear"``
                Standard linear normalisation (default).
            ``"log"``
                Logarithmic scale; data must be positive.
            ``"symlog"``
                Symmetric log scale; supports negative values.

        Raises
        ------
        ValueError
            If *mode* is not one of the accepted values.
        """
        valid = ("linear", "log", "symlog")
        if mode not in valid:
            raise ValueError(f"mode must be one of {valid}")
        self._state["scale_mode"] = mode
        self._push()

    @property
    def colormap_name(self) -> str:
        """str: Name of the active colormap (read/write)."""
        return self._state["colormap_name"]

    @colormap_name.setter
    def colormap_name(self, name: str) -> None:
        self.set_colormap(name)

    # ------------------------------------------------------------------
    # Overlay Widgets
    # ------------------------------------------------------------------
    def add_widget(self, kind: str, color: str = "#00e5ff", **kwargs) -> Widget:
        """Add an interactive draggable overlay widget to this panel.

        Parameters
        ----------
        kind : str
            Widget type — one of ``"circle"``, ``"rectangle"``,
            ``"annular"``, ``"polygon"``, ``"crosshair"``, ``"label"``.
        color : str, optional
            CSS colour for the widget outline/fill.  Default ``"#00e5ff"``.
        **kwargs
            Type-specific initialisation values:

            *circle*
                ``cx``, ``cy`` — centre; ``r`` — radius (all in data-space px).
            *rectangle*
                ``x``, ``y`` — top-left corner; ``w``, ``h`` — size.
            *annular*
                ``cx``, ``cy`` — centre; ``r_outer``, ``r_inner`` — radii.
            *polygon*
                ``vertices`` — list of ``[x, y]`` data-space coordinates.
            *crosshair*
                ``cx``, ``cy`` — centre position.
            *label*
                ``x``, ``y`` — anchor; ``text`` — string; ``fontsize`` — pt.

        Returns
        -------
        Widget
            The created widget.  Register drag callbacks with
            :meth:`Plot2D.on_changed` / :meth:`Plot2D.on_release`.

        Raises
        ------
        ValueError
            If *kind* is not one of the accepted types.

        Examples
        --------
        >>> roi = plot.add_widget("rectangle", x=20, y=20, w=60, h=40)
        >>> ch  = plot.add_widget("crosshair", cx=64, cy=64)
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
        """Return a list of all active :class:`~anyplotlib.widgets.Widget` objects."""
        return list(self._widgets.values())

    def clear_widgets(self) -> None:
        """Remove all overlay widgets from this panel."""
        self._widgets.clear()
        self._push()
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
        """Add arrow markers with tail positions and direction vectors.

        Parameters
        ----------
        offsets : array-like, shape (N, 2)
            Tail positions ``[[x, y], …]`` in data coordinates.
        U, V : array-like, shape (N,)
            Horizontal and vertical vector components.
        name : str, optional
            Group name; auto-generated when omitted.
        edgecolors : str or list, optional
            Arrow colour(s).  Default ``"#ff0000"``.
        linewidths : float, optional
            Stroke width in pixels.  Default ``1.5``.
        hover_edgecolors : str or list, optional
            Colour on mouse-hover.
        labels, label : optional
            Per-marker or group tooltip text.

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
        """Add ellipse markers at (x, y) positions.

        Parameters
        ----------
        offsets : array-like, shape (N, 2)
            Centre positions ``[[x, y], …]`` in data coordinates.
        widths, heights : array-like, shape (N,) or scalar
            Semi-axis lengths along x and y.
        name : str, optional
            Group name; auto-generated when omitted.
        angles : array-like or float, optional
            Rotation in degrees (CCW from x-axis).  Default ``0``.
        facecolors : str or list, optional
            Fill colour(s).  ``None`` → transparent.
        edgecolors : str or list, optional
            Border colour(s).  Default ``"#ff0000"``.
        linewidths : float, optional
            Stroke width.  Default ``1.5``.
        alpha : float, optional
            Fill opacity 0–1.  Default ``0.3``.
        hover_edgecolors, hover_facecolors : optional
            Colours on mouse-hover.
        labels, label : optional
            Tooltip text.

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
        """Add line-segment markers (static polyline overlays).

        Parameters
        ----------
        segments : list of array-like
            Each element is a list of ``[x, y]`` data-space waypoints that
            define one polyline, e.g.
            ``[[[x0, y0], [x1, y1]], [[x2, y2], [x3, y3]]]``.
        name : str, optional
            Group name; auto-generated when omitted.
        edgecolors : str or list, optional
            Line colour(s).  Default ``"#ff0000"``.
        linewidths : float, optional
            Stroke width.  Default ``1.5``.
        hover_edgecolors : str or list, optional
            Colour on mouse-hover.
        labels, label : optional
            Tooltip text.

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
        """Add rectangle markers at (x, y) positions.

        Parameters
        ----------
        offsets : array-like, shape (N, 2)
            Centre positions ``[[x, y], …]`` in data coordinates.
        widths, heights : array-like or scalar
            Rectangle dimensions.
        name : str, optional
            Group name; auto-generated when omitted.
        angles : array-like or float, optional
            Rotation in degrees (CCW).  Default ``0``.
        facecolors : str or list, optional
            Fill colour(s).  ``None`` → transparent.
        edgecolors : str or list, optional
            Border colour(s).  Default ``"#ff0000"``.
        linewidths : float, optional
            Stroke width.  Default ``1.5``.
        alpha : float, optional
            Fill opacity 0–1.  Default ``0.3``.
        hover_edgecolors, hover_facecolors : optional
            Colours on mouse-hover.
        labels, label : optional
            Tooltip text.

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
        """Add square markers (equal-sided rectangles) at (x, y) positions.

        Parameters
        ----------
        offsets : array-like, shape (N, 2)
            Centre positions in data coordinates.
        widths : array-like or scalar
            Side length (width = height).
        name : str, optional
            Group name; auto-generated when omitted.
        angles : array-like or float, optional
            Rotation in degrees.  Default ``0``.
        facecolors : str or list, optional
            Fill colour(s).  ``None`` → transparent.
        edgecolors : str or list, optional
            Border colour(s).  Default ``"#ff0000"``.
        linewidths : float, optional
            Stroke width.  Default ``1.5``.
        alpha : float, optional
            Fill opacity 0–1.  Default ``0.3``.
        hover_edgecolors, hover_facecolors : optional
            Colours on mouse-hover.
        labels, label : optional
            Tooltip text.

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
        """Add polygon markers defined by vertex lists.

        Parameters
        ----------
        vertices_list : list of array-like
            One entry per polygon; each entry is an (M, 2) array of
            ``[x, y]`` data-space vertex coordinates.
        name : str, optional
            Group name; auto-generated when omitted.
        facecolors : str or list, optional
            Fill colour(s).  ``None`` → transparent.
        edgecolors : str or list, optional
            Border colour(s).  Default ``"#ff0000"``.
        linewidths : float, optional
            Stroke width.  Default ``1.5``.
        alpha : float, optional
            Fill opacity 0–1.  Default ``0.3``.
        hover_edgecolors, hover_facecolors : optional
            Colours on mouse-hover.
        labels, label : optional
            Tooltip text.

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
        """Add text-label markers at (x, y) positions.

        Parameters
        ----------
        offsets : array-like, shape (N, 2)
            Anchor positions ``[[x, y], …]`` in data coordinates.
        texts : list of str
            One string per marker.
        name : str, optional
            Group name; auto-generated when omitted.
        color : str, optional
            Text colour.  Default ``"#ff0000"``.
        fontsize : int, optional
            Font size in points.  Default ``12``.
        hover_edgecolors : optional
            Colour on mouse-hover.
        labels, label : optional
            Tooltip text (distinct from the displayed text).

        Returns
        -------
        MarkerGroup
        """
        return self._add_marker("texts", name, offsets=offsets, texts=texts,
                                color=color, fontsize=fontsize,
                                hover_edgecolors=hover_edgecolors,
                                labels=labels, label=label)

    def remove_marker(self, marker_type: str, name: str) -> None:
        """Remove a named marker group from this panel.

        Parameters
        ----------
        marker_type : str
            Category string, e.g. ``"circles"``, ``"lines"``.
        name : str
            The group name passed when the marker was added.

        Raises
        ------
        KeyError
            If no group with that *name* exists under *marker_type*.
        """
        self.markers.remove(marker_type, name)

    def clear_markers(self) -> None:
        """Remove all marker groups from this panel."""
        self.markers.clear()

    def list_markers(self) -> list:
        """Return a summary list of all active marker groups.

        Returns
        -------
        list of dict
            Each entry has keys ``"type"``, ``"name"``, and ``"n"``
            (number of markers in the group).
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

    Follows the matplotlib ``pcolormesh`` convention: axis arrays are cell
    *edge* coordinates (length N+1 and M+1 for an (M, N) data array) rather
    than cell centres.  Non-uniform (e.g. log-spaced) edges are resampled to
    a regular pixel grid for display via :func:`_resample_mesh`.

    Only ``"circles"`` and ``"lines"`` markers are supported; all other
    marker types raise :exc:`ValueError`.

    Inherits :meth:`set_colormap`, :meth:`set_clim`, :meth:`set_scale_mode`,
    :meth:`add_widget`, and the full callback API from :class:`Plot2D`.

    Parameters
    ----------
    data : ndarray, shape (M, N)
        Cell values — one scalar per mesh cell.
    x_edges : array-like, length N+1, optional
        Column edge coordinates.  Defaults to ``np.arange(N+1)``.
    y_edges : array-like, length M+1, optional
        Row edge coordinates.  Defaults to ``np.arange(M+1)``.
    units : str, optional
        Axis label.  Default ``""``.

    Raises
    ------
    ValueError
        If *data* is not 2-D, or if edge arrays have the wrong length.
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
    # Data update
    # ------------------------------------------------------------------
    def update(self, data: np.ndarray,
               x_edges=None, y_edges=None, units: str | None = None) -> None:
        """Replace the mesh data and optionally the edge arrays.

        Parameters
        ----------
        data : ndarray, shape (M, N)
            New cell values.
        x_edges : array-like, length N+1, optional
            New column edge coordinates.  Keeps current edges when omitted.
        y_edges : array-like, length M+1, optional
            New row edge coordinates.  Keeps current edges when omitted.
        units : str, optional
            New axis label.  Keeps the current value when not provided.

        Raises
        ------
        ValueError
            If *data* is not 2-D or edge arrays have the wrong length.
        """
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
    """3-D plot panel created by :meth:`Axes.plot_surface`, :meth:`Axes.scatter3d`,
    or :meth:`Axes.plot3d`.

    Supports three geometry types:

    ``'surface'``
        Triangulated surface mesh coloured by Z-value via a colormap.
    ``'scatter'``
        Point cloud drawn in a single colour.
    ``'line'``
        Connected polyline through 3-D points.

    Not an anywidget.  Holds state in ``_state`` dict; every mutation calls
    :meth:`_push` which writes to the parent Figure's panel traitlet.

    Parameters
    ----------
    geom_type : ``'surface'`` | ``'scatter'`` | ``'line'``
        Geometry kind.
    x, y, z : array-like
        For *surface*: 2-D grid arrays of the same shape (e.g. from
        ``np.meshgrid``), **or** 1-D centre arrays for x/y with a 2-D z.
        For *scatter* / *line*: 1-D coordinate arrays of the same length.
    colormap : str, optional
        Matplotlib-compatible colormap name (surface only).  Default
        ``"viridis"``.
    color : str, optional
        CSS colour for scatter/line geometry.  Default ``"#4fc3f7"``.
    point_size : float, optional
        Point radius in pixels (scatter only).  Default ``4.0``.
    linewidth : float, optional
        Stroke width in pixels (line only).  Default ``1.5``.
    x_label, y_label, z_label : str, optional
        Axis labels.  Default ``"x"``, ``"y"``, ``"z"``.
    azimuth, elevation : float, optional
        Initial camera angles in degrees.  Defaults ``-60`` and ``30``.
    zoom : float, optional
        Initial zoom factor.  Default ``1.0``.

    Raises
    ------
    ValueError
        If *geom_type* is not one of the accepted values, or if the
        array shapes are incompatible with the chosen geometry type.
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
            faces = _triangulate_grid(rows, cols)
            vertices = np.column_stack([xf, yf, zf]).tolist()
            z_values = zf.tolist()
        else:
            if x.ndim != 1 or y.ndim != 1 or z.ndim != 1:
                raise ValueError("scatter/line x, y, z must be 1-D arrays")
            if not (len(x) == len(y) == len(z)):
                raise ValueError("x, y, z must have the same length")
            vertices = np.column_stack([x, y, z]).tolist()
            faces    = []
            z_values = z.tolist()

        # Normalised data bounds for the JS renderer
        all_x = np.asarray([v[0] for v in vertices])
        all_y = np.asarray([v[1] for v in vertices])
        all_z = np.asarray([v[2] for v in vertices])
        data_bounds = {
            "xmin": float(all_x.min()), "xmax": float(all_x.max()),
            "ymin": float(all_y.min()), "ymax": float(all_y.max()),
            "zmin": float(all_z.min()), "zmax": float(all_z.max()),
        }

        cmap_lut = _build_colormap_lut(colormap)

        self._state: dict = {
            "kind":        "3d",
            "geom_type":   geom_type,
            "vertices":    vertices,
            "faces":       faces,
            "z_values":    z_values,
            "colormap_name": colormap,
            "colormap_data": cmap_lut,
            "color":       color,
            "point_size":  float(point_size),
            "linewidth":   float(linewidth),
            "x_label":     x_label,
            "y_label":     y_label,
            "z_label":     z_label,
            "azimuth":     float(azimuth),
            "elevation":   float(elevation),
            "zoom":        float(zoom),
            "data_bounds": data_bounds,
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
        """Set the surface colormap.

        Parameters
        ----------
        name : str
            Matplotlib-compatible colormap name.  Ignored for
            ``'scatter'`` and ``'line'`` geometry.
        """
        self._state["colormap_name"] = name
        self._state["colormap_data"] = _build_colormap_lut(name)
        self._push()

    def set_view(self, azimuth: float | None = None,
                 elevation: float | None = None) -> None:
        """Set the camera orientation.

        Parameters
        ----------
        azimuth : float, optional
            Horizontal rotation in degrees around the z-axis.
            0° points along the positive x-axis; positive values rotate
            counter-clockwise when viewed from above.
        elevation : float, optional
            Vertical tilt in degrees above the x-y plane.  90° looks
            straight down; 0° is a side view.
        """
        if azimuth   is not None: self._state["azimuth"]   = float(azimuth)
        if elevation is not None: self._state["elevation"] = float(elevation)
        self._push()

    def set_zoom(self, zoom: float) -> None:
        """Set the camera zoom factor.

        Parameters
        ----------
        zoom : float
            Scale factor applied to the projection.  Values > 1 zoom in;
            values < 1 zoom out.
        """
        self._state["zoom"] = float(zoom)
        self._push()

    def update(self, x, y, z) -> None:
        """Replace the geometry data without changing camera or style settings.

        Parameters
        ----------
        x, y, z : array-like
            New coordinate data in the same form accepted by the
            constructor for the stored *geom_type*:

            * *surface*: 2-D grid arrays or 1-D x/y + 2-D z.
            * *scatter* / *line*: 1-D arrays of equal length.

        Raises
        ------
        ValueError
            If the array shapes are incompatible with the stored
            geometry type.
        """
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
            faces    = _triangulate_grid(rows, cols)
            vertices = np.column_stack([xf, yf, zf]).tolist()
            z_values = zf.tolist()
        else:
            vertices = np.column_stack([x.ravel(), y.ravel(), z.ravel()]).tolist()
            faces    = []
            z_values = z.ravel().tolist()

        all_x = np.asarray([v[0] for v in vertices])
        all_y = np.asarray([v[1] for v in vertices])
        all_z = np.asarray([v[2] for v in vertices])
        data_bounds = {
            "xmin": float(all_x.min()), "xmax": float(all_x.max()),
            "ymin": float(all_y.min()), "ymax": float(all_y.max()),
            "zmin": float(all_z.min()), "zmax": float(all_z.max()),
        }

        self._state.update({
            "vertices":    vertices,
            "faces":       faces,
            "z_values":    z_values,
            "data_bounds": data_bounds,
            "colormap_data": _build_colormap_lut(self._state["colormap_name"]),
        })
        self._push()

    def __repr__(self) -> str:
        geom = self._state.get("geom_type", "?")
        n = len(self._state.get("vertices", []))
        return f"Plot3D(geom={geom!r}, n_vertices={n})"


# ---------------------------------------------------------------------------
# Plot1D
# ---------------------------------------------------------------------------

class Plot1D:
    """1-D line plot panel created by :meth:`Axes.plot`.

    Not an anywidget.  Holds all display state in a plain ``_state`` dict;
    every mutation calls :meth:`_push` which writes to the parent Figure's
    per-panel traitlet so the JS renderer re-draws.

    Multiple overlaid curves can be added with :meth:`add_line`.
    Shaded spans can be added with :meth:`add_span`.
    Draggable line widgets are available via :meth:`add_vline_widget`,
    :meth:`add_hline_widget`, and :meth:`add_range_widget`.

    The marker API mirrors matplotlib conventions (keyword arguments use
    matplotlib names)::

        plot.add_points(offsets, name="peaks", sizes=6, color="#f00")
        plot.markers["points"]["peaks"].set(sizes=8)   # live update

    Parameters
    ----------
    data : ndarray, shape (N,)
        Y-values of the primary line.
    x_axis : array-like, length N, optional
        Physical x-coordinate array.  Defaults to ``np.arange(N)``.
    units : str, optional
        Label for the x axis.  Default ``"px"``.
    y_units : str, optional
        Label for the y axis.  Default ``""``.
    color : str, optional
        CSS colour for the primary line.  Default ``"#4fc3f7"``.
    linewidth : float, optional
        Stroke width in pixels.  Default ``1.5``.
    label : str, optional
        Legend label for the primary line.  Default ``""``.

    Raises
    ------
    ValueError
        If *data* is not 1-D, or if *x_axis* length does not match *data*.
    """

    def __init__(self, data: np.ndarray,
                 x_axis=None,
                 units: str = "px",
                 y_units: str = "",
                 color: str = "#4fc3f7",
                 linewidth: float = 1.5,
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
            "kind":          "1d",
            "data":          data.tolist(),
            "x_axis":        x_axis.tolist(),
            "units":         units,
            "y_units":       y_units,
            "data_min":      dmin,
            "data_max":      dmax,
            "view_x0":       0.0,
            "view_x1":       1.0,
            "line_color":    color,
            "line_linewidth": float(linewidth),
            "line_label":    label,
            "extra_lines":   [],
            "spans":         [],
            "overlay_widgets": [],
            "markers":       [],
            "registered_keys": [],
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
        d["overlay_widgets"] = [w.to_dict() for w in self._widgets.values()]
        d["markers"] = self.markers.to_wire_list()
        return d

    # ------------------------------------------------------------------
    # Data update
    # ------------------------------------------------------------------
    def update(self, data: np.ndarray, x_axis=None,
               units: str | None = None, y_units: str | None = None) -> None:
        """Replace the primary line data.

        Parameters
        ----------
        data : ndarray, shape (N,)
            New Y-values.
        x_axis : array-like, length N, optional
            New x-coordinate array.  If omitted and the previous array has
            the same length it is reused; otherwise defaults to
            ``np.arange(N)``.
        units : str, optional
            New x-axis label.  Keeps the current value when not provided.
        y_units : str, optional
            New y-axis label.  Keeps the current value when not provided.

        Raises
        ------
        ValueError
            If *data* is not 1-D.
        """
        data = np.asarray(data, dtype=float)
        if data.ndim != 1:
            raise ValueError(f"data must be 1-D, got {data.shape}")
        n = len(data)
        if x_axis is None:
            prev = np.asarray(self._state["x_axis"])
            x_axis = prev if len(prev) == n else np.arange(n, dtype=float)
        x_axis = np.asarray(x_axis, dtype=float)

        dmin = float(np.nanmin(data))
        dmax = float(np.nanmax(data))
        pad  = (dmax - dmin) * 0.05 if dmax > dmin else 0.5

        self._state["data"]    = data.tolist()
        self._state["x_axis"]  = x_axis.tolist()
        self._state["data_min"] = dmin - pad
        self._state["data_max"] = dmax + pad
        if units    is not None: self._state["units"]   = units
        if y_units  is not None: self._state["y_units"] = y_units
        self._push()

    # ------------------------------------------------------------------
    # Extra lines
    # ------------------------------------------------------------------
    def add_line(self, data: np.ndarray, x_axis=None,
                 color: str = "#ffffff", linewidth: float = 1.5,
                 label: str = "") -> str:
        """Overlay an additional line on the same axes.

        Parameters
        ----------
        data : ndarray, shape (N,)
            Y-values of the overlay line.
        x_axis : array-like, optional
            X-coordinate array.  Defaults to the primary line's x-axis.
        color : str, optional
            CSS colour.  Default ``"#ffffff"``.
        linewidth : float, optional
            Stroke width in pixels.  Default ``1.5``.
        label : str, optional
            Legend label.  Default ``""``.

        Returns
        -------
        str
            Unique line ID that can be passed to :meth:`remove_line`.

        Raises
        ------
        ValueError
            If *data* is not 1-D.
        """
        data = np.asarray(data, dtype=float)
        if data.ndim != 1:
            raise ValueError("data must be 1-D")
        xa = (np.asarray(x_axis, float).tolist() if x_axis is not None
              else self._state["x_axis"])
        lid = str(_uuid.uuid4())[:8]
        self._state["extra_lines"].append({
            "id": lid, "data": data.tolist(), "x_axis": xa,
            "color": color, "linewidth": float(linewidth), "label": label,
        })
        self._push()
        return lid

    def remove_line(self, lid: str) -> None:
        """Remove an overlay line by its ID.

        Parameters
        ----------
        lid : str
            Line ID returned by :meth:`add_line`.

        Raises
        ------
        KeyError
            If no line with *lid* exists.
        """
        before = len(self._state["extra_lines"])
        self._state["extra_lines"] = [
            e for e in self._state["extra_lines"] if e["id"] != lid]
        if len(self._state["extra_lines"]) == before:
            raise KeyError(lid)
        self._push()

    def clear_lines(self) -> None:
        """Remove all overlay lines, leaving only the primary line."""
        self._state["extra_lines"] = []
        self._push()

    # ------------------------------------------------------------------
    # Spans
    # ------------------------------------------------------------------
    def add_span(self, v0: float, v1: float,
                 axis: str = "x", color: str | None = None) -> str:
        """Add a shaded span (axvspan / axhspan) to the panel.

        Parameters
        ----------
        v0, v1 : float
            Start and end of the span in data coordinates.
        axis : ``"x"`` | ``"y"``, optional
            Which axis the span runs along.  Default ``"x"``
            (vertical band covering the full y range).
        color : str, optional
            CSS fill colour.  Uses the renderer default when ``None``.

        Returns
        -------
        str
            Unique span ID that can be passed to :meth:`remove_span`.
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
            Span ID returned by :meth:`add_span`.

        Raises
        ------
        KeyError
            If no span with *sid* exists.
        """
        before = len(self._state["spans"])
        self._state["spans"] = [
            s for s in self._state["spans"] if s["id"] != sid]
        if len(self._state["spans"]) == before:
            raise KeyError(sid)
        self._push()

    def clear_spans(self) -> None:
        """Remove all shaded spans from this panel."""
        self._state["spans"] = []
        self._push()

    # ------------------------------------------------------------------
    # Overlay Widgets
    # ------------------------------------------------------------------
    def add_vline_widget(self, x: float, color: str = "#00e5ff") -> _VLineWidget:
        """Add a draggable vertical line at data position *x*.

        Parameters
        ----------
        x : float
            Initial x position in data coordinates.
        color : str, optional
            CSS colour.  Default ``"#00e5ff"``.

        Returns
        -------
        VLineWidget
            Register drag callbacks with :meth:`on_changed` /
            :meth:`on_release`.
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
        """Add a draggable horizontal line at value-axis position *y*.

        Parameters
        ----------
        y : float
            Initial y position in data coordinates.
        color : str, optional
            CSS colour.  Default ``"#00e5ff"``.

        Returns
        -------
        HLineWidget
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
        """Add a draggable shaded range between *x0* and *x1*.

        Parameters
        ----------
        x0, x1 : float
            Initial left and right edge positions in data coordinates.
        color : str, optional
            CSS colour for the range highlight.  Default ``"#00e5ff"``.

        Returns
        -------
        RangeWidget
            Register drag callbacks with :meth:`on_changed` /
            :meth:`on_release`.
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
        """Return a list of all active overlay widget objects."""
        return list(self._widgets.values())

    def clear_widgets(self) -> None:
        """Remove all overlay widgets from this panel."""
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

    # ------------------------------------------------------------------
    # View control
    # ------------------------------------------------------------------
    def set_view(self, x0: float | None = None, x1: float | None = None) -> None:
        """Set the visible x-axis range.

        Parameters
        ----------
        x0 : float, optional
            Left boundary in data coordinates.  Uses the axis minimum
            when not provided.
        x1 : float, optional
            Right boundary in data coordinates.  Uses the axis maximum
            when not provided.
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
        """Reset the x-axis view to show the full data range."""
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
        """Add circular point markers at (x, y) positions.

        Alias for :meth:`add_points` — *radius* maps to the ``sizes``
        parameter.  Uses the ``"points"`` marker type on 1-D panels.

        Parameters
        ----------
        offsets : array-like, shape (N, 2)
            Positions ``[[x, y], …]`` in data coordinates.
        name : str, optional
            Group name; auto-generated when omitted.
        radius : float or array-like, optional
            Point radius in pixels.  Default ``5``.
        facecolors : str or list, optional
            Fill colour(s).  ``None`` → transparent.
        edgecolors : str or list, optional
            Border colour(s).  Default ``"#ff0000"``.
        linewidths : float, optional
            Stroke width.  Default ``1.5``.
        alpha : float, optional
            Fill opacity 0–1.  Default ``0.3``.
        hover_edgecolors, hover_facecolors : optional
            Colours on mouse-hover.
        labels, label : optional
            Tooltip text.

        Returns
        -------
        MarkerGroup
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
        """Add arrow markers with tail positions and direction vectors.

        Parameters
        ----------
        offsets : array-like, shape (N, 2)
            Tail positions in data coordinates.
        U, V : array-like, shape (N,)
            Horizontal and vertical vector components.
        name : str, optional
            Group name; auto-generated when omitted.
        edgecolors : str or list, optional
            Arrow colour(s).  Default ``"#ff0000"``.
        linewidths : float, optional
            Stroke width.  Default ``1.5``.
        hover_edgecolors : optional
            Colour on mouse-hover.
        labels, label : optional
            Tooltip text.

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
        """Add ellipse markers at (x, y) positions.

        Parameters
        ----------
        offsets : array-like, shape (N, 2)
            Centre positions in data coordinates.
        widths, heights : array-like or scalar
            Semi-axis lengths along x and y.
        name : str, optional
            Group name; auto-generated when omitted.
        angles : array-like or float, optional
            Rotation in degrees (CCW).  Default ``0``.
        facecolors : str or list, optional
            Fill colour(s).
        edgecolors : str or list, optional
            Border colour(s).  Default ``"#ff0000"``.
        linewidths : float, optional
            Stroke width.  Default ``1.5``.
        alpha : float, optional
            Fill opacity 0–1.  Default ``0.3``.
        hover_edgecolors, hover_facecolors : optional
            Colours on mouse-hover.
        labels, label : optional
            Tooltip text.

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
        """Add line-segment markers (static polyline overlays).

        Parameters
        ----------
        segments : list of array-like
            Each element is a list of ``[x, y]`` data-space waypoints
            defining one polyline.
        name : str, optional
            Group name; auto-generated when omitted.
        edgecolors : str or list, optional
            Line colour(s).  Default ``"#ff0000"``.
        linewidths : float, optional
            Stroke width.  Default ``1.5``.
        hover_edgecolors : optional
            Colour on mouse-hover.
        labels, label : optional
            Tooltip text.

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
        """Add rectangle markers at (x, y) positions.

        Parameters
        ----------
        offsets : array-like, shape (N, 2)
            Centre positions in data coordinates.
        widths, heights : array-like or scalar
            Rectangle dimensions.
        name : str, optional
            Group name; auto-generated when omitted.
        angles : array-like or float, optional
            Rotation in degrees.  Default ``0``.
        facecolors : str or list, optional
            Fill colour(s).
        edgecolors : str or list, optional
            Border colour(s).  Default ``"#ff0000"``.
        linewidths : float, optional
            Stroke width.  Default ``1.5``.
        alpha : float, optional
            Fill opacity.  Default ``0.3``.
        hover_edgecolors, hover_facecolors : optional
            Colours on mouse-hover.
        labels, label : optional
            Tooltip text.

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
        """Add square markers (equal-sided rectangles) at (x, y) positions.

        Parameters
        ----------
        offsets : array-like, shape (N, 2)
            Centre positions in data coordinates.
        widths : array-like or scalar
            Side length (width = height).
        name : str, optional
            Group name; auto-generated when omitted.
        angles : array-like or float, optional
            Rotation in degrees.  Default ``0``.
        facecolors : str or list, optional
            Fill colour(s).
        edgecolors : str or list, optional
            Border colour(s).  Default ``"#ff0000"``.
        linewidths : float, optional
            Stroke width.  Default ``1.5``.
        alpha : float, optional
            Fill opacity.  Default ``0.3``.
        hover_edgecolors, hover_facecolors : optional
            Colours on mouse-hover.
        labels, label : optional
            Tooltip text.

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
        """Add polygon markers defined by vertex lists.

        Parameters
        ----------
        vertices_list : list of array-like
            One entry per polygon; each entry is an (M, 2) array of
            ``[x, y]`` data-space vertex coordinates.
        name : str, optional
            Group name; auto-generated when omitted.
        facecolors : str or list, optional
            Fill colour(s).
        edgecolors : str or list, optional
            Border colour(s).  Default ``"#ff0000"``.
        linewidths : float, optional
            Stroke width.  Default ``1.5``.
        alpha : float, optional
            Fill opacity.  Default ``0.3``.
        hover_edgecolors, hover_facecolors : optional
            Colours on mouse-hover.
        labels, label : optional
            Tooltip text.

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
        """Add text-label markers at (x, y) positions.

        Parameters
        ----------
        offsets : array-like, shape (N, 2)
            Anchor positions in data coordinates.
        texts : list of str
            One string per marker.
        name : str, optional
            Group name; auto-generated when omitted.
        color : str, optional
            Text colour.  Default ``"#ff0000"``.
        fontsize : int, optional
            Font size in points.  Default ``12``.
        hover_edgecolors : optional
            Colour on mouse-hover.
        labels, label : optional
            Tooltip text.

        Returns
        -------
        MarkerGroup
        """
        return self._add_marker("texts", name, offsets=offsets, texts=texts,
                                color=color, fontsize=fontsize,
                                hover_edgecolors=hover_edgecolors,
                                labels=labels, label=label)

    def remove_marker(self, marker_type: str, name: str) -> None:
        """Remove a named marker group from this panel.

        Parameters
        ----------
        marker_type : str
            Category string, e.g. ``"points"``, ``"lines"``.
        name : str
            The group name passed when the marker was added.

        Raises
        ------
        KeyError
            If no group with that *name* exists under *marker_type*.
        """
        self.markers.remove(marker_type, name)

    def clear_markers(self) -> None:
        """Remove all marker groups from this panel."""
        self.markers.clear()

    def list_markers(self) -> list:
        """Return a summary list of all active marker groups.

        Returns
        -------
        list of dict
            Each entry has keys ``"type"``, ``"name"``, and ``"n"``
            (number of markers in the group).
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
        """Return a list of all active overlay widget objects."""
        return list(self._widgets.values())

    def clear_widgets(self) -> None:
        """Remove all overlay widgets from this panel."""
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
        """Remove the callback registered under integer *cid*."""
        self.callbacks.disconnect(cid)

    def __repr__(self) -> str:
        n = len(self._state.get("values", []))
        orient = self._state.get("orient", "v")
        return f"PlotBar(n={n}, orient={orient!r})"






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

from viewer.markers import MarkerRegistry

__all__ = ["GridSpec", "SubplotSpec", "Axes", "Plot1D", "Plot2D"]


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

    def _attach(self, plot: "Plot1D | Plot2D") -> None:
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


def _compute_histogram(img_u8: np.ndarray, vmin: float, vmax: float) -> dict:
    counts, edges = np.histogram(img_u8.ravel(), bins=256, range=(0, 255))
    bin_centers = vmin + (edges[:-1] + edges[1:]) / 2 / 255.0 * (vmax - vmin)
    return {"bins": bin_centers.tolist(), "counts": counts.tolist()}


def _build_colormap_lut(name: str) -> list:
    """Return a 256-entry [[r,g,b], ...] LUT for the named colormap."""
    try:
        import matplotlib.cm as cm
        cmap = cm.get_cmap(name, 256)
        return [[int(r * 255), int(g * 255), int(b * 255)]
                for r, g, b, _ in (cmap(i / 255) for i in range(256))]
    except Exception:
        return [[i, i, i] for i in range(256)]


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
                 x_axis=None, y_axis=None, units: str = "px"):
        self._id:  str = ""       # assigned by Axes._attach
        self._fig: object = None  # assigned by Axes._attach

        data = np.asarray(data)
        if data.ndim == 3:
            data = data[:, :, 0]
        if data.ndim != 2:
            raise ValueError(f"data must be 2-D (H x W), got {data.shape}")

        h, w = data.shape
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
            "image_b64":         self._encode_bytes(img_u8),
            "image_width":       w,
            "image_height":      h,
            "x_axis":            x_axis.tolist(),
            "y_axis":            y_axis.tolist(),
            "units":             units,
            "scale_x":           scale_x,
            "scale_y":           scale_y,
            "hist_min":          vmin,
            "hist_max":          vmax,
            "display_min":       vmin,
            "display_max":       vmax,
            "histogram_data":    _compute_histogram(img_u8, vmin, vmax),
            "histogram_visible": False,
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
        }

        self.markers = MarkerRegistry(self._push_markers,
                                      allowed=MarkerRegistry._KNOWN_2D)

    @staticmethod
    def _encode_bytes(arr: np.ndarray) -> str:
        import base64
        return base64.b64encode(arr.tobytes()).decode("ascii")

    def _push(self) -> None:
        """Serialise _state + markers and write to Figure trait."""
        if self._fig is None:
            return
        self._fig._push(self._id)

    def _push_markers(self) -> None:
        """Called by MarkerRegistry whenever markers change."""
        self._state["markers"] = self.markers.to_wire_list()
        self._push()

    def to_state_dict(self) -> dict:
        """Return a JSON-serialisable copy of the current state."""
        d = dict(self._state)
        d["markers"] = self.markers.to_wire_list()
        return d

    # ------------------------------------------------------------------
    # Data update
    # ------------------------------------------------------------------
    def update(self, data: np.ndarray,
               x_axis=None, y_axis=None, units: str | None = None) -> None:
        """Replace the image data."""
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
        if y_axis is not None:
            self._state["y_axis"] = np.asarray(y_axis, float).tolist()
            self._state["image_height"] = h
        if units is not None:
            self._state["units"] = units

        self._state.update({
            "image_b64":   self._encode_bytes(img_u8),
            "image_width":  w,
            "image_height": h,
            "hist_min":    vmin,
            "hist_max":    vmax,
            "display_min": vmin,
            "display_max": vmax,
            "histogram_data": _compute_histogram(img_u8, vmin, vmax),
            "colormap_data":  _build_colormap_lut(self._state["colormap_name"]),
        })
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
    def histogram_visible(self) -> bool:
        return self._state["histogram_visible"]

    @histogram_visible.setter
    def histogram_visible(self, val: bool) -> None:
        self._state["histogram_visible"] = bool(val)
        self._push()

    @property
    def colormap_name(self) -> str:
        return self._state["colormap_name"]

    @colormap_name.setter
    def colormap_name(self, name: str) -> None:
        self.set_colormap(name)

    # ------------------------------------------------------------------
    # Overlay widgets
    # ------------------------------------------------------------------
    def add_widget(self, kind: str, color: str = "#00e5ff", **kwargs) -> str:
        kind = kind.lower()
        valid = ("circle", "rectangle", "annular", "polygon", "label", "crosshair")
        if kind not in valid:
            raise ValueError(f"kind must be one of {valid}")
        wid = str(_uuid.uuid4())[:8]
        iw, ih = self._state["image_width"], self._state["image_height"]

        def _f(k, default): return float(kwargs.get(k, default))
        def _i(k, default): return int(kwargs.get(k, default))

        if kind == "circle":
            entry = {"id": wid, "type": "circle",
                     "cx": _f("cx", iw/2), "cy": _f("cy", ih/2),
                     "r":  _f("r",  iw*0.1), "color": color}
        elif kind == "rectangle":
            entry = {"id": wid, "type": "rectangle",
                     "x": _f("x", iw*0.25), "y": _f("y", ih*0.25),
                     "w": _f("w", iw*0.5),  "h": _f("h", ih*0.5), "color": color}
        elif kind == "annular":
            r_outer = _f("r_outer", iw*0.2)
            r_inner = _f("r_inner", iw*0.1)
            if r_inner >= r_outer:
                raise ValueError("r_inner must be < r_outer")
            entry = {"id": wid, "type": "annular",
                     "cx": _f("cx", iw/2), "cy": _f("cy", ih/2),
                     "r_outer": r_outer, "r_inner": r_inner, "color": color}
        elif kind == "polygon":
            raw = kwargs.get("vertices", [[iw*.25,ih*.25],[iw*.75,ih*.25],
                                           [iw*.75,ih*.75],[iw*.25,ih*.75]])
            verts = [[float(x), float(y)] for x, y in raw]
            if len(verts) < 3:
                raise ValueError("polygon needs >= 3 vertices")
            entry = {"id": wid, "type": "polygon", "vertices": verts, "color": color}
        elif kind == "crosshair":
            entry = {"id": wid, "type": "crosshair",
                     "cx": _f("cx", iw/2), "cy": _f("cy", ih/2), "color": color}
        else:  # label
            entry = {"id": wid, "type": "label",
                     "x": _f("x", iw*0.1), "y": _f("y", ih*0.1),
                     "text": str(kwargs.get("text", "Label")),
                     "fontsize": _i("fontsize", 14), "color": color}

        self._state["overlay_widgets"].append(entry)
        self._push()
        return wid

    def get_widget(self, wid: str) -> dict:
        for w in self._state["overlay_widgets"]:
            if w["id"] == wid:
                return dict(w)
        raise KeyError(wid)

    def remove_widget(self, wid: str) -> None:
        before = len(self._state["overlay_widgets"])
        self._state["overlay_widgets"] = [
            w for w in self._state["overlay_widgets"] if w["id"] != wid]
        if len(self._state["overlay_widgets"]) == before:
            raise KeyError(wid)
        self._push()

    def list_widgets(self) -> list:
        return [dict(w) for w in self._state["overlay_widgets"]]

    def clear_widgets(self) -> None:
        self._state["overlay_widgets"] = []
        self._push()

    # convenience widget helpers
    def add_annular_widget(self, cx=None, cy=None, r_outer=None, r_inner=None,
                           color="#00e5ff") -> str:
        iw, ih = self._state["image_width"], self._state["image_height"]
        return self.add_widget("annular", color=color,
                               cx=cx or iw/2, cy=cy or ih/2,
                               r_outer=r_outer or iw*0.2,
                               r_inner=r_inner or iw*0.1)

    def add_crosshair_widget(self, cx=None, cy=None, color="#00e5ff") -> str:
        iw, ih = self._state["image_width"], self._state["image_height"]
        return self.add_widget("crosshair", color=color,
                               cx=cx or iw/2, cy=cy or ih/2)

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
        return self._add_marker("circles", name, offsets=offsets, radius=radius,
                                facecolors=facecolors, edgecolors=edgecolors,
                                linewidths=linewidths, alpha=alpha,
                                hover_edgecolors=hover_edgecolors,
                                hover_facecolors=hover_facecolors,
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


# ---------------------------------------------------------------------------
# Plot1D
# ---------------------------------------------------------------------------

class Plot1D:
    """1-D line plot panel.

    Holds state in ``_state`` dict; every mutation pushes to Figure trait.
    Exposes the full Viewer1D-compatible API plus the new marker API.
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
        }

        self.markers = MarkerRegistry(self._push_markers,
                                      allowed=MarkerRegistry._KNOWN_1D)

    def _push(self) -> None:
        if self._fig is None:
            return
        self._fig._push(self._id)

    def _push_markers(self) -> None:
        self._state["markers"] = self.markers.to_wire_list()
        self._push()

    def to_state_dict(self) -> dict:
        d = dict(self._state)
        d["markers"] = self.markers.to_wire_list()
        return d

    # ------------------------------------------------------------------
    # Data update
    # ------------------------------------------------------------------
    def update(self, data: np.ndarray, x_axis=None,
               units: str | None = None, y_units: str | None = None) -> None:
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
        before = len(self._state["extra_lines"])
        self._state["extra_lines"] = [
            e for e in self._state["extra_lines"] if e["id"] != lid]
        if len(self._state["extra_lines"]) == before:
            raise KeyError(lid)
        self._push()

    def clear_lines(self) -> None:
        self._state["extra_lines"] = []
        self._push()

    # ------------------------------------------------------------------
    # Spans
    # ------------------------------------------------------------------
    def add_span(self, v0: float, v1: float,
                 axis: str = "x", color: str | None = None) -> str:
        sid = str(_uuid.uuid4())[:8]
        self._state["spans"].append({
            "id": sid, "v0": float(v0), "v1": float(v1),
            "axis": axis, "color": color,
        })
        self._push()
        return sid

    def remove_span(self, sid: str) -> None:
        before = len(self._state["spans"])
        self._state["spans"] = [
            s for s in self._state["spans"] if s["id"] != sid]
        if len(self._state["spans"]) == before:
            raise KeyError(sid)
        self._push()

    def clear_spans(self) -> None:
        self._state["spans"] = []
        self._push()

    # ------------------------------------------------------------------
    # Overlay widgets
    # ------------------------------------------------------------------
    def add_vline_widget(self, x: float, color: str = "#00e5ff") -> str:
        wid = str(_uuid.uuid4())[:8]
        self._state["overlay_widgets"].append(
            {"id": wid, "type": "vline", "x": float(x), "color": color})
        self._push()
        return wid

    def add_hline_widget(self, y: float, color: str = "#00e5ff") -> str:
        wid = str(_uuid.uuid4())[:8]
        self._state["overlay_widgets"].append(
            {"id": wid, "type": "hline", "y": float(y), "color": color})
        self._push()
        return wid

    def add_range_widget(self, x0: float, x1: float,
                         color: str = "#00e5ff") -> str:
        wid = str(_uuid.uuid4())[:8]
        self._state["overlay_widgets"].append(
            {"id": wid, "type": "range",
             "x0": float(x0), "x1": float(x1), "color": color})
        self._push()
        return wid

    def get_widget(self, wid: str) -> dict:
        for w in self._state["overlay_widgets"]:
            if w["id"] == wid:
                return dict(w)
        raise KeyError(wid)

    def remove_widget(self, wid: str) -> None:
        before = len(self._state["overlay_widgets"])
        self._state["overlay_widgets"] = [
            w for w in self._state["overlay_widgets"] if w["id"] != wid]
        if len(self._state["overlay_widgets"]) == before:
            raise KeyError(wid)
        self._push()

    def list_widgets(self) -> list:
        return [dict(w) for w in self._state["overlay_widgets"]]

    def clear_widgets(self) -> None:
        self._state["overlay_widgets"] = []
        self._push()

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
    # Marker API  (matplotlib-style)
    # ------------------------------------------------------------------
    def _add_marker(self, mtype: str, name: str | None, **kwargs) -> "MarkerGroup":  # noqa: F821
        return self.markers.add(mtype, name, **kwargs)

    def add_points(self, offsets, name=None, *, sizes=5,
                   facecolors=None, edgecolors="#ff0000",
                   linewidths=1.5, alpha=0.3,
                   hover_edgecolors=None, hover_facecolors=None,
                   labels=None, label=None) -> "MarkerGroup":  # noqa: F821
        return self._add_marker("points", name, offsets=offsets, sizes=sizes,
                                facecolors=facecolors, edgecolors=edgecolors,
                                linewidths=linewidths, alpha=alpha,
                                hover_edgecolors=hover_edgecolors,
                                hover_facecolors=hover_facecolors,
                                labels=labels, label=label)

    def add_vlines(self, offsets, name=None, *,
                   color="#ff0000", linewidths=1.5,
                   hover_edgecolors=None,
                   labels=None, label=None) -> "MarkerGroup":  # noqa: F821
        return self._add_marker("vlines", name, offsets=offsets,
                                color=color, linewidths=linewidths,
                                hover_edgecolors=hover_edgecolors,
                                labels=labels, label=label)

    def add_hlines(self, offsets, name=None, *,
                   color="#ff0000", linewidths=1.5,
                   hover_edgecolors=None,
                   labels=None, label=None) -> "MarkerGroup":  # noqa: F821
        return self._add_marker("hlines", name, offsets=offsets,
                                color=color, linewidths=linewidths,
                                hover_edgecolors=hover_edgecolors,
                                labels=labels, label=label)

    def add_lines(self, segments, name=None, *,
                  edgecolors="#ff0000", linewidths=1.5,
                  hover_edgecolors=None,
                  labels=None, label=None) -> "MarkerGroup":  # noqa: F821
        return self._add_marker("lines", name, segments=segments,
                                edgecolors=edgecolors, linewidths=linewidths,
                                hover_edgecolors=hover_edgecolors,
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



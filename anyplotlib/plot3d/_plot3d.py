"""
plot3d/_plot3d.py
=================
3-D surface / scatter / line plot panel.
"""

from __future__ import annotations

from typing import Callable

import numpy as np

from anyplotlib._base_plot import _BasePlot
from anyplotlib.callbacks import CallbackRegistry
from anyplotlib._utils import _arr_to_b64, _build_colormap_lut


def _triangulate_grid(rows: int, cols: int) -> list:
    """Return a flat list of [i0, i1, i2] triangle indices for an (rows×cols) grid."""
    faces = []
    for r in range(rows - 1):
        for c in range(cols - 1):
            i = r * cols + c
            faces.append([i,       i + 1,       i + cols])
            faces.append([i + 1,   i + cols + 1, i + cols])
    return faces


def _colors_to_u8(colors, n: int) -> np.ndarray:
    """Convert per-point colours to an (N, 3) uint8 RGB array.

    Accepts a sequence of CSS hex strings (``"#rrggbb"``) or an (N, 3)
    numeric array (floats 0–1, or 0–255).
    """
    if isinstance(colors, (list, tuple)) and colors and isinstance(colors[0], str):
        out = np.empty((len(colors), 3), dtype=np.uint8)
        for i, c in enumerate(colors):
            h = c.lstrip("#")
            if len(h) != 6:
                raise ValueError(f"colors[{i}]: expected '#rrggbb', got {c!r}")
            out[i] = [int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)]
    else:
        arr = np.asarray(colors)
        if arr.ndim != 2 or arr.shape[1] != 3:
            raise ValueError(f"colors must be (N, 3) or a list of hex strings, "
                             f"got shape {arr.shape}")
        if arr.dtype != np.uint8:
            arr = arr.astype(np.float64)
            if arr.max() <= 1.0:
                arr = arr * 255.0
            arr = np.clip(arr, 0, 255)
        out = arr.astype(np.uint8)
    if len(out) != n:
        raise ValueError(f"got {len(out)} colors for {n} points")
    return out


def _geometry_state(geom_type: str, x, y, z, bounds=None) -> dict:
    """Validate x/y/z for *geom_type* and return the wire-format state fields.

    Shared by ``Plot3D.__init__`` and ``Plot3D.set_data`` so geometry
    validation and encoding live in exactly one place.

    Parameters
    ----------
    bounds : ((xmin, xmax), (ymin, ymax), (zmin, zmax)) or None
        Override the auto-computed data bounds.  The JS renderer normalises
        geometry into these bounds, so fixing them keeps the origin and
        scale stable — essential for direction vectors on a unit sphere
        (use ``((-1, 1),) * 3``) or when streaming data of varying extent.
    """
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
            raise ValueError(f"{geom_type} x, y, z must be 1-D arrays")
        if not (len(x) == len(y) == len(z)):
            raise ValueError("x, y, z must have the same length")
        xf, yf, zf = x, y, z
        faces_list = []

    # Encode geometry as b64 (float32 saves 50 % wire size vs float64)
    verts_arr = np.column_stack([xf, yf, zf]).astype(np.float32)   # (N, 3)
    zvals_arr = zf.astype(np.float32)                              # (N,)
    faces_arr = (np.asarray(faces_list, dtype=np.int32).reshape(-1, 3)
                 if faces_list else np.empty((0, 3), dtype=np.int32))

    if bounds is not None:
        (bx0, bx1), (by0, by1), (bz0, bz1) = bounds
        data_bounds = {"xmin": float(bx0), "xmax": float(bx1),
                       "ymin": float(by0), "ymax": float(by1),
                       "zmin": float(bz0), "zmax": float(bz1)}
    else:
        data_bounds = {
            "xmin": float(xf.min()), "xmax": float(xf.max()),
            "ymin": float(yf.min()), "ymax": float(yf.max()),
            "zmin": float(zf.min()), "zmax": float(zf.max()),
        }

    return {
        "vertices_b64":   _arr_to_b64(verts_arr, np.float32),
        "vertices_count": len(verts_arr),
        "faces_b64":      _arr_to_b64(faces_arr, np.int32),
        "faces_count":    len(faces_arr),
        "z_values_b64":   _arr_to_b64(zvals_arr, np.float32),
        "data_bounds":    data_bounds,
    }


class Plot3D(_BasePlot):
    """3-D plot panel.

    Supports four geometry types:

    * ``'surface'``  – triangulated surface, Z-coloured via colormap.
    * ``'scatter'``  – point cloud; single colour or per-point ``colors``.
    * ``'line'``     – connected line through 3-D points.
    * ``'voxels'``   – shaded translucent cubes at the given centres;
      voxels lying on a :class:`~anyplotlib.PlaneWidget` slice render more
      opaque.

    A single point can be emphasised with :meth:`set_highlight` (e.g. the
    "current" orientation in an IPF explorer), and ``bounds=`` fixes the
    axes extents for origin-true geometry such as unit vectors on a sphere.
    Draggable :class:`~anyplotlib.PlaneWidget` slice selectors are added
    with :meth:`add_widget`.

    Created by :meth:`Axes.plot_surface`, :meth:`Axes.scatter3d`,
    and :meth:`Axes.plot3d`.

    Not an anywidget.  Holds state in ``_state`` dict; every mutation
    calls ``_push()`` which writes to the parent Figure's panel trait.
    """

    #: Heavy, rarely-changing state keys routed to the separate geometry
    #: channel — re-sent only when their content changes, so view updates
    #: (highlight / camera / planes) never re-transmit them.
    _GEOM_KEYS = frozenset({
        "vertices_b64", "faces_b64", "z_values_b64", "point_colors_b64",
        "colormap_data",
    })

    def __init__(self, geom_type: str,
                 x, y, z, *,
                 colormap: str = "viridis",
                 color: str = "#4fc3f7",
                 colors=None,
                 point_size: float = 4.0,
                 linewidth: float = 1.5,
                 x_label: str = "x",
                 y_label: str = "y",
                 z_label: str = "z",
                 azimuth: float = -60.0,
                 elevation: float = 30.0,
                 zoom: float = 1.0,
                 bounds=None,
                 voxel_size: float = 1.0,
                 alpha: float | None = None,
                 gpu: str | bool = "auto"):
        self._id:  str = ""
        self._fig: object = None
        self._gpu_active: bool = False

        geom_type = geom_type.lower()
        if geom_type not in ("surface", "scatter", "line", "voxels"):
            raise ValueError(
                "geom_type must be 'surface', 'scatter', 'line', or 'voxels'")

        cmap_lut = _build_colormap_lut(colormap)
        self._bounds = bounds
        geom = _geometry_state(geom_type, x, y, z, bounds=bounds)

        point_colors_b64 = ""
        if colors is not None:
            if geom_type not in ("scatter", "voxels"):
                raise ValueError(
                    "per-point colors are only supported for scatter/voxels")
            point_colors_b64 = _arr_to_b64(
                _colors_to_u8(colors, geom["vertices_count"]), np.uint8)

        # The canvas budget is ~20k cubes; WebGPU (gpu="auto"/True) handles
        # far more, so only warn when GPU is explicitly disabled.
        gpu_off = gpu is False or str(gpu) == "off"
        if geom_type == "voxels" and gpu_off and geom["vertices_count"] > 20_000:
            import warnings
            warnings.warn(
                f"Rendering {geom['vertices_count']:,} voxels with gpu=False — "
                f"the canvas renderer budgets roughly 3–6 µs per cube, so "
                f"interactive frame rates need ≤ ~20k. Either allow WebGPU "
                f"(gpu='auto'), downsample the volume (stride slicing) or "
                f"extract boundary voxels, and show full-resolution data in "
                f"linked 2-D slice panels instead.",
                RuntimeWarning, stacklevel=3)

        self._state: dict = {
            "kind":          "3d",
            "geom_type":     geom_type,
            **geom,
            "colormap_name": colormap,
            "colormap_data": cmap_lut,
            "color":         color,
            "point_colors_b64": point_colors_b64,
            # Highlight point: {"x","y","z","color","size"} or None
            "highlight":     None,
            # Reference sphere: {"radius","color","alpha","wireframe"} or None
            "sphere":        None,
            # WebGPU activation policy: 'auto' (GPU above a point threshold),
            # 'always', or 'off'.  Falls back to Canvas2D whenever the GPU is
            # unavailable; query the result via the gpu_active property.
            "gpu_mode":          ("always" if gpu is True else
                                  "off" if gpu is False else str(gpu)),
            # Voxel rendering (geom_type == 'voxels')
            "voxel_size":        float(voxel_size),
            "voxel_alpha":       float(alpha) if alpha is not None else 0.3,
            "voxel_slice_alpha": 0.95,
            # Interactive overlay widgets (PlaneWidget slice selectors)
            "overlay_widgets":   [],
            "point_size":    float(point_size),
            "linewidth":     float(linewidth),
            "title":         "",
            "x_label":       x_label,
            "y_label":       y_label,
            "z_label":       z_label,
            "axis_visible":  True,
            "azimuth":       float(azimuth),
            "elevation":     float(elevation),
            "zoom":          float(zoom),
            "_default_azimuth":   float(azimuth),
            "_default_elevation": float(elevation),
            "_default_zoom":      float(zoom),
            "_view_from_python":  False,
            "pointer_settled_ms":    0,
            "pointer_settled_delta": 4,
        }
        self.callbacks = CallbackRegistry()
        self._widgets: dict = {}

    # ------------------------------------------------------------------
    def _push(self) -> None:
        if self._fig is None:
            return
        self._state["overlay_widgets"] = [w.to_dict() for w in self._widgets.values()]
        self._fig._push(self._id)

    def _push_fields(self, **fields) -> None:
        """Targeted update of small state fields without re-sending geometry.

        For a heavy voxel/scatter panel, moving the highlight or camera would
        otherwise re-transmit hundreds of KB of unchanged ``vertices_b64`` —
        this ships only *fields* via the lightweight event channel.
        """
        self._state.update(fields)
        if self._fig is not None:
            self._fig._push_panel_fields(self._id, fields)

    # ------------------------------------------------------------------
    # Interactive widgets (3-D)
    # ------------------------------------------------------------------
    def add_widget(self, kind: str, **kwargs):
        """Add an interactive overlay widget to this 3-D panel.

        Currently supports ``"plane"`` — a draggable axis-aligned slice
        plane (see :class:`~anyplotlib.PlaneWidget`)::

            pw = vol.add_widget("plane", axis="z", position=24)

            @pw.add_event_handler("pointer_move")
            def on_drag(event):
                resliced(int(round(pw.position)))
        """
        if kind.lower() != "plane":
            raise ValueError("3-D panels currently support only 'plane' widgets")
        from anyplotlib.widgets import PlaneWidget
        widget = PlaneWidget(lambda: None, **kwargs)
        widget._push_fn = self._make_widget_push_fn(widget)
        self._widgets[widget.id] = widget
        self._push()
        return widget

    def remove_widget(self, wid) -> None:
        """Remove a widget by ID string or Widget instance."""
        from anyplotlib.widgets import Widget
        if isinstance(wid, Widget):
            wid = wid.id
        if wid not in self._widgets:
            raise KeyError(wid)
        del self._widgets[wid]
        self._push()

    def list_widgets(self) -> list:
        """Return a list of all active widget objects on this panel."""
        return list(self._widgets.values())

    # ------------------------------------------------------------------
    def set_voxel_alpha(self, alpha: float, slice_alpha: float | None = None) -> None:
        """Set voxel transparency (geom_type ``'voxels'``).

        Parameters
        ----------
        alpha : float
            Base opacity (0–1) for voxels not on any plane widget.
        slice_alpha : float, optional
            Opacity for voxels lying on a :class:`~anyplotlib.PlaneWidget`
            slice.  ``None`` keeps the current value (default 0.95).
        """
        self._state["voxel_alpha"] = float(alpha)
        if slice_alpha is not None:
            self._state["voxel_slice_alpha"] = float(slice_alpha)
        self._push()

    def to_state_dict(self) -> dict:
        return dict(self._state)

    # ------------------------------------------------------------------
    @property
    def gpu_active(self) -> bool:
        """``True`` if this panel is currently rendering geometry on the GPU.

        Reflects the JS renderer's decision after the first frame: WebGPU is
        used only when available and when the panel's ``gpu`` policy and
        point count call for it.  Always ``False`` on the Canvas2D fallback
        path (no ``navigator.gpu``, no adapter, device lost, or ``gpu=False``).
        """
        return self._gpu_active

    def _set_gpu_active(self, active: bool) -> None:
        """Internal: called from the Figure's gpu_status event dispatch."""
        self._gpu_active = bool(active)

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
        """Set the camera azimuth (°) and/or elevation (°).

        Uses a targeted field push so re-aiming the camera never re-transmits
        the panel's geometry — important for large voxel/scatter panels.
        """
        fields = {"_view_from_python": True}
        if azimuth   is not None: fields["azimuth"]   = float(azimuth)
        if elevation is not None: fields["elevation"] = float(elevation)
        self._push_fields(**fields)
        self._state["_view_from_python"] = False

    def set_zoom(self, zoom: float) -> None:
        self._push_fields(zoom=float(zoom), _view_from_python=True)
        self._state["_view_from_python"] = False

    def reset_view(self) -> None:
        """Restore the camera to the angles/zoom set at construction time."""
        with self._python_view_push():
            self._state["azimuth"]   = self._state["_default_azimuth"]
            self._state["elevation"] = self._state["_default_elevation"]
            self._state["zoom"]      = self._state["_default_zoom"]

    def set_xlabel(self, label: str, fontsize: float | None = None) -> None:
        """Set the x-axis label (mini-TeX allowed; default size 11 px)."""
        self._set_label("x_label", label, "x_label_size", fontsize)

    def set_ylabel(self, label: str, fontsize: float | None = None) -> None:
        """Set the y-axis label (mini-TeX allowed; default size 11 px)."""
        self._set_label("y_label", label, "y_label_size", fontsize)

    def set_zlabel(self, label: str, fontsize: float | None = None) -> None:
        """Set the z-axis label (mini-TeX allowed; default size 11 px)."""
        self._set_label("z_label", label, "z_label_size", fontsize)

    def get_xlim(self) -> tuple:
        """Return the data x range as ``(xmin, xmax)``."""
        b = self._state["data_bounds"]
        return (b["xmin"], b["xmax"])

    def get_ylim(self) -> tuple:
        """Return the data y range as ``(ymin, ymax)``."""
        b = self._state["data_bounds"]
        return (b["ymin"], b["ymax"])

    def get_zlim(self) -> tuple:
        """Return the data z range as ``(zmin, zmax)``."""
        b = self._state["data_bounds"]
        return (b["zmin"], b["zmax"])

    def set_data(self, x, y, z) -> None:
        """Replace the geometry data (same shape rules as the constructor).

        Bounds given at construction time (``bounds=``) are preserved.
        """
        self._state.update(_geometry_state(
            self._state["geom_type"], x, y, z, bounds=self._bounds))
        self._push()

    def set_point_colors(self, colors) -> None:
        """Set (or clear) per-point colours on a scatter panel.

        Parameters
        ----------
        colors : list of "#rrggbb" strings, (N, 3) array, or None
            One colour per point.  Floats are interpreted as 0–1 (or 0–255
            when the max exceeds 1).  ``None`` reverts to the single
            ``color`` for all points.
        """
        if self._state["geom_type"] != "scatter":
            raise ValueError("per-point colors are only supported for scatter")
        if colors is None:
            self._state["point_colors_b64"] = ""
        else:
            n = self._state["vertices_count"]
            self._state["point_colors_b64"] = _arr_to_b64(
                _colors_to_u8(colors, n), np.uint8)
        self._push()

    def set_highlight(self, x: float, y: float, z: float, *,
                      color: str = "#ff1744", size: float = 7.0) -> None:
        """Mark one 3-D point with an emphasised dot drawn on top.

        The highlight is independent of the panel's geometry — use it to
        flag the "current" item in a point cloud or on a surface (e.g. the
        orientation under a crosshair in an IPF explorer).  Points on the
        far side of the data are drawn semi-transparent as a depth cue.

        Parameters
        ----------
        x, y, z : float
            Position in data coordinates.
        color : str, optional
            CSS colour of the dot and ring.  Default ``"#ff1744"``.
        size : float, optional
            Dot radius in pixels.  Default 7.

        See Also
        --------
        clear_highlight : Remove the highlight.
        """
        self._push_fields(highlight={
            "x": float(x), "y": float(y), "z": float(z),
            "color": str(color), "size": float(size),
        })

    def clear_highlight(self) -> None:
        """Remove the highlight point set by :meth:`set_highlight`."""
        self._push_fields(highlight=None)

    def set_sphere(self, radius: float = 1.0, *,
                   color: str = "#9e9e9e",
                   alpha: float = 0.15,
                   wireframe: bool = True) -> None:
        """Draw an origin-centred reference sphere behind the data.

        Rendered as a shaded silhouette disk plus latitude/longitude
        wireframe arcs (far-side arcs dimmed).  Scatter points on the far
        side of the sphere are also dimmed, so a point cloud on the sphere
        reads with correct depth — ideal for inverse-pole-figure /
        orientation plots of unit vectors.

        Assumes origin-centred, isotropic bounds — pass
        ``bounds=((-r, r),) * 3`` to the constructor so the sphere's
        screen silhouette is a true circle.

        Parameters
        ----------
        radius : float, optional
            Sphere radius in data units.  Default 1 (unit sphere).
        color : str, optional
            Base CSS colour of the shading and wireframe.  Default grey.
        alpha : float, optional
            Opacity of the shaded silhouette (0–1).  Default 0.15.
        wireframe : bool, optional
            Draw latitude/longitude arcs.  Default True.

        See Also
        --------
        clear_sphere : Remove the reference sphere.
        """
        self._state["sphere"] = {
            "radius": float(radius), "color": str(color),
            "alpha": float(alpha), "wireframe": bool(wireframe),
        }
        self._push()

    def clear_sphere(self) -> None:
        """Remove the reference sphere set by :meth:`set_sphere`."""
        self._state["sphere"] = None
        self._push()

    def __repr__(self) -> str:
        geom = self._state.get("geom_type", "?")
        n = self._state.get("vertices_count", 0)
        return f"Plot3D(geom={geom!r}, n_vertices={n})"

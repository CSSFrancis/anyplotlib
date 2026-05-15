"""
plot3d/_plot3d.py
=================
3-D surface / scatter / line plot panel.
"""

from __future__ import annotations

from typing import Callable

import numpy as np

from anyplotlib.callbacks import CallbackRegistry, _EventMixin
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


class Plot3D(_EventMixin):
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
            "pointer_settled_ms":    0,
            "pointer_settled_delta": 4,
        }
        self.callbacks = CallbackRegistry()

    def _configure_pointer_settled(self, ms: int, delta: float) -> None:
        self._state["pointer_settled_ms"]    = ms
        self._state["pointer_settled_delta"] = delta
        self._push()

    # ------------------------------------------------------------------
    def _push(self) -> None:
        if self._fig is None:
            return
        self._fig._push(self._id)

    def to_state_dict(self) -> dict:
        return dict(self._state)

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

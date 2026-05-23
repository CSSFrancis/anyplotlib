"""
plot2d/_plotmesh.py
===================
pcolormesh panel (non-uniform grid).
"""

from __future__ import annotations

import numpy as np

from anyplotlib.markers import MarkerRegistry
from anyplotlib.plot2d._plot2d import Plot2D
from anyplotlib._utils import _normalize_image, _build_colormap_lut, _resample_mesh


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

    def __repr__(self) -> str:
        xe = self._state.get("x_axis", [])
        ye = self._state.get("y_axis", [])
        cols = max(0, len(xe) - 1)
        rows = max(0, len(ye) - 1)
        cmap = self._state.get("colormap_name", "?")
        return f"PlotMesh({rows}×{cols}, cmap={cmap!r})"

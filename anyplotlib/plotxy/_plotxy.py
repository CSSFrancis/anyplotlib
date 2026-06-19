"""
_plotxy.py — ``PlotXY``: a blank **data-coordinate 2-D axis**.

Where :class:`~anyplotlib.plot1d.Plot1D` is a curve over a (monotonic) x-axis,
``PlotXY`` is a coordinate canvas in the matplotlib sense: you set ``xlim`` /
``ylim`` (+ optional ``aspect="equal"``) and draw ``scatter`` / ``plot`` /
``fill`` / ``text`` as **collection-style artists** in data coordinates — the
surface orix's ``StereographicPlot`` (and an IPF triangle) needs.

It is built on ``Plot1D`` because the 1-D marker collections
(``add_points`` / ``add_lines`` / ``add_polygons`` / ``add_texts``) already map
through the 1-D data→canvas transform, which is exactly matplotlib's
``transLimits → transAxes`` (``_axisValToFrac`` for x + ``_valToPy1d`` for y →
unit box → panel rect). The primary curve is hidden (``alpha=0``); the markers
ARE the content. ``aspect="equal"`` is honoured by the renderer's xy-aspect step
(``state["aspect"]``); without it the data simply fills the panel (auto aspect).

Mirrors matplotlib: ``scatter`` → a ``PathCollection`` (offsets + per-point
colours/sizes), ``plot`` → ``Line2D``, ``fill`` → ``Polygon``, ``text`` →
``Text``.
"""
from __future__ import annotations

import numpy as np

from anyplotlib._utils import _build_colormap_lut
from anyplotlib.plot1d._plot1d import Plot1D


def _colseq(c, n):
    """A matplotlib-style colour arg → ``list[str]`` of length ``n`` (or None)."""
    if c is None:
        return None
    if isinstance(c, str):
        return [c] * n
    return [str(x) for x in c]


class PlotXY(Plot1D):
    """Coordinate-only 2-D axis: ``scatter`` / ``plot`` / ``fill`` / ``text`` in
    data coordinates, with ``set_xlim`` / ``set_ylim`` / ``set_aspect``."""

    def __init__(self, *, xlim=(0.0, 1.0), ylim=(0.0, 1.0), aspect=None,
                 units: str = "", y_units: str = ""):
        super().__init__(
            np.zeros(2, dtype=float),
            x_axis=np.asarray([xlim[0], xlim[1]], dtype=float),
            units=units, y_units=y_units, alpha=0.0,        # hidden primary curve
        )
        s = self._state
        s["line_alpha"] = 0.0
        s["data_min"] = float(ylim[0])
        s["data_max"] = float(ylim[1])
        s["y_range"] = [float(ylim[0]), float(ylim[1])]
        s["aspect"] = "equal" if aspect == "equal" else None

    # ── view (data limits = the transData domain) ────────────────────────────
    def set_xlim(self, xmin: float, xmax: float) -> None:
        self._state["x_axis"] = np.asarray([float(xmin), float(xmax)], dtype=float)
        self._push()

    def set_ylim(self, ymin: float, ymax: float) -> None:
        self._state["y_range"] = [float(ymin), float(ymax)]
        self._state["data_min"] = float(ymin)
        self._state["data_max"] = float(ymax)
        self._push()

    def get_xlim(self) -> tuple:
        x = self._state["x_axis"]
        return (float(x[0]), float(x[-1]))

    def get_ylim(self) -> tuple:
        yr = self._state["y_range"]
        return (float(yr[0]), float(yr[1]))

    def set_aspect(self, aspect) -> None:
        """``"equal"`` → one data unit is the same pixel length on x and y
        (matplotlib ``apply_aspect``); ``"auto"`` / ``None`` → fill the panel."""
        self._state["aspect"] = "equal" if aspect == "equal" else None
        self._push()

    def get_aspect(self):
        return self._state.get("aspect")

    # ── matplotlib-parity artists (each returns its collection MarkerGroup) ──
    def scatter(self, x, y, *, s=8, c=None, facecolors=None,
                edgecolors="#1f77b4", alpha=1.0, name=None):
        """Data-coord scatter → a ``PathCollection``-style points group."""
        x = np.asarray(x, float).ravel()
        y = np.asarray(y, float).ravel()
        offs = np.column_stack([x, y])
        face = _colseq(c if c is not None else facecolors, len(x))
        return self.add_points(offs, name=name, sizes=s, color=edgecolors,
                               facecolors=face, alpha=alpha)

    def plot(self, x, y, *, color="#1f77b4", linewidth=1.5, name=None):
        """Data-coord polyline → a ``Line2D``-style lines group."""
        pts = np.column_stack([np.asarray(x, float).ravel(),
                               np.asarray(y, float).ravel()])
        segs = [[pts[i].tolist(), pts[i + 1].tolist()] for i in range(len(pts) - 1)]
        return self.add_lines(segs, name=name, edgecolors=color, linewidths=linewidth)

    def fill(self, x, y, *, facecolor=None, edgecolor="#1f77b4", alpha=0.3,
             linewidth=1.5, name=None):
        """Data-coord filled polygon → a ``Polygon``-style group."""
        verts = np.column_stack([np.asarray(x, float).ravel(),
                                 np.asarray(y, float).ravel()]).tolist()
        return self.add_polygons([verts], name=name, facecolors=facecolor,
                                 edgecolors=edgecolor, alpha=alpha,
                                 linewidths=linewidth)

    def text(self, x, y, s, *, color="#000000", fontsize=12, name=None):
        """Data-coord text → a ``Text``-style group (one label)."""
        return self.add_texts([[float(x), float(y)]], [str(s)], name=name,
                              color=color, fontsize=fontsize)

    def pcolormesh(self, x, y, c, *, cmap="viridis", vmin=None, vmax=None,
                   edgecolor=None, alpha=1.0, clip_path=None, name=None):
        """Data-coord quad mesh — matplotlib ``pcolormesh``.

        ``x``/``y`` are the ``(N+1, M+1)`` cell-corner grids and ``c`` the
        ``(N, M)`` field: either a scalar array (mapped through *cmap* between
        *vmin*/*vmax*) or an array of CSS colour strings. Masked / non-finite
        cells are skipped — so an ``orix`` pole-density histogram (masked
        outside the fundamental sector) clips itself to the sector. Drawn as
        one polygon ``MarkerGroup`` with per-cell face colours (a
        ``PathCollection``); the edges default to the face colour for a
        seamless heatmap.

        ``clip_path`` is an optional ``(K, 2)`` data-coord polygon the mesh is
        clipped to (matplotlib ``set_clip_path``) — pass the curved sector
        boundary so the edge cells don't overflow it.
        """
        x = np.asarray(x, float)
        y = np.asarray(y, float)
        cm = np.ma.asarray(c)
        nr, nc = cm.shape
        mask = np.ma.getmaskarray(cm)

        if cm.dtype.kind in "fiub":               # scalar field → LUT
            vals = np.ma.filled(cm.astype(float), np.nan)
            finite = vals[np.isfinite(vals)]
            lo = float(vmin) if vmin is not None else (
                float(finite.min()) if finite.size else 0.0)
            hi = float(vmax) if vmax is not None else (
                float(finite.max()) if finite.size else 1.0)
            lut = _build_colormap_lut(cmap)
            span = (hi - lo) or 1.0

            def _color(i, j):
                v = vals[i, j]
                if not np.isfinite(v):
                    return None
                t = min(1.0, max(0.0, (v - lo) / span))
                r, g, b = lut[int(round(t * 255))]
                return f"#{r:02x}{g:02x}{b:02x}"
        else:                                     # already colour strings
            def _color(i, j):
                return None if mask[i, j] else str(cm[i, j])

        verts, faces = [], []
        for i in range(nr):
            for j in range(nc):
                if mask[i, j]:
                    continue
                col = _color(i, j)
                if col is None:
                    continue
                verts.append([[x[i, j],     y[i, j]],
                              [x[i + 1, j], y[i + 1, j]],
                              [x[i + 1, j + 1], y[i + 1, j + 1]],
                              [x[i, j + 1], y[i, j + 1]]])
                faces.append(col)

        edges = faces if edgecolor is None else edgecolor
        return self.add_polygons(verts, name=name, facecolors=faces,
                                 edgecolors=edges, alpha=alpha, linewidths=0.5,
                                 clip_path=clip_path)

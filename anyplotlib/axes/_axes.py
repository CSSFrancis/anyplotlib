"""
axes/_axes.py
=============
Grid-cell container that owns a single plot panel.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from anyplotlib.plot1d import Plot1D, PlotBar
from anyplotlib.plot2d import Plot2D, PlotMesh
from anyplotlib.plot3d import Plot3D

if TYPE_CHECKING:
    from anyplotlib.figure import Figure
    from anyplotlib.figure._gridspec import SubplotSpec


class Axes:
    """A single grid cell in a Figure.

    Returned by Figure.add_subplot() and Figure.subplots().
    Call .imshow() or .plot() to attach a data plot and get back
    a Plot2D or Plot1D object.
    """

    def __init__(self, fig: "Figure", spec: "SubplotSpec"):  # noqa: F821
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
        data : np.ndarray, shape (H, W) or (H, W, 3|4)
            Image data.  2-D arrays are colormapped.  ``(H, W, 3)`` /
            ``(H, W, 4)`` arrays render as true-colour RGB(A): uint8 values
            are used directly; floats are interpreted as 0–1 (or 0–255 when
            the max exceeds 1).  ``cmap``/``vmin``/``vmax`` and the colorbar
            do not apply to RGB images.
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
                  colors=None,
                  point_size: float = 4.0,
                  x_label: str = "x", y_label: str = "y", z_label: str = "z",
                  azimuth: float = -60.0, elevation: float = 30.0,
                  zoom: float = 1.0,
                  bounds=None,
                  gpu: str | bool = "auto") -> "Plot3D":
        """Attach a 3-D scatter plot to this axes cell.

        Parameters
        ----------
        x, y, z : array-like, shape (N,)  Point coordinates.
        color : str, optional  CSS colour for all points.
        colors : list of "#rrggbb" or (N, 3) array, optional
            Per-point colours (overrides *color*).  Floats are 0–1.
        point_size : float, optional  Radius of each point in pixels.
        x_label, y_label, z_label : str, optional  Axis labels.
        azimuth, elevation : float, optional  Initial camera angles in degrees.
        zoom : float, optional  Initial zoom factor.
        bounds : ((xmin, xmax), (ymin, ymax), (zmin, zmax)), optional
            Fix the axes bounds instead of fitting them to the data — keeps
            the origin and scale stable, e.g. ``((-1, 1),) * 3`` for unit
            vectors on a sphere.
        gpu : ``"auto"`` | bool, optional
            WebGPU acceleration policy.  ``"auto"`` (default) renders on the
            GPU when available and the cloud exceeds ~20k points, else
            Canvas2D; ``True`` always attempts GPU; ``False`` forces Canvas2D.
            Falls back silently when WebGPU is unavailable — check
            :attr:`Plot3D.gpu_active` for the actual path.

        Returns
        -------
        Plot3D
        """
        plot = Plot3D("scatter", x, y, z, color=color, colors=colors,
                      point_size=point_size,
                      x_label=x_label, y_label=y_label, z_label=z_label,
                      azimuth=azimuth, elevation=elevation, zoom=zoom,
                      bounds=bounds, gpu=gpu)
        self._attach(plot)
        return plot

    def voxels(self, x, y, z, *,
               colors=None,
               color: str = "#4fc3f7",
               size: float = 1.0,
               alpha: float = 0.3,
               x_label: str = "x", y_label: str = "y", z_label: str = "z",
               azimuth: float = -60.0, elevation: float = 30.0,
               zoom: float = 1.0,
               bounds=None,
               gpu: str | bool = "auto") -> "Plot3D":
        """Attach a 3-D voxel plot: shaded translucent cubes at the centres.

        Designed for volumetric grain/label maps.  Add draggable
        :class:`~anyplotlib.PlaneWidget` slice selectors with
        ``plot.add_widget("plane", axis=..., position=...)`` — voxels lying
        on a plane render at ``voxel_slice_alpha`` (more opaque) so the
        selected slice pops out of the translucent volume.

        **Large volumes** With WebGPU (``gpu="auto"``, the default, active
        above ~8k cubes when a GPU is present) hundreds of thousands of
        voxels render interactively via instancing.  On the Canvas2D
        fallback the budget is ~20k cubes (~3–6 µs each); a warning is
        emitted above that *only when* ``gpu=False``.  For volumes too large
        even for the GPU (e.g. a 512 × 512 × 300 tomogram = 78M voxels),
        downsample with stride slicing (``vol[::s, ::s, ::s]``) or draw only
        grain-boundary voxels, and pair the 3-D overview with linked
        full-resolution 2-D slice panels — the voxel grain explorer example
        demonstrates this pattern.

        Parameters
        ----------
        x, y, z : array-like, shape (N,)
            Voxel centre coordinates.
        colors : list of "#rrggbb" or (N, 3) array, optional
            Per-voxel colours (overrides *color*).  Floats are 0–1.
        color : str, optional  Single CSS colour when *colors* is omitted.
        size : float, optional  Cube edge length in data units.  Default 1.
        alpha : float, optional
            Base voxel opacity (0–1).  Default 0.3.  See also
            :meth:`Plot3D.set_voxel_alpha`.
        x_label, y_label, z_label : str, optional  Axis labels.
        azimuth, elevation : float, optional  Initial camera angles in degrees.
        zoom : float, optional  Initial zoom factor.
        bounds : ((xmin, xmax), (ymin, ymax), (zmin, zmax)), optional
            Fix the axes bounds instead of fitting them to the data.
        gpu : ``"auto"`` | bool, optional
            WebGPU acceleration policy.  ``"auto"`` (default) renders cubes
            on the GPU when available and the set exceeds ~8k; ``True`` always
            attempts GPU; ``False`` forces Canvas2D.  Falls back silently when
            WebGPU is unavailable — see :attr:`Plot3D.gpu_active`.

        Returns
        -------
        Plot3D
        """
        plot = Plot3D("voxels", x, y, z, color=color, colors=colors,
                      voxel_size=size, alpha=alpha,
                      x_label=x_label, y_label=y_label, z_label=z_label,
                      azimuth=azimuth, elevation=elevation, zoom=zoom,
                      bounds=bounds, gpu=gpu)
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
             label: str = "",
             yscale: str = "linear") -> "Plot1D":
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
            import anyplotlib as apl

            x = np.linspace(0, 4 * np.pi, 512)
            fig, ax = apl.subplots(1, 1, figsize=(620, 320))
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
                     label=label, yscale=yscale)
        self._attach(plot)
        return plot

    def semilogy(self, data: np.ndarray,
                 axes: list | None = None, **kwargs) -> "Plot1D":
        """Attach a 1-D line with a logarithmic y-axis."""
        kwargs.setdefault("yscale", "log")
        return self.plot(data, axes=axes, **kwargs)

    def axes2d(self, *, xlim=(0.0, 1.0), ylim=(0.0, 1.0), aspect=None,
               units: str = "", y_units: str = "") -> "PlotXY":   # noqa: F821
        """Attach a blank **data-coordinate 2-D axis** (`PlotXY`).

        Unlike :meth:`plot` (a curve over a monotonic x-axis), this is a
        coordinate canvas: set ``xlim`` / ``ylim`` (+ optional ``aspect="equal"``)
        and draw :meth:`~anyplotlib.plotxy.PlotXY.scatter` / ``plot`` / ``fill`` /
        ``text`` as collection-style artists in data coordinates — matplotlib's
        ``transData`` + ``PathCollection`` model. Suits stereographic / IPF /
        pole-figure style plots.

        Examples
        --------
        >>> import anyplotlib as apl
        >>> fig, ax = apl.subplots()
        >>> xy = ax.axes2d(xlim=(-1, 1), ylim=(-1, 1), aspect="equal")
        >>> xy.fill([0, 1, 0.5], [0, 0, 0.9], facecolor="#eee")   # triangle
        >>> xy.scatter([0.3], [0.3], c="#f00", s=10)
        >>> xy.text(0.5, 0.95, r"$[111]$")
        """
        from anyplotlib.plotxy import PlotXY
        plot = PlotXY(xlim=xlim, ylim=ylim, aspect=aspect, units=units, y_units=y_units)
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

    def _panel_id_from_spec(self) -> str:
        """Derive a deterministic, position-based panel ID from the SubplotSpec.

        The ID is ``"p"`` followed by the first 7 hex characters of a SHA-256
        hash of the row/col bounds, e.g. ``"p6a2f3b1"``.  This is:

        * **Deterministic** – the same SubplotSpec always produces the same ID
          across Python processes and after code edits.
        * **Starts with "p"** – satisfies the JS naming convention and makes it
          easy to grep for panel traits (``panel_{id}_json``).
        * **Short** – 8 characters total; safe to embed in CSS selectors.
        """
        import hashlib as _hl
        key = f"{self._spec.row_start},{self._spec.row_stop},{self._spec.col_start},{self._spec.col_stop}"
        return "p" + _hl.sha256(key.encode()).hexdigest()[:7]

    def _attach(self, plot: "Plot1D | Plot2D | PlotMesh | Plot3D | PlotBar") -> None:
        """Register a plot on this axes (replace any previous plot)."""
        # Allocate a panel id if needed; reuse if replacing
        if self._plot is not None:
            panel_id = self._plot._id
        else:
            panel_id = self._panel_id_from_spec()
        plot._id  = panel_id
        plot._fig = self._fig
        self._plot = plot
        self._fig._register_panel(self, plot)

    def __repr__(self) -> str:
        kind = type(self._plot).__name__ if self._plot else "empty"
        return f"Axes(rows={self._spec.row_start}:{self._spec.row_stop}, cols={self._spec.col_start}:{self._spec.col_stop}, {kind})"

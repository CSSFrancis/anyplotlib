"""
plot1d/_plot1d.py
=================
1-D line panel (Plot1D) and its line helper (Line1D).
"""

from __future__ import annotations

import uuid as _uuid

import numpy as np
from typing import Callable

from anyplotlib._base_plot import _BasePlot, _PanelMixin, _MarkerMixin
from anyplotlib.markers import MarkerRegistry
from anyplotlib.callbacks import CallbackRegistry
from anyplotlib.widgets import (
    Widget,
    VLineWidget as _VLineWidget,
    HLineWidget as _HLineWidget,
    RangeWidget as _RangeWidget,
    PointWidget as _PointWidget,
)
from anyplotlib._utils import _norm_linestyle, _arr_to_b64


# ---------------------------------------------------------------------------
# Line1D — per-line handle
# ---------------------------------------------------------------------------

class Line1D:
    """Handle to a single line on a :class:`Plot1D` panel.

    Returned by :meth:`Plot1D.add_line`.  Use it to update the line data,
    register event handlers scoped to just that line, or to remove it later.

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
    def add_event_handler(self, fn_or_type, *args, **kwargs):
        """Register a handler scoped to this line only.

        Wraps the plot-level pointer_move / pointer_down handler
        with a line_id filter. Only pointer_move and pointer_down
        are meaningful on a line handle.
        """
        target_lid = self._lid

        if callable(fn_or_type):
            fn = fn_or_type
            types = args
            return self._wrap_and_register(fn, types, target_lid, **kwargs)
        else:
            all_types = (fn_or_type,) + args
            def _decorator(fn):
                return self._wrap_and_register(fn, all_types, target_lid, **kwargs)
            return _decorator

    def _wrap_and_register(self, fn, types, target_lid, **kwargs):
        from functools import wraps
        @wraps(fn)
        def _filtered(event):
            if event.line_id == target_lid:
                fn(event)
        _filtered.__wrapped__ = fn
        return self._plot.add_event_handler(_filtered, *types, **kwargs)

    def remove_handler(self, cid_or_fn, *types):
        """Remove a handler registered via this line handle."""
        self._plot.remove_handler(cid_or_fn, *types)

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

class Plot1D(_BasePlot, _PanelMixin, _MarkerMixin):
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
                 label: str = "",
                 yscale: str = "linear"):
        self._id:  str = ""
        self._fig: object = None

        if yscale not in ("linear", "log"):
            raise ValueError("yscale must be 'linear' or 'log'")

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
            "pointer_settled_ms":    0,
            "pointer_settled_delta": 4,
            "yscale":            yscale,
            # Annotation labels
            "title":             "",
            # Explicit y-range override: [ymin, ymax] or None (auto)
            "y_range":           None,
            # Visibility toggles
            "axis_visible":      True,
            "x_ticks_visible":   True,
            "y_ticks_visible":   True,
            "_view_from_python": False,
        }

        self.markers = MarkerRegistry(self._push_markers,
                                      allowed=MarkerRegistry._KNOWN_1D)
        self.callbacks = CallbackRegistry()
        self._widgets: dict[str, Widget] = {}

    def to_state_dict(self) -> dict:
        d = dict(self._state)
        # Replace numpy arrays with b64-encoded strings for the wire format.
        data_arr  = d.pop("data")
        x_arr     = d.pop("x_axis")
        d["data_b64"]    = _arr_to_b64(data_arr,  np.float64)
        d["x_axis_b64"]  = _arr_to_b64(x_arr,     np.float64)
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
                 color: str = "#4fc3f7", linewidth: float = 1.5,
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
            CSS colour string.  Default ``"#4fc3f7"``.
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
        widget._push_fn = self._make_widget_push_fn(widget)
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
        widget._push_fn = self._make_widget_push_fn(widget)
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
        widget._push_fn = self._make_widget_push_fn(widget)
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
        widget._push_fn = self._make_widget_push_fn(widget)
        self._widgets[widget.id] = widget
        if _push:
            self._push()
        return widget

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
        with self._python_view_push():
            self._state["view_x0"] = f0
            self._state["view_x1"] = f1

    def reset_view(self) -> None:
        """Reset the view to show the full x range of the primary line."""
        with self._python_view_push():
            self._state["view_x0"] = 0.0
            self._state["view_x1"] = 1.0

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

    @property
    def color(self) -> str:
        return self._state["line_color"]

    @property
    def x(self) -> np.ndarray:
        return np.asarray(self._state["x_axis"])

    @property
    def y(self) -> np.ndarray:
        return np.asarray(self._state["data"])

    def set_xlabel(self, label: str, fontsize: float | None = None) -> None:
        """Set the x-axis label.

        Parameters
        ----------
        label : str
            Label text.  Supports the mini-TeX subset for scientific
            notation, e.g. ``r"Energy ($10^{-3}$ eV)"`` or ``r"$\\Delta t$ (s)"``
            — see :class:`~anyplotlib._base_plot._BasePlot` notes.
        fontsize : float, optional
            Font size in CSS pixels.  Default 9.  ``None`` keeps the
            current size.
        """
        self._set_label("units", label, "x_label_size", fontsize)

    def set_ylabel(self, label: str, fontsize: float | None = None) -> None:
        """Set the y-axis label.  Same semantics as :meth:`set_xlabel`."""
        self._set_label("y_units", label, "y_label_size", fontsize)

    def set_yscale(self, scale: str) -> None:
        """Set the y-axis scale: ``'linear'`` or ``'log'``."""
        if scale not in ("linear", "log"):
            raise ValueError("scale must be 'linear' or 'log'")
        self._state["yscale"] = scale
        self._push()

    def set_xlim(self, xmin: float, xmax: float) -> None:
        self.set_view(x0=xmin, x1=xmax)

    def set_ylim(self, ymin: float, ymax: float) -> None:
        self._state["y_range"] = [float(ymin), float(ymax)]
        self._push()

    def get_ylim(self) -> tuple:
        yr = self._state.get("y_range")
        if yr is not None:
            return (float(yr[0]), float(yr[1]))
        return (float(self._state["data_min"]), float(self._state["data_max"]))

    def get_xlim(self) -> tuple:
        xarr = np.asarray(self._state["x_axis"])
        if len(xarr) < 2:
            return (0.0, 1.0)
        xmin, xmax = float(xarr[0]), float(xarr[-1])
        span = xmax - xmin or 1.0
        x0 = xmin + self._state["view_x0"] * span
        x1 = xmin + self._state["view_x1"] * span
        return (x0, x1)

    def get_xbound(self) -> tuple:
        xarr = np.asarray(self._state["x_axis"])
        return (float(xarr.min()), float(xarr.max()))

    # ------------------------------------------------------------------
    # Marker API  (matplotlib-style kwargs → MarkerRegistry)
    # ------------------------------------------------------------------
    def add_circles(self, offsets, name=None, *, radius=5,
                    facecolors=None, edgecolors="#ff0000",
                    linewidths=1.5, alpha=0.3,
                    hover_edgecolors=None, hover_facecolors=None,
                    labels=None, label=None,
                    transform: str = "data") -> "MarkerGroup":  # noqa: F821
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
                                labels=labels, label=label,
                                transform=transform)

    def add_points(self, offsets, name=None, *, sizes=5,
                   color="#ff0000", facecolors=None,
                   linewidths=1.5, alpha=0.3,
                   hover_edgecolors=None, hover_facecolors=None,
                   labels=None, label=None,
                   transform: str = "data") -> "MarkerGroup":  # noqa: F821
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
                                labels=labels, label=label,
                                transform=transform)

    def add_hlines(self, y_values, name=None, *,
                   color="#ff0000", linewidths=1.5,
                   hover_edgecolors=None,
                   labels=None, label=None,
                   transform: str = "data") -> "MarkerGroup":  # noqa: F821
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
                                labels=labels, label=label,
                                transform=transform)

    def add_vlines(self, x_values, name=None, *,
                   color="#ff0000", linewidths=1.5,
                   hover_edgecolors=None,
                   labels=None, label=None,
                   transform: str = "data") -> "MarkerGroup":  # noqa: F821
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
                                labels=labels, label=label,
                                transform=transform)

    def add_arrows(self, offsets, U, V, name=None, *,
                   edgecolors="#ff0000", linewidths=1.5,
                   hover_edgecolors=None,
                   labels=None, label=None,
                   transform: str = "data") -> "MarkerGroup":  # noqa: F821
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
                                labels=labels, label=label,
                                transform=transform)

    def add_ellipses(self, offsets, widths, heights, name=None, *,
                     angles=0, facecolors=None, edgecolors="#ff0000",
                     linewidths=1.5, alpha=0.3,
                     hover_edgecolors=None, hover_facecolors=None,
                     labels=None, label=None,
                     transform: str = "data") -> "MarkerGroup":  # noqa: F821
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
                                labels=labels, label=label,
                                transform=transform)

    def add_lines(self, segments, name=None, *,
                  edgecolors="#ff0000", linewidths=1.5,
                  hover_edgecolors=None,
                  labels=None, label=None,
                  transform: str = "data") -> "MarkerGroup":  # noqa: F821
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
                                labels=labels, label=label,
                                transform=transform)

    def add_rectangles(self, offsets, widths, heights, name=None, *,
                       angles=0, facecolors=None, edgecolors="#ff0000",
                       linewidths=1.5, alpha=0.3,
                       hover_edgecolors=None, hover_facecolors=None,
                       labels=None, label=None,
                       transform: str = "data") -> "MarkerGroup":  # noqa: F821
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
                                labels=labels, label=label,
                                transform=transform)

    def add_squares(self, offsets, widths, name=None, *,
                    angles=0, facecolors=None, edgecolors="#ff0000",
                    linewidths=1.5, alpha=0.3,
                    hover_edgecolors=None, hover_facecolors=None,
                    labels=None, label=None,
                    transform: str = "data") -> "MarkerGroup":  # noqa: F821
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
                                labels=labels, label=label,
                                transform=transform)

    def add_polygons(self, vertices_list, name=None, *,
                     facecolors=None, edgecolors="#ff0000",
                     linewidths=1.5, alpha=0.3,
                     hover_edgecolors=None, hover_facecolors=None,
                     labels=None, label=None,
                     transform: str = "data") -> "MarkerGroup":  # noqa: F821
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
                                labels=labels, label=label,
                                transform=transform)

    def add_texts(self, offsets, texts, name=None, *,
                  color="#ff0000", fontsize=12,
                  hover_edgecolors=None,
                  labels=None, label=None,
                  transform: str = "data") -> "MarkerGroup":  # noqa: F821
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
                                labels=labels, label=label,
                                transform=transform)

    def __repr__(self) -> str:
        n = len(self._state.get("data", []))
        color = self._state.get("line_color", "?")
        return f"Plot1D(n={n}, color={color!r})"

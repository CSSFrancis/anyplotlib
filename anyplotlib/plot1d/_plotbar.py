"""
plot1d/_plotbar.py
==================
Bar chart panel (PlotBar).
"""

from __future__ import annotations

import numpy as np
from typing import Callable

from anyplotlib.callbacks import CallbackRegistry, _EventMixin
from anyplotlib.widgets import (
    Widget,
    VLineWidget as _VLineWidget,
    HLineWidget as _HLineWidget,
    RangeWidget as _RangeWidget,
    PointWidget as _PointWidget,
)


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


class PlotBar(_EventMixin):
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
            "align":         align,
            "orient":        orient,
            "baseline":      float(bottom),
            "log_scale":     bool(log_scale),
            "show_values":   bool(show_values),
            "data_min":      dmin,
            "data_max":      dmax,
            "y_range":       None,
            "units":         units,
            "y_units":       y_units,
            "title":         "",
            "x_label":       "",
            "y_label":       "",
            "axis_visible":  True,
            "x_ticks_visible": True,
            "y_ticks_visible": True,
            # overlay-widget coordinate system (mirrors Plot1D)
            "x_axis":        x_axis,
            "view_x0":       0.0,
            "view_x1":       1.0,
            "overlay_widgets": [],
            "pointer_settled_ms":    0,
            "pointer_settled_delta": 4,
            "_view_from_python": False,
        }
        self.callbacks = CallbackRegistry()
        self._widgets: dict[str, Widget] = {}

    def _configure_pointer_settled(self, ms: int, delta: float) -> None:
        self._state["pointer_settled_ms"]    = ms
        self._state["pointer_settled_delta"] = delta
        self._push()

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
    # Display control
    # ------------------------------------------------------------------
    def set_title(self, text: str) -> None:
        """Set the panel title."""
        self._state["title"] = str(text)
        self._push()

    def set_xlabel(self, text: str) -> None:
        """Set the x-axis label."""
        self._state["x_label"] = str(text)
        self._push()

    def set_ylabel(self, text: str) -> None:
        """Set the y-axis / value-axis label."""
        self._state["y_label"] = str(text)
        self._push()

    def set_axis_off(self) -> None:
        """Hide axes, ticks, and labels."""
        self._state["axis_visible"] = False
        self._push()

    def set_axis_on(self) -> None:
        """Show axes, ticks, and labels."""
        self._state["axis_visible"] = True
        self._push()

    def set_ticks_visible(self, visible: bool, *, x: bool | None = None,
                          y: bool | None = None) -> None:
        """Show or hide x/y tick marks independently."""
        if x is None and y is None:
            self._state["x_ticks_visible"] = bool(visible)
            self._state["y_ticks_visible"] = bool(visible)
        else:
            if x is not None:
                self._state["x_ticks_visible"] = bool(x)
            if y is not None:
                self._state["y_ticks_visible"] = bool(y)
        self._push()

    # ------------------------------------------------------------------
    # View (xlim / ylim)
    # ------------------------------------------------------------------
    def set_xlim(self, x_min: float, x_max: float) -> None:
        """Pan/zoom the x-axis to [x_min, x_max] in data coordinates."""
        x_axis = self._state["x_axis"]
        span = x_axis[1] - x_axis[0]
        if span == 0:
            return
        self._state["view_x0"] = (x_min - x_axis[0]) / span
        self._state["view_x1"] = (x_max - x_axis[0]) / span
        self._state["_view_from_python"] = True
        self._push()
        self._state["_view_from_python"] = False

    def set_ylim(self, y_min: float, y_max: float) -> None:
        """Fix the value-axis range to [y_min, y_max]."""
        self._state["y_range"] = [float(y_min), float(y_max)]
        self._push()

    def get_ylim(self) -> tuple:
        """Return the current value-axis range as ``(y_min, y_max)``."""
        yr = self._state.get("y_range")
        if yr is not None:
            return (float(yr[0]), float(yr[1]))
        return (float(self._state["data_min"]), float(self._state["data_max"]))

    def get_xlim(self) -> tuple:
        """Return the current x-axis view range in data coordinates."""
        x_axis = self._state["x_axis"]
        span = x_axis[1] - x_axis[0]
        x0 = x_axis[0] + self._state["view_x0"] * span
        x1 = x_axis[0] + self._state["view_x1"] * span
        return (float(x0), float(x1))

    def reset_view(self) -> None:
        """Reset pan/zoom to show all bars."""
        self._state["view_x0"] = 0.0
        self._state["view_x1"] = 1.0
        self._state["y_range"] = None
        self._state["_view_from_python"] = True
        self._push()
        self._state["_view_from_python"] = False

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

    def __repr__(self) -> str:
        n = len(self._state.get("values", []))
        orient = self._state.get("orient", "v")
        groups = self._state.get("groups", 1)
        if groups > 1:
            return f"PlotBar(n={n}, groups={groups}, orient={orient!r})"
        return f"PlotBar(n={n}, orient={orient!r})"

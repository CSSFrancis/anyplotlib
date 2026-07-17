"""
widgets/_widgets1d.py
=====================
Interactive overlay widgets for 1-D line panels (Plot1D).
"""

from __future__ import annotations
from anyplotlib.widgets._base import Widget


class VLineWidget(Widget):
    """Draggable vertical line overlay widget for 1-D plots.

    Allows interactive selection of a single x-axis value. The line can be
    dragged left/right to change the selected position.

    Parameters
    ----------
    push_fn : Callable
        Update callback.
    x : float
        Initial x-position in data coordinates.
    color : str, optional
        CSS colour for the line. Default ``"#00e5ff"``.
    linewidth : float, optional
        Line stroke width in px. Default 2.
    """
    def __init__(self, push_fn, *, x, color="#00e5ff", linewidth=2):
        super().__init__("vline", push_fn, x=float(x), color=color,
                         linewidth=float(linewidth))


class HLineWidget(Widget):
    """Draggable horizontal line overlay widget for bar charts.

    Allows interactive selection of a single y-axis value. The line can be
    dragged up/down to change the selected value.

    Parameters
    ----------
    push_fn : Callable
        Update callback.
    y : float
        Initial y-position in data coordinates.
    color : str, optional
        CSS colour for the line. Default ``"#00e5ff"``.
    linewidth : float, optional
        Line stroke width in px. Default 2.
    """
    def __init__(self, push_fn, *, y, color="#00e5ff", linewidth=2):
        super().__init__("hline", push_fn, y=float(y), color=color,
                         linewidth=float(linewidth))


class RangeWidget(Widget):
    """Draggable range selection widget.

    Two display styles are available:

    ``style='band'`` (default)
        Two connected vertical lines with a translucent fill band.  Either
        line can be dragged independently; the whole band can be dragged by
        clicking inside it.

    ``style='fwhm'``
        Two circular handles joined by a dashed horizontal line drawn at
        height *y* (the half-maximum level).  Only the x-positions of the
        handles are draggable.  Use this to show/edit a FWHM interval on a
        peak.

    Parameters
    ----------
    push_fn : Callable
        Update callback.
    x0, x1 : float
        Initial left and right positions in data coordinates.
    color : str, optional
        CSS colour.  Default ``"#00e5ff"``.
    style : {'band', 'fwhm'}, optional
        Visual style.  Default ``"band"``.
    y : float, optional
        Y-position (data coordinates) for the connecting line when
        ``style='fwhm'``.  Ignored for ``style='band'``.  Default ``0.0``.
    linewidth : float, optional
        Line stroke width in px. Default 2.
    """
    def __init__(self, push_fn, *, x0, x1, color="#00e5ff",
                 style: str = "band", y: float = 0.0, linewidth=2):
        super().__init__("range", push_fn,
                         x0=float(x0), x1=float(x1), color=color,
                         style=str(style), y=float(y),
                         linewidth=float(linewidth))


class PointWidget(Widget):
    """Draggable point (control point) overlay widget for 1-D plots.

    A free-moving handle that can be dragged to any position within the
    plot area.  Reports its data-space ``x`` and ``y`` coordinates back
    to Python via the standard callback hooks.

    Parameters
    ----------
    push_fn : Callable
        Update callback.
    x : float
        Initial x position in data coordinates.
    y : float
        Initial y position in data coordinates (value axis).
    color : str, optional
        CSS colour for the handle.  Default ``"#00e5ff"``.
    show_crosshair : bool, optional
        If ``True`` (default), draw dashed crosshair guide lines through the
        handle.  Set to ``False`` for a bare draggable dot with no guides.
    linewidth : float, optional
        Guide-line stroke width in px. Default 2.
    """
    def __init__(self, push_fn, *, x, y, color="#00e5ff", show_crosshair=True,
                 linewidth=2):
        super().__init__("point", push_fn, x=float(x), y=float(y), color=color,
                         show_crosshair=bool(show_crosshair),
                         linewidth=float(linewidth))

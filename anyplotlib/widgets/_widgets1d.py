"""
widgets/_widgets1d.py
=====================
Interactive overlay widgets for 1-D line panels (Plot1D).

``VLineWidget`` and ``HLineWidget`` are also used by ``Plot2D``, where they
draw a full-height / full-width rule over the image.
"""

from __future__ import annotations
from anyplotlib.widgets._base import Widget

SNAP_DOC = """snap_values : sequence of float, optional
        Allowed positions.  While dragging, the widget follows the cursor but
        lands only on the nearest of these values — matplotlib's
        ``SpanSelector.snap_values``.  ``None`` (default) drags continuously.
        Set it later with ``widget.snap_values = [...]``."""


def _norm_snap_values(values):
    """Validate snap_values and return a plain list of floats (or None).

    A list is what crosses the wire, so numpy arrays have to be converted
    here — they are not JSON-serialisable and would break the panel push.
    """
    if values is None:
        return None
    out = [float(v) for v in values]
    if not out:
        return None
    return out


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
    def __init__(self, push_fn, *, x, color="#00e5ff", linewidth=2,
                 snap_values=None):
        super().__init__("vline", push_fn, x=float(x), color=color,
                         linewidth=float(linewidth),
                         snap_values=_norm_snap_values(snap_values))


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
    def __init__(self, push_fn, *, y, color="#00e5ff", linewidth=2,
                 snap_values=None):
        super().__init__("hline", push_fn, y=float(y), color=color,
                         linewidth=float(linewidth),
                         snap_values=_norm_snap_values(snap_values))


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

    With ``orientation='vertical'`` the band spans the plot width and selects
    a range on the *value* axis instead — for picking an intensity window
    rather than a spectral one.

    Parameters
    ----------
    push_fn : Callable
        Update callback.
    x0, x1 : float
        The two edges of the range, in data coordinates **along the selection
        axis**: x positions when horizontal, y values when vertical.  The
        names do not change with orientation, mirroring how matplotlib's
        ``SpanSelector.extents`` is read the same way for either ``direction``.
    color : str, optional
        CSS colour.  Default ``"#00e5ff"``.
    style : {'band', 'fwhm'}, optional
        Visual style.  Default ``"band"``.  ``'fwhm'`` is horizontal-only.
    y : float, optional
        Y-position (data coordinates) for the connecting line when
        ``style='fwhm'``.  Ignored for ``style='band'``.  Default ``0.0``.
    orientation : {'horizontal', 'vertical'}, optional
        Which axis the range selects along.  Default ``"horizontal"``.
    linewidth : float, optional
        Line stroke width in px. Default 2.
    max_extent : float, optional
        Maximum span width in DATA units. When set, the span physically stops
        growing at this width while dragging: the edge under the cursor is
        pinned and the opposite edge stays put, so the range never exceeds the
        cap and never jumps. ``None`` (default) leaves it unbounded.

        Use this when span width costs real work downstream — e.g. an
        integrating selector where the width is a number of frames to read.
        Enforcing it in the widget makes the limit visible (the edge simply
        stops) instead of applying a silent clamp after the fact.
    snap_values : sequence of float, optional
        Allowed edge positions.  While dragging, each edge follows the cursor
        but lands only on the nearest of these values — matplotlib's
        ``SpanSelector.snap_values``.  ``None`` (default) drags continuously.
        Set it later with ``widget.snap_values = [...]``.

    Raises
    ------
    ValueError
        If *orientation* is not ``'horizontal'`` or ``'vertical'``, or if
        ``style='fwhm'`` is combined with a vertical orientation.
    """
    def __init__(self, push_fn, *, x0, x1, color="#00e5ff",
                 style: str = "band", y: float = 0.0, linewidth=2,
                 max_extent=None, orientation: str = "horizontal",
                 snap_values=None):
        if orientation not in ("horizontal", "vertical"):
            raise ValueError(
                f"orientation must be 'horizontal' or 'vertical', "
                f"got {orientation!r}"
            )
        if orientation == "vertical" and style == "fwhm":
            raise ValueError("style='fwhm' is only defined for a horizontal range")
        super().__init__("range", push_fn,
                         x0=float(x0), x1=float(x1), color=color,
                         style=str(style), y=float(y),
                         linewidth=float(linewidth),
                         orientation=str(orientation),
                         snap_values=_norm_snap_values(snap_values),
                         max_extent=(None if max_extent is None
                                     else float(max_extent)))


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

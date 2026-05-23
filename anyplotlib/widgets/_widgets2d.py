"""
widgets/_widgets2d.py
=====================
Interactive overlay widgets for 2-D image panels (Plot2D / InsetAxes).
"""

from __future__ import annotations
from anyplotlib.widgets._base import Widget


class RectangleWidget(Widget):
    """Draggable rectangle overlay widget for 2-D plots.

    Parameters
    ----------
    push_fn : Callable
        Update callback.
    x, y : float
        Top-left corner position in pixel/data coordinates.
    w, h : float
        Width and height in pixel/data coordinates.
    color : str, optional
        CSS colour for the rectangle outline. Default ``"#00e5ff"``.
    """
    def __init__(self, push_fn, *, x, y, w, h, color="#00e5ff"):
        super().__init__("rectangle", push_fn,
                         x=float(x), y=float(y),
                         w=float(w), h=float(h), color=color)


class CircleWidget(Widget):
    """Draggable circle overlay widget for 2-D plots.

    Parameters
    ----------
    push_fn : Callable
        Update callback.
    cx, cy : float
        Center position in pixel/data coordinates.
    r : float
        Radius in pixel/data coordinates.
    color : str, optional
        CSS colour for the circle outline. Default ``"#00e5ff"``.
    """
    def __init__(self, push_fn, *, cx, cy, r, color="#00e5ff"):
        super().__init__("circle", push_fn,
                         cx=float(cx), cy=float(cy), r=float(r), color=color)


class AnnularWidget(Widget):
    """Draggable annular (ring) overlay widget for 2-D plots.

    Parameters
    ----------
    push_fn : Callable
        Update callback.
    cx, cy : float
        Center position in pixel/data coordinates.
    r_outer, r_inner : float
        Outer and inner radii in pixel/data coordinates.
        Inner radius must be less than outer radius.
    color : str, optional
        CSS colour for the ring outline. Default ``"#00e5ff"``.

    Raises
    ------
    ValueError
        If r_inner >= r_outer.
    """
    def __init__(self, push_fn, *, cx, cy, r_outer, r_inner, color="#00e5ff"):
        if r_inner >= r_outer:
            raise ValueError("r_inner must be < r_outer")
        super().__init__("annular", push_fn,
                         cx=float(cx), cy=float(cy),
                         r_outer=float(r_outer), r_inner=float(r_inner),
                         color=color)


class CrosshairWidget(Widget):
    """Draggable crosshair overlay widget for 2-D plots.

    Parameters
    ----------
    push_fn : Callable
        Update callback.
    cx, cy : float
        Center position in pixel/data coordinates.
    color : str, optional
        CSS colour for the crosshair. Default ``"#00e5ff"``.
    """
    def __init__(self, push_fn, *, cx, cy, color="#00e5ff"):
        super().__init__("crosshair", push_fn,
                         cx=float(cx), cy=float(cy), color=color)


class PolygonWidget(Widget):
    """Draggable polygon overlay widget for 2-D plots.

    Parameters
    ----------
    push_fn : Callable
        Update callback.
    vertices : list of tuple
        Polygon vertices ``[(x0, y0), (x1, y1), ...]`` in pixel/data coordinates.
        Must have at least 3 vertices.
    color : str, optional
        CSS colour for the polygon outline. Default ``"#00e5ff"``.

    Raises
    ------
    ValueError
        If fewer than 3 vertices provided.
    """
    def __init__(self, push_fn, *, vertices, color="#00e5ff"):
        verts = [[float(x), float(y)] for x, y in vertices]
        if len(verts) < 3:
            raise ValueError("polygon needs >= 3 vertices")
        super().__init__("polygon", push_fn, vertices=verts, color=color)


class LabelWidget(Widget):
    """Text label overlay widget for 2-D plots.

    Parameters
    ----------
    push_fn : Callable
        Update callback.
    x, y : float
        Label position in pixel/data coordinates.
    text : str, optional
        Label text. Default ``"Label"``.
    fontsize : int, optional
        Font size in points. Default 14.
    color : str, optional
        CSS colour for the text. Default ``"#00e5ff"``.
    """
    def __init__(self, push_fn, *, x, y, text="Label", fontsize=14,
                 color="#00e5ff"):
        super().__init__("label", push_fn,
                         x=float(x), y=float(y),
                         text=str(text), fontsize=int(fontsize), color=color)

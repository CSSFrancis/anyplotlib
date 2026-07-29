"""
widgets/_widgets2d.py
=====================
Interactive overlay widgets for 2-D image panels (Plot2D / InsetAxes).

Every 2-D widget accepts ``show_handles`` (default ``True``). When ``False``
the widget body still draws and stays fully hit-testable / draggable, but the
small square grab-handle dots are omitted — a cleaner look for a finished
annotation. It rides along in ``_data`` so it serialises into the panel state's
``overlay_widgets`` list and reaches the JS renderer unchanged.
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
    linewidth : float, optional
        Outline stroke width in px. Default 2.
    show_handles : bool, optional
        Draw the corner grab handles. Default ``True``.
    max_extent : float or (float, float), optional
        Maximum width/height in the widget's coordinates. A scalar caps both
        axes; a ``(max_w, max_h)`` pair caps them separately. When set, the
        rectangle physically stops growing at the cap while dragging — the
        dragged corner pins and the opposite corner stays put. ``None``
        (default) leaves it unbounded.

        Use this when the rectangle's area costs real work downstream — e.g. an
        integrating ROI whose size is a number of frames to read.
    """
    def __init__(self, push_fn, *, x, y, w, h, color="#00e5ff",
                 linewidth=2, show_handles=True, max_extent=None):
        if max_extent is None:
            max_w = max_h = None
        elif isinstance(max_extent, (tuple, list)):
            max_w, max_h = (float(max_extent[0]), float(max_extent[1]))
        else:
            max_w = max_h = float(max_extent)
        super().__init__("rectangle", push_fn,
                         x=float(x), y=float(y),
                         w=float(w), h=float(h), color=color,
                         linewidth=float(linewidth),
                         show_handles=bool(show_handles),
                         max_w=max_w, max_h=max_h)


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
    linewidth : float, optional
        Outline stroke width in px. Default 2.
    show_handles : bool, optional
        Draw the radius grab handle. Default ``True``.
    """
    def __init__(self, push_fn, *, cx, cy, r, color="#00e5ff",
                 linewidth=2, show_handles=True):
        super().__init__("circle", push_fn,
                         cx=float(cx), cy=float(cy), r=float(r), color=color,
                         linewidth=float(linewidth),
                         show_handles=bool(show_handles))


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
    linewidth : float, optional
        Outline stroke width in px. Default 2.
    show_handles : bool, optional
        Draw the inner/outer radius grab handles. Default ``True``.

    Raises
    ------
    ValueError
        If r_inner >= r_outer.
    """
    def __init__(self, push_fn, *, cx, cy, r_outer, r_inner, color="#00e5ff",
                 linewidth=2, show_handles=True):
        if r_inner >= r_outer:
            raise ValueError("r_inner must be < r_outer")
        super().__init__("annular", push_fn,
                         cx=float(cx), cy=float(cy),
                         r_outer=float(r_outer), r_inner=float(r_inner),
                         color=color, linewidth=float(linewidth),
                         show_handles=bool(show_handles))


class LineWidget(Widget):
    """Draggable two-endpoint line segment overlay widget for 2-D plots.

    A plain segment from ``(x1, y1)`` to ``(x2, y2)``: drag either endpoint
    handle to move that end, or drag the shaft to translate the whole
    segment.  Unlike :class:`ArrowWidget` it has no head, and unlike
    :class:`PolygonWidget` it does not close the path — this is the widget for
    a line profile, a cross-section cut, or a two-point measurement.

    Parameters
    ----------
    push_fn : Callable
        Update callback.
    x1, y1 : float
        First endpoint in pixel/data coordinates.
    x2, y2 : float
        Second endpoint in pixel/data coordinates.
    color : str, optional
        CSS colour for the segment. Default ``"#00e5ff"``.
    linewidth : float, optional
        Stroke width in px. Default 2.
    show_handles : bool, optional
        Draw the endpoint grab handles. Default ``True``.
    """
    def __init__(self, push_fn, *, x1, y1, x2, y2, color="#00e5ff",
                 linewidth=2, show_handles=True):
        super().__init__("line", push_fn,
                         x1=float(x1), y1=float(y1),
                         x2=float(x2), y2=float(y2),
                         color=color, linewidth=float(linewidth),
                         show_handles=bool(show_handles))

    @property
    def length(self) -> float:
        """Euclidean length of the segment in data coordinates."""
        return float(
            ((self.x2 - self.x1) ** 2 + (self.y2 - self.y1) ** 2) ** 0.5
        )


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
    linewidth : float, optional
        Line stroke width in px. Default 2.
    show_handles : bool, optional
        Draw the centre dot handle. Default ``True``.
    """
    def __init__(self, push_fn, *, cx, cy, color="#00e5ff", linewidth=2,
                 show_handles=True):
        super().__init__("crosshair", push_fn,
                         cx=float(cx), cy=float(cy), color=color,
                         linewidth=float(linewidth),
                         show_handles=bool(show_handles))


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
    linewidth : float, optional
        Outline stroke width in px. Default 2.
    show_handles : bool, optional
        Draw the per-vertex grab handles. Default ``True``.

    Raises
    ------
    ValueError
        If fewer than 3 vertices provided.
    """
    def __init__(self, push_fn, *, vertices, color="#00e5ff", linewidth=2,
                 show_handles=True):
        verts = [[float(x), float(y)] for x, y in vertices]
        if len(verts) < 3:
            raise ValueError("polygon needs >= 3 vertices")
        super().__init__("polygon", push_fn, vertices=verts, color=color,
                         linewidth=float(linewidth),
                         show_handles=bool(show_handles))


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
    show_handles : bool, optional
        Draw the anchor grab handle. Default ``True``.
    """
    def __init__(self, push_fn, *, x, y, text="Label", fontsize=14,
                 color="#00e5ff", show_handles=True):
        super().__init__("label", push_fn,
                         x=float(x), y=float(y),
                         text=str(text), fontsize=int(fontsize), color=color,
                         show_handles=bool(show_handles))


def _coerce_strokes(strokes) -> list[list[list[float]]]:
    """Validate/normalise a stroke list into plain ``[[[x, y], ...], ...]``.

    Accepts anything iterable-of-iterable-of-pairs (lists, tuples, numpy rows)
    and returns nested plain ``float`` lists so the result is JSON-serialisable
    for the wire.

    Raises
    ------
    ValueError
        If a stroke is empty or a point is not a 2-element ``(x, y)``.
    """
    out: list[list[list[float]]] = []
    for si, stroke in enumerate(strokes):
        pts = []
        for pt in stroke:
            pair = list(pt)
            if len(pair) != 2:
                raise ValueError(
                    f"stroke {si}: every point must be (x, y); got {len(pair)} "
                    "values"
                )
            pts.append([float(pair[0]), float(pair[1])])
        if not pts:
            raise ValueError(f"stroke {si} is empty — a stroke needs >= 1 point")
        out.append(pts)
    return out


class BrushWidget(Widget):
    """Freehand paint-brush overlay widget for 2-D plots.

    Shift-drag on the image to paint a stroke; every stroke is a polyline of
    image-pixel points, stroked with round caps and joins at a width of
    ``2 * radius`` image pixels.  Built for labelling regions — painting
    training scribbles for a pixel classifier, marking a defect, masking a
    beam stop — where a polygon or a rectangle is the wrong shape.

    Two gates govern the painting so a brush can coexist with pan / click /
    other widgets on the same panel:

    1. ``active`` — Python-side arming.  ``False`` keeps the strokes drawn but
       ignores all input, which is how you park the tool without losing work.
    2. **Shift** — the drag modifier.  A *bare* drag still pans the image and
       still drags other widgets; only ``Shift`` + drag paints.  A brush that
       claimed a plain drag would hit-test as "anywhere in the image" and kill
       panning and click-to-select outright.

    While the stroke is being drawn the points accumulate **in the browser** and
    only the finished stroke reaches Python, once, as a ``pointer_up`` event.
    So ``pointer_move`` does **not** fire for a brush stroke — register on
    ``pointer_up``::

        brush = plot.add_brush_widget(radius=6, colors=["#f44", "#4f4"])

        @brush.add_event_handler("pointer_up")
        def stroke_done(event):
            update_labels(brush.strokes, brush.stroke_classes)

    Parameters
    ----------
    push_fn : Callable
        Update callback.
    radius : float, optional
        Brush radius in image pixels — the painted band is ``2 * radius`` wide,
        and an erase drag removes stroke points within this distance.
        Default 8.
    color : str, optional
        CSS colour used when ``colors`` has no entry for a stroke's class.
        Default ``"#00e5ff"``.
    colors : list of str, optional
        Per-class CSS colours, indexed by ``class_id``.  Lets one brush carry
        several label classes at once.  Default ``None`` (every class draws in
        ``color``).
    class_id : int, optional
        Label class new strokes are tagged with.  Default 0.
    strokes : list, optional
        Pre-existing strokes, ``[[[x, y], ...], ...]`` in image-pixel
        coordinates.  Default ``None`` (empty).
    stroke_classes : list of int, optional
        Class id per entry of ``strokes``; must be the same length.  Default
        ``None`` (every seeded stroke takes ``class_id``).
    alpha : float, optional
        Stroke opacity in ``[0, 1]``.  Default 0.6 — a scribble you can see
        the image through, since the point is to label what is underneath.
    active : bool, optional
        Accept Shift-drag painting.  Default ``True``.
    erase : bool, optional
        When ``True`` an armed drag *removes* stroke points within ``radius``
        instead of painting.  Default ``False``.

    Attributes
    ----------
    strokes : list
        Painted strokes, ``[[[x, y], ...], ...]`` in image pixels.  Read-only
        in practice — mutating the list in place does not reach the renderer;
        use :meth:`add_stroke` / :meth:`set_strokes` / :meth:`clear_strokes`.
    stroke_classes : list of int
        Class id of each stroke, parallel to ``strokes``.

    Raises
    ------
    ValueError
        If ``radius <= 0``, ``class_id < 0``, ``alpha`` is outside ``[0, 1]``,
        ``colors`` is not a sequence of strings, a stroke is malformed, or
        ``stroke_classes`` does not match ``strokes`` in length.

    See Also
    --------
    PolygonWidget : Closed straight-edged region with draggable vertices.
    """

    def __init__(self, push_fn, *, radius=8.0, color="#00e5ff", colors=None,
                 class_id=0, strokes=None, stroke_classes=None, alpha=0.6,
                 active=True, erase=False):
        radius = float(radius)
        if not radius > 0:
            raise ValueError(f"radius must be > 0, got {radius}")
        class_id = int(class_id)
        if class_id < 0:
            raise ValueError(f"class_id must be >= 0, got {class_id}")
        alpha = float(alpha)
        if not 0.0 <= alpha <= 1.0:
            raise ValueError(f"alpha must be in [0, 1], got {alpha}")
        if colors is None:
            cols: list[str] = []
        elif isinstance(colors, str):
            raise ValueError("colors must be a list of CSS colours, not a "
                             "single string — use color= for that")
        else:
            cols = [str(c) for c in colors]
        strks = _coerce_strokes(strokes or [])
        if stroke_classes is None:
            classes = [class_id] * len(strks)
        else:
            classes = [int(c) for c in stroke_classes]
            if len(classes) != len(strks):
                raise ValueError(
                    f"stroke_classes has {len(classes)} entries but there are "
                    f"{len(strks)} strokes"
                )
            if any(c < 0 for c in classes):
                raise ValueError("stroke_classes must all be >= 0")
        super().__init__("brush", push_fn,
                         radius=radius, color=color, colors=cols,
                         class_id=class_id, strokes=strks,
                         stroke_classes=classes, alpha=alpha,
                         active=bool(active), erase=bool(erase))

    # ── stroke management ─────────────────────────────────────────────────

    @property
    def n_strokes(self) -> int:
        """Number of painted strokes."""
        return len(self._data["strokes"])

    def clear_strokes(self) -> None:
        """Discard every painted stroke.  Does not change ``class_id``."""
        self.set(strokes=[], stroke_classes=[])

    def add_stroke(self, points, class_id: int | None = None) -> None:
        """Append one stroke.

        Parameters
        ----------
        points : list of tuple
            ``[(x, y), ...]`` in image-pixel coordinates; at least one point.
        class_id : int, optional
            Label class for this stroke.  Defaults to the widget's current
            ``class_id``.

        Raises
        ------
        ValueError
            If ``points`` is empty or a point is not an ``(x, y)`` pair.
        """
        (stroke,) = _coerce_strokes([points])
        cid = int(self._data["class_id"] if class_id is None else class_id)
        if cid < 0:
            raise ValueError(f"class_id must be >= 0, got {cid}")
        self.set(strokes=self._data["strokes"] + [stroke],
                 stroke_classes=self._data["stroke_classes"] + [cid])

    def set_strokes(self, strokes, classes=None) -> None:
        """Replace every stroke (and its class) in one push.

        This is the sanctioned way to write ``strokes``: it keeps the parallel
        ``stroke_classes`` list in lockstep, which a bare
        ``brush.strokes = ...`` assignment cannot do.

        Parameters
        ----------
        strokes : list
            ``[[[x, y], ...], ...]`` in image-pixel coordinates.
        classes : list of int, optional
            Class id per stroke.  Defaults to the widget's current
            ``class_id`` for every stroke.

        Raises
        ------
        ValueError
            If a stroke is malformed or ``classes`` has the wrong length.
        """
        strks = _coerce_strokes(strokes)
        if classes is None:
            cls = [int(self._data["class_id"])] * len(strks)
        else:
            cls = [int(c) for c in classes]
            if len(cls) != len(strks):
                raise ValueError(
                    f"classes has {len(cls)} entries but there are "
                    f"{len(strks)} strokes"
                )
        self.set(strokes=strks, stroke_classes=cls)

    def strokes_for_class(self, class_id: int) -> list:
        """Return only the strokes tagged with ``class_id``.

        Parameters
        ----------
        class_id : int
            Label class to select.

        Returns
        -------
        list
            ``[[[x, y], ...], ...]`` — the matching strokes, in paint order.
        """
        cid = int(class_id)
        return [s for s, c in zip(self._data["strokes"],
                                  self._data["stroke_classes"]) if c == cid]


class ArrowWidget(Widget):
    """Draggable arrow overlay widget for 2-D plots.

    The arrow tail sits at ``(x, y)`` and the head at ``(x + u, y + v)``, all in
    image-pixel coordinates. Dragging the body moves the whole arrow; dragging
    the head handle re-aims it (updates ``u``/``v``).

    Parameters
    ----------
    push_fn : Callable
        Update callback.
    x, y : float
        Tail position in pixel/data coordinates.
    u, v : float
        Arrow vector (head = tail + (u, v)) in pixel/data coordinates.
    color : str, optional
        CSS colour for the arrow. Default ``"#00e5ff"``.
    linewidth : float, optional
        Shaft line width in px. Default 2.
    show_handles : bool, optional
        Draw the tail/head grab handles. Default ``True``.
    """
    def __init__(self, push_fn, *, x, y, u, v, color="#00e5ff",
                 linewidth=2, show_handles=True):
        super().__init__("arrow", push_fn,
                         x=float(x), y=float(y),
                         u=float(u), v=float(v), color=color,
                         linewidth=float(linewidth),
                         show_handles=bool(show_handles))

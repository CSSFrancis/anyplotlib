"""
widgets.py — Interactive overlay widget classes.

Each widget has a .callbacks (CallbackRegistry).  Register handlers via::

    @rect.on_changed        # every drag frame
    def live(event): ...

    @rect.on_release        # once on mouseup
    def done(event): ...

    @rect.on_click
    def clicked(event): ...

    rect.x = 40             # moves widget, sends targeted update to JS
    rect.x                  # always reflects current JS position
"""
from __future__ import annotations

import uuid as _uuid
from typing import Callable

from anyplotlib.callbacks import CallbackRegistry, Event

__all__ = [
    "Widget",
    "RectangleWidget", "CircleWidget", "AnnularWidget",
    "CrosshairWidget", "PolygonWidget", "LabelWidget",
    "VLineWidget", "HLineWidget", "RangeWidget", "PointWidget",
]


class Widget:
    """Base class for all overlay widgets.

    Provides attribute-based state access, callbacks for interaction events,
    and automatic synchronization with the JavaScript renderer.

    Parameters
    ----------
    wtype : str
        Widget type (e.g., 'rectangle', 'circle', 'crosshair').
    push_fn : Callable
        Zero-arg callback to send position updates to the JavaScript renderer.
    **kwargs : dict
        Initial widget state (position, size, color, etc.).

    Attributes
    ----------
    callbacks : CallbackRegistry
        Event callback registry. Register handlers via:
        - ``@widget.on_changed`` — fires on every drag frame
        - ``@widget.on_release`` — fires once when drag settles
        - ``@widget.on_click`` — fires on click event
    """

    def __init__(self, wtype: str, push_fn: Callable, **kwargs):
        self._id: str = str(_uuid.uuid4())[:8]
        self._type: str = wtype
        self._data: dict = dict(kwargs)
        self._data["id"] = self._id
        self._data["type"] = wtype
        self._push_fn: Callable = push_fn
        self.callbacks: CallbackRegistry = CallbackRegistry()

    # ── attribute read ────────────────────────────────────────────────

    def __getattr__(self, key: str):
        """Access widget properties as attributes (read-only)."""
        if key.startswith("_"):
            raise AttributeError(key)
        try:
            return self._data[key]
        except KeyError:
            raise AttributeError(
                f"{type(self).__name__} has no attribute {key!r}. "
                f"Available: {list(self._data)}"
            ) from None

    # ── attribute write — routes public assignments through set() ────

    def __setattr__(self, key: str, value) -> None:
        """Update widget properties via attribute assignment."""
        # Private attrs and 'callbacks' bypass set()
        if key.startswith("_") or key == "callbacks":
            super().__setattr__(key, value)
            return
        # During __init__ _data may not exist yet
        try:
            object.__getattribute__(self, "_data")
        except AttributeError:
            super().__setattr__(key, value)
            return
        self.set(**{key: value})

    # ── set / get ─────────────────────────────────────────────────────

    def set(self, _push: bool = True, **kwargs) -> None:
        """Update properties and send targeted update to JavaScript.

        Parameters
        ----------
        _push : bool, optional
            Whether to push update to renderer. Default True.
            Set to False internally to avoid echo loops.
        **kwargs : dict
            Properties to update (e.g., x=100, y=50, radius=20).

        Notes
        -----
        Updates are sent as targeted widget updates, not full panel re-renders.
        This is more efficient for frequent updates during dragging.
        """
        self._data.update(kwargs)
        if _push:
            self._push_fn()
        self.callbacks.fire(Event("on_changed", source=self, data=dict(self._data)))

    def get(self, key: str, default=None):
        """Get a widget property by name.

        Parameters
        ----------
        key : str
            Property name.
        default : optional
            Default value if property not found.

        Returns
        -------
        object
            The property value.
        """
        return self._data.get(key, default)

    def to_dict(self) -> dict:
        """Return a dict copy of the widget state.

        Returns
        -------
        dict
            All widget properties including id and type.
        """
        return dict(self._data)

    # ── callback decorator methods ────────────────────────────────────

    def on_changed(self, fn: Callable) -> Callable:
        """Decorator: register fn to fire on every drag frame.

        Use this for high-frequency updates (keep handler fast).

        Parameters
        ----------
        fn : Callable
            Handler function receiving an Event.

        Returns
        -------
        Callable
            The decorated function.
        """
        cid = self.callbacks.connect("on_changed", fn)
        fn._cid = cid
        return fn

    def on_release(self, fn: Callable) -> Callable:
        """Decorator: register fn to fire once when drag settles.

        Use this for expensive operations triggered after user stops dragging.

        Parameters
        ----------
        fn : Callable
            Handler function receiving an Event.

        Returns
        -------
        Callable
            The decorated function.
        """
        cid = self.callbacks.connect("on_release", fn)
        fn._cid = cid
        return fn

    def on_click(self, fn: Callable) -> Callable:
        """Decorator: register fn to fire on widget click.

        Parameters
        ----------
        fn : Callable
            Handler function receiving an Event.

        Returns
        -------
        Callable
            The decorated function.
        """
        cid = self.callbacks.connect("on_click", fn)
        fn._cid = cid
        return fn

    def disconnect(self, cid) -> None:
        """Remove the callback registered under *cid*.

        Parameters
        ----------
        cid : int or Callable
            Either the integer CID returned by ``callbacks.connect()``,
            or the decorated function itself (carries a ``._cid`` attribute).
        """
        if callable(cid) and hasattr(cid, "_cid"):
            cid = cid._cid
        self.callbacks.disconnect(cid)

    # ── visibility ────────────────────────────────────────────────────────

    @property
    def visible(self) -> bool:
        """``True`` if the widget is rendered; ``False`` if hidden."""
        return self._data.get("visible", True)

    @visible.setter
    def visible(self, value: bool) -> None:
        self.show() if value else self.hide()

    def show(self) -> None:
        """Show the widget.  Does not fire ``on_changed`` callbacks."""
        self._data["visible"] = True
        self._push_fn()

    def hide(self) -> None:
        """Hide the widget without removing it or its callbacks.

        Call :meth:`show` to make it visible again.
        Does not fire ``on_changed`` callbacks.
        """
        self._data["visible"] = False
        self._push_fn()

    # ── JS → Python sync ──────────────────────────────────────────────

    def _update_from_js(self, new_data: dict, event_type: str = "on_changed") -> bool:
        """Apply incoming JS state without pushing back (avoids echo).

        Parameters
        ----------
        new_data : dict
            Updated widget properties from JavaScript.
        event_type : str, optional
            Type of event that triggered the update.

        Returns
        -------
        bool
            True if any state changed.

        Notes
        -----
        Always fires on_release / on_click callbacks even if nothing changed.
        Only fires on_changed if state actually changed.
        """
        changed = False
        for k, v in new_data.items():
            if k in ("id", "type"):
                continue
            if self._data.get(k) != v:
                self._data[k] = v
                changed = True
        # Always fire for settle / click; only fire on_changed when something moved
        if changed or event_type in ("on_release", "on_click"):
            self.callbacks.fire(Event(event_type, source=self, data=dict(self._data)))
        return changed

    # ── repr ──────────────────────────────────────────────────────────

    def __repr__(self) -> str:
        props = ", ".join(
            f"{k}={v:.4g}" if isinstance(v, float) else f"{k}={v!r}"
            for k, v in self._data.items()
            if k not in ("id", "type", "color")
        )
        return f"{type(self).__name__}({props})"

    @property
    def id(self) -> str:
        """Return the widget's unique identifier."""
        return self._id


# ---------------------------------------------------------------------------
# 2-D widgets
# ---------------------------------------------------------------------------

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
    vertices : list of (x, y) tuples
        Polygon vertices in pixel/data coordinates.
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


# ---------------------------------------------------------------------------
# 1-D widgets
# ---------------------------------------------------------------------------

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
    """
    def __init__(self, push_fn, *, x, color="#00e5ff"):
        super().__init__("vline", push_fn, x=float(x), color=color)


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
    """
    def __init__(self, push_fn, *, y, color="#00e5ff"):
        super().__init__("hline", push_fn, y=float(y), color=color)


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
    """
    def __init__(self, push_fn, *, x0, x1, color="#00e5ff",
                 style: str = "band", y: float = 0.0):
        super().__init__("range", push_fn,
                         x0=float(x0), x1=float(x1), color=color,
                         style=str(style), y=float(y))


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
    """
    def __init__(self, push_fn, *, x, y, color="#00e5ff", show_crosshair=True):
        super().__init__("point", push_fn, x=float(x), y=float(y), color=color,
                         show_crosshair=bool(show_crosshair))

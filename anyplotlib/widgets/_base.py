"""
widgets/_base.py
================
Base Widget class shared by all interactive overlay widgets.
"""

from __future__ import annotations
import uuid as _uuid
from typing import Any, Callable
from anyplotlib.callbacks import CallbackRegistry, Event, _EventMixin

#: Recognised coordinate frames for widget geometry.
COORDS = ("pixel", "data")


def _check_coords(coords: str) -> str:
    if coords not in COORDS:
        raise ValueError(f"coords must be one of {COORDS}, got {coords!r}")
    return coords


def _check_data_only(coords: str) -> str:
    """Validate ``coords`` on a panel whose widgets are always in data units
    (1-D lines, bars).  Accepting ``"data"`` lets code that also drives 2-D
    panels pass ``coords="data"`` everywhere."""
    if coords != "data":
        raise ValueError(
            f"widgets on this panel are positioned in data coordinates; "
            f"coords must be 'data', got {coords!r}")
    return coords


def _convert_role(role: str, value, transform, to_pixels: bool):
    """Convert one geometry value between data and pixel coordinates.

    *role* says what the value is (see ``Widget._GEOMETRY``):

    ``"x"`` / ``"y"``
        A position along that axis.
    ``"dx"`` / ``"dy"`` / ``"r"``
        A non-negative length along x / y (``"r"`` is a radius, which on a
        2-D panel follows the x calibration since circles are drawn round in
        pixel space).
    ``"u"`` / ``"v"``
        A signed displacement along x / y (an arrow vector).
    ``"points"``
        A list of ``[x, y]`` pairs.
    ``"strokes"``
        A list of lists of ``[x, y]`` pairs.
    ``"x_list"`` / ``"y_list"``
        A list of positions along one axis (``snap_values``).
    """
    if value is None:
        return None
    t = transform
    if role == "x":
        return float(t.x_to_pixel(value) if to_pixels else t.pixel_to_x(value))
    if role == "y":
        return float(t.y_to_pixel(value) if to_pixels else t.pixel_to_y(value))
    if role in ("dx", "r"):
        return float(t.x_length_to_pixels(value) if to_pixels
                     else t.pixels_to_x_length(value))
    if role == "dy":
        return float(t.y_length_to_pixels(value) if to_pixels
                     else t.pixels_to_y_length(value))
    if role == "u":
        return float(value) / t.x_scale if to_pixels else float(value) * t.x_scale
    if role == "v":
        return float(value) / t.y_scale if to_pixels else float(value) * t.y_scale
    if role == "points":
        if len(value) == 0:
            return []
        fn = t.data_to_pixel if to_pixels else t.pixel_to_data
        return fn([[float(a), float(b)] for a, b in value]).tolist()
    if role == "strokes":
        return [_convert_role("points", stroke, t, to_pixels) for stroke in value]
    if role in ("x_list", "y_list"):
        axis = role[0]
        return [_convert_role(axis, v, t, to_pixels) for v in value]
    raise ValueError(f"unknown geometry role {role!r}")  # pragma: no cover


class Widget(_EventMixin):
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
        Event callback registry. Register handlers via
        ``widget.add_event_handler(fn, "pointer_move")`` or as a decorator:
        ``@widget.add_event_handler("pointer_move")``.

        Common event types:

        - ``"pointer_move"`` — fires on every drag frame
        - ``"pointer_up"`` — fires once when drag settles
        - ``"pointer_down"`` — fires on click/press event
    """

    # Set by _PanelMixin._make_widget_push_fn when the widget is added to a
    # plot; stays None for a widget constructed standalone (e.g. in a test).
    _plot = None

    #: Coordinate frame for reads and writes; set by the plot's ``add_*``
    #: method.  ``None`` means "the panel's native frame" (see :attr:`coords`).
    _coords = None

    #: ``{field: role}`` for every geometric field, used to convert between
    #: data and pixel coordinates.  See ``_convert_role`` for the roles.
    #: Subclasses override; non-geometric fields (colour, …) are left alone.
    _GEOMETRY: dict = {}

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
            value = self._data[key]
        except KeyError:
            raise AttributeError(
                f"{type(self).__name__} has no attribute {key!r}. "
                f"Available: {list(self._data)}"
            ) from None
        return self._geom_out({key: value})[key]

    # ── attribute write — routes public assignments through set() ────

    def __setattr__(self, key: str, value) -> None:
        """Update widget properties via attribute assignment."""
        # Private attrs and 'callbacks' bypass set()
        if key.startswith("_") or key == "callbacks":
            super().__setattr__(key, value)
            return
        # Read-only properties (plot, kind, id, ...) must not be shadowed by a
        # same-named entry in the wire state; let ``property`` raise.
        attr = getattr(type(self), key, None)
        if isinstance(attr, property) and attr.fset is None:
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

    def set(self, _push: bool = True, _notify: bool = True, *,
            notify: bool | None = None, **kwargs) -> None:
        """Update properties and send targeted update to JavaScript.

        Parameters
        ----------
        notify : bool, optional
            Whether to fire ``pointer_move`` callbacks.  Default ``True``.

            A ``set()`` from Python is otherwise indistinguishable from a user
            drag: handlers that react to the widget moving will run, and one
            that writes back to the widget feeds into itself.  Pass
            ``notify=False`` when *you* are the one moving the widget and the
            handlers are only meant to hear about user input::

                widget.set(x=new_x, notify=False)

            This supersedes wrapping the call in :meth:`pause_events`, which
            suppresses every event type for the duration rather than just this
            update's echo.
        _notify : bool, optional
            Older spelling of ``notify``, kept as an alias.  ``notify`` wins
            when both are given.
        _push : bool, optional
            Whether to push update to renderer. Default True.
            Set to False internally to avoid echo loops.
        **kwargs : dict
            Properties to update (e.g., x=100, y=50, radius=20).  Geometry is
            read in the widget's :attr:`coords` frame, so a widget created
            with ``coords="data"`` takes calibrated values here.

        Notes
        -----
        No widget has a property called ``notify``, so the keyword cannot
        collide with one; ``_notify`` / ``_push`` keep their leading
        underscore for the same reason.

        Updates are sent as targeted widget updates, not full panel re-renders.
        This is more efficient for frequent updates during dragging.
        """
        if notify is None:
            notify = _notify
        self._set_pixels(_push, notify, **self._geom_in(kwargs))

    def _set_pixels(self, _push: bool = True, notify: bool = True,
                    **kwargs) -> None:
        """:meth:`set` without coordinate conversion: *kwargs* are already
        in the wire (image-pixel) frame."""
        self._data.update(kwargs)
        if _push:
            self._push_fn()
        if notify:
            self.callbacks.fire(Event("pointer_move", source=self))

    def get(self, key: str, default=None, *, coords: str | None = None):
        """Get a widget property by name.

        Parameters
        ----------
        key : str
            Property name.
        default : optional
            Default value if property not found.
        coords : ``"pixel"`` | ``"data"``, optional
            Frame to report geometry in.  Defaults to the widget's
            :attr:`coords`.  Ignored on panels without a pixel frame (1-D).

        Returns
        -------
        object
            The property value.
        """
        if key not in self._data:
            return default
        return self._geom_out({key: self._data[key]}, coords)[key]

    def to_dict(self, *, coords: str | None = None) -> dict:
        """Return a dict copy of the widget state.

        Parameters
        ----------
        coords : ``"pixel"`` | ``"data"``, optional
            Frame to report geometry in.  Defaults to the widget's
            :attr:`coords`.

        Returns
        -------
        dict
            All widget properties including id and type.
        """
        return self._geom_out(dict(self._data), coords)

    def _wire_dict(self) -> dict:
        """The widget state exactly as the renderer receives it (pixels)."""
        return dict(self._data)

    # ── coordinate frames ─────────────────────────────────────────────────

    def _transform(self):
        """The owning panel's :class:`~anyplotlib.ImageTransform`, or ``None``
        when the panel has no separate pixel frame (1-D, bar, 3-D, detached)."""
        from anyplotlib.plot2d._transform import ImageTransform
        t = getattr(self._plot, "transform", None)
        return t if isinstance(t, ImageTransform) else None

    @property
    def coords(self) -> str:
        """Coordinate frame of this widget's geometry: ``"pixel"`` or ``"data"``.

        On a 2-D image panel, ``"pixel"`` (the default) means image pixels —
        integer *i* is the centre of pixel *i*, row 0 at the top — and
        ``"data"`` means the calibrated values of the panel's axes.  Attribute
        reads (``widget.cx``), :meth:`get`, :meth:`to_dict` and :meth:`set`
        all use this frame; drag callbacks therefore see calibrated values on
        a ``"data"`` widget.  Choose it with ``coords=`` on the plot's
        ``add_*_widget`` method, or change it with :meth:`set_coords`.

        On 1-D and bar panels positions are always in data units, so this is
        ``"data"``.

        Notes
        -----
        The renderer always works in pixels, so a widget stores pixels and a
        ``"data"`` widget converts on every read and write.  Re-calibrating
        the panel (:meth:`~anyplotlib.Plot2D.set_extent`) therefore keeps the
        widget on the same *pixels*; its data-coordinate values change.
        """
        if self._coords is not None:
            return self._coords
        return "pixel" if self._transform() is not None else "data"

    def set_coords(self, coords: str) -> None:
        """Switch the frame used for reading and writing geometry.

        Does not move the widget.

        Parameters
        ----------
        coords : ``"pixel"`` | ``"data"``
        """
        self._coords = _check_coords(coords)

    def _geom_convert(self, fields: dict, to_pixels: bool,
                      coords: str | None = None) -> dict:
        frame = self.coords if coords is None else _check_coords(coords)
        if frame != "data" or not self._GEOMETRY:
            return fields
        t = self._transform()
        if t is None:
            return fields
        out = dict(fields)
        for key, role in self._GEOMETRY.items():
            if key in out:
                out[key] = _convert_role(role, out[key], t, to_pixels)
        return out

    def _geom_in(self, fields: dict, coords: str | None = None) -> dict:
        """User-frame *fields* → wire (pixel) frame."""
        return self._geom_convert(fields, True, coords)

    def _geom_out(self, fields: dict, coords: str | None = None) -> dict:
        """Wire (pixel) *fields* → user frame."""
        return self._geom_convert(fields, False, coords)

    # ── visibility ────────────────────────────────────────────────────────

    @property
    def visible(self) -> bool:
        """``True`` if the widget is rendered; ``False`` if hidden."""
        return self._data.get("visible", True)

    @visible.setter
    def visible(self, value: bool) -> None:
        self.show() if value else self.hide()

    def show(self) -> None:
        """Show the widget.  Does not fire ``pointer_move`` callbacks."""
        self._data["visible"] = True
        self._push_fn()

    def hide(self) -> None:
        """Hide the widget without removing it or its callbacks.

        Call :meth:`show` to make it visible again.
        Does not fire ``pointer_move`` callbacks.
        """
        self._data["visible"] = False
        self._push_fn()

    # ── removal ───────────────────────────────────────────────────────────

    def remove(self) -> None:
        """Remove this widget from the plot that owns it.

        Equivalent to ``plot.remove_widget(widget)``, but callable when you
        only hold the widget — handle-based APIs otherwise have to re-derive
        the owning plot to delete something they already have.

        Removing a widget that is not attached to a plot, or removing twice,
        is a no-op.
        """
        plot = self._plot
        if plot is None:
            return
        try:
            plot.remove_widget(self._id)
        except KeyError:
            pass  # already removed (e.g. via clear_widgets)

    # ── JS → Python sync ──────────────────────────────────────────────

    def _update_from_js(self, msg: dict, event_type: str = "pointer_move") -> bool:
        """Apply incoming JS state without pushing back (avoids echo).

        Updates widget ``_data`` with widget-specific state fields from msg,
        then fires widget callbacks with a flat Event.

        Parameters
        ----------
        msg : dict
            Full raw event message from JS.
        event_type : str
            One of the pointer event types (``pointer_move``, ``pointer_up``,
            ``pointer_down``).

        Returns
        -------
        bool
            True if any widget state changed.
        """
        _envelope = {
            "source", "panel_id", "event_type", "widget_id",
            "time_stamp", "modifiers", "button", "buttons",
        }
        changed = False
        for k, v in msg.items():
            if k in ("id", "type") or k in _envelope:
                continue
            if self._data.get(k) != v:
                self._data[k] = v
                changed = True

        if changed or event_type in ("pointer_up", "pointer_down"):
            event = Event(
                event_type=event_type,
                source=self,
                time_stamp=msg.get("time_stamp", 0.0),
                modifiers=msg.get("modifiers", []),
                x=msg.get("x"),
                y=msg.get("y"),
                button=msg.get("button"),
                buttons=msg.get("buttons", 0),
                xdata=msg.get("xdata"),
                ydata=msg.get("ydata"),
            )
            self.callbacks.fire(event)
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

    # ── identity ──────────────────────────────────────────────────────────

    @property
    def kind(self) -> str:
        """The widget kind, e.g. ``"rectangle"``, ``"crosshair"``, ``"vline"``.

        The same string :meth:`~anyplotlib.Plot2D.add_widget` dispatches on
        (and ``widget.get("type")`` returns), so code holding only a widget
        can branch on what it is without ``isinstance`` checks.
        """
        return self._type

    @property
    def plot(self):
        """The plot this widget is attached to, or ``None``.

        ``None`` for a widget constructed standalone, and again once the
        widget has been removed (:meth:`remove`, ``plot.remove_widget`` or
        ``plot.clear_widgets``).
        """
        return self._plot

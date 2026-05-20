"""
widgets/_base.py
================
Base Widget class shared by all interactive overlay widgets.
"""

from __future__ import annotations
import uuid as _uuid
from typing import Any, Callable
from anyplotlib.callbacks import CallbackRegistry, Event, _EventMixin


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
        self.callbacks.fire(Event("pointer_move", source=self))

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

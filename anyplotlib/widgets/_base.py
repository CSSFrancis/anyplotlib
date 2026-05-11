"""
widgets/_base.py
================
Base Widget class shared by all interactive overlay widgets.
"""

from __future__ import annotations
import uuid as _uuid
from typing import Any
from anyplotlib.callbacks import CallbackRegistry, Event


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

    def __init__(self, wtype: str, push_fn, **kwargs):
        self._id: str = str(_uuid.uuid4())[:8]
        self._type: str = wtype
        self._data: dict = dict(kwargs)
        self._data["id"] = self._id
        self._data["type"] = wtype
        self._push_fn = push_fn
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

    def on_changed(self, fn) -> Any:
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

    def on_release(self, fn) -> Any:
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

    def on_click(self, fn) -> Any:
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

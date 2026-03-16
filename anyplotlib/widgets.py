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
    "VLineWidget", "HLineWidget", "RangeWidget",
]


class Widget:
    """Base class for all overlay widgets."""

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
        """Update properties.  Sends a targeted event_json update to JS
        (not a full panel push).  Fires on_changed callbacks.

        Use _push=False internally (e.g. _update_from_js) to avoid echo.
        """
        self._data.update(kwargs)
        if _push:
            self._push_fn()
        self.callbacks.fire(Event("on_changed", source=self, data=dict(self._data)))

    def get(self, key: str, default=None):
        return self._data.get(key, default)

    def to_dict(self) -> dict:
        return dict(self._data)

    # ── callback decorator methods ────────────────────────────────────

    def on_changed(self, fn: Callable) -> Callable:
        """Decorator: register fn to fire on every drag frame."""
        cid = self.callbacks.connect("on_changed", fn)
        fn._cid = cid
        return fn

    def on_release(self, fn: Callable) -> Callable:
        """Decorator: register fn to fire once when drag settles."""
        cid = self.callbacks.connect("on_release", fn)
        fn._cid = cid
        return fn

    def on_click(self, fn: Callable) -> Callable:
        """Decorator: register fn to fire on click."""
        cid = self.callbacks.connect("on_click", fn)
        fn._cid = cid
        return fn

    def disconnect(self, cid) -> None:
        """Remove the callback registered under *cid*.

        Accepts either the integer CID returned by ``callbacks.connect()``,
        or the decorated function itself (which carries a ``._cid`` attribute).
        """
        if callable(cid) and hasattr(cid, "_cid"):
            cid = cid._cid
        self.callbacks.disconnect(cid)

    # ── JS → Python sync ──────────────────────────────────────────────

    def _update_from_js(self, new_data: dict, event_type: str = "on_changed") -> bool:
        """Apply incoming JS state without pushing back (avoids echo).
        Fires self.callbacks with event_type.  Returns True if data changed.
        Always fires for on_release / on_click even when nothing changed.
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
        return self._id


# ---------------------------------------------------------------------------
# 2-D widgets
# ---------------------------------------------------------------------------

class RectangleWidget(Widget):
    def __init__(self, push_fn, *, x, y, w, h, color="#00e5ff"):
        super().__init__("rectangle", push_fn,
                         x=float(x), y=float(y),
                         w=float(w), h=float(h), color=color)


class CircleWidget(Widget):
    def __init__(self, push_fn, *, cx, cy, r, color="#00e5ff"):
        super().__init__("circle", push_fn,
                         cx=float(cx), cy=float(cy), r=float(r), color=color)


class AnnularWidget(Widget):
    def __init__(self, push_fn, *, cx, cy, r_outer, r_inner, color="#00e5ff"):
        if r_inner >= r_outer:
            raise ValueError("r_inner must be < r_outer")
        super().__init__("annular", push_fn,
                         cx=float(cx), cy=float(cy),
                         r_outer=float(r_outer), r_inner=float(r_inner),
                         color=color)


class CrosshairWidget(Widget):
    def __init__(self, push_fn, *, cx, cy, color="#00e5ff"):
        super().__init__("crosshair", push_fn,
                         cx=float(cx), cy=float(cy), color=color)


class PolygonWidget(Widget):
    def __init__(self, push_fn, *, vertices, color="#00e5ff"):
        verts = [[float(x), float(y)] for x, y in vertices]
        if len(verts) < 3:
            raise ValueError("polygon needs >= 3 vertices")
        super().__init__("polygon", push_fn, vertices=verts, color=color)


class LabelWidget(Widget):
    def __init__(self, push_fn, *, x, y, text="Label", fontsize=14,
                 color="#00e5ff"):
        super().__init__("label", push_fn,
                         x=float(x), y=float(y),
                         text=str(text), fontsize=int(fontsize), color=color)


# ---------------------------------------------------------------------------
# 1-D widgets
# ---------------------------------------------------------------------------

class VLineWidget(Widget):
    def __init__(self, push_fn, *, x, color="#00e5ff"):
        super().__init__("vline", push_fn, x=float(x), color=color)


class HLineWidget(Widget):
    def __init__(self, push_fn, *, y, color="#00e5ff"):
        super().__init__("hline", push_fn, y=float(y), color=color)


class RangeWidget(Widget):
    def __init__(self, push_fn, *, x0, x1, color="#00e5ff"):
        super().__init__("range", push_fn, x0=float(x0), x1=float(x1), color=color)

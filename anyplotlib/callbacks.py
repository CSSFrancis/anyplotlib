"""
callbacks.py
============

Lightweight two-class event system used by every plot object and widget.

:class:`CallbackRegistry`
    Per-object store of named callbacks.  Every plot object and widget
    exposes ``on_changed``, ``on_release``, ``on_click``, and ``on_key``
    decorator methods that connect handlers through this registry.

:class:`Event`
    Immutable data-carrier passed to every callback.  All keys in the
    raw JS payload are accessible as attributes (``event.zoom``,
    ``event.cx``, etc.) in addition to the typed ``event_type``,
    ``source``, and ``data`` fields.

Example
-------
.. code-block:: python

    fig, ax = apl.subplots(1, 1)
    plot = ax.imshow(data)

    @plot.on_release
    def on_settle(event):
        print(f"zoom={event.zoom:.2f}  center=({event.center_x:.3f}, {event.center_y:.3f})")
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Callable

_VALID_EVENT_TYPES = ("on_click", "on_changed", "on_release", "on_key")


@dataclass
class Event:
    """A single interactive event.
    event_type: one of on_click / on_changed / on_release
    source: the originating Python object (Widget, Plot, or None)
    data: full state dict; all keys also accessible as event.x
    """
    event_type: str
    source:     Any
    data:       dict = field(default_factory=dict)

    def __getattr__(self, key: str) -> Any:
        try:
            return self.data[key]
        except KeyError:
            raise AttributeError(
                f"Event has no attribute {key!r}. "
                f"Available data keys: {list(self.data)}"
            ) from None

    def __repr__(self) -> str:
        src = type(self.source).__name__ if self.source is not None else "None"
        parts = [f"event_type={self.event_type!r}", f"source={src}"]
        _skip = {"id", "type", "color", "colormap_data",
                 "image_b64", "histogram_data", "colormap_name"}
        shown = 0
        for k, v in self.data.items():
            if k in _skip or shown >= 6:
                continue
            parts.append(
                f"{k}={v:.4g}" if isinstance(v, float) else f"{k}={v!r}"
            )
            shown += 1
        return "Event(" + ", ".join(parts) + ")"


class CallbackRegistry:
    """Per-object registry for on_click / on_changed / on_release callbacks."""

    def __init__(self) -> None:
        self._next_cid: int = 1
        self._entries: dict[int, tuple[str, Callable]] = {}

    def connect(self, event_type: str, fn: Callable) -> int:
        """Register fn for event_type.  Returns integer CID."""
        if event_type not in _VALID_EVENT_TYPES:
            raise ValueError(
                f"event_type must be one of {_VALID_EVENT_TYPES}, got {event_type!r}"
            )
        cid = self._next_cid
        self._next_cid += 1
        self._entries[cid] = (event_type, fn)
        return cid

    def disconnect(self, cid: int) -> None:
        """Remove handler for cid.  Silent if not found."""
        self._entries.pop(cid, None)

    def fire(self, event) -> None:
        """Dispatch event to all handlers matching event.event_type."""
        for _cid, (et, fn) in list(self._entries.items()):
            if et == event.event_type:
                fn(event)

    def __bool__(self) -> bool:
        return bool(self._entries)

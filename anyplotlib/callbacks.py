"""
callbacks.py
============

Event system used by all plot objects and widgets.

:class:`Event`
    Flat dataclass carrying all event fields as typed top-level attributes.

:class:`CallbackRegistry`
    Per-object handler store. (Full implementation added in Tasks 2-3.)

:class:`_EventMixin`
    Mixin added to every plot class and widget. (Added in Task 4.)
"""
from __future__ import annotations

import time
from collections import defaultdict, deque
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Callable

VALID_EVENT_TYPES = frozenset({
    "pointer_down", "pointer_up", "pointer_move", "pointer_settled",
    "pointer_enter", "pointer_leave", "double_click", "wheel",
    "key_down", "key_up", "*",
})


@dataclass
class Event:
    """A single interactive event with all payload fields as typed attributes.

    Universal fields (every event):
        event_type, source, time_stamp, modifiers

    Pointer fields (pointer_* and double_click events):
        x, y           — pixel coordinates within the panel
        button         — 0=left 1=middle 2=right; None on move/enter/leave/settled
        buttons        — bitmask of currently held buttons
        xdata, ydata   — data-space coordinates (None for Plot3D)
        ray            — Plot3D only: {"origin": [...], "direction": [...]}
        line_id        — Plot1D only: set when pointer is over a line
        dwell_ms       — pointer_settled only: actual dwell time

    PlotBar extra fields (pointer_down only):
        bar_index, value, x_label, group_index

    Wheel fields:
        dx, dy         — scroll deltas

    Key fields:
        key            — key name e.g. "q", "Enter", "ArrowLeft"

    Propagation:
        stop_propagation — set True inside a handler to halt remaining handlers
    """
    event_type: str
    source: Any = None
    time_stamp: float = field(default_factory=time.perf_counter)
    modifiers: list[str] = field(default_factory=list)
    # Pointer
    x: int | None = None
    y: int | None = None
    button: int | None = None
    buttons: int = 0
    xdata: float | None = None
    ydata: float | None = None
    ray: dict | None = None
    line_id: str | None = None
    dwell_ms: float | None = None
    # PlotBar
    bar_index: int | None = None
    value: float | None = None
    x_label: str | None = None
    group_index: int | None = None
    # Wheel
    dx: float | None = None
    dy: float | None = None
    # Key
    key: str | None = None
    # Propagation (not repr'd)
    stop_propagation: bool = field(default=False, repr=False)

    def __repr__(self) -> str:
        src = type(self.source).__name__ if self.source is not None else "None"
        parts = [f"event_type={self.event_type!r}", f"source={src}"]
        for fname in ("x", "y", "xdata", "ydata", "button", "key",
                      "line_id", "bar_index", "dwell_ms"):
            v = getattr(self, fname)
            if v is not None:
                parts.append(f"{fname}={v!r}")
        if self.modifiers:
            parts.append(f"modifiers={self.modifiers!r}")
        return "Event(" + ", ".join(parts) + ")"


class CallbackRegistry:
    """Minimal placeholder — full implementation in Task 2."""

    def __init__(self) -> None:
        self._next_cid: int = 1
        self._entries: dict[int, tuple[str, Callable]] = {}

    def connect(self, event_type: str, fn: Callable) -> int:
        if event_type not in VALID_EVENT_TYPES:
            raise ValueError(
                f"Invalid event_type {event_type!r}. "
                f"Valid types: {sorted(t for t in VALID_EVENT_TYPES if t != '*')} or '*'"
            )
        cid = self._next_cid
        self._next_cid += 1
        self._entries[cid] = (event_type, fn)
        return cid

    def disconnect(self, cid: int) -> None:
        self._entries.pop(cid, None)

    def fire(self, event: Event) -> None:
        for _cid, (et, fn) in list(self._entries.items()):
            if et == event.event_type:
                fn(event)

    def __bool__(self) -> bool:
        return bool(self._entries)

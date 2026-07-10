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
    "key_down", "key_up", "close", "view_changed", "*",
})


@dataclass
class Event:
    """A single interactive event with all payload fields as typed attributes.

    Universal fields (every event):
        event_type, source, time_stamp, modifiers

    Pointer fields (pointer_* and double_click events):
        x, y           — canvas coordinates within the panel (float pixels)
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
        last_widget_id — id of the last widget the user clicked, or None

    Propagation:
        stop_propagation — set True inside a handler to halt remaining handlers
    """
    event_type: str
    source: Any = None
    time_stamp: float = field(default_factory=time.perf_counter)
    modifiers: list[str] = field(default_factory=list)
    # Pointer
    x: float | None = None
    y: float | None = None
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
    # View (view_changed events — the current zoom/pan viewport)
    zoom: float | None = None
    center_x: float | None = None
    center_y: float | None = None
    image_width: int | None = None
    image_height: int | None = None
    display_width: int | None = None    # panel device px (JS) → tile output resolution
    display_height: int | None = None
    # Key
    key: str | None = None
    last_widget_id: str | None = None
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
    """Per-object handler store.

    Supports:
    - Priority ordering (``order`` kwarg — lower fires first)
    - Wildcard ``"*"`` type receives every dispatched event
    - ``stop_propagation`` on the event halts remaining handlers
    - ``disconnect_fn(fn, *types)`` removes by callback reference
    - ``pause_events`` / ``hold_events`` context managers (added in Task 3)
    """

    def __init__(self) -> None:
        # {event_type: [(order, cid, fn), ...]} — sorted by order
        self._handlers: dict[str, list[tuple[float, int, Callable]]] = defaultdict(list)
        self._next_cid: int = 1
        # {cid: set[str]} — which types this cid is registered under
        self._cid_map: dict[int, set[str]] = {}
        # {id(fn): set[int]} — which cids this fn owns
        self._fn_map: dict[int, set[int]] = defaultdict(set)
        # pause/hold state (populated in Task 3)
        self._pause_counts: dict[str, int] = {}
        self._hold_counts: dict[str, int] = {}
        self._held: deque[Event] = deque()

    # ── registration ─────────────────────────────────────────────────────

    def connect(self, event_type: str, fn: Callable, *, order: float = 0) -> int:
        """Register fn for event_type. Returns integer CID."""
        if event_type not in VALID_EVENT_TYPES:
            raise ValueError(
                f"Invalid event_type {event_type!r}. "
                f"Valid types: {sorted(t for t in VALID_EVENT_TYPES if t != '*')} or '*'"
            )
        cid = self._next_cid
        self._next_cid += 1
        self._handlers[event_type].append((order, cid, fn))
        self._handlers[event_type].sort(key=lambda t: t[0])
        self._cid_map.setdefault(cid, set()).add(event_type)
        self._fn_map[id(fn)].add(cid)
        return cid

    def disconnect(self, cid: int) -> None:
        """Remove handler by CID. Silent if not found."""
        types = self._cid_map.pop(cid, set())
        for et in types:
            self._handlers[et] = [
                (o, c, f) for o, c, f in self._handlers[et] if c != cid
            ]
        for fn_cids in self._fn_map.values():
            fn_cids.discard(cid)

    def disconnect_fn(self, fn: Callable, *types: str) -> None:
        """Remove fn from the given types (all types if none given)."""
        for cid in list(self._fn_map.get(id(fn), set())):
            cid_types = self._cid_map.get(cid, set())
            if not types or cid_types & set(types):
                self.disconnect(cid)

    # ── dispatch ─────────────────────────────────────────────────────────

    def fire(self, event: Event) -> None:
        """Dispatch event to matching handlers (respects pause/hold)."""
        et = event.event_type
        if self._pause_counts.get(et, 0) > 0 or self._pause_counts.get("*", 0) > 0:
            return
        if self._hold_counts.get(et, 0) > 0 or self._hold_counts.get("*", 0) > 0:
            self._held.append(event)
            return
        self._dispatch(event)

    def _dispatch(self, event: Event) -> None:
        et = event.event_type
        specific = list(self._handlers.get(et, []))
        wildcard = list(self._handlers.get("*", []))
        merged = sorted(specific + wildcard, key=lambda t: t[0])
        for _order, _cid, fn in merged:
            if event.stop_propagation:
                break
            fn(event)

    def _flush(self) -> None:
        while self._held:
            self._dispatch(self._held.popleft())

    @contextmanager
    def pause_events(self, *types: str):
        """Suppress events of the given types while inside this context.
        All types are paused when called with no arguments.
        Pause wins over hold for the same type."""
        target = types if types else ("*",)
        for t in target:
            self._pause_counts[t] = self._pause_counts.get(t, 0) + 1
        try:
            yield
        finally:
            for t in target:
                self._pause_counts[t] -= 1
                if self._pause_counts[t] == 0:
                    del self._pause_counts[t]

    @contextmanager
    def hold_events(self, *types: str):
        """Buffer events of the given types; flush when the outermost hold exits.
        All types are held when called with no arguments."""
        target = types if types else ("*",)
        for t in target:
            self._hold_counts[t] = self._hold_counts.get(t, 0) + 1
        try:
            yield
        finally:
            for t in target:
                self._hold_counts[t] -= 1
                if self._hold_counts[t] == 0:
                    del self._hold_counts[t]
            if not self._hold_counts:
                self._flush()

    def __bool__(self) -> bool:
        return any(bool(v) for v in self._handlers.values())


class _EventMixin:
    """Mixin for plot classes and widgets.

    Provides ``add_event_handler`` / ``remove_handler`` / ``pause_events`` /
    ``hold_events``.  The host class must set ``self.callbacks = CallbackRegistry()``
    in its ``__init__``.
    """

    callbacks: CallbackRegistry

    def add_event_handler(
        self,
        fn_or_type,
        *args,
        order: float = 0,
        ms: int = 300,
        delta: float = 4,
    ):
        """Register an event handler. Works as a direct call or decorator.

        Direct call::

            plot.add_event_handler(fn, "pointer_down")
            plot.add_event_handler(fn, "pointer_down", "pointer_up")

        Decorator::

            @plot.add_event_handler("pointer_down")
            def handler(event): ...

            @plot.add_event_handler("pointer_settled", ms=400, delta=5)
            def on_settle(event): ...

        Parameters
        ----------
        fn_or_type : callable or str
            Handler function (direct call) or first event type string (decorator).
        *args : str
            Remaining event type strings.
        order : float
            Priority. Lower fires first. Default 0.
        ms : int
            ``pointer_settled`` dwell threshold in milliseconds. Default 300.
            Raises ``ValueError`` if provided without ``"pointer_settled"`` in types.
        delta : float
            ``pointer_settled`` pixel radius. Default 4.
            Raises ``ValueError`` if provided without ``"pointer_settled"`` in types.
        """
        if callable(fn_or_type):
            return self._register(fn_or_type, args, order=order, ms=ms, delta=delta)
        else:
            all_types = (fn_or_type,) + args
            def _decorator(fn: Callable) -> Callable:
                self._register(fn, all_types, order=order, ms=ms, delta=delta)
                return fn
            return _decorator

    def _register(
        self, fn: Callable, types: tuple, *, order: float, ms: int, delta: float
    ) -> Callable:
        has_settled = "pointer_settled" in types
        _ms_changed = ms != 300
        _delta_changed = delta != 4
        if (_ms_changed or _delta_changed) and not has_settled:
            raise ValueError(
                "ms/delta kwargs are only valid when 'pointer_settled' is in the event types"
            )
        for event_type in types:
            self.callbacks.connect(event_type, fn, order=order)
        if has_settled:
            self._configure_pointer_settled(ms, delta)
        fn._event_types = getattr(fn, "_event_types", set()) | set(types)
        return fn

    def remove_handler(self, cid_or_fn, *types: str) -> None:
        """Remove a registered handler.

        Parameters
        ----------
        cid_or_fn : int or callable
            CID returned by ``callbacks.connect()`` or the handler function.
        *types : str
            If given, only remove from these types. If omitted, remove from all.
        """
        had_settled = bool(self.callbacks._handlers.get("pointer_settled"))
        if isinstance(cid_or_fn, int):
            self.callbacks.disconnect(cid_or_fn)
        else:
            self.callbacks.disconnect_fn(cid_or_fn, *types)
        if had_settled and not self.callbacks._handlers.get("pointer_settled"):
            self._configure_pointer_settled(0, 0)

    def _configure_pointer_settled(self, ms: int, delta: float) -> None:
        """Override in plot subclasses to push thresholds to JS."""
        pass

    @contextmanager
    def pause_events(self, *types: str):
        """Suppress events of the given types (all types if none given)."""
        with self.callbacks.pause_events(*types):
            yield

    @contextmanager
    def hold_events(self, *types: str):
        """Buffer events of the given types; flush when context exits."""
        with self.callbacks.hold_events(*types):
            yield

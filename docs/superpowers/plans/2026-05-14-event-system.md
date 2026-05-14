# Event System Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the existing `on_click`/`on_changed`/`on_release`/`on_key` event system with pygfx-aligned `pointer_*`/`key_*` events, a flat `Event` dataclass, multi-type/wildcard/priority registration, `pause_events`/`hold_events` context managers, and `pointer_settled` with per-panel JS timer.

**Architecture:** Python-first — rewrite `CallbackRegistry` and `Event` in `callbacks.py`, add `_EventMixin` for the user-facing API, then update all plot/widget classes to inherit it. JS changes forward new event types and add the `pointer_settled` dwell timer. All old decorator methods (`on_click`, `on_changed`, etc.) are removed.

**Tech Stack:** Python 3.10+, dataclasses, contextlib, anywidget traitlets, Playwright for browser tests, pytest.

**Spec:** `docs/superpowers/specs/2026-05-14-event-system-design.md`

---

## File Map

**Modified:**
- `anyplotlib/callbacks.py` — rewrite `Event`, `CallbackRegistry`; add `_EventMixin`
- `anyplotlib/figure/_figure.py` — update `_dispatch_event` field mapping; add `import time`
- `anyplotlib/plot1d/_plot1d.py` — inherit `_EventMixin`, remove old decorators, update `Line1D`
- `anyplotlib/plot2d/_plot2d.py` — same pattern
- `anyplotlib/plot2d/_plotmesh.py` — same pattern (inherits Plot2D, may need minimal changes)
- `anyplotlib/plot3d/_plot3d.py` — same pattern + `ray` field in state
- `anyplotlib/plot1d/_plotbar.py` — same pattern + updated pointer_down payload
- `anyplotlib/widgets/_base.py` — inherit `_EventMixin`, remove old decorators, update `_update_from_js`
- `anyplotlib/figure_esm.js` — forward new event types, add fields, pointer_settled timer, remove registered_keys

**Replaced:**
- `anyplotlib/tests/test_interactive/test_callbacks.py` — full rewrite for new API

**Created:**
- `anyplotlib/tests/test_interactive/test_event_plots.py` — Playwright per-plot-type matrix
- `anyplotlib/tests/test_interactive/test_event_settled.py` — pointer_settled Playwright tests
- `anyplotlib/tests/test_interactive/test_event_pause_hold.py` — pause/hold Playwright tests

---

## Task 1: Rewrite `Event` dataclass

Flatten `Event` — all payload fields become top-level typed attributes instead of a `data` dict with `__getattr__` proxy.

**Files:**
- Modify: `anyplotlib/callbacks.py`
- Modify: `anyplotlib/tests/test_interactive/test_callbacks.py`

- [ ] **Step 1: Write the failing tests**

Replace the top of `anyplotlib/tests/test_interactive/test_callbacks.py` with:

```python
"""Tests for the redesigned Event dataclass and CallbackRegistry."""
from __future__ import annotations
import time
import pytest
from anyplotlib.callbacks import Event, CallbackRegistry, VALID_EVENT_TYPES


# ── Event dataclass ───────────────────────────────────────────────────────────

class TestEvent:
    def test_required_fields(self):
        e = Event(event_type="pointer_down", source=None)
        assert e.event_type == "pointer_down"
        assert e.source is None

    def test_time_stamp_auto_set(self):
        before = time.perf_counter()
        e = Event(event_type="pointer_down")
        after = time.perf_counter()
        assert before <= e.time_stamp <= after

    def test_modifiers_default_empty_list(self):
        e = Event(event_type="pointer_move")
        assert e.modifiers == []
        assert isinstance(e.modifiers, list)

    def test_pointer_fields_default_none(self):
        e = Event(event_type="pointer_move")
        assert e.x is None
        assert e.y is None
        assert e.button is None
        assert e.buttons == 0
        assert e.xdata is None
        assert e.ydata is None
        assert e.ray is None
        assert e.line_id is None
        assert e.dwell_ms is None

    def test_wheel_fields_default_none(self):
        e = Event(event_type="wheel")
        assert e.dx is None
        assert e.dy is None

    def test_key_field_default_none(self):
        e = Event(event_type="key_down")
        assert e.key is None

    def test_bar_fields_default_none(self):
        e = Event(event_type="pointer_down")
        assert e.bar_index is None
        assert e.value is None
        assert e.x_label is None
        assert e.group_index is None

    def test_stop_propagation_default_false(self):
        e = Event(event_type="pointer_down")
        assert e.stop_propagation is False

    def test_all_fields_settable(self):
        e = Event(
            event_type="pointer_down",
            source="plot",
            modifiers=["ctrl", "shift"],
            x=100, y=200,
            button=0, buttons=1,
            xdata=3.14, ydata=2.71,
            line_id="abc12345",
            bar_index=2, value=99.5, x_label="Jan", group_index=1,
            dx=10.0, dy=-5.0,
            key="q",
        )
        assert e.modifiers == ["ctrl", "shift"]
        assert e.x == 100
        assert e.xdata == 3.14
        assert e.line_id == "abc12345"
        assert e.bar_index == 2
        assert e.key == "q"

    def test_no_data_dict_attribute(self):
        e = Event(event_type="pointer_move")
        assert not hasattr(e, "data")

    def test_repr_includes_event_type(self):
        e = Event(event_type="pointer_down", x=10, y=20)
        assert "pointer_down" in repr(e)
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
uv run pytest anyplotlib/tests/test_interactive/test_callbacks.py::TestEvent -v
```
Expected: FAIL — `Event` still has `data` field, `time_stamp` not auto-set, etc.

- [ ] **Step 3: Rewrite `Event` in `callbacks.py`**

Replace the entire `callbacks.py` with:

```python
"""
callbacks.py
============

Event system used by all plot objects and widgets.

:class:`Event`
    Flat dataclass carrying all event fields as typed top-level attributes.

:class:`CallbackRegistry`
    Per-object handler store with multi-type, wildcard, priority, pause, and hold support.

:class:`_EventMixin`
    Mixin added to every plot class and widget exposing ``add_event_handler`` /
    ``remove_handler`` / ``pause_events`` / ``hold_events``.
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
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
uv run pytest anyplotlib/tests/test_interactive/test_callbacks.py::TestEvent -v
```
Expected: All 11 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add anyplotlib/callbacks.py anyplotlib/tests/test_interactive/test_callbacks.py
git commit -m "refactor: flatten Event dataclass — all payload fields are typed top-level attrs"
```

---

## Task 2: Rewrite `CallbackRegistry`

Replace the simple `_entries` dict with a per-type handler list supporting priority ordering, wildcard `"*"`, multi-type registration, and `stop_propagation`.

**Files:**
- Modify: `anyplotlib/callbacks.py` (append to Task 1 file)
- Modify: `anyplotlib/tests/test_interactive/test_callbacks.py`

- [ ] **Step 1: Write failing tests — append to test file**

```python
class TestCallbackRegistry:
    def test_connect_returns_int_cid(self):
        reg = CallbackRegistry()
        cid = reg.connect("pointer_down", lambda e: None)
        assert isinstance(cid, int)

    def test_fire_calls_handler(self):
        reg = CallbackRegistry()
        calls = []
        reg.connect("pointer_down", lambda e: calls.append(e.event_type))
        reg.fire(Event("pointer_down"))
        assert calls == ["pointer_down"]

    def test_fire_only_matching_type(self):
        reg = CallbackRegistry()
        calls = []
        reg.connect("pointer_down", lambda e: calls.append("down"))
        reg.connect("pointer_up",   lambda e: calls.append("up"))
        reg.fire(Event("pointer_down"))
        assert calls == ["down"]

    def test_disconnect_by_cid(self):
        reg = CallbackRegistry()
        calls = []
        cid = reg.connect("pointer_down", lambda e: calls.append(1))
        reg.disconnect(cid)
        reg.fire(Event("pointer_down"))
        assert calls == []

    def test_disconnect_silent_if_not_found(self):
        reg = CallbackRegistry()
        reg.disconnect(999)  # should not raise

    def test_wildcard_receives_all_types(self):
        reg = CallbackRegistry()
        calls = []
        reg.connect("*", lambda e: calls.append(e.event_type))
        reg.fire(Event("pointer_down"))
        reg.fire(Event("key_down"))
        reg.fire(Event("wheel"))
        assert calls == ["pointer_down", "key_down", "wheel"]

    def test_priority_order(self):
        reg = CallbackRegistry()
        order = []
        reg.connect("pointer_down", lambda e: order.append("second"), order=1)
        reg.connect("pointer_down", lambda e: order.append("first"),  order=0)
        reg.fire(Event("pointer_down"))
        assert order == ["first", "second"]

    def test_same_priority_fires_in_registration_order(self):
        reg = CallbackRegistry()
        order = []
        reg.connect("pointer_down", lambda e: order.append("a"), order=0)
        reg.connect("pointer_down", lambda e: order.append("b"), order=0)
        reg.fire(Event("pointer_down"))
        assert order == ["a", "b"]

    def test_stop_propagation(self):
        reg = CallbackRegistry()
        calls = []
        def handler_a(e):
            calls.append("a")
            e.stop_propagation = True
        reg.connect("pointer_down", handler_a, order=0)
        reg.connect("pointer_down", lambda e: calls.append("b"), order=1)
        reg.fire(Event("pointer_down"))
        assert calls == ["a"]

    def test_disconnect_fn_by_reference(self):
        reg = CallbackRegistry()
        calls = []
        fn = lambda e: calls.append(1)
        reg.connect("pointer_down", fn)
        reg.disconnect_fn(fn)
        reg.fire(Event("pointer_down"))
        assert calls == []

    def test_disconnect_fn_specific_type(self):
        reg = CallbackRegistry()
        calls = []
        fn = lambda e: calls.append(e.event_type)
        reg.connect("pointer_down", fn)
        reg.connect("pointer_up", fn)
        reg.disconnect_fn(fn, "pointer_down")
        reg.fire(Event("pointer_down"))
        reg.fire(Event("pointer_up"))
        assert calls == ["pointer_up"]

    def test_bool_true_when_handlers_present(self):
        reg = CallbackRegistry()
        assert not bool(reg)
        reg.connect("pointer_down", lambda e: None)
        assert bool(reg)

    def test_invalid_event_type_raises(self):
        reg = CallbackRegistry()
        with pytest.raises(ValueError, match="Invalid event_type"):
            reg.connect("on_click", lambda e: None)

    def test_connect_same_fn_multiple_types(self):
        reg = CallbackRegistry()
        calls = []
        fn = lambda e: calls.append(e.event_type)
        reg.connect("pointer_down", fn)
        reg.connect("pointer_up",   fn)
        reg.fire(Event("pointer_down"))
        reg.fire(Event("pointer_up"))
        assert calls == ["pointer_down", "pointer_up"]
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
uv run pytest anyplotlib/tests/test_interactive/test_callbacks.py::TestCallbackRegistry -v
```
Expected: Most FAIL — old `CallbackRegistry` doesn't support priority, wildcard, `disconnect_fn`, or new event type names.

- [ ] **Step 3: Append new `CallbackRegistry` to `callbacks.py`**

Remove the old `CallbackRegistry` class and replace with:

```python
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
        # pause/hold (populated in Task 3)
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

    def __bool__(self) -> bool:
        return any(bool(v) for v in self._handlers.values())
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest anyplotlib/tests/test_interactive/test_callbacks.py::TestCallbackRegistry -v
```
Expected: All 14 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add anyplotlib/callbacks.py anyplotlib/tests/test_interactive/test_callbacks.py
git commit -m "refactor: rewrite CallbackRegistry with priority, wildcard, disconnect_fn, stop_propagation"
```

---

## Task 3: Add `pause_events` / `hold_events` to `CallbackRegistry`

**Files:**
- Modify: `anyplotlib/callbacks.py` (append context managers)
- Modify: `anyplotlib/tests/test_interactive/test_callbacks.py`

- [ ] **Step 1: Write failing tests — append to test file**

```python
class TestPauseHold:
    def test_pause_drops_events(self):
        reg = CallbackRegistry()
        calls = []
        reg.connect("pointer_move", lambda e: calls.append(1))
        with reg.pause_events("pointer_move"):
            reg.fire(Event("pointer_move"))
        assert calls == []

    def test_pause_handlers_intact_after_exit(self):
        reg = CallbackRegistry()
        calls = []
        reg.connect("pointer_move", lambda e: calls.append(1))
        with reg.pause_events("pointer_move"):
            reg.fire(Event("pointer_move"))
        reg.fire(Event("pointer_move"))
        assert calls == [1]

    def test_pause_all_types_when_no_args(self):
        reg = CallbackRegistry()
        calls = []
        reg.connect("pointer_down", lambda e: calls.append("down"))
        reg.connect("key_down",     lambda e: calls.append("key"))
        with reg.pause_events():
            reg.fire(Event("pointer_down"))
            reg.fire(Event("key_down"))
        assert calls == []

    def test_pause_only_specified_type(self):
        reg = CallbackRegistry()
        calls = []
        reg.connect("pointer_move", lambda e: calls.append("move"))
        reg.connect("pointer_down", lambda e: calls.append("down"))
        with reg.pause_events("pointer_move"):
            reg.fire(Event("pointer_move"))
            reg.fire(Event("pointer_down"))
        assert calls == ["down"]

    def test_pause_nested_same_type(self):
        reg = CallbackRegistry()
        calls = []
        reg.connect("pointer_move", lambda e: calls.append(1))
        with reg.pause_events("pointer_move"):
            with reg.pause_events("pointer_move"):
                reg.fire(Event("pointer_move"))
            reg.fire(Event("pointer_move"))  # still paused — outer not exited
        reg.fire(Event("pointer_move"))      # now fires
        assert calls == [1]

    def test_hold_buffers_and_flushes_on_exit(self):
        reg = CallbackRegistry()
        calls = []
        reg.connect("pointer_settled", lambda e: calls.append(1))
        with reg.hold_events("pointer_settled"):
            reg.fire(Event("pointer_settled"))
            reg.fire(Event("pointer_settled"))
            assert calls == []       # buffered, not fired yet
        assert calls == [1, 1]       # flushed on exit

    def test_hold_fires_non_held_types_immediately(self):
        reg = CallbackRegistry()
        move_calls = []
        settled_calls = []
        reg.connect("pointer_move",    lambda e: move_calls.append(1))
        reg.connect("pointer_settled", lambda e: settled_calls.append(1))
        with reg.hold_events("pointer_settled"):
            reg.fire(Event("pointer_move"))       # not held → immediate
            reg.fire(Event("pointer_settled"))    # held → buffered
        assert move_calls == [1]
        assert settled_calls == [1]   # flushed on exit

    def test_hold_events_in_order(self):
        reg = CallbackRegistry()
        calls = []
        reg.connect("pointer_settled", lambda e: calls.append(e.x))
        with reg.hold_events():
            reg.fire(Event("pointer_settled", x=1))
            reg.fire(Event("pointer_settled", x=2))
            reg.fire(Event("pointer_settled", x=3))
        assert calls == [1, 2, 3]

    def test_pause_wins_over_hold(self):
        reg = CallbackRegistry()
        calls = []
        reg.connect("pointer_move", lambda e: calls.append(1))
        with reg.hold_events("pointer_move"):
            with reg.pause_events("pointer_move"):
                reg.fire(Event("pointer_move"))
        assert calls == []   # dropped, not buffered then flushed
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
uv run pytest anyplotlib/tests/test_interactive/test_callbacks.py::TestPauseHold -v
```
Expected: FAIL — `pause_events`/`hold_events` not yet implemented.

- [ ] **Step 3: Append context managers to `CallbackRegistry` in `callbacks.py`**

Add these methods inside the `CallbackRegistry` class (after `_flush`):

```python
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
```

- [ ] **Step 4: Run tests**

```bash
uv run pytest anyplotlib/tests/test_interactive/test_callbacks.py::TestPauseHold -v
```
Expected: All 9 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add anyplotlib/callbacks.py anyplotlib/tests/test_interactive/test_callbacks.py
git commit -m "feat: add pause_events and hold_events context managers to CallbackRegistry"
```

---

## Task 4: Add `_EventMixin` to `callbacks.py`

The mixin provides `add_event_handler`, `remove_handler`, `pause_events`, `hold_events` for every plot and widget.

**Files:**
- Modify: `anyplotlib/callbacks.py` (append class)
- Modify: `anyplotlib/tests/test_interactive/test_callbacks.py`

- [ ] **Step 1: Write failing tests — append to test file**

```python
class _FakePlot(_EventMixin):
    """Minimal plot stub for testing _EventMixin."""
    def __init__(self):
        self.callbacks = CallbackRegistry()
        self._settled_config = (0, 0)

    def _configure_pointer_settled(self, ms: int, delta: float) -> None:
        self._settled_config = (ms, delta)


class TestEventMixin:
    def test_functional_form_single_type(self):
        plot = _FakePlot()
        calls = []
        fn = lambda e: calls.append(e.event_type)
        plot.add_event_handler(fn, "pointer_down")
        plot.callbacks.fire(Event("pointer_down"))
        assert calls == ["pointer_down"]

    def test_functional_form_multi_type(self):
        plot = _FakePlot()
        calls = []
        fn = lambda e: calls.append(e.event_type)
        plot.add_event_handler(fn, "pointer_down", "pointer_up")
        plot.callbacks.fire(Event("pointer_down"))
        plot.callbacks.fire(Event("pointer_up"))
        assert calls == ["pointer_down", "pointer_up"]

    def test_decorator_form_single_type(self):
        plot = _FakePlot()
        calls = []
        @plot.add_event_handler("pointer_move")
        def handler(e):
            calls.append(e.event_type)
        plot.callbacks.fire(Event("pointer_move"))
        assert calls == ["pointer_move"]

    def test_decorator_form_multi_type(self):
        plot = _FakePlot()
        calls = []
        @plot.add_event_handler("pointer_down", "key_down")
        def handler(e):
            calls.append(e.event_type)
        plot.callbacks.fire(Event("pointer_down"))
        plot.callbacks.fire(Event("key_down"))
        assert calls == ["pointer_down", "key_down"]

    def test_wildcard_decorator(self):
        plot = _FakePlot()
        calls = []
        @plot.add_event_handler("*")
        def handler(e):
            calls.append(e.event_type)
        plot.callbacks.fire(Event("pointer_down"))
        plot.callbacks.fire(Event("wheel"))
        assert calls == ["pointer_down", "wheel"]

    def test_remove_handler_by_fn(self):
        plot = _FakePlot()
        calls = []
        fn = lambda e: calls.append(1)
        plot.add_event_handler(fn, "pointer_down")
        plot.remove_handler(fn)
        plot.callbacks.fire(Event("pointer_down"))
        assert calls == []

    def test_remove_handler_by_fn_specific_type(self):
        plot = _FakePlot()
        calls = []
        fn = lambda e: calls.append(e.event_type)
        plot.add_event_handler(fn, "pointer_down", "pointer_up")
        plot.remove_handler(fn, "pointer_down")
        plot.callbacks.fire(Event("pointer_down"))
        plot.callbacks.fire(Event("pointer_up"))
        assert calls == ["pointer_up"]

    def test_remove_handler_by_cid(self):
        plot = _FakePlot()
        calls = []
        cid = plot.callbacks.connect("pointer_down", lambda e: calls.append(1))
        plot.remove_handler(cid)
        plot.callbacks.fire(Event("pointer_down"))
        assert calls == []

    def test_pointer_settled_configures_on_connect(self):
        plot = _FakePlot()
        plot.add_event_handler(lambda e: None, "pointer_settled", ms=400, delta=5)
        assert plot._settled_config == (400, 5)

    def test_pointer_settled_clears_on_last_disconnect(self):
        plot = _FakePlot()
        fn = lambda e: None
        plot.add_event_handler(fn, "pointer_settled", ms=400, delta=5)
        plot.remove_handler(fn)
        assert plot._settled_config == (0, 0)

    def test_ms_delta_without_settled_raises(self):
        plot = _FakePlot()
        with pytest.raises(ValueError, match="ms/delta"):
            plot.add_event_handler(lambda e: None, "pointer_down", ms=400)

    def test_pause_events_delegates_to_registry(self):
        plot = _FakePlot()
        calls = []
        plot.add_event_handler(lambda e: calls.append(1), "pointer_move")
        with plot.pause_events("pointer_move"):
            plot.callbacks.fire(Event("pointer_move"))
        assert calls == []

    def test_hold_events_delegates_to_registry(self):
        plot = _FakePlot()
        calls = []
        plot.add_event_handler(lambda e: calls.append(1), "pointer_settled")
        with plot.hold_events("pointer_settled"):
            plot.callbacks.fire(Event("pointer_settled"))
            assert calls == []
        assert calls == [1]
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
uv run pytest anyplotlib/tests/test_interactive/test_callbacks.py::TestEventMixin -v
```
Expected: FAIL — `_EventMixin` not yet defined.

- [ ] **Step 3: Append `_EventMixin` to `callbacks.py`**

```python
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
        if isinstance(cid_or_fn, int):
            self.callbacks.disconnect(cid_or_fn)
        else:
            self.callbacks.disconnect_fn(cid_or_fn, *types)
        if not self.callbacks._handlers.get("pointer_settled"):
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
```

Also add `_EventMixin` to the module's `__all__` export and update the top docstring.

- [ ] **Step 4: Run tests**

```bash
uv run pytest anyplotlib/tests/test_interactive/test_callbacks.py -v
```
Expected: All tests in all three test classes PASS.

- [ ] **Step 5: Commit**

```bash
git add anyplotlib/callbacks.py anyplotlib/tests/test_interactive/test_callbacks.py
git commit -m "feat: add _EventMixin with add_event_handler, remove_handler, pause/hold_events"
```

---

## Task 5: Update `_dispatch_event` in Figure and `Widget._update_from_js`

Map renamed JS fields (`phys_x`→`xdata`, `mouse_x`→`x`) to the flat `Event` constructor. Update widget sync.

**Files:**
- Modify: `anyplotlib/figure/_figure.py`
- Modify: `anyplotlib/widgets/_base.py`

- [ ] **Step 1: Add `import time` to `figure/_figure.py`**

Find the existing imports block (around line 1-10) and add:
```python
import time
```

- [ ] **Step 2: Replace `_dispatch_event` in `figure/_figure.py`**

Find the `_dispatch_event` method (currently lines ~343-397) and replace the body entirely:

```python
def _dispatch_event(self, raw: str) -> None:
    if not raw or raw == "{}":
        return
    try:
        msg = json.loads(raw)
    except Exception:
        return
    if msg.get("source") == "python":
        return

    panel_id   = msg.get("panel_id", "")
    event_type = msg.get("event_type", "pointer_move")
    widget_id  = msg.get("widget_id")

    # Inset state changes
    if event_type == "inset_state_change":
        inset_ax = self._insets_map.get(panel_id)
        if inset_ax is not None:
            new_state = msg.get("new_state", "normal")
            if new_state in ("normal", "minimized", "maximized"):
                inset_ax._inset_state = new_state
                self._push_layout()
        return

    plot = self._plots_map.get(panel_id)
    if plot is None:
        return

    source = None
    if widget_id and hasattr(plot, "_widgets"):
        widget = plot._widgets.get(widget_id)
        if widget is not None:
            widget._update_from_js(msg, event_type)
            source = widget

    if hasattr(plot, "callbacks"):
        event = Event(
            event_type=event_type,
            source=source,
            time_stamp=msg.get("time_stamp", time.perf_counter()),
            modifiers=msg.get("modifiers", []),
            x=msg.get("x"),
            y=msg.get("y"),
            button=msg.get("button"),
            buttons=msg.get("buttons", 0),
            xdata=msg.get("xdata"),
            ydata=msg.get("ydata"),
            ray=msg.get("ray"),
            line_id=msg.get("line_id"),
            dwell_ms=msg.get("dwell_ms"),
            bar_index=msg.get("bar_index"),
            value=msg.get("value"),
            x_label=msg.get("x_label"),
            group_index=msg.get("group_index"),
            dx=msg.get("dx"),
            dy=msg.get("dy"),
            key=msg.get("key"),
        )
        plot.callbacks.fire(event)
```

Also update the import at the top of `_figure.py` — find the `from anyplotlib.callbacks import ...` line and make sure `Event` is imported:
```python
from anyplotlib.callbacks import CallbackRegistry, Event
```

- [ ] **Step 3: Update `Widget._update_from_js` in `widgets/_base.py`**

Find `_update_from_js` (currently lines ~223-253) and replace:

```python
def _update_from_js(self, msg: dict, event_type: str = "pointer_move") -> bool:
    """Apply incoming JS state without pushing back (avoids echo).

    Updates widget ``_data`` with widget-specific state fields from JS,
    then fires widget callbacks with a flat Event.

    Parameters
    ----------
    msg : dict
        Full raw event message from JS.
    event_type : str
        One of the new pointer event types (``pointer_move``, ``pointer_up``,
        ``pointer_down``).

    Returns
    -------
    bool
        True if any widget state changed.
    """
    # Fields that belong to the event envelope, not widget state
    _envelope = {
        "source", "panel_id", "event_type", "widget_id",
        "time_stamp", "modifiers", "button", "buttons",
        "x", "y", "xdata", "ydata",
    }
    changed = False
    for k, v in msg.items():
        if k in ("id", "type") or k in _envelope:
            continue
        if self._data.get(k) != v:
            self._data[k] = v
            changed = True

    # Always fire on press/release; only fire pointer_move when state changed
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
```

Also update the `set` method (line ~97) which currently fires `Event("on_changed", ...)` directly:

```python
def set(self, _push: bool = True, **kwargs) -> None:
    self._data.update(kwargs)
    if _push:
        self._push_fn()
    # Fire pointer_move for programmatic updates
    self.callbacks.fire(Event("pointer_move", source=self))
```

- [ ] **Step 4: Run existing Python tests to check nothing broke**

```bash
uv run pytest anyplotlib/tests/ -v --ignore=anyplotlib/tests/test_interactive -x
```
Expected: All non-interactive tests PASS (they don't touch event dispatch).

- [ ] **Step 5: Commit**

```bash
git add anyplotlib/figure/_figure.py anyplotlib/widgets/_base.py
git commit -m "refactor: update _dispatch_event and Widget._update_from_js to use flat Event fields"
```

---

## Task 6: Update `Plot1D` and `Line1D`

Remove `on_changed`/`on_release`/`on_click`/`on_key`/`on_line_hover`/`on_line_click`/`disconnect`/`_connect_on_key`. Inherit `_EventMixin`. Update `Line1D` to expose `add_event_handler` with `line_id` filtering. Remove `registered_keys` from state.

**Files:**
- Modify: `anyplotlib/plot1d/_plot1d.py`

- [ ] **Step 1: Update imports in `plot1d/_plot1d.py`**

Find the imports block and update the callbacks import:
```python
from anyplotlib.callbacks import CallbackRegistry, _EventMixin
```

- [ ] **Step 2: Make `Plot1D` inherit `_EventMixin`**

Find the class definition line:
```python
class Plot1D:
```
Change to:
```python
class Plot1D(_EventMixin):
```

- [ ] **Step 3: Remove `registered_keys` from `_state` in `Plot1D.__init__`**

Find `"registered_keys": [],` in the `_state` dict initialisation and delete that line.

- [ ] **Step 4: Add `_configure_pointer_settled` to `Plot1D`**

After `self.callbacks = CallbackRegistry()` in `__init__`, add to the `_state` dict:
```python
"pointer_settled_ms":    0,
"pointer_settled_delta": 4,
```

Add this method to the `Plot1D` class:
```python
def _configure_pointer_settled(self, ms: int, delta: float) -> None:
    self._state["pointer_settled_ms"]    = ms
    self._state["pointer_settled_delta"] = delta
    self._push()
```

- [ ] **Step 5: Remove old event decorator methods from `Plot1D`**

Delete these methods entirely (find by name):
- `on_changed`
- `on_release`
- `on_click`
- `on_key`
- `_connect_on_key`
- `on_line_hover`
- `on_line_click`
- `disconnect`

- [ ] **Step 6: Update `Line1D` event methods**

Replace `Line1D.on_hover` and `Line1D.on_click` with a single `add_event_handler` that filters by `line_id`:

```python
def add_event_handler(self, fn_or_type, *args, **kwargs):
    """Register a handler scoped to this line only.

    Wraps the plot-level ``pointer_move`` / ``pointer_down`` handler
    with a ``line_id`` filter. Only ``pointer_move`` and ``pointer_down``
    are meaningful on a line handle.

    Usage::

        @line.add_event_handler("pointer_move")
        def on_hover(event):
            print(event.xdata, event.line_id)

        @line.add_event_handler("pointer_down")
        def on_pick(event):
            print("picked", event.line_id)
    """
    target_lid = self._lid

    if callable(fn_or_type):
        fn = fn_or_type
        types = args
        return self._wrap_and_register(fn, types, target_lid, **kwargs)
    else:
        all_types = (fn_or_type,) + args
        def _decorator(fn):
            return self._wrap_and_register(fn, all_types, target_lid, **kwargs)
        return _decorator

def _wrap_and_register(self, fn, types, target_lid, **kwargs):
    from functools import wraps
    @wraps(fn)
    def _filtered(event):
        if event.line_id == target_lid:
            fn(event)
    _filtered.__wrapped__ = fn
    return self._plot.add_event_handler(_filtered, *types, **kwargs)

def remove_handler(self, cid_or_fn, *types):
    """Remove a handler registered via this line handle."""
    self._plot.remove_handler(cid_or_fn, *types)
```

- [ ] **Step 7: Run tests**

```bash
uv run pytest anyplotlib/tests/test_interactive/test_callbacks.py anyplotlib/tests/test_plot1d/ -v
```
Expected: All PASS. If `test_callbacks.py` had tests that used old `on_click` decorator on plots, update those to use `add_event_handler`.

- [ ] **Step 8: Commit**

```bash
git add anyplotlib/plot1d/_plot1d.py
git commit -m "refactor: Plot1D and Line1D adopt _EventMixin, remove old on_* decorators and registered_keys"
```

---

## Task 7: Update `Plot2D` and `PlotMesh`

Same pattern as Task 6 — inherit `_EventMixin`, remove old decorators, add `_configure_pointer_settled`.

**Files:**
- Modify: `anyplotlib/plot2d/_plot2d.py`
- Modify: `anyplotlib/plot2d/_plotmesh.py`

- [ ] **Step 1: In `plot2d/_plot2d.py` — update import, inherit `_EventMixin`**

```python
from anyplotlib.callbacks import CallbackRegistry, _EventMixin
```
```python
class Plot2D(_EventMixin):
```

- [ ] **Step 2: Remove `registered_keys` from `_state`, add settled config keys**

Remove `"registered_keys": [],` from the `_state` dict.

Add to `_state`:
```python
"pointer_settled_ms":    0,
"pointer_settled_delta": 4,
```

- [ ] **Step 3: Add `_configure_pointer_settled` to `Plot2D`**

```python
def _configure_pointer_settled(self, ms: int, delta: float) -> None:
    self._state["pointer_settled_ms"]    = ms
    self._state["pointer_settled_delta"] = delta
    self._push()
```

- [ ] **Step 4: Remove old event methods from `Plot2D`**

Delete: `on_changed`, `on_release`, `on_click`, `on_key`, `_connect_on_key`, `disconnect`.

- [ ] **Step 5: Check `PlotMesh` — it inherits `Plot2D`**

Open `anyplotlib/plot2d/_plotmesh.py`. If `PlotMesh` also defines any of the removed methods directly, delete them. If it only inherits, no change is needed beyond checking the import line references nothing removed.

- [ ] **Step 6: Run tests**

```bash
uv run pytest anyplotlib/tests/test_plot2d/ -v
```
Expected: All PASS.

- [ ] **Step 7: Commit**

```bash
git add anyplotlib/plot2d/_plot2d.py anyplotlib/plot2d/_plotmesh.py
git commit -m "refactor: Plot2D and PlotMesh adopt _EventMixin, remove old on_* decorators"
```

---

## Task 8: Update `Plot3D`

Same pattern. Additionally, add `"ray": None` to the `_state` template since Plot3D pointer events carry a `ray` field instead of `xdata`/`ydata`.

**Files:**
- Modify: `anyplotlib/plot3d/_plot3d.py`

- [ ] **Step 1: Update import, inherit `_EventMixin`**

```python
from anyplotlib.callbacks import CallbackRegistry, _EventMixin
```
```python
class Plot3D(_EventMixin):
```

- [ ] **Step 2: Remove `registered_keys`, add settled config**

Remove `"registered_keys": [],` from `_state`.

Add:
```python
"pointer_settled_ms":    0,
"pointer_settled_delta": 4,
```

- [ ] **Step 3: Add `_configure_pointer_settled`**

```python
def _configure_pointer_settled(self, ms: int, delta: float) -> None:
    self._state["pointer_settled_ms"]    = ms
    self._state["pointer_settled_delta"] = delta
    self._push()
```

- [ ] **Step 4: Remove old event methods**

Delete: `on_changed`, `on_release`, `on_click`, `on_key`, `_connect_on_key`, `disconnect`.

- [ ] **Step 5: Run tests**

```bash
uv run pytest anyplotlib/tests/test_plot3d/ -v
```
Expected: All PASS.

- [ ] **Step 6: Commit**

```bash
git add anyplotlib/plot3d/_plot3d.py
git commit -m "refactor: Plot3D adopts _EventMixin, remove old on_* decorators"
```

---

## Task 9: Update `PlotBar`

Same pattern. The `pointer_down` event for PlotBar carries `bar_index`, `value`, `x_label`, `group_index` from the JS side — these are already handled by the flat `Event` constructor in `_dispatch_event`, so no extra Python work is needed beyond inheriting the mixin.

**Files:**
- Modify: `anyplotlib/plot1d/_plotbar.py`

- [ ] **Step 1: Update import, inherit `_EventMixin`**

```python
from anyplotlib.callbacks import CallbackRegistry, _EventMixin
```
```python
class PlotBar(_EventMixin):
```

- [ ] **Step 2: Remove `registered_keys`, add settled config**

Remove `"registered_keys": [],` from `_state`.

Add:
```python
"pointer_settled_ms":    0,
"pointer_settled_delta": 4,
```

- [ ] **Step 3: Add `_configure_pointer_settled`**

```python
def _configure_pointer_settled(self, ms: int, delta: float) -> None:
    self._state["pointer_settled_ms"]    = ms
    self._state["pointer_settled_delta"] = delta
    self._push()
```

- [ ] **Step 4: Remove old event methods**

Delete: `on_click`, `on_changed`, `on_release`, `on_key`, `_connect_on_key`, `disconnect`.

- [ ] **Step 5: Run tests**

```bash
uv run pytest anyplotlib/tests/test_plot1d/test_plotbar.py -v
```
Expected: All PASS.

- [ ] **Step 6: Commit**

```bash
git add anyplotlib/plot1d/_plotbar.py
git commit -m "refactor: PlotBar adopts _EventMixin, remove old on_* decorators"
```

---

## Task 10: Update `Widget` base class

Replace `on_changed`/`on_release`/`on_click`/`disconnect` with `_EventMixin`. The `_update_from_js` was already updated in Task 5.

**Files:**
- Modify: `anyplotlib/widgets/_base.py`

- [ ] **Step 1: Update import**

```python
from anyplotlib.callbacks import CallbackRegistry, Event, _EventMixin
```

- [ ] **Step 2: Inherit `_EventMixin`**

```python
class Widget(_EventMixin):
```

- [ ] **Step 3: Remove old decorator methods**

Delete: `on_changed`, `on_release`, `on_click`, `disconnect`.

The `callbacks` attribute is already set in `__init__` — `_EventMixin` will find it.

- [ ] **Step 4: Run tests**

```bash
uv run pytest anyplotlib/tests/test_interactive/ -v -k "widget"
```
Expected: All widget tests PASS.

- [ ] **Step 5: Run full Python test suite**

```bash
uv run pytest anyplotlib/tests/ -v --ignore=anyplotlib/tests/test_interactive/test_event_plots.py \
  --ignore=anyplotlib/tests/test_interactive/test_event_settled.py \
  --ignore=anyplotlib/tests/test_interactive/test_event_pause_hold.py
```
Expected: All PASS.

- [ ] **Step 6: Commit**

```bash
git add anyplotlib/widgets/_base.py
git commit -m "refactor: Widget adopts _EventMixin, remove old on_changed/on_release/on_click/disconnect"
```

---

## Task 11: JS — Forward new event types and fields

Add the six missing event types to `figure_esm.js` and add `modifiers`, `buttons`, `button`, `time_stamp` to all emitted events.

**Files:**
- Modify: `anyplotlib/figure_esm.js`

This file is ~4000 lines. Search for existing mouse/key event listeners to find the right locations.

- [ ] **Step 1: Find existing event emission sites**

```bash
grep -n "mousedown\|mouseup\|mousemove\|keydown\|keyup\|wheel\|dblclick\|mouseenter\|mouseleave\|event_json\|event_type" anyplotlib/figure_esm.js | head -40
```
Note the line numbers for: mouse event listeners, the function that sends events to Python, key event handling.

- [ ] **Step 2: Add a helper to extract common fields**

Find where JS sends events to Python (the function that writes to `event_json`). Add a helper function near the top of the event-handling section:

```javascript
function _pointerFields(e, panelId) {
  return {
    time_stamp: performance.now() / 1000,   // seconds, matching perf_counter()
    modifiers:  _modifiers(e),
    button:     e.button ?? null,
    buttons:    e.buttons ?? 0,
  };
}

function _modifiers(e) {
  const mods = [];
  if (e.ctrlKey)  mods.push("ctrl");
  if (e.shiftKey) mods.push("shift");
  if (e.altKey)   mods.push("alt");
  if (e.metaKey)  mods.push("meta");
  return mods;
}
```

- [ ] **Step 3: Rename outgoing `event_type` values**

Find all places the JS emits `event_type: "on_click"`, `"on_changed"`, `"on_release"`, `"on_key"`, `"on_line_hover"`, `"on_line_click"` and replace:

| Old JS `event_type` | New JS `event_type` |
|---------------------|---------------------|
| `"on_click"` | `"pointer_down"` |
| `"on_changed"` | `"pointer_move"` |
| `"on_release"` | `"pointer_settled"` |
| `"on_key"` | `"key_down"` |
| `"on_line_hover"` | `"pointer_move"` (with `line_id` field already set) |
| `"on_line_click"` | `"pointer_down"` (with `line_id` field already set) |
| `"on_inset_state_change"` | `"inset_state_change"` |

- [ ] **Step 4: Rename outgoing payload field names**

In all JS event payloads, rename:
- `phys_x` → `xdata`
- `phys_y` → `ydata`
- `mouse_x` → `x`
- `mouse_y` → `y`

```bash
grep -n "phys_x\|phys_y\|mouse_x\|mouse_y" anyplotlib/figure_esm.js
```
Replace every occurrence.

- [ ] **Step 5: Add `_pointerFields` to every emitted pointer event**

For every place the JS calls the send-to-Python function with a pointer event, spread `_pointerFields(e, panelId)` into the payload:

```javascript
// Before (example):
sendEvent({ event_type: "pointer_down", panel_id: panelId, x: px, y: py });

// After:
sendEvent({ event_type: "pointer_down", panel_id: panelId,
            ..._pointerFields(e, panelId), x: px, y: py });
```

- [ ] **Step 6: Add listener for `pointer_up` (mouseup)**

Find the `mousedown` listener and add a `mouseup` listener alongside it:

```javascript
canvas.addEventListener("mouseup", (e) => {
  sendEvent({
    event_type: "pointer_up",
    panel_id:   panelId,
    ..._pointerFields(e, panelId),
    x: /* pixel x relative to canvas */,
    y: /* pixel y relative to canvas */,
    xdata: /* data coord x or null */,
    ydata: /* data coord y or null */,
  });
});
```

- [ ] **Step 7: Add `pointer_enter` / `pointer_leave` listeners**

```javascript
canvas.addEventListener("mouseenter", (e) => {
  sendEvent({ event_type: "pointer_enter", panel_id: panelId,
              ..._pointerFields(e, panelId), x: /*px*/, y: /*py*/ });
});
canvas.addEventListener("mouseleave", (e) => {
  sendEvent({ event_type: "pointer_leave", panel_id: panelId,
              ..._pointerFields(e, panelId), x: /*px*/, y: /*py*/ });
});
```

Note: `button` is `null` on enter/leave events (no button triggered the event). `buttons` reflects currently-held buttons.

- [ ] **Step 8: Add `double_click` listener**

```javascript
canvas.addEventListener("dblclick", (e) => {
  sendEvent({ event_type: "double_click", panel_id: panelId,
              ..._pointerFields(e, panelId), x: /*px*/, y: /*py*/,
              xdata: /*or null*/, ydata: /*or null*/ });
});
```

- [ ] **Step 9: Add `wheel` listener**

```javascript
canvas.addEventListener("wheel", (e) => {
  e.preventDefault();
  sendEvent({ event_type: "wheel", panel_id: panelId,
              time_stamp: performance.now() / 1000,
              modifiers: _modifiers(e),
              x: /*px*/, y: /*py*/,
              dx: e.deltaX, dy: e.deltaY });
}, { passive: false });
```

- [ ] **Step 10: Add `key_up` listener**

Find the existing `keydown` listener and add `keyup` alongside:

```javascript
document.addEventListener("keyup", (e) => {
  if (!panelFocused) return;
  sendEvent({ event_type: "key_up", panel_id: panelId,
              time_stamp: performance.now() / 1000,
              modifiers: _modifiers(e),
              key: e.key, x: lastPointerX, y: lastPointerY });
});
```

- [ ] **Step 11: Remove `registered_keys` filtering from JS**

Find the section that checks `registered_keys` before forwarding key events (something like `if (state.registered_keys.includes(e.key) || ...)`). Remove this guard — forward all key events unconditionally.

- [ ] **Step 12: Run the full pure-Python test suite to confirm no regressions**

```bash
uv run pytest anyplotlib/tests/ -v -k "not test_event_plots and not test_event_settled and not test_event_pause_hold"
```
Expected: All PASS.

- [ ] **Step 13: Commit**

```bash
git add anyplotlib/figure_esm.js
git commit -m "feat: JS forwards pointer_up, pointer_enter/leave, double_click, wheel, key_up; rename event fields to xdata/ydata/x/y; add modifiers/button/buttons/time_stamp"
```

---

## Task 12: JS — `pointer_settled` dwell timer

Add a per-panel dwell timer that fires `pointer_settled` after the pointer holds still for the configured ms/delta thresholds.

**Files:**
- Modify: `anyplotlib/figure_esm.js`

- [ ] **Step 1: Add timer state per panel**

Near the per-panel state initialisation, add:

```javascript
let _settledTimer   = null;
let _settledStartX  = 0;
let _settledStartY  = 0;
let _settledStartTs = 0;
```

- [ ] **Step 2: Add `pointer_settled` trigger inside the `pointer_move` handler**

Inside the `mousemove` / `pointer_move` emission block, after emitting `pointer_move`, add:

```javascript
// pointer_settled dwell timer
const settledMs    = panelState.pointer_settled_ms    ?? 0;
const settledDelta = panelState.pointer_settled_delta ?? 4;
if (settledMs > 0) {
  clearTimeout(_settledTimer);
  const nowX  = currentPixelX;
  const nowY  = currentPixelY;
  const nowTs = performance.now();
  _settledStartX  = nowX;
  _settledStartY  = nowY;
  _settledStartTs = nowTs;
  _settledTimer = setTimeout(() => {
    const dist = Math.hypot(currentPixelX - _settledStartX,
                            currentPixelY - _settledStartY);
    if (dist <= settledDelta) {
      const dwellMs = performance.now() - _settledStartTs;
      sendEvent({
        event_type: "pointer_settled",
        panel_id:   panelId,
        time_stamp: performance.now() / 1000,
        modifiers:  lastModifiers,
        buttons:    lastButtons,
        button:     null,
        x:          currentPixelX,
        y:          currentPixelY,
        xdata:      currentDataX ?? null,
        ydata:      currentDataY ?? null,
        dwell_ms:   dwellMs,
      });
    }
  }, settledMs);
}
```

Where `currentPixelX`, `currentPixelY`, `currentDataX`, `currentDataY`, `lastModifiers`, `lastButtons` are variables already tracked by the mousemove handler.

- [ ] **Step 3: Cancel timer on `mouseup` and `mouseleave`**

Inside the `mouseup` and `mouseleave` handlers, add:
```javascript
clearTimeout(_settledTimer);
_settledTimer = null;
```

- [ ] **Step 4: Commit**

```bash
git add anyplotlib/figure_esm.js
git commit -m "feat: add pointer_settled dwell timer to JS with zero cost when unused"
```

---

## Task 13: Playwright tests — pointer events per plot type

**Files:**
- Create: `anyplotlib/tests/test_interactive/test_event_plots.py`

- [ ] **Step 1: Create the test file**

```python
"""
Playwright tests for pointer/key events across all plot types.
Each plot type gets: pointer_down, pointer_up, pointer_move, pointer_enter,
pointer_leave, double_click, wheel, key_down, key_up, modifiers.
"""
from __future__ import annotations
import json
import numpy as np
import pytest
import anyplotlib as apl


# ── helpers ──────────────────────────────────────────────────────────────────

def _collect(page, fig, event_type):
    """Return a list of event dicts received for event_type."""
    page.evaluate(f"""
        window._evts_{event_type} = [];
        window._aplModel.on("{event_type}", (e) => {{
            window._evts_{event_type}.push(e);
        }});
    """)
    return page.evaluate(f"window._evts_{event_type}")


def _plot1d_fig():
    fig, ax = apl.subplots(1, 1, figsize=(400, 300))
    ax.plot(np.zeros(100))
    return fig


def _plot2d_fig():
    fig, ax = apl.subplots(1, 1, figsize=(400, 400))
    ax.imshow(np.zeros((64, 64)))
    return fig


def _plot3d_fig():
    x = np.linspace(-2, 2, 20)
    y = np.linspace(-2, 2, 20)
    XX, YY = np.meshgrid(x, y)
    fig, ax = apl.subplots(1, 1, figsize=(400, 400))
    ax.plot_surface(XX, YY, np.zeros_like(XX))
    return fig


def _plotbar_fig():
    fig, ax = apl.subplots(1, 1, figsize=(400, 300))
    ax.bar(["A", "B", "C"], [1.0, 2.0, 3.0])
    return fig


# ── pointer_down ─────────────────────────────────────────────────────────────

class TestPointerDown:
    def test_plot1d_pointer_down_fields(self, interact_page):
        fig = _plot1d_fig()
        page = interact_page(fig)
        received = []
        page.expose_function("_on_pd", lambda e: received.append(json.loads(e)))
        page.evaluate("""
          window._aplModel && window._aplModel.on &&
          window._aplModel.on("pointer_down", e => window._on_pd(JSON.stringify(e)))
        """)
        page.mouse.click(200, 150)
        page.wait_for_timeout(200)
        assert len(received) >= 1
        e = received[0]
        assert e["event_type"] == "pointer_down"
        assert isinstance(e["x"], (int, float))
        assert isinstance(e["y"], (int, float))
        assert e["button"] == 0
        assert e["buttons"] == 0    # buttons=0 after release
        assert isinstance(e["modifiers"], list)
        assert isinstance(e["time_stamp"], (int, float))

    def test_plot2d_pointer_down_has_xdata_ydata(self, interact_page):
        fig = _plot2d_fig()
        page = interact_page(fig)
        received = []
        page.expose_function("_on_pd2", lambda e: received.append(json.loads(e)))
        page.evaluate(
            "window._aplModel.on('pointer_down', e => window._on_pd2(JSON.stringify(e)))"
        )
        page.mouse.click(200, 200)
        page.wait_for_timeout(200)
        assert len(received) >= 1
        e = received[0]
        assert e.get("xdata") is not None
        assert e.get("ydata") is not None

    def test_plot3d_pointer_down_no_xdata(self, interact_page):
        fig = _plot3d_fig()
        page = interact_page(fig)
        received = []
        page.expose_function("_on_pd3", lambda e: received.append(json.loads(e)))
        page.evaluate(
            "window._aplModel.on('pointer_down', e => window._on_pd3(JSON.stringify(e)))"
        )
        page.mouse.click(200, 200)
        page.wait_for_timeout(200)
        assert len(received) >= 1
        e = received[0]
        assert e.get("xdata") is None
        assert e.get("ydata") is None

    def test_ctrl_click_modifiers(self, interact_page):
        fig = _plot1d_fig()
        page = interact_page(fig)
        received = []
        page.expose_function("_on_ctrl", lambda e: received.append(json.loads(e)))
        page.evaluate(
            "window._aplModel.on('pointer_down', e => window._on_ctrl(JSON.stringify(e)))"
        )
        page.keyboard.down("Control")
        page.mouse.click(200, 150)
        page.keyboard.up("Control")
        page.wait_for_timeout(200)
        assert any("ctrl" in e.get("modifiers", []) for e in received)


# ── pointer_up ────────────────────────────────────────────────────────────────

class TestPointerUp:
    def test_fires_after_drag(self, interact_page):
        fig = _plot1d_fig()
        page = interact_page(fig)
        received = []
        page.expose_function("_on_pu", lambda e: received.append(json.loads(e)))
        page.evaluate(
            "window._aplModel.on('pointer_up', e => window._on_pu(JSON.stringify(e)))"
        )
        page.mouse.move(200, 150)
        page.mouse.down()
        page.mouse.move(150, 150, steps=5)
        page.mouse.up()
        page.wait_for_timeout(200)
        assert len(received) >= 1
        e = received[-1]
        assert e["event_type"] == "pointer_up"
        assert e["button"] == 0


# ── pointer_move ──────────────────────────────────────────────────────────────

class TestPointerMove:
    def test_fires_during_drag(self, interact_page):
        fig = _plot1d_fig()
        page = interact_page(fig)
        received = []
        page.expose_function("_on_pm", lambda e: received.append(json.loads(e)))
        page.evaluate(
            "window._aplModel.on('pointer_move', e => window._on_pm(JSON.stringify(e)))"
        )
        page.mouse.move(200, 150)
        page.mouse.down()
        page.mouse.move(100, 150, steps=10)
        page.mouse.up()
        page.wait_for_timeout(300)
        assert len(received) >= 5     # multiple frames during drag


# ── pointer_enter / pointer_leave ─────────────────────────────────────────────

class TestPointerEnterLeave:
    def test_enter_fires_on_mouse_enter(self, interact_page):
        fig = _plot1d_fig()
        page = interact_page(fig)
        received = []
        page.expose_function("_on_pe", lambda e: received.append(json.loads(e)))
        page.evaluate(
            "window._aplModel.on('pointer_enter', e => window._on_pe(JSON.stringify(e)))"
        )
        # Move from outside the widget to inside
        page.mouse.move(0, 0)
        page.mouse.move(200, 150)
        page.wait_for_timeout(200)
        assert len(received) >= 1
        assert received[0]["event_type"] == "pointer_enter"
        assert received[0].get("button") is None   # button is None on enter
        assert isinstance(received[0]["buttons"], int)

    def test_leave_fires_on_mouse_leave(self, interact_page):
        fig = _plot1d_fig()
        page = interact_page(fig)
        received = []
        page.expose_function("_on_pl", lambda e: received.append(json.loads(e)))
        page.evaluate(
            "window._aplModel.on('pointer_leave', e => window._on_pl(JSON.stringify(e)))"
        )
        page.mouse.move(200, 150)
        page.mouse.move(0, 0)
        page.wait_for_timeout(200)
        assert len(received) >= 1
        assert received[0]["event_type"] == "pointer_leave"


# ── double_click ──────────────────────────────────────────────────────────────

class TestDoubleClick:
    def test_fires_on_dblclick(self, interact_page):
        fig = _plot1d_fig()
        page = interact_page(fig)
        received = []
        page.expose_function("_on_dc", lambda e: received.append(json.loads(e)))
        page.evaluate(
            "window._aplModel.on('double_click', e => window._on_dc(JSON.stringify(e)))"
        )
        page.mouse.dblclick(200, 150)
        page.wait_for_timeout(200)
        assert len(received) >= 1
        assert received[0]["event_type"] == "double_click"
        assert received[0]["button"] == 0


# ── wheel ─────────────────────────────────────────────────────────────────────

class TestWheel:
    def test_fires_on_scroll(self, interact_page):
        fig = _plot2d_fig()
        page = interact_page(fig)
        received = []
        page.expose_function("_on_wh", lambda e: received.append(json.loads(e)))
        page.evaluate(
            "window._aplModel.on('wheel', e => window._on_wh(JSON.stringify(e)))"
        )
        page.mouse.move(200, 200)
        page.mouse.wheel(0, 100)
        page.wait_for_timeout(200)
        assert len(received) >= 1
        e = received[0]
        assert e["event_type"] == "wheel"
        assert e.get("dy") is not None


# ── key_down / key_up ─────────────────────────────────────────────────────────

class TestKeyEvents:
    def test_key_down_fires_any_key(self, interact_page):
        fig = _plot1d_fig()
        page = interact_page(fig)
        received = []
        page.expose_function("_on_kd", lambda e: received.append(json.loads(e)))
        page.evaluate(
            "window._aplModel.on('key_down', e => window._on_kd(JSON.stringify(e)))"
        )
        page.mouse.move(200, 150)  # focus the panel
        page.keyboard.press("r")
        page.wait_for_timeout(200)
        assert any(e["key"] == "r" for e in received)

    def test_key_up_fires(self, interact_page):
        fig = _plot1d_fig()
        page = interact_page(fig)
        received = []
        page.expose_function("_on_ku", lambda e: received.append(json.loads(e)))
        page.evaluate(
            "window._aplModel.on('key_up', e => window._on_ku(JSON.stringify(e)))"
        )
        page.mouse.move(200, 150)
        page.keyboard.down("q")
        page.keyboard.up("q")
        page.wait_for_timeout(200)
        assert any(e["key"] == "q" for e in received)
```

- [ ] **Step 2: Run the new tests**

```bash
uv run pytest anyplotlib/tests/test_interactive/test_event_plots.py -v
```
Expected: All PASS. Fix any failures by adjusting pixel coordinates or widget locators to match your actual panel layout.

- [ ] **Step 3: Commit**

```bash
git add anyplotlib/tests/test_interactive/test_event_plots.py
git commit -m "test: add Playwright tests for pointer_down/up/move, enter/leave, double_click, wheel, key_down/up"
```

---

## Task 14: Playwright tests — `pointer_settled`

**Files:**
- Create: `anyplotlib/tests/test_interactive/test_event_settled.py`

- [ ] **Step 1: Create the test file**

```python
"""Tests for pointer_settled dwell timer — JS computes, Python receives."""
from __future__ import annotations
import json
import numpy as np
import pytest
import anyplotlib as apl
from anyplotlib.callbacks import Event


# ── Python-side: _configure_pointer_settled ───────────────────────────────────

class TestSettledConfig:
    def test_state_set_on_first_connect(self):
        fig, ax = apl.subplots(1, 1)
        plot = ax.imshow(np.zeros((32, 32)))
        assert plot._state["pointer_settled_ms"]    == 0
        assert plot._state["pointer_settled_delta"] == 4

        plot.add_event_handler(lambda e: None, "pointer_settled", ms=400, delta=5)
        assert plot._state["pointer_settled_ms"]    == 400
        assert plot._state["pointer_settled_delta"] == 5

    def test_state_cleared_on_last_disconnect(self):
        fig, ax = apl.subplots(1, 1)
        plot = ax.imshow(np.zeros((32, 32)))
        fn = lambda e: None
        plot.add_event_handler(fn, "pointer_settled", ms=400, delta=5)
        plot.remove_handler(fn)
        assert plot._state["pointer_settled_ms"]    == 0

    def test_two_handlers_keep_last_config(self):
        fig, ax = apl.subplots(1, 1)
        plot = ax.imshow(np.zeros((32, 32)))
        fn1 = lambda e: None
        fn2 = lambda e: None
        plot.add_event_handler(fn1, "pointer_settled", ms=200, delta=3)
        plot.add_event_handler(fn2, "pointer_settled", ms=800, delta=6)
        # Last connect wins — ms=800, delta=6
        assert plot._state["pointer_settled_ms"]    == 800
        assert plot._state["pointer_settled_delta"] == 6
        # Remove fn2 — config clears only when NO handlers remain
        plot.remove_handler(fn2)
        # fn1 still connected → ms stays at 800 (fn1's config is remembered by registry)
        assert plot._state["pointer_settled_ms"] > 0


# ── Playwright: dwell timer ───────────────────────────────────────────────────

class TestSettledPlaywright:
    def test_fires_after_hold(self, interact_page):
        fig, ax = apl.subplots(1, 1, figsize=(400, 300))
        plot = ax.imshow(np.zeros((64, 64)))
        # Configure a short dwell (200ms) for fast tests
        plot.add_event_handler(lambda e: None, "pointer_settled", ms=200, delta=4)

        page = interact_page(fig)
        received = []
        page.expose_function("_on_st", lambda e: received.append(json.loads(e)))
        page.evaluate(
            "window._aplModel.on('pointer_settled', e => window._on_st(JSON.stringify(e)))"
        )

        # Move into panel and hold still
        page.mouse.move(200, 150)
        page.wait_for_timeout(400)     # well past the 200ms threshold

        assert len(received) >= 1
        e = received[0]
        assert e["event_type"] == "pointer_settled"
        assert e["dwell_ms"] >= 200

    def test_does_not_fire_if_moving(self, interact_page):
        fig, ax = apl.subplots(1, 1, figsize=(400, 300))
        plot = ax.imshow(np.zeros((64, 64)))
        plot.add_event_handler(lambda e: None, "pointer_settled", ms=300, delta=4)

        page = interact_page(fig)
        received = []
        page.expose_function("_on_st2", lambda e: received.append(json.loads(e)))
        page.evaluate(
            "window._aplModel.on('pointer_settled', e => window._on_st2(JSON.stringify(e)))"
        )

        # Keep moving — should never settle
        page.mouse.move(100, 150)
        page.mouse.move(150, 150, steps=5)
        page.mouse.move(200, 150, steps=5)
        page.mouse.move(250, 150, steps=5)
        page.wait_for_timeout(100)

        assert received == []

    def test_no_timer_when_no_handler_connected(self, interact_page):
        fig, ax = apl.subplots(1, 1, figsize=(400, 300))
        plot = ax.imshow(np.zeros((64, 64)))
        # No pointer_settled handler connected — pointer_settled_ms stays 0

        page = interact_page(fig)
        # Confirm JS state has no timer configured
        settled_ms = page.evaluate(
            f"JSON.parse(window._aplModel.get('panel_{plot._id}_json')).pointer_settled_ms"
        )
        assert settled_ms == 0

    def test_fires_again_after_re_settle(self, interact_page):
        fig, ax = apl.subplots(1, 1, figsize=(400, 300))
        plot = ax.imshow(np.zeros((64, 64)))
        plot.add_event_handler(lambda e: None, "pointer_settled", ms=200, delta=4)

        page = interact_page(fig)
        received = []
        page.expose_function("_on_st3", lambda e: received.append(json.loads(e)))
        page.evaluate(
            "window._aplModel.on('pointer_settled', e => window._on_st3(JSON.stringify(e)))"
        )

        # First settle
        page.mouse.move(200, 150)
        page.wait_for_timeout(350)

        # Move and settle again
        page.mouse.move(100, 150, steps=3)
        page.wait_for_timeout(350)

        assert len(received) >= 2    # fired twice
```

- [ ] **Step 2: Run tests**

```bash
uv run pytest anyplotlib/tests/test_interactive/test_event_settled.py -v
```
Expected: All PASS.

- [ ] **Step 3: Commit**

```bash
git add anyplotlib/tests/test_interactive/test_event_settled.py
git commit -m "test: add pointer_settled Playwright tests including zero-cost guard"
```

---

## Task 15: Playwright tests — pause/hold integration

**Files:**
- Create: `anyplotlib/tests/test_interactive/test_event_pause_hold.py`

- [ ] **Step 1: Create the test file**

```python
"""Integration tests for pause_events / hold_events during live interactions."""
from __future__ import annotations
import json
import numpy as np
import pytest
import anyplotlib as apl


class TestPauseIntegration:
    def test_pause_drops_pointer_move_during_drag(self, interact_page):
        fig, ax = apl.subplots(1, 1, figsize=(400, 300))
        plot = ax.imshow(np.zeros((64, 64)))
        received = []
        plot.add_event_handler(lambda e: received.append(1), "pointer_move")

        page = interact_page(fig)

        # Pause then trigger drag — moves should not reach handler
        page.evaluate("window._aplPaused = true")  # hook into test infra below
        with plot.pause_events("pointer_move"):
            page.mouse.move(200, 150)
            page.mouse.down()
            page.mouse.move(100, 150, steps=5)
            page.mouse.up()
            page.wait_for_timeout(200)

        assert received == []

        # After context exits, moves should fire again
        page.mouse.move(200, 150)
        page.mouse.down()
        page.mouse.move(150, 150, steps=3)
        page.mouse.up()
        page.wait_for_timeout(200)
        assert len(received) > 0


class TestHoldIntegration:
    def test_hold_buffers_settled_fires_on_exit(self, interact_page):
        fig, ax = apl.subplots(1, 1, figsize=(400, 300))
        plot = ax.imshow(np.zeros((64, 64)))
        plot.add_event_handler(lambda e: None, "pointer_settled", ms=150, delta=4)
        received = []
        plot.add_event_handler(lambda e: received.append(1), "pointer_settled")

        page = interact_page(fig)

        with plot.hold_events("pointer_settled"):
            page.mouse.move(200, 150)
            page.wait_for_timeout(300)     # settled fires → buffered
            assert received == []

        # hold context exited → flushed
        assert received == [1]

    def test_hold_fires_pointer_move_immediately(self, interact_page):
        fig, ax = apl.subplots(1, 1, figsize=(400, 300))
        plot = ax.imshow(np.zeros((64, 64)))
        moves = []
        settles = []
        plot.add_event_handler(lambda e: moves.append(1),   "pointer_move")
        plot.add_event_handler(lambda e: None,               "pointer_settled", ms=150, delta=4)
        plot.add_event_handler(lambda e: settles.append(1), "pointer_settled")

        page = interact_page(fig)

        with plot.hold_events("pointer_settled"):
            page.mouse.move(200, 150)
            page.mouse.down()
            page.mouse.move(100, 150, steps=5)
            page.mouse.up()
            page.wait_for_timeout(300)

        assert len(moves) > 0      # pointer_move not held → fired immediately
        assert len(settles) == 1   # flushed on exit
```

- [ ] **Step 2: Run tests**

```bash
uv run pytest anyplotlib/tests/test_interactive/test_event_pause_hold.py -v
```
Expected: All PASS.

- [ ] **Step 3: Commit**

```bash
git add anyplotlib/tests/test_interactive/test_event_pause_hold.py
git commit -m "test: add pause_events and hold_events Playwright integration tests"
```

---

## Task 16: Update Examples and regression tests

**Files:**
- Modify: All `Examples/**/*.py` files that use old event API
- Modify: `anyplotlib/tests/test_interactive/test_callbacks.py` (add regression block)

- [ ] **Step 1: Find all example files using old event API**

```bash
grep -rn "on_click\|on_changed\|on_release\|on_key\|on_hover\|\.disconnect(" Examples/ --include="*.py"
```

- [ ] **Step 2: Update each file**

For each file found, replace old API calls:

| Old | New |
|-----|-----|
| `@plot.on_click` | `@plot.add_event_handler("pointer_down")` |
| `@plot.on_changed` | `@plot.add_event_handler("pointer_move")` |
| `@plot.on_release` | `@plot.add_event_handler("pointer_settled")` |
| `@plot.on_key` | `@plot.add_event_handler("key_down")` |
| `@plot.on_key('q')` | `@plot.add_event_handler("key_down")` + `if event.key == "q": return` |
| `@widget.on_changed` | `@widget.add_event_handler("pointer_move")` |
| `@widget.on_release` | `@widget.add_event_handler("pointer_up")` |
| `@widget.on_click` | `@widget.add_event_handler("pointer_down")` |
| `@line.on_hover` | `@line.add_event_handler("pointer_move")` |
| `@line.on_click` | `@line.add_event_handler("pointer_down")` |
| `plot.disconnect(cid)` | `plot.remove_handler(cid)` |
| `event.phys_x` | `event.xdata` |
| `event.phys_y` | `event.ydata` |
| `event.mouse_x` | `event.x` |
| `event.mouse_y` | `event.y` |

- [ ] **Step 3: Add regression tests to `test_callbacks.py`**

Append to `anyplotlib/tests/test_interactive/test_callbacks.py`:

```python
class TestRegressionOldAPIGone:
    """Confirm old decorator methods no longer exist on plots and widgets."""

    def test_plot1d_no_on_click(self):
        fig, ax = apl.subplots(1, 1)
        plot = ax.plot(np.zeros(10))
        assert not hasattr(plot, "on_click")

    def test_plot1d_no_on_changed(self):
        fig, ax = apl.subplots(1, 1)
        plot = ax.plot(np.zeros(10))
        assert not hasattr(plot, "on_changed")

    def test_plot1d_no_on_release(self):
        fig, ax = apl.subplots(1, 1)
        plot = ax.plot(np.zeros(10))
        assert not hasattr(plot, "on_release")

    def test_plot1d_no_on_key(self):
        fig, ax = apl.subplots(1, 1)
        plot = ax.plot(np.zeros(10))
        assert not hasattr(plot, "on_key")

    def test_plot1d_no_disconnect(self):
        fig, ax = apl.subplots(1, 1)
        plot = ax.plot(np.zeros(10))
        assert not hasattr(plot, "disconnect")

    def test_plot2d_no_on_click(self):
        fig, ax = apl.subplots(1, 1)
        plot = ax.imshow(np.zeros((32, 32)))
        assert not hasattr(plot, "on_click")

    def test_widget_no_on_changed(self):
        fig, ax = apl.subplots(1, 1)
        plot = ax.plot(np.zeros(10))
        w = plot.add_vline_widget(5.0)
        assert not hasattr(w, "on_changed")

    def test_widget_no_on_release(self):
        fig, ax = apl.subplots(1, 1)
        plot = ax.plot(np.zeros(10))
        w = plot.add_vline_widget(5.0)
        assert not hasattr(w, "on_release")

    def test_event_no_phys_x(self):
        e = Event(event_type="pointer_down", xdata=3.14)
        assert not hasattr(e, "phys_x")
        assert e.xdata == 3.14

    def test_event_no_data_dict(self):
        e = Event(event_type="pointer_move")
        assert not hasattr(e, "data")
```

- [ ] **Step 4: Run the full test suite**

```bash
uv run pytest anyplotlib/tests/ -v
```
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add Examples/ anyplotlib/tests/test_interactive/test_callbacks.py
git commit -m "refactor: update Examples to new event API; add regression tests confirming old API removed"
```

---

## Verification

After all tasks complete, run the full suite once more:

```bash
uv run pytest anyplotlib/tests/ -v --tb=short 2>&1 | tail -20
```

Expected output ends with something like:
```
========== NNN passed in XX.Xs ==========
```

with zero failures or errors.

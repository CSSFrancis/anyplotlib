"""
tests/test_interactive/test_event_pause_hold.py
================================================

Tests for ``pause_events`` and ``hold_events`` Python-side context managers.

``pause_events`` and ``hold_events`` operate on the ``CallbackRegistry``
after events have been dispatched to Python.  The Figure's ``_dispatch_event``
method is the entry point: it builds an ``Event`` and calls
``plot.callbacks.fire()``.  When paused, ``fire()`` drops the event; when
held, ``fire()`` buffers it and flushes on context exit.

In the standalone Playwright setup there is no real Python kernel — the model
is a JS-only shim.  Python handlers are therefore not reachable from the
browser.  These tests drive the Python dispatch path directly via
``fig._dispatch_event(json_str)`` to verify pause/hold semantics end-to-end,
with a Playwright test verifying JS actually sends the expected events.
"""
from __future__ import annotations

import json

import numpy as np
import pytest

import anyplotlib as apl

# ── coordinate constants ──────────────────────────────────────────────────────
PAD_L, PAD_R, PAD_T, PAD_B = 58, 12, 12, 42
GRID_PAD = 8
FIG_W, FIG_H = 400, 300


def _plot_center_page() -> tuple[int, int]:
    cx = PAD_L + (FIG_W - PAD_L - PAD_R) // 2
    cy = PAD_T + (FIG_H - PAD_T - PAD_B) // 2
    return cx + GRID_PAD, cy + GRID_PAD


def _sim(fig, plot, event_type: str, **fields) -> None:
    """Simulate a JS event by calling fig._dispatch_event directly."""
    payload = {"source": "js", "panel_id": plot._id, "event_type": event_type}
    payload.update(fields)
    fig._dispatch_event(json.dumps(payload))


def _collect_events(page) -> None:
    page.evaluate("""() => {
        window._aplAllEvents = [];
        const orig = window._aplModel.set.bind(window._aplModel);
        window._aplModel.set = (k, v) => {
            if (k === 'event_json') {
                try { window._aplAllEvents.push(JSON.parse(v)); } catch(_) {}
            }
            return orig(k, v);
        };
    }""")


def _get_events(page, event_type: str | None = None) -> list:
    events = page.evaluate("() => window._aplAllEvents")
    if event_type:
        return [e for e in events if e.get("event_type") == event_type]
    return events


# ═══════════════════════════════════════════════════════════════════════════════
# 1. pause_events — Python-side dispatch simulation
# ═══════════════════════════════════════════════════════════════════════════════

class TestPauseIntegration:
    def test_pause_drops_pointer_move(self):
        """pause_events suppresses Python handler calls for pointer_move."""
        fig, ax = apl.subplots(1, 1, figsize=(FIG_W, FIG_H))
        plot = ax.imshow(np.zeros((64, 64)))
        received = []
        plot.add_event_handler(lambda e: received.append(1), "pointer_move")

        with plot.pause_events("pointer_move"):
            _sim(fig, plot, "pointer_move", x=100, y=100)
            _sim(fig, plot, "pointer_move", x=110, y=100)

        assert received == [], (
            f"pause_events should drop all pointer_move calls; got {len(received)}"
        )

    def test_events_resume_after_pause_exits(self):
        """pointer_move handler fires again after pause_events context exits."""
        fig, ax = apl.subplots(1, 1, figsize=(FIG_W, FIG_H))
        plot = ax.imshow(np.zeros((64, 64)))
        received = []
        plot.add_event_handler(lambda e: received.append(1), "pointer_move")

        with plot.pause_events("pointer_move"):
            _sim(fig, plot, "pointer_move", x=100, y=100)

        assert received == [], "No events during pause"

        # After context exits, moves fire again
        _sim(fig, plot, "pointer_move", x=120, y=100)
        assert len(received) == 1, (
            "pointer_move should fire after pause_events context exits"
        )

    def test_pause_only_specified_type(self):
        """pause_events('pointer_move') does not suppress pointer_down."""
        fig, ax = apl.subplots(1, 1, figsize=(FIG_W, FIG_H))
        plot = ax.imshow(np.zeros((64, 64)))
        move_calls = []
        down_calls = []
        plot.add_event_handler(lambda e: move_calls.append(1), "pointer_move")
        plot.add_event_handler(lambda e: down_calls.append(1), "pointer_down")

        with plot.pause_events("pointer_move"):
            _sim(fig, plot, "pointer_move", x=100, y=100)
            _sim(fig, plot, "pointer_down", x=100, y=100)

        assert move_calls == [], "pointer_move should be paused"
        assert len(down_calls) == 1, "pointer_down should not be paused"


# ═══════════════════════════════════════════════════════════════════════════════
# 2. hold_events — buffers and flushes on exit
# ═══════════════════════════════════════════════════════════════════════════════

class TestHoldIntegration:
    def test_hold_buffers_pointer_settled_and_flushes_on_exit(self):
        """pointer_settled is buffered during hold and flushed on context exit."""
        fig, ax = apl.subplots(1, 1, figsize=(FIG_W, FIG_H))
        plot = ax.imshow(np.zeros((32, 32)))
        received = []
        plot.add_event_handler(
            lambda e: received.append(e),
            "pointer_settled",
            ms=200,
            delta=4,
        )

        with plot.hold_events("pointer_settled"):
            _sim(fig, plot, "pointer_settled", x=100, y=100, dwell_ms=250.0)
            _sim(fig, plot, "pointer_settled", x=101, y=100, dwell_ms=260.0)
            assert received == [], "Handler should not be called while holding"

        assert len(received) == 2, (
            f"Both buffered events should flush on context exit; got {len(received)}"
        )

    def test_hold_is_type_specific(self):
        """hold_events('pointer_settled') does not delay pointer_move."""
        fig, ax = apl.subplots(1, 1, figsize=(FIG_W, FIG_H))
        plot = ax.imshow(np.zeros((32, 32)))

        move_received = []
        settled_received = []
        plot.add_event_handler(
            lambda e: move_received.append(1), "pointer_move"
        )
        plot.add_event_handler(
            lambda e: settled_received.append(1),
            "pointer_settled",
            ms=200,
            delta=4,
        )

        with plot.hold_events("pointer_settled"):
            _sim(fig, plot, "pointer_move", x=100, y=100)
            _sim(fig, plot, "pointer_settled", x=100, y=100, dwell_ms=250.0)

            # pointer_move fires immediately
            assert len(move_received) == 1, (
                "pointer_move should not be held when only pointer_settled is held"
            )
            # pointer_settled is still buffered
            assert settled_received == [], (
                "pointer_settled should not have fired yet (still inside hold)"
            )

        # On exit, buffered pointer_settled is flushed
        assert len(settled_received) == 1, (
            "pointer_settled should flush on context exit"
        )

    def test_hold_flush_preserves_event_order(self):
        """Buffered events are flushed in the order they were received."""
        fig, ax = apl.subplots(1, 1, figsize=(FIG_W, FIG_H))
        plot = ax.imshow(np.zeros((32, 32)))
        order = []
        plot.add_event_handler(
            lambda e: order.append(e.x),
            "pointer_settled",
            ms=200,
        )

        with plot.hold_events("pointer_settled"):
            for xval in (10, 20, 30):
                _sim(fig, plot, "pointer_settled", x=xval, y=100, dwell_ms=210.0)

        assert order == [10, 20, 30], (
            f"Events should flush in order; got {order}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Playwright smoke test — JS sends pointer_move during drag on 3D panel
# ═══════════════════════════════════════════════════════════════════════════════

class TestPlaywrightJSSends:
    """Verify JS actually emits pointer_move events that could be paused/held.

    This confirms the JS side of the pipeline is working; the pause/hold
    semantics are tested purely in Python (above) since the standalone shim
    has no real Python kernel.
    """

    def test_3d_drag_sends_pointer_move_events(self, interact_page):
        """A drag on a 3D panel emits multiple pointer_move event_json payloads."""
        fig, ax = apl.subplots(1, 1, figsize=(FIG_W, FIG_H))
        x = np.linspace(-1, 1, 8)
        X, Y = np.meshgrid(x, x)
        Z = X ** 2 + Y ** 2
        plot = ax.plot_surface(X, Y, Z)

        page = interact_page(fig)
        _collect_events(page)

        cx = FIG_W // 2 + GRID_PAD
        cy = FIG_H // 2 + GRID_PAD
        page.mouse.move(cx, cy)
        page.mouse.down()
        page.mouse.move(cx + 40, cy, steps=6)
        page.mouse.up()
        page.wait_for_timeout(100)

        events = _get_events(page, "pointer_move")
        assert len(events) > 0, (
            "JS should emit pointer_move events during a 3D drag; "
            "these are what pause_events/hold_events would intercept in Python"
        )

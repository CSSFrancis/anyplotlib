"""
tests/test_interactive/test_callbacks_playwright.py
====================================================

Playwright integration tests for the callback system.

Each test exercises the full JS → Python dispatch pipeline:
  1. ``interact_page(fig)`` opens the standalone HTML in headless Chromium.
  2. ``_collect_events(page)`` intercepts every ``event_json`` write on the
     JS model shim so we can verify the browser emitted the right payload.
  3. ``page.mouse.*`` / ``page.keyboard.*`` fires real browser events.
  4. ``_sim(fig, plot, event_type, ...)`` replays the same payload through
     ``fig._dispatch_event`` to verify the Python handler receives it.

Because the standalone HTML has no live Python kernel, steps 3 and 4 are
independent but complementary: step 3 confirms JS sends the event; step 4
confirms Python processes it.

Coordinate system (mirrors figure_esm.js constants)
----------------------------------------------------
  PAD_L=58  PAD_R=12  PAD_T=12  PAD_B=42  GRID_PAD=8
  400×300 figure → plot area page-coords: x≈66, y≈20, w≈330, h≈246
"""
from __future__ import annotations

import json

import numpy as np
import pytest

import anyplotlib as apl
from anyplotlib.tests.test_interactive._event_test_utils import (
    _collect_events,
    _get_events,
    _plot_center_page,
    GRID_PAD,
    PAD_L, PAD_R, PAD_T, PAD_B,
)

FIG_W, FIG_H = 400, 300


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _sim(fig, plot, event_type: str, **fields) -> None:
    """Drive the Python dispatch path directly (no browser needed)."""
    payload = {"source": "js", "panel_id": plot._id, "event_type": event_type}
    payload.update(fields)
    fig._dispatch_event(json.dumps(payload))


def _make_1d(interact_page):
    fig, ax = apl.subplots(1, 1, figsize=(FIG_W, FIG_H))
    plot = ax.plot(np.sin(np.linspace(0, 6.28, 128)))
    page = interact_page(fig)
    _collect_events(page)
    return fig, plot, page


def _make_2d(interact_page):
    fig, ax = apl.subplots(1, 1, figsize=(FIG_W, FIG_H))
    plot = ax.imshow(np.zeros((32, 32), dtype=np.float32))
    page = interact_page(fig)
    _collect_events(page)
    return fig, plot, page


def _center():
    return _plot_center_page(FIG_W, FIG_H)


def _plot_left_edge():
    """Page x-coordinate of the left edge of the plot area."""
    return GRID_PAD + PAD_L + 5


def _plot_top_edge():
    """Page y-coordinate of the top edge of the plot area."""
    return GRID_PAD + PAD_T + 5


def _outside_plot():
    """Page coords clearly outside the plot area (title bar region)."""
    return GRID_PAD + 10, GRID_PAD + 5


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Event types — JS emission verified with Playwright
# ═══════════════════════════════════════════════════════════════════════════════

class TestEventTypesJsEmission:
    """Verify each event type is emitted by the JS engine on real interactions."""

    def test_pointer_down_emitted(self, interact_page):
        _, _, page = _make_2d(interact_page)
        cx, cy = _center()
        page.mouse.move(cx, cy)
        page.mouse.down()
        page.wait_for_timeout(80)
        page.mouse.up()
        events = _get_events(page, "pointer_down")
        assert len(events) >= 1, "pointer_down should be emitted on click"

    def test_pointer_up_emitted(self, interact_page):
        # pointer_up fires on significant drag release (not a plain click).
        _, _, page = _make_2d(interact_page)
        cx, cy = _center()
        page.mouse.move(cx, cy)
        page.mouse.down()
        page.mouse.move(cx + 50, cy, steps=10)
        page.mouse.up()
        page.wait_for_timeout(100)
        events = _get_events(page, "pointer_up")
        assert len(events) >= 1, "pointer_up should be emitted after a drag release"

    def test_pointer_move_emitted(self, interact_page):
        # pointer_move fires on every mousemove over a 3D panel.
        fig, ax = apl.subplots(1, 1, figsize=(FIG_W, FIG_H))
        x = np.linspace(-1, 1, 8)
        X, Y = np.meshgrid(x, x)
        plot = ax.plot_surface(X, Y, X ** 2 + Y ** 2)
        page = interact_page(fig)
        _collect_events(page)
        cx, cy = _center()
        page.mouse.move(cx, cy)
        page.mouse.down()
        page.mouse.move(cx + 30, cy, steps=8)
        page.mouse.up()
        page.wait_for_timeout(50)
        events = _get_events(page, "pointer_move")
        assert len(events) > 0, "pointer_move events should fire during 3D drag"

    def test_double_click_emitted(self, interact_page):
        _, _, page = _make_2d(interact_page)
        cx, cy = _center()
        page.mouse.dblclick(cx, cy)
        page.wait_for_timeout(100)
        events = _get_events(page, "double_click")
        assert len(events) >= 1, "double_click should be emitted on dblclick"

    def test_wheel_emitted(self, interact_page):
        _, _, page = _make_2d(interact_page)
        cx, cy = _center()
        page.mouse.move(cx, cy)
        page.mouse.wheel(0, -100)
        page.wait_for_timeout(80)
        events = _get_events(page, "wheel")
        assert len(events) >= 1, "wheel event should be emitted on scroll"

    def test_key_down_emitted(self, interact_page):
        _, _, page = _make_2d(interact_page)
        cx, cy = _center()
        page.mouse.move(cx, cy)
        page.mouse.down()
        page.mouse.up()
        page.wait_for_timeout(50)
        page.keyboard.press("r")
        page.wait_for_timeout(80)
        events = _get_events(page, "key_down")
        assert len(events) >= 1, "key_down should be emitted on key press"

    def test_pointer_enter_emitted(self, interact_page):
        _, _, page = _make_2d(interact_page)
        ox, oy = _outside_plot()
        px = _plot_left_edge()
        py = _plot_top_edge()
        page.mouse.move(ox, oy)
        page.wait_for_timeout(30)
        page.mouse.move(px, py, steps=5)
        page.wait_for_timeout(80)
        events = _get_events(page, "pointer_enter")
        assert len(events) >= 1, "pointer_enter should fire when mouse enters plot area"

    def test_pointer_leave_emitted(self, interact_page):
        _, _, page = _make_2d(interact_page)
        cx, cy = _center()
        page.mouse.move(cx, cy)
        page.wait_for_timeout(30)
        ox, oy = _outside_plot()
        page.mouse.move(ox, oy, steps=5)
        page.wait_for_timeout(80)
        events = _get_events(page, "pointer_leave")
        assert len(events) >= 1, "pointer_leave should fire when mouse exits plot area"

    def test_pointer_down_has_required_fields(self, interact_page):
        _, _, page = _make_2d(interact_page)
        cx, cy = _center()
        page.mouse.click(cx, cy)
        page.wait_for_timeout(100)
        events = _get_events(page, "pointer_down")
        assert events, "No pointer_down events collected"
        e = events[0]
        for field in ("event_type", "x", "y", "button", "buttons", "modifiers"):
            assert field in e, f"pointer_down missing field {field!r}"

    def test_pointer_down_has_xdata_ydata(self, interact_page):
        _, _, page = _make_2d(interact_page)
        cx, cy = _center()
        page.mouse.click(cx, cy)
        page.wait_for_timeout(100)
        events = _get_events(page, "pointer_down")
        assert events
        e = events[0]
        assert "xdata" in e and "ydata" in e, "2D pointer_down should carry xdata/ydata"

    def test_wheel_has_dx_dy_fields(self, interact_page):
        _, _, page = _make_2d(interact_page)
        cx, cy = _center()
        page.mouse.move(cx, cy)
        page.mouse.wheel(0, -120)
        page.wait_for_timeout(80)
        events = _get_events(page, "wheel")
        assert events
        e = events[0]
        assert "dy" in e or "dx" in e, "wheel event should carry dx or dy"


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Python dispatch — via _sim + real Python handlers
# ═══════════════════════════════════════════════════════════════════════════════

class TestPythonDispatch:
    """Verify Python callback machinery processes dispatched events correctly."""

    def test_pointer_down_calls_handler(self, interact_page):
        fig, plot, page = _make_2d(interact_page)
        received = []
        plot.add_event_handler(lambda e: received.append(e.event_type), "pointer_down")
        _sim(fig, plot, "pointer_down", x=200, y=150, xdata=16.0, ydata=16.0)
        assert received == ["pointer_down"]

    def test_pointer_move_calls_handler(self, interact_page):
        fig, plot, page = _make_2d(interact_page)
        received = []
        plot.add_event_handler(lambda e: received.append(e.xdata), "pointer_move")
        _sim(fig, plot, "pointer_move", x=200, y=150, xdata=8.0, ydata=8.0)
        assert received == [8.0]

    def test_double_click_calls_handler(self, interact_page):
        fig, plot, page = _make_2d(interact_page)
        received = []
        plot.add_event_handler(lambda e: received.append(True), "double_click")
        _sim(fig, plot, "double_click", x=200, y=150)
        assert received == [True]

    def test_wheel_calls_handler(self, interact_page):
        fig, plot, page = _make_2d(interact_page)
        received = []
        plot.add_event_handler(lambda e: received.append(e.dy), "wheel")
        _sim(fig, plot, "wheel", dx=0.0, dy=-1.0)
        assert received == [-1.0]

    def test_key_down_calls_handler(self, interact_page):
        fig, plot, page = _make_2d(interact_page)
        received = []
        plot.add_event_handler(lambda e: received.append(e.key), "key_down")
        _sim(fig, plot, "key_down", key="r")
        assert received == ["r"]

    def test_wildcard_handler_receives_all_event_types(self, interact_page):
        fig, plot, page = _make_2d(interact_page)
        received = []
        plot.add_event_handler(lambda e: received.append(e.event_type), "*")
        for etype in ("pointer_down", "pointer_up", "pointer_move", "wheel"):
            _sim(fig, plot, etype, x=100, y=100)
        assert received == ["pointer_down", "pointer_up", "pointer_move", "wheel"]

    def test_priority_order_respected(self, interact_page):
        fig, plot, page = _make_2d(interact_page)
        order = []
        plot.add_event_handler(
            lambda e: order.append("low"), "pointer_down", order=1
        )
        plot.add_event_handler(
            lambda e: order.append("high"), "pointer_down", order=0
        )
        _sim(fig, plot, "pointer_down", x=100, y=100)
        assert order == ["high", "low"]

    def test_stop_propagation_halts_chain(self, interact_page):
        fig, plot, page = _make_2d(interact_page)
        called = []

        def first(e):
            called.append("first")
            e.stop_propagation = True

        plot.add_event_handler(first, "pointer_down", order=0)
        plot.add_event_handler(lambda e: called.append("second"), "pointer_down", order=1)
        _sim(fig, plot, "pointer_down", x=100, y=100)
        assert called == ["first"]

    def test_disconnect_stops_delivery(self, interact_page):
        fig, plot, page = _make_2d(interact_page)
        received = []
        fn = lambda e: received.append(1)
        plot.add_event_handler(fn, "pointer_down")
        plot.remove_handler(fn)
        _sim(fig, plot, "pointer_down", x=100, y=100)
        assert received == []


# ═══════════════════════════════════════════════════════════════════════════════
# 3. pause_events — JS emission + Python dispatch combined
# ═══════════════════════════════════════════════════════════════════════════════

class TestPauseEventsPlaywright:
    """pause_events drops events in the Python callback layer."""

    def test_pause_suppresses_pointer_move_handler(self, interact_page):
        """JS fires pointer_move; Python handler does not receive it while paused."""
        fig, plot, page = _make_2d(interact_page)
        received = []
        plot.add_event_handler(lambda e: received.append(1), "pointer_move")

        with plot.pause_events("pointer_move"):
            cx, cy = _center()
            page.mouse.move(cx, cy)
            page.mouse.move(cx + 20, cy, steps=5)
            page.wait_for_timeout(50)
            # JS events are sent to model; Python dispatch is paused
            _sim(fig, plot, "pointer_move", x=200, y=150)
            _sim(fig, plot, "pointer_move", x=210, y=150)

        assert received == [], (
            "pause_events should prevent handler from firing during the context"
        )

    def test_pause_allows_other_types_through(self, interact_page):
        fig, plot, page = _make_2d(interact_page)
        move_received = []
        down_received = []
        plot.add_event_handler(lambda e: move_received.append(1), "pointer_move")
        plot.add_event_handler(lambda e: down_received.append(1), "pointer_down")

        with plot.pause_events("pointer_move"):
            _sim(fig, plot, "pointer_move", x=100, y=100)
            _sim(fig, plot, "pointer_down", x=100, y=100)

        assert move_received == []
        assert down_received == [1]

    def test_events_resume_after_pause_context(self, interact_page):
        fig, plot, page = _make_2d(interact_page)
        received = []
        plot.add_event_handler(lambda e: received.append(1), "pointer_move")

        with plot.pause_events("pointer_move"):
            _sim(fig, plot, "pointer_move", x=100, y=100)

        _sim(fig, plot, "pointer_move", x=110, y=100)
        assert received == [1], "Handler should fire after pause context exits"

    def test_js_still_emits_events_during_pause(self, interact_page):
        """The browser still emits events during Python pause — only dispatch is suppressed.

        Uses a 3D panel because pointer_move fires on every mousemove there.
        """
        fig, ax = apl.subplots(1, 1, figsize=(FIG_W, FIG_H))
        x = np.linspace(-1, 1, 8)
        X, Y = np.meshgrid(x, x)
        plot = ax.plot_surface(X, Y, X ** 2 + Y ** 2)
        page = interact_page(fig)
        _collect_events(page)

        with plot.pause_events("pointer_move"):
            cx, cy = _center()
            page.mouse.move(cx, cy)
            page.mouse.down()
            page.mouse.move(cx + 40, cy, steps=8)
            page.mouse.up()
            page.wait_for_timeout(50)

        js_events = _get_events(page, "pointer_move")
        assert len(js_events) > 0, (
            "JS should still emit pointer_move even while Python pause is active"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# 4. hold_events — buffers and flushes on context exit
# ═══════════════════════════════════════════════════════════════════════════════

class TestHoldEventsPlaywright:
    """hold_events buffers Python callbacks and flushes them on context exit."""

    def test_hold_buffers_during_context(self, interact_page):
        fig, plot, page = _make_2d(interact_page)
        received = []
        plot.add_event_handler(
            lambda e: received.append(e.dwell_ms),
            "pointer_settled",
            ms=50,
            delta=2,
        )

        with plot.hold_events("pointer_settled"):
            _sim(fig, plot, "pointer_settled", x=200, y=150, dwell_ms=100.0)
            _sim(fig, plot, "pointer_settled", x=205, y=150, dwell_ms=110.0)
            assert received == [], "Buffered events should not fire inside hold context"

        assert len(received) == 2, "Both buffered events should flush on exit"

    def test_hold_flush_preserves_order(self, interact_page):
        fig, plot, page = _make_2d(interact_page)
        order = []
        plot.add_event_handler(
            lambda e: order.append(e.x),
            "pointer_settled",
            ms=50,
        )

        with plot.hold_events("pointer_settled"):
            for x in (10, 20, 30, 40):
                _sim(fig, plot, "pointer_settled", x=x, y=100, dwell_ms=60.0)

        assert order == [10, 20, 30, 40]

    def test_hold_non_held_type_fires_immediately(self, interact_page):
        fig, plot, page = _make_2d(interact_page)
        move_calls = []
        settled_calls = []
        plot.add_event_handler(lambda e: move_calls.append(1), "pointer_move")
        plot.add_event_handler(
            lambda e: settled_calls.append(1), "pointer_settled", ms=50
        )

        with plot.hold_events("pointer_settled"):
            _sim(fig, plot, "pointer_move", x=100, y=100)
            _sim(fig, plot, "pointer_settled", x=100, y=100, dwell_ms=60.0)
            assert move_calls == [1], "pointer_move not held — should fire immediately"
            assert settled_calls == [], "pointer_settled should still be buffered"

        assert settled_calls == [1]

    def test_pause_inside_hold_drops_not_buffers(self, interact_page):
        """An event that matches both hold and pause: pause wins, event is dropped."""
        fig, plot, page = _make_2d(interact_page)
        received = []
        plot.add_event_handler(lambda e: received.append(1), "pointer_move")

        with plot.hold_events("pointer_move"):
            with plot.pause_events("pointer_move"):
                _sim(fig, plot, "pointer_move", x=100, y=100)

        assert received == [], "pause inside hold should drop the event entirely"


# ═══════════════════════════════════════════════════════════════════════════════
# 5. pointer_settled — real dwell detection via Playwright
# ═══════════════════════════════════════════════════════════════════════════════

class TestPointerSettledPlaywright:
    def test_pointer_settled_fires_after_dwell(self, interact_page):
        """After the mouse stops moving, pointer_settled is emitted by JS.

        The handler must be registered BEFORE interact_page() so the settled
        dwell config (ms/delta) is baked into the serialised state that the
        standalone HTML page loads.
        """
        fig, ax = apl.subplots(1, 1, figsize=(FIG_W, FIG_H))
        plot = ax.imshow(np.zeros((32, 32), dtype=np.float32))
        plot.add_event_handler(lambda e: None, "pointer_settled", ms=100, delta=2)
        page = interact_page(fig)
        _collect_events(page)

        cx, cy = _center()
        page.mouse.move(cx, cy)
        page.wait_for_timeout(400)

        events = _get_events(page, "pointer_settled")
        assert len(events) >= 1, "pointer_settled should fire after dwell timeout"

    def test_pointer_settled_not_fired_on_rapid_movement(self, interact_page):
        """Continuous rapid movement suppresses pointer_settled."""
        fig, plot, page = _make_2d(interact_page)
        plot.add_event_handler(lambda e: None, "pointer_settled", ms=300, delta=2)

        cx, cy = _center()
        for _ in range(8):
            page.mouse.move(cx, cy)
            page.mouse.move(cx + 60, cy, steps=4)
            page.mouse.move(cx, cy, steps=4)
        page.wait_for_timeout(100)

        events = _get_events(page, "pointer_settled")
        assert len(events) == 0, (
            "pointer_settled should not fire during continuous rapid movement"
        )

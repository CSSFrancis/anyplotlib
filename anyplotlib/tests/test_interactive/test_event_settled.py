"""
tests/test_interactive/test_event_settled.py
============================================

Pure-Python unit tests and Playwright integration tests for the
``pointer_settled`` event.

Pure-Python tests verify that connecting / disconnecting a handler updates
the ``pointer_settled_ms`` / ``pointer_settled_delta`` state fields.

Playwright tests verify that the JS dwell timer fires after the configured
dwell period and suppresses when the pointer keeps moving.
"""
from __future__ import annotations

import json
import time

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


def _panel_state(page, plot) -> dict:
    raw = page.evaluate(
        f"() => window._aplModel.get('panel_{plot._id}_json')"
    )
    return json.loads(raw)


# ═══════════════════════════════════════════════════════════════════════════════
# Pure-Python: state field updates on connect / disconnect
# ═══════════════════════════════════════════════════════════════════════════════

class TestSettledConfig:
    def test_default_state_before_any_handler(self):
        """pointer_settled_ms starts at 0 and delta at 4 before any handler."""
        fig, ax = apl.subplots(1, 1)
        plot = ax.imshow(np.zeros((32, 32)))
        assert plot._state["pointer_settled_ms"] == 0
        assert plot._state["pointer_settled_delta"] == 4

    def test_state_set_on_first_connect(self):
        """Connecting a pointer_settled handler sets ms and delta in _state."""
        fig, ax = apl.subplots(1, 1)
        plot = ax.imshow(np.zeros((32, 32)))
        plot.add_event_handler(lambda e: None, "pointer_settled", ms=400, delta=5)
        assert plot._state["pointer_settled_ms"] == 400
        assert plot._state["pointer_settled_delta"] == 5

    def test_state_cleared_on_last_disconnect(self):
        """Removing the last pointer_settled handler resets ms to 0."""
        fig, ax = apl.subplots(1, 1)
        plot = ax.imshow(np.zeros((32, 32)))
        fn = lambda e: None
        plot.add_event_handler(fn, "pointer_settled", ms=400, delta=5)
        plot.remove_handler(fn)
        assert plot._state["pointer_settled_ms"] == 0

    def test_multiple_handlers_use_last_configured_ms(self):
        """Adding a second handler overrides ms/delta with the new values."""
        fig, ax = apl.subplots(1, 1)
        plot = ax.imshow(np.zeros((32, 32)))
        fn1 = lambda e: None
        fn2 = lambda e: None
        plot.add_event_handler(fn1, "pointer_settled", ms=300, delta=4)
        plot.add_event_handler(fn2, "pointer_settled", ms=500, delta=8)
        assert plot._state["pointer_settled_ms"] == 500
        assert plot._state["pointer_settled_delta"] == 8

    def test_remove_one_handler_keeps_nonzero_ms(self):
        """Removing one handler when another remains keeps ms non-zero."""
        fig, ax = apl.subplots(1, 1)
        plot = ax.imshow(np.zeros((32, 32)))
        fn1 = lambda e: None
        fn2 = lambda e: None
        plot.add_event_handler(fn1, "pointer_settled", ms=400)
        plot.add_event_handler(fn2, "pointer_settled", ms=400)
        plot.remove_handler(fn1)
        # fn2 is still connected — ms must remain non-zero
        assert plot._state["pointer_settled_ms"] > 0


# ═══════════════════════════════════════════════════════════════════════════════
# Playwright: dwell timer fires / suppresses correctly
# ═══════════════════════════════════════════════════════════════════════════════

class TestSettledPlaywright:
    def _make_page(self, interact_page, ms: int = 200, delta: int = 4):
        """Create a 2D imshow with a pointer_settled handler at ms=200."""
        fig, ax = apl.subplots(1, 1, figsize=(FIG_W, FIG_H))
        plot = ax.imshow(np.zeros((32, 32)))
        received = []
        plot.add_event_handler(
            lambda e: received.append(e),
            "pointer_settled",
            ms=ms,
            delta=delta,
        )
        page = interact_page(fig)
        _collect_events(page)
        return page, plot, received

    def test_no_timer_when_no_handler(self, interact_page):
        """pointer_settled_ms stays 0 in JS when no handler is connected."""
        fig, ax = apl.subplots(1, 1, figsize=(FIG_W, FIG_H))
        plot = ax.imshow(np.zeros((32, 32)))
        # No handler — do NOT call add_event_handler
        page = interact_page(fig)

        ms_val = page.evaluate(
            f"() => JSON.parse(window._aplModel.get('panel_{plot._id}_json')).pointer_settled_ms"
        )
        assert ms_val == 0, (
            f"pointer_settled_ms should be 0 when no handler connected, got {ms_val}"
        )

    def test_fires_after_hold(self, interact_page):
        """pointer_settled fires after the pointer holds still for >= ms."""
        page, plot, received = self._make_page(interact_page, ms=200)
        px, py = _plot_center_page()

        # Confirm JS sees the configured ms
        ms_in_js = page.evaluate(
            f"() => JSON.parse(window._aplModel.get('panel_{plot._id}_json')).pointer_settled_ms"
        )
        assert ms_in_js == 200, f"JS pointer_settled_ms should be 200, got {ms_in_js}"

        # Move into panel and hold still for 350 ms (well past 200 ms threshold)
        page.mouse.move(px, py)
        page.wait_for_timeout(350)

        events = _get_events(page, "pointer_settled")
        assert len(events) >= 1, (
            "pointer_settled should fire after holding still for >= 200 ms"
        )
        e = events[0]
        assert "dwell_ms" in e, "pointer_settled must include dwell_ms"
        assert e["dwell_ms"] >= 200, (
            f"dwell_ms should be >= 200, got {e['dwell_ms']:.1f}"
        )

    def test_does_not_fire_if_moving(self, interact_page):
        """pointer_settled does not fire if the pointer keeps moving."""
        page, plot, received = self._make_page(interact_page, ms=300)
        px, py = _plot_center_page()

        # Keep moving for 250 ms (less than 300 ms threshold)
        page.mouse.move(px, py)
        for _ in range(8):
            px += 5
            page.mouse.move(px, py)
            page.wait_for_timeout(30)

        events = _get_events(page, "pointer_settled")
        assert len(events) == 0, (
            "pointer_settled should not fire while the pointer is still moving"
        )

    def test_fires_again_after_re_settle(self, interact_page):
        """pointer_settled fires a second time after a second dwell period."""
        page, plot, received = self._make_page(interact_page, ms=200)
        px, py = _plot_center_page()

        # First dwell
        page.mouse.move(px, py)
        page.wait_for_timeout(300)

        first_count = len(_get_events(page, "pointer_settled"))
        assert first_count >= 1, "First pointer_settled should have fired"

        # Move away to reset the timer, then hold again
        page.mouse.move(px + 30, py + 30)
        page.wait_for_timeout(50)
        page.mouse.move(px, py)
        page.wait_for_timeout(300)

        second_count = len(_get_events(page, "pointer_settled"))
        assert second_count >= 2, (
            f"Expected at least 2 pointer_settled events, got {second_count}"
        )

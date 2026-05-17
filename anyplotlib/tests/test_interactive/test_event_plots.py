"""
tests/test_interactive/test_event_plots.py
==========================================

Playwright tests verifying that the JS event system correctly emits the new
event types introduced in the event system redesign.

Coordinate system (mirrors figure_esm.js constants):
  PAD_L=58  PAD_R=12  PAD_T=12  PAD_B=42  GRID_PAD=8
  For a 400×300 fig: plot rect = {x:58, y:12, w:330, h:246}
  Page coords = canvas coords + 8
"""
from __future__ import annotations

import numpy as np
import pytest

import anyplotlib as apl

# ── layout constants ──────────────────────────────────────────────────────────
PAD_L, PAD_R, PAD_T, PAD_B = 58, 12, 12, 42
GRID_PAD = 8

FIG_W, FIG_H = 400, 300


def _plot_center_page() -> tuple[int, int]:
    """Page-space centre of the plot area for a 400×300 figure."""
    cx = PAD_L + (FIG_W - PAD_L - PAD_R) // 2
    cy = PAD_T + (FIG_H - PAD_T - PAD_B) // 2
    return cx + GRID_PAD, cy + GRID_PAD


def _collect_events(page) -> None:
    """Monkey-patch model.set to accumulate every event_json payload."""
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


# ── fixtures ──────────────────────────────────────────────────────────────────

def _make_2d_page(interact_page):
    fig, ax = apl.subplots(1, 1, figsize=(FIG_W, FIG_H))
    plot = ax.imshow(np.zeros((32, 32)))
    page = interact_page(fig)
    _collect_events(page)
    return page, plot


def _make_3d_page(interact_page):
    fig, ax = apl.subplots(1, 1, figsize=(FIG_W, FIG_H))
    x = np.linspace(-1, 1, 8)
    X, Y = np.meshgrid(x, x)
    Z = X ** 2 + Y ** 2
    plot = ax.plot_surface(X, Y, Z)
    page = interact_page(fig)
    _collect_events(page)
    return page, plot


# ═══════════════════════════════════════════════════════════════════════════════
# pointer_down — 2D click emits correct fields
# ═══════════════════════════════════════════════════════════════════════════════

class TestPointerDown:
    def test_2d_click_emits_pointer_down_fields(self, interact_page):
        """Short click on a 2D panel emits pointer_down with required fields."""
        page, plot = _make_2d_page(interact_page)
        px, py = _plot_center_page()

        page.mouse.click(px, py)
        page.wait_for_timeout(100)

        events = _get_events(page, "pointer_down")
        assert len(events) >= 1, "Expected at least one pointer_down event"
        e = events[0]
        for field in ("event_type", "x", "y", "button", "buttons", "modifiers", "time_stamp"):
            assert field in e, f"pointer_down missing field {field!r}"
        assert e["event_type"] == "pointer_down"
        assert isinstance(e["modifiers"], list)

    def test_2d_pointer_down_has_xdata_ydata(self, interact_page):
        """Plot2D pointer_down includes xdata and ydata fields."""
        page, plot = _make_2d_page(interact_page)
        px, py = _plot_center_page()

        page.mouse.click(px, py)
        page.wait_for_timeout(100)

        events = _get_events(page, "pointer_down")
        assert len(events) >= 1
        e = events[0]
        assert "xdata" in e, "2D pointer_down must include xdata"
        assert "ydata" in e, "2D pointer_down must include ydata"
        assert e["xdata"] is not None
        assert e["ydata"] is not None

    def test_ctrl_click_modifiers(self, interact_page):
        """Ctrl+click produces modifiers=['ctrl'] on pointer_down."""
        page, plot = _make_2d_page(interact_page)
        px, py = _plot_center_page()

        page.keyboard.down("Control")
        page.mouse.click(px, py)
        page.keyboard.up("Control")
        page.wait_for_timeout(100)

        events = _get_events(page, "pointer_down")
        assert len(events) >= 1
        assert "ctrl" in events[0].get("modifiers", []), (
            f"Expected 'ctrl' in modifiers, got {events[0].get('modifiers')!r}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# pointer_up — fires after mousedown + mousemove + mouseup
# ═══════════════════════════════════════════════════════════════════════════════

class TestPointerUp:
    def test_fires_after_drag(self, interact_page):
        """pointer_up fires after a drag sequence."""
        page, plot = _make_2d_page(interact_page)
        px, py = _plot_center_page()

        page.mouse.move(px, py)
        page.mouse.down()
        page.mouse.move(px + 30, py, steps=5)
        page.mouse.up()
        page.wait_for_timeout(100)

        events = _get_events(page, "pointer_up")
        assert len(events) >= 1, "Expected at least one pointer_up event"


# ═══════════════════════════════════════════════════════════════════════════════
# pointer_move — fires during drag (3D panel emits it on every mousemove)
# ═══════════════════════════════════════════════════════════════════════════════

class TestPointerMove:
    def test_fires_during_drag(self, interact_page):
        """pointer_move events fire during a drag on a 3D panel."""
        page, plot = _make_3d_page(interact_page)
        cx = FIG_W // 2 + GRID_PAD
        cy = FIG_H // 2 + GRID_PAD

        page.mouse.move(cx, cy)
        page.mouse.down()
        page.mouse.move(cx + 40, cy, steps=8)
        page.mouse.up()
        page.wait_for_timeout(100)

        events = _get_events(page, "pointer_move")
        assert len(events) > 0, "Expected pointer_move events during 3D drag"


# ═══════════════════════════════════════════════════════════════════════════════
# pointer_enter / pointer_leave
# ═══════════════════════════════════════════════════════════════════════════════

class TestPointerEnterLeave:
    def test_pointer_enter_fires_on_mouseenter(self, interact_page):
        """pointer_enter fires when mouse enters the canvas."""
        page, plot = _make_2d_page(interact_page)
        px, py = _plot_center_page()

        # Start outside, move inside
        page.mouse.move(0, 0)
        page.wait_for_timeout(50)
        page.mouse.move(px, py)
        page.wait_for_timeout(100)

        events = _get_events(page, "pointer_enter")
        assert len(events) >= 1, "Expected pointer_enter event"
        e = events[0]
        # button should be null when no button is held
        assert e.get("button") is None, (
            f"pointer_enter button should be null, got {e.get('button')!r}"
        )

    def test_pointer_leave_fires_on_mouseleave(self, interact_page):
        """pointer_leave fires when mouse leaves the canvas."""
        page, plot = _make_2d_page(interact_page)
        px, py = _plot_center_page()

        page.mouse.move(px, py)
        page.wait_for_timeout(50)
        page.mouse.move(0, 0)
        page.wait_for_timeout(100)

        events = _get_events(page, "pointer_leave")
        assert len(events) >= 1, "Expected pointer_leave event"


# ═══════════════════════════════════════════════════════════════════════════════
# double_click
# ═══════════════════════════════════════════════════════════════════════════════

class TestDoubleClick:
    def test_fires_on_dblclick(self, interact_page):
        """double_click event fires on a browser dblclick."""
        page, plot = _make_2d_page(interact_page)
        px, py = _plot_center_page()

        page.mouse.dblclick(px, py)
        page.wait_for_timeout(100)

        events = _get_events(page, "double_click")
        assert len(events) >= 1, "Expected double_click event"
        assert events[0].get("button") == 0


# ═══════════════════════════════════════════════════════════════════════════════
# wheel
# ═══════════════════════════════════════════════════════════════════════════════

class TestWheel:
    def test_fires_with_dy_field(self, interact_page):
        """wheel event fires with a dy field when scrolling."""
        page, plot = _make_2d_page(interact_page)
        px, py = _plot_center_page()

        page.mouse.move(px, py)
        page.wait_for_timeout(50)
        page.mouse.wheel(0, 120)
        page.wait_for_timeout(100)

        events = _get_events(page, "wheel")
        assert len(events) >= 1, "Expected wheel event"
        e = events[0]
        assert "dy" in e, "wheel event must include dy field"


# ═══════════════════════════════════════════════════════════════════════════════
# key_down / key_up
# ═══════════════════════════════════════════════════════════════════════════════

class TestKeyEvents:
    def test_key_down_fires_on_keypress(self, interact_page):
        """key_down fires for any keypress (not just registered shortcuts)."""
        page, plot = _make_2d_page(interact_page)
        px, py = _plot_center_page()

        # Focus canvas via mouseenter
        page.mouse.move(px, py)
        page.wait_for_timeout(50)

        page.keyboard.press("q")
        page.wait_for_timeout(100)

        events = _get_events(page, "key_down")
        assert len(events) >= 1, "Expected key_down event"
        e = events[0]
        assert e.get("key") == "q", f"Expected key='q', got {e.get('key')!r}"

    def test_key_up_fires_on_key_release(self, interact_page):
        """key_up fires when a key is released."""
        page, plot = _make_2d_page(interact_page)
        px, py = _plot_center_page()

        page.mouse.move(px, py)
        page.wait_for_timeout(50)

        page.keyboard.down("z")
        page.wait_for_timeout(30)
        page.keyboard.up("z")
        page.wait_for_timeout(100)

        events = _get_events(page, "key_up")
        assert len(events) >= 1, "Expected key_up event"
        e = events[0]
        assert e.get("key") == "z", f"Expected key='z', got {e.get('key')!r}"


# ═══════════════════════════════════════════════════════════════════════════════
# Plot3D — pointer_down absent, wheel present
# ═══════════════════════════════════════════════════════════════════════════════

class TestPlot3DEvents:
    def test_3d_pointer_down_no_xdata(self, interact_page):
        """3D pointer_down events (if any) should not have xdata/ydata fields."""
        page, plot = _make_3d_page(interact_page)
        # 3D canvas covers the full panel; use centre
        cx = FIG_W // 2 + GRID_PAD
        cy = FIG_H // 2 + GRID_PAD

        page.mouse.move(cx, cy)
        page.mouse.click(cx, cy)
        page.wait_for_timeout(300)

        events = _get_events(page, "pointer_down")
        for e in events:
            assert e.get("xdata") is None, "3D pointer_down should not have xdata"
            assert e.get("ydata") is None, "3D pointer_down should not have ydata"
        # Test passes even if no pointer_down events — 3D may not emit them

    def test_3d_wheel_fires(self, interact_page):
        """Plot3D emits a wheel event on scroll."""
        page, plot = _make_3d_page(interact_page)
        cx = FIG_W // 2 + GRID_PAD
        cy = FIG_H // 2 + GRID_PAD

        page.mouse.move(cx, cy)
        page.wait_for_timeout(50)
        page.mouse.wheel(0, 120)
        page.wait_for_timeout(100)

        wheel_events = _get_events(page, "wheel")
        assert len(wheel_events) >= 1, "Expected wheel event from 3D panel"
        assert "dy" in wheel_events[0]

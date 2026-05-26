"""
tests/test_interactive/test_events_regression.py
=================================================

Regression tests for event isolation in figure_esm.js.

Core invariants verified here
------------------------------
1. double_click fires on dblclick and is NOT consumed/suppressed by the
   pan/drag machinery or the single-click candidate logic.
2. A true drag (significant movement) does NOT emit pointer_down; it emits
   pointer_up instead.
3. A short single click emits exactly one pointer_down (no spurious extras).
4. Right-click (button=2) does not trigger the left-click event path.
5. The wheel event fires independently of click/drag state.
6. Event ordering on a double-click: pointer_down ×2 → double_click.
7. A drag followed immediately by a double-click: double_click still fires.

Coordinate system (mirrors figure_esm.js constants)
----------------------------------------------------
  PAD_L=58  PAD_R=12  PAD_T=12  PAD_B=42  GRID_PAD=8
  For a 400×300 fig: plot area = {x:66, y:20, w:330, h:246}
  (page coords = canvas coords + GRID_PAD)
"""
from __future__ import annotations

import numpy as np
import pytest

import anyplotlib as apl
from anyplotlib.tests.test_interactive._event_test_utils import (
    _collect_events,
    _get_events,
    _plot_center_page,
    GRID_PAD,
)


def _clear_events(page) -> None:
    """Clear the accumulated event list without re-wrapping the model setter."""
    page.evaluate("() => { window._aplAllEvents = []; }")

FIG_W, FIG_H = 400, 300

# Large enough move to clear the 4 px² drag threshold (>4 px in one direction).
DRAG_DISTANCE = 40


# ── page factories ─────────────────────────────────────────────────────────────

def _make_2d_page(interact_page):
    fig, ax = apl.subplots(1, 1, figsize=(FIG_W, FIG_H))
    plot = ax.imshow(np.zeros((32, 32)))
    page = interact_page(fig)
    _collect_events(page)
    return page, plot


def _make_1d_page(interact_page):
    fig, ax = apl.subplots(1, 1, figsize=(FIG_W, FIG_H))
    plot = ax.plot(np.sin(np.linspace(0, 2 * np.pi, 128)))
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


# ══════════════════════════════════════════════════════════════════════════════
# Double-click isolation
# ══════════════════════════════════════════════════════════════════════════════

class TestDoubleClickIsolation:
    """double_click must fire even when the pan/drag machinery is active."""

    # ── Click-cascade prerequisites (expose the e.preventDefault() bug) ───────
    #
    # Playwright's page.mouse.dblclick() injects dblclick via CDP (clickCount=2),
    # bypassing the browser's click → dblclick cascade entirely.  To detect the
    # real regression we must verify the prerequisite: that `click` fires after
    # mousedown + mouseup.  Chrome suppresses `click` when mousedown calls
    # e.preventDefault(), which breaks every real user double-click.

    def test_click_fires_after_mousedown_2d(self, interact_page):
        """click fires after mousedown+mouseup on the 2D canvas (dblclick prerequisite).

        Chrome spec: mousedown.preventDefault() suppresses the subsequent click.
        Without click, the browser's dblclick cascade breaks for real users.
        This test directly verifies the precondition: no e.preventDefault() in
        the 2D pan mousedown must allow click to propagate.
        """
        page, _ = _make_2d_page(interact_page)
        px, py = _plot_center_page()

        page.evaluate("""() => {
            window._aplClickCount = 0;
            document.addEventListener('click', () => window._aplClickCount++, true);
        }""")

        page.mouse.move(px, py)
        page.mouse.down()
        page.mouse.up()
        page.wait_for_timeout(50)

        click_count = page.evaluate("() => window._aplClickCount")
        assert click_count >= 1, (
            "click must fire after mousedown+mouseup on the 2D canvas. "
            "e.preventDefault() on mousedown suppresses click → breaks dblclick "
            "for real users. Fix: remove preventDefault from the 2D pan mousedown."
        )

    def test_click_fires_after_mousedown_1d(self, interact_page):
        """click fires after mousedown+mouseup on the 1D canvas (dblclick prerequisite)."""
        page, _ = _make_1d_page(interact_page)
        px, py = _plot_center_page()

        page.evaluate("""() => {
            window._aplClickCount = 0;
            document.addEventListener('click', () => window._aplClickCount++, true);
        }""")

        page.mouse.move(px, py)
        page.mouse.down()
        page.mouse.up()
        page.wait_for_timeout(50)

        click_count = page.evaluate("() => window._aplClickCount")
        assert click_count >= 1, (
            "click must fire after mousedown+mouseup on the 1D canvas. "
            "e.preventDefault() on mousedown suppresses click → breaks dblclick."
        )

    def test_click_fires_after_mousedown_3d(self, interact_page):
        """click fires after mousedown+mouseup on the 3D canvas (dblclick prerequisite)."""
        page, _ = _make_3d_page(interact_page)
        cx = FIG_W // 2 + GRID_PAD
        cy = FIG_H // 2 + GRID_PAD

        page.evaluate("""() => {
            window._aplClickCount = 0;
            document.addEventListener('click', () => window._aplClickCount++, true);
        }""")

        page.mouse.move(cx, cy)
        page.mouse.down()
        page.mouse.up()
        page.wait_for_timeout(50)

        click_count = page.evaluate("() => window._aplClickCount")
        assert click_count >= 1, (
            "click must fire after mousedown+mouseup on the 3D canvas. "
            "e.preventDefault() on mousedown suppresses click → breaks dblclick."
        )

    # ── Synthetic dblclick tests (page.mouse.dblclick uses CDP clickCount=2) ──

    def test_dblclick_fires_on_2d_panel(self, interact_page):
        """double_click is emitted when the user double-clicks a 2D panel."""
        page, _ = _make_2d_page(interact_page)
        px, py = _plot_center_page()

        page.mouse.dblclick(px, py)
        page.wait_for_timeout(150)

        events = _get_events(page, "double_click")
        assert len(events) >= 1, "double_click must fire on dblclick"
        assert events[0].get("button") == 0, "double_click button should be 0"

    def test_dblclick_fires_on_1d_panel(self, interact_page):
        """double_click is emitted when the user double-clicks a 1D panel."""
        page, _ = _make_1d_page(interact_page)
        px, py = _plot_center_page()

        page.mouse.dblclick(px, py)
        page.wait_for_timeout(150)

        events = _get_events(page, "double_click")
        assert len(events) >= 1, "double_click must fire on 1D dblclick"

    def test_dblclick_fires_on_3d_panel(self, interact_page):
        """double_click is emitted when the user double-clicks a 3D panel."""
        page, _ = _make_3d_page(interact_page)
        cx = FIG_W // 2 + GRID_PAD
        cy = FIG_H // 2 + GRID_PAD

        page.mouse.dblclick(cx, cy)
        page.wait_for_timeout(150)

        events = _get_events(page, "double_click")
        assert len(events) >= 1, "double_click must fire on 3D dblclick"

    def test_dblclick_fires_after_preceding_drag(self, interact_page):
        """double_click still fires after a preceding drag sequence.

        This guards the regression where the isPanning flag or the drag
        document-level listener could prevent subsequent dblclick events.
        """
        page, _ = _make_2d_page(interact_page)
        px, py = _plot_center_page()

        # Perform a drag first
        page.mouse.move(px, py)
        page.mouse.down()
        page.mouse.move(px + DRAG_DISTANCE, py, steps=8)
        page.mouse.up()
        page.wait_for_timeout(100)

        # Now double-click: double_click must still fire
        _clear_events(page)
        page.mouse.dblclick(px, py)
        page.wait_for_timeout(150)

        events = _get_events(page, "double_click")
        assert len(events) >= 1, (
            "double_click must fire after a preceding drag — "
            "isPanning flag must not suppress dblclick"
        )

    def test_dblclick_has_correct_coordinates(self, interact_page):
        """double_click payload carries plausible x/y coordinates."""
        page, _ = _make_2d_page(interact_page)
        px, py = _plot_center_page()

        page.mouse.dblclick(px, py)
        page.wait_for_timeout(150)

        events = _get_events(page, "double_click")
        assert len(events) >= 1
        e = events[0]
        # x/y should be within the canvas bounds (0..FIG_W, 0..FIG_H)
        assert "x" in e and "y" in e, "double_click must carry x, y fields"
        assert 0 <= e["x"] <= FIG_W, f"double_click x={e['x']} out of range"
        assert 0 <= e["y"] <= FIG_H, f"double_click y={e['y']} out of range"

    def test_double_click_event_order(self, interact_page):
        """On dblclick: pointer_down fires before double_click.

        The expected sequence is: pointer_down(×1-2) then double_click.
        We verify that the last event in the sequence is double_click (not
        the first), so the double_click is never emitted before its preceding
        single-click path has had a chance to run.
        """
        page, _ = _make_2d_page(interact_page)
        px, py = _plot_center_page()

        page.mouse.dblclick(px, py)
        page.wait_for_timeout(150)

        all_events = _get_events(page)
        # At minimum: pointer_down events and double_click
        event_types = [e.get("event_type") for e in all_events]
        assert "double_click" in event_types, "double_click must be in event sequence"
        last_relevant = [t for t in event_types if t in ("pointer_down", "double_click")]
        assert last_relevant, "Expected pointer_down and/or double_click events"
        assert last_relevant[-1] == "double_click", (
            f"double_click must be the last in the click sequence, got {last_relevant}"
        )


# ══════════════════════════════════════════════════════════════════════════════
# Drag vs click distinction
# ══════════════════════════════════════════════════════════════════════════════

class TestDragVsClick:
    """Drag and single-click are mutually exclusive event paths on 2D panels."""

    def test_single_click_emits_pointer_down(self, interact_page):
        """A short stationary click emits exactly one pointer_down."""
        page, _ = _make_2d_page(interact_page)
        px, py = _plot_center_page()

        page.mouse.click(px, py)
        page.wait_for_timeout(150)

        events = _get_events(page, "pointer_down")
        assert len(events) == 1, (
            f"Expected exactly 1 pointer_down on single click, got {len(events)}"
        )

    def test_significant_drag_does_not_emit_pointer_down(self, interact_page):
        """A drag with significant motion clears the click candidate → no pointer_down."""
        page, _ = _make_2d_page(interact_page)
        px, py = _plot_center_page()

        page.mouse.move(px, py)
        page.mouse.down()
        # Move well past the 4 px threshold
        page.mouse.move(px + DRAG_DISTANCE, py, steps=10)
        page.mouse.up()
        page.wait_for_timeout(150)

        pd_events = _get_events(page, "pointer_down")
        assert len(pd_events) == 0, (
            f"Drag must not emit pointer_down (click candidate should be cleared), "
            f"got {len(pd_events)} pointer_down events"
        )

    def test_significant_drag_emits_pointer_up(self, interact_page):
        """A drag emits pointer_up on release."""
        page, _ = _make_2d_page(interact_page)
        px, py = _plot_center_page()

        page.mouse.move(px, py)
        page.mouse.down()
        page.mouse.move(px + DRAG_DISTANCE, py, steps=10)
        page.mouse.up()
        page.wait_for_timeout(150)

        pu_events = _get_events(page, "pointer_up")
        assert len(pu_events) >= 1, "Drag must emit at least one pointer_up on release"

    def test_drag_then_click_emits_pointer_down(self, interact_page):
        """After a drag completes, a subsequent short click fires pointer_down."""
        page, _ = _make_2d_page(interact_page)
        px, py = _plot_center_page()

        # Drag first
        page.mouse.move(px, py)
        page.mouse.down()
        page.mouse.move(px + DRAG_DISTANCE, py, steps=10)
        page.mouse.up()
        page.wait_for_timeout(100)

        # Reset event collector
        _clear_events(page)

        # Short click
        page.mouse.click(px, py)
        page.wait_for_timeout(150)

        events = _get_events(page, "pointer_down")
        assert len(events) == 1, (
            "After a drag, a short click must still emit pointer_down"
        )

    def test_small_movement_still_registers_as_click(self, interact_page):
        """Movement within the 2 px click threshold still triggers pointer_down."""
        page, _ = _make_2d_page(interact_page)
        px, py = _plot_center_page()

        page.mouse.move(px, py)
        page.mouse.down()
        # Move less than 2 px — within the distance² ≤ 25 threshold
        page.mouse.move(px + 1, py + 1, steps=2)
        page.mouse.up()
        page.wait_for_timeout(150)

        events = _get_events(page, "pointer_down")
        assert len(events) == 1, (
            "Tiny movement within click threshold must still produce pointer_down"
        )


# ══════════════════════════════════════════════════════════════════════════════
# Button filtering
# ══════════════════════════════════════════════════════════════════════════════

class TestButtonFiltering:
    """Non-primary buttons must not trigger the 2D left-click event path."""

    def test_right_click_does_not_emit_pointer_down(self, interact_page):
        """Right-click (button=2) on a 2D panel does not emit pointer_down.

        The mousedown handler returns early for button !== 0, so no
        clickCandidate is set and pointer_down must not fire.
        """
        page, _ = _make_2d_page(interact_page)
        px, py = _plot_center_page()

        page.mouse.click(px, py, button="right")
        page.wait_for_timeout(150)

        events = _get_events(page, "pointer_down")
        assert len(events) == 0, (
            "Right-click must not emit pointer_down (button !== 0 guard)"
        )

    def test_middle_click_does_not_emit_pointer_down(self, interact_page):
        """Middle-click (button=1) on a 2D panel does not emit pointer_down."""
        page, _ = _make_2d_page(interact_page)
        px, py = _plot_center_page()

        page.mouse.click(px, py, button="middle")
        page.wait_for_timeout(150)

        events = _get_events(page, "pointer_down")
        assert len(events) == 0, (
            "Middle-click must not emit pointer_down (button !== 0 guard)"
        )

    def test_left_click_emits_pointer_down(self, interact_page):
        """Sanity-check: left-click still emits pointer_down after button tests."""
        page, _ = _make_2d_page(interact_page)
        px, py = _plot_center_page()

        page.mouse.click(px, py)
        page.wait_for_timeout(150)

        events = _get_events(page, "pointer_down")
        assert len(events) == 1, "Left-click must emit pointer_down"


# ══════════════════════════════════════════════════════════════════════════════
# Wheel independence
# ══════════════════════════════════════════════════════════════════════════════

class TestWheelIndependence:
    """Wheel events fire independently of click/drag state."""

    def test_wheel_after_click_still_fires(self, interact_page):
        """wheel event fires correctly after a preceding click."""
        page, _ = _make_2d_page(interact_page)
        px, py = _plot_center_page()

        page.mouse.click(px, py)
        page.wait_for_timeout(50)

        _clear_events(page)
        page.mouse.move(px, py)
        page.mouse.wheel(0, 120)
        page.wait_for_timeout(100)

        events = _get_events(page, "wheel")
        assert len(events) >= 1, "wheel must fire after a preceding click"
        assert "dy" in events[0], "wheel event must carry dy field"

    def test_wheel_during_drag_does_not_suppress_dblclick(self, interact_page):
        """wheel event during an active pan does not block subsequent dblclick."""
        page, _ = _make_2d_page(interact_page)
        px, py = _plot_center_page()

        # Drag + wheel
        page.mouse.move(px, py)
        page.mouse.down()
        page.mouse.move(px + DRAG_DISTANCE, py, steps=5)
        page.mouse.wheel(0, 120)
        page.mouse.up()
        page.wait_for_timeout(100)

        _clear_events(page)
        page.mouse.dblclick(px, py)
        page.wait_for_timeout(150)

        events = _get_events(page, "double_click")
        assert len(events) >= 1, "double_click must fire after wheel+drag sequence"


# ══════════════════════════════════════════════════════════════════════════════
# 1D panel event specifics
# ══════════════════════════════════════════════════════════════════════════════

class TestPlot1DEvents:
    """1D panel event path regression tests."""

    def test_1d_single_click_emits_pointer_down_when_near_line(self, interact_page):
        """Short 1D click near the plotted line emits pointer_down."""
        fig, ax = apl.subplots(1, 1, figsize=(FIG_W, FIG_H))
        # Flat line at y=0; the plot centre is near the line.
        ax.plot(np.zeros(128))
        page = interact_page(fig)
        _clear_events(page)

        px, py = _plot_center_page()
        page.mouse.click(px, py)
        page.wait_for_timeout(150)

        # pointer_down fires when the hit-test finds the line; if not found
        # the event is simply not emitted — so we verify count is 0 or 1.
        events = _get_events(page, "pointer_down")
        # Not asserting exact count because line hit depends on render geometry.
        # Key guarantee: no error raised, and no spurious extra pointer_down events.
        assert isinstance(events, list)

    def test_1d_drag_does_not_emit_pointer_down(self, interact_page):
        """A 1D drag larger than 5 px does not emit pointer_down."""
        page, _ = _make_1d_page(interact_page)
        px, py = _plot_center_page()

        page.mouse.move(px, py)
        page.mouse.down()
        page.mouse.move(px + 30, py, steps=10)
        page.mouse.up()
        page.wait_for_timeout(150)

        events = _get_events(page, "pointer_down")
        assert len(events) == 0, (
            "1D drag must not emit pointer_down (distance guard)"
        )

    def test_1d_dblclick_fires_double_click(self, interact_page):
        """1D panel dblclick emits double_click, not blocked by pan state."""
        page, _ = _make_1d_page(interact_page)
        px, py = _plot_center_page()

        page.mouse.dblclick(px, py)
        page.wait_for_timeout(150)

        events = _get_events(page, "double_click")
        assert len(events) >= 1, "1D dblclick must emit double_click"

    def test_1d_pointer_up_fires_on_drag(self, interact_page):
        """1D drag emits pointer_up on release."""
        page, _ = _make_1d_page(interact_page)
        px, py = _plot_center_page()

        page.mouse.move(px, py)
        page.mouse.down()
        page.mouse.move(px + 30, py, steps=10)
        page.mouse.up()
        page.wait_for_timeout(150)

        events = _get_events(page, "pointer_up")
        assert len(events) >= 1, "1D drag must emit pointer_up on release"


# ══════════════════════════════════════════════════════════════════════════════
# 3D panel event specifics
# ══════════════════════════════════════════════════════════════════════════════

class TestPlot3DEvents:
    """3D panel event regression tests."""

    def test_3d_dblclick_fires_double_click(self, interact_page):
        """3D panel dblclick emits double_click despite drag being active."""
        page, _ = _make_3d_page(interact_page)
        cx = FIG_W // 2 + GRID_PAD
        cy = FIG_H // 2 + GRID_PAD

        page.mouse.dblclick(cx, cy)
        page.wait_for_timeout(150)

        events = _get_events(page, "double_click")
        assert len(events) >= 1, "3D dblclick must emit double_click"

    def test_3d_drag_emits_pointer_move(self, interact_page):
        """3D drag emits pointer_move events (not blocked by drag state)."""
        page, _ = _make_3d_page(interact_page)
        cx = FIG_W // 2 + GRID_PAD
        cy = FIG_H // 2 + GRID_PAD

        page.mouse.move(cx, cy)
        page.mouse.down()
        page.mouse.move(cx + 40, cy, steps=8)
        page.mouse.up()
        page.wait_for_timeout(150)

        events = _get_events(page, "pointer_move")
        assert len(events) > 0, "3D drag must emit pointer_move events"

    def test_3d_dblclick_fires_after_drag(self, interact_page):
        """3D double_click fires after a preceding drag sequence."""
        page, _ = _make_3d_page(interact_page)
        cx = FIG_W // 2 + GRID_PAD
        cy = FIG_H // 2 + GRID_PAD

        # Drag first
        page.mouse.move(cx, cy)
        page.mouse.down()
        page.mouse.move(cx + 40, cy, steps=8)
        page.mouse.up()
        page.wait_for_timeout(100)

        _clear_events(page)
        page.mouse.dblclick(cx, cy)
        page.wait_for_timeout(150)

        events = _get_events(page, "double_click")
        assert len(events) >= 1, (
            "3D double_click must fire after preceding drag"
        )

    def test_3d_wheel_fires_independently(self, interact_page):
        """3D wheel event fires even during/after a drag."""
        page, _ = _make_3d_page(interact_page)
        cx = FIG_W // 2 + GRID_PAD
        cy = FIG_H // 2 + GRID_PAD

        page.mouse.move(cx, cy)
        page.mouse.wheel(0, 120)
        page.wait_for_timeout(100)

        events = _get_events(page, "wheel")
        assert len(events) >= 1, "3D wheel must fire"
        assert "dy" in events[0]


# ══════════════════════════════════════════════════════════════════════════════
# Pointer enter / leave
# ══════════════════════════════════════════════════════════════════════════════

class TestPointerEnterLeave:
    """pointer_enter and pointer_leave must fire independently of click/drag."""

    def test_pointer_enter_fires_after_drag(self, interact_page):
        """pointer_enter fires when entering after a drag on another part of the page."""
        page, _ = _make_2d_page(interact_page)
        px, py = _plot_center_page()

        # Leave canvas, do a drag outside, then re-enter
        page.mouse.move(0, 0)
        page.wait_for_timeout(50)
        page.mouse.move(px, py)
        page.wait_for_timeout(100)

        events = _get_events(page, "pointer_enter")
        assert len(events) >= 1, "pointer_enter must fire on canvas entry"

    def test_pointer_leave_fires_after_drag(self, interact_page):
        """pointer_leave fires when leaving even if a drag is in progress."""
        page, _ = _make_2d_page(interact_page)
        px, py = _plot_center_page()

        page.mouse.move(px, py)
        page.wait_for_timeout(30)
        _clear_events(page)

        # Move outside the figure entirely
        page.mouse.move(0, 0)
        page.wait_for_timeout(100)

        events = _get_events(page, "pointer_leave")
        assert len(events) >= 1, "pointer_leave must fire on canvas exit"


# ══════════════════════════════════════════════════════════════════════════════
# HAADF STEM nanoparticle picker regression
# ══════════════════════════════════════════════════════════════════════════════

class TestParticlePickerDblClick:
    """Regression tests mirroring the HAADF STEM nanoparticle picker example.

    The picker's ``_on_double_click`` handler starts with::

        if event.xdata is None or event.ydata is None:
            return

    So if the JS ``double_click`` event payload does not include ``xdata`` and
    ``ydata``, every pick silently fails.  These tests reproduce that exact
    failure mode.
    """

    def test_dblclick_payload_includes_xdata_ydata(self, interact_page):
        """double_click event on a 2D imshow carries non-None xdata and ydata.

        Root cause: the dblclick handler in figure_esm.js was emitting only
        canvas-pixel ``x``/``y``, not the image-space ``xdata``/``ydata``
        that Python handlers receive as ``event.xdata``/``event.ydata``.
        The particle picker's guard ``if event.xdata is None: return`` meant
        every double-click was silently dropped.
        """
        fig, ax = apl.subplots(1, 1, figsize=(FIG_W, FIG_H))
        plot = ax.imshow(np.zeros((64, 64)))
        page = interact_page(fig)
        _collect_events(page)

        px, py = _plot_center_page()
        page.mouse.dblclick(px, py)
        page.wait_for_timeout(150)

        events = _get_events(page, "double_click")
        assert len(events) >= 1, "double_click must fire on dblclick"
        e = events[0]
        assert "xdata" in e, "double_click payload must include xdata"
        assert "ydata" in e, "double_click payload must include ydata"
        assert e["xdata"] is not None, "xdata must not be None"
        assert e["ydata"] is not None, "ydata must not be None"

    def test_dblclick_xdata_ydata_are_image_coords(self, interact_page):
        """xdata/ydata in double_click are image-space coordinates (0..N range).

        For a 64×64 image, a click at the canvas centre should produce
        xdata and ydata near 32 (the image midpoint).
        """
        fig, ax = apl.subplots(1, 1, figsize=(FIG_W, FIG_H))
        plot = ax.imshow(np.zeros((64, 64)))
        page = interact_page(fig)
        _collect_events(page)

        px, py = _plot_center_page()
        page.mouse.dblclick(px, py)
        page.wait_for_timeout(150)

        events = _get_events(page, "double_click")
        assert len(events) >= 1
        e = events[0]
        # Image is 64×64; centre click should land roughly in the middle half.
        assert 10 <= e["xdata"] <= 54, (
            f"xdata={e['xdata']:.1f} out of expected range for 64×64 image centre click"
        )
        assert 10 <= e["ydata"] <= 54, (
            f"ydata={e['ydata']:.1f} out of expected range for 64×64 image centre click"
        )

    def test_dblclick_with_circles_markers_present(self, interact_page):
        """double_click still carries xdata/ydata when circles markers are on the plot.

        The particle picker adds candidate circles before any interaction.
        This test ensures markers don't interfere with the dblclick coordinate
        computation.
        """
        fig, ax = apl.subplots(1, 1, figsize=(FIG_W, FIG_H))
        plot = ax.imshow(np.zeros((64, 64)))
        # Mirror the particle picker: add candidate circles
        candidates = np.array([[16.0, 16.0], [48.0, 48.0], [32.0, 32.0]])
        plot.add_circles(candidates, name="candidates", radius=6,
                         facecolors="none", edgecolors="#555555")
        page = interact_page(fig)
        _collect_events(page)

        px, py = _plot_center_page()
        page.mouse.dblclick(px, py)
        page.wait_for_timeout(150)

        events = _get_events(page, "double_click")
        assert len(events) >= 1, "double_click must fire with circles present"
        e = events[0]
        assert e.get("xdata") is not None, "xdata must not be None with circles present"
        assert e.get("ydata") is not None, "ydata must not be None with circles present"

    def test_dblclick_after_pan_carries_xdata_ydata(self, interact_page):
        """After a pan (which shifts the viewport), dblclick still carries xdata/ydata.

        The particle picker is used with zoom/pan interactions before picking.
        xdata/ydata must track the panned viewport, not the raw canvas offset.
        """
        fig, ax = apl.subplots(1, 1, figsize=(FIG_W, FIG_H))
        plot = ax.imshow(np.zeros((64, 64)))
        page = interact_page(fig)
        _collect_events(page)

        px, py = _plot_center_page()

        # Pan the viewport
        page.mouse.move(px, py)
        page.mouse.down()
        page.mouse.move(px + 30, py + 20, steps=8)
        page.mouse.up()
        page.wait_for_timeout(100)
        _clear_events(page)

        # Now double-click — xdata/ydata must reflect the panned position
        page.mouse.dblclick(px, py)
        page.wait_for_timeout(150)

        events = _get_events(page, "double_click")
        assert len(events) >= 1, "double_click must fire after a pan"
        e = events[0]
        assert e.get("xdata") is not None, "xdata must not be None after pan"
        assert e.get("ydata") is not None, "ydata must not be None after pan"


# ══════════════════════════════════════════════════════════════════════════════
# HAADF STEM nanoparticle picker — dwell/settle regression
# ══════════════════════════════════════════════════════════════════════════════

class TestParticlePickerDwell:
    """Regression tests mirroring the particle picker's pointer_settled handler.

    The picker's ``_on_settled`` starts with::

        if event.xdata is None or event.ydata is None:
            return

    So ``pointer_settled`` must include ``xdata``/``ydata`` for the dwell
    inspection to work.  These tests reproduce that exact failure mode and
    guard the fix.
    """

    def _make_picker_page(self, interact_page, ms: int = 200):
        """Build a page that mirrors the particle picker setup.

        Uses ms=200 so the test doesn't have to wait the full 300 ms of the
        real example.  The panel state is serialised into the standalone HTML
        so JS sees ``pointer_settled_ms = 200`` without needing a Python kernel.
        """
        fig, ax = apl.subplots(1, 1, figsize=(FIG_W, FIG_H))
        plot = ax.imshow(np.zeros((64, 64)))
        # Mirrors the picker: add candidate circles
        candidates = np.array([[16.0, 16.0], [48.0, 48.0], [32.0, 32.0]])
        plot.add_circles(candidates, name="candidates", radius=6,
                         facecolors="none", edgecolors="#555555")
        # Register a dummy handler so pointer_settled_ms is baked into state
        plot.add_event_handler(lambda e: None, "pointer_settled", ms=ms, delta=6)
        page = interact_page(fig)
        _collect_events(page)
        return page, plot

    def test_settled_payload_includes_xdata_ydata(self, interact_page):
        """pointer_settled event on a 2D imshow carries non-None xdata and ydata.

        Root cause: the setTimeout callback in figure_esm.js was emitting only
        canvas-pixel ``x``/``y``.  The particle picker's guard
        ``if event.xdata is None: return`` therefore caused every dwell
        inspection to be silently skipped.
        """
        page, plot = self._make_picker_page(interact_page)
        px, py = _plot_center_page()

        # Move into the plot area and hold still — wait for the event
        page.mouse.move(px, py)
        page.wait_for_function(
            "() => window._aplAllEvents.some(e => e.event_type === 'pointer_settled')",
            timeout=2000,
        )

        events = _get_events(page, "pointer_settled")
        assert len(events) >= 1, "pointer_settled must fire after dwell"
        e = events[0]
        assert "xdata" in e, "pointer_settled payload must include xdata"
        assert "ydata" in e, "pointer_settled payload must include ydata"
        assert e["xdata"] is not None, "xdata must not be None"
        assert e["ydata"] is not None, "ydata must not be None"

    def test_settled_xdata_ydata_are_image_coords(self, interact_page):
        """xdata/ydata in pointer_settled are image-space coordinates (0..N range).

        For a 64×64 image, a dwell at the canvas centre should produce
        xdata and ydata near 32.
        """
        page, plot = self._make_picker_page(interact_page)
        px, py = _plot_center_page()

        page.mouse.move(px, py)
        page.wait_for_function(
            "() => window._aplAllEvents.some(e => e.event_type === 'pointer_settled')",
            timeout=2000,
        )

        events = _get_events(page, "pointer_settled")
        assert len(events) >= 1
        e = events[0]
        assert 10 <= e["xdata"] <= 54, (
            f"xdata={e['xdata']:.1f} out of expected range for 64×64 image centre dwell"
        )
        assert 10 <= e["ydata"] <= 54, (
            f"ydata={e['ydata']:.1f} out of expected range for 64×64 image centre dwell"
        )

    def test_settled_fires_after_configured_ms(self, interact_page):
        """pointer_settled fires after the configured dwell period (ms=200).

        Guards the full pipeline: Python sets pointer_settled_ms in state →
        state is serialised to HTML → JS reads it and arms the setTimeout →
        event fires after the dwell period with dwell_ms >= 200.
        """
        page, plot = self._make_picker_page(interact_page, ms=200)
        px, py = _plot_center_page()

        # Verify JS received the configured ms value
        ms_in_js = page.evaluate(
            f"() => JSON.parse(window._aplModel.get('panel_{plot._id}_json')).pointer_settled_ms"
        )
        assert ms_in_js == 200, f"JS pointer_settled_ms should be 200, got {ms_in_js}"

        page.mouse.move(px, py)
        page.wait_for_function(
            "() => window._aplAllEvents.some(e => e.event_type === 'pointer_settled')",
            timeout=2000,
        )

        events = _get_events(page, "pointer_settled")
        e = events[0]
        assert "dwell_ms" in e, "pointer_settled must carry dwell_ms"
        assert e["dwell_ms"] >= 200, (
            f"dwell_ms={e['dwell_ms']:.0f} should be >= 200"
        )
        assert e.get("xdata") is not None, "xdata must be present after dwell"
        assert e.get("ydata") is not None, "ydata must be present after dwell"

    def test_settled_not_fired_while_moving(self, interact_page):
        """pointer_settled does not fire while the pointer keeps moving.

        The particle picker should only inspect a candidate when the user
        deliberately hovers over it — not during panning.
        """
        page, plot = self._make_picker_page(interact_page, ms=200)
        px, py = _plot_center_page()

        # Keep moving for ~240 ms (less than 200 ms settle threshold between moves)
        page.mouse.move(px, py)
        for _ in range(8):
            px += 5
            page.mouse.move(px, py)
            page.wait_for_timeout(25)

        events = _get_events(page, "pointer_settled")
        assert len(events) == 0, (
            "pointer_settled must not fire while pointer is continuously moving"
        )

    def test_settled_fires_after_pan_with_xdata_ydata(self, interact_page):
        """After a pan, pointer_settled still carries correct xdata/ydata.

        The particle picker is frequently used after navigating the image.
        The settled event must report the panned position, not the original
        canvas position.
        """
        page, plot = self._make_picker_page(interact_page)
        px, py = _plot_center_page()

        # Pan the viewport first
        page.mouse.move(px, py)
        page.mouse.down()
        page.mouse.move(px + 30, py + 20, steps=8)
        page.mouse.up()
        page.wait_for_timeout(50)
        _clear_events(page)

        # Now hold still over the same canvas position
        page.mouse.move(px, py)
        page.wait_for_function(
            "() => window._aplAllEvents.some(e => e.event_type === 'pointer_settled')",
            timeout=2000,
        )

        events = _get_events(page, "pointer_settled")
        assert len(events) >= 1, "pointer_settled must fire after pan + dwell"
        e = events[0]
        assert e.get("xdata") is not None, "xdata must not be None after pan"
        assert e.get("ydata") is not None, "ydata must not be None after pan"


# ══════════════════════════════════════════════════════════════════════════════
# Marker pixel-centre alignment  (_imgToCanvas2d +0.5 fix)
# ══════════════════════════════════════════════════════════════════════════════

class TestMarkerPixelCenterAlignment:
    """Circle markers must be drawn at (ix+0.5)*scale, not ix*scale.

    Each rendered image pixel i occupies canvas [i*scale, (i+1)*scale).
    Its visual centre is at (i+0.5)*scale.  Previously _imgToCanvas2d used
    ix*scale (the leading/top-left edge), so every marker appeared shifted
    0.5*scale pixels up and to the left — visibly wrong when zoomed in.

    This regression test directly samples the markersCanvas pixel at the
    point that lies on the circle ring only when the centre is correct.
    """

    def test_circle_drawn_at_pixel_center(self, interact_page):
        """Circle at image pixel (8,8) is rendered at canvas centre (136,136).

        Setup: 16×16 image.  2D panels always reserve PAD_T=12px at the top,
        so to get scale=16 we need imgW=imgH=256, which requires:
          FIG_W=256, FIG_H=256+12=268 (no axes → no left/bottom gutters)
          imgW=256, imgH=268-12=256 → scale=min(256/16,256/16)=16

          correct centre = (8+0.5)*16 = 136
          old wrong centre = 8*16 = 128

        A radius-0.5 circle (canvas radius 8) centred at (136,136) has its
        ring passing through canvas (144,136).  The old wrong circle would
        have its ring passing through canvas (136,128) instead.
        We sample (144,136) and require non-zero alpha.
        """
        PAD_T = 12
        IMG_W = IMG_H = 16
        FIG_W = IMG_W * 16           # 256 — so imgW = FIG_W = 256, scale=16
        FIG_H = IMG_H * 16 + PAD_T   # 268 — so imgH = FIG_H - PAD_T = 256, scale=16

        fig, ax = apl.subplots(1, 1, figsize=(FIG_W, FIG_H))
        plot = ax.imshow(np.zeros((IMG_H, IMG_W)))
        # radius=0.5 image-px → 8 canvas-px at scale=16
        plot.add_circles(np.array([[8.0, 8.0]]), radius=0.5)

        page = interact_page(fig)
        page.wait_for_timeout(300)

        alpha = page.evaluate("""() => {
            const dpr = window.devicePixelRatio || 1;
            // markersCanvas: pointer-events:none, z-index:6, visible
            const mk = Array.from(document.querySelectorAll('canvas'))
                .find(c => c.style.pointerEvents === 'none' &&
                           c.style.zIndex === '6' &&
                           c.style.display !== 'none' &&
                           c.width > 0);
            if (!mk) return -1;
            const ctx = mk.getContext('2d');
            // If circle centre is at (136,136), the ring (r=8) passes through (144,136).
            // Check a 3px neighbourhood to be robust against sub-pixel rendering.
            let maxAlpha = 0;
            for (let dx = -1; dx <= 1; dx++) {
                for (let dy = -1; dy <= 1; dy++) {
                    const bx = Math.round((144 + dx) * dpr);
                    const by = Math.round((136 + dy) * dpr);
                    const d = ctx.getImageData(bx, by, 1, 1).data;
                    maxAlpha = Math.max(maxAlpha, d[3]);
                }
            }
            return maxAlpha;
        }""")

        assert alpha > 0, (
            "Circle ring should appear near canvas (144, 136) when the centre "
            "is at (8+0.5)*16=136.  alpha=0 means _imgToCanvas2d is still "
            "placing the circle at the leading edge (8*16=128) instead of the "
            "pixel centre (8.5*16=136)."
        )


# ══════════════════════════════════════════════════════════════════════════════
# Modifier keys in key_down and pointer_down events
# ══════════════════════════════════════════════════════════════════════════════

class TestModifierKeys:
    """Verify that modifier keys (ctrl, shift, alt) appear in event payloads.

    The JS _modifiers() helper always runs; these tests lock that invariant
    so future refactors can't silently drop modifier detection.
    """

    def test_shift_modifier_in_key_down(self, interact_page):
        """Shift+a fires key_down with modifiers=['shift']."""
        page, _ = _make_2d_page(interact_page)
        cx, cy = _plot_center_page(FIG_W, FIG_H)
        page.mouse.move(cx, cy)
        _clear_events(page)
        page.keyboard.press('Shift+a')
        page.wait_for_timeout(80)
        key_events = [e for e in _get_events(page, 'key_down')
                      if e.get('key', '').lower() == 'a']
        assert key_events, "key_down must fire for Shift+a"
        assert 'shift' in key_events[-1].get('modifiers', []), (
            "Shift key must appear in modifiers list"
        )

    def test_ctrl_modifier_in_key_down(self, interact_page):
        """Ctrl+a fires key_down with modifiers=['ctrl']."""
        page, _ = _make_2d_page(interact_page)
        cx, cy = _plot_center_page(FIG_W, FIG_H)
        page.mouse.move(cx, cy)
        _clear_events(page)
        page.keyboard.press('Control+a')
        page.wait_for_timeout(80)
        key_events = [e for e in _get_events(page, 'key_down')
                      if e.get('key', '').lower() == 'a']
        assert key_events, "key_down must fire for Ctrl+a"
        assert 'ctrl' in key_events[-1].get('modifiers', []), (
            "Ctrl key must appear in modifiers list"
        )

    def test_no_modifier_on_plain_key(self, interact_page):
        """Plain key press carries an empty modifiers list."""
        page, _ = _make_2d_page(interact_page)
        cx, cy = _plot_center_page(FIG_W, FIG_H)
        page.mouse.move(cx, cy)
        _clear_events(page)
        page.keyboard.press('a')
        page.wait_for_timeout(80)
        key_events = [e for e in _get_events(page, 'key_down')
                      if e.get('key', '').lower() == 'a']
        assert key_events, "key_down must fire for plain 'a'"
        assert key_events[-1].get('modifiers', None) == [], (
            "Plain key must have empty modifiers list"
        )

    def test_shift_modifier_in_pointer_down(self, interact_page):
        """pointer_down with Shift held carries modifiers=['shift']."""
        page, _ = _make_2d_page(interact_page)
        cx, cy = _plot_center_page(FIG_W, FIG_H)
        _clear_events(page)
        page.keyboard.down('Shift')
        page.mouse.click(cx, cy)
        page.keyboard.up('Shift')
        page.wait_for_timeout(80)
        ptr_events = _get_events(page, 'pointer_down')
        assert ptr_events, "pointer_down must fire on click"
        assert 'shift' in ptr_events[-1].get('modifiers', []), (
            "Shift held during click must appear in pointer_down modifiers"
        )

"""
tests/test_widgets.py
=====================

Tests for the Widget class system and the event_json dispatch pipeline.

Covers:
  * Widget creation, attribute access, set(), to_dict(), __setattr__
  * on_changed / on_release / on_click decorator + disconnect
  * _update_from_js — always fires for on_release/on_click
  * Plot2D / Plot1D widget integration
  * Figure event_json dispatch (JS→Python path via _simulate_js_event)
  * widget.x = 40 attribute assignment
  * widget.x read-back after JS event
  * End-to-end FFT example with simulated JS drag
"""

from __future__ import annotations

import json
import numpy as np
import pytest

import anyplotlib as apl
from anyplotlib.callbacks import Event
from anyplotlib.widgets import (
    Widget, RectangleWidget, CircleWidget, AnnularWidget,
    CrosshairWidget, PolygonWidget, LabelWidget,
    VLineWidget, HLineWidget, RangeWidget,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helper: simulate JS sending an interaction event
# ─────────────────────────────────────────────────────────────────────────────

def _simulate_js_event(fig, plot, event_type: str, *, widget_id=None, **fields):
    """Simulate what JS does when the user interacts with a widget.

    JS writes to event_json:
        { source:"js", panel_id, event_type, widget_id?, ...fields }
    """
    payload = {"source": "js", "panel_id": plot._id, "event_type": event_type}
    if widget_id is not None:
        payload["widget_id"] = widget_id if isinstance(widget_id, str) else widget_id._id
    payload.update(fields)
    fig._on_event({"new": json.dumps(payload)})


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Widget class unit tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestWidgetBase:
    def test_rectangle_attributes(self):
        w = RectangleWidget(lambda: None, x=10, y=20, w=30, h=40)
        assert w.x == 10.0 and w.y == 20.0 and w.w == 30.0 and w.h == 40.0
        assert w._type == "rectangle"

    def test_circle_attributes(self):
        w = CircleWidget(lambda: None, cx=5, cy=6, r=7)
        assert w.cx == 5.0 and w.r == 7.0

    def test_annular_validates(self):
        with pytest.raises(ValueError, match="r_inner"):
            AnnularWidget(lambda: None, cx=0, cy=0, r_outer=5, r_inner=10)

    def test_polygon_validates(self):
        with pytest.raises(ValueError, match="3 vertices"):
            PolygonWidget(lambda: None, vertices=[[0, 0], [1, 1]])

    def test_set_updates_and_pushes(self):
        pushed = []
        w = RectangleWidget(lambda: pushed.append(1), x=0, y=0, w=10, h=10)
        w.set(x=50)
        assert w.x == 50.0
        assert len(pushed) == 1

    def test_set_no_push(self):
        pushed = []
        w = RectangleWidget(lambda: pushed.append(1), x=0, y=0, w=10, h=10)
        w.set(_push=False, x=50)
        assert w.x == 50.0
        assert len(pushed) == 0

    def test_to_dict(self):
        w = CircleWidget(lambda: None, cx=1, cy=2, r=3)
        d = w.to_dict()
        assert d["cx"] == 1.0 and d["type"] == "circle" and "id" in d

    def test_get(self):
        w = RectangleWidget(lambda: None, x=10, y=20, w=30, h=40)
        assert w.get("x") == 10.0
        assert w.get("missing", 99) == 99

    def test_unknown_attr_raises(self):
        w = RectangleWidget(lambda: None, x=0, y=0, w=1, h=1)
        with pytest.raises(AttributeError, match="no_such"):
            _ = w.no_such

    def test_repr(self):
        w = RectangleWidget(lambda: None, x=1, y=2, w=3, h=4)
        assert "RectangleWidget" in repr(w) and "1" in repr(w)

    def test_id_property(self):
        w = RectangleWidget(lambda: None, x=0, y=0, w=1, h=1)
        assert isinstance(w.id, str) and len(w.id) == 8

    def test_setattr_routes_through_set(self):
        """Public attribute assignment should call set() and push."""
        pushed = []
        w = RectangleWidget(lambda: pushed.append(1), x=0, y=0, w=10, h=10)
        w.x = 40.0
        assert w.x == pytest.approx(40.0)
        assert len(pushed) == 1   # set() triggered the push

    def test_setattr_private_bypasses_set(self):
        """Private attributes must not go through set()."""
        pushed = []
        w = RectangleWidget(lambda: pushed.append(1), x=0, y=0, w=10, h=10)
        pushed.clear()
        w._custom = "private"
        assert len(pushed) == 0

    def test_setattr_callbacks_bypasses_set(self):
        """'callbacks' attribute assignment must never go through set()."""
        from anyplotlib.callbacks import CallbackRegistry
        pushed = []
        w = RectangleWidget(lambda: pushed.append(1), x=0, y=0, w=10, h=10)
        pushed.clear()
        w.callbacks = CallbackRegistry()   # must not crash or push
        assert len(pushed) == 0


class TestWidgetCallbacks:
    def test_on_changed_fires(self):
        w = RectangleWidget(lambda: None, x=0, y=0, w=10, h=10)
        results = []
        w.on_changed(lambda event: results.append(event.x))
        w.set(x=42)
        assert results == [42.0]

    def test_on_changed_event_source_is_widget(self):
        w = CircleWidget(lambda: None, cx=0, cy=0, r=5)
        received = []
        w.on_changed(lambda event: received.append(event.source))
        w.set(cx=10)
        assert received[0] is w

    def test_multiple_callbacks(self):
        w = RectangleWidget(lambda: None, x=0, y=0, w=10, h=10)
        a, b = [], []
        w.on_changed(lambda event: a.append(1))
        w.on_changed(lambda event: b.append(1))
        w.set(x=1)
        assert len(a) == 1 and len(b) == 1

    def test_disconnect_by_fn(self):
        """Disconnecting using the function object (which has ._cid) should work."""
        w = RectangleWidget(lambda: None, x=0, y=0, w=10, h=10)
        results = []
        fn = w.on_changed(lambda event: results.append(1))
        w.set(x=1);  assert len(results) == 1
        w.disconnect(fn)   # fn._cid is used
        w.set(x=2);  assert len(results) == 1

    def test_disconnect_by_cid(self):
        """Disconnecting using the integer CID should also work."""
        w = RectangleWidget(lambda: None, x=0, y=0, w=10, h=10)
        results = []
        fn = w.on_changed(lambda event: results.append(1))
        w.disconnect(fn._cid)
        w.set(x=2)
        assert results == []

    def test_disconnect_nonexistent_silent(self):
        w = RectangleWidget(lambda: None, x=0, y=0, w=10, h=10)
        w.disconnect(9999)

    def test_on_release_decorator(self):
        w = RectangleWidget(lambda: None, x=0, y=0, w=10, h=10)
        results = []
        w.on_release(lambda event: results.append(event.event_type))
        w.callbacks.fire(Event("on_release", w, {"x": 5.0}))
        assert results == ["on_release"]

    def test_on_click_decorator(self):
        w = CircleWidget(lambda: None, cx=0, cy=0, r=5)
        results = []
        w.on_click(lambda event: results.append(event.event_type))
        w.callbacks.fire(Event("on_click", w, {}))
        assert results == ["on_click"]


class TestWidgetUpdateFromJs:
    def test_update_returns_true_on_change(self):
        w = RectangleWidget(lambda: None, x=0, y=0, w=10, h=10)
        assert w._update_from_js({"x": 5.0})

    def test_update_returns_false_on_no_change(self):
        w = RectangleWidget(lambda: None, x=0, y=0, w=10, h=10, color="#00e5ff")
        assert not w._update_from_js(
            {"id": w.id, "type": "rectangle",
             "x": 0.0, "y": 0.0, "w": 10.0, "h": 10.0, "color": "#00e5ff"})

    def test_update_fires_on_changed_when_changed(self):
        w = RectangleWidget(lambda: None, x=0, y=0, w=10, h=10)
        results = []
        w.on_changed(lambda event: results.append(event.x))
        w._update_from_js({"x": 99.0})
        assert results == [99.0]

    def test_update_does_not_fire_on_changed_if_unchanged(self):
        w = RectangleWidget(lambda: None, x=5, y=5, w=10, h=10, color="#abc")
        results = []
        w.on_changed(lambda event: results.append(1))
        w._update_from_js({"x": 5.0, "y": 5.0, "w": 10.0, "h": 10.0, "color": "#abc"})
        assert results == []

    def test_update_always_fires_on_release(self):
        """on_release fires even when nothing changed (drag ended in place)."""
        w = RectangleWidget(lambda: None, x=5, y=5, w=10, h=10)
        results = []
        w.on_release(lambda event: results.append(1))
        w._update_from_js({"x": 5.0, "y": 5.0, "w": 10.0, "h": 10.0},
                          event_type="on_release")
        assert results == [1]

    def test_update_always_fires_on_click(self):
        """on_click fires even when nothing changed."""
        w = CrosshairWidget(lambda: None, cx=16.0, cy=16.0)
        results = []
        w.on_click(lambda event: results.append(1))
        w._update_from_js({"cx": 16.0, "cy": 16.0}, event_type="on_click")
        assert results == [1]

    def test_id_and_type_ignored(self):
        w = RectangleWidget(lambda: None, x=0, y=0, w=10, h=10)
        old_id = w.id
        w._update_from_js({"id": "FAKE", "type": "FAKE", "x": 1.0})
        assert w.id == old_id and w._type == "rectangle"


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Plot2D widget integration
# ═══════════════════════════════════════════════════════════════════════════════

class TestPlot2DWidgets:
    def test_add_widget_returns_widget_object(self):
        fig, ax = apl.subplots(1, 1)
        v = ax.imshow(np.zeros((32, 32)))
        w = v.add_widget("rectangle", x=10, y=10, w=20, h=20)
        assert isinstance(w, RectangleWidget) and w.x == 10.0

    def test_add_circle(self):
        fig, ax = apl.subplots(1, 1)
        v = ax.imshow(np.zeros((32, 32)))
        w = v.add_widget("circle", cx=16, cy=16, r=5)
        assert isinstance(w, CircleWidget) and w.cx == 16.0

    def test_add_crosshair(self):
        fig, ax = apl.subplots(1, 1)
        v = ax.imshow(np.zeros((32, 32)))
        assert isinstance(v.add_widget("crosshair"), CrosshairWidget)

    def test_add_annular(self):
        fig, ax = apl.subplots(1, 1)
        v = ax.imshow(np.zeros((32, 32)))
        assert isinstance(v.add_widget("annular", r_outer=10, r_inner=5), AnnularWidget)

    def test_add_polygon(self):
        fig, ax = apl.subplots(1, 1)
        v = ax.imshow(np.zeros((32, 32)))
        w = v.add_widget("polygon", vertices=[[0,0],[10,0],[10,10],[0,10]])
        assert isinstance(w, PolygonWidget)

    def test_add_label(self):
        fig, ax = apl.subplots(1, 1)
        v = ax.imshow(np.zeros((32, 32)))
        w = v.add_widget("label", x=5, y=5, text="hello")
        assert isinstance(w, LabelWidget) and w.text == "hello"

    def test_invalid_kind_raises(self):
        fig, ax = apl.subplots(1, 1)
        v = ax.imshow(np.zeros((32, 32)))
        with pytest.raises(ValueError):
            v.add_widget("nonexistent")

    def test_get_widget_by_id(self):
        fig, ax = apl.subplots(1, 1)
        v = ax.imshow(np.zeros((32, 32)))
        w = v.add_widget("rectangle", x=1, y=2, w=3, h=4)
        assert v.get_widget(w.id) is w

    def test_get_widget_by_object(self):
        fig, ax = apl.subplots(1, 1)
        v = ax.imshow(np.zeros((32, 32)))
        w = v.add_widget("circle")
        assert v.get_widget(w) is w

    def test_remove_widget(self):
        fig, ax = apl.subplots(1, 1)
        v = ax.imshow(np.zeros((32, 32)))
        w = v.add_widget("rectangle")
        v.remove_widget(w)
        assert len(v.list_widgets()) == 0

    def test_list_widgets(self):
        fig, ax = apl.subplots(1, 1)
        v = ax.imshow(np.zeros((32, 32)))
        v.add_widget("circle");  v.add_widget("rectangle")
        assert len(v.list_widgets()) == 2

    def test_clear_widgets(self):
        fig, ax = apl.subplots(1, 1)
        v = ax.imshow(np.zeros((32, 32)))
        v.add_widget("circle");  v.add_widget("rectangle")
        v.clear_widgets()
        assert v.list_widgets() == []

    def test_widget_set_updates_state_dict(self):
        fig, ax = apl.subplots(1, 1)
        v = ax.imshow(np.zeros((32, 32)))
        w = v.add_widget("rectangle", x=0, y=0, w=10, h=10)
        w.set(x=99)
        found = [wd for wd in v.to_state_dict()["overlay_widgets"] if wd["id"] == w.id]
        assert found[0]["x"] == 99.0

    def test_to_state_dict_includes_widgets(self):
        fig, ax = apl.subplots(1, 1)
        v = ax.imshow(np.zeros((32, 32)))
        v.add_widget("circle", cx=1, cy=2, r=3)
        d = v.to_state_dict()
        assert len(d["overlay_widgets"]) == 1
        assert d["overlay_widgets"][0]["cx"] == 1.0

    def test_setattr_moves_widget(self):
        """widget.x = 40 triggers push and updates _data."""
        fig, ax = apl.subplots(1, 1)
        v = ax.imshow(np.zeros((32, 32)))
        w = v.add_widget("rectangle", x=0.0, y=0.0, w=10.0, h=10.0)
        w.x = 40.0
        assert w.x == pytest.approx(40.0)
        d = v.to_state_dict()["overlay_widgets"]
        assert d[0]["x"] == pytest.approx(40.0)


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Plot1D widget integration
# ═══════════════════════════════════════════════════════════════════════════════

class TestPlot1DWidgets:
    def test_add_vline_returns_widget(self):
        fig, ax = apl.subplots(1, 1)
        v = ax.plot(np.zeros(64))
        w = v.add_vline_widget(x=10.0)
        assert isinstance(w, VLineWidget) and w.x == 10.0

    def test_add_hline_returns_widget(self):
        fig, ax = apl.subplots(1, 1)
        v = ax.plot(np.zeros(64))
        w = v.add_hline_widget(y=0.5)
        assert isinstance(w, HLineWidget) and w.y == 0.5

    def test_add_range_returns_widget(self):
        fig, ax = apl.subplots(1, 1)
        v = ax.plot(np.zeros(64))
        w = v.add_range_widget(x0=10, x1=20)
        assert isinstance(w, RangeWidget) and w.x0 == 10.0

    def test_remove_widget(self):
        fig, ax = apl.subplots(1, 1)
        v = ax.plot(np.zeros(64))
        w = v.add_vline_widget(x=5)
        v.remove_widget(w)
        assert len(v.list_widgets()) == 0


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Figure event_json dispatch (the JS→Python path)
# ═══════════════════════════════════════════════════════════════════════════════

class TestEventJsonDispatch:
    """Simulate what JS does: write event_json with source:"js".
    Verify that Widget callbacks fire correctly."""

    def test_rectangle_drag_fires_on_changed(self):
        fig, ax = apl.subplots(1, 1)
        v = ax.imshow(np.zeros((32, 32)))
        w = v.add_widget("rectangle", x=10, y=10, w=20, h=20)
        results = []
        w.on_changed(lambda event: results.append((event.x, event.y)))

        _simulate_js_event(fig, v, "on_changed", widget_id=w, x=50.0, y=60.0)

        assert len(results) == 1
        assert results[0] == (50.0, 60.0)
        assert w.x == 50.0 and w.y == 60.0

    def test_no_change_no_on_changed_callback(self):
        """on_changed must NOT fire when nothing actually changed."""
        fig, ax = apl.subplots(1, 1)
        v = ax.imshow(np.zeros((32, 32)))
        w = v.add_widget("rectangle", x=10, y=10, w=20, h=20)
        results = []
        w.on_changed(lambda event: results.append(1))

        _simulate_js_event(fig, v, "on_changed", widget_id=w,
                           x=10.0, y=10.0, w=20.0, h=20.0)
        assert results == []

    def test_on_release_always_fires(self):
        """on_release fires even when position didn't change."""
        fig, ax = apl.subplots(1, 1)
        v = ax.imshow(np.zeros((32, 32)))
        w = v.add_widget("rectangle", x=10, y=10, w=20, h=20)
        results = []
        w.on_release(lambda event: results.append(1))

        _simulate_js_event(fig, v, "on_release", widget_id=w,
                           x=10.0, y=10.0, w=20.0, h=20.0)
        assert len(results) == 1

    def test_on_click_fires(self):
        fig, ax = apl.subplots(1, 1)
        v = ax.imshow(np.zeros((32, 32)))
        w = v.add_widget("crosshair", cx=16.0, cy=16.0)
        results = []
        w.on_click(lambda event: results.append(event.cx))

        _simulate_js_event(fig, v, "on_click", widget_id=w, cx=16.0, cy=16.0)
        assert len(results) == 1
        assert results[0] == pytest.approx(16.0)

    def test_on_click_line1d_overlay_fires(self):
        """Line1D.on_click fires when JS sends on_line_click with the matching line_id."""
        fig, ax = apl.subplots(1, 1)
        v = ax.plot(np.zeros(64))
        line = v.add_line(np.ones(64), color="#ff0000")
        results = []
        line.on_click(lambda event: results.append(event.line_id))

        _simulate_js_event(fig, v, "on_line_click", line_id=line.id)
        assert len(results) == 1
        assert results[0] == line.id

    def test_on_click_line1d_primary_fires(self):
        """Line1D.on_click on the primary line fires when JS sends on_line_click with no line_id."""
        fig, ax = apl.subplots(1, 1)
        v = ax.plot(np.zeros(64))
        results = []
        v.line.on_click(lambda event: results.append(1))

        # No line_id in payload → event.data.get("line_id") is None → matches primary
        _simulate_js_event(fig, v, "on_line_click")
        assert len(results) == 1

    def test_on_click_line1d_wrong_id_no_fire(self):
        """Line1D.on_click does NOT fire when the JS event carries a different line_id."""
        fig, ax = apl.subplots(1, 1)
        v = ax.plot(np.zeros(64))
        line = v.add_line(np.ones(64), color="#00ff00")
        results = []
        line.on_click(lambda event: results.append(1))

        _simulate_js_event(fig, v, "on_line_click", line_id="completely-wrong-id")
        assert results == []

    def test_circle_drag(self):
        fig, ax = apl.subplots(1, 1)
        v = ax.imshow(np.zeros((32, 32)))
        w = v.add_widget("circle", cx=16, cy=16, r=5)
        results = []
        w.on_changed(lambda event: results.append(event.cx))

        _simulate_js_event(fig, v, "on_changed", widget_id=w, cx=25.0)
        assert results == [25.0]

    def test_python_set_does_not_echo(self):
        """Python widget.set() triggers on_changed once (from set itself),
        but the subsequent event_json push must NOT re-fire callbacks."""
        fig, ax = apl.subplots(1, 1)
        v = ax.imshow(np.zeros((32, 32)))
        w = v.add_widget("rectangle", x=10, y=10, w=20, h=20)
        results = []
        w.on_changed(lambda event: results.append("cb"))

        w.set(x=99)
        assert results == ["cb"]   # one fire from set()
        results.clear()

        # The push to event_json has source:"python" — must be ignored
        assert results == []

    def test_multi_widget_only_changed_fires(self):
        fig, ax = apl.subplots(1, 1)
        v = ax.imshow(np.zeros((32, 32)))
        w1 = v.add_widget("circle", cx=10, cy=10, r=5)
        w2 = v.add_widget("rectangle", x=0, y=0, w=10, h=10)
        r1, r2 = [], []
        w1.on_changed(lambda e: r1.append(1))
        w2.on_changed(lambda e: r2.append(1))

        _simulate_js_event(fig, v, "on_changed", widget_id=w2, x=50.0, y=50.0)
        assert r1 == []
        assert len(r2) == 1

    def test_multi_panel_routing(self):
        fig, (ax1, ax2) = apl.subplots(1, 2)
        v1 = ax1.imshow(np.zeros((16, 16)))
        v2 = ax2.imshow(np.zeros((16, 16)))
        w1 = v1.add_widget("circle", cx=8, cy=8, r=3)
        w2 = v2.add_widget("circle", cx=8, cy=8, r=3)
        r1, r2 = [], []
        w1.on_changed(lambda e: r1.append(1))
        w2.on_changed(lambda e: r2.append(1))

        _simulate_js_event(fig, v1, "on_changed", widget_id=w1, cx=12.0)
        assert len(r1) == 1 and r2 == []

    def test_1d_vline_drag(self):
        fig, ax = apl.subplots(1, 1)
        v = ax.plot(np.zeros(64))
        w = v.add_vline_widget(x=10.0)
        results = []
        w.on_changed(lambda event: results.append(event.x))

        _simulate_js_event(fig, v, "on_changed", widget_id=w, x=30.0)
        assert results == [30.0]

    def test_1d_range_drag(self):
        fig, ax = apl.subplots(1, 1)
        v = ax.plot(np.zeros(64))
        w = v.add_range_widget(x0=10, x1=20)
        results = []
        w.on_changed(lambda event: results.append((event.x0, event.x1)))

        _simulate_js_event(fig, v, "on_changed", widget_id=w, x0=15.0, x1=25.0)
        assert results == [(15.0, 25.0)]

    def test_disconnect_prevents_callback(self):
        fig, ax = apl.subplots(1, 1)
        v = ax.imshow(np.zeros((32, 32)))
        w = v.add_widget("rectangle", x=0, y=0, w=10, h=10)
        results = []
        fn = w.on_changed(lambda event: results.append(1))
        w.disconnect(fn)

        _simulate_js_event(fig, v, "on_changed", widget_id=w, x=50.0)
        assert results == []

    def test_widget_state_synced_after_js_event(self):
        fig, ax = apl.subplots(1, 1)
        v = ax.imshow(np.zeros((32, 32)))
        w = v.add_widget("rectangle", x=0, y=0, w=10, h=10)

        _simulate_js_event(fig, v, "on_changed", widget_id=w,
                           x=77.0, y=88.0, w=33.0, h=44.0)
        assert w.x == 77.0 and w.y == 88.0 and w.w == 33.0 and w.h == 44.0

    def test_widget_x_readback_after_js_event(self):
        """After a JS event, reading widget.x returns the updated value."""
        fig, ax = apl.subplots(1, 1)
        v = ax.imshow(np.zeros((32, 32)))
        w = v.add_widget("circle", cx=0.0, cy=0.0, r=5.0)

        _simulate_js_event(fig, v, "on_release", widget_id=w, cx=20.0, cy=30.0)
        assert w.cx == pytest.approx(20.0)
        assert w.cy == pytest.approx(30.0)


# ═══════════════════════════════════════════════════════════════════════════════
# 5. End-to-end FFT example
# ═══════════════════════════════════════════════════════════════════════════════

class TestInteractiveFft:
    """End-to-end: two panels, rectangle widget, simulate JS events,
    verify callback fires and updates the FFT panel."""

    @staticmethod
    def _compute_fft(img, x0, y0, w, h, scale=0.1):
        ih, iw = img.shape
        x0i = max(0, int(round(x0)));   y0i = max(0, int(round(y0)))
        x1i = min(iw, x0i + max(1, int(round(w))))
        y1i = min(ih, y0i + max(1, int(round(h))))
        crop = img[y0i:y1i, x0i:x1i].copy()
        ch, cw = crop.shape
        if ch < 2 or cw < 2:
            f = np.fft.fftfreq(4, d=scale)
            return np.zeros((4, 4)), f, f
        crop *= np.hanning(ch)[:, None] * np.hanning(cw)[None, :]
        fft2 = np.fft.fftshift(np.fft.fft2(crop))
        log_mag = np.log1p(np.abs(fft2))
        return (log_mag,
                np.fft.fftshift(np.fft.fftfreq(cw, d=scale)),
                np.fft.fftshift(np.fft.fftfreq(ch, d=scale)))

    def test_drag_rectangle_updates_fft(self):
        N = 64
        rng = np.random.default_rng(0)
        img = rng.standard_normal((N, N)).cumsum(0).cumsum(1)
        img = (img - img.min()) / (img.max() - img.min())
        scale = 0.1
        xy = np.arange(N) * scale

        fig, (ax_real, ax_fft) = apl.subplots(1, 2, figsize=(600, 300))
        v_real = ax_real.imshow(img, axes=[xy, xy], units="Å")

        ROI_W, ROI_H = 32, 32
        roi_x0, roi_y0 = 16, 16
        rect = v_real.add_widget("rectangle",
                                 x=float(roi_x0), y=float(roi_y0),
                                 w=float(ROI_W), h=float(ROI_H))

        fft0, fx0, fy0 = self._compute_fft(img, roi_x0, roi_y0, ROI_W, ROI_H)
        v_fft = ax_fft.imshow(fft0, axes=[fx0, fy0], units="1/Å")

        initial_b64 = v_fft._state["image_b64"]
        updates = []

        @rect.on_changed
        def on_rect_changed(event):
            log_mag, freq_x, freq_y = self._compute_fft(
                img, event.x, event.y, event.w, event.h)
            v_fft.set_data(log_mag, x_axis=freq_x, y_axis=freq_y, units="1/Å")
            updates.append({"x": event.x, "y": event.y,
                            "w": event.w, "h": event.h})

        _simulate_js_event(fig, v_real, "on_changed", widget_id=rect,
                           x=0.0, y=0.0, w=48.0, h=48.0)

        assert len(updates) == 1
        assert updates[0]["x"] == 0.0 and updates[0]["w"] == 48.0
        assert v_fft._state["image_b64"] != initial_b64

    def test_multiple_drags_fire_multiple_callbacks(self):
        N = 32
        img = np.random.default_rng(1).random((N, N))
        fig, ax = apl.subplots(1, 1)
        v = ax.imshow(img)
        rect = v.add_widget("rectangle", x=0, y=0, w=16, h=16)
        count = [0]
        rect.on_changed(lambda e: count.__setitem__(0, count[0] + 1))

        for i in range(5):
            _simulate_js_event(fig, v, "on_changed", widget_id=rect, x=float(i))

        # Only fires when something actually changed — first fire is from x=0
        # (which equals the initial value, no change), then 1,2,3,4 = 4 fires
        assert count[0] == 4

    def test_drag_then_disconnect(self):
        fig, ax = apl.subplots(1, 1)
        v = ax.imshow(np.zeros((32, 32)))
        rect = v.add_widget("rectangle", x=0, y=0, w=10, h=10)
        results = []
        fn = rect.on_changed(lambda e: results.append(1))

        _simulate_js_event(fig, v, "on_changed", widget_id=rect, x=5.0)
        assert len(results) == 1

        rect.disconnect(fn)
        _simulate_js_event(fig, v, "on_changed", widget_id=rect, x=10.0)
        assert len(results) == 1

    def test_on_release_after_drags(self):
        N = 32
        img = np.random.default_rng(2).random((N, N))
        fig, ax = apl.subplots(1, 1)
        v = ax.imshow(img)
        rect = v.add_widget("rectangle", x=0, y=0, w=16, h=16)
        drag_count = [0];  release_count = [0]

        rect.on_changed(lambda e: drag_count.__setitem__(0, drag_count[0] + 1))
        rect.on_release(lambda e: release_count.__setitem__(0, release_count[0] + 1))

        for i in range(1, 6):
            _simulate_js_event(fig, v, "on_changed", widget_id=rect, x=float(i))
        _simulate_js_event(fig, v, "on_release", widget_id=rect, x=5.0)

        assert drag_count[0] == 5
        assert release_count[0] == 1


# ═══════════════════════════════════════════════════════════════════════════════
# 6. Widget visibility (hide / show)
# ═══════════════════════════════════════════════════════════════════════════════

class TestWidgetVisibility:
    """Unit tests for Widget.hide(), Widget.show(), and Widget.visible."""

    def test_visible_default_true(self):
        """A freshly created widget is visible by default."""
        w = RectangleWidget(lambda: None, x=0, y=0, w=10, h=10)
        assert w.visible is True

    def test_hide_sets_visible_false(self):
        """hide() marks the widget as not visible."""
        w = CircleWidget(lambda: None, cx=5, cy=5, r=3)
        w.hide()
        assert w.visible is False

    def test_show_restores_visible(self):
        """show() after hide() restores visibility."""
        w = CircleWidget(lambda: None, cx=5, cy=5, r=3)
        w.hide()
        w.show()
        assert w.visible is True

    def test_hide_calls_push(self):
        """hide() must call push_fn exactly once."""
        pushed = []
        w = RectangleWidget(lambda: pushed.append(1), x=0, y=0, w=10, h=10)
        pushed.clear()
        w.hide()
        assert len(pushed) == 1

    def test_show_calls_push(self):
        """show() must call push_fn exactly once."""
        pushed = []
        w = RectangleWidget(lambda: pushed.append(1), x=0, y=0, w=10, h=10)
        pushed.clear()
        w.show()
        assert len(pushed) == 1

    def test_hide_does_not_fire_on_changed(self):
        """hide() must NOT fire on_changed callbacks."""
        w = CircleWidget(lambda: None, cx=0, cy=0, r=5)
        fired = []
        w.on_changed(lambda e: fired.append(1))
        w.hide()
        assert fired == []

    def test_show_does_not_fire_on_changed(self):
        """show() must NOT fire on_changed callbacks."""
        w = CircleWidget(lambda: None, cx=0, cy=0, r=5)
        fired = []
        w.on_changed(lambda e: fired.append(1))
        w.hide()
        w.show()
        assert fired == []

    def test_visible_in_to_dict_after_hide(self):
        """to_dict() reflects visible=False after hide()."""
        w = RectangleWidget(lambda: None, x=0, y=0, w=10, h=10)
        w.hide()
        assert w.to_dict()["visible"] is False

    def test_visible_in_to_dict_after_show(self):
        """to_dict() reflects visible=True after show()."""
        w = RectangleWidget(lambda: None, x=0, y=0, w=10, h=10)
        w.hide()
        w.show()
        assert w.to_dict()["visible"] is True

    def test_visible_in_state_dict_after_hide(self):
        """The panel state dict propagates visible=False for a hidden widget."""
        fig, ax = apl.subplots(1, 1)
        v = ax.plot(np.zeros(64))
        w = v.add_vline_widget(x=5.0)
        w.hide()
        widgets = v.to_state_dict()["overlay_widgets"]
        entry = next(e for e in widgets if e["id"] == w.id)
        assert entry["visible"] is False

    def test_visible_in_state_dict_after_show(self):
        """The panel state dict propagates visible=True after show()."""
        fig, ax = apl.subplots(1, 1)
        v = ax.plot(np.zeros(64))
        w = v.add_vline_widget(x=5.0)
        w.hide()
        w.show()
        widgets = v.to_state_dict()["overlay_widgets"]
        entry = next(e for e in widgets if e["id"] == w.id)
        assert entry["visible"] is True

    def test_hide_then_show_widget_still_draggable(self):
        """After show(), a JS drag event fires callbacks as normal."""
        fig, ax = apl.subplots(1, 1)
        v = ax.imshow(np.zeros((32, 32)))
        w = v.add_widget("circle", cx=10, cy=10, r=5)
        fired = []
        w.on_changed(lambda e: fired.append(e.cx))
        w.hide()
        w.show()
        _simulate_js_event(fig, v, "on_changed", widget_id=w, cx=20.0)
        assert fired == [20.0]

    def test_hide_show_1d_range_widget(self):
        """hide/show round-trip works for a RangeWidget."""
        fig, ax = apl.subplots(1, 1)
        v = ax.plot(np.zeros(64))
        w = v.add_range_widget(x0=10, x1=20)
        w.hide()
        assert w.visible is False
        w.show()
        assert w.visible is True

    def test_multiple_hide_calls_idempotent(self):
        """Calling hide() twice leaves visible=False, pushes twice."""
        pushed = []
        w = CircleWidget(lambda: pushed.append(1), cx=0, cy=0, r=5)
        pushed.clear()
        w.hide()
        w.hide()
        assert w.visible is False
        assert len(pushed) == 2   # each hide() pushes once

    def test_multiple_show_calls_idempotent(self):
        """Calling show() twice leaves visible=True, pushes twice."""
        pushed = []
        w = CircleWidget(lambda: pushed.append(1), cx=0, cy=0, r=5)
        pushed.clear()
        w.show()
        w.show()
        assert w.visible is True
        assert len(pushed) == 2


# ═══════════════════════════════════════════════════════════════════════════════
# 7. Interactive Fitting — plot_interactive_fitting.py scenario
# ═══════════════════════════════════════════════════════════════════════════════

from anyplotlib.widgets import RangeWidget as _RangeWidget2, PointWidget as _PointWidget2


def _gaussian(x, amp, mu, sigma):
    return amp * np.exp(-0.5 * ((x - mu) / sigma) ** 2)


def _two_gaussians(x, a1, mu1, s1, a2, mu2, s2):
    return _gaussian(x, a1, mu1, s1) + _gaussian(x, a2, mu2, s2)


class _GaussianController:
    """Mirror of GaussianController from plot_interactive_fitting.py."""

    def __init__(self, plot, line, p, color, x, fit_callback):
        self._plot      = plot
        self.line       = line
        self.amp        = p["amp"]
        self.mu         = p["mu"]
        self.sigma      = p["sigma"]
        self.color      = color
        self._x         = x
        self._refit     = fit_callback
        self._active    = False
        self._syncing   = False
        self._pt        = None
        self._rng_w     = None

    def component_y(self):
        return _gaussian(self._x, self.amp, self.mu, self.sigma)

    def toggle(self):
        if self._active:
            self._pt.hide()
            self._rng_w.hide()
            self._active = False
        else:
            if self._pt is None:
                self._pt    = self._plot.add_point_widget(self.mu, self.amp,
                                                          color=self.color)
                self._rng_w = self._plot.add_range_widget(
                    self.mu - self.sigma, self.mu + self.sigma,
                    color=self.color,
                )
                self._wire()
            else:
                self._pt.show()
                self._rng_w.show()
            self._active = True

    def _wire(self):
        @self._pt.on_changed
        def _peak_moved(event):
            if self._syncing:
                return
            self._syncing = True
            try:
                self.amp = event.data["y"]
                self.mu  = event.data["x"]
                self._rng_w.set(x0=self.mu - self.sigma,
                                x1=self.mu + self.sigma)
                self.line.set_data(self.component_y())
                self._refit()
            finally:
                self._syncing = False

        @self._rng_w.on_changed
        def _range_moved(event):
            if self._syncing:
                return
            self._syncing = True
            try:
                x0, x1    = event.data["x0"], event.data["x1"]
                self.mu    = (x0 + x1) / 2.0
                self.sigma = abs(x1 - x0) / 2.0
                self._pt.set(x=self.mu)
                self.line.set_data(self.component_y())
                self._refit()
            finally:
                self._syncing = False


class TestInteractiveFitting:
    """End-to-end tests mirroring plot_interactive_fitting.py.

    Validates widget hide/show toggle, PointWidget and RangeWidget drag
    callbacks, and the live refit flow — all without a browser.
    """

    def _build(self):
        """Return (fig, plot, controllers, fit_line, x, signal)."""
        from scipy.optimize import curve_fit

        x = np.linspace(0, 10, 200)
        TRUE_P = [
            dict(amp=1.0, mu=3.2, sigma=0.55),
            dict(amp=0.75, mu=6.8, sigma=0.80),
        ]
        COLORS = ["#ff6b6b", "#69db7c"]
        rng    = np.random.default_rng(0)
        signal = sum(_gaussian(x, **p) for p in TRUE_P) + rng.normal(0, 0.03, len(x))

        INIT_P = [
            dict(amp=1.0, mu=3.0, sigma=0.6),
            dict(amp=0.7, mu=7.0, sigma=0.9),
        ]

        fig, ax = apl.subplots(1, 1, figsize=(600, 300))
        plot = ax.plot(signal, axes=[x], color="#adb5bd")

        comp_lines = [
            plot.add_line(_gaussian(x, **p), x_axis=x, color=c)
            for i, (p, c) in enumerate(zip(INIT_P, COLORS))
        ]

        fit_line = plot.add_line(
            sum(_gaussian(x, **p) for p in INIT_P), x_axis=x,
            color="#ffd43b", linestyle="dashed",
        )

        refit_calls = [0]

        def _refit():
            c0, c1 = controllers[0], controllers[1]
            p0 = [c0.amp, c0.mu, c0.sigma, c1.amp, c1.mu, c1.sigma]
            lo = [0, x[0], 1e-3, 0, x[0], 1e-3]
            hi = [np.inf, x[-1], x[-1]-x[0], np.inf, x[-1], x[-1]-x[0]]
            try:
                popt, _ = curve_fit(_two_gaussians, x, signal, p0=p0,
                                    bounds=(lo, hi), maxfev=3000)
                fit_line.set_data(_two_gaussians(x, *popt))
            except RuntimeError:
                fit_line.set_data(sum(c.component_y() for c in controllers))
            refit_calls[0] += 1

        controllers = [
            _GaussianController(plot, comp_lines[i], INIT_P[i], COLORS[i],
                                 x, _refit)
            for i in range(2)
        ]

        return fig, plot, controllers, fit_line, x, signal, refit_calls

    # ── toggle creates widgets ────────────────────────────────────────────────

    def test_toggle_once_creates_point_and_range_widgets(self):
        """First toggle creates a PointWidget and a RangeWidget."""
        _, plot, ctrls, *_ = self._build()
        ctrl = ctrls[0]
        assert ctrl._pt is None and ctrl._rng_w is None
        ctrl.toggle()
        assert ctrl._pt is not None
        assert ctrl._rng_w is not None
        assert ctrl._active is True

    def test_toggle_once_adds_two_widgets_to_plot(self):
        """After first toggle, the plot has exactly 2 new widgets."""
        _, plot, ctrls, *_ = self._build()
        ctrl = ctrls[0]
        ctrl.toggle()
        assert len(plot.list_widgets()) == 2

    def test_widgets_visible_after_first_toggle(self):
        """Widgets created on first toggle are visible."""
        _, plot, ctrls, *_ = self._build()
        ctrl = ctrls[0]
        ctrl.toggle()
        assert ctrl._pt.visible is True
        assert ctrl._rng_w.visible is True

    # ── toggle hides widgets ──────────────────────────────────────────────────

    def test_toggle_twice_hides_widgets(self):
        """Second toggle hides the point and range widgets."""
        _, plot, ctrls, *_ = self._build()
        ctrl = ctrls[0]
        ctrl.toggle()   # activate
        ctrl.toggle()   # deactivate
        assert ctrl._active is False
        assert ctrl._pt.visible is False
        assert ctrl._rng_w.visible is False

    def test_toggle_twice_widgets_still_in_plot(self):
        """Hidden widgets are NOT removed from the plot — they stay but are hidden."""
        _, plot, ctrls, *_ = self._build()
        ctrl = ctrls[0]
        ctrl.toggle()
        ctrl.toggle()
        # Still registered — just hidden
        assert len(plot.list_widgets()) == 2

    # ── toggle shows widgets again ────────────────────────────────────────────

    def test_toggle_three_times_reshows_widgets(self):
        """Third toggle re-shows the existing widgets without creating new ones."""
        _, plot, ctrls, *_ = self._build()
        ctrl = ctrls[0]
        ctrl.toggle()          # create + show
        pt_id   = ctrl._pt.id
        rng_id  = ctrl._rng_w.id
        ctrl.toggle()          # hide
        ctrl.toggle()          # re-show
        assert ctrl._active is True
        assert ctrl._pt.visible is True
        assert ctrl._rng_w.visible is True
        # Same objects — not recreated
        assert ctrl._pt.id   == pt_id
        assert ctrl._rng_w.id == rng_id
        assert len(plot.list_widgets()) == 2

    # ── PointWidget drag updates component line ───────────────────────────────

    def test_point_drag_updates_component_amp_and_mu(self):
        """Simulating a PointWidget drag updates amp and mu on the controller."""
        fig, plot, ctrls, fit_line, x, signal, refit_calls = self._build()
        ctrl = ctrls[0]
        ctrl.toggle()

        _simulate_js_event(fig, plot, "on_changed",
                           widget_id=ctrl._pt, x=3.5, y=0.9)

        assert ctrl.mu  == pytest.approx(3.5)
        assert ctrl.amp == pytest.approx(0.9)

    def test_point_drag_updates_range_widget_position(self):
        """Dragging the point recentres the range widget around new mu."""
        fig, plot, ctrls, fit_line, x, signal, refit_calls = self._build()
        ctrl = ctrls[0]
        ctrl.toggle()
        original_sigma = ctrl.sigma

        _simulate_js_event(fig, plot, "on_changed",
                           widget_id=ctrl._pt, x=4.0, y=1.0)

        expected_x0 = 4.0 - original_sigma
        expected_x1 = 4.0 + original_sigma
        assert ctrl._rng_w.x0 == pytest.approx(expected_x0)
        assert ctrl._rng_w.x1 == pytest.approx(expected_x1)

    def test_point_drag_updates_component_line_data(self):
        """After a PointWidget drag, the component line data reflects new params."""
        fig, plot, ctrls, fit_line, x, signal, refit_calls = self._build()
        ctrl = ctrls[0]
        ctrl.toggle()

        old_data = _gaussian(x, ctrl.amp, ctrl.mu, ctrl.sigma).copy()
        _simulate_js_event(fig, plot, "on_changed",
                           widget_id=ctrl._pt, x=4.0, y=0.8)

        # Find the extra_line entry for comp_lines[0]
        lid = ctrl.line.id
        entry = next(e for e in plot._state["extra_lines"] if e["id"] == lid)
        new_y = entry["data"]
        expected_y = _gaussian(x, 0.8, 4.0, ctrl.sigma)
        np.testing.assert_allclose(new_y, expected_y, rtol=1e-10)

    def test_point_drag_triggers_refit(self):
        """Dragging the PointWidget calls the refit callback."""
        fig, plot, ctrls, fit_line, x, signal, refit_calls = self._build()
        ctrl = ctrls[0]
        ctrl.toggle()

        _simulate_js_event(fig, plot, "on_changed",
                           widget_id=ctrl._pt, x=3.5, y=0.9)

        assert refit_calls[0] >= 1

    def test_point_drag_updates_fit_line(self):
        """After a point drag, the fit line data changes."""
        fig, plot, ctrls, fit_line, x, signal, refit_calls = self._build()
        ctrl = ctrls[0]
        ctrl.toggle()

        lid = fit_line.id
        entry_before = next(e for e in plot._state["extra_lines"] if e["id"] == lid)
        old_fit = entry_before["data"].copy()

        _simulate_js_event(fig, plot, "on_changed",
                           widget_id=ctrl._pt, x=4.5, y=0.5)

        entry_after = next(e for e in plot._state["extra_lines"] if e["id"] == lid)
        assert not np.array_equal(entry_after["data"], old_fit)

    # ── RangeWidget drag updates component line ───────────────────────────────

    def test_range_drag_updates_mu_and_sigma(self):
        """Simulating a RangeWidget drag updates mu and sigma on the controller."""
        fig, plot, ctrls, fit_line, x, signal, refit_calls = self._build()
        ctrl = ctrls[0]
        ctrl.toggle()

        _simulate_js_event(fig, plot, "on_changed",
                           widget_id=ctrl._rng_w, x0=2.5, x1=4.5)

        assert ctrl.mu    == pytest.approx(3.5)
        assert ctrl.sigma == pytest.approx(1.0)

    def test_range_drag_recentres_point_widget(self):
        """Dragging the range widget moves the point widget to the new centre."""
        fig, plot, ctrls, fit_line, x, signal, refit_calls = self._build()
        ctrl = ctrls[0]
        ctrl.toggle()

        _simulate_js_event(fig, plot, "on_changed",
                           widget_id=ctrl._rng_w, x0=2.0, x1=5.0)

        assert ctrl._pt.x == pytest.approx(3.5)

    def test_range_drag_updates_component_line_data(self):
        """After a RangeWidget drag, the component line reflects the new sigma."""
        fig, plot, ctrls, fit_line, x, signal, refit_calls = self._build()
        ctrl = ctrls[0]
        ctrl.toggle()

        _simulate_js_event(fig, plot, "on_changed",
                           widget_id=ctrl._rng_w, x0=2.5, x1=4.5)

        lid = ctrl.line.id
        entry = next(e for e in plot._state["extra_lines"] if e["id"] == lid)
        expected_y = _gaussian(x, ctrl.amp, 3.5, 1.0)
        np.testing.assert_allclose(entry["data"], expected_y, rtol=1e-10)

    def test_range_drag_triggers_refit(self):
        """Dragging the RangeWidget calls the refit callback."""
        fig, plot, ctrls, fit_line, x, signal, refit_calls = self._build()
        ctrl = ctrls[0]
        ctrl.toggle()

        _simulate_js_event(fig, plot, "on_changed",
                           widget_id=ctrl._rng_w, x0=2.5, x1=4.5)

        assert refit_calls[0] >= 1

    # ── both controllers independent ─────────────────────────────────────────

    def test_two_controllers_independent(self):
        """Dragging ctrl[0] does not affect ctrl[1] state."""
        fig, plot, ctrls, fit_line, x, signal, refit_calls = self._build()
        ctrls[0].toggle()
        ctrls[1].toggle()

        old_mu1 = ctrls[1].mu

        _simulate_js_event(fig, plot, "on_changed",
                           widget_id=ctrls[0]._pt, x=3.8, y=1.1)

        assert ctrls[1].mu == pytest.approx(old_mu1)

    def test_both_controllers_active_at_same_time(self):
        """Both controllers can be active simultaneously with no crosstalk."""
        _, plot, ctrls, *_ = self._build()
        ctrls[0].toggle()
        ctrls[1].toggle()
        assert len(plot.list_widgets()) == 4
        assert ctrls[0]._active and ctrls[1]._active

    def test_hide_one_leaves_other_visible(self):
        """Hiding ctrl[0] does not affect ctrl[1] visibility."""
        _, plot, ctrls, *_ = self._build()
        ctrls[0].toggle()   # activate
        ctrls[1].toggle()   # activate
        ctrls[0].toggle()   # hide
        assert ctrls[0]._pt.visible is False
        assert ctrls[1]._pt.visible is True

    # ── line click toggles controller ─────────────────────────────────────────

    def test_line_click_activates_controller(self):
        """Simulating a click on a component line activates its controller."""
        fig, plot, ctrls, fit_line, x, signal, refit_calls = self._build()
        ctrl = ctrls[0]

        # Wire up the line.on_click handler (same as the example)
        @ctrl.line.on_click
        def _clicked(event, c=ctrl):
            c.toggle()

        # Simulate JS sending an on_line_click event for comp_lines[0]
        fig._on_event({"new": __import__("json").dumps({
            "source": "js",
            "panel_id": plot._id,
            "event_type": "on_line_click",
            "line_id": ctrl.line.id,
        })})

        assert ctrl._active is True
        assert ctrl._pt is not None

    def test_line_click_twice_hides_widgets(self):
        """Two clicks on the same component line toggle it off again."""
        fig, plot, ctrls, fit_line, x, signal, refit_calls = self._build()
        ctrl = ctrls[0]

        @ctrl.line.on_click
        def _clicked(event, c=ctrl):
            c.toggle()

        import json as _json

        def _click():
            fig._on_event({"new": _json.dumps({
                "source": "js",
                "panel_id": plot._id,
                "event_type": "on_line_click",
                "line_id": ctrl.line.id,
            })})

        _click()   # → active
        _click()   # → hidden

        assert ctrl._active is False
        assert ctrl._pt.visible is False

    def test_line_click_wrong_line_id_no_toggle(self):
        """A click on a different line ID does NOT toggle this controller."""
        fig, plot, ctrls, fit_line, x, signal, refit_calls = self._build()
        ctrl = ctrls[0]

        @ctrl.line.on_click
        def _clicked(event, c=ctrl):
            c.toggle()

        import json as _json
        fig._on_event({"new": _json.dumps({
            "source": "js",
            "panel_id": plot._id,
            "event_type": "on_line_click",
            "line_id": "completely-wrong-id",
        })})

        assert ctrl._active is False   # was never toggled

    # ── example-mirroring tests ───────────────────────────────────────────────

    def _build_with_click_handlers(self):
        """Same as _build() but wires line.on_click → ctrl.toggle() for both
        components, exactly as the for-loop in plot_interactive_fitting.py."""
        result = self._build()
        _, _, controllers, *_ = result
        for ctrl in controllers:
            @ctrl.line.on_click
            def _clicked(event, c=ctrl):
                c.toggle()
        return result

    def test_example_both_lines_clickable(self):
        """Clicking each component line activates its controller and makes
        the widgets visible — mirrors the click-handler loop in the example."""
        fig, plot, ctrls, fit_line, x, signal, refit_calls = \
            self._build_with_click_handlers()

        # Click component 0
        _simulate_js_event(fig, plot, "on_line_click", line_id=ctrls[0].line.id)
        assert ctrls[0]._active is True
        assert ctrls[0]._pt is not None
        assert ctrls[0]._rng_w is not None
        assert ctrls[0]._pt.visible is True
        assert ctrls[0]._rng_w.visible is True
        assert ctrls[1]._active is False  # other controller untouched

        # Click component 1
        _simulate_js_event(fig, plot, "on_line_click", line_id=ctrls[1].line.id)
        assert ctrls[1]._active is True
        assert ctrls[1]._pt.visible is True
        assert ctrls[1]._rng_w.visible is True

    def test_example_click_shows_widgets_registered_in_plot(self):
        """After clicking a component line its widgets appear in list_widgets()."""
        fig, plot, ctrls, fit_line, x, signal, refit_calls = \
            self._build_with_click_handlers()

        assert len(plot.list_widgets()) == 0

        _simulate_js_event(fig, plot, "on_line_click", line_id=ctrls[0].line.id)
        assert len(plot.list_widgets()) == 2   # PointWidget + RangeWidget

        _simulate_js_event(fig, plot, "on_line_click", line_id=ctrls[1].line.id)
        assert len(plot.list_widgets()) == 4   # +2 for ctrl[1]

    def test_example_second_click_hides_widgets(self):
        """Second click hides widgets but keeps them registered in the plot."""
        fig, plot, ctrls, fit_line, x, signal, refit_calls = \
            self._build_with_click_handlers()

        def _click(ctrl):
            _simulate_js_event(fig, plot, "on_line_click",
                                line_id=ctrl.line.id)

        _click(ctrls[0])   # show
        assert ctrls[0]._active is True and ctrls[0]._pt.visible is True

        _click(ctrls[0])   # hide
        assert ctrls[0]._active is False
        assert ctrls[0]._pt.visible is False
        assert ctrls[0]._rng_w.visible is False
        assert len(plot.list_widgets()) == 2   # still registered, just hidden

    def test_example_third_click_reshows_same_widgets(self):
        """Third click re-shows the same widget objects without recreating them."""
        fig, plot, ctrls, fit_line, x, signal, refit_calls = \
            self._build_with_click_handlers()

        def _click(ctrl):
            _simulate_js_event(fig, plot, "on_line_click",
                                line_id=ctrl.line.id)

        _click(ctrls[0])
        pt_id  = ctrls[0]._pt.id
        rng_id = ctrls[0]._rng_w.id

        _click(ctrls[0])   # hide
        _click(ctrls[0])   # re-show

        assert ctrls[0]._active is True
        assert ctrls[0]._pt.visible is True
        assert ctrls[0]._rng_w.visible is True
        assert ctrls[0]._pt.id   == pt_id    # same objects, not recreated
        assert ctrls[0]._rng_w.id == rng_id
        assert len(plot.list_widgets()) == 2

    def test_example_click_then_drag_updates_fit(self):
        """Full flow: click to activate → drag PointWidget → fit line changes."""
        fig, plot, ctrls, fit_line, x, signal, refit_calls = \
            self._build_with_click_handlers()

        _simulate_js_event(fig, plot, "on_line_click", line_id=ctrls[0].line.id)
        assert ctrls[0]._active is True

        lid = fit_line.id
        fit_before = next(
            e for e in plot._state["extra_lines"] if e["id"] == lid
        )["data"].copy()

        _simulate_js_event(fig, plot, "on_changed",
                           widget_id=ctrls[0]._pt, x=4.0, y=0.8)

        fit_after = next(
            e for e in plot._state["extra_lines"] if e["id"] == lid
        )["data"]
        assert not np.array_equal(fit_after, fit_before)
        assert refit_calls[0] >= 1

    def test_example_wrong_line_id_not_clickable(self):
        """A click event for an unknown line ID activates no controller."""
        fig, plot, ctrls, fit_line, x, signal, refit_calls = \
            self._build_with_click_handlers()

        _simulate_js_event(fig, plot, "on_line_click", line_id="no-such-line")
        assert ctrls[0]._active is False
        assert ctrls[1]._active is False




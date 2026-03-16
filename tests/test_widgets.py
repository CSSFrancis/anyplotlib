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
            v_fft.update(log_mag, x_axis=freq_x, y_axis=freq_y, units="1/Å")
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

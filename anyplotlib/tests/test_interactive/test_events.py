"""
tests/test_events.py
====================

Tests for the unified object-level callback system.

  * Event dataclass  – event_type / source / data / attribute forwarding
  * CallbackRegistry – connect / disconnect / fire (event_type dispatch only)
  * Plot2D / Plot1D / PlotMesh / Plot3D – on_changed / on_release / on_click
  * Widget-level – @wid.on_changed / @wid.on_release / @wid.on_click
  * Figure._on_event – JSON routing to widget + plot callbacks
  * Practical patterns
  * Interactive FFT example – unit tests (pure Python, no browser)
"""

from __future__ import annotations

import json
import numpy as np
import pytest

import anyplotlib as apl
from anyplotlib.callbacks import CallbackRegistry, Event
from anyplotlib.figure_plots import Plot1D, Plot2D, PlotMesh, Plot3D


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _simulate_js_event(fig, plot, event_type: str, *, widget_id=None, **fields):
    """Simulate JS sending an interaction event via event_json."""
    payload = {"source": "js", "panel_id": plot._id, "event_type": event_type}
    if widget_id is not None:
        payload["widget_id"] = widget_id if isinstance(widget_id, str) else widget_id._id
    payload.update(fields)
    fig._on_event({"new": json.dumps(payload)})


def _plot2d():
    fig, ax = apl.subplots(1, 1)
    return ax.imshow(np.zeros((32, 32)))


def _plot1d():
    fig, ax = apl.subplots(1, 1)
    return ax.plot(np.zeros(64))


def _plotmesh():
    fig, ax = apl.subplots(1, 1)
    return ax.pcolormesh(np.zeros((8, 8)))


def _plot3d():
    fig, ax = apl.subplots(1, 1)
    x = np.linspace(-1, 1, 10)
    y = np.linspace(-1, 1, 10)
    X, Y = np.meshgrid(x, y)
    Z = X ** 2 + Y ** 2
    return ax.plot_surface(X, Y, Z)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Event dataclass
# ─────────────────────────────────────────────────────────────────────────────

class TestEvent:
    def test_event_type_field(self):
        ev = Event(event_type="on_release", source=None, data={"x": 1.0})
        assert ev.event_type == "on_release"

    def test_source_field(self):
        obj = object()
        ev = Event(event_type="on_changed", source=obj, data={})
        assert ev.source is obj

    def test_data_attribute_forwarding(self):
        ev = Event(event_type="on_changed", source=None, data={"cx": 12.5, "cy": 8.0})
        assert ev.cx == pytest.approx(12.5)
        assert ev.cy == pytest.approx(8.0)

    def test_unknown_attribute_raises(self):
        ev = Event(event_type="on_changed", source=None, data={"x": 1.0})
        with pytest.raises(AttributeError, match="Event has no attribute 'nonexistent'"):
            _ = ev.nonexistent

    def test_data_key_various_types(self):
        ev = Event(event_type="on_click", source=None,
                   data={"x": 1.1, "text": "hello", "flag": True, "n": 7})
        assert ev.x == pytest.approx(1.1)
        assert ev.text == "hello"
        assert ev.flag is True
        assert ev.n == 7

    def test_empty_data_raises_on_access(self):
        ev = Event(event_type="on_release", source=None, data={})
        with pytest.raises(AttributeError):
            _ = ev.anything

    def test_repr_contains_event_type(self):
        ev = Event(event_type="on_release", source=None, data={"zoom": 2.5})
        assert "on_release" in repr(ev)

    def test_repr_shows_source_type(self):
        from anyplotlib.widgets import CircleWidget
        w = CircleWidget(lambda: None, cx=0, cy=0, r=5)
        ev = Event(event_type="on_changed", source=w, data={})
        assert "CircleWidget" in repr(ev)


# ─────────────────────────────────────────────────────────────────────────────
# 2. CallbackRegistry
# ─────────────────────────────────────────────────────────────────────────────

class TestCallbackRegistry:

    def test_connect_returns_int_cid(self):
        reg = CallbackRegistry()
        cid = reg.connect("on_changed", lambda e: None)
        assert isinstance(cid, int)

    def test_connect_cids_increment(self):
        reg = CallbackRegistry()
        c1 = reg.connect("on_changed", lambda e: None)
        c2 = reg.connect("on_release", lambda e: None)
        assert c2 > c1

    def test_invalid_event_type_raises(self):
        reg = CallbackRegistry()
        with pytest.raises(ValueError, match="event_type must be one of"):
            reg.connect("change", lambda e: None)   # old name

    def test_fire_on_changed(self):
        reg = CallbackRegistry()
        fired = []
        reg.connect("on_changed", lambda e: fired.append(e))
        reg.fire(Event("on_changed", None, {}))
        assert len(fired) == 1

    def test_fire_does_not_cross_types(self):
        reg = CallbackRegistry()
        fired = []
        reg.connect("on_release", lambda e: fired.append(e))
        reg.fire(Event("on_changed", None, {}))
        assert fired == []

    def test_fire_on_release(self):
        reg = CallbackRegistry()
        fired = []
        reg.connect("on_release", lambda e: fired.append(e))
        reg.fire(Event("on_release", None, {}))
        assert len(fired) == 1

    def test_fire_on_click(self):
        reg = CallbackRegistry()
        fired = []
        reg.connect("on_click", lambda e: fired.append(e))
        reg.fire(Event("on_click", None, {}))
        assert len(fired) == 1

    def test_three_types_independent(self):
        reg = CallbackRegistry()
        c_log, r_log, k_log = [], [], []
        reg.connect("on_changed", lambda e: c_log.append(1))
        reg.connect("on_release", lambda e: r_log.append(1))
        reg.connect("on_click",   lambda e: k_log.append(1))
        reg.fire(Event("on_changed", None, {}))
        reg.fire(Event("on_release", None, {}))
        reg.fire(Event("on_click",   None, {}))
        assert len(c_log) == 1 and len(r_log) == 1 and len(k_log) == 1

    def test_disconnect_removes_handler(self):
        reg = CallbackRegistry()
        fired = []
        cid = reg.connect("on_release", lambda e: fired.append(e))
        reg.disconnect(cid)
        reg.fire(Event("on_release", None, {}))
        assert fired == []

    def test_disconnect_unknown_cid_is_silent(self):
        reg = CallbackRegistry()
        reg.disconnect(9999)

    def test_disconnect_twice_is_silent(self):
        reg = CallbackRegistry()
        cid = reg.connect("on_release", lambda e: None)
        reg.disconnect(cid)
        reg.disconnect(cid)

    def test_bool_false_when_empty(self):
        assert not CallbackRegistry()

    def test_bool_true_when_connected(self):
        reg = CallbackRegistry()
        reg.connect("on_changed", lambda e: None)
        assert reg

    def test_bool_false_after_all_disconnected(self):
        reg = CallbackRegistry()
        cid = reg.connect("on_changed", lambda e: None)
        reg.disconnect(cid)
        assert not reg

    def test_multiple_handlers_all_called(self):
        reg = CallbackRegistry()
        log = []
        reg.connect("on_release", lambda e: log.append("a"))
        reg.connect("on_release", lambda e: log.append("b"))
        reg.connect("on_release", lambda e: log.append("c"))
        reg.fire(Event("on_release", None, {}))
        assert sorted(log) == ["a", "b", "c"]

    def test_disconnect_inside_callback_is_safe(self):
        reg = CallbackRegistry()
        fired = []

        def self_disconnect(event):
            fired.append(event)
            reg.disconnect(self_disconnect._cid)

        self_disconnect._cid = reg.connect("on_release", self_disconnect)
        reg.fire(Event("on_release", None, {}))
        reg.fire(Event("on_release", None, {}))
        assert len(fired) == 1

    def test_no_handlers_fire_is_noop(self):
        CallbackRegistry().fire(Event("on_release", None, {}))


# ─────────────────────────────────────────────────────────────────────────────
# 3. Plot2D callback API
# ─────────────────────────────────────────────────────────────────────────────

class TestPlot2DCallbacks:

    def test_has_callbacks_registry(self):
        assert isinstance(_plot2d().callbacks, CallbackRegistry)

    def test_on_changed_decorator(self):
        v = _plot2d()
        fired = []

        @v.on_changed
        def cb(event): fired.append(event)

        v.callbacks.fire(Event("on_changed", None, {}))
        assert len(fired) == 1

    def test_on_changed_not_fired_for_release(self):
        v = _plot2d()
        fired = []

        @v.on_changed
        def cb(event): fired.append(event)

        v.callbacks.fire(Event("on_release", None, {}))
        assert fired == []

    def test_on_release_decorator(self):
        v = _plot2d()
        fired = []

        @v.on_release
        def cb(event): fired.append(event)

        v.callbacks.fire(Event("on_release", None, {}))
        assert len(fired) == 1

    def test_on_click_decorator(self):
        v = _plot2d()
        fired = []

        @v.on_click
        def cb(event): fired.append(event)

        v.callbacks.fire(Event("on_click", None, {"x": 5.0, "y": 10.0}))
        assert len(fired) == 1
        assert fired[0].x == pytest.approx(5.0)

    def test_decorator_stamps_cid(self):
        v = _plot2d()

        @v.on_release
        def cb(event): pass

        assert hasattr(cb, "_cid") and isinstance(cb._cid, int)

    def test_disconnect(self):
        v = _plot2d()
        fired = []

        @v.on_release
        def cb(event): fired.append(event)

        v.disconnect(cb._cid)
        v.callbacks.fire(Event("on_release", None, {}))
        assert fired == []

    def test_single_fire_pattern(self):
        v = _plot2d()
        fired = []

        @v.on_release
        def once(event):
            fired.append(event)
            v.disconnect(once._cid)

        v.callbacks.fire(Event("on_release", None, {}))
        v.callbacks.fire(Event("on_release", None, {}))
        assert len(fired) == 1

    def test_zoom_event_data(self):
        v = _plot2d()
        fired = []

        @v.on_release
        def cb(event): fired.append(event)

        v.callbacks.fire(Event("on_release", None,
                               {"center_x": 0.6, "center_y": 0.4, "zoom": 3.0}))
        assert fired[0].zoom == pytest.approx(3.0)


# ─────────────────────────────────────────────────────────────────────────────
# 4. Plot1D callback API
# ─────────────────────────────────────────────────────────────────────────────

class TestPlot1DCallbacks:

    def test_has_callbacks_registry(self):
        assert isinstance(_plot1d().callbacks, CallbackRegistry)

    def test_on_changed_and_on_release(self):
        v = _plot1d()
        change_fired, release_fired = [], []

        @v.on_changed
        def lv(event): change_fired.append(event)

        @v.on_release
        def done(event): release_fired.append(event)

        v.callbacks.fire(Event("on_changed", None, {}))
        v.callbacks.fire(Event("on_release", None, {}))
        assert len(change_fired) == 1 and len(release_fired) == 1

    def test_view_change_event_data(self):
        v = _plot1d()
        fired = []

        @v.on_release
        def cb(event): fired.append(event)

        v.callbacks.fire(Event("on_release", None, {"view_x0": 0.2, "view_x1": 0.8}))
        assert fired[0].view_x0 == pytest.approx(0.2)
        assert fired[0].view_x1 == pytest.approx(0.8)

    def test_disconnect(self):
        v = _plot1d()
        fired = []

        @v.on_changed
        def cb(event): fired.append(event)

        v.disconnect(cb._cid)
        v.callbacks.fire(Event("on_changed", None, {}))
        assert fired == []


# ─────────────────────────────────────────────────────────────────────────────
# 5. PlotMesh callback API
# ─────────────────────────────────────────────────────────────────────────────

class TestPlotMeshCallbacks:

    def test_has_callbacks_registry(self):
        assert isinstance(_plotmesh().callbacks, CallbackRegistry)

    def test_on_changed_and_on_release(self):
        v = _plotmesh()
        change_fired, release_fired = [], []

        @v.on_changed
        def lv(event): change_fired.append(event)

        @v.on_release
        def done(event): release_fired.append(event)

        v.callbacks.fire(Event("on_changed", None, {}))
        v.callbacks.fire(Event("on_release", None, {}))
        assert len(change_fired) == 1 and len(release_fired) == 1

    def test_disconnect(self):
        v = _plotmesh()
        fired = []

        @v.on_release
        def cb(event): fired.append(event)

        v.disconnect(cb._cid)
        v.callbacks.fire(Event("on_release", None, {}))
        assert fired == []


# ─────────────────────────────────────────────────────────────────────────────
# 6. Plot3D callback API
# ─────────────────────────────────────────────────────────────────────────────

class TestPlot3DCallbacks:

    def test_has_callbacks_registry(self):
        assert isinstance(_plot3d().callbacks, CallbackRegistry)

    def test_on_changed_rotation(self):
        v = _plot3d()
        fired = []

        @v.on_changed
        def cb(event): fired.append(event)

        v.callbacks.fire(Event("on_changed", None,
                               {"azimuth": 45.0, "elevation": 30.0, "zoom": 1.0}))
        assert fired[0].azimuth == pytest.approx(45.0)

    def test_on_release_data(self):
        v = _plot3d()
        fired = []

        @v.on_release
        def cb(event): fired.append(event)

        v.callbacks.fire(Event("on_release", None,
                               {"azimuth": -60.0, "elevation": 20.0, "zoom": 2.5}))
        assert fired[0].zoom == pytest.approx(2.5)

    def test_on_click(self):
        v = _plot3d()
        fired = []

        @v.on_click
        def cb(event): fired.append(event)

        v.callbacks.fire(Event("on_click", None, {"x": 1.0}))
        assert len(fired) == 1

    def test_disconnect(self):
        v = _plot3d()
        fired = []

        @v.on_release
        def cb(event): fired.append(event)

        v.disconnect(cb._cid)
        v.callbacks.fire(Event("on_release", None, {}))
        assert fired == []


# ─────────────────────────────────────────────────────────────────────────────
# 7. Widget-level callbacks (@wid.on_changed / on_release / on_click)
# ─────────────────────────────────────────────────────────────────────────────

class TestWidgetLevelCallbacks:

    def test_on_changed_fires_on_drag_frame(self):
        fig, ax = apl.subplots(1, 1)
        v = ax.imshow(np.zeros((32, 32)))
        wid = v.add_widget("circle")
        fired = []

        @wid.on_changed
        def cb(event): fired.append(event)

        _simulate_js_event(fig, v, "on_changed", widget_id=wid, cx=10.0, cy=20.0)
        assert len(fired) == 1
        assert fired[0].cx == pytest.approx(10.0)
        assert fired[0].source is wid

    def test_on_release_fires_on_mouseup(self):
        fig, ax = apl.subplots(1, 1)
        v = ax.imshow(np.zeros((32, 32)))
        wid = v.add_widget("rectangle")
        fired = []

        @wid.on_release
        def cb(event): fired.append(event)

        _simulate_js_event(fig, v, "on_release", widget_id=wid,
                           x=5.0, y=5.0, w=20.0, h=20.0)
        assert len(fired) == 1
        assert fired[0].event_type == "on_release"

    def test_on_click_fires_without_state_change(self):
        """on_click must fire even when no field values changed."""
        fig, ax = apl.subplots(1, 1)
        v = ax.imshow(np.zeros((32, 32)))
        wid = v.add_widget("crosshair", cx=16.0, cy=16.0)
        fired = []

        @wid.on_click
        def cb(event): fired.append(event)

        _simulate_js_event(fig, v, "on_click", widget_id=wid, cx=16.0, cy=16.0)
        assert len(fired) == 1

    def test_on_changed_not_fire_for_release(self):
        fig, ax = apl.subplots(1, 1)
        v = ax.imshow(np.zeros((32, 32)))
        wid = v.add_widget("circle")
        fired = []

        @wid.on_changed
        def cb(event): fired.append(event)

        _simulate_js_event(fig, v, "on_release", widget_id=wid, cx=5.0, cy=5.0)
        assert fired == []

    def test_widget_and_plot_both_fire(self):
        fig, ax = apl.subplots(1, 1)
        v = ax.imshow(np.zeros((32, 32)))
        wid = v.add_widget("circle")
        w_fired, p_fired = [], []

        @wid.on_release
        def wc(event): w_fired.append(event)

        @v.on_release
        def pc(event): p_fired.append(event)

        _simulate_js_event(fig, v, "on_release", widget_id=wid, cx=5.0, cy=5.0)
        assert len(w_fired) == 1 and len(p_fired) == 1
        assert w_fired[0].source is wid
        assert p_fired[0].source is wid

    def test_widget_state_updated_after_js_event(self):
        fig, ax = apl.subplots(1, 1)
        v = ax.imshow(np.zeros((32, 32)))
        wid = v.add_widget("rectangle", x=0.0, y=0.0, w=10.0, h=10.0)

        _simulate_js_event(fig, v, "on_changed", widget_id=wid,
                           x=50.0, y=60.0, w=20.0, h=20.0)
        assert wid.x == pytest.approx(50.0)
        assert wid.y == pytest.approx(60.0)

    def test_no_echo_from_python_push(self):
        fig, ax = apl.subplots(1, 1)
        v = ax.imshow(np.zeros((32, 32)))
        wid = v.add_widget("circle")
        fired = []

        @wid.on_changed
        def cb(event): fired.append(event)

        fig._on_event({"new": json.dumps({
            "source": "python", "panel_id": v._id,
            "widget_id": wid._id, "cx": 99.0
        })})
        assert fired == []

    def test_1d_vline_widget_event(self):
        fig, ax = apl.subplots(1, 1)
        v = ax.plot(np.zeros(64))
        wid = v.add_vline_widget(x=10.0)
        fired = []

        @wid.on_changed
        def cb(event): fired.append(event)

        _simulate_js_event(fig, v, "on_changed", widget_id=wid, x=30.0)
        assert len(fired) == 1
        assert fired[0].x == pytest.approx(30.0)

    def test_1d_range_widget_event(self):
        fig, ax = apl.subplots(1, 1)
        v = ax.plot(np.zeros(64))
        wid = v.add_range_widget(x0=5.0, x1=15.0)
        fired = []

        @wid.on_release
        def cb(event): fired.append(event)

        _simulate_js_event(fig, v, "on_release", widget_id=wid, x0=8.0, x1=20.0)
        assert len(fired) == 1
        assert fired[0].x0 == pytest.approx(8.0)


# ─────────────────────────────────────────────────────────────────────────────
# 8. Figure._on_event routing
# ─────────────────────────────────────────────────────────────────────────────

class TestFigureOnEvent:

    def test_dispatch_reaches_plot_callbacks(self):
        fig, ax = apl.subplots(1, 1)
        v = ax.imshow(np.zeros((32, 32)))
        fired = []

        @v.on_release
        def cb(event): fired.append(event)

        _simulate_js_event(fig, v, "on_release", cx=10.0, cy=20.0)
        assert len(fired) == 1
        assert fired[0].cx == pytest.approx(10.0)

    def test_dispatch_with_widget_id_updates_widget(self):
        fig, ax = apl.subplots(1, 1)
        v = ax.imshow(np.zeros((32, 32)))
        wid = v.add_widget("circle", cx=0.0, cy=0.0)

        _simulate_js_event(fig, v, "on_changed", widget_id=wid, cx=5.0)
        assert wid.cx == pytest.approx(5.0)

    def test_dispatch_wrong_panel_id_ignored(self):
        fig, ax = apl.subplots(1, 1)
        v = ax.imshow(np.zeros((32, 32)))
        fired = []

        @v.on_release
        def cb(event): fired.append(event)

        fig._on_event({"new": json.dumps({"source": "js", "panel_id": "nonexistent",
                                          "event_type": "on_release"})})
        assert fired == []

    def test_dispatch_empty_json_ignored(self):
        fig, ax = apl.subplots(1, 1)
        fig._on_event({"new": "{}"})

    def test_dispatch_invalid_json_ignored(self):
        fig, ax = apl.subplots(1, 1)
        fig._on_event({"new": "not-json"})

    def test_source_python_not_dispatched(self):
        fig, ax = apl.subplots(1, 1)
        v = ax.imshow(np.zeros((32, 32)))
        fired = []

        @v.on_changed
        def cb(event): fired.append(event)

        fig._on_event({"new": json.dumps(
            {"source": "python", "panel_id": v._id,
             "event_type": "on_changed", "cx": 5.0})})
        assert fired == []

    def test_multi_panel_correct_routing(self):
        fig, (ax1, ax2) = apl.subplots(1, 2)
        v1 = ax1.imshow(np.zeros((16, 16)))
        v2 = ax2.plot(np.zeros(32))
        fired1, fired2 = [], []

        @v1.on_release
        def cb1(event): fired1.append(event)

        @v2.on_release
        def cb2(event): fired2.append(event)

        _simulate_js_event(fig, v1, "on_release", zoom=1.5)
        assert len(fired1) == 1 and fired2 == []

        _simulate_js_event(fig, v2, "on_release", view_x0=0.1, view_x1=0.9)
        assert len(fired2) == 1 and len(fired1) == 1

    def test_protocol_keys_stripped_from_event_data(self):
        fig, ax = apl.subplots(1, 1)
        v = ax.imshow(np.zeros((16, 16)))
        fired = []

        @v.on_release
        def cb(event): fired.append(event)

        _simulate_js_event(fig, v, "on_release", zoom=2.0)
        ev = fired[0]
        assert "panel_id"   not in ev.data
        assert "event_type" not in ev.data
        assert "source"     not in ev.data
        assert ev.zoom == pytest.approx(2.0)

    def test_default_event_type_is_on_changed(self):
        fig, ax = apl.subplots(1, 1)
        v = ax.imshow(np.zeros((16, 16)))
        fired = []

        @v.on_changed
        def cb(event): fired.append(event)

        fig._on_event({"new": json.dumps({"source": "js",
                                          "panel_id": v._id, "cx": 1.0})})
        assert len(fired) == 1


# ─────────────────────────────────────────────────────────────────────────────
# 9. Practical patterns
# ─────────────────────────────────────────────────────────────────────────────

class TestPracticalPatterns:

    def test_readout_update_on_drag(self):
        fig, ax = apl.subplots(1, 1)
        v = ax.imshow(np.zeros((64, 64)))
        wid = v.add_widget("crosshair")
        readout = {"value": ""}

        @wid.on_changed
        def live(event):
            readout["value"] = f"({event.cx:.1f}, {event.cy:.1f})"

        _simulate_js_event(fig, v, "on_changed", widget_id=wid, cx=12.5, cy=7.3)
        assert readout["value"] == "(12.5, 7.3)"

    def test_expensive_work_gated_on_release(self):
        fig, ax = apl.subplots(1, 1)
        v = ax.plot(np.zeros(64))
        wid = v.add_vline_widget(x=284.0)
        calls = {"cheap": 0, "expensive": 0}

        @wid.on_changed
        def live(event): calls["cheap"] += 1

        @wid.on_release
        def done(event): calls["expensive"] += 1

        for i in range(10):
            _simulate_js_event(fig, v, "on_changed", widget_id=wid, x=285.0 + i)
        _simulate_js_event(fig, v, "on_release", widget_id=wid, x=285.0)

        assert calls["cheap"] == 10
        assert calls["expensive"] == 1

    def test_multiple_widgets_separate_callbacks(self):
        fig, ax = apl.subplots(1, 1)
        v = ax.imshow(np.zeros((32, 32)))
        w1 = v.add_widget("circle")
        w2 = v.add_widget("crosshair")
        log = {w1._id: [], w2._id: []}

        @w1.on_release
        def cb1(event): log[w1._id].append(event)

        @w2.on_release
        def cb2(event): log[w2._id].append(event)

        _simulate_js_event(fig, v, "on_release", widget_id=w1, cx=5.0, cy=5.0)
        assert len(log[w1._id]) == 1 and len(log[w2._id]) == 0

        _simulate_js_event(fig, v, "on_release", widget_id=w2, cx=8.0, cy=8.0)
        assert len(log[w1._id]) == 1 and len(log[w2._id]) == 1

    def test_widget_attribute_assignment(self):
        fig, ax = apl.subplots(1, 1)
        v = ax.imshow(np.zeros((32, 32)))
        wid = v.add_widget("rectangle", x=0.0, y=0.0, w=10.0, h=10.0)
        wid.x = 40.0
        assert wid.x == pytest.approx(40.0)
        assert v.to_state_dict()["overlay_widgets"][0]["x"] == pytest.approx(40.0)

    def test_widget_x_readback_after_js_event(self):
        fig, ax = apl.subplots(1, 1)
        v = ax.imshow(np.zeros((32, 32)))
        wid = v.add_widget("rectangle", x=0.0, y=0.0, w=10.0, h=10.0)
        _simulate_js_event(fig, v, "on_changed", widget_id=wid,
                           x=77.0, y=88.0, w=33.0, h=44.0)
        assert wid.x == pytest.approx(77.0)
        assert wid.y == pytest.approx(88.0)

    def test_3d_rotate_many_frames_one_release(self):
        x = y = np.linspace(-1, 1, 5)
        X, Y = np.meshgrid(x, y)
        fig, ax = apl.subplots(1, 1)
        v = ax.plot_surface(X, Y, np.zeros((5, 5)))
        frames, final = [], {}

        @v.on_changed
        def live(event): frames.append(event.azimuth)

        @v.on_release
        def done(event): final["az"] = event.azimuth

        for az in range(0, 50, 5):
            _simulate_js_event(fig, v, "on_changed",
                               azimuth=float(az), elevation=30.0, zoom=1.0)
        _simulate_js_event(fig, v, "on_release",
                           azimuth=45.0, elevation=30.0, zoom=1.0)

        assert len(frames) == 10
        assert final["az"] == pytest.approx(45.0)


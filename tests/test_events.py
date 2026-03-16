"""
tests/test_events.py
====================

Tests for the callback / event system:

  * CallbackRegistry  – unit tests for connect / disconnect / fire
  * Event             – attribute forwarding, repr
  * Plot2D callbacks  – on_change / on_release / disconnect / single-fire
  * Plot1D callbacks  – same API, different event names
  * PlotMesh callbacks
  * Plot3D callbacks
  * Figure._on_event  – JSON dispatch from model to plot registry
  * Filtering         – tier, name, widget_id wildcards and exact matches
  * Practical patterns
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

def _event(name="widget_change", panel_id="p1", widget_id="w1",
           settled=True, **data):
    return Event(name=name, panel_id=panel_id, widget_id=widget_id,
                 settled=settled, data=data)


def _change_event(**kw):
    return _event(settled=False, **kw)


def _release_event(**kw):
    return _event(settled=True, **kw)


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
    def test_basic_fields(self):
        ev = Event(name="zoom_change", panel_id="abc", widget_id=None,
                   settled=True, data={"zoom": 2.5, "center_x": 0.4})
        assert ev.name == "zoom_change"
        assert ev.panel_id == "abc"
        assert ev.widget_id is None
        assert ev.settled is True

    def test_data_attribute_forwarding(self):
        ev = _event(cx=12.5, cy=8.0)
        assert ev.cx == pytest.approx(12.5)
        assert ev.cy == pytest.approx(8.0)

    def test_unknown_attribute_raises(self):
        ev = _event(cx=1.0)
        with pytest.raises(AttributeError, match="Event has no attribute 'nonexistent'"):
            _ = ev.nonexistent

    def test_repr_contains_name_and_settled(self):
        ev = _event(name="rotate_change", settled=False, azimuth=45.0)
        r = repr(ev)
        assert "rotate_change" in r
        assert "settled=False" in r

    def test_repr_shows_widget_id_when_set(self):
        ev = _event(widget_id="mywidget")
        assert "mywidget" in repr(ev)

    def test_repr_omits_widget_id_when_none(self):
        ev = _event(name="zoom_change", widget_id=None)
        assert "widget_id" not in repr(ev)

    def test_data_key_forwarding_various_types(self):
        ev = _event(x=1.1, text="hello", flag=True, n=7)
        assert ev.x == pytest.approx(1.1)
        assert ev.text == "hello"
        assert ev.flag is True
        assert ev.n == 7

    def test_empty_data(self):
        ev = Event(name="view_change", panel_id="p", widget_id=None,
                   settled=True, data={})
        with pytest.raises(AttributeError):
            _ = ev.anything


# ─────────────────────────────────────────────────────────────────────────────
# 2. CallbackRegistry – unit tests
# ─────────────────────────────────────────────────────────────────────────────

class TestCallbackRegistry:

    # ── connect / disconnect ─────────────────────────────────────────────────

    def test_connect_returns_incrementing_cids(self):
        reg = CallbackRegistry()
        cid1 = reg.connect("change",  None, None, lambda e: None)
        cid2 = reg.connect("release", None, None, lambda e: None)
        assert isinstance(cid1, int)
        assert isinstance(cid2, int)
        assert cid2 > cid1

    def test_disconnect_removes_handler(self):
        reg = CallbackRegistry()
        fired = []
        cid = reg.connect("release", None, None, lambda e: fired.append(e))
        reg.disconnect(cid)
        reg.fire(_release_event())
        assert fired == []

    def test_disconnect_unknown_cid_is_silent(self):
        reg = CallbackRegistry()
        reg.disconnect(9999)  # should not raise

    def test_disconnect_twice_is_silent(self):
        reg = CallbackRegistry()
        cid = reg.connect("release", None, None, lambda e: None)
        reg.disconnect(cid)
        reg.disconnect(cid)  # should not raise

    def test_bool_false_when_empty(self):
        assert not CallbackRegistry()

    def test_bool_true_when_connected(self):
        reg = CallbackRegistry()
        reg.connect("change", None, None, lambda e: None)
        assert reg

    def test_bool_false_after_all_disconnected(self):
        reg = CallbackRegistry()
        cid = reg.connect("change", None, None, lambda e: None)
        reg.disconnect(cid)
        assert not reg

    def test_invalid_tier_raises(self):
        reg = CallbackRegistry()
        with pytest.raises(ValueError, match="tier must be"):
            reg.connect("invalid", None, None, lambda e: None)

    # ── tier dispatch ────────────────────────────────────────────────────────

    def test_change_tier_fires_on_not_settled(self):
        reg = CallbackRegistry()
        fired = []
        reg.connect("change", None, None, lambda e: fired.append(e))
        reg.fire(_change_event())
        assert len(fired) == 1
        assert not fired[0].settled

    def test_change_tier_does_not_fire_on_settled(self):
        reg = CallbackRegistry()
        fired = []
        reg.connect("change", None, None, lambda e: fired.append(e))
        reg.fire(_release_event())
        assert fired == []

    def test_release_tier_fires_on_settled(self):
        reg = CallbackRegistry()
        fired = []
        reg.connect("release", None, None, lambda e: fired.append(e))
        reg.fire(_release_event())
        assert len(fired) == 1
        assert fired[0].settled

    def test_release_tier_does_not_fire_on_not_settled(self):
        reg = CallbackRegistry()
        fired = []
        reg.connect("release", None, None, lambda e: fired.append(e))
        reg.fire(_change_event())
        assert fired == []

    def test_both_tiers_independent(self):
        reg = CallbackRegistry()
        change_fired, release_fired = [], []
        reg.connect("change",  None, None, lambda e: change_fired.append(e))
        reg.connect("release", None, None, lambda e: release_fired.append(e))
        reg.fire(_change_event())
        reg.fire(_release_event())
        assert len(change_fired) == 1
        assert len(release_fired) == 1

    # ── name filtering ───────────────────────────────────────────────────────

    def test_name_wildcard_matches_any(self):
        reg = CallbackRegistry()
        fired = []
        reg.connect("release", None, None, lambda e: fired.append(e))
        reg.fire(_release_event(name="zoom_change"))
        reg.fire(_release_event(name="view_change"))
        assert len(fired) == 2

    def test_name_exact_match_fires(self):
        reg = CallbackRegistry()
        fired = []
        reg.connect("release", "zoom_change", None, lambda e: fired.append(e))
        reg.fire(_release_event(name="zoom_change"))
        assert len(fired) == 1

    def test_name_exact_match_does_not_fire_other_name(self):
        reg = CallbackRegistry()
        fired = []
        reg.connect("release", "zoom_change", None, lambda e: fired.append(e))
        reg.fire(_release_event(name="view_change"))
        assert fired == []

    # ── widget_id filtering ──────────────────────────────────────────────────

    def test_widget_id_wildcard_matches_any(self):
        reg = CallbackRegistry()
        fired = []
        reg.connect("release", None, None, lambda e: fired.append(e))
        reg.fire(_release_event(widget_id="abc"))
        reg.fire(_release_event(widget_id="xyz"))
        assert len(fired) == 2

    def test_widget_id_exact_match_fires(self):
        reg = CallbackRegistry()
        fired = []
        reg.connect("release", None, "abc", lambda e: fired.append(e))
        reg.fire(_release_event(widget_id="abc"))
        assert len(fired) == 1

    def test_widget_id_exact_match_does_not_fire_other_widget(self):
        reg = CallbackRegistry()
        fired = []
        reg.connect("release", None, "abc", lambda e: fired.append(e))
        reg.fire(_release_event(widget_id="xyz"))
        assert fired == []

    def test_widget_id_exact_does_not_match_none_widget(self):
        reg = CallbackRegistry()
        fired = []
        reg.connect("release", None, "abc", lambda e: fired.append(e))
        reg.fire(_release_event(widget_id=None))
        assert fired == []

    def test_widget_id_wildcard_matches_none_widget(self):
        """Wildcard (None) fires even for zoom/view events where widget_id=None."""
        reg = CallbackRegistry()
        fired = []
        reg.connect("release", None, None, lambda e: fired.append(e))
        reg.fire(_release_event(name="zoom_change", widget_id=None))
        assert len(fired) == 1

    # ── combined filtering ───────────────────────────────────────────────────

    def test_all_conditions_must_match(self):
        reg = CallbackRegistry()
        fired = []
        reg.connect("release", "widget_change", "w1", lambda e: fired.append(e))
        reg.fire(_change_event(  name="widget_change", widget_id="w1"))  # wrong tier
        reg.fire(_release_event( name="zoom_change",   widget_id="w1"))  # wrong name
        reg.fire(_release_event( name="widget_change", widget_id="w2"))  # wrong widget
        assert fired == []
        reg.fire(_release_event( name="widget_change", widget_id="w1"))  # all match
        assert len(fired) == 1

    # ── multiple callbacks ───────────────────────────────────────────────────

    def test_multiple_handlers_all_called(self):
        reg = CallbackRegistry()
        log = []
        reg.connect("release", None, None, lambda e: log.append("a"))
        reg.connect("release", None, None, lambda e: log.append("b"))
        reg.connect("release", None, None, lambda e: log.append("c"))
        reg.fire(_release_event())
        assert sorted(log) == ["a", "b", "c"]

    def test_disconnect_only_removes_one(self):
        reg = CallbackRegistry()
        log = []
        cid1 = reg.connect("release", None, None, lambda e: log.append("a"))
        reg.connect(      "release", None, None, lambda e: log.append("b"))
        reg.disconnect(cid1)
        reg.fire(_release_event())
        assert log == ["b"]

    def test_disconnect_inside_callback_is_safe(self):
        """Disconnecting from within a callback should not crash."""
        reg = CallbackRegistry()
        fired = []

        def self_disconnect(event):
            fired.append(event)
            reg.disconnect(self_disconnect._cid)

        self_disconnect._cid = reg.connect("release", None, None, self_disconnect)
        reg.fire(_release_event())
        reg.fire(_release_event())  # handler already removed
        assert len(fired) == 1

    def test_no_handlers_fire_is_noop(self):
        CallbackRegistry().fire(_release_event())  # should not raise


# ─────────────────────────────────────────────────────────────────────────────
# 3. Plot2D callback API
# ─────────────────────────────────────────────────────────────────────────────

class TestPlot2DCallbacks:

    def test_has_callbacks_registry(self):
        assert isinstance(_plot2d().callbacks, CallbackRegistry)

    def test_on_change_decorator_fires_on_change(self):
        v = _plot2d()
        fired = []

        @v.on_change()
        def cb(event): fired.append(event)

        v.callbacks.fire(_change_event())
        assert len(fired) == 1

    def test_on_change_does_not_fire_on_release(self):
        v = _plot2d()
        fired = []

        @v.on_change()
        def cb(event): fired.append(event)

        v.callbacks.fire(_release_event())
        assert fired == []

    def test_on_release_decorator_fires_on_release(self):
        v = _plot2d()
        fired = []

        @v.on_release()
        def cb(event): fired.append(event)

        v.callbacks.fire(_release_event())
        assert len(fired) == 1

    def test_on_release_does_not_fire_on_change(self):
        v = _plot2d()
        fired = []

        @v.on_release()
        def cb(event): fired.append(event)

        v.callbacks.fire(_change_event())
        assert fired == []

    def test_decorator_assigns_cid(self):
        v = _plot2d()

        @v.on_release()
        def cb(event): pass

        assert hasattr(cb, "_cid") and isinstance(cb._cid, int)

    def test_disconnect(self):
        v = _plot2d()
        fired = []

        @v.on_release()
        def cb(event): fired.append(event)

        v.disconnect(cb._cid)
        v.callbacks.fire(_release_event())
        assert fired == []

    def test_widget_id_filter(self):
        v = _plot2d()
        wid = v.add_widget("crosshair")
        fired = []

        @v.on_release(wid)
        def cb(event): fired.append(event)

        v.callbacks.fire(_release_event(widget_id="other"))
        assert fired == []
        v.callbacks.fire(_release_event(widget_id=wid))
        assert len(fired) == 1

    def test_wildcard_fires_for_any_widget(self):
        v = _plot2d()
        fired = []

        @v.on_release()
        def cb(event): fired.append(event)

        v.callbacks.fire(_release_event(widget_id="any1"))
        v.callbacks.fire(_release_event(widget_id="any2"))
        assert len(fired) == 2

    def test_single_fire_pattern(self):
        v = _plot2d()
        fired = []

        @v.on_release()
        def once(event):
            fired.append(event)
            v.disconnect(once._cid)

        v.callbacks.fire(_release_event())
        v.callbacks.fire(_release_event())
        assert len(fired) == 1

    def test_zoom_event_no_widget_id(self):
        v = _plot2d()
        fired = []

        @v.on_release()
        def cb(event): fired.append(event)

        v.callbacks.fire(_release_event(name="zoom_change", widget_id=None,
                                        center_x=0.6, center_y=0.4, zoom=3.0))
        assert len(fired) == 1
        assert fired[0].zoom == pytest.approx(3.0)


# ─────────────────────────────────────────────────────────────────────────────
# 4. Plot1D callback API
# ─────────────────────────────────────────────────────────────────────────────

class TestPlot1DCallbacks:

    def test_has_callbacks_registry(self):
        assert isinstance(_plot1d().callbacks, CallbackRegistry)

    def test_on_change_and_on_release(self):
        v = _plot1d()
        change_fired, release_fired = [], []

        @v.on_change()
        def lv(event): change_fired.append(event)

        @v.on_release()
        def done(event): release_fired.append(event)

        v.callbacks.fire(_change_event(name="vline_change"))
        v.callbacks.fire(_release_event(name="vline_change"))
        assert len(change_fired) == 1
        assert len(release_fired) == 1

    def test_vline_widget_filter(self):
        v = _plot1d()
        wid = v.add_vline_widget(x=10.0)
        fired = []

        @v.on_release(wid)
        def cb(event): fired.append(event)

        v.callbacks.fire(_release_event(name="vline_change", widget_id="other"))
        assert fired == []
        v.callbacks.fire(_release_event(name="vline_change", widget_id=wid))
        assert len(fired) == 1

    def test_range_widget_filter(self):
        v = _plot1d()
        wid = v.add_range_widget(x0=5.0, x1=15.0)
        fired = []

        @v.on_release(wid)
        def cb(event): fired.append(event)

        v.callbacks.fire(_release_event(name="range_change", widget_id=wid,
                                        x0=5.0, x1=15.0))
        assert len(fired) == 1

    def test_view_change_event_data(self):
        v = _plot1d()
        fired = []

        @v.on_release()
        def cb(event): fired.append(event)

        v.callbacks.fire(_release_event(name="view_change", widget_id=None,
                                        view_x0=0.2, view_x1=0.8))
        assert len(fired) == 1
        assert fired[0].view_x0 == pytest.approx(0.2)
        assert fired[0].view_x1 == pytest.approx(0.8)

    def test_disconnect(self):
        v = _plot1d()
        fired = []

        @v.on_change()
        def cb(event): fired.append(event)

        v.disconnect(cb._cid)
        v.callbacks.fire(_change_event())
        assert fired == []

    def test_hline_widget_filter(self):
        v = _plot1d()
        wid = v.add_hline_widget(y=0.5)
        fired = []

        @v.on_release(wid)
        def cb(event): fired.append(event)

        v.callbacks.fire(_release_event(name="hline_change", widget_id=wid, y=0.5))
        assert len(fired) == 1
        assert fired[0].y == pytest.approx(0.5)


# ─────────────────────────────────────────────────────────────────────────────
# 5. PlotMesh callback API
# ─────────────────────────────────────────────────────────────────────────────

class TestPlotMeshCallbacks:

    def test_has_callbacks_registry(self):
        assert isinstance(_plotmesh().callbacks, CallbackRegistry)

    def test_on_change_and_on_release(self):
        v = _plotmesh()
        change_fired, release_fired = [], []

        @v.on_change()
        def lv(event): change_fired.append(event)

        @v.on_release()
        def done(event): release_fired.append(event)

        v.callbacks.fire(_change_event())
        v.callbacks.fire(_release_event())
        assert len(change_fired) == 1
        assert len(release_fired) == 1

    def test_disconnect(self):
        v = _plotmesh()
        fired = []

        @v.on_release()
        def cb(event): fired.append(event)

        v.disconnect(cb._cid)
        v.callbacks.fire(_release_event())
        assert fired == []

    def test_zoom_event(self):
        v = _plotmesh()
        fired = []

        @v.on_release()
        def cb(event): fired.append(event)

        v.callbacks.fire(_release_event(name="zoom_change", widget_id=None,
                                        center_x=0.5, center_y=0.5, zoom=2.0))
        assert fired[0].zoom == pytest.approx(2.0)


# ─────────────────────────────────────────────────────────────────────────────
# 6. Plot3D callback API
# ─────────────────────────────────────────────────────────────────────────────

class TestPlot3DCallbacks:

    def test_has_callbacks_registry(self):
        assert isinstance(_plot3d().callbacks, CallbackRegistry)

    def test_on_change_rotation(self):
        v = _plot3d()
        fired = []

        @v.on_change()
        def cb(event): fired.append(event)

        v.callbacks.fire(_change_event(name="rotate_change", widget_id=None,
                                       azimuth=45.0, elevation=30.0, zoom=1.0))
        assert len(fired) == 1
        assert fired[0].azimuth == pytest.approx(45.0)

    def test_on_release_rotation_data(self):
        v = _plot3d()
        fired = []

        @v.on_release()
        def cb(event): fired.append(event)

        v.callbacks.fire(_release_event(name="rotate_change", widget_id=None,
                                        azimuth=-60.0, elevation=20.0, zoom=2.5))
        assert fired[0].zoom == pytest.approx(2.5)
        assert fired[0].elevation == pytest.approx(20.0)

    def test_on_release_zoom(self):
        v = _plot3d()
        fired = []

        @v.on_release()
        def cb(event): fired.append(event)

        v.callbacks.fire(_release_event(name="zoom_change", widget_id=None,
                                        zoom=1.5, azimuth=0.0, elevation=30.0))
        assert fired[0].zoom == pytest.approx(1.5)

    def test_disconnect(self):
        v = _plot3d()
        fired = []

        @v.on_release()
        def cb(event): fired.append(event)

        v.disconnect(cb._cid)
        v.callbacks.fire(_release_event())
        assert fired == []


# ─────────────────────────────────────────────────────────────────────────────
# 7. Figure._on_event — JSON dispatch from model traitlet
# ─────────────────────────────────────────────────────────────────────────────

class TestFigureOnEvent:

    def _dispatch(self, fig, plot, name, widget_id, settled, **data):
        """Simulate JS sending event_json."""
        payload = dict(panel_id=plot._id, name=name,
                       widget_id=widget_id, settled=settled, **data)
        fig._on_event({"new": json.dumps(payload)})

    def test_dispatch_reaches_plot(self):
        fig, ax = apl.subplots(1, 1)
        v = ax.imshow(np.zeros((32, 32)))
        fired = []

        @v.on_release()
        def cb(event): fired.append(event)

        self._dispatch(fig, v, "widget_change", "w1", True, cx=10.0, cy=20.0)
        assert len(fired) == 1
        assert fired[0].cx == pytest.approx(10.0)

    def test_dispatch_wrong_panel_id_ignored(self):
        fig, ax = apl.subplots(1, 1)
        v = ax.imshow(np.zeros((32, 32)))
        fired = []

        @v.on_release()
        def cb(event): fired.append(event)

        payload = dict(panel_id="nonexistent", name="widget_change",
                       widget_id=None, settled=True)
        fig._on_event({"new": json.dumps(payload)})
        assert fired == []

    def test_dispatch_empty_json_ignored(self):
        fig, ax = apl.subplots(1, 1)
        v = ax.imshow(np.zeros((32, 32)))
        fig._on_event({"new": "{}"})  # should not raise

    def test_dispatch_invalid_json_ignored(self):
        fig, ax = apl.subplots(1, 1)
        v = ax.imshow(np.zeros((32, 32)))
        fig._on_event({"new": "not-json"})  # should not raise

    def test_dispatch_settled_false_calls_on_change(self):
        fig, ax = apl.subplots(1, 1)
        v = ax.imshow(np.zeros((32, 32)))
        fired = []

        @v.on_change()
        def cb(event): fired.append(event)

        self._dispatch(fig, v, "widget_change", "w1", False, cx=5.0)
        assert len(fired) == 1
        assert not fired[0].settled

    def test_dispatch_settled_true_calls_on_release(self):
        fig, ax = apl.subplots(1, 1)
        v = ax.imshow(np.zeros((32, 32)))
        fired = []

        @v.on_release()
        def cb(event): fired.append(event)

        self._dispatch(fig, v, "zoom_change", None, True, zoom=2.0)
        assert len(fired) == 1
        assert fired[0].zoom == pytest.approx(2.0)

    def test_dispatch_to_1d_plot(self):
        fig, ax = apl.subplots(1, 1)
        v = ax.plot(np.zeros(64))
        fired = []

        @v.on_release()
        def cb(event): fired.append(event)

        self._dispatch(fig, v, "vline_change", "vl1", True, x=42.0)
        assert fired[0].x == pytest.approx(42.0)

    def test_dispatch_multi_panel_correct_routing(self):
        fig, (ax1, ax2) = apl.subplots(1, 2)
        v1 = ax1.imshow(np.zeros((16, 16)))
        v2 = ax2.plot(np.zeros(32))
        fired1, fired2 = [], []

        @v1.on_release()
        def cb1(event): fired1.append(event)

        @v2.on_release()
        def cb2(event): fired2.append(event)

        self._dispatch(fig, v1, "zoom_change", None, True, zoom=1.5)
        assert len(fired1) == 1 and fired2 == []

        self._dispatch(fig, v2, "view_change", None, True, view_x0=0.1, view_x1=0.9)
        assert len(fired2) == 1 and len(fired1) == 1  # v1 still only 1

    def test_extra_keys_stripped_from_event_data(self):
        """panel_id / name / widget_id / settled must not appear in event.data."""
        fig, ax = apl.subplots(1, 1)
        v = ax.imshow(np.zeros((16, 16)))
        fired = []

        @v.on_release()
        def cb(event): fired.append(event)

        self._dispatch(fig, v, "zoom_change", None, True, zoom=2.0)
        ev = fired[0]
        assert "panel_id" not in ev.data
        assert "name"     not in ev.data
        assert "settled"  not in ev.data
        assert ev.zoom == pytest.approx(2.0)


# ─────────────────────────────────────────────────────────────────────────────
# 8. Filtering edge cases
# ─────────────────────────────────────────────────────────────────────────────

class TestFilteringEdgeCases:

    def test_repeated_change_then_single_release(self):
        reg = CallbackRegistry()
        change_log, release_log = [], []
        reg.connect("change",  None, None, lambda e: change_log.append(1))
        reg.connect("release", None, None, lambda e: release_log.append(1))

        for _ in range(5):
            reg.fire(_change_event())
        for _ in range(3):
            reg.fire(_release_event())

        assert len(change_log) == 5
        assert len(release_log) == 3

    def test_both_wildcards_matches_everything(self):
        reg = CallbackRegistry()
        fired = []
        reg.connect("release", None, None, lambda e: fired.append(e))
        for ev in [
            _release_event(name="zoom_change",   widget_id=None),
            _release_event(name="widget_change", widget_id="w1"),
            _release_event(name="rotate_change", widget_id=None),
        ]:
            reg.fire(ev)
        assert len(fired) == 3

    def test_exact_name_wildcard_widget(self):
        reg = CallbackRegistry()
        fired = []
        reg.connect("release", "zoom_change", None, lambda e: fired.append(e))
        reg.fire(_release_event(name="zoom_change", widget_id="w1"))
        reg.fire(_release_event(name="zoom_change", widget_id="w2"))
        reg.fire(_release_event(name="other",       widget_id="w1"))
        assert len(fired) == 2

    def test_wildcard_name_exact_widget(self):
        reg = CallbackRegistry()
        fired = []
        reg.connect("release", None, "w1", lambda e: fired.append(e))
        reg.fire(_release_event(name="zoom_change",   widget_id="w1"))
        reg.fire(_release_event(name="widget_change", widget_id="w1"))
        reg.fire(_release_event(name="zoom_change",   widget_id="w2"))
        assert len(fired) == 2


# ─────────────────────────────────────────────────────────────────────────────
# 9. Practical usage patterns
# ─────────────────────────────────────────────────────────────────────────────

class TestPracticalPatterns:

    def test_readout_update_on_drag(self):
        v = _plot2d()
        wid = v.add_widget("crosshair")
        readout = {"value": ""}

        @v.on_change(wid)
        def live(event):
            readout["value"] = f"({event.cx:.1f}, {event.cy:.1f})"

        v.callbacks.fire(_change_event(name="crosshair_change",
                                       widget_id=wid, cx=12.5, cy=7.3))
        assert readout["value"] == "(12.5, 7.3)"

    def test_expensive_work_gated_on_release(self):
        v = _plot1d()
        wid = v.add_vline_widget(x=284.0)
        calls = {"cheap": 0, "expensive": 0}

        @v.on_change(wid)
        def live(event): calls["cheap"] += 1

        @v.on_release(wid)
        def done(event): calls["expensive"] += 1

        for _ in range(10):
            v.callbacks.fire(_change_event(name="vline_change", widget_id=wid, x=285.0))
        v.callbacks.fire(_release_event(name="vline_change", widget_id=wid, x=285.0))

        assert calls["cheap"] == 10
        assert calls["expensive"] == 1

    def test_multiple_widgets_separate_callbacks(self):
        v = _plot2d()
        w1 = v.add_widget("circle")
        w2 = v.add_widget("crosshair")
        log = {w1: [], w2: []}

        @v.on_release(w1)
        def cb1(event): log[w1].append(event)

        @v.on_release(w2)
        def cb2(event): log[w2].append(event)

        v.callbacks.fire(_release_event(widget_id=w1))
        assert len(log[w1]) == 1 and len(log[w2]) == 0

        v.callbacks.fire(_release_event(widget_id=w2))
        assert len(log[w1]) == 1 and len(log[w2]) == 1

    def test_3d_rotate_many_frames_one_release(self):
        v = _plot3d()
        frames, final = [], {}

        @v.on_change()
        def live(event): frames.append(event.azimuth)

        @v.on_release()
        def done(event): final["az"] = event.azimuth

        for az in range(0, 50, 5):
            v.callbacks.fire(_change_event(name="rotate_change", widget_id=None,
                                           azimuth=float(az), elevation=30.0, zoom=1.0))
        v.callbacks.fire(_release_event(name="rotate_change", widget_id=None,
                                        azimuth=45.0, elevation=30.0, zoom=1.0))

        assert len(frames) == 10
        assert final["az"] == pytest.approx(45.0)

    def test_cid_returned_from_direct_connect(self):
        reg = CallbackRegistry()
        fired = []
        cid = reg.connect("release", None, None, lambda e: fired.append(e))
        reg.fire(_release_event())
        assert len(fired) == 1
        reg.disconnect(cid)
        reg.fire(_release_event())
        assert len(fired) == 1  # handler removed

    def test_on_change_and_on_release_same_widget(self):
        """Same widget can have both tiers active simultaneously."""
        v = _plot2d()
        wid = v.add_widget("circle")
        fast, slow = [], []

        @v.on_change(wid)
        def live(event): fast.append(event)

        @v.on_release(wid)
        def done(event): slow.append(event)

        for _ in range(5):
            v.callbacks.fire(_change_event(widget_id=wid))
        v.callbacks.fire(_release_event(widget_id=wid))

        assert len(fast) == 5
        assert len(slow) == 1


"""Tests for the redesigned Event dataclass and CallbackRegistry."""
from __future__ import annotations
import time
import pytest
import numpy as np
import anyplotlib as apl
from anyplotlib.callbacks import Event, CallbackRegistry, VALID_EVENT_TYPES, _EventMixin


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
        assert e.dx == 10.0
        assert e.dy == -5.0

    def test_no_data_dict_attribute(self):
        e = Event(event_type="pointer_move")
        assert not hasattr(e, "data")

    def test_repr_includes_event_type(self):
        e = Event(event_type="pointer_down", x=10, y=20)
        assert "pointer_down" in repr(e)

    def test_stop_propagation_not_in_repr(self):
        e = Event(event_type="pointer_down", stop_propagation=True)
        assert "stop_propagation" not in repr(e)


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


# ── regression: old API is gone ──────────────────────────────────────────────


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
        from anyplotlib.callbacks import Event
        e = Event(event_type="pointer_down", xdata=3.14)
        assert not hasattr(e, "phys_x")
        assert e.xdata == 3.14

    def test_plot3d_no_on_click(self):
        import numpy as np
        x = np.linspace(-2, 2, 10)
        XX, YY = np.meshgrid(x, x)
        fig, ax = apl.subplots(1, 1)
        plot = ax.plot_surface(XX, YY, np.zeros_like(XX))
        assert not hasattr(plot, "on_click")

    def test_plotbar_no_on_click(self):
        fig, ax = apl.subplots(1, 1)
        plot = ax.bar(["A", "B"], [1.0, 2.0])
        assert not hasattr(plot, "on_click")

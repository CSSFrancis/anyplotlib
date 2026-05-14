"""Tests for the redesigned Event dataclass and CallbackRegistry."""
from __future__ import annotations
import time
import pytest
from anyplotlib.callbacks import Event, CallbackRegistry, VALID_EVENT_TYPES


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

    def test_no_data_dict_attribute(self):
        e = Event(event_type="pointer_move")
        assert not hasattr(e, "data")

    def test_repr_includes_event_type(self):
        e = Event(event_type="pointer_down", x=10, y=20)
        assert "pointer_down" in repr(e)

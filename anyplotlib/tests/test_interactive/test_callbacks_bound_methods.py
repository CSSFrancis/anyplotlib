"""
``add_event_handler`` with bound methods.

``_register`` stamps ``_event_types`` onto the handler, which a bound method
refuses — so registering ``obj.method`` used to raise ``AttributeError`` and
callers had to wrap every method in a plain function.  Removal by
``remove_handler(obj.method)`` also has to work, even though each attribute
access builds a new bound-method object.
"""
from __future__ import annotations

import functools

import numpy as np

import anyplotlib as apl
from anyplotlib.callbacks import Event


class _Listener:
    def __init__(self):
        self.seen = []

    def on_event(self, event):
        self.seen.append(event.event_type)


def _plot():
    fig, ax = apl.subplots(1, 1)
    return ax.imshow(np.zeros((12, 25)))


class TestBoundMethodHandlers:
    def test_bound_method_registers(self):
        plot = _plot()
        listener = _Listener()
        plot.add_event_handler(listener.on_event, "pointer_down")
        plot.callbacks.fire(Event("pointer_down"))
        assert listener.seen == ["pointer_down"]

    def test_bound_method_as_decorator_target(self):
        plot = _plot()
        listener = _Listener()
        plot.add_event_handler("pointer_up")(listener.on_event)
        plot.callbacks.fire(Event("pointer_up"))
        assert listener.seen == ["pointer_up"]

    def test_remove_by_fresh_bound_method(self):
        """A second ``obj.method`` access is a new object but the same handler."""
        plot = _plot()
        listener = _Listener()
        plot.add_event_handler(listener.on_event, "pointer_down")
        plot.remove_handler(listener.on_event)
        plot.callbacks.fire(Event("pointer_down"))
        assert listener.seen == []

    def test_remove_only_matching_instance(self):
        plot = _plot()
        a, b = _Listener(), _Listener()
        plot.add_event_handler(a.on_event, "pointer_down")
        plot.add_event_handler(b.on_event, "pointer_down")
        plot.remove_handler(a.on_event)
        plot.callbacks.fire(Event("pointer_down"))
        assert a.seen == [] and b.seen == ["pointer_down"]

    def test_widget_accepts_bound_method(self):
        plot = _plot()
        widget = plot.add_widget("crosshair", cx=3, cy=4)
        listener = _Listener()
        widget.add_event_handler(listener.on_event, "pointer_move")
        widget.set(cx=5)
        assert listener.seen == ["pointer_move"]

    def test_partial_accepted(self):
        plot = _plot()
        seen = []
        handler = functools.partial(lambda tag, e: seen.append(tag), "p")
        plot.add_event_handler(handler, "pointer_down")
        plot.callbacks.fire(Event("pointer_down"))
        assert seen == ["p"]

    def test_plain_function_still_stamped(self):
        plot = _plot()

        def handler(event):
            pass

        plot.add_event_handler(handler, "pointer_down", "pointer_up")
        assert handler._event_types == {"pointer_down", "pointer_up"}

"""
Widget.set(_notify=False) and Widget.remove().

``set()`` fires ``pointer_move`` so that a JS-driven drag reaches Python
handlers.  A ``set()`` made *from* Python is indistinguishable from that, so a
handler that writes back to the widget feeds into itself.  ``_notify=False``
suppresses just this update's echo, without the blast radius of wrapping the
call in ``pause_events()``.
"""
from __future__ import annotations

import numpy as np

import anyplotlib as apl


def _plot_with_widget():
    fig, ax = apl.subplots(1, 1)
    plot = ax.imshow(np.zeros((16, 16), dtype=np.float32))
    widget = plot.add_widget("rectangle", x=2, y=2, w=4, h=4)
    return fig, plot, widget


class TestSetNotify:
    def test_set_fires_by_default(self):
        _, _, widget = _plot_with_widget()
        seen = []
        widget.add_event_handler(lambda e: seen.append(e), "pointer_move")
        widget.set(x=5)
        assert len(seen) == 1

    def test_notify_false_suppresses_callbacks(self):
        _, _, widget = _plot_with_widget()
        seen = []
        widget.add_event_handler(lambda e: seen.append(e), "pointer_move")
        widget.set(_notify=False, x=5)
        assert seen == []

    def test_notify_false_still_updates_state(self):
        _, _, widget = _plot_with_widget()
        widget.set(_notify=False, x=7)
        assert widget.x == 7

    def test_notify_false_still_pushes(self):
        """Suppressing the callback must not suppress the render update."""
        _, _, widget = _plot_with_widget()
        pushed = []
        widget._push_fn = lambda: pushed.append(True)
        widget.set(_notify=False, x=9)
        assert pushed == [True]

    def test_attribute_assignment_still_notifies(self):
        """widget.x = 5 keeps its existing behaviour."""
        _, _, widget = _plot_with_widget()
        seen = []
        widget.add_event_handler(lambda e: seen.append(e), "pointer_move")
        widget.x = 5
        assert len(seen) == 1

    def test_notify_is_not_swallowed_as_a_property(self):
        """The underscore keeps the flag from shadowing widget state."""
        _, _, widget = _plot_with_widget()
        widget.set(_notify=False, x=3)
        assert widget.get("_notify") is None
        assert widget.get("notify") is None

    def test_write_back_handler_does_not_recurse(self):
        """The motivating case: a handler that moves the widget it listens to."""
        _, _, widget = _plot_with_widget()
        calls = []

        def clamp(event):
            calls.append(event)
            # Without _notify=False this re-enters clamp for ever.
            widget.set(_notify=False, x=min(widget.x, 10))

        widget.add_event_handler(clamp, "pointer_move")
        widget.set(x=50)
        assert len(calls) == 1
        assert widget.x == 10


class TestWidgetRemove:
    def test_remove_detaches_from_plot(self):
        _, plot, widget = _plot_with_widget()
        assert widget in plot.list_widgets()
        widget.remove()
        assert widget not in plot.list_widgets()

    def test_remove_is_idempotent(self):
        _, _, widget = _plot_with_widget()
        widget.remove()
        widget.remove()  # must not raise

    def test_remove_after_clear_widgets(self):
        _, plot, widget = _plot_with_widget()
        plot.clear_widgets()
        widget.remove()  # must not raise

    def test_remove_on_unattached_widget(self):
        from anyplotlib.widgets import RectangleWidget

        widget = RectangleWidget(lambda: None, x=0, y=0, w=1, h=1)
        widget.remove()  # no owning plot — no-op, not an error

    def test_matches_plot_remove_widget(self):
        _, plot, widget = _plot_with_widget()
        other = plot.add_widget("circle", cx=8, cy=8, r=2)
        widget.remove()
        assert plot.list_widgets() == [other]

"""
Public widget identity: ``Widget.plot`` and ``Widget.kind``.

Code that holds only a widget handle (a drag callback, a remover) needs the
owning plot and the widget kind without reaching into ``_plot`` / ``_type``.
"""
from __future__ import annotations

import numpy as np
import pytest

import anyplotlib as apl
from anyplotlib.widgets import RectangleWidget


def _plot2d():
    fig, ax = apl.subplots(1, 1)
    return ax.imshow(np.zeros((12, 25)))


class TestWidgetPlot:
    def test_plot2d_widget(self):
        plot = _plot2d()
        w = plot.add_widget("rectangle", x=1, y=2, w=3, h=4)
        assert w.plot is plot

    def test_plot1d_widget(self):
        fig, ax = apl.subplots(1, 1)
        plot = ax.plot(np.arange(48.0))
        assert plot.add_vline_widget(3.0).plot is plot
        assert plot.add_range_widget(1.0, 5.0).plot is plot

    def test_standalone_is_none(self):
        assert RectangleWidget(lambda: None, x=0, y=0, w=1, h=1).plot is None

    def test_none_after_remove(self):
        plot = _plot2d()
        w = plot.add_widget("circle", cx=3, cy=4, r=2)
        w.remove()
        assert w.plot is None

    def test_none_after_remove_widget_and_clear(self):
        plot = _plot2d()
        a = plot.add_widget("crosshair", cx=3, cy=4)
        b = plot.add_widget("crosshair", cx=5, cy=6)
        plot.remove_widget(a)
        assert a.plot is None and b.plot is plot
        plot.clear_widgets()
        assert b.plot is None

    def test_read_only(self):
        plot = _plot2d()
        w = plot.add_widget("crosshair", cx=3, cy=4)
        with pytest.raises(AttributeError):
            w.plot = None
        assert "plot" not in w.to_dict()


class TestWidgetKind:
    @pytest.mark.parametrize("kind", ["rectangle", "circle", "annular",
                                      "polygon", "crosshair", "label",
                                      "arrow", "line", "brush", "vline",
                                      "hline"])
    def test_plot2d_kinds(self, kind):
        w = _plot2d().add_widget(kind)
        assert w.kind == kind == w.get("type")

    def test_plot1d_kinds(self):
        fig, ax = apl.subplots(1, 1)
        plot = ax.plot(np.arange(48.0))
        assert plot.add_vline_widget(1.0).kind == "vline"
        assert plot.add_hline_widget(1.0).kind == "hline"
        assert plot.add_range_widget(1.0, 2.0).kind == "range"
        assert plot.add_point_widget(1.0, 2.0).kind == "point"

    def test_read_only(self):
        w = _plot2d().add_widget("crosshair")
        with pytest.raises(AttributeError):
            w.kind = "circle"

    def test_writable_property_still_routes(self):
        """``visible`` has a setter, so assignment keeps working."""
        w = _plot2d().add_widget("crosshair")
        w.visible = False
        assert w.visible is False

"""
Figure lifecycle (close hook, ``closed`` / ``displayed`` flags, idempotent
``display()``) and Axes label setters that work before a plot is attached.
"""
from __future__ import annotations

import numpy as np
import pytest

import anyplotlib as apl


class _Owner:
    def __init__(self):
        self.closed_with = []

    def on_close(self, event):
        self.closed_with.append(event)


class TestClose:
    def test_closed_flag(self):
        fig, ax = apl.subplots(1, 1)
        assert fig.closed is False
        fig.close()
        assert fig.closed is True

    def test_on_close_receives_event(self):
        fig, ax = apl.subplots(1, 1)
        seen = []
        fig.on_close(lambda e: seen.append(e))
        fig.close()
        assert len(seen) == 1
        assert seen[0].event_type == "close" and seen[0].source is fig

    def test_on_close_bound_method(self):
        fig, ax = apl.subplots(1, 1)
        owner = _Owner()
        fig.on_close(owner.on_close)
        fig.close()
        assert len(owner.closed_with) == 1

    def test_on_close_runs_once(self):
        fig, ax = apl.subplots(1, 1)
        seen = []
        fig.on_close(lambda e: seen.append(1))
        fig.close()
        fig.close()
        assert seen == [1]

    def test_multiple_callbacks_in_order(self):
        fig, ax = apl.subplots(1, 1)
        seen = []
        fig.on_close(lambda e: seen.append("a"))
        fig.on_close(lambda e: seen.append("b"))
        fig.close()
        assert seen == ["a", "b"]

    def test_remove_by_cid(self):
        fig, ax = apl.subplots(1, 1)
        seen = []
        cid = fig.on_close(lambda e: seen.append(1))
        fig.remove_handler(cid)
        fig.close()
        assert seen == []

    def test_add_event_handler_close(self):
        fig, ax = apl.subplots(1, 1)
        seen = []
        fig.add_event_handler(lambda e: seen.append(e.event_type), "close")
        fig.close()
        assert seen == ["close"]

    def test_figure_before_panels(self):
        fig, ax = apl.subplots(1, 1)
        plot = ax.imshow(np.zeros((12, 25)))
        order = []
        plot.add_event_handler(lambda e: order.append("panel"), "close")
        fig.on_close(lambda e: order.append("figure"))
        fig.close()
        assert order == ["figure", "panel"]

    def test_raising_handler_still_closes(self):
        fig, ax = apl.subplots(1, 1)

        def boom(event):
            raise RuntimeError("boom")

        fig.on_close(boom)
        with pytest.raises(RuntimeError):
            fig.close()
        assert fig.closed is True
        assert fig.layout.display == "none"

    def test_raising_figure_handler_does_not_skip_panels(self):
        fig, axes = apl.subplots(1, 2)
        p0 = axes[0].imshow(np.zeros((12, 25)))
        p1 = axes[1].plot(np.zeros(48))
        seen = []

        def boom(event):
            raise RuntimeError("figure boom")

        fig.on_close(boom)
        p0.add_event_handler(lambda e: seen.append("p0"), "close")
        p1.add_event_handler(lambda e: seen.append("p1"), "close")
        with pytest.raises(RuntimeError, match="figure boom"):
            fig.close()
        assert sorted(seen) == ["p0", "p1"]
        assert fig.closed is True
        assert fig.layout.display == "none"

    def test_raising_panel_handler_does_not_skip_others(self):
        fig, axes = apl.subplots(1, 2)
        p0 = axes[0].imshow(np.zeros((12, 25)))
        p1 = axes[1].plot(np.zeros(48))
        seen = []

        def boom(event):
            raise ValueError("panel boom")

        def boom2(event):
            raise KeyError("second")

        fig.on_close(lambda e: seen.append("fig"))
        p0.add_event_handler(boom, "close")
        p1.add_event_handler(lambda e: seen.append("p1"), "close")
        p1.add_event_handler(boom2, "close")
        # the first exception wins; a later failure does not replace it
        with pytest.raises(ValueError, match="panel boom"):
            fig.close()
        assert seen == ["fig", "p1"]
        assert fig.closed is True
        assert fig.layout.display == "none"


class TestDisplay:
    def test_initially_not_displayed(self):
        fig, ax = apl.subplots(1, 1)
        assert fig.displayed is False

    def test_display_is_idempotent(self, monkeypatch):
        import IPython.display

        shown = []
        monkeypatch.setattr(IPython.display, "display", lambda obj: shown.append(obj))
        fig, ax = apl.subplots(1, 1)
        assert fig.display() is True
        assert fig.display() is False
        assert shown == [fig]
        assert fig.displayed is True

    def test_force(self, monkeypatch):
        import IPython.display

        shown = []
        monkeypatch.setattr(IPython.display, "display", lambda obj: shown.append(obj))
        fig, ax = apl.subplots(1, 1)
        fig.display()
        assert fig.display(force=True) is True
        assert len(shown) == 2

    def test_closed_figure_not_displayed(self, monkeypatch):
        import IPython.display

        shown = []
        monkeypatch.setattr(IPython.display, "display", lambda obj: shown.append(obj))
        fig, ax = apl.subplots(1, 1)
        fig.close()
        assert fig.display() is False
        assert shown == []

    def test_rich_repr_marks_displayed(self):
        fig, ax = apl.subplots(1, 1)
        fig._repr_mimebundle_()
        assert fig.displayed is True

    def test_html_repr_marks_displayed(self):
        fig, ax = apl.subplots(1, 1)
        ax.imshow(np.zeros((12, 25)))
        fig._repr_html_()
        assert fig.displayed is True

    def test_real_ipython_display(self):
        """Through the real IPython machinery (no kernel: prints the repr)."""
        fig, ax = apl.subplots(1, 1)
        assert fig.display() is True
        assert fig.displayed


class TestDeferredLabels:
    def test_labels_before_imshow(self):
        fig, ax = apl.subplots(1, 1)
        ax.set_xlabel("x (nm)")
        ax.set_ylabel("y (nm)", fontsize=13)
        ax.set_title("Title")
        plot = ax.imshow(np.zeros((12, 25)))
        assert plot._state["x_label"] == "x (nm)"
        assert plot._state["y_label"] == "y (nm)"
        assert plot._state["y_label_size"] == 13
        assert plot._state["title"] == "Title"

    def test_labels_before_plot(self):
        fig, ax = apl.subplots(1, 1)
        ax.set_title("Spectrum")
        plot = ax.plot(np.arange(48.0))
        assert plot._state["title"] == "Spectrum"

    def test_last_pending_wins(self):
        fig, ax = apl.subplots(1, 1)
        ax.set_xlabel("first")
        ax.set_xlabel("second")
        plot = ax.imshow(np.zeros((12, 25)))
        assert plot._state["x_label"] == "second"

    def test_pending_applied_once(self):
        fig, ax = apl.subplots(1, 1)
        ax.set_title("once")
        ax.imshow(np.zeros((12, 25)))
        replacement = ax.imshow(np.zeros((12, 25)))
        assert replacement._state["title"] == ""

    def test_after_attach_delegates(self):
        fig, ax = apl.subplots(1, 1)
        plot = ax.imshow(np.zeros((12, 25)))
        ax.set_xlabel("x", fontsize=9)
        assert plot._state["x_label"] == "x"
        assert plot._state["x_label_size"] == 9

    def test_inset(self):
        fig, ax = apl.subplots(1, 1)
        inset = fig.add_inset(0.3, 0.3)
        inset.set_title("zoom")
        plot = inset.imshow(np.zeros((12, 25)))
        assert plot._state["title"] == "zoom"

    def test_unsupported_after_attach_raises(self):
        from types import SimpleNamespace

        fig, ax = apl.subplots(1, 1)
        ax._plot = SimpleNamespace()       # a plot type with no label setters
        with pytest.raises(AttributeError, match="set_title"):
            ax.set_title("t")

    def test_unsupported_pending_is_dropped(self):
        """A pending label the new plot cannot show is skipped, not an error."""
        fig, ax = apl.subplots(1, 1)
        ax.set_ylabel("z")
        X, Y = np.meshgrid(np.arange(5.0), np.arange(4.0))
        ax.plot_surface(X, Y, np.zeros((4, 5)))
        assert ax._pending_labels == {}

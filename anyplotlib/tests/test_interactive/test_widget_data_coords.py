"""
Widgets in calibrated data coordinates (``coords="data"``).

The renderer places 2-D widgets in image pixels.  A widget created with
``coords="data"`` takes and reports its geometry in the panel's calibrated
axis units, while the wire state (what the renderer and JS drags see) stays
in pixels.

The image is 12 rows × 25 columns so a swapped axis cannot pass.
"""
from __future__ import annotations

import numpy as np
import pytest

import anyplotlib as apl

H, W = 12, 25
X = 10.0 + 0.5 * np.arange(W)       # data x = 10 + 0.5 * col
Y = -3.0 + 0.25 * np.arange(H)      # data y = -3 + 0.25 * row


def px_x(x):
    return (x - 10.0) / 0.5


def px_y(y):
    return (y + 3.0) / 0.25


def _plot(**kwargs):
    fig, ax = apl.subplots(1, 1)
    return ax.imshow(np.zeros((H, W)), axes=[X, Y], **kwargs)


def _wire(widget):
    """The widget as serialised to the renderer."""
    plot = widget.plot
    entries = plot.to_state_dict()["overlay_widgets"]
    return next(e for e in entries if e["id"] == widget.id)


class TestFrame:
    def test_default_is_pixel_on_2d(self):
        w = _plot().add_widget("crosshair", cx=2, cy=3)
        assert w.coords == "pixel"
        assert w.cx == 2

    def test_data_frame(self):
        w = _plot().add_widget("crosshair", cx=11.0, cy=-2.0, coords="data")
        assert w.coords == "data"
        assert w.cx == pytest.approx(11.0)
        assert w.cy == pytest.approx(-2.0)
        assert _wire(w)["cx"] == pytest.approx(2.0)
        assert _wire(w)["cy"] == pytest.approx(4.0)

    def test_invalid_coords(self):
        with pytest.raises(ValueError, match="coords"):
            _plot().add_widget("crosshair", coords="axes")

    def test_1d_is_data(self):
        fig, ax = apl.subplots(1, 1)
        plot = ax.plot(np.arange(48.0), axes=[np.linspace(0, 1, 48)])
        w = plot.add_vline_widget(0.25, coords="data")
        assert w.coords == "data" and w.x == 0.25
        assert plot.add_range_widget(0.1, 0.2).coords == "data"
        assert plot.add_point_widget(0.1, 0.2, coords="data").x == 0.1
        assert plot.add_hline_widget(0.5, coords="data").y == 0.5
        with pytest.raises(ValueError, match="data"):
            plot.add_vline_widget(0.25, coords="pixel")

    def test_bar_accepts_data(self):
        fig, ax = apl.subplots(1, 1)
        bar = ax.bar(["a", "b", "c"], [1.0, 2.0, 3.0])
        assert bar.add_hline_widget(1.5, coords="data").y == 1.5
        with pytest.raises(ValueError):
            bar.add_vline_widget(0.5, coords="pixel")


class TestKinds:
    def test_rectangle(self):
        w = _plot().add_widget("rectangle", x=11.0, y=-2.0, w=2.0, h=1.0,
                               coords="data")
        wire = _wire(w)
        assert (wire["x"], wire["y"], wire["w"], wire["h"]) == pytest.approx(
            (2.0, 4.0, 4.0, 4.0))
        assert (w.x, w.y, w.w, w.h) == pytest.approx((11.0, -2.0, 2.0, 1.0))

    def test_rectangle_max_extent(self):
        w = _plot().add_rectangle_widget(x=11.0, y=-2.0, w=1.0, h=0.5,
                                         max_extent=(2.0, 1.0), coords="data")
        assert _wire(w)["max_w"] == pytest.approx(4.0)
        assert _wire(w)["max_h"] == pytest.approx(4.0)
        assert w.max_w == pytest.approx(2.0)

    def test_rectangle_scalar_max_extent(self):
        w = _plot().add_rectangle_widget(x=11.0, y=-2.0, w=0.5, h=0.5,
                                         max_extent=1.0, coords="data")
        assert _wire(w)["max_w"] == pytest.approx(2.0)
        assert _wire(w)["max_h"] == pytest.approx(4.0)

    def test_circle(self):
        w = _plot().add_widget("circle", cx=12.0, cy=-1.0, r=1.5, coords="data")
        wire = _wire(w)
        assert (wire["cx"], wire["cy"], wire["r"]) == pytest.approx((4.0, 8.0, 3.0))
        assert w.r == pytest.approx(1.5)

    def test_annular(self):
        w = _plot().add_widget("annular", cx=12.0, cy=-1.0, r_outer=2.0,
                               r_inner=1.0, coords="data")
        assert _wire(w)["r_outer"] == pytest.approx(4.0)
        assert _wire(w)["r_inner"] == pytest.approx(2.0)
        assert w.r_inner == pytest.approx(1.0)

    def test_line(self):
        w = _plot().add_widget("line", x1=10.0, y1=-3.0, x2=12.0, y2=-2.0,
                               coords="data")
        wire = _wire(w)
        assert (wire["x1"], wire["y1"], wire["x2"], wire["y2"]) == pytest.approx(
            (0.0, 0.0, 4.0, 4.0))
        # length is reported in the widget's frame
        assert w.length == pytest.approx(np.hypot(2.0, 1.0))

    def test_polygon(self):
        verts = [(10.0, -3.0), (12.0, -3.0), (12.0, -2.0)]
        w = _plot().add_widget("polygon", vertices=verts, coords="data")
        np.testing.assert_allclose(_wire(w)["vertices"],
                                   [[0.0, 0.0], [4.0, 0.0], [4.0, 4.0]])
        np.testing.assert_allclose(w.vertices, verts)

    def test_label(self):
        w = _plot().add_widget("label", x=11.0, y=-2.0, text="hi", coords="data")
        assert (_wire(w)["x"], _wire(w)["y"]) == pytest.approx((2.0, 4.0))
        assert w.text == "hi"

    def test_arrow(self):
        w = _plot().add_widget("arrow", x=11.0, y=-2.0, u=1.0, v=0.5,
                               coords="data")
        wire = _wire(w)
        assert (wire["u"], wire["v"]) == pytest.approx((2.0, 2.0))
        assert (w.u, w.v) == pytest.approx((1.0, 0.5))

    def test_arrow_descending_y_keeps_sign(self):
        """origin='lower': data +y points up the screen, i.e. -rows."""
        w = _plot(origin="lower").add_widget("arrow", x=11.0, y=-2.0, u=0.0,
                                             v=0.5, coords="data")
        assert _wire(w)["v"] == pytest.approx(-2.0)
        assert w.v == pytest.approx(0.5)

    def test_vline_hline(self):
        plot = _plot()
        v = plot.add_vline_widget(x=12.0, coords="data")
        h = plot.add_hline_widget(y=-1.0, coords="data")
        assert _wire(v)["x"] == pytest.approx(4.0)
        assert _wire(h)["y"] == pytest.approx(8.0)
        assert v.x == pytest.approx(12.0) and h.y == pytest.approx(-1.0)

    def test_vline_snap_values(self):
        v = _plot().add_vline_widget(x=12.0, coords="data")
        v.set(snap_values=[10.0, 11.0], notify=False)
        assert _wire(v)["snap_values"] == pytest.approx([0.0, 2.0])
        assert v.snap_values == pytest.approx([10.0, 11.0])

    def test_brush(self):
        plot = _plot()
        b = plot.add_brush_widget(radius=1.0, strokes=[[(10.0, -3.0), (11.0, -2.0)]],
                                  coords="data")
        assert _wire(b)["radius"] == pytest.approx(2.0)
        np.testing.assert_allclose(_wire(b)["strokes"], [[[0.0, 0.0], [2.0, 4.0]]])
        b.add_stroke([(12.0, -1.0)], class_id=1)
        np.testing.assert_allclose(_wire(b)["strokes"][0], [[0.0, 0.0], [2.0, 4.0]])
        np.testing.assert_allclose(_wire(b)["strokes"][1], [[4.0, 8.0]])
        np.testing.assert_allclose(b.strokes_for_class(1), [[[12.0, -1.0]]])
        np.testing.assert_allclose(b.strokes[0], [[10.0, -3.0], [11.0, -2.0]])

    def test_defaults_are_in_pixels(self):
        """Omitted geometry still defaults relative to the image."""
        w = _plot().add_widget("crosshair", coords="data")
        assert _wire(w)["cx"] == pytest.approx(W / 2)
        assert w.cx == pytest.approx(10.0 + 0.5 * W / 2)


class TestReadWrite:
    def test_set_converts(self):
        w = _plot().add_widget("crosshair", cx=11.0, cy=-2.0, coords="data")
        w.set(cx=12.0, notify=False)
        assert _wire(w)["cx"] == pytest.approx(4.0)
        w.cy = -1.0
        assert _wire(w)["cy"] == pytest.approx(8.0)

    def test_get_and_to_dict(self):
        w = _plot().add_widget("crosshair", cx=11.0, cy=-2.0, coords="data")
        assert w.get("cx") == pytest.approx(11.0)
        assert w.get("cx", coords="pixel") == pytest.approx(2.0)
        assert w.get("missing", 7) == 7
        d = w.to_dict()
        assert d["cx"] == pytest.approx(11.0) and d["color"] == w.color
        assert w.to_dict(coords="pixel")["cx"] == pytest.approx(2.0)

    def test_pixel_widget_can_report_data(self):
        w = _plot().add_widget("crosshair", cx=2.0, cy=4.0)
        assert w.get("cx", coords="data") == pytest.approx(11.0)
        assert w.to_dict(coords="data")["cy"] == pytest.approx(-2.0)

    def test_set_coords(self):
        w = _plot().add_widget("crosshair", cx=2.0, cy=4.0)
        w.set_coords("data")
        assert w.cx == pytest.approx(11.0)
        assert _wire(w)["cx"] == pytest.approx(2.0)      # did not move
        with pytest.raises(ValueError):
            w.set_coords("screen")

    def test_js_drag_reports_data(self):
        """A drag arrives in pixels; handlers read calibrated values."""
        w = _plot().add_widget("crosshair", cx=11.0, cy=-2.0, coords="data")
        seen = []
        w.add_event_handler(lambda e: seen.append((e.source.cx, e.source.cy)),
                            "pointer_move")
        w._update_from_js({"cx": 6.0, "cy": 2.0, "event_type": "pointer_move"})
        assert seen == [pytest.approx((13.0, -2.5))]

    def test_recalibration_keeps_pixels(self):
        plot = _plot()
        w = plot.add_widget("crosshair", cx=11.0, cy=-2.0, coords="data")
        plot.set_extent(2 * X, 2 * Y)
        assert _wire(w)["cx"] == pytest.approx(2.0)
        assert w.cx == pytest.approx(22.0)

    def test_detached_widget_reads_raw(self):
        plot = _plot()
        w = plot.add_widget("crosshair", cx=11.0, cy=-2.0, coords="data")
        w.remove()
        assert w.cx == pytest.approx(2.0)   # no panel, no calibration


class TestRectangleFlippedAxes:
    """In data coords a rectangle's ``(x, y)`` is the corner with the
    smallest data x and y and ``(w, h)`` are positive data lengths: it spans
    ``[x, x + w] × [y, y + h]`` in data, whichever way the axes run.

    Data x 11..13 / y -2..-1 on the 12 × 25 image:
    ascending           → cols 2..6,  rows 4..8
    origin="lower"      → cols 2..6,  rows 3..7  (row = 11 - (y + 3) / 0.25)
    descending x        → cols 18..22, rows 4..8 (col = (22 - x) / 0.5)
    """

    CASES = {
        "ascending": ({}, (2.0, 4.0, 4.0, 4.0)),
        "origin_lower": ({"origin": "lower"}, (2.0, 3.0, 4.0, 4.0)),
        "descending_x": ({"axes": [X[::-1], Y]}, (18.0, 4.0, 4.0, 4.0)),
    }

    @staticmethod
    def _make(kw):
        fig, ax = apl.subplots(1, 1)
        kw = dict(kw)
        axes = kw.pop("axes", [X, Y])
        return ax.imshow(np.zeros((H, W)), axes=axes, **kw)

    @staticmethod
    def _px(w):
        wire = _wire(w)
        return (wire["x"], wire["y"], wire["w"], wire["h"])

    @pytest.mark.parametrize("case", list(CASES))
    def test_stored_pixel_rect(self, case):
        kw, expect = self.CASES[case]
        w = self._make(kw).add_rectangle_widget(x=11.0, y=-2.0, w=2.0, h=1.0,
                                                coords="data")
        assert self._px(w) == pytest.approx(expect)

    @pytest.mark.parametrize("case", list(CASES))
    def test_round_trip_reads(self, case):
        kw, _ = self.CASES[case]
        w = self._make(kw).add_rectangle_widget(x=11.0, y=-2.0, w=2.0, h=1.0,
                                                coords="data")
        assert (w.x, w.y, w.w, w.h) == pytest.approx((11.0, -2.0, 2.0, 1.0))
        assert w.get("x") == pytest.approx(11.0)
        d = w.to_dict()
        assert (d["x"], d["y"], d["w"], d["h"]) == pytest.approx(
            (11.0, -2.0, 2.0, 1.0))

    def test_partial_set_descending_x(self):
        w = self._make({"axes": [X[::-1], Y]}).add_rectangle_widget(
            x=11.0, y=-2.0, w=2.0, h=1.0, coords="data")
        w.set(x=11.5, notify=False)          # span 11.5..13.5 → cols 17..21
        assert self._px(w) == pytest.approx((17.0, 4.0, 4.0, 4.0))
        w.w = 1.0                            # span 11.5..12.5 → cols 19..21
        assert self._px(w) == pytest.approx((19.0, 4.0, 2.0, 4.0))
        assert (w.x, w.w) == pytest.approx((11.5, 1.0))

    def test_partial_set_origin_lower(self):
        w = self._make({"origin": "lower"}).add_rectangle_widget(
            x=11.0, y=-2.0, w=2.0, h=1.0, coords="data")
        w.h = 0.5                            # y -2..-1.5 → rows 5..7
        assert self._px(w) == pytest.approx((2.0, 5.0, 4.0, 2.0))
        assert (w.y, w.h) == pytest.approx((-2.0, 0.5))

    def test_drag_reports_data_corner(self):
        """A JS drag sends the pixel rect; handlers see the data corner."""
        w = self._make({"origin": "lower"}).add_rectangle_widget(
            x=11.0, y=-2.0, w=2.0, h=1.0, coords="data")
        seen = []
        w.add_event_handler(
            lambda e: seen.append((e.source.x, e.source.y, e.source.w,
                                   e.source.h)), "pointer_move")
        # pixel rows 1..5 → y from 11 - 5 = 6 → -1.5 up to 11 - 1 = 10 → -0.5
        w._update_from_js({"x": 4.0, "y": 1.0, "w": 4.0, "h": 4.0,
                           "event_type": "pointer_move"})
        assert seen == [pytest.approx((12.0, -1.5, 2.0, 1.0))]

    def test_defaults_on_descending_x(self):
        """Omitted geometry still defaults to the same pixel rectangle."""
        p = self._make({"axes": [X[::-1], Y]})
        ref = p.add_rectangle_widget()
        w = p.add_rectangle_widget(coords="data")
        assert self._px(w) == pytest.approx(self._px(ref))
        w2 = p.add_rectangle_widget(x=11.0, coords="data")
        # given x = left data edge; default data width keeps W/2 pixels
        assert self._px(w2)[2] == pytest.approx(W * 0.5)
        assert w2.x == pytest.approx(11.0)

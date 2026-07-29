"""
tests/test_interactive/test_widget_brush.py
============================================

``BrushWidget`` — freehand painted strokes on a 2-D image, for labelling
regions (painting training scribbles for a pixel classifier).

Two things about this widget are load-bearing and neither is visible from
Python, so most of the coverage here drives a real browser:

**Arming.** A brush's body is "anywhere in the image". The 2-D mousedown handler
gives an ``_ovHitTest2d`` hit ABSOLUTE priority over panning and over
click-to-select, so a brush that hit-tested as its body would kill both outright.
Painting is therefore gated twice: the widget must be ``active``, and the drag
must hold **Shift**. A bare drag still pans — ``test_bare_drag_pans_and_does_not_paint``
is the single most important test in this file.

**Emit on release only.** Widget drags in ``figure_esm.js`` are unthrottled:
every document mousemove ends ``_doDrag2d`` with a full ``_viewStateJson``
serialise + ``save_changes()``, and the caller spreads the whole widget dict into
an ``event_json``. A stroke that grew by a point per tick would re-serialise and
re-diff the entire stroke list on EVERY tick — O(n²) over one stroke. So the
stroke accumulates in JS, redraws locally, and reaches Python exactly once, on
mouseup. ``TestEmitOncePerStroke`` counts the events that contract promises.

Coordinates: all 2-D widgets in this library speak IMAGE PIXELS. The page
position of an image pixel depends on the panel's live zoom/centre, so the tests
derive it from the transform the draw path publishes to
``window._aplWidgetGeom`` — never from figure padding.
"""
from __future__ import annotations

import json

import numpy as np
import pytest

import anyplotlib as apl
from anyplotlib.widgets import BrushWidget
from anyplotlib.tests.test_interactive._event_test_utils import (
    _collect_events, _get_events,
)

FIG_W, FIG_H = 400, 300
IMG = 64          # image is IMG x IMG px in every browser test


# ═══════════════════════════════════════════════════════════════════════════
# 1. Python API
# ═══════════════════════════════════════════════════════════════════════════

class TestBrushAttributes:
    def test_defaults(self):
        w = BrushWidget(lambda: None)
        assert w._type == "brush"
        assert w.radius == 8.0
        assert w.class_id == 0
        assert w.active is True
        assert w.erase is False
        assert w.strokes == [] and w.stroke_classes == [] and w.colors == []

    def test_state_dict_carries_everything_js_reads(self):
        """JS reads the widget dict, so every painted field has to survive
        to_dict() — that is the whole wire format."""
        w = BrushWidget(lambda: None, radius=3, colors=["#f00", "#0f0"],
                        class_id=1, alpha=0.4, active=False, erase=True,
                        strokes=[[(1, 2), (3, 4)]], stroke_classes=[1])
        d = w.to_dict()
        assert d["type"] == "brush"
        assert d["radius"] == 3.0
        assert d["colors"] == ["#f00", "#0f0"]
        assert d["class_id"] == 1
        assert d["alpha"] == 0.4
        assert d["active"] is False and d["erase"] is True
        assert d["strokes"] == [[[1.0, 2.0], [3.0, 4.0]]]
        assert d["stroke_classes"] == [1]

    def test_points_are_coerced_to_plain_floats(self):
        """The dict is JSON-serialised onto a traitlet, so numpy must not
        survive into it."""
        w = BrushWidget(lambda: None,
                        strokes=[np.array([[1, 2], [3, 4]], dtype=np.int16)])
        pts = w.strokes[0]
        assert pts == [[1.0, 2.0], [3.0, 4.0]]
        assert all(type(c) is float for pt in pts for c in pt)

    def test_stroke_classes_default_to_the_active_class(self):
        w = BrushWidget(lambda: None, class_id=2,
                        strokes=[[(0, 0)], [(1, 1)]])
        assert w.stroke_classes == [2, 2]


class TestBrushValidation:
    def test_zero_radius_raises(self):
        with pytest.raises(ValueError, match="radius"):
            BrushWidget(lambda: None, radius=0)

    def test_negative_radius_raises(self):
        with pytest.raises(ValueError, match="radius"):
            BrushWidget(lambda: None, radius=-4)

    def test_negative_class_id_raises(self):
        with pytest.raises(ValueError, match="class_id"):
            BrushWidget(lambda: None, class_id=-1)

    def test_alpha_out_of_range_raises(self):
        with pytest.raises(ValueError, match="alpha"):
            BrushWidget(lambda: None, alpha=1.5)

    def test_a_single_colour_string_raises(self):
        """colors= is the per-CLASS list; a bare string is almost certainly a
        confusion with color=, and iterating it would give one colour per
        character."""
        with pytest.raises(ValueError, match="colors"):
            BrushWidget(lambda: None, colors="#ff0000")

    def test_a_point_that_is_not_a_pair_raises(self):
        with pytest.raises(ValueError, match=r"\(x, y\)"):
            BrushWidget(lambda: None, strokes=[[(1, 2, 3)]])

    def test_an_empty_stroke_raises(self):
        with pytest.raises(ValueError, match="empty"):
            BrushWidget(lambda: None, strokes=[[]])

    def test_class_length_mismatch_raises(self):
        with pytest.raises(ValueError, match="stroke_classes"):
            BrushWidget(lambda: None, strokes=[[(0, 0)]], stroke_classes=[0, 1])

    def test_negative_stroke_class_raises(self):
        with pytest.raises(ValueError, match="stroke_classes"):
            BrushWidget(lambda: None, strokes=[[(0, 0)]], stroke_classes=[-2])


class TestStrokeManagement:
    def test_add_stroke_uses_the_active_class(self):
        w = BrushWidget(lambda: None, class_id=3)
        w.add_stroke([(0, 0), (1, 1)])
        assert w.n_strokes == 1 and w.stroke_classes == [3]

    def test_add_stroke_explicit_class_overrides(self):
        w = BrushWidget(lambda: None, class_id=3)
        w.add_stroke([(0, 0)], class_id=1)
        assert w.stroke_classes == [1]

    def test_add_stroke_rejects_an_empty_stroke(self):
        w = BrushWidget(lambda: None)
        with pytest.raises(ValueError, match="empty"):
            w.add_stroke([])

    def test_clear_strokes_empties_both_lists(self):
        w = BrushWidget(lambda: None, strokes=[[(0, 0)], [(1, 1)]])
        w.clear_strokes()
        assert w.strokes == [] and w.stroke_classes == []

    def test_clear_strokes_keeps_the_active_class(self):
        w = BrushWidget(lambda: None, class_id=2, strokes=[[(0, 0)]])
        w.clear_strokes()
        assert w.class_id == 2

    def test_set_strokes_replaces_and_keeps_classes_in_lockstep(self):
        w = BrushWidget(lambda: None, strokes=[[(9, 9)]])
        w.set_strokes([[(0, 0)], [(1, 1)]], [4, 5])
        assert w.strokes == [[[0.0, 0.0]], [[1.0, 1.0]]]
        assert w.stroke_classes == [4, 5]

    def test_set_strokes_rejects_a_class_length_mismatch(self):
        w = BrushWidget(lambda: None)
        with pytest.raises(ValueError, match="classes"):
            w.set_strokes([[(0, 0)]], [0, 1])

    def test_strokes_for_class_filters(self):
        w = BrushWidget(lambda: None,
                        strokes=[[(0, 0)], [(1, 1)], [(2, 2)]],
                        stroke_classes=[0, 1, 0])
        assert w.strokes_for_class(0) == [[[0.0, 0.0]], [[2.0, 2.0]]]
        assert w.strokes_for_class(1) == [[[1.0, 1.0]]]
        assert w.strokes_for_class(7) == []

    def test_pushes_reach_the_plot(self):
        """A mutator that forgets _push() leaves the renderer showing stale
        strokes, which is invisible from Python."""
        fig, ax = apl.subplots(1, 1)
        plot = ax.imshow(np.zeros((32, 32), dtype=np.float32))
        w = plot.add_brush_widget()
        w.add_stroke([(1, 1), (2, 2)])
        plot._push()                      # refresh overlay_widgets from _widgets
        assert plot._state["overlay_widgets"][0]["strokes"] == \
            [[[1.0, 1.0], [2.0, 2.0]]]


class TestBrushFactory:
    def test_add_brush_widget_registers_the_widget(self):
        fig, ax = apl.subplots(1, 1)
        plot = ax.imshow(np.zeros((32, 32), dtype=np.float32))
        w = plot.add_brush_widget()
        assert isinstance(w, BrushWidget)
        assert plot._widgets[w.id] is w
        assert [x["type"] for x in plot._state["overlay_widgets"]] == ["brush"]

    def test_default_radius_scales_with_the_image(self):
        fig, ax = apl.subplots(1, 1)
        plot = ax.imshow(np.zeros((512, 512), dtype=np.float32))
        assert plot.add_brush_widget().radius == pytest.approx(512 * 0.02)

    def test_default_radius_has_a_floor_on_a_tiny_image(self):
        fig, ax = apl.subplots(1, 1)
        plot = ax.imshow(np.zeros((16, 16), dtype=np.float32))
        assert plot.add_brush_widget().radius == 2.0

    def test_explicit_radius_wins(self):
        fig, ax = apl.subplots(1, 1)
        plot = ax.imshow(np.zeros((512, 512), dtype=np.float32))
        assert plot.add_brush_widget(radius=1.5).radius == 1.5

    def test_add_widget_dispatches_brush(self):
        fig, ax = apl.subplots(1, 1)
        plot = ax.imshow(np.zeros((32, 32), dtype=np.float32))
        w = plot.add_widget("brush", radius=4, colors=["#f00"])
        assert isinstance(w, BrushWidget) and w.radius == 4.0

    def test_seeded_strokes_reach_the_state(self):
        fig, ax = apl.subplots(1, 1)
        plot = ax.imshow(np.zeros((32, 32), dtype=np.float32))
        plot.add_brush_widget(strokes=[[(1, 1), (5, 5)]], stroke_classes=[1])
        st = plot._state["overlay_widgets"][0]
        assert st["strokes"] == [[[1.0, 1.0], [5.0, 5.0]]]
        assert st["stroke_classes"] == [1]


class TestJsToPython:
    """The JS ships the finished stroke as ONE pointer_up.  Python has to absorb
    it and fire the handler that hosts actually register on."""

    def test_pointer_up_converges_the_strokes(self):
        fig, ax = apl.subplots(1, 1)
        plot = ax.imshow(np.zeros((32, 32), dtype=np.float32))
        brush = plot.add_brush_widget()
        seen = []
        brush.add_event_handler(lambda ev: seen.append(ev), "pointer_up")

        # Exactly the payload figure_esm.js emits on mouseup: the whole widget
        # dict plus the pointer envelope.
        payload = dict(brush.to_dict())
        payload.update(strokes=[[[1.0, 2.0], [3.0, 4.0]]], stroke_classes=[0])
        payload.update(source="js", panel_id=plot._id, event_type="pointer_up",
                       widget_id=brush.id, time_stamp=1.0, modifiers=["shift"],
                       button=0, buttons=0)
        fig._on_event({"new": json.dumps(payload)})

        assert brush.strokes == [[[1.0, 2.0], [3.0, 4.0]]]
        assert brush.n_strokes == 1
        assert len(seen) == 1 and seen[0].event_type == "pointer_up"


# ═══════════════════════════════════════════════════════════════════════════
# 2. Real browser drags — the arming and emit-once logic lives entirely in
#    figure_esm.js, so a Python-only test proves nothing about painting.
# ═══════════════════════════════════════════════════════════════════════════

def _setup(interact_page, **brush_kwargs):
    fig, ax = apl.subplots(1, 1, figsize=(FIG_W, FIG_H))
    plot = ax.imshow(np.arange(IMG * IMG, dtype=np.float32).reshape(IMG, IMG))
    brush = plot.add_brush_widget(radius=2.0, **brush_kwargs)
    page = interact_page(fig)
    _collect_events(page)
    return fig, plot, brush, page


def _brush_geom(page, plot_id, widget_id):
    """The canvas-space geometry the draw path publishes for this brush.

    ``ox``/``oy``/``scale`` are the live image->canvas transform. A test cannot
    derive a 2-D widget's page position from figure padding — the mapping depends
    on the panel's zoom/centre state — and unlike a rectangle a brush has no
    handle (and with zero strokes, nothing drawn at all) to aim at.
    """
    return page.evaluate(
        """([pid, wid]) => {
            const g = window._aplWidgetGeom && window._aplWidgetGeom[pid];
            return g ? (g[wid] || null) : null;
        }""", [str(plot_id), str(widget_id)])


def _overlay_rect(page):
    """Bounding rect of the OVERLAY canvas — the element ``_clientPos``
    measures mouse positions against (inline ``z-index:5``)."""
    return page.evaluate(
        """() => {
            const c = [...document.querySelectorAll('canvas')]
                        .find(x => x.style.zIndex === '5');
            const r = c.getBoundingClientRect();
            return {left: r.left, top: r.top,
                    sfX: r.width ? c.width / r.width : 1,
                    sfY: r.height ? c.height / r.height : 1};
        }""")


def _img_to_page(geom, rect, ix, iy):
    """Image pixel -> page coordinate, via the published transform."""
    return (rect["left"] + (geom["ox"] + ix * geom["scale"]) / rect["sfX"],
            rect["top"] + (geom["oy"] + iy * geom["scale"]) / rect["sfY"])


def _paint(page, geom, rect, pts, *, shift=True, steps=6):
    """Drag through a list of IMAGE-pixel points, optionally holding Shift."""
    x0, y0 = _img_to_page(geom, rect, *pts[0])
    page.mouse.move(x0, y0)
    if shift:
        page.keyboard.down("Shift")
    page.mouse.down()
    for ix, iy in pts[1:]:
        px, py = _img_to_page(geom, rect, ix, iy)
        page.mouse.move(px, py, steps=steps)
    page.mouse.up()
    if shift:
        page.keyboard.up("Shift")
    page.wait_for_timeout(80)


def _widget(page, plot_id, idx=0):
    """The live widget dict out of the panel's JS state."""
    return page.evaluate(
        """([pid, i]) => {
            const raw = window._aplModel.get('panel_' + pid + '_json');
            const st = raw ? JSON.parse(raw) : null;
            const ws = st && st.overlay_widgets;
            return ws && ws[i] ? ws[i] : null;
        }""", [str(plot_id), idx])


def _view(page, plot_id):
    """zoom / centre of the panel — how the tests detect a pan."""
    return page.evaluate(
        """(pid) => {
            const raw = window._aplModel.get('panel_' + pid + '_json');
            const st = raw ? JSON.parse(raw) : null;
            return st ? {zoom: st.zoom, cx: st.center_x, cy: st.center_y} : null;
        }""", str(plot_id))


def _count_overlay_color(page, rgb, tol=48):
    """Non-transparent overlay pixels within ``tol`` of an RGB triple."""
    return page.evaluate(
        """([r0, g0, b0, tol]) => {
            const c = [...document.querySelectorAll('canvas')]
                        .find(x => x.style.zIndex === '5');
            const d = c.getContext('2d')
                       .getImageData(0, 0, c.width, c.height).data;
            let n = 0;
            for (let i = 0; i < d.length; i += 4) {
                if (d[i + 3] < 8) continue;
                if (Math.abs(d[i] - r0) <= tol &&
                    Math.abs(d[i + 1] - g0) <= tol &&
                    Math.abs(d[i + 2] - b0) <= tol) n++;
            }
            return n;
        }""", [rgb[0], rgb[1], rgb[2], tol])


@pytest.mark.usefixtures("interact_page")
class TestArming:
    """THE constraint: a brush must not swallow the panel's other gestures."""

    def test_bare_drag_pans_and_does_not_paint(self, interact_page):
        """The most important test here. `_attachEvents2d`'s mousedown gives an
        `_ovHitTest2d` hit absolute priority over panning, so a brush that
        claimed a plain drag would kill panning for the whole panel.

        The pan is detected via ``center_x``, which the pan handler writes on
        every move regardless of zoom (at zoom 1 the blit itself is pinned, but
        the state still moves)."""
        fig, plot, brush, page = _setup(interact_page)
        geom = _brush_geom(page, plot._id, brush.id)
        assert geom is not None, "brush geometry readback missing"
        rect = _overlay_rect(page)
        before = _view(page, plot._id)

        _paint(page, geom, rect, [(20, 32), (44, 32)], shift=False)

        after_w = _widget(page, plot._id)
        assert after_w["strokes"] == [], \
            "a BARE drag painted — that kills pan and click for the panel"
        after = _view(page, plot._id)
        assert abs(after["cx"] - before["cx"]) > 0.01, \
            "a bare drag did not pan the image"

    def test_shift_drag_paints_and_does_not_pan(self, interact_page):
        fig, plot, brush, page = _setup(interact_page)
        geom = _brush_geom(page, plot._id, brush.id)
        rect = _overlay_rect(page)
        before = _view(page, plot._id)

        _paint(page, geom, rect, [(20, 32), (44, 32)])

        w = _widget(page, plot._id)
        assert len(w["strokes"]) == 1, "Shift+drag did not paint one stroke"
        assert len(w["strokes"][0]) >= 3, \
            f"stroke has too few points: {w['strokes'][0]}"
        after = _view(page, plot._id)
        assert after["cx"] == pytest.approx(before["cx"], abs=1e-9), \
            "painting panned the image as well"

    def test_inactive_brush_is_ignored_and_still_pans(self, interact_page):
        """`active=False` parks the tool: the strokes stay drawn, the input
        goes back to the panel."""
        fig, plot, brush, page = _setup(interact_page, active=False)
        geom = _brush_geom(page, plot._id, brush.id)
        rect = _overlay_rect(page)
        before = _view(page, plot._id)

        _paint(page, geom, rect, [(20, 32), (44, 32)])

        assert _widget(page, plot._id)["strokes"] == [], \
            "an inactive brush painted"
        assert abs(_view(page, plot._id)["cx"] - before["cx"]) > 0.01, \
            "an inactive brush swallowed the pan"

    def test_shift_drag_over_another_widget_still_paints(self, interact_page):
        """Painting is modal: a scribble across the image must not be stolen
        half way by whatever widget happens to sit under the cursor."""
        fig, ax = apl.subplots(1, 1, figsize=(FIG_W, FIG_H))
        plot = ax.imshow(np.zeros((IMG, IMG), dtype=np.float32))
        brush = plot.add_brush_widget(radius=2.0)
        # Added AFTER the brush, so it is on top in the hit-test's z-order.
        plot.add_rectangle_widget(x=20, y=20, w=24, h=24)
        page = interact_page(fig)
        _collect_events(page)

        geom = _brush_geom(page, plot._id, brush.id)
        rect = _overlay_rect(page)
        _paint(page, geom, rect, [(24, 32), (40, 32)])   # straight through it

        widgets = page.evaluate(
            """(pid) => JSON.parse(
                    window._aplModel.get('panel_' + pid + '_json')
               ).overlay_widgets""", str(plot._id))
        bw = next(w for w in widgets if w["type"] == "brush")
        rw = next(w for w in widgets if w["type"] == "rectangle")
        assert len(bw["strokes"]) == 1, "the rectangle stole the paint gesture"
        assert (rw["x"], rw["y"], rw["w"], rw["h"]) == (20.0, 20.0, 24.0, 24.0), \
            "the rectangle moved or resized"

    def test_shift_click_paints_a_single_dot(self, interact_page):
        """A tap with no motion is a legitimate one-point stroke — the stroke
        opens on mousedown, not on the first move."""
        fig, plot, brush, page = _setup(interact_page)
        geom = _brush_geom(page, plot._id, brush.id)
        rect = _overlay_rect(page)

        px, py = _img_to_page(geom, rect, 32, 32)
        page.mouse.move(px, py)
        page.keyboard.down("Shift")
        page.mouse.down()
        page.mouse.up()
        page.keyboard.up("Shift")
        page.wait_for_timeout(80)

        w = _widget(page, plot._id)
        assert len(w["strokes"]) == 1 and len(w["strokes"][0]) == 1


@pytest.mark.usefixtures("interact_page")
class TestPainting:
    def test_stroke_points_are_image_pixels_along_the_drag(self, interact_page):
        fig, plot, brush, page = _setup(interact_page)
        geom = _brush_geom(page, plot._id, brush.id)
        rect = _overlay_rect(page)

        _paint(page, geom, rect, [(10, 40), (50, 40)])

        pts = _widget(page, plot._id)["strokes"][0]
        assert pts[0][0] == pytest.approx(10, abs=1.5)
        assert pts[-1][0] == pytest.approx(50, abs=1.5)
        assert all(abs(y - 40) < 1.5 for _x, y in pts), \
            "a horizontal drag wandered in y — coordinates are not image px"
        assert all(0 <= x < IMG and 0 <= y < IMG for x, y in pts)

    def test_multiple_drags_accumulate_strokes(self, interact_page):
        fig, plot, brush, page = _setup(interact_page)
        geom = _brush_geom(page, plot._id, brush.id)
        rect = _overlay_rect(page)

        _paint(page, geom, rect, [(10, 16), (50, 16)])
        _paint(page, geom, rect, [(10, 32), (50, 32)])
        _paint(page, geom, rect, [(10, 48), (50, 48)])

        w = _widget(page, plot._id)
        assert len(w["strokes"]) == 3
        assert len(w["stroke_classes"]) == 3
        ys = [round(w["strokes"][i][0][1]) for i in range(3)]
        assert ys == sorted(ys) and ys[0] != ys[-1]

    def test_the_stroke_draws_while_the_mouse_is_still_down(self, interact_page):
        """A brush that only appeared on release would be unusable. Nothing is
        pushed to the model until mouseup, so ``drawOverlay2d`` has to read the
        in-progress stroke out of the panel scratch to paint it live."""
        fig, ax = apl.subplots(1, 1, figsize=(FIG_W, FIG_H))
        plot = ax.imshow(np.zeros((IMG, IMG), dtype=np.float32))
        brush = plot.add_brush_widget(radius=3.0, alpha=1.0, colors=["#00ff00"])
        page = interact_page(fig)
        _collect_events(page)
        geom = _brush_geom(page, plot._id, brush.id)
        rect = _overlay_rect(page)

        x0, y0 = _img_to_page(geom, rect, 12, 32)
        x1, y1 = _img_to_page(geom, rect, 52, 32)
        page.mouse.move(x0, y0)
        page.keyboard.down("Shift")
        page.mouse.down()
        page.mouse.move(x1, y1, steps=8)
        # STILL HELD DOWN — nothing has been committed or pushed yet.
        assert _widget(page, plot._id)["strokes"] == [], \
            "the stroke reached the model before release"
        mid_geom = _brush_geom(page, plot._id, brush.id)
        assert mid_geom["n_strokes"] == 1, \
            "the in-progress stroke is not being drawn"
        assert len(mid_geom["strokes"][0]) >= 3
        assert _count_overlay_color(page, (0, 255, 0)) > 200, \
            "nothing is painted on the overlay canvas mid-drag"

        page.mouse.up()
        page.keyboard.up("Shift")
        page.wait_for_timeout(80)
        assert len(_widget(page, plot._id)["strokes"]) == 1

    def test_a_model_echo_mid_stroke_does_not_wipe_it(self, interact_page):
        """The panel trait stays STALE for the whole stroke — that is the point of
        emitting once on release. So any unrelated ``save_changes()`` re-fires
        ``change:panel_<id>_json`` and replaces ``p.state`` from that stale value.
        The stroke therefore cannot live in ``p.state``; it lives in a per-panel
        scratch. In normal use a ``pointer_leave`` emit (cursor crossing the panel
        edge while painting) is enough to trigger this."""
        fig, plot, brush, page = _setup(interact_page)
        geom = _brush_geom(page, plot._id, brush.id)
        rect = _overlay_rect(page)

        x0, y0 = _img_to_page(geom, rect, 10, 32)
        xm, ym = _img_to_page(geom, rect, 32, 32)
        x1, y1 = _img_to_page(geom, rect, 54, 32)
        page.mouse.move(x0, y0)
        page.keyboard.down("Shift")
        page.mouse.down()
        page.mouse.move(xm, ym, steps=8)
        page.evaluate("() => window._aplModel.save_changes()")   # the echo
        page.mouse.move(x1, y1, steps=8)
        page.mouse.up()
        page.keyboard.up("Shift")
        page.wait_for_timeout(80)

        w = _widget(page, plot._id)
        assert len(w["strokes"]) == 1, "the echo split or dropped the stroke"
        xs = [x for x, _y in w["strokes"][0]]
        assert min(xs) == pytest.approx(10, abs=1.5), \
            "the echo wiped the first half of the stroke"
        assert max(xs) == pytest.approx(54, abs=1.5)

    def test_points_outside_the_image_are_dropped(self, interact_page):
        """A label coordinate outside the array is useless to a consumer, and a
        negative index silently wraps."""
        fig, plot, brush, page = _setup(interact_page)
        geom = _brush_geom(page, plot._id, brush.id)
        rect = _overlay_rect(page)

        # Start inside, drag well past the right edge of the image.
        _paint(page, geom, rect, [(32, 32), (IMG + 40, 32)])

        w = _widget(page, plot._id)
        assert w["strokes"], "nothing was painted at all"
        for stroke in w["strokes"]:
            for x, y in stroke:
                assert 0 <= x < IMG and 0 <= y < IMG, f"out-of-image point {x},{y}"


@pytest.mark.usefixtures("interact_page")
class TestClassColours:
    def test_the_active_class_tags_and_colours_the_stroke(self, interact_page):
        """One brush, several label classes: the stroke records ``class_id`` and
        draws in ``colors[class_id]``."""
        fig, ax = apl.subplots(1, 1, figsize=(FIG_W, FIG_H))
        plot = ax.imshow(np.zeros((IMG, IMG), dtype=np.float32))
        brush = plot.add_brush_widget(radius=3.0, class_id=1, alpha=1.0,
                                     colors=["#ff0000", "#00ff00"])
        page = interact_page(fig)
        _collect_events(page)
        geom = _brush_geom(page, plot._id, brush.id)
        rect = _overlay_rect(page)

        _paint(page, geom, rect, [(12, 32), (52, 32)])

        w = _widget(page, plot._id)
        assert w["stroke_classes"] == [1], "the stroke lost its class"
        green = _count_overlay_color(page, (0, 255, 0))
        red = _count_overlay_color(page, (255, 0, 0))
        assert green > 200, f"class 1 did not draw in colors[1] (green={green})"
        assert red == 0, f"class 1 drew in colors[0] as well (red={red})"

    def test_class_zero_uses_the_first_colour(self, interact_page):
        fig, ax = apl.subplots(1, 1, figsize=(FIG_W, FIG_H))
        plot = ax.imshow(np.zeros((IMG, IMG), dtype=np.float32))
        brush = plot.add_brush_widget(radius=3.0, class_id=0, alpha=1.0,
                                     colors=["#ff0000", "#00ff00"])
        page = interact_page(fig)
        _collect_events(page)
        geom = _brush_geom(page, plot._id, brush.id)
        rect = _overlay_rect(page)

        _paint(page, geom, rect, [(12, 32), (52, 32)])

        assert _widget(page, plot._id)["stroke_classes"] == [0]
        assert _count_overlay_color(page, (255, 0, 0)) > 200
        assert _count_overlay_color(page, (0, 255, 0)) == 0

    def test_switching_class_from_python_retags_the_next_stroke(
            self, interact_page):
        """The real multi-class workflow: the host flips ``class_id`` between
        strokes (a class button in its UI). That arrives as the standard
        Python->JS targeted widget update, so the NEXT stroke must pick up the
        new class and its colour — and the stroke already painted must keep
        its own."""
        fig, ax = apl.subplots(1, 1, figsize=(FIG_W, FIG_H))
        plot = ax.imshow(np.zeros((IMG, IMG), dtype=np.float32))
        brush = plot.add_brush_widget(radius=3.0, alpha=1.0,
                                     colors=["#ff0000", "#00ff00"])
        page = interact_page(fig)
        _collect_events(page)
        geom = _brush_geom(page, plot._id, brush.id)
        rect = _overlay_rect(page)

        _paint(page, geom, rect, [(12, 20), (52, 20)])          # class 0

        # The second stroke is driven by hand rather than through _paint, because
        # the ORDER matters and it is not the brush's doing: Figure._push_widget
        # deliberately never writes panel_<id>_json (see its docstring), so the
        # panel trait stays stale after a targeted widget update — and the very
        # next `save_changes()` from anything (here the Shift key_down emit)
        # re-fires change:panel_<id>_json and reverts it. So press Shift FIRST,
        # then push the class, then drag. This exposure is pre-existing and
        # applies to every widget's targeted updates, not just this one.
        x0, y0 = _img_to_page(geom, rect, 12, 44)
        x1, y1 = _img_to_page(geom, rect, 52, 44)
        page.mouse.move(x0, y0)
        page.keyboard.down("Shift")
        # Exactly what Figure._push_widget sends for `brush.class_id = 1`.
        page.evaluate(
            """([pid, wid]) => window._aplModel.set('event_json', JSON.stringify(
                   {source: 'python', panel_id: pid, widget_id: wid,
                    class_id: 1}))""",
            [str(plot._id), str(brush.id)])
        page.mouse.down()
        page.mouse.move(x1, y1, steps=6)
        page.mouse.up()
        page.keyboard.up("Shift")
        page.wait_for_timeout(80)

        w = _widget(page, plot._id)
        assert w["stroke_classes"] == [0, 1], \
            "the class switch did not retag the next stroke"
        assert _count_overlay_color(page, (255, 0, 0)) > 200
        assert _count_overlay_color(page, (0, 255, 0)) > 200

    def test_seeded_multiclass_strokes_draw_in_both_colours(self, interact_page):
        """Both classes coexist in ONE widget — that is the point of the
        ``colors`` list."""
        fig, ax = apl.subplots(1, 1, figsize=(FIG_W, FIG_H))
        plot = ax.imshow(np.zeros((IMG, IMG), dtype=np.float32))
        plot.add_brush_widget(radius=3.0, alpha=1.0,
                             colors=["#ff0000", "#00ff00"],
                             strokes=[[(8, 20), (56, 20)],
                                      [(8, 44), (56, 44)]],
                             stroke_classes=[0, 1])
        page = interact_page(fig)
        assert _count_overlay_color(page, (255, 0, 0)) > 200
        assert _count_overlay_color(page, (0, 255, 0)) > 200


@pytest.mark.usefixtures("interact_page")
class TestErase:
    def test_erase_removes_points_under_the_brush(self, interact_page):
        fig, plot, brush, page = _setup(
            interact_page, erase=True,
            strokes=[[(x, 32) for x in range(8, 57, 2)]])
        geom = _brush_geom(page, plot._id, brush.id)
        rect = _overlay_rect(page)
        before = len(_widget(page, plot._id)["strokes"][0])
        assert before >= 20

        _paint(page, geom, rect, [(8, 32), (30, 32)])   # erase the left half

        after = _widget(page, plot._id)
        kept = sum(len(s) for s in after["strokes"])
        assert kept < before, "erase removed nothing"
        assert kept > 0, "erase wiped the whole stroke"
        assert all(x > 30 for s in after["strokes"] for x, _y in s), \
            "points under the erase drag survived"

    def test_erasing_the_middle_splits_the_stroke(self, interact_page):
        """A surviving RUN becomes its own stroke. Filtering in place instead
        would rejoin the ends with one straight segment right across the gap the
        user just erased."""
        fig, plot, brush, page = _setup(
            interact_page, erase=True,
            strokes=[[(x, 32) for x in range(8, 57, 2)]])
        geom = _brush_geom(page, plot._id, brush.id)
        rect = _overlay_rect(page)

        px, py = _img_to_page(geom, rect, 32, 32)
        page.mouse.move(px, py)
        page.keyboard.down("Shift")
        page.mouse.down()
        page.mouse.up()
        page.keyboard.up("Shift")
        page.wait_for_timeout(80)

        after = _widget(page, plot._id)
        assert len(after["strokes"]) == 2, \
            f"expected two fragments, got {len(after['strokes'])}"
        assert len(after["stroke_classes"]) == 2, "classes lost the split"
        assert max(x for x, _ in after["strokes"][0]) < \
            min(x for x, _ in after["strokes"][1])

    def test_erase_does_not_paint(self, interact_page):
        fig, plot, brush, page = _setup(interact_page, erase=True)
        geom = _brush_geom(page, plot._id, brush.id)
        rect = _overlay_rect(page)

        _paint(page, geom, rect, [(12, 32), (52, 32)])

        assert _widget(page, plot._id)["strokes"] == [], \
            "an erase drag painted a stroke"


@pytest.mark.usefixtures("interact_page")
class TestEmitOncePerStroke:
    """The performance contract. Widget drags in figure_esm.js are unthrottled:
    without the local-accumulate design every mousemove would re-serialise the
    whole (growing) stroke list into BOTH panel_<id>_json and event_json."""

    def test_exactly_one_event_per_stroke(self, interact_page):
        fig, plot, brush, page = _setup(interact_page)
        geom = _brush_geom(page, plot._id, brush.id)
        rect = _overlay_rect(page)

        _paint(page, geom, rect, [(10, 32), (54, 32)], steps=20)

        mine = [e for e in _get_events(page)
                if e.get("widget_id") == brush.id]
        assert len(mine) == 1, \
            f"expected 1 event per stroke, got {len(mine)}: " \
            f"{[e['event_type'] for e in mine]}"
        assert mine[0]["event_type"] == "pointer_up"
        assert len(mine[0]["strokes"][0]) >= 5, \
            "the one event did not carry the finished stroke"

    def test_no_pointer_move_is_emitted_while_painting(self, interact_page):
        fig, plot, brush, page = _setup(interact_page)
        geom = _brush_geom(page, plot._id, brush.id)
        rect = _overlay_rect(page)

        _paint(page, geom, rect, [(10, 32), (54, 32)], steps=20)

        moves = _get_events(page, "pointer_move")
        assert moves == [], \
            f"{len(moves)} pointer_move events fired during one stroke"

    def test_three_strokes_are_three_events(self, interact_page):
        fig, plot, brush, page = _setup(interact_page)
        geom = _brush_geom(page, plot._id, brush.id)
        rect = _overlay_rect(page)

        for y in (16, 32, 48):
            _paint(page, geom, rect, [(10, y), (54, y)], steps=12)

        mine = [e for e in _get_events(page) if e.get("widget_id") == brush.id]
        assert len(mine) == 3, f"got {len(mine)} events for 3 strokes"
        assert all(e["event_type"] == "pointer_up" for e in mine)
        # The last event carries the cumulative stroke list, not just its own.
        assert len(mine[-1]["strokes"]) == 3

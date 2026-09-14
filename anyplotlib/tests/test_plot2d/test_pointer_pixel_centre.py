"""
2-D pointer coordinates use the pixel-CENTRE convention (GH #72).

``_imgToCanvas2d`` places image coordinate *i* at the centre of pixel *i*, as
marker offsets, widget positions and :meth:`Plot2D.display_to_data` all do.
``_canvasToImg2d`` used to skip the matching ``-0.5``, so every pointer event
read half a pixel right and down of anything drawn at the same spot, and a
handler doing ``round(event.img_x)`` got pixel ``i + 1`` for the right half of
pixel ``i``.
"""
from __future__ import annotations

import pathlib

import numpy as np
import pytest

import anyplotlib as apl
from anyplotlib.tests.test_interactive._event_test_utils import (
    GRID_PAD, _collect_events, _get_events,
)

_ESM = pathlib.Path(apl.__file__).parent / "figure_esm.js"


def _grab(src: str, name: str) -> str:
    """The source of top-level ``function name(...) {...}`` in figure_esm.js."""
    start = src.index(f"function {name}(")
    depth, i = 0, src.index("{", start)
    while True:
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                return src[start:i + 1]
        i += 1


@pytest.fixture(scope="module")
def coord_fns(_pw_browser):
    """A blank page exposing the renderer's pure 2-D coordinate helpers."""
    src = _ESM.read_text(encoding="utf-8")
    names = ["_imgFitRect", "_imgToCanvas2d", "_canvasToImg2d", "_axisFracToVal",
             "_imgPix2d", "_inImgAxis2d", "_imgToAxisVal2d"]
    page = _pw_browser.new_page()
    page.evaluate(
        "src => { window._apl = new Function(src)(); }",
        "\n".join(_grab(src, n) for n in names)
        + "\nreturn {" + ", ".join(names) + "};",
    )
    yield page
    page.close()


class TestRoundTrip:
    @pytest.mark.parametrize("zoom", [0.5, 1.0, 2.0, 4.0, 37.0])
    @pytest.mark.parametrize("center", [0.5, 0.1, 0.93])
    def test_canvas_to_img_inverts_img_to_canvas(self, coord_fns, zoom, center):
        worst = coord_fns.evaluate("""([zoom, c]) => {
            const st = {image_width: 512, image_height: 384, zoom,
                        center_x: c, center_y: 1 - c};
            let worst = 0;
            for (const i of [0, 0.25, 100, 383, 511]) {
              const [cx, cy] = _apl._imgToCanvas2d(i, i, st, 1024, 768);
              const [bx, by] = _apl._canvasToImg2d(cx, cy, st, 1024, 768);
              worst = Math.max(worst, Math.abs(bx - i), Math.abs(by - i));
            }
            return worst;
        }""", [zoom, center])
        assert worst < 1e-9, f"round trip is off by {worst} image px"

    def test_pixel_spans_half_a_pixel_either_side_of_its_centre(self, coord_fns):
        got = coord_fns.evaluate("""() => [
            _apl._imgPix2d(7.51), _apl._imgPix2d(8.0), _apl._imgPix2d(8.49),
            _apl._imgPix2d(-0.5), _apl._inImgAxis2d(-0.5, 16),
            _apl._inImgAxis2d(-0.51, 16), _apl._inImgAxis2d(15.49, 16),
            _apl._inImgAxis2d(15.5, 16)]""")
        assert got == [8, 8, 8, 0, True, False, True, False]


class TestAxisValue:
    def test_imshow_pixel_centre_reads_its_axis_value(self, coord_fns):
        """imshow axes hold one value per pixel centre: pixel i is exactly
        x_axis[i], and the outer half of an edge pixel continues the spacing
        instead of clamping."""
        got = coord_fns.evaluate("""() => {
            const ax = Array.from({length: 16}, (_, k) => 10 + 0.5 * k);
            const st = {};
            return [0, 8, 15, -0.5, 15.5].map(i => _apl._imgToAxisVal2d(st, ax, i, 16));
        }""")
        assert got == pytest.approx([10.0, 14.0, 17.5, 9.75, 17.75])

    def test_mesh_reads_its_edges_as_before(self, coord_fns):
        """pcolormesh axes are the n + 1 cell edges: the centre of cell i is
        the midpoint of edges i and i + 1 — the value the old edge-convention
        formula already produced, so mesh xdata does not move."""
        got = coord_fns.evaluate("""() => {
            const edges = [0, 1, 3, 6, 10];
            const st = {is_mesh: true};
            return [0, 1, 3].map(i => _apl._imgToAxisVal2d(st, edges, i, 4));
        }""")
        assert got == pytest.approx([0.5, 2.0, 8.0])

    def test_no_axis_falls_back_to_the_image_coordinate(self, coord_fns):
        assert coord_fns.evaluate(
            "() => _apl._imgToAxisVal2d({}, [], 3.25, 16)") == pytest.approx(3.25)


# ── in the real renderer ──────────────────────────────────────────────────────

# 16×16 image at 16 canvas px per image px, no axis gutters (see
# TestMarkerPixelCenterAlignment in test_events_regression.py).
_PAD_T = 12
_FIG_W, _FIG_H = 16 * 16, 16 * 16 + _PAD_T


def _click(page, plot, ix, iy):
    """Click the page point where image coordinate (ix, iy) is drawn.

    ``data_to_display`` is the centre-convention Python mirror of
    ``_imgToCanvas2d`` (checked against screenshots in test_coord_conversion),
    so the event must hand back the coordinate it was given.
    """
    x, y = plot.data_to_display([ix, iy])
    page.mouse.click(GRID_PAD + x, GRID_PAD + y)
    page.wait_for_timeout(120)
    events = _get_events(page, "pointer_down")
    assert events, "a click on the image must emit pointer_down"
    return events[-1]


class TestPointerEvents:
    def test_click_on_a_pixel_centre_reports_that_coordinate(self, interact_page):
        fig, ax = apl.subplots(1, 1, figsize=(_FIG_W, _FIG_H))
        plot = ax.imshow(np.zeros((16, 16)))
        page = interact_page(fig)
        _collect_events(page)

        e = _click(page, plot, 8.0, 5.0)
        # One canvas px is 1/16 image px; allow for the integer mouse position.
        assert e["img_x"] == pytest.approx(8.0, abs=0.1), e
        assert e["img_y"] == pytest.approx(5.0, abs=0.1), e

    def test_right_half_of_a_pixel_rounds_to_that_pixel(self, interact_page):
        """The failure the issue describes: +0.375 px into pixel 8 used to read
        8.875, which rounds to 9."""
        fig, ax = apl.subplots(1, 1, figsize=(_FIG_W, _FIG_H))
        plot = ax.imshow(np.zeros((16, 16)))
        page = interact_page(fig)
        _collect_events(page)

        e = _click(page, plot, 8.375, 8.375)
        assert (round(e["img_x"]), round(e["img_y"])) == (8, 8), e

    def test_imshow_xdata_is_the_axis_value_of_the_clicked_pixel(self, interact_page):
        fig, ax = apl.subplots(1, 1, figsize=(400, 400))
        plot = ax.imshow(np.zeros((16, 16)),
                         axes=[np.arange(16) * 0.5, np.arange(16) * 2.0])
        page = interact_page(fig)
        _collect_events(page)

        e = _click(page, plot, 4.0, 11.0)
        scale = plot.plot_box()["width"] / 16          # canvas px per image px
        tol = 1.0 / scale                              # one canvas px, in image px
        assert e["img_x"] == pytest.approx(4.0, abs=tol), e
        assert e["xdata"] == pytest.approx(0.5 * e["img_x"], abs=1e-9), e
        assert e["ydata"] == pytest.approx(2.0 * e["img_y"], abs=1e-9), e

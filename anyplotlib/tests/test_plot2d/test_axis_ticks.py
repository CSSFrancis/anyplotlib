"""
2-D tick gutters label the pixels they sit next to.

imshow axis arrays hold one value per pixel CENTRE.  The gutters used to take a
value's fraction of the axis array as a fraction of the gutter, so the first and
last centres landed on the gutter's two ends — every label stretched outward by
up to half a pixel — and a letterboxed image's ticks ignored its offset inside
the gutter altogether.  Ticks now go through ``_imgToCanvas2d``, the transform
markers and pointer events use, and ``set_view`` / ``set_xlim`` read the axis
the same way.

The rendering tests find the tick marks in a real screenshot and compare them
with :meth:`Plot2D.data_to_display` (itself checked against drawn markers in
``test_layouts/test_coord_conversion.py``).
"""
from __future__ import annotations

import pathlib

import numpy as np
import pytest

import anyplotlib as apl

GRID_PAD = 8
_ESM = pathlib.Path(apl.__file__).parent / "figure_esm.js"


def _dark_runs(line: np.ndarray, thresh: int = 40) -> list[float]:
    """Centres of runs of pixels clearly darker than the line's background."""
    lum = line[..., :3].astype(int).sum(axis=-1) / 3
    bg = np.median(lum)
    hit = np.flatnonzero(bg - lum > thresh)
    if not len(hit):
        return []
    runs, start = [], hit[0]
    for a, b in zip(hit[:-1], hit[1:]):
        if b != a + 1:
            runs.append((start + a) / 2)
            start = b
    runs.append((start + hit[-1]) / 2)
    return runs


def _x_ticks(img, plot):
    """Page x of every tick mark under the image (3 px into the x gutter)."""
    box = plot.plot_box()
    row = int(round(GRID_PAD + box["y"] + box["height"] + 3))
    return _dark_runs(img[row])


def _y_ticks(img, plot):
    """Page y of every tick mark left of the image (3 px into the y gutter)."""
    box = plot.plot_box()
    col = int(round(GRID_PAD + box["x"] - 3))
    return _dark_runs(img[:, col])


def _near(ticks, want, tol=1.5):
    return all(any(abs(t - w) <= tol for t in ticks) for w in want)


class TestTicksSitOnPixelCentres:
    def test_pillarboxed_x_ticks(self, take_screenshot):
        """A 6×4 image in a wide panel: the fit rect is offset inside the
        gutter, and tick i must sit under the centre of column i."""
        fig, ax = apl.subplots(1, 1, figsize=(520, 330))
        plot = ax.imshow(np.zeros((4, 6)), axes=[np.arange(6.0), np.arange(4.0)])
        ticks = _x_ticks(take_screenshot(fig), plot)
        want = [GRID_PAD + plot.data_to_display([i, 0])[0] for i in range(6)]
        assert _near(ticks, want), f"ticks at {ticks}, pixel centres at {want}"

    def test_letterboxed_y_ticks(self, take_screenshot):
        fig, ax = apl.subplots(1, 1, figsize=(420, 460))
        plot = ax.imshow(np.zeros((4, 6)), axes=[np.arange(6.0), np.arange(4.0)])
        ticks = _y_ticks(take_screenshot(fig), plot)
        want = [GRID_PAD + plot.data_to_display([0, j])[1] for j in range(4)]
        assert _near(ticks, want), f"ticks at {ticks}, pixel centres at {want}"

    def test_scaled_axis_ticks_follow_zoom_and_pan(self, take_screenshot):
        """Physical units, zoomed into an off-centre window: tick v sits at the
        pixel coordinate (v - x0) / dx."""
        fig, ax = apl.subplots(1, 1, figsize=(500, 360))
        dx = 0.25
        plot = ax.imshow(np.zeros((40, 50)),
                         axes=[10.0 + dx * np.arange(50), dx * np.arange(40)])
        plot.set_view(x0=12.0, x1=15.0, y0=2.0, y1=4.5)
        img = take_screenshot(fig)
        ticks = _x_ticks(img, plot)
        want = [GRID_PAD + plot.data_to_display([(v - 10.0) / dx, 0])[0]
                for v in (12.5, 13.0, 13.5, 14.0, 14.5)]
        assert _near(ticks, want), f"ticks at {ticks}, values at {want}"

    def test_descending_y_axis_is_ticked(self, take_screenshot):
        """origin='lower' reverses the y axis; its labels still land on their
        rows."""
        fig, ax = apl.subplots(1, 1, figsize=(420, 460))
        plot = ax.imshow(np.zeros((4, 6)), axes=[np.arange(6.0), np.arange(4.0)],
                         origin="lower")
        ticks = _y_ticks(take_screenshot(fig), plot)
        # Row 0 of the displayed image is the TOP, which carries y = 3.
        want = [GRID_PAD + plot.data_to_display([0, 3 - v])[1] for v in range(4)]
        assert _near(ticks, want), f"ticks at {ticks}, rows at {want}"

    def test_mesh_ticks_still_span_the_cell_edges(self, take_screenshot):
        """pcolormesh axes are the n + 1 edges: edge k sits at the leading edge
        of cell k.  The centre convention does not apply to them, but they
        shared the letterbox bug — a pillarboxed mesh's ticks ran across the
        whole gutter too."""
        fig, ax = apl.subplots(1, 1, figsize=(520, 330))
        plot = ax.pcolormesh(np.zeros((4, 6)), x_edges=np.arange(7.0),
                             y_edges=np.arange(5.0))
        ticks = _x_ticks(take_screenshot(fig), plot)
        want = [GRID_PAD + plot.data_to_display([k - 0.5, 0])[0] for k in range(7)]
        assert _near(ticks, want), f"ticks at {ticks}, cell edges at {want}"


class TestSetView:
    def test_whole_extent_is_zoom_one(self):
        fig, ax = apl.subplots(1, 1)
        plot = ax.imshow(np.zeros((16, 32)))
        plot.set_view(x0=-0.5, x1=31.5, y0=-0.5, y1=15.5)
        assert plot._state["zoom"] == pytest.approx(1.0)
        assert plot._state["center_x"] == pytest.approx(0.5)
        assert plot._state["center_y"] == pytest.approx(0.5)

    def test_window_between_pixel_centres(self):
        """x0 and x1 are where the view's edges land: [7.5, 23.5] on a 32 px
        arange axis is columns 8..23 — half the image, centred."""
        fig, ax = apl.subplots(1, 1)
        plot = ax.imshow(np.zeros((32, 32)))
        plot.set_xlim(7.5, 23.5)
        assert plot._state["zoom"] == pytest.approx(2.0)
        assert plot._state["center_x"] == pytest.approx(0.5)

    def test_physical_units(self):
        fig, ax = apl.subplots(1, 1)
        plot = ax.imshow(np.zeros((10, 40)),
                         axes=[100.0 + 0.5 * np.arange(40), None])
        plot.set_xlim(104.75, 109.75)       # pixel coords 9.5 .. 19.5
        assert plot._state["zoom"] == pytest.approx(4.0)
        assert plot._state["center_x"] == pytest.approx(15.0 / 40)

    def test_descending_axis(self):
        """origin='lower' stores a descending y axis; set_ylim(lo, hi) must
        still zoom (both orders of the ends are accepted)."""
        fig, ax = apl.subplots(1, 1)
        plot = ax.imshow(np.zeros((32, 32)), origin="lower")
        plot.set_ylim(7.5, 23.5)
        assert plot._state["zoom"] == pytest.approx(2.0)
        assert plot._state["center_y"] == pytest.approx(0.5)

    def test_mesh_keeps_edge_mapping(self):
        fig, ax = apl.subplots(1, 1)
        plot = ax.pcolormesh(np.zeros((8, 8)), x_edges=np.arange(9.0),
                             y_edges=np.arange(9.0))
        plot.set_xlim(2.0, 6.0)
        assert plot._state["zoom"] == pytest.approx(2.0)
        assert plot._state["center_x"] == pytest.approx(0.5)


def _grab(src: str, name: str) -> str:
    start = src.index(f"function {name}(")
    depth, i = 0, src.index("{", start)
    while True:
        depth += {"{": 1, "}": -1}.get(src[i], 0)
        if depth == 0:
            return src[start:i + 1]
        i += 1


class TestJsPythonParity:
    """``_axisValToImg2d`` (JS ticks) and ``Plot2D._axis_extent_frac`` (Python
    set_view) must agree, and the JS pair must invert each other."""

    @pytest.fixture(scope="class")
    def js(self, _pw_browser):
        src = _ESM.read_text(encoding="utf-8")
        names = ["_axisFracToVal", "_imgToAxisVal2d", "_axisValToImg2d"]
        page = _pw_browser.new_page()
        page.evaluate("src => { window._apl = new Function(src)(); }",
                      "\n".join(_grab(src, n) for n in names)
                      + "\nreturn {" + ", ".join(names) + "};")
        yield page
        page.close()

    @pytest.mark.parametrize("arr", [
        list(np.arange(12.0)),
        list(3.0 - 0.4 * np.arange(12)),                  # descending
        list(np.cumsum(np.linspace(0.5, 2.0, 12))),       # non-uniform
    ])
    def test_round_trip_and_parity(self, js, arr):
        n = 12
        coords = [-0.5, -0.2, 0.0, 3.3, 7.0, 11.0, 11.5]
        back = js.evaluate("""([arr, n, cs]) => cs.map(c =>
            _apl._axisValToImg2d(arr, _apl._imgToAxisVal2d({}, arr, c, n), n))""",
                           [arr, n, coords])
        assert back == pytest.approx(coords, abs=1e-9)

        fig, ax = apl.subplots(1, 1)
        plot = ax.imshow(np.zeros((4, n)), axes=[np.asarray(arr), None])
        vals = js.evaluate("""([arr, n, cs]) => cs.map(c =>
            _apl._imgToAxisVal2d({}, arr, c, n))""", [arr, n, coords])
        fracs = [plot._axis_extent_frac(arr, v, n) for v in vals]
        assert fracs == pytest.approx([(c + 0.5) / n for c in coords], abs=1e-9)

"""
Playwright tests for the navigated-embed runtime.

The page under test is the real product: ``navigated_html`` output opened from
``file://``, with the data it navigates packed into it.  Dragging the
navigator's crosshair has to put the right frame on the signal panel, put the
right overlay rows on top of it, and a detector on the signal panel has to
reduce the whole block back onto the navigator.
"""
from __future__ import annotations

import pathlib
import tempfile

import numpy as np
import pytest

import anyplotlib as apl
from anyplotlib.embed import Ragged, navigated_html

NAV_SHAPE = (8, 8)
SIGNAL_SHAPE = (64, 64)
ROWS_PER_POSITION = 3

# The renderer names a live binary frame with this prefix (figure_esm.js).
BINARY_TOKEN_PREFIX = "\u0000bin:"


def _dataset():
    """A dense (8, 8, 64, 64) block plus a ragged block of three rows each."""
    rng = np.random.default_rng(7)
    signal = rng.integers(0, 256, size=NAV_SHAPE + SIGNAL_SHAPE).astype(np.uint8)
    positions = NAV_SHAPE[0] * NAV_SHAPE[1]
    rows = positions * ROWS_PER_POSITION
    spots = Ragged(
        offsets=np.arange(0, rows + 1, ROWS_PER_POSITION, dtype=np.int32)[:positions + 1],
        columns={"x": (rng.random(rows) * 63).astype(np.float32),
                 "y": (rng.random(rows) * 63).astype(np.float32),
                 "intensity": (rng.random(rows) * 100 + 1).astype(np.float32)},
        nav_shape=NAV_SHAPE,
    )
    return signal, spots


def _to_codes(values, low, high):
    """The Python-side quantiser the runtime's toU8 mirrors."""
    scaled = (np.asarray(values, dtype=np.float64) - low) / ((high - low) or 1) * 255.0
    return np.clip(scaled, 0, 255).astype(np.uint8)


@pytest.fixture
def navigated_page(_pw_browser):
    """Open a ``navigated_html`` page and return the live Page."""
    pages, paths = [], []

    def _open(html):
        with tempfile.NamedTemporaryFile(
                suffix=".html", mode="w", encoding="utf-8", delete=False) as fh:
            fh.write(html)
            tmp = pathlib.Path(fh.name)
        paths.append(tmp)
        page = _pw_browser.new_page()
        pages.append(page)
        page.goto(tmp.as_uri())
        page.wait_for_function("() => window._aplReady === true", timeout=20_000)
        page.evaluate(
            "() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))")
        return page

    yield _open
    for page in pages:
        try:
            page.close()
        except Exception:
            pass
    for path in paths:
        path.unlink(missing_ok=True)


def _build_page(signal, spots, *, overlays=True, detector=True,
                navigator_widget="crosshair"):
    """A navigator + signal figure wired to the two blocks."""
    fig, axes = apl.subplots(1, 2, figsize=(640, 320))
    navigator = axes[0].imshow(signal.sum(axis=(2, 3)).astype(np.float32), cmap="gray")
    signal_plot = axes[1].imshow(signal[0, 0], cmap="gray")

    if navigator_widget == "crosshair":
        navigator.add_widget("crosshair", cx=0, cy=0)
    else:
        navigator.add_widget("rectangle", x=1, y=2, w=3, h=2)
    if detector:
        signal_plot.add_widget("rectangle", x=8, y=12, w=16, h=10)

    driven = {"panel_id": signal_plot._id, "role": "driven",
              "frame": {"block": "signal", "kind": "image", "levels": [0, 255]}}
    if overlays:
        driven["overlays"] = [{"block": "spots", "kind": "circles",
                               "style": {"radius": 4, "color": "#00ff00"}}]
    if detector:
        driven["reduce"] = {"block": "signal", "navigator_panel": navigator._id}

    html = navigated_html(
        fig, {"signal": signal, "spots": spots},
        [{"panel_id": navigator._id, "role": "navigator"}, driven],
        title="Navigated", caption="crosshair drives the frame")
    return html, navigator._id, signal_plot._id


_CLIENT_POINT = """
(args) => {
  const [panelId, ix, iy] = args;
  const panel = window._aplHandle.api.panels.get(panelId);
  const state = panel.state;
  const scale = Math.min(panel.imgW / state.image_width,
                         panel.imgH / state.image_height);
  const fitWidth = state.image_width * scale, fitHeight = state.image_height * scale;
  const x = (panel.imgW - fitWidth) / 2 + (ix + 0.5) / state.image_width * fitWidth;
  const y = (panel.imgH - fitHeight) / 2 + (iy + 0.5) / state.image_height * fitHeight;
  const rect = panel.overlayCanvas.getBoundingClientRect();
  return [rect.left + x * (rect.width / panel.imgW),
          rect.top + y * (rect.height / panel.imgH)];
}
"""

_PAINTED_CODES = """
(panelId) => Array.from(
  window._aplHandle.api.panels.get(panelId).state.image_b64_bytes || [])
"""


def _client_point(page, panel_id, ix, iy):
    return page.evaluate(_CLIENT_POINT, [panel_id, ix, iy])


def _painted_codes(page, panel_id):
    return np.asarray(page.evaluate(_PAINTED_CODES, panel_id), dtype=np.uint8)


def _drag(page, panel_id, start, end):
    x0, y0 = _client_point(page, panel_id, *start)
    x1, y1 = _client_point(page, panel_id, *end)
    page.mouse.move(x0, y0)
    page.mouse.down()
    page.mouse.move(x1, y1, steps=4)
    page.mouse.up()
    page.evaluate(
        "() => new Promise(r => requestAnimationFrame("
        "  () => requestAnimationFrame(() => requestAnimationFrame(r))))")


class TestCrosshairDrivesTheFrame:
    def test_dragged_index_paints_that_frame(self, navigated_page):
        signal, spots = _dataset()
        html, navigator_id, signal_id = _build_page(signal, spots, detector=False)
        page = navigated_page(html)

        # The initial dispatch is position (0, 0).
        assert np.array_equal(_painted_codes(page, signal_id), signal[0, 0].ravel())

        _drag(page, navigator_id, (0, 0), (5, 3))
        assert page.evaluate("() => window._aplHandle.index") == [3, 5]
        assert np.array_equal(_painted_codes(page, signal_id), signal[3, 5].ravel())

    def test_canvas_pixels_match_the_frame(self, navigated_page):
        signal, spots = _dataset()
        html, navigator_id, signal_id = _build_page(signal, spots, detector=False,
                                                    overlays=False)
        page = navigated_page(html)
        _drag(page, navigator_id, (0, 0), (6, 2))

        samples = [(3, 5), (31, 40), (60, 9)]
        painted = page.evaluate(
            """(args) => {
              const [panelId, points] = args;
              const panel = window._aplHandle.api.panels.get(panelId);
              const state = panel.state;
              const scale = Math.min(panel.imgW / state.image_width,
                                     panel.imgH / state.image_height);
              const fitWidth = state.image_width * scale;
              const fitHeight = state.image_height * scale;
              const left = (panel.imgW - fitWidth) / 2;
              const top = (panel.imgH - fitHeight) / 2;
              const device = panel.plotCanvas.width / panel.imgW;
              const context = panel.plotCanvas.getContext('2d');
              return points.map(([ix, iy]) => {
                const x = Math.floor((left + (ix + 0.5) / state.image_width * fitWidth) * device);
                const y = Math.floor((top + (iy + 0.5) / state.image_height * fitHeight) * device);
                const d = context.getImageData(x, y, 1, 1).data;
                return [d[0], d[1], d[2]];
              });
            }""",
            [signal_id, [[ix, iy] for ix, iy in samples]])
        lookup = page.evaluate(
            "(id) => window._aplHandle.api.panels.get(id).state.colormap_data",
            signal_id)
        for (ix, iy), rgb in zip(samples, painted):
            expected = lookup[int(signal[2, 6, iy, ix])]
            assert rgb == expected, f"pixel ({ix}, {iy}) painted {rgb}, expected {expected}"


class TestRaggedOverlay:
    def test_circles_land_on_their_rows(self, navigated_page):
        signal, spots = _dataset()
        html, navigator_id, signal_id = _build_page(signal, spots, detector=False)
        page = navigated_page(html)
        _drag(page, navigator_id, (0, 0), (2, 4))

        markers = page.evaluate(
            "(id) => window._aplHandle.api.panels.get(id).state.markers", signal_id)
        assert len(markers) == 1 and markers[0]["type"] == "circles"
        position = 4 * NAV_SHAPE[1] + 2
        start = position * ROWS_PER_POSITION
        expected = np.stack([spots.columns["x"][start:start + ROWS_PER_POSITION],
                             spots.columns["y"][start:start + ROWS_PER_POSITION]], axis=1)
        assert np.allclose(np.asarray(markers[0]["offsets"]), expected, atol=1e-4)
        assert markers[0]["sizes"] == [4, 4, 4]

    def test_marker_canvas_has_ink_where_a_row_sits(self, navigated_page):
        signal, spots = _dataset()
        html, navigator_id, signal_id = _build_page(signal, spots, detector=False)
        page = navigated_page(html)
        _drag(page, navigator_id, (0, 0), (1, 1))
        green = page.evaluate(
            """(id) => {
              const panel = window._aplHandle.api.panels.get(id);
              const canvas = panel.markersCanvas;
              const d = canvas.getContext('2d')
                              .getImageData(0, 0, canvas.width, canvas.height).data;
              let n = 0;
              for (let i = 0; i < d.length; i += 4)
                if (d[i + 1] > 200 && d[i] < 100 && d[i + 3] > 0) n++;
              return n;
            }""",
            signal_id)
        assert green > 0, "the circles overlay drew nothing"


class TestDetectorReducesOntoTheNavigator:
    def test_reduce_matches_numpy_einsum(self, navigated_page):
        signal, spots = _dataset()
        html, navigator_id, signal_id = _build_page(signal, spots)
        page = navigated_page(html)

        widget = {"type": "rectangle", "x": 8, "y": 12, "w": 16, "h": 10}
        values = page.evaluate(
            """(args) => {
              const [widget, height, width] = args;
              const mod = window._aplModule.embed;
              const mask = mod.maskFromWidget(widget, width, height);
              const reader = mod.dense(window._aplHandle.blocks.signal);
              return {mask: Array.from(mask), values: Array.from(reader.reduce(mask))};
            }""",
            [widget, SIGNAL_SHAPE[0], SIGNAL_SHAPE[1]])

        mask = np.asarray(values["mask"], dtype=np.uint8).reshape(SIGNAL_SHAPE)
        expected_mask = np.zeros(SIGNAL_SHAPE, dtype=np.uint8)
        expected_mask[12:22, 8:24] = 1
        assert np.array_equal(mask, expected_mask)

        expected = np.einsum("yxij,ij->yx", signal.astype(np.float64), mask).ravel()
        assert np.array_equal(np.asarray(values["values"], dtype=np.float64), expected)

    def test_dragging_the_detector_repaints_the_navigator(self, navigated_page):
        signal, spots = _dataset()
        html, navigator_id, signal_id = _build_page(signal, spots)
        page = navigated_page(html)

        before = _painted_codes(page, navigator_id)
        _drag(page, signal_id, (16, 17), (40, 40))
        after = _painted_codes(page, navigator_id)
        assert after.size == NAV_SHAPE[0] * NAV_SHAPE[1]
        assert not np.array_equal(before, after), (
            "moving the detector left the navigator image unchanged")


class TestRegionSelection:
    def test_rectangle_navigator_gathers_the_mean(self, navigated_page):
        signal, spots = _dataset()
        html, navigator_id, signal_id = _build_page(
            signal, spots, detector=False, overlays=False,
            navigator_widget="rectangle")
        page = navigated_page(html)
        # Nudge the rectangle by one position so the drag produces a real event.
        _drag(page, navigator_id, (2, 3), (3, 4))

        indices = page.evaluate("() => window._aplHandle.index")
        selected = np.asarray(indices)
        assert selected.ndim == 2 and len(selected) > 1, f"no region selected: {indices}"

        frames = signal[selected[:, 0], selected[:, 1]].astype(np.float64)
        expected = _to_codes(frames.mean(axis=0).ravel(), 0, 255)
        painted = _painted_codes(page, signal_id).astype(np.int16)
        # The runtime accumulates in float32 and scales by 1/n; numpy means in
        # float64. A value sitting on a code boundary can truncate either way.
        assert np.abs(painted - expected.astype(np.int16)).max() <= 1


class TestReaders:
    def test_raster_disks_matches_numpy(self, navigated_page):
        signal, spots = _dataset()
        html, _, _ = _build_page(signal, spots, detector=False)
        page = navigated_page(html)

        rows = {"x": [4.2, 20.0, 61.8], "y": [5.1, 20.0, 3.0],
                "intensity": [2.0, 5.0, 7.0]}
        radius = 3
        for combine in ("max", "sum"):
            raster = np.asarray(page.evaluate(
                """(args) => {
                  const [rows, width, height, radius, combine] = args;
                  const typed = {x: Float32Array.from(rows.x),
                                 y: Float32Array.from(rows.y),
                                 intensity: Float32Array.from(rows.intensity)};
                  return Array.from(window._aplModule.embed.rasterDisks(
                    typed, width, height, radius, combine));
                }""",
                [rows, 64, 64, radius, combine]), dtype=np.float32).reshape(64, 64)

            # The convention: each row paints a filled disk of its intensity,
            # centred on its rounded position and clipped to the grid; rows
            # combine by max (one position) or sum (a gathered region).
            lines, columns = np.mgrid[0:64, 0:64]
            painted = []
            for x, y, value in zip(rows["x"], rows["y"], rows["intensity"]):
                inside = ((columns - round(x)) ** 2
                          + (lines - round(y)) ** 2) <= radius ** 2
                painted.append(np.where(inside, np.float32(value), np.float32(0)))
            stacked = np.stack(painted)
            expected = (stacked.sum(axis=0) if combine == "sum"
                        else stacked.max(axis=0)).astype(np.float32)
            assert np.array_equal(raster, expected), f"rasterDisks({combine}) diverged"

    def test_mask_from_widget_matches_numpy(self, navigated_page):
        signal, spots = _dataset()
        html, _, _ = _build_page(signal, spots, detector=False)
        page = navigated_page(html)

        lines, columns = np.mgrid[0:32, 0:40]
        cases = [
            ({"type": "rectangle", "x": 3.0, "y": 5.0, "w": 12.0, "h": 7.0},
             (columns >= 3) & (columns < 15) & (lines >= 5) & (lines < 12)),
            ({"type": "circle", "cx": 20.0, "cy": 16.0, "r": 6.0},
             ((columns - 20) ** 2 + (lines - 16) ** 2) <= 36),
            ({"type": "annular", "cx": 18.0, "cy": 14.0,
              "r_outer": 9.0, "r_inner": 4.0},
             (((columns - 18) ** 2 + (lines - 14) ** 2) <= 81)
             & (((columns - 18) ** 2 + (lines - 14) ** 2) >= 16)),
        ]
        for widget, expected in cases:
            mask = np.asarray(page.evaluate(
                "(args) => Array.from(window._aplModule.embed.maskFromWidget("
                "  args[0], args[1], args[2]))",
                [widget, 40, 32]), dtype=np.uint8).reshape(32, 40)
            assert np.array_equal(mask, expected.astype(np.uint8)), (
                f"maskFromWidget({widget['type']}) diverged")

    def test_robust_levels_bracket_the_percentiles(self, navigated_page):
        signal, spots = _dataset()
        html, _, _ = _build_page(signal, spots, detector=False)
        page = navigated_page(html)
        values = np.linspace(-5.0, 15.0, 4001)
        levels = page.evaluate(
            "(v) => window._aplModule.embed.robustLevels(Float32Array.from(v), 2, 98)",
            values.tolist())
        # A 1024-bin histogram resolves a percentile to within one bin width.
        tolerance = (values.max() - values.min()) / 1024
        assert abs(levels[0] - np.percentile(values, 2)) <= tolerance
        assert abs(levels[1] - np.percentile(values, 98)) <= tolerance

    def test_full_range_levels_are_exact(self, navigated_page):
        signal, spots = _dataset()
        html, _, _ = _build_page(signal, spots, detector=False)
        page = navigated_page(html)
        levels = page.evaluate(
            "() => window._aplModule.embed.robustLevels("
            "  Float32Array.from([3, -1, 40, 7]), 0, 100)")
        assert levels == [-1, 40]


_HOST_PAGE = """<!DOCTYPE html>
<html><head><meta charset="utf-8"/></head><body>
<script>
window._heights = [];
window.addEventListener('message', (e) => {
  if (e.data && e.data.aplEmbedHeight) window._heights.push(e.data.aplEmbedHeight);
});
const frame = document.createElement('iframe');
frame.src = "__SRC__";
frame.style.cssText = 'width:700px;height:420px;border:none;';
document.body.appendChild(frame);
</script></body></html>
"""


class TestPageChrome:
    def test_page_reports_its_height_to_a_host_frame(self, _pw_browser, tmp_path):
        signal, spots = _dataset()
        html, _, _ = _build_page(signal, spots, detector=False)
        embed = tmp_path / "embed.html"
        embed.write_text(html, encoding="utf-8")
        host = tmp_path / "host.html"
        host.write_text(_HOST_PAGE.replace("__SRC__", embed.name), encoding="utf-8")

        page = _pw_browser.new_page()
        try:
            page.goto(host.as_uri())
            page.wait_for_function("() => window._heights.length > 0", timeout=20_000)
            heights = page.evaluate("() => window._heights")
        finally:
            page.close()
        assert heights and all(height > 0 for height in heights), heights

    def test_png_harvest_answers(self, navigated_page):
        signal, spots = _dataset()
        html, _, _ = _build_page(signal, spots, detector=False)
        page = navigated_page(html)
        result = page.evaluate(
            """() => new Promise((resolve) => {
              window.addEventListener('message', (e) => {
                if (e.data && e.data.type === 'anyplotlib_export_png_result')
                  resolve({hasUrl: typeof e.data.dataUrl === 'string',
                           error: e.data.error || null});
              });
              window.postMessage(
                {type: 'anyplotlib_export_png', requestId: 'r1', opts: {}}, '*');
            })""")
        assert result["error"] is None and result["hasUrl"], result


class TestDatalessPage:
    def test_a_page_with_no_blocks_still_mounts(self, navigated_page):
        fig, ax = apl.subplots(1, 1, figsize=(320, 240))
        plot = ax.imshow(np.zeros((16, 16), dtype=np.uint8), cmap="gray")
        html = navigated_html(fig, {}, [{"panel_id": plot._id, "role": "static"}])
        page = navigated_page(html)
        assert page.evaluate("() => window._aplHandle.panelIds()") == [plot._id]


# ── a 1-D navigator: a stack of frames scrubbed by a line plot ─────────────

# figure_esm.js's shared plot-area padding, which a 1-D drag has to land inside.
PAD_LEFT, PAD_RIGHT, PAD_TOP, PAD_BOTTOM = 58, 12, 12, 42

_ONE_D_POINT = """
(args) => {
  const [panelId, fraction, padding] = args;
  const [left, right, top, bottom] = padding;
  const panel = window._aplHandle.api.panels.get(panelId);
  const state = panel.state;
  const viewFirst = state.view_x0 || 0, viewLast = state.view_x1 || 1;
  const plotLeft = left, plotWidth = Math.max(1, panel.pw - left - right);
  const x = plotLeft + ((fraction - viewFirst) / ((viewLast - viewFirst) || 1)) * plotWidth;
  const y = top + (panel.ph - top - bottom) / 2;
  const rect = panel.overlayCanvas.getBoundingClientRect();
  return [rect.left + x * (rect.width / panel.pw),
          rect.top + y * (rect.height / panel.ph)];
}
"""


def _movie(frames=6, height=16, width=16):
    rng = np.random.default_rng(11)
    return rng.integers(0, 256, size=(frames, height, width)).astype(np.uint8)


def _stack_page(movie, *, widget="vline"):
    """A 1-D navigator (per-frame sums) driving the frame panel beside it."""
    fig, axes = apl.subplots(1, 2, figsize=(640, 300))
    times = np.arange(movie.shape[0], dtype=float) * 0.5
    navigator = axes[0].plot(movie.sum(axis=(1, 2)).astype(float), axes=[times])
    frame_plot = axes[1].imshow(movie[0], cmap="gray")
    if widget == "vline":
        navigator.add_vline_widget(float(times[0]))
    else:
        navigator.add_range_widget(float(times[0]), float(times[1]))

    html = navigated_html(
        fig, {"movie": movie},
        [{"panel_id": navigator._id, "role": "navigator"},
         {"panel_id": frame_plot._id, "role": "driven",
          "frame": {"block": "movie", "kind": "image", "levels": [0, 255]}}])
    return html, navigator._id, frame_plot._id


def _drag_1d(page, panel_id, from_fraction, to_fraction):
    """Drag a 1-D widget between two positions given as axis fractions."""
    padding = [PAD_LEFT, PAD_RIGHT, PAD_TOP, PAD_BOTTOM]
    x0, y0 = page.evaluate(_ONE_D_POINT, [panel_id, from_fraction, padding])
    x1, y1 = page.evaluate(_ONE_D_POINT, [panel_id, to_fraction, padding])
    page.mouse.move(x0, y0)
    page.mouse.down()
    page.mouse.move(x1, y1, steps=4)
    page.mouse.up()
    page.evaluate(
        "() => new Promise(r => requestAnimationFrame("
        "  () => requestAnimationFrame(() => requestAnimationFrame(r))))")


class TestOneDimensionalNavigator:
    def test_vline_drag_paints_that_time_frame(self, navigated_page):
        movie = _movie()
        html, navigator_id, frame_id = _stack_page(movie)
        page = navigated_page(html)
        assert np.array_equal(_painted_codes(page, frame_id), movie[0].ravel())

        _drag_1d(page, navigator_id, 0.0, 4 / (movie.shape[0] - 1))
        assert page.evaluate("() => window._aplHandle.index") == [4]
        assert np.array_equal(_painted_codes(page, frame_id), movie[4].ravel())

    def test_range_selection_gathers_the_span(self, navigated_page):
        movie = _movie()
        html, navigator_id, frame_id = _stack_page(movie, widget="range")
        page = navigated_page(html)

        span = movie.shape[0] - 1
        _drag_1d(page, navigator_id, 1 / span, 4 / span)
        indices = page.evaluate("() => window._aplHandle.index")
        selected = [pair[0] for pair in indices]
        assert len(selected) > 1, f"the span selected one position: {indices}"

        expected = _to_codes(movie[selected].astype(np.float64).mean(axis=0).ravel(),
                             0, 255)
        painted = _painted_codes(page, frame_id).astype(np.int16)
        assert np.abs(painted - expected.astype(np.int16)).max() <= 1


class TestStaticOverlaysSurvive:
    def test_a_figure_marker_outlives_a_dispatch(self, navigated_page):
        signal, spots = _dataset()
        fig, axes = apl.subplots(1, 2, figsize=(640, 320))
        navigator = axes[0].imshow(signal.sum(axis=(2, 3)).astype(np.float32), cmap="gray")
        signal_plot = axes[1].imshow(signal[0, 0], cmap="gray")
        navigator.add_widget("crosshair", cx=0, cy=0)
        signal_plot.add_circles([[10.0, 20.0]], name="fixed", radius=6,
                                edgecolors="#ff00ff")

        html = navigated_html(
            fig, {"signal": signal, "spots": spots},
            [{"panel_id": navigator._id, "role": "navigator"},
             {"panel_id": signal_plot._id, "role": "driven",
              "frame": {"block": "signal", "kind": "image", "levels": [0, 255]},
              "overlays": [{"block": "spots", "kind": "circles",
                            "style": {"radius": 4, "color": "#00ff00"}}]}])
        page = navigated_page(html)
        _drag(page, navigator._id, (0, 0), (3, 3))

        names = page.evaluate(
            "(id) => window._aplHandle.api.panels.get(id).state.markers"
            "        .map((group) => group.name)",
            signal_plot._id)
        assert "fixed" in names, f"the figure's own marker group was wiped: {names}"
        assert "spots" in names, f"the overlay group is missing: {names}"


class TestReaderGuards:
    def test_ragged_index_arity_is_checked(self, navigated_page):
        signal, spots = _dataset()
        html, _, _ = _build_page(signal, spots, detector=False)
        page = navigated_page(html)
        message = page.evaluate(
            """() => {
              const block = window._aplHandle.blocks.spots;
              const flat = {kind: 'ragged', columns: block.columns,
                            offsets: block.offsets, navShape: null};
              try {
                window._aplModule.embed.ragged(flat).at([2, 3]);
                return null;
              } catch (e) { return String(e.message); }
            }""")
        assert message is not None, "a 2-D index into a flat block was accepted"
        assert "1-D navigation grid" in message and "nav_shape" in message

    def test_reduce_checks_the_mask_covers_the_signal_grid(self, navigated_page):
        signal, spots = _dataset()
        html, _, _ = _build_page(signal, spots, detector=False)
        page = navigated_page(html)
        message = page.evaluate(
            """() => {
              const reader = window._aplModule.embed.dense(
                window._aplHandle.blocks.signal);
              try { reader.reduce(new Uint8Array(100)); return null; }
              catch (e) { return String(e.message); }
            }""")
        assert message is not None, "a short mask was accepted"
        assert "64x64 signal grid" in message

    def test_to_u8_saturates_infinity_and_zeroes_nan(self, navigated_page):
        signal, spots = _dataset()
        html, _, _ = _build_page(signal, spots, detector=False)
        page = navigated_page(html)
        codes = page.evaluate(
            "() => Array.from(window._aplModule.embed.toU8("
            "  [Infinity, -Infinity, NaN, 0, 1], 0, 1))")
        assert codes == [255, 0, 0, 0, 255]


class TestViews:
    def _page(self):
        rng = np.random.default_rng(5)
        first = rng.random((4, 4, 8, 8)).astype(np.float32)
        second = (first * -1).astype(np.float32)
        fig, axes = apl.subplots(1, 2, figsize=(560, 280))
        navigator = axes[0].imshow(first.sum(axis=(2, 3)), cmap="gray")
        panel = axes[1].imshow(first[0, 0], cmap="gray")
        navigator.add_widget("crosshair", cx=0, cy=0)
        html = navigated_html(
            fig, {"exx": first, "eyy": second},
            [{"panel_id": navigator._id, "role": "navigator"},
             {"panel_id": panel._id, "role": "driven",
              "views": [{"label": "exx", "block": "exx"},
                        {"label": "eyy", "block": "eyy"}],
              "frame": {"kind": "image", "levels": [-1, 1]}}])
        return html, navigator._id, panel._id, first, second

    def test_the_first_view_is_shown_and_a_click_swaps_the_block(self, navigated_page):
        html, navigator_id, panel_id, first, second = self._page()
        page = navigated_page(html)
        assert np.array_equal(_painted_codes(page, panel_id),
                              _to_codes(first[0, 0].ravel(), -1, 1))

        _drag(page, navigator_id, (0, 0), (2, 1))
        assert np.array_equal(_painted_codes(page, panel_id),
                              _to_codes(first[1, 2].ravel(), -1, 1))

        page.evaluate(
            """async (id) => {
              document.querySelector(`#apl-views-${id} button[data-view="1"]`).click();
              await new Promise((r) => requestAnimationFrame(r));
              await new Promise((r) => requestAnimationFrame(r));
            }""",
            panel_id)
        assert np.array_equal(_painted_codes(page, panel_id),
                              _to_codes(second[1, 2].ravel(), -1, 1)), (
            "picking a view did not re-read the frame from its block")
        pressed = page.evaluate(
            f"() => [...document.querySelectorAll('#apl-views-{panel_id} button')]"
            "        .filter((button) => button.getAttribute('aria-pressed') === 'true')"
            "        .map((button) => button.textContent)")
        assert pressed == ["eyy"]


class TestDetectorValidation:
    def test_a_reduce_binding_without_a_detector_is_refused(self, _pw_browser, tmp_path):
        signal, _ = _dataset()
        fig, axes = apl.subplots(1, 2, figsize=(560, 280))
        navigator = axes[0].imshow(signal.sum(axis=(2, 3)).astype(np.float32))
        signal_plot = axes[1].imshow(signal[0, 0])
        navigator.add_widget("crosshair", cx=0, cy=0)

        html = navigated_html(
            fig, {"signal": signal},
            [{"panel_id": navigator._id, "role": "navigator"},
             {"panel_id": signal_plot._id, "role": "driven",
              "frame": {"block": "signal", "kind": "image"},
              "reduce": {"block": "signal", "navigator_panel": navigator._id}}])
        path = tmp_path / "no-detector.html"
        path.write_text(html, encoding="utf-8")

        page = _pw_browser.new_page()
        try:
            page.goto(path.as_uri())
            page.wait_for_function(
                "() => document.getElementById('apl-host').textContent.length > 0",
                timeout=20_000)
            message = page.evaluate(
                "() => document.getElementById('apl-host').textContent")
        finally:
            page.close()
        assert "carries no rectangle/circle/annular widget" in message, message

    def test_a_non_detector_widget_on_the_reduce_panel_is_ignored(self, navigated_page):
        signal, _ = _dataset()
        fig, axes = apl.subplots(1, 2, figsize=(640, 320))
        navigator = axes[0].imshow(signal.sum(axis=(2, 3)).astype(np.float32), cmap="gray")
        signal_plot = axes[1].imshow(signal[0, 0], cmap="gray")
        navigator.add_widget("crosshair", cx=0, cy=0)
        signal_plot.add_widget("rectangle", x=8, y=12, w=16, h=10)
        signal_plot.add_widget("crosshair", cx=40, cy=40)

        html = navigated_html(
            fig, {"signal": signal},
            [{"panel_id": navigator._id, "role": "navigator"},
             {"panel_id": signal_plot._id, "role": "driven",
              "frame": {"block": "signal", "kind": "image", "levels": [0, 255]},
              "reduce": {"block": "signal", "navigator_panel": navigator._id}}])
        page = navigated_page(html)
        failures = []
        page.on("pageerror", lambda error: failures.append(str(error)))
        _drag(page, signal_plot._id, (40, 40), (44, 44))
        assert failures == [], failures


class TestVirtualImage:
    def test_a_circle_detector_gives_the_navigator_the_einsum(self, navigated_page):
        signal, _ = _dataset()
        fig, axes = apl.subplots(1, 2, figsize=(640, 320))
        navigator = axes[0].imshow(signal.sum(axis=(2, 3)).astype(np.float32), cmap="gray")
        signal_plot = axes[1].imshow(signal[0, 0], cmap="gray")
        navigator.add_widget("crosshair", cx=0, cy=0)
        detector = {"type": "circle", "cx": 30.0, "cy": 34.0, "r": 11.0}
        signal_plot.add_widget("circle", cx=detector["cx"], cy=detector["cy"],
                               r=detector["r"])

        html = navigated_html(
            fig, {"signal": signal},
            [{"panel_id": navigator._id, "role": "navigator"},
             {"panel_id": signal_plot._id, "role": "driven",
              "frame": {"block": "signal", "kind": "image", "levels": [0, 255]},
              "reduce": {"block": "signal", "navigator_panel": navigator._id}}])
        page = navigated_page(html)

        result = page.evaluate(
            """(args) => {
              const [widget, height, width] = args;
              const embed = window._aplModule.embed;
              const mask = embed.maskFromWidget(widget, width, height);
              const reader = embed.dense(window._aplHandle.blocks.signal);
              return {mask: Array.from(mask), values: Array.from(reader.reduce(mask))};
            }""",
            [detector, SIGNAL_SHAPE[0], SIGNAL_SHAPE[1]])

        mask = np.asarray(result["mask"], dtype=np.uint8).reshape(SIGNAL_SHAPE)
        assert mask.sum() > 0
        expected = np.einsum("...ij,ij->...", signal.astype(np.float64), mask).ravel()
        assert np.array_equal(np.asarray(result["values"], dtype=np.float64), expected)


class TestGeomPushKeepsTheLiveFrame:
    def test_a_geom_push_leaves_the_binary_token_in_place(self, navigated_page):
        signal, spots = _dataset()
        html, _, signal_id = _build_page(signal, spots, detector=False)
        page = navigated_page(html)

        pushed = page.evaluate(
            """async (panelId) => {
              const handle = window._aplHandle;
              handle.setImage(panelId, new Uint8Array(64 * 64).fill(66), 64, 64,
                              {display_min: 0, display_max: 255});
              await new Promise((r) => requestAnimationFrame(r));
              await new Promise((r) => requestAnimationFrame(r));
              // A host pushing the panel's geometry again (a colormap change,
              // say) must not rename the key that identifies the live bytes.
              const geom = handle.get(`panel_${panelId}_geom`);
              handle.applyUpdate(`panel_${panelId}_geom`, geom);
              await new Promise((r) => requestAnimationFrame(r));
              const panel = handle.api.panels.get(panelId);
              return {token: panel._geomCache.image_b64,
                      codes: Array.from(panel.state.image_b64_bytes.slice(0, 4))};
            }""",
            signal_id)
        assert pushed["token"].startswith(BINARY_TOKEN_PREFIX), (
            f"a geom push renamed the live binary frame to {pushed['token'][:24]!r}")
        assert pushed["codes"] == [66, 66, 66, 66]

    def test_a_geom_push_carrying_its_own_token_wins(self, navigated_page):
        signal, spots = _dataset()
        html, _, signal_id = _build_page(signal, spots, detector=False)
        page = navigated_page(html)
        token = page.evaluate(
            """async (panelId) => {
              const handle = window._aplHandle;
              handle.setImage(panelId, new Uint8Array(64 * 64).fill(9), 64, 64);
              await new Promise((r) => requestAnimationFrame(r));
              const geom = JSON.parse(handle.get(`panel_${panelId}_geom`));
              geom.image_b64 = '\\u0000bin:99999';
              handle.applyUpdate(`panel_${panelId}_geom`, JSON.stringify(geom));
              await new Promise((r) => requestAnimationFrame(r));
              return handle.api.panels.get(panelId)._geomCache.image_b64;
            }""",
            signal_id)
        assert token == BINARY_TOKEN_PREFIX + "99999"


class TestTwoFiguresInOneDocument:
    def test_two_mounts_keep_their_own_pixels(self, navigated_page):
        """Panel ids hash the layout position, so two identical figures in one
        document write the same global pixel slot."""
        signal, spots = _dataset()
        html, _, signal_id = _build_page(signal, spots, detector=False)
        page = navigated_page(html)

        page.evaluate(
            """async () => {
              const host = document.createElement('div');
              document.body.appendChild(host);
              window._secondHandle = await window._aplModule.mountNavigated(
                host, window._aplPage, {});
            }""")
        page.wait_for_function("() => window._secondHandle !== undefined", timeout=20_000)

        result = page.evaluate(
            """async (panelId) => {
              const read = (handle) => {
                const panel = handle.api.panels.get(panelId);
                return [Array.from(panel.state.image_b64_bytes.slice(0, 2)),
                        panel._geomCache.image_b64];
              };
              window._aplHandle.setImage(panelId, new Uint8Array(64 * 64).fill(11),
                                         64, 64, {display_min: 0, display_max: 255});
              window._secondHandle.setImage(panelId, new Uint8Array(64 * 64).fill(222),
                                            64, 64, {display_min: 0, display_max: 255});
              await new Promise((r) => requestAnimationFrame(r));
              await new Promise((r) => requestAnimationFrame(r));
              return {first: read(window._aplHandle), second: read(window._secondHandle)};
            }""",
            signal_id)
        assert result["first"][0] == [11, 11], result
        assert result["second"][0] == [222, 222], result
        assert result["first"][1] != result["second"][1], (
            f"both figures claimed the pixel key {result['first'][1]!r}")


class TestFrameLevels:
    def test_the_panel_window_is_kept_across_positions(self, navigated_page):
        """Without fixed levels the window is the panel's, not a per-frame one."""
        rng = np.random.default_rng(2)
        block = (rng.random((4, 4, 8, 8)) * 100).astype(np.float32)
        block[2, 2] += 900.0                       # one very bright position
        fig, axes = apl.subplots(1, 2, figsize=(560, 280))
        navigator = axes[0].imshow(block.sum(axis=(2, 3)), cmap="gray")
        panel = axes[1].imshow(block[0, 0], cmap="gray", vmin=0.0, vmax=100.0)
        navigator.add_widget("crosshair", cx=0, cy=0)
        html = navigated_html(
            fig, {"cube": block},
            [{"panel_id": navigator._id, "role": "navigator"},
             {"panel_id": panel._id, "role": "driven",
              "frame": {"block": "cube", "kind": "image"}}])
        page = navigated_page(html)
        _drag(page, navigator._id, (0, 0), (2, 2))

        window = page.evaluate(
            "(id) => { const s = window._aplHandle.api.panels.get(id).state;"
            "  return [s.display_min, s.display_max]; }",
            panel._id)
        assert window == [0.0, 100.0], (
            f"the frame window drifted to {window} instead of keeping the panel's")
        assert np.array_equal(_painted_codes(page, panel._id),
                              _to_codes(block[2, 2].ravel(), 0.0, 100.0))


class TestGeometryLandsWithItsBytes:
    def test_a_resize_is_not_applied_before_the_bytes(self, navigated_page):
        signal, spots = _dataset()
        html, _, signal_id = _build_page(signal, spots, detector=False)
        page = navigated_page(html)
        sizes = page.evaluate(
            """async (panelId) => {
              const handle = window._aplHandle;
              const state = () => handle.api.panels.get(panelId).state;
              handle.setImage(panelId, new Uint8Array(16 * 32).fill(5), 32, 16,
                              {display_min: 0, display_max: 255});
              const beforeFrame = [state().image_width, state().image_height];
              await new Promise((r) => requestAnimationFrame(r));
              await new Promise((r) => requestAnimationFrame(r));
              const afterFrame = [state().image_width, state().image_height];
              return {beforeFrame, afterFrame,
                      bytes: state().image_b64_bytes.length};
            }""",
            signal_id)
        assert sizes["beforeFrame"] == [64, 64], (
            "the panel was resized before the bytes it describes were committed")
        assert sizes["afterFrame"] == [32, 16]
        assert sizes["bytes"] == 32 * 16


class TestOverlayStylePassesThrough:
    def test_fill_alpha_reaches_the_wire_and_paints_opaque(self, navigated_page):
        """An allow-list here silently drops whatever it has not heard of."""
        signal, spots = _dataset()
        fig, axes = apl.subplots(1, 2, figsize=(640, 320))
        navigator = axes[0].imshow(signal.sum(axis=(2, 3)).astype(np.float32), cmap="gray")
        signal_plot = axes[1].imshow(np.zeros(SIGNAL_SHAPE, dtype=np.uint8), cmap="gray")
        navigator.add_widget("crosshair", cx=0, cy=0)

        style = {"radius": 9, "color": "#ff0000", "fill_color": "#00ff00",
                 "fill_alpha": 1.0}
        html = navigated_html(
            fig, {"signal": signal, "spots": spots},
            [{"panel_id": navigator._id, "role": "navigator"},
             {"panel_id": signal_plot._id, "role": "driven",
              "frame": {"block": "signal", "kind": "image", "levels": [0, 255]},
              "overlays": [{"block": "spots", "kind": "circles", "style": style}]}])
        page = navigated_page(html)

        wire = page.evaluate(
            "(id) => window._aplHandle.api.panels.get(id).state.markers[0]",
            signal_plot._id)
        assert wire["fill_alpha"] == 1.0, wire
        assert wire["fill_color"] == "#00ff00", wire
        assert "radius" not in wire, "the sizes input leaked into the wire dict"
        assert wire["sizes"] == [9] * ROWS_PER_POSITION

        # A fully opaque fill paints the fill colour, not a 30 % blend of it.
        opaque = page.evaluate(
            """(id) => {
              const canvas = window._aplHandle.api.panels.get(id).markersCanvas;
              const data = canvas.getContext('2d')
                                 .getImageData(0, 0, canvas.width, canvas.height).data;
              let n = 0;
              for (let i = 0; i < data.length; i += 4)
                if (data[i] < 40 && data[i + 1] > 215 && data[i + 2] < 40
                    && data[i + 3] > 250) n++;
              return n;
            }""",
            signal_plot._id)
        assert opaque > 20, f"only {opaque} fully opaque green pixels"

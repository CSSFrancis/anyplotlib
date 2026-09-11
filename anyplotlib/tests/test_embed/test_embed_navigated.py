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
              const mod = window._aplModule;
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
        assert np.array_equal(_painted_codes(page, signal_id), expected)


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
                  return Array.from(window._aplModule.rasterDisks(
                    typed, width, height, radius, combine));
                }""",
                [rows, 64, 64, radius, combine]), dtype=np.float32).reshape(64, 64)

            expected = np.zeros((64, 64), dtype=np.float32)
            lines, columns = np.ogrid[-radius:radius + 1, -radius:radius + 1]
            disk = (lines ** 2 + columns ** 2) <= radius ** 2
            for x, y, value in zip(rows["x"], rows["y"], rows["intensity"]):
                cx, cy = int(round(x)), int(round(y))
                for dy in range(-radius, radius + 1):
                    for dx in range(-radius, radius + 1):
                        if not disk[dy + radius, dx + radius]:
                            continue
                        column, line = cx + dx, cy + dy
                        if not (0 <= column < 64 and 0 <= line < 64):
                            continue
                        expected[line, column] = (expected[line, column] + value
                                                  if combine == "sum"
                                                  else max(expected[line, column], value))
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
                "(args) => Array.from(window._aplModule.maskFromWidget("
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
            "(v) => window._aplModule.robustLevels(Float32Array.from(v), 2, 98)",
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
            "() => window._aplModule.robustLevels("
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

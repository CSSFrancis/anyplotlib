"""
A 3-D panel driven by a navigated page.

The shape this exists for is an orientation map: a navigator of orientations,
a sphere of the whole cloud beside it, and a highlight marking the position
under the crosshair.  The sphere turns to face the picked point, and a
direction toggle swaps the cloud and its per-point colours.
"""
from __future__ import annotations

import math
import pathlib
import tempfile

import numpy as np
import pytest

import anyplotlib as apl
from anyplotlib.embed import navigated_html

NAV_SHAPE = (6, 6)


def _sphere_dataset():
    """A unit-sphere cloud, two colourings of it, and one direction per position."""
    rng = np.random.default_rng(17)
    count = 240
    points = rng.normal(size=(count, 3)).astype(np.float32)
    points /= np.linalg.norm(points, axis=1, keepdims=True)

    red = np.zeros((count, 3), dtype=np.uint8)
    red[:, 0] = 230
    blue = np.zeros((count, 3), dtype=np.uint8)
    blue[:, 2] = 230

    positions = NAV_SHAPE[0] * NAV_SHAPE[1]
    picked = points[rng.integers(0, count, size=positions)].astype(np.float32)
    return points, red, blue, picked.reshape(NAV_SHAPE + (3,))


def _sphere_page(picks, *, face_camera=True, with_views=True):
    points, red, blue, _ = _sphere_dataset()
    fig, axes = apl.subplots(1, 2, figsize=(640, 320))
    navigator = axes[0].imshow(picks[..., 2].astype(np.float32), cmap="gray")
    sphere = axes[1].scatter3d(points[:, 0], points[:, 1], points[:, 2],
                               colors=np.zeros((len(points), 3), dtype=np.float32),
                               point_size=4.0, azimuth=-60.0, elevation=30.0)
    sphere.set_sphere(1.0)
    navigator.add_widget("crosshair", cx=0, cy=0)

    driven = {"panel_id": sphere._id, "role": "driven",
              "overlays": [{"block": "picks", "kind": "highlight",
                            "style": {"color": "#ffffff", "size": 11},
                            "face_camera": face_camera}]}
    if with_views:
        driven["views"] = [{"label": "z", "block": "cloud", "colors": "red"},
                           {"label": "x", "block": "cloud", "colors": "blue"}]
        driven["frame"] = {"kind": "points3d"}
    else:
        driven["frame"] = {"block": "cloud", "kind": "points3d", "colors": "red"}

    blocks = {"cloud": points, "red": red, "blue": blue, "picks": picks}
    html = navigated_html(
        fig, blocks,
        [{"panel_id": navigator._id, "role": "navigator"}, driven])
    return html, navigator._id, sphere._id


@pytest.fixture
def sphere_page(_pw_browser):
    """Open a navigated page holding a 3-D panel; return the live Page."""
    pages, paths = [], []

    def _open(html):
        with tempfile.NamedTemporaryFile(
                suffix=".html", mode="w", encoding="utf-8", delete=False) as handle:
            handle.write(html)
            path = pathlib.Path(handle.name)
        paths.append(path)
        page = _pw_browser.new_page()
        pages.append(page)
        page.goto(path.as_uri())
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


def _drag(page, panel_id, start, end):
    x0, y0 = page.evaluate(_CLIENT_POINT, [panel_id, *start])
    x1, y1 = page.evaluate(_CLIENT_POINT, [panel_id, *end])
    page.mouse.move(x0, y0)
    page.mouse.down()
    page.mouse.move(x1, y1, steps=4)
    page.mouse.up()
    page.evaluate(
        "() => new Promise(r => requestAnimationFrame("
        "  () => requestAnimationFrame(() => requestAnimationFrame(r))))")


def _camera(page, panel_id):
    return page.evaluate(
        "(id) => { const s = window._aplHandle.api.panels.get(id).state;"
        "  return [s.azimuth, s.elevation, s._view_from_python]; }",
        panel_id)


def _ink(page, panel_id, channel):
    """Pixels on the 3-D plot canvas whose dominant channel is *channel*."""
    return page.evaluate(
        """(args) => {
          const [id, channel] = args;
          const canvas = window._aplHandle.api.panels.get(id).plotCanvas;
          const data = canvas.getContext('2d')
                             .getImageData(0, 0, canvas.width, canvas.height).data;
          let n = 0;
          for (let i = 0; i < data.length; i += 4) {
            if (data[i + 3] < 200) continue;
            const rgb = [data[i], data[i + 1], data[i + 2]];
            const best = rgb.indexOf(Math.max(...rgb));
            if (best === channel && rgb[best] - Math.min(...rgb) > 60) n++;
          }
          return n;
        }""",
        [panel_id, channel])


class TestHighlightFollowsTheNavigator:
    def test_the_highlight_is_the_block_row_at_that_index(self, sphere_page):
        _, _, _, picks = _sphere_dataset()
        html, navigator_id, sphere_id = _sphere_page(picks, face_camera=False)
        page = sphere_page(html)

        highlight = page.evaluate(
            "(id) => window._aplHandle.api.panels.get(id).state.highlight", sphere_id)
        assert highlight["color"] == "#ffffff" and highlight["size"] == 11
        assert np.allclose([highlight["x"], highlight["y"], highlight["z"]],
                           picks[0, 0], atol=1e-6)

        _drag(page, navigator_id, (0, 0), (4, 2))
        assert page.evaluate("() => window._aplHandle.index") == [2, 4]
        moved = page.evaluate(
            "(id) => window._aplHandle.api.panels.get(id).state.highlight", sphere_id)
        assert np.allclose([moved["x"], moved["y"], moved["z"]],
                           picks[2, 4], atol=1e-6)

    def test_the_marked_point_repaints(self, sphere_page):
        _, _, _, picks = _sphere_dataset()
        html, navigator_id, sphere_id = _sphere_page(picks, face_camera=False)
        page = sphere_page(html)

        def white_pixels():
            return page.evaluate(
                """(id) => {
                  const canvas = window._aplHandle.api.panels.get(id).plotCanvas;
                  const data = canvas.getContext('2d')
                                     .getImageData(0, 0, canvas.width, canvas.height).data;
                  const out = [];
                  for (let i = 0; i < data.length; i += 4)
                    if (data[i] > 240 && data[i + 1] > 240 && data[i + 2] > 240
                        && data[i + 3] > 250) out.push(i >> 2);
                  return out;
                }""",
                sphere_id)

        before = white_pixels()
        assert before, "the highlight drew nothing"
        _drag(page, navigator_id, (0, 0), (5, 5))
        after = white_pixels()
        assert after, "the highlight vanished"
        assert before != after, "the highlight did not move with the navigator"


class TestFaceCamera:
    def test_the_camera_turns_to_the_picked_point(self, sphere_page):
        _, _, _, picks = _sphere_dataset()
        html, navigator_id, sphere_id = _sphere_page(picks, face_camera=True)
        page = sphere_page(html)
        _drag(page, navigator_id, (0, 0), (3, 1))

        x, y, z = (float(value) for value in picks[1, 3])
        radius = math.hypot(x, y, z) or 1.0
        azimuth, elevation, from_python = _camera(page, sphere_id)
        assert from_python is True
        assert azimuth == pytest.approx(math.degrees(math.atan2(x, -y)), abs=1e-6)
        assert elevation == pytest.approx(math.degrees(math.asin(z / radius)), abs=1e-6)

    def test_without_it_the_readers_orbit_is_kept(self, sphere_page):
        _, _, _, picks = _sphere_dataset()
        html, navigator_id, sphere_id = _sphere_page(picks, face_camera=False)
        page = sphere_page(html)

        # Orbit the sphere the way a reader would, then move the navigator.
        page.evaluate(
            """async (id) => {
              const panel = window._aplHandle.api.panels.get(id);
              const rect = panel.overlayCanvas.getBoundingClientRect();
              const mid = {clientX: rect.left + rect.width / 2,
                           clientY: rect.top + rect.height / 2};
              panel.overlayCanvas.dispatchEvent(
                new MouseEvent('mousedown', {bubbles: true, ...mid}));
              document.dispatchEvent(new MouseEvent('mousemove', {
                bubbles: true, clientX: mid.clientX + 70, clientY: mid.clientY + 25}));
              document.dispatchEvent(new MouseEvent('mouseup', {bubbles: true}));
              await new Promise((r) => requestAnimationFrame(r));
            }""",
            sphere_id)
        orbited = _camera(page, sphere_id)
        assert orbited[:2] != [-60.0, 30.0], "the orbit did not move the camera"

        _drag(page, navigator_id, (0, 0), (2, 3))
        after = _camera(page, sphere_id)
        assert after[0] == pytest.approx(orbited[0]), after
        assert after[1] == pytest.approx(orbited[1]), after
        assert after[2] is False


class TestViewsSwapTheCloud:
    def test_a_view_click_repaints_the_points_in_its_colours(self, sphere_page):
        _, _, _, picks = _sphere_dataset()
        html, navigator_id, sphere_id = _sphere_page(picks, face_camera=False)
        page = sphere_page(html)

        red_before, blue_before = _ink(page, sphere_id, 0), _ink(page, sphere_id, 2)
        assert red_before > 50, f"the cloud did not paint red: {red_before}"

        page.evaluate(
            """async (id) => {
              document.querySelector(`#apl-views-${id} button[data-view="1"]`)
                      .click();
              await new Promise((r) => requestAnimationFrame(r));
              await new Promise((r) => requestAnimationFrame(r));
            }""",
            sphere_id)
        red_after, blue_after = _ink(page, sphere_id, 0), _ink(page, sphere_id, 2)
        assert blue_after > blue_before, (red_before, blue_before, red_after, blue_after)
        assert red_after < red_before, (red_before, blue_before, red_after, blue_after)

    def test_the_cloud_is_pushed_once_not_per_move(self, sphere_page):
        """A cloud is the whole dataset; only a view click changes it."""
        _, _, _, picks = _sphere_dataset()
        html, navigator_id, sphere_id = _sphere_page(picks, face_camera=False)
        page = sphere_page(html)
        first = page.evaluate(
            "(id) => JSON.parse(window._aplHandle.get(`panel_${id}_json`))._geom_rev",
            sphere_id)
        _drag(page, navigator_id, (0, 0), (4, 4))
        again = page.evaluate(
            "(id) => JSON.parse(window._aplHandle.get(`panel_${id}_json`))._geom_rev",
            sphere_id)
        assert again == first, "the cloud was re-pushed on a navigator move"

    def test_the_cloud_reaches_the_geometry_channel(self, sphere_page):
        points, red, _, picks = _sphere_dataset()
        html, _, sphere_id = _sphere_page(picks, with_views=False, face_camera=False)
        page = sphere_page(html)
        pushed = page.evaluate(
            """(id) => {
              const geom = JSON.parse(window._aplHandle.get(`panel_${id}_geom`));
              const decode = (text) => {
                const binary = atob(text);
                const bytes = new Uint8Array(binary.length);
                for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
                return bytes;
              };
              const state = window._aplHandle.api.panels.get(id).state;
              return {vertices: Array.from(new Float32Array(
                        decode(geom.vertices_b64).buffer).slice(0, 6)),
                      colors: Array.from(decode(geom.point_colors_b64).slice(0, 6)),
                      count: state.vertices_count};
            }""",
            sphere_id)
        assert pushed["count"] == len(points)
        assert np.allclose(pushed["vertices"], points[:2].ravel(), atol=1e-6)
        assert pushed["colors"] == list(red[:2].ravel())


class TestSetImageStillRefuses3d:
    def test_a_sphere_panel_refuses_pixel_bytes(self, sphere_page):
        _, _, _, picks = _sphere_dataset()
        html, _, sphere_id = _sphere_page(picks, face_camera=False)
        page = sphere_page(html)
        message = page.evaluate(
            """(id) => {
              try {
                window._aplHandle.setImage(id, new Uint8Array(64), 8, 8);
                return null;
              } catch (e) { return String(e.message); }
            }""",
            sphere_id)
        assert message is not None and "only a 2-D image panel" in message


class TestDenseVectorRead:
    def test_at_returns_the_three_vector(self, sphere_page):
        _, _, _, picks = _sphere_dataset()
        html, _, _ = _sphere_page(picks, face_camera=False)
        page = sphere_page(html)
        vector = page.evaluate(
            "() => Array.from(window._aplModule.embed.dense("
            "  window._aplHandle.blocks.picks).at([3, 2]))")
        assert np.allclose(vector, picks[3, 2], atol=1e-6)

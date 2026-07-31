"""
tests/test_interactive/test_orbit_direction.py
==============================================

Orbit drag is DIRECT MANIPULATION: the surface under the cursor follows the
cursor, the way a globe does.

Both signs in the handler are inverted relative to the camera angles, because
azimuth/elevation move the CAMERA rather than the object.  A feature's screen
x is ``cx + scale*cos(az - θ)``, so raising azimuth sweeps the surface LEFT,
and raising elevation lifts the camera to show more of the top.  The handler
originally added ``dx`` and subtracted ``dy``, which made a rightward drag
push the surface left — it felt like grabbing the far side of the sphere.

These tests pin the sign at both levels: the camera angle the drag produces,
and the direction a tracked feature actually moves on screen.
"""
from __future__ import annotations

import base64
import json
import pathlib
import tempfile

import numpy as np
import pytest

import anyplotlib as apl
from anyplotlib.embed import esm_path, figure_state


_MOUNT_PAGE = """<!DOCTYPE html>
<html><head><meta charset="utf-8"/>
<style>html,body{margin:0;padding:0;}</style></head>
<body><div id="host"></div>
<script type="module">
const STATE = __STATE__;
const esmSource = __ESM__;
const blobUrl = URL.createObjectURL(new Blob([esmSource], {type: "text/javascript"}));
import(blobUrl).then(mod => {
  window._api = mod.mount(document.getElementById("host"), STATE, {});
  window._aplReady = true;
}).catch(err => { document.body.textContent = "mount error: " + err; });
</script></body></html>
"""


@pytest.fixture
def orbit_page(_pw_browser):
    """Mount a figure via the public ``mount()`` and hand back the live page.

    Not ``orbit_page``: that fixture's template does not expose the
    render API, and these tests need both the panel state and ``exportPNG``.
    """
    pages, paths = [], []

    def _open(fig):
        html = (_MOUNT_PAGE
                .replace("__STATE__", json.dumps(figure_state(fig)))
                .replace("__ESM__", json.dumps(esm_path().read_text(encoding="utf-8"))))
        with tempfile.NamedTemporaryFile(suffix=".html", mode="w",
                                         encoding="utf-8", delete=False) as fh:
            fh.write(html)
            tmp = pathlib.Path(fh.name)
        paths.append(tmp)
        page = _pw_browser.new_page(viewport={"width": 500, "height": 500})
        pages.append(page)
        page.goto(tmp.as_uri())
        page.wait_for_function("() => window._aplReady === true", timeout=20_000)
        page.wait_for_timeout(300)
        return page

    yield _open
    for p in pages:
        try:
            p.close()
        except Exception:
            pass
    for f in paths:
        f.unlink(missing_ok=True)


def _sphere(ndec=49, nra=97):
    ra = np.linspace(0, 2 * np.pi, nra)
    dec = np.linspace(np.pi / 2, -np.pi / 2, ndec)
    RA, DEC = np.meshgrid(ra, dec)
    return np.cos(DEC) * np.cos(RA), np.cos(DEC) * np.sin(RA), np.sin(DEC)


def _ramp_texture(h=256, w=512):
    """Red ramps with longitude, green with latitude — two tracked gradients."""
    img = np.zeros((h, w, 3), np.uint8)
    yy, xx = np.mgrid[0:h, 0:w]
    img[..., 0] = xx * 255 // w
    img[..., 1] = 255 - yy * 255 // h
    img[..., 2] = 120                      # constant: marks "on the sphere"
    return img


def _globe():
    X, Y, Z = _sphere()
    fig, ax = apl.subplots(1, 1, figsize=(360, 360))
    s = ax.plot_surface(X, Y, Z, bounds=((-1, 1),) * 3,
                        azimuth=0, elevation=0, gpu=False)
    s.set_axis_off()
    s.set_texture(_ramp_texture(), cull_backfaces=True)
    return fig, s


def _drag(page, dx, dy):
    # Must be the PANEL's plotCanvas: the first canvas in the DOM is the
    # hidden, zero-sized gpuCanvas, whose rect would put the drag at (0, 0).
    box = page.evaluate(
        """() => {
          for (const p of window._api.api.panels.values()) {
            if (p.kind !== '3d') continue;
            const c = p.plotCanvas.getBoundingClientRect();
            return {cx: c.left + c.width/2, cy: c.top + c.height/2};
          }
        }""")
    page.mouse.move(box["cx"], box["cy"])
    page.mouse.down()
    page.mouse.move(box["cx"] + dx, box["cy"] + dy, steps=20)
    page.mouse.up()
    page.wait_for_timeout(200)


def _view(page):
    return page.evaluate("""() => {
      for (const p of window._api.api.panels.values())
        if (p.kind === '3d') return {az: p.state.azimuth, el: p.state.elevation};
    }""")


class TestOrbitDirection:
    """Camera-angle level: which way do the angles move?"""

    def test_drag_right_decreases_azimuth(self, orbit_page):
        page = orbit_page(_globe()[0])
        assert _view(page)["az"] == pytest.approx(0, abs=1e-6)
        _drag(page, 100, 0)
        assert _view(page)["az"] < -5, (
            "dragging right must LOWER azimuth so the surface follows the "
            "cursor; a positive azimuth sweeps the surface the other way")

    def test_drag_left_increases_azimuth(self, orbit_page):
        page = orbit_page(_globe()[0])
        _drag(page, -100, 0)
        assert _view(page)["az"] > 5

    def test_drag_down_raises_elevation(self, orbit_page):
        page = orbit_page(_globe()[0])
        _drag(page, 0, 80)
        assert _view(page)["el"] > 5, (
            "dragging down must RAISE elevation — pulling the near face down "
            "tips the top toward the camera")

    def test_drag_up_lowers_elevation(self, orbit_page):
        page = orbit_page(_globe()[0])
        _drag(page, 0, -80)
        assert _view(page)["el"] < -5


def _export(page):
    from anyplotlib.tests._png_utils import decode_png
    url = page.evaluate(
        "() => window._api.exportPNG({scale: 1}).then(r => r.dataUrl)")
    return decode_png(base64.b64decode(url.split(",", 1)[1])).astype(int)


def _sphere_row(arr):
    """(indices, red profile) along the image's centre row, sphere pixels only.

    The blue channel is a constant 120 in the texture, so it identifies what
    is sphere and what is background.
    """
    h = arr.shape[0]
    row = arr[h // 2, :, :3]
    on = np.nonzero((row[:, 2] > 60) & (row[:, 2] < 200))[0]
    return on, row[on, 0]


def _x_of_red(arr, target):
    """Screen x where the longitude ramp reaches *target*.

    Longitude increases monotonically across the visible hemisphere, so the
    red profile is monotonic and the crossing is unique — but only for a
    target that is actually in range, hence taking it from a live frame
    rather than hard-coding one.
    """
    on, red = _sphere_row(arr)
    if len(on) < 20:
        return None
    cross = np.nonzero((red[:-1] - target) * (red[1:] - target) <= 0)[0]
    return float(on[cross[0]]) if len(cross) else None


class TestSurfaceFollowsCursor:
    """Pixel level: does the texture actually move with the cursor?"""

    def test_texture_moves_right_with_a_rightward_drag(self, orbit_page):
        page = orbit_page(_globe()[0])
        page.wait_for_timeout(900)          # async texture decode

        before = _export(page)
        on, red = _sphere_row(before)
        assert len(on) > 40, "sphere did not render"
        # Track the longitude that starts at the centre of the disc; a modest
        # drag keeps it comfortably on the visible hemisphere.
        mid = len(on) // 2
        target = float(red[mid])
        x_before = float(on[mid])

        _drag(page, 40, 0)
        x_after = _x_of_red(_export(page), target)
        assert x_after is not None, "lost track of the meridian after the drag"
        assert x_after > x_before + 4, (
            f"the tracked meridian moved {x_before:.0f} -> {x_after:.0f}; it "
            f"must follow the cursor to the right, not run away from it")

"""
tests/test_plot3d/test_gpu_depth.py
===================================

Depth-ordering contract for the WebGPU 3-D paths.

``_gpuMatrix`` emits ``clip.z`` from the geometry's depth into the screen, and
every depth-tested GPU pipeline compares with ``less`` against a 1.0 clear —
so ``clip.z`` MUST increase with depth for the nearest fragment to win.  The
sign was originally negated, which inverted the test: a GPU scatter cloud
painted its far points over its near ones, and (once textured surfaces gained
a GPU path) a sphere rendered inside-out, showing the far hemisphere.

It went unnoticed for scatter because the artifact only shows where two points
overlap on screen, and voxels — the other GPU consumer — disable depth writes
entirely, so they never exercised the comparison.

These tests pin the behaviour against the Canvas2D path, which orders by an
explicit back-to-front sort and is the reference.
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
from anyplotlib.tests._png_utils import decode_png
from anyplotlib.tests.conftest import gpu3d_diag, wait_3d_settled


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
def render(_pw_gpu_browser):
    """Render a figure in the WebGPU browser → (pixels, {gpu, active})."""
    pages, paths = [], []

    def _render(fig, panel_id):
        html = (_MOUNT_PAGE
                .replace("__STATE__", json.dumps(figure_state(fig)))
                .replace("__ESM__", json.dumps(esm_path().read_text(encoding="utf-8"))))
        with tempfile.NamedTemporaryFile(suffix=".html", mode="w",
                                         encoding="utf-8", delete=False) as fh:
            fh.write(html)
            tmp = pathlib.Path(fh.name)
        paths.append(tmp)
        page = _pw_gpu_browser.new_page()
        pages.append(page)
        page.goto(tmp.as_uri())
        page.wait_for_function("() => window._aplReady === true", timeout=20_000)
        # Device init is async and schedules the activation redraw itself, so
        # wait for the panel's GPU decision to settle instead of sleeping a
        # fixed amount (which races a slow runner — see wait_3d_settled).
        wait_3d_settled(page)
        info = page.evaluate(
            """(pid) => {
                const p = window._api.api.panels.get(pid);
                return p ? { gpu: p._gpu, active: !!p._gpuActiveNow } : null;
            }""", panel_id)
        if info is not None:
            info["diag"] = gpu3d_diag(page).get(panel_id)
        url = page.evaluate(
            "() => window._api.exportPNG({scale: 1}).then(r => r.dataUrl)")
        px = decode_png(base64.b64decode(url.split(",", 1)[1])).astype(int)
        return px, info

    yield _render
    for p in pages:
        try:
            p.close()
        except Exception:
            pass
    for f in paths:
        f.unlink(missing_ok=True)


def _occluding_pair(gpu):
    """Two points that coincide on screen, differing ONLY in depth.

    The camera's into-screen axis for (azimuth 0, elevation 30) is the second
    row of ``_rot3``: ``(0, cos30, -sin30)``.  Placing the pair along it makes
    them project to the same pixel, so whichever is drawn on top is exactly
    the depth-test answer.  Near is red, far is blue.

    NB the elevation is 30 rather than a cleaner 0 because the renderer reads
    it as ``st.elevation || 30`` — a passed 0 is falsy and becomes 30.
    """
    e = np.radians(30.0)
    d = np.array([0.0, np.cos(e), -np.sin(e)])
    pts = np.vstack([-0.8 * d, 0.8 * d])
    fig, ax = apl.subplots(1, 1, figsize=(240, 240))
    s = ax.scatter3d(pts[:, 0], pts[:, 1], pts[:, 2],
                     colors=["#ff0000", "#0000ff"], point_size=30,
                     bounds=((-1, 1),) * 3, gpu=gpu)
    s.set_axis_off()
    s.set_view(azimuth=0)
    return fig, s


def _centre(arr):
    h, w = arr.shape[:2]
    return arr[h // 2, w // 2, :3]


class TestScatterDepth:
    def test_canvas_draws_the_near_point_on_top(self, render):
        fig, s = _occluding_pair(False)
        arr, info = render(fig, s._id)
        assert not info["active"]
        px = _centre(arr)
        assert px[0] > px[2] + 60, f"expected the near (red) point, got {px}"

    def test_gpu_draws_the_near_point_on_top(self, render):
        fig, s = _occluding_pair("always")
        arr, info = render(fig, s._id)
        assert info["active"], "GPU path did not activate"
        px = _centre(arr)
        assert px[0] > px[2] + 60, (
            f"expected the near (red) point, got {px} — clip.z sign inverted?")

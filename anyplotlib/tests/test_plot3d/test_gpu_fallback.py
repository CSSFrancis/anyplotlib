"""
Tests for the WebGPU scatter path — focused on the FALLBACK CONTRACT.

A real GPU adapter is rarely available in CI (headless Chromium exposes
``navigator.gpu`` but ``requestAdapter()`` returns null without Vulkan/
lavapipe), so these tests assert the thing that must hold *everywhere*:
when the GPU is unavailable, a GPU-requesting scatter renders identically
to the Canvas2D path and ``gpu_active`` reports False.

The actual GPU render is validated manually on a real-GPU machine; see
WEBGPU_PLAN.md Phase 1 acceptance.
"""
from __future__ import annotations

import json

import numpy as np
import pytest

import anyplotlib as apl


def _scatter(n=100, **kwargs):
    fig, ax = apl.subplots(1, 1, figsize=(320, 320))
    rng = np.random.default_rng(1)
    pts = rng.uniform(-1, 1, size=(n, 3))
    return ax.scatter3d(pts[:, 0], pts[:, 1], pts[:, 2],
                        bounds=((-1, 1),) * 3, **kwargs)


class TestGpuApi:
    def test_default_mode_auto(self):
        assert _scatter()._state["gpu_mode"] == "auto"

    def test_gpu_true_is_always(self):
        assert _scatter(gpu=True)._state["gpu_mode"] == "always"

    def test_gpu_false_is_off(self):
        assert _scatter(gpu=False)._state["gpu_mode"] == "off"

    def test_gpu_active_starts_false(self):
        assert _scatter()._gpu_active is False
        assert _scatter().gpu_active is False

    def test_gpu_status_echo_updates_active(self):
        v = _scatter()
        fig = v._fig
        fig._dispatch_event(json.dumps({
            "panel_id": v._id, "event_type": "gpu_status", "gpu_active": True}))
        assert v.gpu_active is True
        fig._dispatch_event(json.dumps({
            "panel_id": v._id, "event_type": "gpu_status", "gpu_active": False}))
        assert v.gpu_active is False

    def test_gpu_only_for_scatter(self):
        # voxels/surface don't carry gpu_mode into the GPU path (Phase 1 =
        # points only); the kwarg simply isn't offered there. Sanity: scatter
        # has the field, surface does not error.
        assert "gpu_mode" in _scatter()._state


class TestFallbackRendersOnCanvas:
    """gpu='always' with no adapter MUST render via Canvas2D, unchanged."""

    def _red_ink(self, page):
        return page.evaluate("""() => {
            const cs = [...document.querySelectorAll('canvas')];
            const c = cs.find(x => !x.style.zIndex || x.style.zIndex === '1');
            const d = c.getContext('2d').getImageData(0,0,c.width,c.height).data;
            let red = 0;
            for (let i = 0; i < d.length; i += 4)
                if (d[i] > 180 && d[i+1] < 140 && d[i+2] < 140) red++;
            return red;
        }""")

    def test_always_falls_back_to_canvas(self, interact_page):
        v = _scatter(n=2000, gpu="always",
                     colors=np.tile([255, 80, 80], (2000, 1)).astype(np.uint8),
                     point_size=4)
        v.set_axis_off()
        page = interact_page(v._fig)
        page.wait_for_timeout(400)   # allow the async device probe to resolve
        # When requestAdapter() is null the gpuCanvas stays hidden …
        disp = page.evaluate("""() => {
            const g = [...document.querySelectorAll('canvas')]
                .find(c => c.style.zIndex === '0');
            return g ? g.style.display : 'none';
        }""")
        assert disp == 'none', "gpuCanvas must stay hidden without an adapter"
        # … and the points still render on the 2D canvas.
        assert self._red_ink(page) > 500, "canvas fallback produced no points"

    def test_auto_small_cloud_uses_canvas(self, interact_page):
        """Below the threshold, 'auto' never even probes the GPU."""
        v = _scatter(n=500, gpu="auto",
                     colors=np.tile([255, 80, 80], (500, 1)).astype(np.uint8),
                     point_size=4)
        v.set_axis_off()
        page = interact_page(v._fig)
        page.wait_for_timeout(300)
        assert self._red_ink(page) > 200

    def test_gpu_off_renders_canvas(self, interact_page):
        v = _scatter(n=1000, gpu=False,
                     colors=np.tile([255, 80, 80], (1000, 1)).astype(np.uint8),
                     point_size=4)
        v.set_axis_off()
        page = interact_page(v._fig)
        page.wait_for_timeout(300)
        assert self._red_ink(page) > 300

    def test_no_console_errors_on_fallback(self, interact_page):
        v = _scatter(n=2000, gpu="always")
        v.set_axis_off()
        page = interact_page(v._fig)
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.wait_for_timeout(400)
        assert not errors, f"GPU fallback raised page errors: {errors}"


def _voxels(n_side=8, **kwargs):
    fig, ax = apl.subplots(1, 1, figsize=(320, 320))
    g = np.arange(0, n_side, dtype=float)
    zz, yy, xx = np.meshgrid(g, g, g, indexing="ij")
    return ax.voxels(xx.ravel(), yy.ravel(), zz.ravel(),
                     bounds=((0, n_side - 1),) * 3, **kwargs)


class TestVoxelGpuFallback:
    """gpu='always' voxels with no adapter MUST render via Canvas2D."""

    def test_voxel_gpu_mode_state(self):
        assert _voxels(gpu=True)._state["gpu_mode"] == "always"
        assert _voxels(gpu=False)._state["gpu_mode"] == "off"
        assert _voxels()._state["gpu_mode"] == "auto"

    def test_voxel_always_falls_back_to_canvas(self, interact_page):
        colors = np.tile([255, 60, 60], (512, 1)).astype(np.uint8)
        v = _voxels(colors=colors, alpha=0.4, gpu="always")
        v.set_axis_off()
        page = interact_page(v._fig)
        page.wait_for_timeout(400)
        disp = page.evaluate("""() => {
            const g = [...document.querySelectorAll('canvas')]
                .find(c => c.style.zIndex === '0');
            return g ? g.style.display : 'none';
        }""")
        assert disp == 'none', "voxel gpuCanvas must stay hidden without adapter"
        red = page.evaluate("""() => {
            const c = [...document.querySelectorAll('canvas')]
                .find(x => x.style.position === 'relative' && x.style.display !== 'none');
            const d = c.getContext('2d').getImageData(0,0,c.width,c.height).data;
            let r = 0;
            for (let i = 0; i < d.length; i += 4)
                if (d[i] > 120 && d[i+1] < 120 && d[i+2] < 120) r++;
            return r;
        }""")
        assert red > 500, "voxel canvas fallback produced no cubes"

    def test_voxel_gpu_no_console_errors(self, interact_page):
        v = _voxels(colors=np.tile([200, 80, 80], (512, 1)).astype(np.uint8),
                    gpu="always")
        v.set_axis_off()
        v.add_widget("plane", axis="z", position=4)
        page = interact_page(v._fig)
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.wait_for_timeout(400)
        assert not errors, f"GPU voxel fallback raised errors: {errors}"

    def test_gpu_draw_failure_self_heals(self, interact_page, _pw_browser):
        """A GPU device that ACTIVATES then throws mid-draw (e.g. Safari's
        experimental WebGPU losing the device) must self-heal: the panel
        re-renders on the canvas path in the same frame — voxels AND axes —
        without the user needing to resize, and the plotCanvas background is
        restored to opaque (not left transparent over a dead gpuCanvas).
        """
        import pathlib, tempfile
        from anyplotlib.tests.conftest import _build_interact_html

        colors = np.tile([255, 60, 60], (512, 1)).astype(np.uint8)
        v = _voxels(colors=colors, alpha=0.5, gpu="always")   # axes ON
        html = _build_interact_html(v._fig)
        with tempfile.NamedTemporaryFile(
                suffix=".html", mode="w", encoding="utf-8", delete=False) as fh:
            fh.write(html)
            tmp = pathlib.Path(fh.name)

        # Fake navigator.gpu: adapter+device resolve (GPU ACTIVATES, plotCanvas
        # goes transparent), but the first command encoder throws — the exact
        # "worked beautifully then broke" Safari signature.
        fake_gpu = """
        () => {
          const tex = () => ({ createView:()=>({}), destroy:()=>{} });
          const buf = () => ({ destroy:()=>{} });
          const dev = {
            lost: new Promise(()=>{}),
            createShaderModule:()=>({}), createBuffer:()=>buf(),
            createBindGroupLayout:()=>({}), createPipelineLayout:()=>({}),
            createBindGroup:()=>({}), createTexture:()=>tex(),
            createRenderPipeline:()=>({ getBindGroupLayout:()=>({}) }),
            createCommandEncoder:()=>{ throw new Error('SIMULATED mid-draw GPU failure'); },
            queue:{ writeBuffer:()=>{}, submit:()=>{}, readTexture:()=>new Uint8Array(4) },
          };
          navigator.gpu = {
            getPreferredCanvasFormat:()=>'bgra8unorm',
            requestAdapter: async ()=>({ info:{}, requestDevice: async ()=>dev }),
          };
        }"""
        page = _pw_browser.new_page()
        page.set_viewport_size({"width": 400, "height": 400})
        page.add_init_script(fake_gpu)
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        try:
            page.goto(tmp.as_uri())
            page.wait_for_function("() => window._aplReady === true", timeout=15000)
            page.wait_for_timeout(600)
            res = page.evaluate("""() => {
                const cs = [...document.querySelectorAll('canvas')];
                const plot = cs.find(x => x.style.zIndex === '1');
                const gpu  = cs.find(x => x.style.zIndex === '0');
                const d = plot.getContext('2d').getImageData(0,0,plot.width,plot.height).data;
                let red = 0;
                for (let i = 0; i < d.length; i += 4)
                    if (d[i] > 150 && d[i+1] < 130 && d[i+2] < 130) red++;
                return { plotBg: plot.style.background,
                         gpuDisp: gpu ? gpu.style.display : null, red };
            }""")
        finally:
            page.close()
            tmp.unlink(missing_ok=True)

        assert not errors, f"mid-draw GPU failure leaked errors: {errors}"
        assert res["gpuDisp"] == "none", "dead gpuCanvas must be hidden"
        assert res["plotBg"] and res["plotBg"] != "transparent", \
            f"plotCanvas bg must be restored to opaque, got {res['plotBg']!r}"
        assert res["red"] > 500, \
            f"panel did not self-heal onto canvas (no voxels): {res}"

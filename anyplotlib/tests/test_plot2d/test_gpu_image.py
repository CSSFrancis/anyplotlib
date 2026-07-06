"""
WebGPU 2-D image path — Python-side wiring + Canvas2D-fallback rendering.

Playwright's bundled Chromium has NO WebGPU, so these tests exercise the FALLBACK
contract: the gpu param maps to gpu_mode, the gpu_active echo starts False, and a
large image still renders correctly via Canvas2D when the GPU is absent. The
GPU-active render path itself is verified in the consuming app on real hardware
(see the SpyDE electron webgpu_image.spec.ts).
"""
from __future__ import annotations

import numpy as np
import pytest

import anyplotlib as apl


class TestGpuModeParam:
    def test_default_is_auto(self):
        fig, ax = apl.subplots(1, 1)
        p = ax.imshow(np.zeros((4, 4)))
        assert p._state["gpu_mode"] == "auto"

    def test_true_forces_always(self):
        fig, ax = apl.subplots(1, 1)
        p = ax.imshow(np.zeros((4, 4)), gpu=True)
        assert p._state["gpu_mode"] == "always"

    def test_false_and_off_disable(self):
        fig, ax = apl.subplots(1, 1)
        assert ax.imshow(np.zeros((4, 4)), gpu=False)._state["gpu_mode"] == "off"
        assert ax.imshow(np.zeros((4, 4)), gpu="off")._state["gpu_mode"] == "off"


class TestGpuActiveEcho:
    def test_starts_false(self):
        fig, ax = apl.subplots(1, 1)
        p = ax.imshow(np.zeros((4, 4)), gpu=True)
        assert p.gpu_active is False           # nothing has reported activation

    def test_set_gpu_active_updates_property_and_state(self):
        fig, ax = apl.subplots(1, 1)
        p = ax.imshow(np.zeros((4, 4)))
        p._set_gpu_active(True)
        assert p.gpu_active is True
        assert p._state["gpu_active"] is True
        p._set_gpu_active(False)
        assert p.gpu_active is False

    def test_gpu_status_event_dispatches_to_plot(self):
        # The Figure routes a gpu_status event to plot._set_gpu_active.
        fig, ax = apl.subplots(1, 1)
        p = ax.imshow(np.zeros((8, 8)), gpu=True)
        import json
        fig._dispatch_event(json.dumps({
            "panel_id": p._id, "event_type": "gpu_status", "gpu_active": True}))
        assert p.gpu_active is True


class TestCanvas2dFallbackRender:
    def test_gpu_false_always_renders_on_canvas(self, interact_page):
        # gpu=False must NEVER take the GPU path, regardless of whether the test
        # Chromium has WebGPU — the image renders on the Canvas2D plotCanvas.
        w = h = 1200                                   # > 1 Mpx (would be GPU in auto)
        img = np.tile(np.linspace(0, 1, w, dtype=np.float32), (h, 1))
        fig, ax = apl.subplots(1, 1, figsize=(300, 300))
        p = ax.imshow(img, cmap="viridis", gpu=False)
        page = interact_page(fig)
        page.wait_for_timeout(300)

        info = page.evaluate("""() => {
            const c = document.querySelector('canvas');   // plotCanvas (image)
            const ctx = c.getContext('2d');
            const w = c.width, h = c.height;
            const left  = Array.from(ctx.getImageData(Math.round(w*0.1), h*0.5|0, 1, 1).data);
            const right = Array.from(ctx.getImageData(Math.round(w*0.9), h*0.5|0, 1, 1).data);
            return { left, right };
        }""")
        # A viridis ramp: non-black and varying L→R → the Canvas2D LUT ran.
        assert sum(info["left"][:3]) + sum(info["right"][:3]) > 0
        assert info["left"][:3] != info["right"][:3], "ramp did not render on canvas"
        assert p.gpu_active is False               # gpu=False never activates GPU

    def test_small_image_stays_on_canvas_in_auto(self, interact_page):
        # A sub-threshold image in auto mode stays on Canvas2D (no GPU attempt).
        img = np.tile(np.linspace(0, 1, 64, dtype=np.float32), (64, 1))  # 4 Kpx
        fig, ax = apl.subplots(1, 1, figsize=(200, 200))
        p = ax.imshow(img, cmap="viridis", gpu="auto")
        page = interact_page(fig)
        page.wait_for_timeout(300)
        rendered = page.evaluate("""() => {
            const c = document.querySelector('canvas');
            const ctx = c.getContext('2d');
            const px = Array.from(ctx.getImageData((c.width*0.5)|0, (c.height*0.5)|0, 1, 1).data);
            return px.slice(0,3).some(v => v > 0);
        }""")
        assert rendered, "small image did not render on canvas"
        assert p.gpu_active is False

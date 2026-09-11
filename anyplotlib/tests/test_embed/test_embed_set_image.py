"""
Playwright tests for ``handle.setImage``, the binary image setter.

A navigated page scrubs frames as fast as the user drags, so the cost the
caller pays to hand one over has to be independent of the frame size.  These
tests pin that: the push is a side-table write plus one animation-frame
request, and the paint it schedules is the renderer's ordinary blit.
"""
from __future__ import annotations

import numpy as np
import pytest

import anyplotlib as apl

# A frame push must stay well inside one 60 Hz frame even at 2048², where the
# base64 route cost 129-136 ms of main-thread time.
PUSH_BUDGET_MS = 5.0

# One measured push per frame, enough samples for a stable median.
FRAME_COUNT = 40


def _figure_with_panel():
    """A small grayscale panel; setImage grows it to the size under test."""
    fig, ax = apl.subplots(1, 1, figsize=(320, 320))
    plot = ax.imshow(np.zeros((16, 16), dtype=np.uint8), cmap="gray")
    return fig, plot


_PUSH_SCRIPT = """
async (args) => {
  const [panelId, size, frameCount] = args;
  const handle = window._handle;
  const pixels = size * size;
  // Eight distinct frames, cycled: enough to prove the canvas follows the
  // pushes without holding forty full-size buffers alive at once.
  const frames = [];
  for (let f = 0; f < 8; f++) {
    const frame = new Uint8Array(pixels);
    for (let i = 0; i < pixels; i++) frame[i] = (i + f * 31) & 255;
    frames.push(frame);
  }
  const nextFrame = () => new Promise((r) => requestAnimationFrame(r));
  const durations = [];
  for (let n = 0; n < frameCount; n++) {
    const frame = frames[n % frames.length];
    const start = performance.now();
    handle.setImage(panelId, frame, size, size, {display_min: 0, display_max: 255});
    durations.push(performance.now() - start);
    await nextFrame();
    await nextFrame();
  }
  // performance.now() is clamped to 100 us in a page that is not
  // cross-origin-isolated, so one push lands on 0.0 or 0.1 and the median says
  // little. Timing the whole run of pushes back to back resolves it; they
  // coalesce into one paint, which is the steady-state scrub cost.
  const batchCount = frameCount * 25;
  const batchStart = performance.now();
  for (let n = 0; n < batchCount; n++)
    handle.setImage(panelId, frames[n % frames.length], size, size,
                    {display_min: 0, display_max: 255});
  const perPush = (performance.now() - batchStart) / batchCount;
  await nextFrame();
  await nextFrame();

  // The first push is the one that resizes the panel to the new frame, so it
  // is reported apart from the steady-state scrub it is not representative of.
  const first = durations[0];
  const rest = durations.slice(1).sort((a, b) => a - b);
  return {first, perPush,
          median: rest[rest.length >> 1], worst: rest[rest.length - 1]};
}
"""

_SAMPLE_SCRIPT = """
(args) => {
  const [panelId, ix, iy] = args;
  const panel = window._handle.api.panels.get(panelId);
  const state = panel.state;
  const scale = Math.min(panel.imgW / state.image_width,
                         panel.imgH / state.image_height);
  const fitWidth = state.image_width * scale, fitHeight = state.image_height * scale;
  const left = (panel.imgW - fitWidth) / 2, top = (panel.imgH - fitHeight) / 2;
  const device = panel.plotCanvas.width / panel.imgW;
  const x = Math.floor((left + (ix + 0.5) / state.image_width * fitWidth) * device);
  const y = Math.floor((top + (iy + 0.5) / state.image_height * fitHeight) * device);
  const data = panel.plotCanvas.getContext('2d').getImageData(x, y, 1, 1).data;
  return [data[0], data[1], data[2]];
}
"""


def _sample(page, panel_id, ix, iy):
    return page.evaluate(_SAMPLE_SCRIPT, [panel_id, ix, iy])


def _colormap_rgb(page, panel_id, code):
    """The colour the renderer's lookup table gives one 8-bit code."""
    return page.evaluate(
        "(args) => window._handle.api.panels.get(args[0])"
        "  .state.colormap_data[args[1]]",
        [panel_id, code])


class TestSetImageCost:
    @pytest.mark.parametrize("size", [512, 2048])
    def test_push_median_is_independent_of_frame_size(self, mount_page, size, capsys):
        fig, plot = _figure_with_panel()
        page = mount_page(fig)
        timings = page.evaluate(_PUSH_SCRIPT, [plot._id, size, FRAME_COUNT])
        with capsys.disabled():
            print(f"\nsetImage {size}x{size} over {FRAME_COUNT} frames: "
                  f"median {timings['median']:.3f} ms, worst {timings['worst']:.3f} ms, "
                  f"{timings['perPush']:.4f} ms per push back to back, "
                  f"first (resizes the panel) {timings['first']:.3f} ms")
        assert timings["median"] < PUSH_BUDGET_MS, (
            f"setImage median {timings['median']:.3f} ms at {size}² exceeds "
            f"the {PUSH_BUDGET_MS} ms budget")
        # The back-to-back mean is the one number the clock resolves properly,
        # and it is where a per-frame blit would show up as a regression.
        assert timings["perPush"] < PUSH_BUDGET_MS, (
            f"setImage costs {timings['perPush']:.4f} ms per push at {size}², "
            f"over the {PUSH_BUDGET_MS} ms budget")


class TestSetImagePaints:
    def test_pushed_frames_reach_the_canvas(self, mount_page):
        fig, plot = _figure_with_panel()
        page = mount_page(fig)

        def push(fill):
            page.evaluate(
                """async (args) => {
                    const [panelId, fill] = args;
                    const frame = new Uint8Array(64 * 64).fill(fill);
                    window._handle.setImage(panelId, frame, 64, 64,
                                            {display_min: 0, display_max: 255});
                    await new Promise((r) => requestAnimationFrame(r));
                    await new Promise((r) => requestAnimationFrame(r));
                }""",
                [plot._id, fill])

        push(40)
        dark = _sample(page, plot._id, 32, 32)
        push(210)
        bright = _sample(page, plot._id, 32, 32)
        assert dark == _colormap_rgb(page, plot._id, 40), (
            f"pushed code 40 painted as {dark}")
        assert bright == _colormap_rgb(page, plot._id, 210), (
            f"pushed code 210 painted as {bright}")

    def test_geometry_follows_the_bytes(self, mount_page):
        """A frame of a different size repaints at that size, not the old one."""
        fig, plot = _figure_with_panel()
        page = mount_page(fig)
        page.evaluate(
            """async (panelId) => {
                const frame = new Uint8Array(32 * 8).fill(100);
                window._handle.setImage(panelId, frame, 32, 8);
                await new Promise((r) => requestAnimationFrame(r));
            }""",
            plot._id)
        geometry = page.evaluate(
            "(id) => { const s = window._handle.api.panels.get(id).state;"
            "  return [s.image_width, s.image_height, s.base_width]; }",
            plot._id)
        assert geometry == [32, 8, 0]

    def test_length_mismatch_throws(self, mount_page):
        fig, plot = _figure_with_panel()
        page = mount_page(fig)
        message = page.evaluate(
            """(panelId) => {
                try {
                  window._handle.setImage(panelId, new Uint8Array(10), 8, 8);
                  return null;
                } catch (e) { return String(e.message); }
            }""",
            plot._id)
        assert message is not None, "a short buffer was accepted"
        assert "64 bytes" in message and "got 10" in message

    def test_unknown_panel_throws(self, mount_page):
        fig, _ = _figure_with_panel()
        page = mount_page(fig)
        message = page.evaluate(
            """() => {
                try {
                  window._handle.setImage('nope', new Uint8Array(4), 2, 2);
                  return null;
                } catch (e) { return String(e.message); }
            }""")
        assert message is not None and "unknown panel" in message

    def test_no_sync_echo(self, mount_page):
        """The pixels are an inbound update; they must not bounce to onSync."""
        fig, plot = _figure_with_panel()
        page = mount_page(fig)
        page.evaluate("() => { window._syncs = []; }")
        page.evaluate(
            """async (panelId) => {
                window._handle.setImage(panelId, new Uint8Array(64 * 64).fill(7),
                                        64, 64, {display_min: 0, display_max: 255});
                await new Promise((r) => requestAnimationFrame(r));
                await new Promise((r) => requestAnimationFrame(r));
            }""",
            plot._id)
        keys = page.evaluate("() => (window._syncs || []).map((s) => s.key)")
        assert keys == [], f"setImage echoed through onSync: {keys}"

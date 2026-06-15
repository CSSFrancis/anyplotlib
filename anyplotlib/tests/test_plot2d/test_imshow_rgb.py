"""
Tests for true-colour (H, W, 3|4) imshow support.

Unit tests cover state encoding and dtype handling; Playwright tests verify
actual rendered pixel colours on the canvas.
"""
from __future__ import annotations

import base64

import numpy as np
import pytest

import anyplotlib as apl


def _rgb_quadrants(n=32):
    """Image with pure-red TL, pure-green TR, pure-blue BL, white BR."""
    img = np.zeros((n, n, 3), dtype=np.uint8)
    h = n // 2
    img[:h, :h] = [255, 0, 0]
    img[:h, h:] = [0, 255, 0]
    img[h:, :h] = [0, 0, 255]
    img[h:, h:] = [255, 255, 255]
    return img


class TestRgbState:
    def test_uint8_rgb_sets_state(self):
        fig, ax = apl.subplots(1, 1)
        v = ax.imshow(_rgb_quadrants())
        assert v._state["is_rgb"] is True
        raw = base64.b64decode(v._state["image_b64"])
        assert len(raw) == 32 * 32 * 4          # RGBA bytes
        assert raw[0:4] == bytes([255, 0, 0, 255])

    def test_float_01_rgb_scaled(self):
        fig, ax = apl.subplots(1, 1)
        v = ax.imshow(np.full((4, 4, 3), 0.5))
        raw = base64.b64decode(v._state["image_b64"])
        assert raw[0] == 127 or raw[0] == 128   # 0.5 * 255

    def test_rgba_alpha_preserved(self):
        img = np.zeros((4, 4, 4), dtype=np.uint8)
        img[..., 3] = 99
        fig, ax = apl.subplots(1, 1)
        v = ax.imshow(img)
        raw = base64.b64decode(v._state["image_b64"])
        assert raw[3] == 99

    def test_grayscale_unchanged(self):
        fig, ax = apl.subplots(1, 1)
        v = ax.imshow(np.zeros((8, 8)))
        assert v._state["is_rgb"] is False
        assert len(base64.b64decode(v._state["image_b64"])) == 64  # 1 byte/px

    def test_two_channel_raises(self):
        fig, ax = apl.subplots(1, 1)
        with pytest.raises(ValueError, match="3 .RGB. or 4"):
            ax.imshow(np.zeros((8, 8, 2)))

    def test_set_data_switches_modes(self):
        fig, ax = apl.subplots(1, 1)
        v = ax.imshow(np.zeros((8, 8)))
        v.set_data(_rgb_quadrants(8))
        assert v._state["is_rgb"] is True
        v.set_data(np.zeros((8, 8)))
        assert v._state["is_rgb"] is False

    def test_origin_lower_flips_rgb(self):
        img = np.zeros((2, 2, 3), dtype=np.uint8)
        img[0, 0] = [255, 0, 0]                 # red in row 0
        fig, ax = apl.subplots(1, 1)
        v = ax.imshow(img, origin="lower")
        raw = base64.b64decode(v._state["image_b64"])
        # flipud → red pixel is now in the LAST row, first column
        last_row_first_px = raw[(2 * 1 + 0) * 4: (2 * 1 + 0) * 4 + 4]
        assert last_row_first_px == bytes([255, 0, 0, 255])


class TestRgbRendering:
    def test_quadrant_colors_on_canvas(self, interact_page):
        fig, ax = apl.subplots(1, 1, figsize=(300, 300))
        ax.imshow(_rgb_quadrants())
        page = interact_page(fig)
        page.wait_for_timeout(150)

        px = page.evaluate("""() => {
            const c = document.querySelector('canvas');
            const ctx = c.getContext('2d');
            const w = c.width, h = c.height;
            const grab = (fx, fy) => Array.from(
                ctx.getImageData(Math.round(w*fx), Math.round(h*fy), 1, 1).data);
            return { tl: grab(0.25, 0.25), tr: grab(0.75, 0.25),
                     bl: grab(0.25, 0.75), br: grab(0.75, 0.75) };
        }""")
        assert px["tl"][:3] == [255, 0, 0], f"top-left not red: {px['tl']}"
        assert px["tr"][:3] == [0, 255, 0], f"top-right not green: {px['tr']}"
        assert px["bl"][:3] == [0, 0, 255], f"bottom-left not blue: {px['bl']}"
        assert px["br"][:3] == [255, 255, 255], f"bottom-right not white: {px['br']}"

    def test_colorbar_suppressed_for_rgb(self, interact_page):
        fig, ax = apl.subplots(1, 1, figsize=(300, 300))
        q = np.linspace(0, 1, 32)
        v = ax.imshow(_rgb_quadrants(), axes=[q, q])
        v.set_colorbar_visible(True)            # must be ignored for RGB
        page = interact_page(fig)
        page.wait_for_timeout(150)
        visible = page.evaluate("""() => {
            for (const c of document.querySelectorAll('canvas')) {
                const left = parseFloat(c.style.left || '0');
                if (c.width <= 80 && left > 150 && c.style.display !== 'none')
                    return true;   // a visible colorbar-sized canvas
            }
            return false;
        }""")
        assert not visible, "colorbar must stay hidden for RGB images"

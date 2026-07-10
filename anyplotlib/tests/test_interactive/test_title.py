"""
Playwright tests verifying 2D title rendering.

Title rendering
---------------
2D image panels always reserve a PAD_T (12 px) strip at the top, matching 1D
behaviour.  ``set_title(...)`` draws text in that strip via a dedicated
``titleCanvas`` (z-index 8) above the plotCanvas.  The title must be visible
(non-zero alpha pixels) regardless of whether physical axes are provided.
"""
from __future__ import annotations

import numpy as np

import anyplotlib as apl


# ── helpers ───────────────────────────────────────────────────────────────────

def _title_pixel_count(page) -> int:
    """Count non-transparent pixels in the titleCanvas (z-index:8)."""
    return page.evaluate("""() => {
        const tc = Array.from(document.querySelectorAll('canvas'))
                        .find(c => c.style.zIndex === '8');
        if (!tc) return -1;
        const ctx = tc.getContext('2d');
        const d = ctx.getImageData(0, 0, tc.width, tc.height).data;
        let n = 0;
        for (let i = 3; i < d.length; i += 4) { if (d[i] > 0) n++; }
        return n;
    }""")


def _title_canvas_info(page) -> dict:
    """Return display/position/size info about the titleCanvas."""
    return page.evaluate("""() => {
        const tc = Array.from(document.querySelectorAll('canvas'))
                        .find(c => c.style.zIndex === '8');
        if (!tc) return null;
        return {
            display: tc.style.display,
            top: tc.style.top,
            left: tc.style.left,
            cssWidth: tc.style.width,
            cssHeight: tc.style.height,
            physW: tc.width,
            physH: tc.height,
        };
    }""")


# ══════════════════════════════════════════════════════════════════════════════
# 2D title rendering
# ══════════════════════════════════════════════════════════════════════════════

class TestTitle2DRendering:
    """Title text must appear above the image in the PAD_T strip."""

    def test_title_canvas_visible_without_axes(self, interact_page):
        """titleCanvas is display:block for imshow WITHOUT explicit axes."""
        fig, ax = apl.subplots(1, 1, figsize=(400, 300))
        plot = ax.imshow(np.zeros((32, 32), dtype=np.float32))
        plot.set_title("Plain imshow title")
        page = interact_page(fig)
        page.wait_for_timeout(200)

        info = _title_canvas_info(page)
        assert info is not None, "titleCanvas not found (z-index:8 canvas missing)"
        assert info["display"] == "block", (
            f"titleCanvas must be display:block, got {info['display']!r}"
        )

    def test_title_canvas_visible_with_axes(self, interact_page):
        """titleCanvas is display:block for imshow WITH explicit axes."""
        fig, ax = apl.subplots(1, 1, figsize=(400, 300))
        plot = ax.imshow(
            np.zeros((32, 32), dtype=np.float32),
            axes=[np.linspace(0, 10, 32)] * 2,
            units="nm",
        )
        plot.set_title("Physical axes title")
        page = interact_page(fig)
        page.wait_for_timeout(200)

        info = _title_canvas_info(page)
        assert info is not None
        assert info["display"] == "block"

    def test_title_text_renders_pixels(self, interact_page):
        """set_title() produces non-transparent pixels in the titleCanvas."""
        fig, ax = apl.subplots(1, 1, figsize=(400, 300))
        plot = ax.imshow(np.zeros((32, 32), dtype=np.float32))
        plot.set_title("Hello World")
        page = interact_page(fig)
        page.wait_for_timeout(200)

        n = _title_pixel_count(page)
        assert n > 0, (
            "set_title() must produce visible pixels in titleCanvas. "
            f"Got {n} non-zero alpha pixels — title is not rendering."
        )

    def test_empty_title_produces_no_pixels(self, interact_page):
        """An empty (unset) title leaves titleCanvas transparent."""
        fig, ax = apl.subplots(1, 1, figsize=(400, 300))
        plot = ax.imshow(np.zeros((32, 32), dtype=np.float32))
        # No set_title call
        page = interact_page(fig)
        page.wait_for_timeout(200)

        n = _title_pixel_count(page)
        assert n == 0, (
            f"Empty title must leave titleCanvas transparent, got {n} pixels"
        )

    def test_title_canvas_in_top_strip(self, interact_page):
        """titleCanvas top=0 and height=PAD_T (12 px) — sits above the image."""
        fig, ax = apl.subplots(1, 1, figsize=(400, 300))
        plot = ax.imshow(np.zeros((32, 32), dtype=np.float32))
        plot.set_title("Position check")
        page = interact_page(fig)
        page.wait_for_timeout(200)

        info = _title_canvas_info(page)
        assert info is not None
        assert info["top"] == "0px", (
            f"titleCanvas must sit at top:0, got top={info['top']!r}"
        )
        assert info["cssHeight"] == "12px", (
            f"titleCanvas height must be PAD_T=12px, got {info['cssHeight']!r}"
        )

    def test_title_above_image_not_overlapping(self, interact_page):
        """titleCanvas sits in the 12px gutter above the plotCanvas (no overlap).

        The plotCanvas must start at top ≥ 12px so the title strip is
        unobstructed.
        """
        fig, ax = apl.subplots(1, 1, figsize=(400, 300))
        plot = ax.imshow(np.zeros((32, 32), dtype=np.float32))
        plot.set_title("No overlap check")
        page = interact_page(fig)
        page.wait_for_timeout(200)

        plot_canvas_top = page.evaluate("""() => {
            // plotCanvas is the FIRST canvas in DOM order (a WebGPU image canvas,
            // if present, is appended after it and sits below via z-index).
            const pc = document.querySelector('canvas');
            return pc ? pc.style.top : null;
        }""")

        assert plot_canvas_top is not None, "plotCanvas not found"
        top_px = int(plot_canvas_top.replace("px", ""))
        assert top_px >= 12, (
            f"plotCanvas top must be >= 12px (PAD_T) so title is above image, "
            f"got top={top_px}px"
        )

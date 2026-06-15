"""
Playwright tests for label font sizes and mini-TeX rendering.

Strategy
--------
Canvas text cannot be read back as strings, so these tests assert on *ink*:

* a larger ``fontsize`` must produce more non-background pixels in the
  axis gutter than a smaller one;
* a TeX string like ``$10^{-3}$`` must render *narrower* than the same
  characters drawn literally (``10^{-3}``) — the ``$`` delimiters are
  consumed and the exponent shrinks to a superscript;
* TeX titles must produce visible pixels in the title canvas.
"""
from __future__ import annotations

import numpy as np

import anyplotlib as apl

PAD_B = 42  # bottom axis gutter height (PAD_* constants in figure_esm.js)


# ── helpers ───────────────────────────────────────────────────────────────────

def _x_gutter(img: np.ndarray) -> np.ndarray:
    """Return the bottom PAD_B-row strip of a widget screenshot."""
    return img[-PAD_B:, :, :3].astype(int)


def _ink_mask(strip: np.ndarray) -> np.ndarray:
    """Boolean mask of pixels that differ from the strip's corner colour."""
    bg = strip[2, 2]
    return np.abs(strip - bg).sum(axis=-1) > 60


def _x_gutter_ink(take_screenshot, label: str, fontsize=None) -> np.ndarray:
    """Render an imshow with the given x label; return the gutter ink mask."""
    fig, ax = apl.subplots(1, 1, figsize=(400, 300))
    plot = ax.imshow(
        np.zeros((32, 32), dtype=np.float32),
        axes=[np.linspace(0, 10, 32)] * 2,
        units="nm",
    )
    if fontsize is None:
        plot.set_xlabel(label)
    else:
        plot.set_xlabel(label, fontsize=fontsize)
    return _ink_mask(_x_gutter(take_screenshot(fig)))


def _title_pixel_count(page) -> int:
    """Count non-transparent pixels in the 2D titleCanvas (z-index:8)."""
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


# ══════════════════════════════════════════════════════════════════════════════


class TestFontsizeRendering:
    def test_larger_fontsize_more_ink(self, take_screenshot):
        small = _x_gutter_ink(take_screenshot, "Distance", fontsize=9)
        large = _x_gutter_ink(take_screenshot, "Distance", fontsize=18)
        assert large.sum() > small.sum() * 1.3, (
            f"fontsize=18 must draw more label ink than fontsize=9 "
            f"(got {large.sum()} vs {small.sum()})"
        )

    def test_tick_label_size_changes_ink(self, take_screenshot):
        def gutter_ink(tick_size):
            fig, ax = apl.subplots(1, 1, figsize=(400, 300))
            plot = ax.imshow(
                np.zeros((32, 32), dtype=np.float32),
                axes=[np.linspace(0, 10, 32)] * 2,
            )
            if tick_size:
                plot.set_tick_label_size(tick_size)
            return _ink_mask(_x_gutter(take_screenshot(fig))).sum()

        assert gutter_ink(16) > gutter_ink(None) * 1.2, (
            "set_tick_label_size(16) must draw more tick ink than the default"
        )


class TestTexRendering:
    def test_tex_label_renders_ink(self, take_screenshot):
        ink = _x_gutter_ink(take_screenshot, r"$10^{-3}$ m")
        assert ink.sum() > 0, "TeX label must render visible pixels"

    def test_tex_consumes_dollars_and_shrinks_exponent(self, take_screenshot):
        """$10^{-3}$ must be narrower than the literal text 10^{-3}.

        The TeX path drops the two ``$`` delimiters and the ``^{}`` braces
        and renders ``-3`` at ~0.68× size, so its ink must span fewer
        columns than the literal 7-glyph string.
        """
        tex = _x_gutter_ink(take_screenshot, r"$10^{-3}$")
        lit = _x_gutter_ink(take_screenshot, "10^{-3}")
        # Width = number of columns containing any ink in the label row band.
        # Restrict to the bottom 14 rows where the centred label is drawn,
        # away from tick numbers at the top of the gutter.
        tex_cols = np.flatnonzero(tex[-14:, :].any(axis=0))
        lit_cols = np.flatnonzero(lit[-14:, :].any(axis=0))
        assert len(tex_cols) > 0 and len(lit_cols) > 0
        tex_w = tex_cols[-1] - tex_cols[0]
        lit_w = lit_cols[-1] - lit_cols[0]
        assert tex_w < lit_w, (
            f"TeX '$10^{{-3}}$' must render narrower than literal '10^{{-3}}' "
            f"(got {tex_w} vs {lit_w} px)"
        )

    def test_tex_title_renders_pixels(self, interact_page):
        fig, ax = apl.subplots(1, 1, figsize=(400, 300))
        plot = ax.imshow(np.zeros((32, 32), dtype=np.float32))
        plot.set_title(r"$\sigma^2 = \langle x^2 \rangle$")
        page = interact_page(fig)
        page.wait_for_timeout(200)
        n = _title_pixel_count(page)
        assert n > 0, "TeX title must produce visible pixels in titleCanvas"

    def test_greek_and_symbols_render(self, take_screenshot):
        ink = _x_gutter_ink(take_screenshot, r"$\Delta E$ ($\mu$eV) $\times$ $\AA$")
        assert ink.sum() > 0

    def test_plain_label_unaffected(self, take_screenshot):
        """A label with no $ must render through the fast path identically."""
        ink = _x_gutter_ink(take_screenshot, "plain label, no math")
        assert ink.sum() > 0

"""
Playwright regression tests: labels, titles, and tick text must never be
clipped by their canvas bounds.

Strategy: read back each text-bearing canvas with ``getImageData`` and assert
no ink (non-transparent pixel) sits on the canvas's first/last row.  Text
whose glyphs are cut by the canvas edge always leaves ink on the edge row, so
"no ink on the edge" ⇒ "nothing clipped vertically".

The 2D title canvas is fully transparent except for the title, making it the
cleanest probe for both the dynamic title strip and the TeX superscript rise.
"""
from __future__ import annotations

import numpy as np
import pytest

import anyplotlib as apl


def _title_ink_rows(page) -> dict:
    """Return {h, minRow, maxRow} of ink in the 2D titleCanvas (z-index 8)."""
    return page.evaluate("""() => {
        const tc = Array.from(document.querySelectorAll('canvas'))
                        .find(c => c.style.zIndex === '8');
        if (!tc) return null;
        const d = tc.getContext('2d').getImageData(0, 0, tc.width, tc.height).data;
        let minR = 1e9, maxR = -1;
        for (let y = 0; y < tc.height; y++) for (let x = 0; x < tc.width; x++) {
            if (d[(y * tc.width + x) * 4 + 3] > 0) {
                if (y < minR) minR = y;
                if (y > maxR) maxR = y;
            }
        }
        return { h: tc.height, minRow: minR, maxRow: maxR };
    }""")


def _open_imshow_with_title(interact_page, title, fontsize=None):
    fig, ax = apl.subplots(1, 1, figsize=(460, 380))
    q = np.linspace(-2.3, 2.3, 64)
    plot = ax.imshow(np.zeros((64, 64), dtype=np.float32), axes=[q, q], units="nm")
    if fontsize is None:
        plot.set_title(title)
    else:
        plot.set_title(title, fontsize=fontsize)
    page = interact_page(fig)
    page.wait_for_timeout(150)
    return page


class TestTitleNeverClipped:
    @pytest.mark.parametrize("title,fontsize", [
        ("Plain gyp TX", None),                 # default plain — baseline case
        (r"TeX: $|F(q)|^2$ gyp", None),         # default TeX — strip grows for sup
        (r"Large $x^2$ gyp", 16),               # large TeX — strip grows
        ("Plain large gyp", 16),                # large plain
        (r"XL $y_i^2$ gyp", 22),                # extreme, sup + sub + descenders
    ])
    def test_title_ink_within_strip(self, interact_page, title, fontsize):
        page = _open_imshow_with_title(interact_page, title, fontsize)
        r = _title_ink_rows(page)
        assert r is not None and r["maxRow"] >= 0, "title produced no ink"
        assert r["minRow"] > 0, (
            f"title ink touches the top edge (clipped ascender/superscript): {r}"
        )
        assert r["maxRow"] < r["h"] - 1, (
            f"title ink touches the bottom edge (clipped descender): {r}"
        )


class TestColorbarLabelVisible:
    def test_colorbar_label_renders_in_reserved_gutter(self, interact_page):
        """The image must shrink so the colorbar strip + label fit the panel."""
        fig, ax = apl.subplots(1, 1, figsize=(460, 380))
        q = np.linspace(-2.3, 2.3, 64)
        plot = ax.imshow(np.zeros((64, 64), dtype=np.float32), axes=[q, q])
        plot.set_colorbar_visible(True)
        plot.set_colorbar_label(r"counts $\times 10^{3}$")
        page = interact_page(fig)
        page.wait_for_timeout(150)

        res = page.evaluate("""() => {
            // cbCanvas: the only canvas right of the image, width > 16
            const panel = 460;
            for (const c of document.querySelectorAll('canvas')) {
                const left = parseFloat(c.style.left || '0');
                if (c.width > 16 && c.width < 80 && left > 300) {
                    // entire canvas must sit inside the panel width
                    const fits = left + c.width <= panel;
                    // ink in the label gutter (x > 16)
                    const d = c.getContext('2d').getImageData(16, 0, c.width - 16, c.height).data;
                    let ink = 0;
                    for (let i = 3; i < d.length; i += 4) if (d[i] > 0) ink++;
                    return { w: c.width, left, fits, labelInk: ink };
                }
            }
            return null;
        }""")
        assert res is not None, "colorbar canvas not found"
        assert res["fits"], f"colorbar extends past the panel edge: {res}"
        assert res["labelInk"] > 0, f"colorbar label has no visible ink: {res}"

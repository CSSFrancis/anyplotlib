"""Export sources, theme override and panel cropping.

``panelId`` changes only the origin and extent, so a panel export must be the
matching sub-rectangle of the figure export.  ``source`` is ``'view'`` (as
displayed), ``'full'`` (whole extent at panel resolution) or ``'native'``
(one output pixel per data pixel, decorations included).

Two properties are asserted throughout: the export must not disturb the live
figure, and must not write the model — a leaked zoom reset would un-zoom every
shared-axis sibling.  ``'native'`` is impossible from the browser for a tiled
plot, which holds only an overview, and must say so rather than export it.

Assertions use exact sizes, known-LUT probes and the literal theme constants;
no golden baselines are added.
"""
from __future__ import annotations

import numpy as np
import pytest

import anyplotlib as apl
from anyplotlib.tests._png_utils import compare_arrays
from anyplotlib.tests.test_embed._export_utils import (
    closest_color,
    export_array,
    export_via_handle,
    is_nonblank,
)

# _makeTheme's literal palette (figure_esm.js). The figure background is what a
# corner pixel of the export lands on.
LIGHT_BG = (0xF0, 0xF0, 0xF0)
DARK_BG = (0x1E, 0x1E, 0x2E)

IMG = 48          # small enough that native export stays tiny and fast
FIGW, FIGH = 360, 300


def _ramp(n=IMG):
    """A 0..255 horizontal ramp — column j maps to LUT entry j at vmin/vmax."""
    return np.tile(np.arange(256, dtype=np.uint8)[:n], (n, 1))


def _corner(arr):
    """Top-left pixel: always figure background (inside the 8 px grid pad)."""
    return tuple(int(v) for v in arr[2, 2, :3])


# ══════════════════════════════════════════════════════════════════════════════
# source='native' — the decorated panel at one output pixel per data pixel
# ══════════════════════════════════════════════════════════════════════════════

class TestNativeSource:
    def test_native_image_area_is_exactly_the_data_resolution(self, mount_page):
        """The panel is resized so its inner image area is image_width x
        image_height; the output is that plus the gutters it actually has."""
        fig, ax = apl.subplots(1, 1, figsize=(FIGW, FIGH))
        plot = ax.imshow(_ramp(), cmap="gray", vmin=0, vmax=255, tile=False)
        page = mount_page(fig)

        res = export_via_handle(page, {"panelId": plot._id, "source": "native"})
        assert "error" not in res, res.get("error")
        # No physical axes on a bare imshow → no left/bottom gutter; the title
        # strip (PAD_T = 12) is always reserved.
        assert res["width"] == IMG, f"width {res['width']} != {IMG}"
        assert res["height"] == IMG + 12, f"height {res['height']} != {IMG + 12}"

    def test_native_is_independent_of_panel_size(self, mount_page):
        """Two figures of very different on-screen size export the same data at
        the same native resolution."""
        sizes = []
        for figsize in ((200, 180), (700, 600)):
            fig, ax = apl.subplots(1, 1, figsize=figsize)
            plot = ax.imshow(_ramp(), cmap="gray", vmin=0, vmax=255, tile=False)
            page = mount_page(fig)
            res = export_via_handle(page, {"panelId": plot._id, "source": "native"})
            assert "error" not in res, res.get("error")
            sizes.append((res["width"], res["height"]))
        assert sizes[0] == sizes[1], (
            f"native export size followed the panel size: {sizes[0]} vs {sizes[1]}")

    def test_native_columns_match_the_colormap_lut(self, mount_page):
        """Known-LUT probe: with a 0..255 ramp at vmin=0/vmax=255 and one output
        pixel per data pixel, output column j must be LUT[j] exactly."""
        fig, ax = apl.subplots(1, 1, figsize=(FIGW, FIGH))
        plot = ax.imshow(_ramp(), cmap="gray", vmin=0, vmax=255, tile=False)
        lut = plot.to_state_dict()["colormap_data"]
        page = mount_page(fig)

        arr = export_array(page, {"panelId": plot._id, "source": "native"})
        row = arr[-4, :IMG, :3].astype(int)      # inside the image, below the title
        for j in (0, 1, IMG // 2, IMG - 1):
            expect = np.array(lut[j], dtype=int)
            assert np.abs(row[j] - expect).max() <= 1, (
                f"native column {j} is {tuple(row[j])}, LUT[{j}] is {tuple(expect)} "
                "— the native render is not 1:1 with the data")

    def test_native_keeps_axes_and_colorbar(self, mount_page):
        """Decorations are part of a native export: turning the colorbar on must
        widen the output by the reserved gutter, not crop the image."""
        fig, ax = apl.subplots(1, 1, figsize=(FIGW, FIGH))
        plot = ax.imshow(_ramp(), cmap="viridis", vmin=0, vmax=255, tile=False)
        page = mount_page(fig)
        bare = export_via_handle(page, {"panelId": plot._id, "source": "native"})

        fig2, ax2 = apl.subplots(1, 1, figsize=(FIGW, FIGH))
        plot2 = ax2.imshow(_ramp(), cmap="viridis", vmin=0, vmax=255, tile=False)
        plot2.set_colorbar_visible(True)
        page2 = mount_page(fig2)
        withcb = export_via_handle(page2, {"panelId": plot2._id, "source": "native"})

        assert "error" not in bare and "error" not in withcb
        assert withcb["width"] > bare["width"], (
            "colorbar did not add a gutter to the native export "
            f"({bare['width']} -> {withcb['width']})")
        # The image itself is still the full data width.
        assert withcb["height"] == bare["height"]

    def test_native_restores_the_live_panel(self, mount_page):
        """The panel is transiently resized to the data resolution; afterwards
        the on-screen canvas must be back to its original size."""
        fig, ax = apl.subplots(1, 1, figsize=(FIGW, FIGH))
        plot = ax.imshow(_ramp(), cmap="gray", vmin=0, vmax=255, tile=False)
        page = mount_page(fig)

        before = page.evaluate(
            "(pid) => {const c = document.querySelectorAll('canvas');"
            " return [...c].map(x => x.width + 'x' + x.height).join(',');}", plot._id)
        export_via_handle(page, {"panelId": plot._id, "source": "native"})
        after = page.evaluate(
            "(pid) => {const c = document.querySelectorAll('canvas');"
            " return [...c].map(x => x.width + 'x' + x.height).join(',');}", plot._id)
        assert before == after, (
            f"native export left the panel resized:\n  before {before}\n  after  {after}")

    def test_native_on_tiled_plot_points_at_savefig(self, mount_page):
        """Above TILE_THRESHOLD the browser holds only an overview, so a native
        export must refuse loudly rather than export the overview."""
        fig, ax = apl.subplots(1, 1, figsize=(FIGW, FIGH))
        plot = ax.imshow(np.zeros((1200, 1200), dtype=np.float32), cmap="gray")
        assert plot.to_state_dict()["tile_enabled"], (
            "test premise broken: a 1200px image should auto-enable tile mode")
        page = mount_page(fig)

        res = export_via_handle(page, {"panelId": plot._id, "source": "native"})
        assert "error" in res, "native export of a tiled plot unexpectedly succeeded"
        msg = res["error"]
        assert "tile" in msg and "savefig" in msg, (
            f"error should name tiling and point at savefig, got: {msg!r}")

    @pytest.mark.parametrize("kind", ["line", "scatter3d"])
    def test_native_rejected_for_non_image_panels(self, mount_page, kind):
        fig, ax = apl.subplots(1, 1, figsize=(FIGW, FIGH))
        if kind == "line":
            plot = ax.plot(np.arange(10, dtype=float))
        else:
            plot = ax.scatter3d(np.zeros(4), np.zeros(4), np.zeros(4))
        page = mount_page(fig)

        res = export_via_handle(page, {"panelId": plot._id, "source": "native"})
        assert "error" in res
        assert "2-D image panels" in res["error"], res["error"]

    def test_native_without_panel_id_is_rejected(self, mount_page):
        """Panels have different native sizes, so there is no figure-level
        native export."""
        fig, ax = apl.subplots(1, 1, figsize=(FIGW, FIGH))
        ax.imshow(_ramp(), tile=False)
        page = mount_page(fig)
        res = export_via_handle(page, {"source": "native"})
        assert "error" in res and "panelId" in res["error"], res.get("error")


# ══════════════════════════════════════════════════════════════════════════════
# source='full' — the whole data extent, at panel resolution
# ══════════════════════════════════════════════════════════════════════════════

class TestFullSource:
    def test_full_differs_from_zoomed_view_and_matches_unzoomed(self, mount_page):
        fig, ax = apl.subplots(1, 1, figsize=(FIGW, FIGH))
        plot = ax.imshow(_ramp(), cmap="viridis", vmin=0, vmax=255, tile=False)
        page = mount_page(fig)

        unzoomed = export_array(page, {"panelId": plot._id, "source": "view"})
        page.evaluate("(pid) => globalThis.__apl_setZoom(pid, 4.0, 0.25, 0.25)",
                      plot._id)
        zoomed = export_array(page, {"panelId": plot._id, "source": "view"})
        full = export_array(page, {"panelId": plot._id, "source": "full"})

        assert not compare_arrays(zoomed, unzoomed, tol=8, max_diff_frac=0.02)[0], (
            "zooming did not change the 'view' export — test premise broken")
        ok, detail = compare_arrays(full, unzoomed, tol=8, max_diff_frac=0.02)
        assert ok, f"'full' export does not match the unzoomed view: {detail}"

    def test_full_does_not_disturb_the_live_zoom(self, mount_page):
        """The reset is transient and must never reach the model — a leak would
        un-zoom every shared-axis sibling."""
        fig, ax = apl.subplots(1, 1, figsize=(FIGW, FIGH))
        plot = ax.imshow(_ramp(), cmap="viridis", vmin=0, vmax=255, tile=False)
        page = mount_page(fig)
        page.evaluate("(pid) => globalThis.__apl_setZoom(pid, 4.0, 0.25, 0.25)",
                      plot._id)

        trait_before = page.evaluate(
            "(pid) => window._handle.get('panel_' + pid + '_json')", plot._id)

        export_via_handle(page, {"panelId": plot._id, "source": "full"})

        live = page.evaluate(
            "(pid) => JSON.parse(globalThis.__apl_viewStateJson(pid)).zoom", plot._id)
        assert abs(live - 4.0) < 1e-6, (
            f"'full' export left the live panel at zoom={live} instead of restoring 4.0")
        trait_after = page.evaluate(
            "(pid) => window._handle.get('panel_' + pid + '_json')", plot._id)
        assert trait_after == trait_before, (
            "'full' export wrote the panel trait — a transient view reset must "
            "never reach the model, or shared-axis siblings would un-zoom too")

    def test_full_on_tiled_plot_does_not_stretch_the_detail_tile(self, mount_page):
        """A detail tile covers only the pre-reset region.  Left in place while
        zoom is forced to 1, _blit2d would stretch that sub-region over the whole
        fit-rect, so the tile has to be cleared for the duration."""
        rng = np.random.default_rng(3)
        data = (np.add.outer(np.arange(1200), np.arange(1200)) % 255).astype(np.float32)
        data += rng.random((1200, 1200)).astype(np.float32)
        fig, ax = apl.subplots(1, 1, figsize=(FIGW, FIGH))
        plot = ax.imshow(data, cmap="viridis")
        page = mount_page(fig)

        unzoomed = export_array(page, {"panelId": plot._id, "source": "view"})
        page.evaluate("(pid) => globalThis.__apl_setZoom(pid, 6.0, 0.3, 0.3)",
                      plot._id)
        page.wait_for_timeout(250)          # let any detail tile arrive
        full = export_array(page, {"panelId": plot._id, "source": "full"})

        ok, detail = compare_arrays(full, unzoomed, tol=12, max_diff_frac=0.05)
        assert ok, (
            "'full' export of a tiled plot does not match the unzoomed view — "
            f"the detail tile was probably stretched over the image: {detail}")


# ══════════════════════════════════════════════════════════════════════════════
# theme override
# ══════════════════════════════════════════════════════════════════════════════

class TestThemeOverride:
    def test_light_and_dark_backgrounds(self, mount_page):
        fig, ax = apl.subplots(1, 1, figsize=(FIGW, FIGH))
        ax.imshow(_ramp(), cmap="viridis", tile=False)
        page = mount_page(fig)

        light = export_array(page, {"theme": "light"})
        dark = export_array(page, {"theme": "dark"})
        assert _corner(light) == LIGHT_BG, (
            f"light export corner is {_corner(light)}, expected {LIGHT_BG}")
        assert _corner(dark) == DARK_BG, (
            f"dark export corner is {_corner(dark)}, expected {DARK_BG}")

    def test_theme_export_leaves_the_live_figure_untouched(self, mount_page):
        """Two 'current' exports bracketing a light and a dark export must be
        byte-identical.  This is the strongest available assertion that the
        swap-redraw-restore cycle leaves nothing stale behind."""
        fig, ax = apl.subplots(1, 1, figsize=(FIGW, FIGH))
        ax.imshow(_ramp(), cmap="viridis", vmin=0, vmax=255, tile=False)
        page = mount_page(fig)

        before = export_array(page)
        export_array(page, {"theme": "light"})
        export_array(page, {"theme": "dark"})
        after = export_array(page)

        ok, detail = compare_arrays(after, before, tol=0, max_diff_frac=0.0)
        assert ok, f"a themed export changed later 'current' exports: {detail}"

    def test_theme_applies_to_line_and_3d_plot_areas(self, mount_page):
        """The plot-area background (bgPlot) differs from the figure background,
        so a 1-D panel proves the swap reached the per-kind draw functions."""
        fig, axes = apl.subplots(1, 2, figsize=(520, 260))
        axes[0].plot(np.sin(np.arange(20) / 3.0))
        axes[1].imshow(_ramp(), cmap="viridis", tile=False)
        page = mount_page(fig)

        light = export_array(page, {"theme": "light"})
        dark = export_array(page, {"theme": "dark"})
        # bgPlot: #ffffff light, #181825 dark.
        assert closest_color(light, (0xFF, 0xFF, 0xFF), tol=4) > 500, (
            "light export has no white plot area — the 1-D panel kept its theme")
        assert closest_color(dark, (0x18, 0x18, 0x25), tol=4) > 500, (
            "dark export has no dark plot area — the 1-D panel kept its theme")


# ══════════════════════════════════════════════════════════════════════════════
# panelId — a panel export is the cropped figure export
# ══════════════════════════════════════════════════════════════════════════════

class TestPanelCrop:
    def test_panel_export_is_smaller_than_the_figure(self, mount_page):
        fig, axes = apl.subplots(1, 2, figsize=(520, 240))
        p0 = axes[0].imshow(_ramp(), cmap="viridis", tile=False)
        axes[1].imshow(_ramp(), cmap="magma", tile=False)
        page = mount_page(fig)

        whole = export_via_handle(page)
        panel = export_via_handle(page, {"panelId": p0._id})
        assert "error" not in panel, panel.get("error")
        assert panel["width"] < whole["width"], (
            f"panel export {panel['width']} not narrower than figure {whole['width']}")

    def test_panel_export_matches_the_figure_sub_rectangle(self, mount_page):
        """The contract: changing panelId changes only the origin and extent, so
        the result is exactly the corresponding crop of the figure export."""
        fig, axes = apl.subplots(1, 2, figsize=(520, 240))
        p0 = axes[0].imshow(_ramp(), cmap="viridis", vmin=0, vmax=255, tile=False)
        axes[1].imshow(_ramp(), cmap="magma", vmin=0, vmax=255, tile=False)
        page = mount_page(fig)

        whole = export_array(page)
        panel = export_array(page, {"panelId": p0._id})
        box = page.evaluate(
            """(pid) => {
                 const api = window._handle.api;
                 const p = api.panels.get(pid);
                 const el = p.plotWrap || p.plotCanvas.parentElement;
                 const r = el.getBoundingClientRect();
                 const g = (p.cell || el).parentElement.getBoundingClientRect();
                 return {x: Math.round(r.left - g.left), y: Math.round(r.top - g.top)};
               }""", p0._id)
        h, w = panel.shape[:2]
        crop = whole[box["y"]:box["y"] + h, box["x"]:box["x"] + w]
        assert crop.shape[:2] == (h, w), (
            f"crop {crop.shape[:2]} != panel export {(h, w)}")
        ok, detail = compare_arrays(panel, crop, tol=2, max_diff_frac=0.01)
        assert ok, f"panel export is not the figure's sub-rectangle: {detail}"

    def test_unknown_panel_id_is_rejected(self, mount_page):
        fig, ax = apl.subplots(1, 1, figsize=(FIGW, FIGH))
        ax.imshow(_ramp(), tile=False)
        page = mount_page(fig)
        res = export_via_handle(page, {"panelId": "nope"})
        assert "error" in res and "nope" in res["error"], res.get("error")


# ══════════════════════════════════════════════════════════════════════════════
# CSS transform:scale() — the figure shrunk to fit a narrow cell
# ══════════════════════════════════════════════════════════════════════════════

class TestCssScale:
    def test_export_fills_the_canvas_when_the_figure_is_css_scaled(
            self, scaled_mount_page):
        """_applyScale shrinks outerDiv with transform:scale(s) whenever the
        figure is wider than its container — the normal Jupyter case for a wide
        figure.  getBoundingClientRect then reports VISUAL px while the extent
        comes from fig_width, so without un-scaling the panels composite into
        the top-left corner and the rest is flat background."""
        fig, ax = apl.subplots(1, 1, figsize=(700, 320))
        ax.imshow(_ramp(), cmap="viridis", vmin=0, vmax=255, tile=False)
        page = scaled_mount_page(fig)

        s = page.evaluate(
            """() => {
                 const o = document.querySelector('.apl-outer')
                        || document.getElementById('host').firstElementChild;
                 const t = getComputedStyle(o).transform;
                 const m = t && t.match(/matrix\\(\\s*([-\\d.eE+]+)/);
                 return m ? parseFloat(m[1]) : 1;
               }""")
        assert s < 0.99, f"test premise broken: no CSS scale applied (s={s})"

        arr = export_array(page)
        h, w = arr.shape[:2]
        # The bottom-right quadrant must contain real content, not background.
        quad = arr[h // 2:, w // 2:]
        assert is_nonblank(quad), (
            "bottom-right quadrant of the export is flat — the composite was "
            f"squeezed into the top-left corner (CSS scale s={s})")

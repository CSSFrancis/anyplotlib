"""Playwright tests for the PNG export path.

Two surfaces are covered:

1. ``handle.exportPNG({scale?, includeWidgets?})`` — the JS mount-handle method
   that composites the whole figure (all panels, insets, background) onto one
   offscreen canvas at ``devicePixelRatio × scale`` and returns
   ``{dataUrl, width, height}``.  Exercised through the public ``mount()`` entry
   point exactly as an Electron / SpyDE app would call it.

2. The standalone-HTML ``postMessage`` export protocol — a parent page posts
   ``{type:'anyplotlib_export_png', requestId, opts}`` into the figure iframe and
   receives ``{type:'anyplotlib_export_png_result', requestId, dataUrl, ...}``
   back.  This rides the same channel as the live ``state_update`` postMessages.

The GPU case verifies the WebGPU readback hazard is handled: exportPNG forces a
synchronous re-render of active-GPU panels before compositing, so
``drawImage(gpuCanvas)`` reads live pixels instead of a blank buffer.  It is
skipped cleanly when no WebGPU adapter is available (see ``_pw_gpu_browser``).
"""
from __future__ import annotations

import base64
import json
import pathlib
import tempfile

import numpy as np
import pytest

import anyplotlib as apl
from anyplotlib._repr_utils import build_standalone_html
from anyplotlib.embed import esm_path, figure_state
from anyplotlib.tests._png_utils import decode_png

# Above GPU_IMAGE_THRESHOLD (1 << 20 = 1 Mpx): the GPU image path engages in
# auto mode for a 1200² frame (1.44 Mpx).
GPU_IMG_N = 1200


# ---------------------------------------------------------------------------
# mount() page fixture (public embedding contract — no anywidget shim)
# ---------------------------------------------------------------------------

_MOUNT_PAGE = """<!DOCTYPE html>
<html><head><meta charset="utf-8"/>
<style>html,body{margin:0;padding:0;}</style></head>
<body><div id="host"></div>
<script type="module">
const STATE = __STATE__;
const esmSource = __ESM__;
const blobUrl = URL.createObjectURL(new Blob([esmSource], {type: "text/javascript"}));
import(blobUrl).then(mod => {
  window._handle = mod.mount(document.getElementById("host"), STATE, {});
  window._aplReady = true;
}).catch(err => { document.body.textContent = "mount error: " + err; });
</script></body></html>
"""


@pytest.fixture
def mount_page(_pw_browser):
    """Open a figure via the public mount() API; return the live Page."""
    pages, paths = [], []

    def _open(fig, device_scale_factor=None):
        html = (_MOUNT_PAGE
                .replace("__STATE__", json.dumps(figure_state(fig)))
                .replace("__ESM__", json.dumps(esm_path().read_text(encoding="utf-8"))))
        with tempfile.NamedTemporaryFile(
            suffix=".html", mode="w", encoding="utf-8", delete=False
        ) as fh:
            fh.write(html)
            tmp = pathlib.Path(fh.name)
        paths.append(tmp)
        new_page_kwargs = {}
        if device_scale_factor is not None:
            new_page_kwargs["device_scale_factor"] = device_scale_factor
        page = _pw_browser.new_page(**new_page_kwargs)
        pages.append(page)
        page.goto(tmp.as_uri())
        page.wait_for_function("() => window._aplReady === true", timeout=15_000)
        page.evaluate(
            "() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))"
        )
        return page

    yield _open
    for p in pages:
        try:
            p.close()
        except Exception:
            pass
    for f in paths:
        f.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _export_via_handle(page, opts=None):
    """Call window._handle.exportPNG(opts) and return {dataUrl, width, height}."""
    return page.evaluate(
        """(opts) => window._handle.exportPNG(opts || {})
                .then(r => ({dataUrl: r.dataUrl, width: r.width, height: r.height}))
                .catch(e => ({error: String(e && e.message || e)}))""",
        opts or {},
    )


def _decode_data_url(data_url: str) -> np.ndarray:
    assert data_url.startswith("data:image/png;base64,"), (
        f"unexpected data URL prefix: {data_url[:40]!r}"
    )
    raw = base64.b64decode(data_url.split(",", 1)[1])
    return decode_png(raw)


def _is_nonblank(arr: np.ndarray) -> bool:
    """True when the image is not a single flat colour (has real content)."""
    rgb = arr[..., :3].reshape(-1, 3)
    return int(np.unique(rgb, axis=0).shape[0]) > 1


def _closest_color(arr: np.ndarray, rgb) -> int:
    """Number of pixels whose RGB is within tol of `rgb` (per-channel <= 12)."""
    d = np.abs(arr[..., :3].astype(np.int32) - np.asarray(rgb, dtype=np.int32))
    return int(((d <= 12).all(axis=-1)).sum())


# ---------------------------------------------------------------------------
# 1. Basic single-panel export
# ---------------------------------------------------------------------------

class TestExportBasic:
    def test_export_nonblank_expected_size(self, mount_page):
        fig, ax = apl.subplots(1, 1, figsize=(400, 300))
        rng = np.random.default_rng(0)
        ax.imshow(rng.random((32, 32)).astype(np.float32), cmap="viridis")
        page = mount_page(fig)

        res = _export_via_handle(page)
        assert "error" not in res, res.get("error")
        arr = _decode_data_url(res["dataUrl"])

        # devicePricelRatio in headless Chromium is 1 → output == figure px.
        # Figure background = fig_width/height + 8 px grid padding each side.
        dpr = page.evaluate("() => window.devicePixelRatio || 1")
        exp_w = round((400 + 16) * dpr)
        exp_h = round((300 + 16) * dpr)
        assert res["width"] == exp_w and res["height"] == exp_h, (
            f"size {res['width']}x{res['height']} != expected {exp_w}x{exp_h}"
        )
        assert arr.shape[1] == res["width"] and arr.shape[0] == res["height"]
        assert _is_nonblank(arr), "exported image is a single flat colour"

    def test_export_known_lut_pixel(self, mount_page):
        """A constant image at vmax must export as the colormap's high endpoint
        colour (LUT[255]).  Proves the actual rendered pixels are captured, not
        an empty/placeholder canvas."""
        fig, ax = apl.subplots(1, 1, figsize=(300, 220))
        plot = ax.imshow(np.full((32, 32), 1.0, dtype=np.float32),
                         cmap="viridis", vmin=0.0, vmax=1.0)
        # The high LUT endpoint the constant image maps to.
        hi = plot.to_state_dict()["colormap_data"][255]

        page = mount_page(fig)
        res = _export_via_handle(page)
        assert "error" not in res, res.get("error")
        arr = _decode_data_url(res["dataUrl"])

        # The fit-rect (letterboxed image) must be filled with the endpoint
        # colour — a large fraction of the frame, and specifically the centre.
        cy, cx = arr.shape[0] // 2, arr.shape[1] // 2
        centre = arr[cy, cx, :3].tolist()
        d = max(abs(centre[i] - hi[i]) for i in range(3))
        assert d <= 12, (
            f"centre pixel {centre} != expected viridis endpoint {hi} (dmax={d})"
        )
        # And the colour must cover a large area (the whole image region).
        assert _closest_color(arr, hi) > 0.2 * arr.shape[0] * arr.shape[1], (
            "endpoint colour does not fill the image area"
        )

    def test_export_scale_multiplies_size(self, mount_page):
        fig, ax = apl.subplots(1, 1, figsize=(200, 160))
        ax.imshow(np.random.default_rng(1).random((16, 16)).astype(np.float32))
        page = mount_page(fig)

        base = _export_via_handle(page, {"scale": 1})
        big = _export_via_handle(page, {"scale": 2})
        assert "error" not in base and "error" not in big
        assert big["width"] == base["width"] * 2
        assert big["height"] == base["height"] * 2

    def test_widgets_excluded_by_default(self, mount_page):
        """A drawn rectangle widget must NOT appear unless includeWidgets=True.

        The widget's red/accent stroke lives on the overlayCanvas (z-index 5),
        which the default composite skips.
        """
        fig, ax = apl.subplots(1, 1, figsize=(360, 300))
        plot = ax.imshow(np.zeros((32, 32), dtype=np.float32),
                         cmap="gray", vmin=0.0, vmax=1.0)
        plot.add_widget("rectangle", x=6.0, y=6.0, w=18.0, h=18.0)
        page = mount_page(fig)
        # let the overlay draw the widget
        page.evaluate(
            "() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))"
        )

        without = _decode_data_url(_export_via_handle(page, {})["dataUrl"])
        withw = _decode_data_url(
            _export_via_handle(page, {"includeWidgets": True})["dataUrl"])

        # The two exports must be the SAME size, and differ (widget adds ink).
        assert without.shape == withw.shape
        diff = np.abs(without.astype(np.int32) - withw.astype(np.int32)).sum()
        assert diff > 0, (
            "includeWidgets=True produced an identical image — overlay not drawn"
        )

    def test_widget_handles_not_exported(self, mount_page):
        """Panel-overlay widget grab-handle dots are edit-mode chrome (like the
        figure-marker handles covered by test_edit_chrome_handles_not_exported)
        and must never be baked into an exported PNG, even with
        includeWidgets=True and show_handles=True (SpyDE's report edit mode
        uses show_handles=True on circle/rect/arrow widgets).

        Compares an includeWidgets export of a scene with show_handles=True
        widgets against the identical scene with show_handles=False — these
        must be pixel-identical: the widget BODY (circle outline, rect
        outline, arrow shaft/head) must still export, only the white
        handle-node dots are suppressed.
        """
        def _build(show_handles):
            fig, ax = apl.subplots(1, 1, figsize=(360, 300))
            plot = ax.imshow(np.zeros((32, 32), dtype=np.float32),
                             cmap="gray", vmin=0.0, vmax=1.0)
            plot.add_widget("circle", cx=8.0, cy=8.0, r=5.0,
                            color="#ff0000", show_handles=show_handles)
            plot.add_widget("rectangle", x=18.0, y=4.0, w=10.0, h=8.0,
                            color="#00ff00", show_handles=show_handles)
            plot.add_widget("arrow", x=4.0, y=24.0, u=10.0, v=5.0,
                            color="#0000ff", show_handles=show_handles)
            return fig

        page_handles = mount_page(_build(True))
        page_no_handles = mount_page(_build(False))
        for pg in (page_handles, page_no_handles):
            pg.evaluate(
                "() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))"
            )

        arr_handles = _decode_data_url(
            _export_via_handle(page_handles, {"includeWidgets": True})["dataUrl"])
        arr_no_handles = _decode_data_url(
            _export_via_handle(page_no_handles, {"includeWidgets": True})["dataUrl"])

        assert arr_handles.shape == arr_no_handles.shape
        # Widget body ink (coloured stroke) must be present in both — proves
        # the export isn't just blank / widgets-excluded.
        assert _is_nonblank(arr_handles) and _is_nonblank(arr_no_handles)
        diff = np.abs(arr_handles.astype(np.int32) - arr_no_handles.astype(np.int32)).sum()
        assert diff == 0, (
            "show_handles=True export differs from show_handles=False — "
            f"widget handle dots leaked into the exported image (diff={diff})"
        )

    def test_widget_body_still_exported_with_handles_suppressed(self, mount_page):
        """Sanity check for the handle-suppression redraw: the widget BODY
        (not just the handle dots) must still appear in the includeWidgets
        export — i.e. the fix must not have blanked the overlay entirely.
        (Handle-dot suppression itself is proven by the pixel-identical diff
        in test_widget_handles_not_exported above; a global/local white-pixel
        count is not a reliable signal here since the default light theme's
        figure background is itself near white.)"""
        fig, ax = apl.subplots(1, 1, figsize=(360, 300))
        plot = ax.imshow(np.zeros((32, 32), dtype=np.float32),
                         cmap="gray", vmin=0.0, vmax=1.0)
        plot.add_widget("rectangle", x=6.0, y=6.0, w=18.0, h=18.0,
                        color="#ff0000", show_handles=True)
        page = mount_page(fig)
        page.evaluate(
            "() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))"
        )
        res = _export_via_handle(page, {"includeWidgets": True})
        assert "error" not in res, res.get("error")
        arr = _decode_data_url(res["dataUrl"])
        assert _closest_color(arr, (255, 0, 0)) > 10, (
            "widget body stroke missing from includeWidgets export — "
            "handle-suppression redraw dropped the widget entirely"
        )

        # Confirm the on-screen overlay canvas itself is untouched by the
        # export redraw (no flicker): edit_chrome + a selected panel draws
        # handles live, and that must be unaffected by having just exported.
        fig2, ax2 = apl.subplots(1, 1, figsize=(360, 300))
        plot2 = ax2.imshow(np.zeros((32, 32), dtype=np.float32),
                          cmap="gray", vmin=0.0, vmax=1.0)
        plot2.add_widget("rectangle", x=6.0, y=6.0, w=18.0, h=18.0,
                         color="#ff0000", show_handles=True)
        fig2.edit_chrome = True
        fig2.selected_panel = list(fig2._plots_map)[0]
        page2 = mount_page(fig2)
        page2.evaluate(
            "() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))"
        )
        before = page2.evaluate(
            """(pid) => {
                const p = window._handle.api.panels.get(pid);
                return p.overlayCanvas.toDataURL();
            }""",
            list(fig2._plots_map)[0],
        )
        page2.evaluate(
            "() => window._handle.exportPNG({includeWidgets: true})"
        )
        after = page2.evaluate(
            """(pid) => {
                const p = window._handle.api.panels.get(pid);
                return p.overlayCanvas.toDataURL();
            }""",
            list(fig2._plots_map)[0],
        )
        assert before == after, (
            "exportPNG mutated the live on-screen overlayCanvas — "
            "handle-suppression redraw must use a scratch canvas, not the "
            "live one"
        )


# ---------------------------------------------------------------------------
# 1c. Figure-level annotation layer export (always composited; edit chrome is
#     never exported).
# ---------------------------------------------------------------------------

class TestExportFigureMarkers:
    RED = (255, 0, 0)

    def test_figure_marker_always_exported(self, mount_page):
        """A figure-level marker is CONTENT — it must appear in the default
        export (no includeWidgets flag needed)."""
        fig, ax = apl.subplots(1, 1, figsize=(360, 300))
        ax.imshow(np.zeros((32, 32), dtype=np.float32),
                  cmap="gray", vmin=0.0, vmax=1.0)
        fig.set_figure_markers([
            {"kind": "rect", "x": 0.5, "y": 0.5, "w": 0.4, "h": 0.4,
             "color": "#ff0000", "linewidth": 4},
        ])
        page = mount_page(fig)
        page.evaluate(
            "() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))"
        )
        arr = _decode_data_url(_export_via_handle(page, {})["dataUrl"])
        assert _closest_color(arr, self.RED) > 20, (
            "figure-level red rect not present in the default export"
        )

    def test_edit_chrome_handles_not_exported(self, mount_page):
        """With edit_chrome on the on-screen marker draws grab-handle dots, but
        the export must be identical to the non-edit export (handles suppressed;
        hover/selection outlines are DOM styles, never on a canvas)."""
        def _build(edit):
            fig, ax = apl.subplots(1, 1, figsize=(360, 300))
            ax.imshow(np.zeros((32, 32), dtype=np.float32),
                      cmap="gray", vmin=0.0, vmax=1.0)
            fig.set_figure_markers([
                {"kind": "circle", "x": 0.5, "y": 0.5, "r": 0.25,
                 "color": "#ff0000", "linewidth": 3, "id": "c1"},
            ])
            fig.edit_chrome = edit
            fig.selected_panel = list(fig._plots_map)[0] if edit else ""
            return fig

        page_off = mount_page(_build(False))
        page_on = mount_page(_build(True))
        for pg in (page_off, page_on):
            pg.evaluate(
                "() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))"
            )
        arr_off = _decode_data_url(_export_via_handle(page_off, {})["dataUrl"])
        arr_on = _decode_data_url(_export_via_handle(page_on, {})["dataUrl"])

        assert arr_off.shape == arr_on.shape
        # Handle dots are white with a coloured ring — if they were exported the
        # red count / white-dot pixels would differ.  Require pixel-identical.
        diff = np.abs(arr_off.astype(np.int32) - arr_on.astype(np.int32)).sum()
        assert diff == 0, (
            "edit-mode export differs from non-edit — handles/outlines leaked "
            f"into the exported image (diff={diff})"
        )

    def test_figMarkerCanvas_exposed_on_handle(self, mount_page):
        """The render API exposes figMarkerCanvas + _drawFigureMarkers (SpyDE
        and tests reach the marker layer through these)."""
        fig, ax = apl.subplots(1, 1, figsize=(200, 160))
        ax.imshow(np.zeros((8, 8), dtype=np.float32))
        page = mount_page(fig)
        has = page.evaluate(
            """() => ({
                canvas: !!window._handle.api.figMarkerCanvas,
                draw: typeof window._handle.api._drawFigureMarkers === 'function',
            })"""
        )
        assert has["canvas"] and has["draw"]


# ---------------------------------------------------------------------------
# 1b. Inset title bar export (exportPNG must draw the DOM title text)
# ---------------------------------------------------------------------------

def _inset_titlebar_rect(page, plot_id):
    """CSS-px rect of an inset's titleBar, relative to the figure origin.

    calloutCanvas shares the same 8px-padding offset from outerDiv as
    gridDiv/insetsContainer (see figure_esm.js), so its rect is a stable,
    API-exposed proxy for the figure content origin exportPNG measures from
    (mirrors _inset_dom_rect in test_inset_callout.py).
    """
    return page.evaluate(
        """(pid) => {
            const p = window._handle.api.panels.get(pid);
            const r = p.titleBar.getBoundingClientRect();
            const base = window._handle.api.calloutCanvas.getBoundingClientRect();
            return {left: r.left - base.left, top: r.top - base.top,
                    width: r.width, height: r.height};
        }""",
        plot_id,
    )


class TestExportInsetTitle:
    def test_inset_title_drawn_in_titlebar_band(self, mount_page):
        """A non-empty inset title must leave title-text-coloured ink in the
        titlebar row band; an otherwise-identical inset with an empty title
        must NOT — ruling out a false positive from the titlebar's own flat
        fill colour (which both figures share) rather than actual text."""
        dpr = None
        GRID_PAD = 8

        def _titlebar_band(fig_factory, title):
            fig, ax = fig_factory()
            ax.imshow(np.zeros((32, 32), dtype=np.float32), cmap="gray",
                     vmin=0.0, vmax=1.0)
            inset = fig.add_inset(0.35, 0.35, corner="top-right", title=title)
            plot = inset.imshow(np.zeros((16, 16), dtype=np.float32),
                                cmap="gray", vmin=0.0, vmax=1.0)
            page = mount_page(fig)
            rect = _inset_titlebar_rect(page, plot._id)
            res = _export_via_handle(page)
            assert "error" not in res, res.get("error")
            arr = _decode_data_url(res["dataUrl"])
            dpr_ = page.evaluate("() => window.devicePixelRatio || 1")
            y0 = max(0, round((rect["top"] + GRID_PAD) * dpr_))
            y1 = min(arr.shape[0], round((rect["top"] + rect["height"] + GRID_PAD) * dpr_))
            x0 = max(0, round((rect["left"] + GRID_PAD) * dpr_))
            x1 = min(arr.shape[1], round((rect["left"] + rect["width"] + GRID_PAD) * dpr_))
            return arr[y0:y1, x0:x1, :3], dpr_

        def _make_fig():
            return apl.subplots(1, 1, figsize=(400, 300))

        band_titled, dpr = _titlebar_band(_make_fig, "Zoom View")
        band_empty, _ = _titlebar_band(_make_fig, "")
        assert band_titled.size > 0 and band_empty.size > 0, (
            f"empty titlebar band(s): titled={band_titled.shape} "
            f"empty={band_empty.shape}"
        )
        assert band_titled.shape == band_empty.shape, (
            "titlebar bands differ in size between the two figures — "
            f"titled={band_titled.shape} empty={band_empty.shape}"
        )

        # Both bands share the identical titlebar chrome (same theme, corner,
        # size — including its border-bottom row), so any per-pixel
        # difference between the two must be the drawn title TEXT.
        diff = np.abs(band_titled.astype(np.int32) - band_empty.astype(np.int32))
        changed_px = int((diff.sum(axis=-1) > 20).sum())
        assert changed_px > 0, (
            "titled and empty-title exports are pixel-identical in the "
            "titlebar band — exportPNG is not drawing the inset title text"
        )
        # The border-bottom row (~1 CSS px) is the only chrome difference a
        # mis-measured band could pick up; text ink should account for far
        # more than one scaled row's worth of pixels.
        assert changed_px > band_titled.shape[1] * dpr, (
            f"only {changed_px} px differ — looks like border noise, not text "
            f"(band width {band_titled.shape[1]})"
        )


# ---------------------------------------------------------------------------
# 2. Multi-panel export
# ---------------------------------------------------------------------------

class TestExportMultiPanel:
    def test_two_panels_both_present(self, mount_page):
        """subplots(1, 2) with two distinct constant-colour images must export
        both panels, each in its own half of the composite."""
        fig, axes = apl.subplots(1, 2, figsize=(240, 200))
        # Left panel: low endpoint; right panel: high endpoint. Different cmaps
        # so the two halves are unmistakably distinct colours.
        pl = axes[0].imshow(np.full((24, 24), 0.0, dtype=np.float32),
                            cmap="viridis", vmin=0.0, vmax=1.0)
        pr = axes[1].imshow(np.full((24, 24), 1.0, dtype=np.float32),
                            cmap="magma", vmin=0.0, vmax=1.0)
        left_lo = pl.to_state_dict()["colormap_data"][0]     # viridis dark blue
        right_hi = pr.to_state_dict()["colormap_data"][255]  # magma pale yellow

        page = mount_page(fig)
        res = _export_via_handle(page)
        assert "error" not in res, res.get("error")
        arr = _decode_data_url(res["dataUrl"])

        H, Wtot = arr.shape[0], arr.shape[1]
        left_half = arr[:, : Wtot // 2, :3]
        right_half = arr[:, Wtot // 2:, :3]

        # Left panel colour lives in the LEFT half, right panel colour in the
        # RIGHT half — proves both panels rendered AND are positioned correctly.
        assert _closest_color(left_half, left_lo) > 0.05 * left_half.shape[0] * left_half.shape[1], (
            "left panel colour missing from left half"
        )
        assert _closest_color(right_half, right_hi) > 0.05 * right_half.shape[0] * right_half.shape[1], (
            "right panel colour missing from right half"
        )
        # And they must NOT be swapped (right colour should be rare on the left).
        assert _closest_color(left_half, right_hi) < _closest_color(right_half, right_hi)

    def test_fractional_scale_no_seam_between_panels(self, mount_page):
        """exportPNG at a fractional effective scale (devicePixelRatio ×
        opts.scale) on touching (wspace=0) panels must not leave a
        background-coloured seam between their interior content areas at
        the shared boundary.

        Reproduced with device_scale_factor=1.5 (a real fractional-DPR
        display, e.g. 150% Windows scaling) and a panel width whose CSS
        boundary lands exactly on a half-pixel (250px figure → two 125px
        panels stretched by DPR 1.5 → boundary at 187.5 output px): with
        unrounded per-element dx/dw, the two neighbouring canvases (each
        independently measuring its own getBoundingClientRect() * outScale)
        can round their shared edge to different output pixels, opening a
        1px background gap exactly at the seam. Confirmed to fail before
        the _drawEl edge-rounding fix and pass after.
        """
        fig, axes = apl.subplots(1, 2, figsize=(250, 200))
        fig.subplots_adjust(wspace=0)
        # Full-bleed constant-colour panels (no axes/title/colorbar → each
        # plotCanvas fills its entire grid cell, so the panels' image content
        # touches directly at the shared boundary with no letterboxing).
        axes[0].imshow(np.full((24, 24), 0.0, dtype=np.float32),
                       cmap="viridis", vmin=0.0, vmax=1.0)
        axes[1].imshow(np.full((24, 24), 1.0, dtype=np.float32),
                       cmap="viridis", vmin=0.0, vmax=1.0)

        page = mount_page(fig, device_scale_factor=1.5)
        scale = 1.0
        info = page.evaluate(
            """(sc) => {
                const ps = [...window._handle.api.panels.values()]
                    .filter(p => !p.isInset)
                    .sort((a, b) => a.plotCanvas.getBoundingClientRect().left
                                  - b.plotCanvas.getBoundingClientRect().left);
                const outScale = (window.devicePixelRatio || 1) * sc;
                const l = ps[0].plotCanvas.getBoundingClientRect();
                const r = ps[1].plotCanvas.getBoundingClientRect();
                return {
                    leftRight: l.right * outScale,
                    rightLeft: r.left  * outScale,
                    top: Math.max(l.top, r.top) * outScale,
                    bottom: Math.min(l.bottom, r.bottom) * outScale,
                    dpr: window.devicePixelRatio,
                };
            }""",
            scale,
        )
        res = _export_via_handle(page, {"scale": scale})
        assert "error" not in res, res.get("error")
        arr = _decode_data_url(res["dataUrl"])

        boundary = round(info["leftRight"])
        assert abs(info["leftRight"] - info["rightLeft"]) < 1.0, (
            "test precondition failed: panels aren't actually touching "
            f"({info})"
        )
        y0 = max(0, round(info["top"]) + 2)
        y1 = min(arr.shape[0], round(info["bottom"]) - 2)
        assert y1 > y0, f"degenerate row range: {info}"

        bg_rgb = page.evaluate(
            """() => {
                const el = [...document.querySelectorAll('div')]
                    .find(d => getComputedStyle(d).display === 'grid');
                const m = getComputedStyle(el).backgroundColor
                    .match(/(\\d+),\\s*(\\d+),\\s*(\\d+)/);
                return m ? [+m[1], +m[2], +m[3]] : [240, 240, 240];
            }"""
        )
        bg = np.array(bg_rgb)

        # A window of a few columns straddling the rounded boundary must
        # contain no background-coloured pixel (a gap) — the two panels'
        # distinct colours must butt together directly.
        band = arr[y0:y1, max(0, boundary - 2):boundary + 3, :3]
        is_bg = np.abs(band.astype(np.int32) - bg).sum(axis=-1) < 20
        assert not is_bg.any(), (
            f"background-coloured pixel(s) at the panel boundary "
            f"(x≈{boundary}, dpr={info['dpr']}) — seam between touching "
            f"panels at scale={scale}: band={band.tolist()}"
        )


# ---------------------------------------------------------------------------
# 3. Iframe postMessage round-trip (standalone HTML template)
# ---------------------------------------------------------------------------

_PARENT_PAGE = """<!DOCTYPE html>
<html><head><meta charset="utf-8"/><style>html,body{margin:0;padding:0;}</style></head>
<body>
<iframe id="fig" srcdoc="__SRCDOC__" width="360" height="280"
        style="border:none;"></iframe>
<script>
window._exportResult = null;
window.addEventListener('message', (e) => {
  if (e.data && e.data.type === 'anyplotlib_export_png_result') {
    window._exportResult = e.data;
  }
});
window._requestExport = function(opts) {
  window._exportResult = null;
  const ifr = document.getElementById('fig');
  ifr.contentWindow.postMessage(
    {type: 'anyplotlib_export_png', requestId: 'rq1', opts: opts || {}}, '*');
};
</script>
</body></html>
"""


class TestExportIframeRoundTrip:
    def test_postmessage_export_returns_png(self, _pw_browser):
        fig, ax = apl.subplots(1, 1, figsize=(320, 240))
        ax.imshow(np.random.default_rng(2).random((32, 32)).astype(np.float32),
                  cmap="viridis")

        srcdoc = build_standalone_html(fig, resizable=False)
        # Escape for the srcdoc attribute (mirrors repr_html_iframe / SpyDE).
        from html import escape
        parent = _PARENT_PAGE.replace("__SRCDOC__", escape(srcdoc, quote=True))

        with tempfile.NamedTemporaryFile(
            suffix=".html", mode="w", encoding="utf-8", delete=False
        ) as fh:
            fh.write(parent)
            tmp = pathlib.Path(fh.name)

        page = _pw_browser.new_page()
        try:
            page.goto(tmp.as_uri())
            # Wait until the figure inside the iframe has rendered (the export
            # API is set on the render() return).  Give the module import +
            # first paint a couple of frames.
            page.wait_for_timeout(500)
            page.evaluate("() => window._requestExport({})")
            page.wait_for_function(
                "() => window._exportResult !== null", timeout=15_000)
            result = page.evaluate("() => window._exportResult")
        finally:
            page.close()
            tmp.unlink(missing_ok=True)

        assert result.get("requestId") == "rq1"
        assert not result.get("error"), f"export error: {result.get('error')}"
        assert result.get("dataUrl", "").startswith("data:image/png;base64,")
        arr = _decode_data_url(result["dataUrl"])
        assert result["width"] > 0 and result["height"] > 0
        assert arr.shape[1] == result["width"] and arr.shape[0] == result["height"]
        assert _is_nonblank(arr), "iframe-exported PNG is a single flat colour"


# ---------------------------------------------------------------------------
# 4. GPU (WebGPU readback) export
# ---------------------------------------------------------------------------

@pytest.fixture
def gpu_mount_page(_pw_gpu_browser):
    """Open a figure via mount() in the WebGPU-capable browser.

    Returns ``open(fig, expect_gpu=False) -> page``.  With ``expect_gpu=True``
    it waits until every 2-D image panel reports the GPU path active (the async
    device init + activation redraw landed), so a subsequent exportPNG is
    guaranteed to composite the WebGPU rendering, not a first-frame Canvas2D
    fallback.  Skipped when no adapter is available (via ``_pw_gpu_browser``).
    """
    pages, paths = [], []

    def _open(fig, expect_gpu=False):
        html = (_MOUNT_PAGE
                .replace("__STATE__", json.dumps(figure_state(fig)))
                .replace("__ESM__", json.dumps(esm_path().read_text(encoding="utf-8"))))
        with tempfile.NamedTemporaryFile(
            suffix=".html", mode="w", encoding="utf-8", delete=False
        ) as fh:
            fh.write(html)
            tmp = pathlib.Path(fh.name)
        paths.append(tmp)
        page = _pw_gpu_browser.new_page()
        pages.append(page)
        page.goto(tmp.as_uri())
        page.wait_for_function("() => window._aplReady === true", timeout=15_000)
        page.evaluate(
            "() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))"
        )
        if expect_gpu:
            page.wait_for_function(
                """() => {
                    const d = globalThis.__apl_gpu2d || {};
                    const v = Object.values(d);
                    return v.length > 0 && v.every(x => x.active);
                }""",
                timeout=20_000,
            )
        return page

    yield _open
    for p in pages:
        try:
            p.close()
        except Exception:
            pass
    for f in paths:
        f.unlink(missing_ok=True)


def _gpu_asym_image(n=GPU_IMG_N):
    """Gradient + distinct corner blocks: content the composite must capture."""
    yy, xx = np.mgrid[0:n, 0:n].astype(np.float32)
    img = (xx / n) * 0.3 + (yy / n) * 0.3
    img[(yy < n // 3) & (xx < n // 3)] = 1.0
    img[(yy > 2 * n // 3) & (xx > 2 * n // 3)] = 0.8
    return img


def _scatter3d_fig(gpu):
    """A 3-D scatter of pure-red points (the point fragment shader returns the
    per-point colour unshaded, so exported point pixels are exactly red)."""
    fig, ax = apl.subplots(1, 1, figsize=(320, 320))
    rng = np.random.default_rng(7)
    pts = rng.uniform(-1, 1, size=(3000, 3))
    v = ax.scatter3d(pts[:, 0], pts[:, 1], pts[:, 2], bounds=((-1, 1),) * 3,
                     gpu=gpu,
                     colors=np.tile([255, 0, 0], (3000, 1)).astype(np.uint8),
                     point_size=5)
    v.set_axis_off()
    return fig


_WAIT_3D_GPU_ACTIVE = """() => {
    const api = window._handle && window._handle.api;
    if (!api || !api.panels) return false;
    for (const p of api.panels.values())
        if (p.kind === '3d')
            return p._gpu === 'active' && !!p._gpuObj && p._gpuActiveNow;
    return false;
}"""


class TestExportGpu3d:
    """3-D WebGPU panels in exportPNG — the safeguard that re-renders the 3-D
    pass in-task before drawImage(gpuCanvas).  Without it a scatter3d/voxels
    panel exports as an empty background rectangle (the WebGPU drawing buffer
    is cleared after the frame that rendered it is presented)."""

    def test_scatter3d_gpu_export_nonblank(self, gpu_mount_page):
        fig = _scatter3d_fig(gpu="always")
        page = gpu_mount_page(fig)
        page.wait_for_function(_WAIT_3D_GPU_ACTIVE, timeout=20_000)
        # Settle a couple of frames so the export runs in a LATER task than
        # the activation render — the exact condition under which the drawing
        # buffer would read back blank without the in-task re-render.
        page.evaluate(
            "() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))"
        )

        res = _export_via_handle(page)
        assert "error" not in res, res.get("error")
        arr = _decode_data_url(res["dataUrl"])
        assert _is_nonblank(arr), "3-D GPU export is a single flat colour"
        red = _closest_color(arr, (255, 0, 0))
        assert red > 200, (
            f"only {red} red point pixels in the 3-D GPU export — "
            "gpuCanvas read back blank (missing in-task draw3d re-render?)"
        )

    def test_scatter3d_canvas_fallback_export_nonblank(self, mount_page):
        """No-regression guard: the Canvas2D 3-D path (gpu=False, and CI
        runners without an adapter) draws points on plotCanvas, which the
        composite has always captured."""
        fig = _scatter3d_fig(gpu=False)
        page = mount_page(fig)
        res = _export_via_handle(page)
        assert "error" not in res, res.get("error")
        arr = _decode_data_url(res["dataUrl"])
        assert _is_nonblank(arr), "3-D canvas export is a single flat colour"
        # Canvas path dims far-side points (alpha), so count "reddish" ink
        # rather than exact red.
        rgb = arr[..., :3].astype(np.int32)
        reddish = int(((rgb[..., 0] > 150)
                       & (rgb[..., 0] - rgb[..., 1] > 60)
                       & (rgb[..., 0] - rgb[..., 2] > 60)).sum())
        assert reddish > 200, (
            f"only {reddish} reddish pixels in the 3-D canvas export"
        )


class TestExportGpu:
    def test_gpu_export_nonblank(self, gpu_mount_page):
        """A large scalar image engaging the WebGPU path must export non-blank.

        This is the readback test: exportPNG forces a synchronous re-render of
        the active-GPU panel before drawImage(gpuCanvas), so the GPU raster is
        captured instead of a blank drawing buffer.
        """
        fig, ax = apl.subplots(1, 1, figsize=(400, 300))
        plot = ax.imshow(_gpu_asym_image(), cmap="viridis",
                         vmin=0.0, vmax=1.0, gpu=True)
        hi = plot.to_state_dict()["colormap_data"][255]  # value-1.0 endpoint

        page = gpu_mount_page(fig, expect_gpu=True)

        # Confirm the GPU path is actually the one painting this frame.
        diag = page.evaluate("() => globalThis.__apl_gpu2d || {}")
        assert diag and all(d.get("active") for d in diag.values()), (
            f"GPU path not active: {diag}"
        )

        res = _export_via_handle(page)
        assert "error" not in res, res.get("error")
        arr = _decode_data_url(res["dataUrl"])
        assert _is_nonblank(arr), (
            "GPU export is a single flat colour — WebGPU readback returned blank"
        )
        # The bright top-left block (value 1.0) → viridis endpoint colour must
        # be present, proving the GPU raster (not just decorations) was drawn.
        assert _closest_color(arr, hi) > 500, (
            "GPU-rendered image content missing from export (blank gpuCanvas?)"
        )

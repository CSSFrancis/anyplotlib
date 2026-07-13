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

    def _open(fig):
        html = (_MOUNT_PAGE
                .replace("__STATE__", json.dumps(figure_state(fig)))
                .replace("__ESM__", json.dumps(esm_path().read_text(encoding="utf-8"))))
        with tempfile.NamedTemporaryFile(
            suffix=".html", mode="w", encoding="utf-8", delete=False
        ) as fh:
            fh.write(html)
            tmp = pathlib.Path(fh.name)
        paths.append(tmp)
        page = _pw_browser.new_page()
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

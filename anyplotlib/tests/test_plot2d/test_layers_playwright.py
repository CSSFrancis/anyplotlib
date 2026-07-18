"""Browser (Playwright) tests for multi-image LAYERS.

Exercised through the public ``mount()`` entry point exactly as an Electron /
SpyDE app would.  We assert on real composited pixels via ``exportPNG`` (which
captures the plotCanvas where layers draw):

* two constant-value images with distinct colormaps + ``alpha=0.5`` → the blended
  colour ``base*(1-a) + layer*a`` (Canvas2D source-over), computed from the LUTs;
* ``visible=False`` removes the layer's contribution;
* ``layer.set_data`` swaps the layer pixels;
* a large image on the WebGPU base path with a Canvas2D layer over it (skips
  cleanly without a WebGPU adapter);
* ``exportPNG`` includes the layer contribution.

Bundled Chromium (the default ``_pw_browser``) has NO WebGPU, so the base image
renders on Canvas2D there; the GPU-base case uses ``_pw_gpu_browser``.
"""
from __future__ import annotations

import base64
import json
import pathlib
import tempfile

import numpy as np
import pytest

import anyplotlib as apl
from anyplotlib.embed import esm_path, figure_state
from anyplotlib.tests._png_utils import decode_png


_MOUNT_PAGE = """<!DOCTYPE html>
<html><head><meta charset="utf-8"/>
<style>html,body{margin:0;padding:0;}</style></head>
<body><div id="host"></div>
<script type="module">
const STATE = __STATE__;
const esmSource = __ESM__;
const blobUrl = URL.createObjectURL(new Blob([esmSource], {type: "text/javascript"}));
import(blobUrl).then(mod => {
  window._mod = mod;
  window._handle = mod.mount(document.getElementById("host"), STATE, {});
  window._aplReady = true;
}).catch(err => { document.body.textContent = "mount error: " + err; });
</script></body></html>
"""


def _make_page(browser, fig):
    html = (_MOUNT_PAGE
            .replace("__STATE__", json.dumps(figure_state(fig)))
            .replace("__ESM__", json.dumps(esm_path().read_text(encoding="utf-8"))))
    with tempfile.NamedTemporaryFile(
        suffix=".html", mode="w", encoding="utf-8", delete=False
    ) as fh:
        fh.write(html)
        tmp = pathlib.Path(fh.name)
    page = browser.new_page()
    page.goto(tmp.as_uri())
    page.wait_for_function("() => window._aplReady === true", timeout=15_000)
    page.evaluate(
        "() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))"
    )
    return page, tmp


@pytest.fixture
def mount_page(_pw_browser):
    pages, paths = [], []

    def _open(fig):
        page, tmp = _make_page(_pw_browser, fig)
        pages.append(page)
        paths.append(tmp)
        return page

    yield _open
    for p in pages:
        try:
            p.close()
        except Exception:
            pass
    for f in paths:
        f.unlink(missing_ok=True)


# ── helpers ──────────────────────────────────────────────────────────────────

def _export(page, opts=None):
    return page.evaluate(
        """(opts) => window._handle.exportPNG(opts || {})
                .then(r => ({dataUrl: r.dataUrl, width: r.width, height: r.height}))
                .catch(e => ({error: String(e && e.message || e)}))""",
        opts or {},
    )


def _decode(data_url):
    assert data_url.startswith("data:image/png;base64,"), data_url[:40]
    return decode_png(base64.b64decode(data_url.split(",", 1)[1]))


def _flush(page):
    page.evaluate(
        "() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))"
    )


def _center_rgb(arr):
    cy, cx = arr.shape[0] // 2, arr.shape[1] // 2
    return arr[cy, cx, :3].astype(np.int32)


def _count_near(arr, rgb, tol=14):
    d = np.abs(arr[..., :3].astype(np.int32) - np.asarray(rgb, np.int32))
    return int(((d <= tol).all(axis=-1)).sum())


def _lut_endpoint(cmap, idx=255):
    """The [r,g,b] a constant image at the clim top/bottom maps to for *cmap*."""
    fig, ax = apl.subplots(1, 1)
    p = ax.imshow(np.zeros((4, 4), np.float32), cmap=cmap, vmin=0, vmax=1, gpu=False)
    return list(p.to_state_dict()["colormap_data"][idx])


# ── tests ────────────────────────────────────────────────────────────────────

class TestLayerBlend:
    def test_two_layer_alpha_blend_pixels(self, mount_page):
        """A constant base at vmax (gray→white) with a constant magma layer at
        vmax and alpha=0.5 must composite to base*(1-a) + layer*a at the centre."""
        base_cmap, layer_cmap, alpha = "gray", "magma", 0.5
        fig, ax = apl.subplots(1, 1, figsize=(300, 300))
        p = ax.imshow(np.full((32, 32), 1.0, np.float32),
                      cmap=base_cmap, vmin=0.0, vmax=1.0, gpu=False)
        p.add_layer(np.full((32, 32), 1.0, np.float32),
                    cmap=layer_cmap, alpha=alpha, clim=(0, 1))

        base_hi = np.array(_lut_endpoint(base_cmap, 255), np.float64)   # white
        layer_hi = np.array(_lut_endpoint(layer_cmap, 255), np.float64)  # pale yellow
        expected = np.round(base_hi * (1 - alpha) + layer_hi * alpha)

        page = mount_page(fig)
        res = _export(page)
        assert "error" not in res, res.get("error")
        arr = _decode(res["dataUrl"])

        centre = _center_rgb(arr)
        d = int(np.max(np.abs(centre - expected)))
        assert d <= 16, (
            f"centre {centre.tolist()} != blend {expected.tolist()} (dmax={d}); "
            f"base_hi={base_hi.tolist()} layer_hi={layer_hi.tolist()}"
        )
        # The blend colour must NOT equal the bare base (proves the layer drew).
        assert int(np.max(np.abs(centre - base_hi))) > 16, (
            "centre equals the bare base — layer contribution missing"
        )

    def test_layer_visible_false_removes_contribution(self, mount_page):
        fig, ax = apl.subplots(1, 1, figsize=(300, 300))
        p = ax.imshow(np.full((32, 32), 1.0, np.float32),
                      cmap="gray", vmin=0.0, vmax=1.0, gpu=False)
        lyr = p.add_layer(np.full((32, 32), 1.0, np.float32),
                          cmap="magma", alpha=0.5, clim=(0, 1))
        page = mount_page(fig)

        with_layer = _center_rgb(_decode(_export(page)["dataUrl"]))

        # Hide the layer → drive the state update the way a live app does → repaint.
        lyr.set(visible=False)
        _set_panel(page, p)
        _flush(page)
        without_layer = _center_rgb(_decode(_export(page)["dataUrl"]))

        base_hi = np.array(_lut_endpoint("gray", 255), np.int32)
        assert int(np.max(np.abs(without_layer - base_hi))) <= 16, (
            f"hiding the layer did not revert to the base ({without_layer.tolist()})"
        )
        assert int(np.max(np.abs(with_layer - without_layer))) > 16, (
            "visible toggle produced no pixel change"
        )

    def test_layer_set_data_swaps_pixels(self, mount_page):
        """Swapping the layer's data (low→high value) changes the composited
        colour (the magma layer goes from dark to pale)."""
        fig, ax = apl.subplots(1, 1, figsize=(300, 300))
        p = ax.imshow(np.zeros((32, 32), np.float32),
                      cmap="gray", vmin=0.0, vmax=1.0, gpu=False)
        lyr = p.add_layer(np.zeros((32, 32), np.float32),
                          cmap="magma", alpha=0.6, clim=(0, 1))
        page = mount_page(fig)
        before = _center_rgb(_decode(_export(page)["dataUrl"]))

        lyr.set_data(np.full((32, 32), 1.0, np.float32))
        _set_panel(page, p)
        _flush(page)
        after = _center_rgb(_decode(_export(page)["dataUrl"]))

        assert int(np.max(np.abs(after - before))) > 16, (
            f"set_data did not change the composite ({before.tolist()} → {after.tolist()})"
        )

    def test_exportpng_includes_layer(self, mount_page):
        """exportPNG must capture the layer (it draws into plotCanvas, so it is
        free) — a large fraction of the frame carries the blended colour."""
        fig, ax = apl.subplots(1, 1, figsize=(300, 300))
        p = ax.imshow(np.full((32, 32), 1.0, np.float32),
                      cmap="gray", vmin=0.0, vmax=1.0, gpu=False)
        p.add_layer(np.full((32, 32), 1.0, np.float32),
                    cmap="magma", alpha=0.5, clim=(0, 1))
        base_hi = np.array(_lut_endpoint("gray", 255), np.float64)
        layer_hi = np.array(_lut_endpoint("magma", 255), np.float64)
        blend = np.round(base_hi * 0.5 + layer_hi * 0.5)

        page = mount_page(fig)
        arr = _decode(_export(page)["dataUrl"])
        assert _count_near(arr, blend) > 0.15 * arr.shape[0] * arr.shape[1], (
            "blended colour does not fill the image region in the export"
        )


class TestTintedLayer:
    """tint= layers: clear→colour ramp composited via per-texel LUT alpha."""

    def test_tint_ramp_transparent_low_opaque_high(self, mount_page):
        """A half-0 / half-1 tinted layer (alpha=1) must show the OPAQUE tint
        colour where intensity is high and the untouched base where intensity
        is low (per-texel alpha 0 → fully transparent)."""
        fig, ax = apl.subplots(1, 1, figsize=(300, 300))
        # Mid-gray base (distinct from the page/theme background).
        p = ax.imshow(np.full((32, 32), 0.5, np.float32),
                      cmap="gray", vmin=0.0, vmax=1.0, gpu=False)
        data = np.zeros((32, 32), np.float32)
        data[:, 16:] = 1.0                       # right half at clim top
        p.add_layer(data, tint="#ff0000", alpha=1.0, clim=(0, 1))

        base_mid = np.array(_lut_endpoint("gray", 127), np.float64)  # ~mid gray
        red = np.array([255, 0, 0], np.float64)

        page = mount_page(fig)
        res = _export(page)
        assert "error" not in res, res.get("error")
        arr = _decode(res["dataUrl"])
        npx = arr.shape[0] * arr.shape[1]

        # Opaque tint where intensity is high (right half of the fit-rect).
        assert _count_near(arr, red) > 0.08 * npx, (
            "opaque tint colour missing where layer intensity is high"
        )
        # Untouched base where intensity is low (alpha-0 texels draw nothing).
        assert _count_near(arr, base_mid) > 0.08 * npx, (
            "base colour not visible where layer intensity is low — "
            "alpha-0 texels are not transparent"
        )

    def test_texel_alpha_multiplies_with_layer_alpha(self, mount_page):
        """Per-texel LUT alpha (255 at clim top) × layer alpha 0.5 must give
        the 50 % base⊕tint blend — proving the two alphas compose (ImageData is
        unpremultiplied; globalAlpha multiplies at drawImage time)."""
        alpha = 0.5
        fig, ax = apl.subplots(1, 1, figsize=(300, 300))
        p = ax.imshow(np.full((32, 32), 0.5, np.float32),
                      cmap="gray", vmin=0.0, vmax=1.0, gpu=False)
        p.add_layer(np.full((32, 32), 1.0, np.float32),
                    tint="#ff0000", alpha=alpha, clim=(0, 1))

        base_mid = np.array(_lut_endpoint("gray", 127), np.float64)
        red = np.array([255, 0, 0], np.float64)
        expected = np.round(base_mid * (1 - alpha) + red * alpha)

        page = mount_page(fig)
        arr = _decode(_export(page)["dataUrl"])
        centre = _center_rgb(arr)
        d = int(np.max(np.abs(centre - expected)))
        assert d <= 16, (
            f"centre {centre.tolist()} != blend {expected.tolist()} (dmax={d})"
        )

    def test_set_tint_live_updates_composite(self, mount_page):
        """Toggling tint via layer.set() must invalidate the JS LUT-bitmap
        cache (lutKey) and repaint in the new colour."""
        fig, ax = apl.subplots(1, 1, figsize=(300, 300))
        p = ax.imshow(np.full((32, 32), 0.5, np.float32),
                      cmap="gray", vmin=0.0, vmax=1.0, gpu=False)
        lyr = p.add_layer(np.full((32, 32), 1.0, np.float32),
                          tint="#ff0000", alpha=1.0, clim=(0, 1))
        page = mount_page(fig)
        before = _center_rgb(_decode(_export(page)["dataUrl"]))
        assert int(np.max(np.abs(before - [255, 0, 0]))) <= 16, (
            f"initial tint not red: {before.tolist()}"
        )

        lyr.set(tint="#00ff00")
        _set_panel(page, p)
        _flush(page)
        after = _center_rgb(_decode(_export(page)["dataUrl"]))
        assert int(np.max(np.abs(after - [0, 255, 0]))) <= 16, (
            f"tint change did not repaint (still {after.tolist()}) — stale "
            "lutKey cache?"
        )

    def test_set_cmap_reverts_tint_to_opaque_cmap(self, mount_page):
        """set(cmap=...) clears the tint: low-intensity texels go back to the
        OPAQUE cmap colour (a 3-channel LUT defaults alpha to 255)."""
        fig, ax = apl.subplots(1, 1, figsize=(300, 300))
        p = ax.imshow(np.full((32, 32), 0.5, np.float32),
                      cmap="gray", vmin=0.0, vmax=1.0, gpu=False)
        # Zero-intensity tinted layer → fully transparent → base shows.
        lyr = p.add_layer(np.zeros((32, 32), np.float32),
                          tint="#ff0000", alpha=1.0, clim=(0, 1))
        page = mount_page(fig)
        base_mid = np.array(_lut_endpoint("gray", 127), np.int32)
        tinted = _center_rgb(_decode(_export(page)["dataUrl"]))
        assert int(np.max(np.abs(tinted - base_mid))) <= 16, (
            f"alpha-0 tinted layer altered the base: {tinted.tolist()}"
        )

        lyr.set(cmap="magma")
        _set_panel(page, p)
        _flush(page)
        reverted = _center_rgb(_decode(_export(page)["dataUrl"]))
        cmap_lo = np.array(_lut_endpoint("magma", 0), np.int32)  # opaque dark
        assert int(np.max(np.abs(reverted - cmap_lo))) <= 16, (
            f"cmap revert did not restore opaque colormap display: "
            f"{reverted.tolist()} != {cmap_lo.tolist()}"
        )


def _set_panel(page, plot):
    """Push the plot's CURRENT state into the mounted figure, splitting the geom
    channel exactly like ``Figure._push`` does (base64-resolved pixels, since the
    mount path has no PLOTBIN channel). Drives a live update as the app would."""
    pid = plot._id
    state = plot.to_state_dict()
    if hasattr(plot, "resolve_pixel_tokens"):
        plot.resolve_pixel_tokens(state)
    geom_keys = set(plot._GEOM_KEYS)
    geom = {k: state.pop(k) for k in list(geom_keys) if k in state}
    state["_geom_rev"] = (state.get("_geom_rev") or 0) + 1
    page.evaluate(
        """(args) => {
            const [pid, geom, view] = args;
            window._handle.set('panel_' + pid + '_geom', JSON.stringify(geom));
            window._handle.setPanelState(pid, view);
        }""",
        [pid, geom, state],
    )


# ── GPU base + Canvas2D layer ────────────────────────────────────────────────

GPU_IMG_N = 1200   # > GPU_IMAGE_THRESHOLD (1 Mpx) → WebGPU base in auto mode


@pytest.fixture
def gpu_mount_page(_pw_gpu_browser):
    pages, paths = [], []

    def _open(fig, expect_gpu=False):
        page, tmp = _make_page(_pw_gpu_browser, fig)
        pages.append(page)
        paths.append(tmp)
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


class TestGpuBaseWithLayer:
    def test_layer_over_gpu_base(self, gpu_mount_page):
        """A large image on the WebGPU base path with a Canvas2D layer over it:
        the layer (which composites on plotCanvas above gpuCanvas) must appear in
        the export. Skips cleanly without a WebGPU adapter (via _pw_gpu_browser)."""
        n = GPU_IMG_N
        fig, ax = apl.subplots(1, 1, figsize=(400, 300))
        # Base engages the GPU path (large, gpu=True) but tile=False so the WHOLE
        # frame goes to the GPU as one texture (layers + tiling are mutually
        # exclusive). A constant magma layer composites on Canvas2D over it.
        p = ax.imshow(np.full((n, n), 1.0, np.float32),
                      cmap="gray", vmin=0.0, vmax=1.0, gpu=True, tile=False)
        p.add_layer(np.full((n, n), 1.0, np.float32),
                    cmap="magma", alpha=0.5, clim=(0, 1))

        base_hi = np.array(_lut_endpoint("gray", 255), np.float64)
        layer_hi = np.array(_lut_endpoint("magma", 255), np.float64)
        blend = np.round(base_hi * 0.5 + layer_hi * 0.5)

        page = gpu_mount_page(fig, expect_gpu=True)
        # Confirm the GPU path is the one painting the base.
        diag = page.evaluate("() => globalThis.__apl_gpu2d || {}")
        assert diag and all(d.get("active") for d in diag.values()), (
            f"GPU base path not active: {diag}"
        )

        res = _export(page)
        assert "error" not in res, res.get("error")
        arr = _decode(res["dataUrl"])
        # The blended colour (base⊕layer) must be present — proves the Canvas2D
        # layer composited over the WebGPU base and both are captured.
        assert _count_near(arr, blend) > 500, (
            f"blend colour {blend.tolist()} missing over GPU base — layer not composited"
        )
        # And it must differ from the bare GPU base colour.
        assert int(np.max(np.abs(blend - base_hi))) > 16

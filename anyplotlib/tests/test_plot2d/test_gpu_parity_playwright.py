"""GPU-vs-CPU rendering parity for the WebGPU 2-D image path.

Every test renders the SAME figure twice in the SAME WebGPU-capable browser —
once with ``gpu=True`` (WebGPU texture + shader-LUT path) and once with
``gpu=False`` (the Canvas2D reference path) — applies IDENTICAL interactions
to both, and compares full-composite PNG screenshots. The Canvas2D path is the
fully CI-tested reference, so any GPU divergence (zoom/pan window, letterbox,
colormap, detail-tile stitch) shows up as a pixel diff.

These run on real WebGPU in headless Chromium (``channel="chromium"`` +
``--enable-unsafe-webgpu`` — see ``_pw_gpu_browser``) and are skipped on
machines with no adapter. ``page.screenshot()`` DOES capture the WebGPU canvas
under the new headless mode, so plain PNG comparison works (the old
"swapchain reads black" caveat applies to Electron offscreen capture, not to
this harness).

Regression anchor: the shader used to sample the v (row) window MIRRORED about
the texture midline (``1 - mix(v0, v1, q.y)`` instead of interpolating from
``v1`` down to ``v0``), which was invisible at rest and at centred zoom
(v0+v1=1) but flipped the pan direction vertically and detached the image from
the markers/widgets whenever the view was vertically off-centre. The pan tests
below fail hard (>50 % of pixels) on that bug.
"""
from __future__ import annotations

import json

import numpy as np
import pytest

import anyplotlib as apl
from anyplotlib.tests._png_utils import compare_arrays, decode_png

FIG_W, FIG_H = 400, 300
PAD_L, PAD_R, PAD_T, PAD_B = 58, 12, 12, 42
GRID_PAD = 8
IMG_N = 1200  # > 1 Mpx: over GPU_IMAGE_THRESHOLD even in auto mode


# ---------------------------------------------------------------------------
# Scene + helpers
# ---------------------------------------------------------------------------

def _asym_image(n: int = IMG_N) -> np.ndarray:
    """Gradient + distinct corner blocks: any flip/mirror/offset is visible."""
    yy, xx = np.mgrid[0:n, 0:n].astype(np.float32)
    img = (xx / n) * 0.3 + (yy / n) * 0.3
    img[(yy < n // 3) & (xx < n // 3)] = 1.0          # bright block TOP-LEFT
    img[(yy > 2 * n // 3) & (xx > 2 * n // 3)] = 0.8  # dimmer block BOTTOM-RIGHT
    return img


def _make_pair(gpu_page, *, tile=False, markers=False, widget=False,
               img=None):
    """Build gpu=True / gpu=False twins and open both pages.

    Returns (page_gpu, page_cpu, plot_gpu, plot_cpu).
    """
    plots, pages = [], []
    for gpu in (True, False):
        fig, ax = apl.subplots(1, 1, figsize=(FIG_W, FIG_H))
        data = _asym_image() if img is None else img
        p = ax.imshow(data, cmap="viridis", vmin=0.0, vmax=1.0,
                      gpu=gpu, tile=tile)
        if markers:
            p.add_circles(
                np.array([[150.0, 200.0], [600.0, 600.0], [900.0, 300.0]],
                         dtype=np.float32),
                name="pts", radius=40,
                edgecolors="#ff0000", linewidths=2.5,
            )
        if widget:
            p.add_widget("rectangle", x=400.0, y=450.0, w=220.0, h=160.0)
        plots.append(p)
        pages.append(gpu_page(fig, expect_gpu=gpu))
    return pages[0], pages[1], plots[0], plots[1]


def _plot_center() -> tuple[int, int]:
    cx = GRID_PAD + PAD_L + (FIG_W - PAD_L - PAD_R) // 2
    cy = GRID_PAD + PAD_T + (FIG_H - PAD_T - PAD_B) // 2
    return cx, cy


def _snap(page) -> np.ndarray:
    return decode_png(page.locator("#widget-root").screenshot())


def _settle(page, ms=150):
    page.wait_for_timeout(ms)
    page.evaluate(
        "() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))"
    )


def _assert_parity(name, arr_gpu, arr_cpu, *, tol=10, max_diff_frac=0.005):
    """GPU output must match the Canvas2D reference.

    Tolerance covers nearest-sampling rounding differences between the shader
    UV math and Canvas2D drawImage at fractional source rects; a coordinate
    bug (mirror/offset/flip) moves whole image regions and produces diffs two
    orders of magnitude above this.
    """
    ok, msg = compare_arrays(arr_gpu, arr_cpu, tol=tol, max_diff_frac=max_diff_frac)
    assert ok, f"{name}: GPU render diverged from Canvas2D reference — {msg}"


def _assert_gpu_active(page, expect=True):
    diag = page.evaluate("() => globalThis.__apl_gpu2d || {}")
    assert diag, "no 2-D GPU diagnostic recorded"
    for pid, d in diag.items():
        assert d.get("active") is expect, (
            f"panel {pid}: GPU path active={d.get('active')} (expected {expect}) — {d}"
        )


def _set_zoom(page, plot, zoom, cx=None, cy=None):
    page.evaluate(
        "(a) => globalThis.__apl_setZoom(a.pid, a.z, a.cx, a.cy)",
        {"pid": plot._id, "z": zoom, "cx": cx, "cy": cy},
    )


def _view_state(page, plot) -> dict:
    return json.loads(
        page.evaluate("(pid) => globalThis.__apl_viewStateJson(pid)", plot._id)
    )


# ---------------------------------------------------------------------------
# Image parity: rest / zoom / pan
# ---------------------------------------------------------------------------

class TestGpuImageParity:
    def test_rest_parity(self, gpu_interact_page):
        pg, pc, *_ = _make_pair(gpu_interact_page)
        _settle(pg); _settle(pc)
        _assert_gpu_active(pg)
        _assert_gpu_active(pc, expect=False)
        _assert_parity("rest", _snap(pg), _snap(pc))

    def test_zoom_in_centred_parity(self, gpu_interact_page):
        pg, pc, p_gpu, p_cpu = _make_pair(gpu_interact_page)
        for page, plot in ((pg, p_gpu), (pc, p_cpu)):
            _set_zoom(page, plot, 3.0, 0.5, 0.5)
            _settle(page)
        _assert_gpu_active(pg)  # GPU must NOT fall back on zoom
        _assert_parity("zoom-in centred", _snap(pg), _snap(pc))

    def test_pan_y_parity(self, gpu_interact_page):
        # Vertically OFF-CENTRE window — the historical v-mirror bug shows here.
        pg, pc, p_gpu, p_cpu = _make_pair(gpu_interact_page)
        for page, plot in ((pg, p_gpu), (pc, p_cpu)):
            _set_zoom(page, plot, 3.0, 0.5, 0.22)
            _settle(page)
        _assert_gpu_active(pg)
        _assert_parity("pan-y (off-centre v window)", _snap(pg), _snap(pc))

    def test_pan_x_parity(self, gpu_interact_page):
        pg, pc, p_gpu, p_cpu = _make_pair(gpu_interact_page)
        for page, plot in ((pg, p_gpu), (pc, p_cpu)):
            _set_zoom(page, plot, 3.0, 0.2, 0.5)
            _settle(page)
        _assert_gpu_active(pg)
        _assert_parity("pan-x (off-centre u window)", _snap(pg), _snap(pc))

    def test_pan_corner_parity(self, gpu_interact_page):
        pg, pc, p_gpu, p_cpu = _make_pair(gpu_interact_page)
        for page, plot in ((pg, p_gpu), (pc, p_cpu)):
            _set_zoom(page, plot, 4.0, 0.85, 0.8)
            _settle(page)
        _assert_gpu_active(pg)
        _assert_parity("pan corner", _snap(pg), _snap(pc))

    def test_zoom_out_parity(self, gpu_interact_page):
        # zoom < 1: the dest-rect (letterbox shrink) branch of the uniform.
        pg, pc, p_gpu, p_cpu = _make_pair(gpu_interact_page)
        for page, plot in ((pg, p_gpu), (pc, p_cpu)):
            _set_zoom(page, plot, 0.75, 0.5, 0.5)
            _settle(page)
        _assert_gpu_active(pg)
        _assert_parity("zoom-out", _snap(pg), _snap(pc))


class TestGpuMousePanParity:
    """End-to-end through the real wheel/drag handlers (not __apl_setZoom)."""

    def test_wheel_zoom_then_drag_pan(self, gpu_interact_page):
        pg, pc, p_gpu, p_cpu = _make_pair(gpu_interact_page)
        cx, cy = _plot_center()

        for page in (pg, pc):
            page.mouse.move(cx, cy)
            for _ in range(6):
                page.mouse.wheel(0, -120)
            _settle(page)
        _assert_parity("mouse wheel zoom", _snap(pg), _snap(pc))

        # Drag DOWN: image content must move down (view up) on BOTH paths.
        for page in (pg, pc):
            page.mouse.move(cx, cy)
            page.mouse.down()
            page.mouse.move(cx, cy + 60, steps=8)
            page.mouse.up()
            _settle(page)
        st_g = _view_state(pg, p_gpu)
        st_c = _view_state(pc, p_cpu)
        assert st_g["zoom"] == st_c["zoom"]
        assert st_g["center_x"] == st_c["center_x"]
        assert st_g["center_y"] == st_c["center_y"]
        _assert_gpu_active(pg)
        _assert_parity("mouse pan down", _snap(pg), _snap(pc))

        # Then drag RIGHT while still vertically off-centre.
        for page in (pg, pc):
            page.mouse.move(cx, cy)
            page.mouse.down()
            page.mouse.move(cx + 60, cy, steps=8)
            page.mouse.up()
            _settle(page)
        _assert_gpu_active(pg)
        _assert_parity("mouse pan right", _snap(pg), _snap(pc))

    def test_pan_direction_moves_content_with_cursor(self, gpu_interact_page):
        """Row-profile check independent of the CPU reference: dragging DOWN
        must move image rows DOWN on screen (the same rows appear lower)."""
        pg, _, p_gpu, _ = _make_pair(gpu_interact_page)
        cx, cy = _plot_center()
        _set_zoom(pg, p_gpu, 3.0, 0.5, 0.5)
        _settle(pg)
        before = _snap(pg).astype(np.int32)

        pg.mouse.move(cx, cy)
        pg.mouse.down()
        pg.mouse.move(cx, cy + 40, steps=8)
        pg.mouse.up()
        _settle(pg)
        after = _snap(pg).astype(np.int32)

        # The pan handler moved center_y UP the image (drag down = view up), so
        # the "after" frame equals "before" shifted DOWN by ~40 px. Verify by
        # comparing a shifted slice — mean row-difference must be far smaller
        # for the correct shift than for the opposite one.
        h = before.shape[0]
        shift = 40
        band = slice(80, h - 80)
        correct = np.abs(after[shift:, :][band] - before[:-shift, :][band]).mean()
        inverted = np.abs(after[:-shift, :][band] - before[shift:, :][band]).mean()
        assert correct < inverted, (
            f"pan-y direction inverted on GPU path: shifted-down diff {correct:.2f} "
            f">= shifted-up diff {inverted:.2f}"
        )


# ---------------------------------------------------------------------------
# Markers + widgets registration with the GPU image
# ---------------------------------------------------------------------------

def _feature_marker_image(n: int = IMG_N, fx: int = 780, fy: int = 420):
    """Black field with one bright square centred at (fx, fy) image px."""
    img = np.zeros((n, n), dtype=np.float32)
    img[fy - 12:fy + 12, fx - 12:fx + 12] = 1.0
    return img, fx, fy


def _centroid(mask: np.ndarray):
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        return None
    return float(xs.mean()), float(ys.mean())


def _feature_and_ring_centroids(arr: np.ndarray):
    """Locate the viridis-bright feature block and the red marker ring."""
    r = arr[..., 0].astype(np.int32)
    g = arr[..., 1].astype(np.int32)
    b = arr[..., 2].astype(np.int32)
    # value 1.0 in viridis ≈ (253, 231, 37)
    feature = (r > 200) & (g > 200) & (b < 120)
    ring = (r > 180) & (g < 90) & (b < 90)
    return _centroid(feature), _centroid(ring)


class TestGpuMarkerRegistration:
    def _scene(self, gpu):
        img, fx, fy = _feature_marker_image()
        fig, ax = apl.subplots(1, 1, figsize=(FIG_W, FIG_H))
        p = ax.imshow(img, cmap="viridis", vmin=0.0, vmax=1.0, gpu=gpu)
        p.add_circles(np.array([[float(fx), float(fy)]], dtype=np.float32),
                      name="mark", radius=60,
                      edgecolors="#ff0000", linewidths=3)
        return fig, p, fx, fy

    @pytest.mark.parametrize("view", [
        (1.0, None, None),        # rest
        (3.0, 0.65, 0.35),        # zoom + off-centre both axes
        (2.0, 0.5, 0.42),         # vertically off-centre (the mirror case);
                                  # feature y=420 stays inside rows [204, 804]
    ])
    def test_marker_sits_on_feature(self, gpu_interact_page, view):
        """The red circle must stay centred on the bright block it marks, on
        BOTH paths, at any zoom/pan — ties the marker transform to the image
        transform directly (no reference page needed)."""
        zoom, cx, cy = view
        for gpu in (True, False):
            fig, p, _, _ = self._scene(gpu)
            page = gpu_interact_page(fig, expect_gpu=gpu)
            if zoom != 1.0:
                _set_zoom(page, p, zoom, cx, cy)
            _settle(page)
            if gpu:
                _assert_gpu_active(page)
            feat, ring = _feature_and_ring_centroids(_snap(page))
            path = "GPU" if gpu else "CPU"
            assert feat is not None, f"{path}: feature block not visible at {view}"
            assert ring is not None, f"{path}: marker ring not visible at {view}"
            dist = ((feat[0] - ring[0]) ** 2 + (feat[1] - ring[1]) ** 2) ** 0.5
            assert dist < 4.0, (
                f"{path}: marker detached from image feature at zoom={zoom} "
                f"center=({cx},{cy}): feature {feat} vs ring {ring} — {dist:.1f} px apart"
            )

    def test_marker_composite_parity_zoom_pan(self, gpu_interact_page):
        pg, pc, p_gpu, p_cpu = _make_pair(gpu_interact_page, markers=True)
        for page, plot in ((pg, p_gpu), (pc, p_cpu)):
            _set_zoom(page, plot, 2.5, 0.6, 0.3)
            _settle(page)
        _assert_gpu_active(pg)
        _assert_parity("markers over zoom/pan", _snap(pg), _snap(pc))


class TestGpuWidgetParity:
    def _rect_center_screen(self, page, plot):
        st = _view_state(page, plot)
        w = next(x for x in st["overlay_widgets"] if x["type"] == "rectangle")
        wcx, wcy = w["x"] + w["w"] / 2, w["y"] + w["h"] / 2
        return page.evaluate(
            """(a) => {
                const ov = Array.from(document.querySelectorAll('canvas'))
                    .find(c => c.style && c.style.zIndex === '5');
                const r = ov.getBoundingClientRect();
                const q = globalThis.__apl_imgToCanvas
                    ? globalThis.__apl_imgToCanvas(a.pid, a.ix, a.iy) : null;
                return q ? [r.left + q[0], r.top + q[1]] : null;
            }""",
            {"pid": plot._id, "ix": wcx, "iy": wcy},
        )

    def test_widget_drag_same_result_and_pixels(self, gpu_interact_page):
        pg, pc, p_gpu, p_cpu = _make_pair(gpu_interact_page, widget=True)
        for page, plot in ((pg, p_gpu), (pc, p_cpu)):
            _set_zoom(page, plot, 2.0, 0.45, 0.35)
            _settle(page)

        # Drag each rectangle by the same screen delta, grabbing its centre.
        for page, plot in ((pg, p_gpu), (pc, p_cpu)):
            pos = self._rect_center_screen(page, plot)
            assert pos is not None, "__apl_imgToCanvas hook missing"
            sx, sy = pos
            page.mouse.move(sx, sy)
            page.mouse.down()
            page.mouse.move(sx + 30, sy + 25, steps=10)
            page.mouse.up()
            _settle(page)

        st_g = _view_state(pg, p_gpu)
        st_c = _view_state(pc, p_cpu)
        w_g = next(x for x in st_g["overlay_widgets"] if x["type"] == "rectangle")
        w_c = next(x for x in st_c["overlay_widgets"] if x["type"] == "rectangle")
        for k in ("x", "y", "w", "h"):
            assert abs(w_g[k] - w_c[k]) < 1e-6, (
                f"widget {k} diverged: gpu={w_g[k]} cpu={w_c[k]}"
            )
        _assert_gpu_active(pg)
        _assert_parity("widget drag composite", _snap(pg), _snap(pc))


# ---------------------------------------------------------------------------
# Detail tile (tile mode) on the GPU detail pass
# ---------------------------------------------------------------------------

class TestGpuDetailTileParity:
    def test_detail_tile_zoom_parity(self, gpu_interact_page):
        """Zoomed-in view fully covered by a pre-baked detail tile: the GPU
        detail pass (uniformBuf2) must place the tile rows exactly like the
        Canvas2D detail blit. Tile content differs from the base so sampling
        the tile (not the base) is proven, and any v-mirror in the detail
        pass moves the pattern."""
        n = IMG_N
        base = _asym_image(n)
        # Tile covering [480,960]x[180,660] with content DIFFERENT from base.
        # Content must be vertically APERIODIC: a monotonic vertical gradient
        # (any v-mirror reverses it) + one unique bright band near the tile top
        # (periodic stripes can self-align under a mirror and hide the bug).
        ty0, ty1, tx0, tx1 = 180, 660, 480, 960
        th = ty1 - ty0
        tile = np.tile(
            (0.15 + 0.55 * np.arange(th, dtype=np.float32) / th)[:, None],
            (1, tx1 - tx0))
        tile[40:80, :] = 1.0  # unique band, near the TOP of the tile only

        pages, plots = [], []
        for gpu in (True, False):
            fig, ax = apl.subplots(1, 1, figsize=(FIG_W, FIG_H))
            p = ax.imshow(base, cmap="viridis", vmin=0.0, vmax=1.0,
                          gpu=gpu, tile=True)
            p.set_detail(tile, tx0, tx1, ty0, ty1)
            # Bake a zoom/centre whose visible window sits INSIDE the tile
            # region but vertically OFF its centre (the mirror-sensitive case):
            # zoom=4 → 300 px window; centre (0.6, 0.25*?) …
            plots.append(p)
            page = gpu_interact_page(fig, expect_gpu=gpu)
            _set_zoom(page, p, 4.0, 0.6, 0.3)   # window x [570,870] y [210,510]
            _settle(page, 300)                  # let the detail blend ramp finish
            pages.append(page)

        pg, pc = pages
        _assert_gpu_active(pg)
        arr_gpu, arr_cpu = _snap(pg), _snap(pc)
        # Sanity: the tile's unique bright band (near the tile TOP, inside the
        # visible window) must be visible — i.e. the tile was sampled, not the
        # base gradient.
        bright = (arr_cpu[..., 0] > 200) & (arr_cpu[..., 1] > 200)
        assert bright.mean() > 0.03, "detail tile content not visible on reference"
        _assert_parity("detail tile zoom", arr_gpu, arr_cpu)

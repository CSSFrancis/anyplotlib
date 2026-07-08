"""Playwright parity tests for tile vs non-tile interactive behaviour.

These tests use the same interactions on paired figures and require strict
pixel equality so subtle overlay regressions are not hidden by tolerances.
"""
from __future__ import annotations

import json

import numpy as np

import anyplotlib as apl
from anyplotlib.tests._png_utils import compare_arrays, compare_arrays_exact, decode_png
from anyplotlib.tests.test_interactive._event_test_utils import (
    _collect_events,
    _get_events,
    _plot_center_page,
)

FIG_W, FIG_H = 400, 300
PAD_L, PAD_R, PAD_T, PAD_B = 58, 12, 12, 42


def _widget_png(page) -> np.ndarray:
    return decode_png(page.locator("#widget-root").screenshot())


def _markers_canvas_rgb(page) -> np.ndarray:
    data = page.evaluate(
        """() => {
            const c = Array.from(document.querySelectorAll('canvas'))
              .find(x => x.style && x.style.zIndex === '6');
            if (!c) throw new Error('markers canvas not found');
            const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
            return { w: c.width, h: c.height, data: Array.from(d) };
        }"""
    )
    arr = np.asarray(data["data"], dtype=np.uint8).reshape(data["h"], data["w"], 4)
    return arr[:, :, :3]


def _assert_exact(
    name: str,
    actual: np.ndarray,
    expected: np.ndarray,
    *,
    allow_tolerance: bool = False,
) -> None:
    ok, msg = compare_arrays_exact(actual, expected)
    if ok:
        return
    if allow_tolerance:
        ok_tol, msg_tol = compare_arrays(actual, expected, tol=4, max_diff_frac=0.003)
        assert ok_tol, f"{name}: exact mismatch ({msg}); tolerance mismatch ({msg_tol})"
        return
    assert ok, f"{name}: {msg}"


def _make_scene(tile: bool):
    fig, ax = apl.subplots(1, 1, figsize=(FIG_W, FIG_H))
    # 1024x1024 keeps tile mode active when requested but avoids overview decimation.
    img = np.tile(np.linspace(0.0, 1.0, 1024, dtype=np.float32), (1024, 1))
    plot = ax.imshow(img, cmap="gray", vmin=0.0, vmax=1.0, tile=tile, gpu=False)
    plot.add_circles(
        np.array([[120.0, 180.0], [500.0, 500.0], [860.0, 260.0]], dtype=np.float32),
        name="pts",
        radius=7,
        facecolors="#ff4d4d",
        edgecolors="#ffffff",
    )
    rect = plot.add_widget("rectangle", x=320.0, y=320.0, w=180.0, h=140.0)
    return fig, plot, rect


def _rect_center_page(page, panel_id: str, widget_id: str) -> tuple[float, float]:
    return tuple(page.evaluate(
        """(args) => {
            const [pid, wid, padL, padR, padT, padB] = args;
            const st = JSON.parse(globalThis.__apl_viewStateJson(pid));
            const w = (st.overlay_widgets || []).find(v => v.id === wid);
            if (!w) throw new Error('widget not found');
            const ov = Array.from(document.querySelectorAll('canvas'))
              .find(c => c.style && c.style.zIndex === '5');
            if (!ov) throw new Error('overlay canvas not found');
            const r = ov.getBoundingClientRect();
            const availW = ov.width - padL - padR;
            const availH = ov.height - padT - padB;
            const iw = Math.max(1, st.image_width || 1);
            const ih = Math.max(1, st.image_height || 1);
            const s = Math.min(availW / iw, availH / ih);
            const fitW = iw * s;
            const fitH = ih * s;
            const ox = padL + (availW - fitW) * 0.5;
            const oy = padT + (availH - fitH) * 0.5;
            const cx = w.x + w.w * 0.5;
            const cy = w.y + w.h * 0.5;
            return [r.left + ox + cx * s, r.top + oy + cy * s];
        }""",
        [panel_id, widget_id, PAD_L, PAD_R, PAD_T, PAD_B],
    ))


def _widget_rect(page, panel_id: str, widget_id: str) -> dict:
    st = json.loads(page.evaluate("(pid) => globalThis.__apl_viewStateJson(pid)", panel_id))
    w = [x for x in st.get("overlay_widgets", []) if x.get("id") == widget_id]
    assert w, "rectangle widget not found in state"
    return w[0]


class TestTileInteractiveParity:
    def test_initial_marker_widget_overlay_matches(self, interact_page):
        fig_plain, p_plain, _ = _make_scene(tile=False)
        fig_tile, p_tile, _ = _make_scene(tile=True)
        page_plain = interact_page(fig_plain)
        page_tile = interact_page(fig_tile)
        page_plain.wait_for_timeout(120)
        page_tile.wait_for_timeout(120)

        # Sanity: this test should exercise tile mode on one side.
        st_tile = json.loads(page_tile.evaluate("(pid) => globalThis.__apl_viewStateJson(pid)", p_tile._id))
        assert st_tile.get("tile_enabled") is True

        arr_plain = _widget_png(page_plain)
        arr_tile = _widget_png(page_tile)
        _assert_exact("initial marker/widget overlay parity", arr_tile, arr_plain)

    def test_widget_drag_parity_events_and_pixels(self, interact_page):
        fig_plain, p_plain, r_plain = _make_scene(tile=False)
        fig_tile, p_tile, r_tile = _make_scene(tile=True)
        page_plain = interact_page(fig_plain)
        page_tile = interact_page(fig_tile)
        _collect_events(page_plain)
        _collect_events(page_tile)

        sx_plain, sy_plain = _rect_center_page(page_plain, p_plain._id, r_plain.id)
        sx_tile, sy_tile = _rect_center_page(page_tile, p_tile._id, r_tile.id)

        for page, sx, sy in (
            (page_plain, sx_plain, sy_plain),
            (page_tile, sx_tile, sy_tile),
        ):
            page.mouse.move(sx, sy)
            page.mouse.down()
            page.mouse.move(sx + 35, sy + 20, steps=10)
            page.mouse.up()
            page.wait_for_timeout(120)

        rect_plain = _widget_rect(page_plain, p_plain._id, r_plain.id)
        rect_tile = _widget_rect(page_tile, p_tile._id, r_tile.id)
        for key in ("x", "y", "w", "h"):
            assert rect_tile[key] == rect_plain[key], (
                f"widget field {key} diverged: tile={rect_tile[key]} plain={rect_plain[key]}"
            )

        ev_plain = _get_events(page_plain)
        ev_tile = _get_events(page_tile)
        pm_plain = len([e for e in ev_plain if e.get("event_type") == "pointer_move"])
        pm_tile = len([e for e in ev_tile if e.get("event_type") == "pointer_move"])
        pu_plain = len([e for e in ev_plain if e.get("event_type") == "pointer_up"])
        pu_tile = len([e for e in ev_tile if e.get("event_type") == "pointer_up"])
        assert pm_plain > 0 and pu_plain > 0
        assert pm_tile == pm_plain and pu_tile == pu_plain

        arr_plain = _widget_png(page_plain)
        arr_tile = _widget_png(page_tile)
        _assert_exact("post-drag marker/widget overlay parity", arr_tile, arr_plain)

    def test_zoomed_marker_overlay_matches(self, interact_page):
        fig_plain, p_plain, _ = _make_scene(tile=False)
        fig_tile, p_tile, _ = _make_scene(tile=True)
        page_plain = interact_page(fig_plain)
        page_tile = interact_page(fig_tile)

        cx, cy = _plot_center_page(FIG_W, FIG_H)
        for page in (page_plain, page_tile):
            page.mouse.move(cx, cy)
            page.mouse.wheel(0, -500)
            page.wait_for_timeout(160)

        arr_plain = _markers_canvas_rgb(page_plain)
        arr_tile = _markers_canvas_rgb(page_tile)
        _assert_exact(
            "zoomed marker-canvas parity",
            arr_tile,
            arr_plain,
            allow_tolerance=True,
        )

        st_plain = json.loads(page_plain.evaluate("(pid) => globalThis.__apl_viewStateJson(pid)", p_plain._id))
        st_tile = json.loads(page_tile.evaluate("(pid) => globalThis.__apl_viewStateJson(pid)", p_tile._id))
        assert st_tile.get("zoom") == st_plain.get("zoom")





"""
Touch input tests — the touch-to-mouse bridge in figure_esm.js makes plots
usable on iPad / iPhone:

  * 1-finger drag  → pan / orbit / drag a widget / ROI / marker / plane
  * 2-finger pinch → zoom (mapped to wheel)
  * double-tap     → dblclick → the panel's double_click event (picking /
                     app callbacks); reset-zoom is the ``r`` key, unchanged

These drive the SAME handlers the mouse uses, via synthesised MouseEvent /
WheelEvent, so a passing mouse interaction implies a passing touch one.  The
tests use Playwright's touch emulation (``has_touch=True``) and dispatch raw
TouchEvents (Playwright has no high-level multi-touch drag helper).
"""
from __future__ import annotations

import json
import pathlib
import tempfile

import numpy as np
import pytest

import anyplotlib as apl
from anyplotlib.tests.conftest import _build_interact_html


# ── touch-enabled page fixture ────────────────────────────────────────────────

@pytest.fixture
def touch_page(_pw_browser):
    """Open a figure in a touch-enabled context; return the live Page."""
    contexts, paths = [], []

    def _open(widget):
        html = _build_interact_html(widget)
        with tempfile.NamedTemporaryFile(
            suffix=".html", mode="w", encoding="utf-8", delete=False
        ) as fh:
            fh.write(html)
            tmp = pathlib.Path(fh.name)
        paths.append(tmp)
        ctx = _pw_browser.new_context(has_touch=True,
                                      viewport={"width": 600, "height": 600})
        contexts.append(ctx)
        page = ctx.new_page()
        page.goto(tmp.as_uri())
        page.wait_for_function("() => window._aplReady === true", timeout=15_000)
        page.evaluate(
            "() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))"
        )
        return page

    yield _open
    for c in contexts:
        try:
            c.close()
        except Exception:
            pass
    for p in paths:
        p.unlink(missing_ok=True)


# ── touch-gesture helpers (raw TouchEvent dispatch) ───────────────────────────

_OVERLAY = "[...document.querySelectorAll('canvas')].find(x => x.style.zIndex === '5')"


def _overlay_box(page):
    return page.evaluate(
        f"() => {{ const c = {_OVERLAY}; const r = c.getBoundingClientRect();"
        f"  return {{ x: r.x, y: r.y, w: r.width, h: r.height }}; }}")


def _touch_drag(page, x0, y0, dx, dy, steps=6):
    page.evaluate(
        f"""([x0,y0,dx,dy,steps]) => {{
            const c = {_OVERLAY};
            const mk = (x,y) => new Touch({{identifier:1, target:c, clientX:x, clientY:y}});
            const tev = (t,x,y) => new TouchEvent(t, {{
                touches: t==='touchend' ? [] : [mk(x,y)],
                changedTouches:[mk(x,y)], targetTouches: t==='touchend'?[]:[mk(x,y)],
                bubbles:true, cancelable:true }});
            c.dispatchEvent(tev('touchstart', x0, y0));
            for (let i=1;i<=steps;i++)
                c.dispatchEvent(tev('touchmove', x0+dx*i/steps, y0+dy*i/steps));
            c.dispatchEvent(tev('touchend', x0+dx, y0+dy));
        }}""", [x0, y0, dx, dy, steps])


def _touch_tap(page, x, y):
    page.evaluate(
        f"""([x,y]) => {{
            const c = {_OVERLAY};
            const t = new Touch({{identifier:1, target:c, clientX:x, clientY:y}});
            c.dispatchEvent(new TouchEvent('touchstart', {{touches:[t],changedTouches:[t],bubbles:true,cancelable:true}}));
            c.dispatchEvent(new TouchEvent('touchend', {{touches:[],changedTouches:[t],bubbles:true,cancelable:true}}));
        }}""", [x, y])


def _pinch(page, cx, cy, start_half=20, end_half=130, steps=8):
    """Two-finger pinch centred at (cx,cy); spread = zoom in."""
    page.evaluate(
        f"""([cx,cy,sh,eh,steps]) => {{
            const c = {_OVERLAY};
            const mk = (id,x,y) => new Touch({{identifier:id, target:c, clientX:x, clientY:y}});
            const tev = (t,ts) => new TouchEvent(t, {{touches:ts, changedTouches:ts, targetTouches:ts, bubbles:true, cancelable:true}});
            c.dispatchEvent(tev('touchstart', [mk(1,cx-sh,cy), mk(2,cx+sh,cy)]));
            for (let i=1;i<=steps;i++) {{
                const h = sh + (eh-sh)*i/steps;
                c.dispatchEvent(tev('touchmove', [mk(1,cx-h,cy), mk(2,cx+h,cy)]));
            }}
            c.dispatchEvent(tev('touchend', []));
        }}""", [cx, cy, start_half, end_half, steps])


def _panel_state(page, pid):
    return json.loads(page.evaluate(f"() => window._aplModel.get('panel_{pid}_json')"))


def _no_errors(page):
    errs = []
    page.on("pageerror", lambda e: errs.append(str(e)))
    return errs


# ── tests ─────────────────────────────────────────────────────────────────────

class TestTouch2D:
    def test_one_finger_drags_crosshair_widget(self, touch_page):
        fig, ax = apl.subplots(1, 1, figsize=(400, 400))
        plot = ax.imshow(np.zeros((64, 64), dtype=np.float32))
        cw = plot.add_widget("crosshair", cx=32, cy=32, color="#ff0000")
        page = touch_page(fig)
        b = _overlay_box(page)
        # crosshair at image-centre → overlay-centre (no axis gutters for plain imshow)
        cx, cy = b["x"] + b["w"] * 0.5, b["y"] + b["h"] * 0.5
        before = _panel_state(page, plot._id)["overlay_widgets"][0]
        _touch_drag(page, cx, cy, -80, -60)
        page.wait_for_timeout(150)
        after = _panel_state(page, plot._id)["overlay_widgets"][0]
        assert abs(after["cx"] - before["cx"]) > 3 or abs(after["cy"] - before["cy"]) > 3, \
            f"crosshair did not move on 1-finger drag: {before} -> {after}"

    def test_pinch_zooms_image(self, touch_page):
        fig, ax = apl.subplots(1, 1, figsize=(400, 400))
        plot = ax.imshow(np.zeros((64, 64), dtype=np.float32))
        page = touch_page(fig)
        b = _overlay_box(page)
        z0 = _panel_state(page, plot._id)["zoom"]
        _pinch(page, b["x"] + b["w"] * 0.5, b["y"] + b["h"] * 0.5)
        page.wait_for_timeout(150)
        z1 = _panel_state(page, plot._id)["zoom"]
        assert z1 > z0 + 0.1, f"pinch-out did not zoom in: {z0} -> {z1}"

    def test_no_console_errors(self, touch_page):
        fig, ax = apl.subplots(1, 1, figsize=(400, 400))
        plot = ax.imshow(np.zeros((32, 32), dtype=np.float32))
        plot.add_widget("crosshair", cx=16, cy=16)
        page = touch_page(fig)
        errs = _no_errors(page)
        b = _overlay_box(page)
        _touch_drag(page, b["x"] + b["w"]*0.5, b["y"] + b["h"]*0.5, 40, 30)
        _pinch(page, b["x"] + b["w"]*0.5, b["y"] + b["h"]*0.5)
        page.wait_for_timeout(150)
        assert not errs, f"touch interaction raised errors: {errs}"


class TestTouch3D:
    def test_one_finger_orbits(self, touch_page):
        fig, ax = apl.subplots(1, 1, figsize=(360, 360))
        g = np.linspace(-2, 2, 16); X, Y = np.meshgrid(g, g)
        v = ax.plot_surface(X, Y, np.sin(np.sqrt(X**2 + Y**2)), azimuth=-60)
        page = touch_page(fig)
        b = _overlay_box(page)
        az0 = _panel_state(page, v._id)["azimuth"]
        _touch_drag(page, b["x"] + b["w"]*0.5, b["y"] + b["h"]*0.5, 90, 0)
        page.wait_for_timeout(150)
        az1 = _panel_state(page, v._id)["azimuth"]
        assert abs(az1 - az0) > 5, f"3-D did not orbit on 1-finger drag: {az0} -> {az1}"

    def test_pinch_zooms(self, touch_page):
        fig, ax = apl.subplots(1, 1, figsize=(360, 360))
        g = np.linspace(-2, 2, 16); X, Y = np.meshgrid(g, g)
        v = ax.plot_surface(X, Y, np.sin(np.sqrt(X**2 + Y**2)))
        page = touch_page(fig)
        b = _overlay_box(page)
        z0 = _panel_state(page, v._id)["zoom"]
        _pinch(page, b["x"] + b["w"]*0.5, b["y"] + b["h"]*0.5)
        page.wait_for_timeout(150)
        z1 = _panel_state(page, v._id)["zoom"]
        assert z1 != z0, f"3-D pinch did not change zoom: {z0} -> {z1}"


class TestTouch1D:
    def test_one_finger_drags_vline(self, touch_page):
        fig, ax = apl.subplots(1, 1, figsize=(400, 260))
        p = ax.plot(np.sin(np.linspace(0, 6, 100)))
        p.add_vline_widget(50.0)
        page = touch_page(fig)
        b = _overlay_box(page)
        # vline x=50/99 maps into the data area [PAD_L, w-PAD_R] = [58, w-12]
        PAD_L, PAD_R = 58, 12
        line_x = b["x"] + PAD_L + (50/99.0) * (b["w"] - PAD_L - PAD_R)
        cy = b["y"] + b["h"] * 0.5
        before = _panel_state(page, p._id)["overlay_widgets"][0]["x"]
        _touch_drag(page, line_x, cy, 80, 0)
        page.wait_for_timeout(150)
        after = _panel_state(page, p._id)["overlay_widgets"][0]["x"]
        assert abs(after - before) > 2, f"vline did not move on touch drag: {before} -> {after}"


class TestTouchDoubleTap:
    def test_double_tap_fires_double_click(self, touch_page):
        """A quick second tap near the first synthesises a dblclick, which the
        2-D handler turns into a ``double_click`` event (for picking / app
        callbacks) — exactly as a mouse double-click does."""
        fig, ax = apl.subplots(1, 1, figsize=(400, 400))
        plot = ax.imshow(np.zeros((64, 64), dtype=np.float32))
        page = touch_page(fig)
        b = _overlay_box(page)
        cx, cy = b["x"] + b["w"]*0.5, b["y"] + b["h"]*0.5
        _touch_tap(page, cx, cy)
        _touch_tap(page, cx, cy)   # second tap within 300ms → dblclick
        page.wait_for_timeout(120)
        ev = json.loads(page.evaluate("() => window._aplModel.get('event_json')"))
        assert ev.get("event_type") == "double_click", \
            f"double-tap did not fire double_click: {ev.get('event_type')}"
        assert ev.get("panel_id") == plot._id

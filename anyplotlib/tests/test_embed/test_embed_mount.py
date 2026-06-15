"""
Playwright tests for the JS `mount()` embedding entry point.

These build a page that uses ONLY the public embedding contract — import
``figure_esm.js``, call ``mount(el, state, opts)`` — exactly as an Electron
app would.  No anywidget shim, no Jupyter, no `_repr_utils` template.
"""
from __future__ import annotations

import json
import pathlib
import tempfile

import numpy as np
import pytest

import anyplotlib as apl
from anyplotlib.embed import esm_path, figure_state

_MOUNT_PAGE = """<!DOCTYPE html>
<html><head><meta charset="utf-8"/>
<style>html,body{margin:0;padding:0;}</style></head>
<body><div id="host"></div>
<script type="module">
const STATE = __STATE__;
const esmSource = __ESM__;
const blobUrl = URL.createObjectURL(new Blob([esmSource], {type: "text/javascript"}));
window._events = [];
window._syncs  = [];
import(blobUrl).then(mod => {
  window._handle = mod.mount(document.getElementById("host"), STATE, {
    onEvent: (ev) => window._events.push(ev),
    onSync:  (key, value) => window._syncs.push({key, value}),
  });
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


def _fig_with_image():
    fig, ax = apl.subplots(1, 1, figsize=(400, 300))
    q = np.linspace(0, 10, 32)
    plot = ax.imshow(np.random.default_rng(0).random((32, 32)), axes=[q, q])
    return fig, plot


def _plot_canvas_ink(page) -> int:
    return page.evaluate("""() => {
        const c = document.querySelector('#host canvas');
        if (!c) return -1;
        const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
        let n = 0;
        for (let i = 3; i < d.length; i += 4) if (d[i] > 0) n++;
        return n;
    }""")


class TestMountRenders:
    def test_canvases_created_with_ink(self, mount_page):
        fig, _ = _fig_with_image()
        page = mount_page(fig)
        n_canvas = page.evaluate("() => document.querySelectorAll('#host canvas').length")
        assert n_canvas >= 3, f"expected canvas stack, got {n_canvas}"
        assert _plot_canvas_ink(page) > 1000, "image canvas has no rendered pixels"

    def test_multiple_mounts_one_page_mdi_style(self, mount_page):
        """Two figures in one page must not interfere (MDI sub-windows)."""
        fig, _ = _fig_with_image()
        page = mount_page(fig)
        # Mount a second, independent figure into a fresh container.
        fig2, _ = _fig_with_image()
        state2 = json.dumps(figure_state(fig2))
        page.evaluate(f"""() => {{
            const div = document.createElement('div');
            div.id = 'host2';
            document.body.appendChild(div);
            const esm = {json.dumps(esm_path().read_text(encoding="utf-8"))};
            const blobUrl = URL.createObjectURL(new Blob([esm], {{type:'text/javascript'}}));
            return import(blobUrl).then(mod => {{
                window._handle2 = mod.mount(div, {state2}, {{}});
            }});
        }}""")
        page.wait_for_function("() => window._handle2 !== undefined", timeout=15_000)
        n1 = page.evaluate("() => document.querySelectorAll('#host canvas').length")
        n2 = page.evaluate("() => document.querySelectorAll('#host2 canvas').length")
        assert n1 >= 3 and n2 >= 3

    def test_dispose_clears_dom(self, mount_page):
        fig, _ = _fig_with_image()
        page = mount_page(fig)
        page.evaluate("() => window._handle.dispose()")
        n = page.evaluate("() => document.querySelectorAll('#host canvas').length")
        assert n == 0


class TestMountLiveUpdates:
    def test_set_panel_state_rerenders(self, mount_page):
        """setPanelState() with a new title must draw title pixels."""
        fig, plot = _fig_with_image()
        page = mount_page(fig)

        def title_ink():
            return page.evaluate("""() => {
                const tc = Array.from(document.querySelectorAll('#host canvas'))
                                .find(c => c.style.zIndex === '8');
                if (!tc) return -1;
                const d = tc.getContext('2d').getImageData(0,0,tc.width,tc.height).data;
                let n = 0;
                for (let i = 3; i < d.length; i += 4) if (d[i] > 0) n++;
                return n;
            }""")

        assert title_ink() == 0
        new_state = {**plot.to_state_dict(), "title": "Live from JS"}
        page.evaluate(
            "(args) => window._handle.setPanelState(args[0], args[1])",
            [plot._id, new_state],
        )
        page.wait_for_timeout(150)
        assert title_ink() > 0, "setPanelState() did not re-render the title"

    def test_apply_update_does_not_echo(self, mount_page):
        """applyUpdate() (Python → JS path) must not bounce back via onSync."""
        fig, plot = _fig_with_image()
        page = mount_page(fig)
        new_state = json.dumps({**plot.to_state_dict(), "title": "no echo"})
        page.evaluate(
            "(args) => window._handle.applyUpdate('panel_' + args[0] + '_json', args[1])",
            [plot._id, new_state],
        )
        page.wait_for_timeout(100)
        syncs = page.evaluate("() => window._syncs.map(s => s.key)")
        assert f"panel_{plot._id}_json" not in syncs


class TestMountEvents:
    def test_pointer_event_reaches_onevent_and_onsync(self, mount_page):
        fig, plot = _fig_with_image()
        page = mount_page(fig)
        # Click the centre of the image area.
        page.mouse.move(200, 150)
        page.mouse.down()
        page.mouse.up()
        page.wait_for_timeout(200)

        events = page.evaluate("() => window._events")
        assert any(e.get("event_type") == "pointer_down" for e in events), (
            f"no pointer_down in onEvent stream: {[e.get('event_type') for e in events]}"
        )
        assert all(e.get("panel_id") == plot._id
                   for e in events if "panel_id" in e)
        syncs = page.evaluate("() => window._syncs.map(s => s.key)")
        assert "event_json" in syncs, "event_json was not flushed through onSync"


class TestBridgeRoundTrip:
    """End-to-end Level-3 pattern: mount() in a real browser wired to a live
    Python FigureBridge, with the test harness acting as the transport
    (in an Electron app this would be a WebSocket / IPC pipe)."""

    def test_full_round_trip(self, mount_page):
        from anyplotlib.embed import FigureBridge

        fig, plot = _fig_with_image()
        clicks = []

        @plot.add_event_handler("pointer_down")
        def on_click(event):
            clicks.append((event.xdata, event.ydata))

        outbound = []   # Python → JS queue
        bridge = FigureBridge(fig, send=lambda k, v: outbound.append((k, v)))
        page = mount_page(fig)

        # ── JS → Python: click in the browser, pump onSync into the bridge ──
        page.mouse.move(200, 150)
        page.mouse.down()
        page.mouse.up()
        page.wait_for_timeout(200)
        for s in page.evaluate("() => window._syncs"):
            bridge.receive(s["key"], s["value"])
        assert clicks, "browser click did not reach the Python callback"
        assert clicks[0][0] is not None, "event lost its data coordinates"

        # ── Python → JS: set_title streams back into rendered pixels ──
        outbound.clear()
        plot.set_title("From Python")
        assert outbound, "Python mutation produced no bridge messages"
        for k, v in outbound:
            page.evaluate("(a) => window._handle.applyUpdate(a[0], a[1])", [k, v])
        page.wait_for_timeout(150)
        title_ink = page.evaluate("""() => {
            const tc = Array.from(document.querySelectorAll('#host canvas'))
                            .find(c => c.style.zIndex === '8');
            if (!tc) return -1;
            const d = tc.getContext('2d').getImageData(0,0,tc.width,tc.height).data;
            let n = 0;
            for (let i = 3; i < d.length; i += 4) if (d[i] > 0) n++;
            return n;
        }""")
        assert title_ink > 0, "Python set_title did not render in the browser"
        bridge.close()

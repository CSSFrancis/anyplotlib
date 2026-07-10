"""First-paint race — a pixel frame that ARRIVES BEFORE ``render()`` must still
paint on the FIRST draw, not leave the panel permanently blank.

The bug
-------
Every SpyDE figure iframe loads its anywidget ESM via an async
``import(blobUrl)``; ``render()`` (which registers the panel's
``model.on('change:panel_<id>_geom', …)`` listeners) therefore runs on a LATER
microtask than the synchronously-registered ``window.addEventListener('message')``
handler. If the FIRST real pixel push lands in that gap:

* **binary transport** — the raw uint8 bytes are stashed in the global
  ``__apl_pixbytes`` side-table (the model can't carry a ``Uint8Array``) and a
  tiny token trait is ``set()``. With no listener registered yet, nothing
  consumes the bytes; and the panel's INITIAL paint only parses the slimmed geom
  JSON (LUT/flags), which does NOT contain the bytes — so the frame is stranded
  in the side-table and the panel stays permanently blank.
* **base64 transport** — the pixels ride the ``panel_<id>_geom`` JSON. If that
  trait arrived before render, the initial ``_loadGeom`` DOES pick it up; this
  test also guards that path so a future refactor can't regress it.

The fix (figure_esm ``_spliceBinaryBytes`` + its call at panel-init) makes the
initial paint consume any already-arrived binary side-table bytes, mirroring
what the change listener would have done.

The test drives the ORDER deterministically (it does NOT try to win a real
race): render is gated behind ``window.__aplTestGate``; the test dispatches the
pixel ``message`` event FIRST (exactly as the parent bridge would), THEN releases
render, then asserts the canvas painted the delivered frame (non-blank + the
right brightness). The Canvas2D fallback path is exercised (the splice is
GPU-independent), so it runs in Playwright's WebGPU-less Chromium.
"""
from __future__ import annotations

import base64
import json
import pathlib
import tempfile

import numpy as np

import anyplotlib as apl


FIG_W, FIG_H = 240, 240
N = 128  # small → plain Canvas2D blit path (no tile, no GPU dependence)


def _bright_frame() -> np.ndarray:
    """A frame that is BRIGHT on the right half, dark on the left — an easy,
    unambiguous non-blank signature (mean brightness well above zero, and a
    left/right asymmetry a blank panel can't fake)."""
    img = np.zeros((N, N), dtype=np.float32)
    img[:, N // 2:] = 1.0
    return img


def _gate_html(fig, *, strip_pixels: bool) -> str:
    """Return build_standalone_html output, but:

    * gate ``renderFn`` behind a promise the test resolves (``__aplTestGate``),
      exposing ``window.__aplReleaseRender()`` to release it;
    * expose ``window._aplModel`` for probing;
    * when ``strip_pixels`` is set, blank out the pixel value in the baked-in
      initial STATE's geom trait so the ONLY pixels the panel can show are the
      ones the test delivers via the message handler before render — i.e. the
      first real paint truly arrives in the pre-render gap.
    """
    from anyplotlib._repr_utils import build_standalone_html

    html = build_standalone_html(fig, resizable=False)

    # Gate render behind a promise the test controls: turn the import handler
    # ``async`` and ``await`` the gate before calling renderFn. The message
    # listener (registered synchronously below the import) is UNAFFECTED, so the
    # test can deliver a frame while render is still parked on the gate.
    assert "import(blobUrl).then(mod => {" in html, "template import shape changed"
    html = html.replace(
        "import(blobUrl).then(mod => {",
        "window.__aplTestGate = new Promise(res => "
        "{ window.__aplReleaseRender = res; });\n"
        "import(blobUrl).then(async mod => {\n"
        "  await window.__aplTestGate;",
    )
    html = html.replace(
        "const model   = makeModel(STATE);",
        "const model   = makeModel(STATE);\nwindow._aplModel = model;",
    )
    html = html.replace(
        "renderFn({ model, el });",
        "renderFn({ model, el }); window._aplReady = true;",
    )

    if strip_pixels:
        # Blank the pixels in every baked-in geom trait so the panel starts with
        # NOTHING to draw; the test then supplies the first frame pre-render.
        marker = "const STATE = "
        i = html.index(marker) + len(marker)
        j = html.index(";\n", i)
        state = json.loads(html[i:j])
        for k, v in list(state.items()):
            if k.startswith("panel_") and k.endswith("_geom") and isinstance(v, str):
                try:
                    geom = json.loads(v)
                except Exception:
                    continue
                for pk in ("image_b64", "overlay_mask_b64", "detail_b64"):
                    if pk in geom:
                        geom[pk] = ""
                state[k] = json.dumps(geom)
        html = html[:i] + json.dumps(state, default=str) + html[j:]

    return html


def _open(browser, html):
    with tempfile.NamedTemporaryFile(
        suffix=".html", mode="w", encoding="utf-8", delete=False
    ) as fh:
        fh.write(html)
        tmp = pathlib.Path(fh.name)
    page = browser.new_page()
    page.goto(tmp.as_uri())
    return page, tmp


def _panel_of(fig):
    """The 2-D image panel's id and its geom trait name."""
    p = next(iter(fig._plots_map.values()))
    return p._id, f"panel_{p._id}_geom"


def _geom_json_and_bytes(fig):
    """Push a bright frame and return (slim geom JSON with token, raw uint8
    bytes, real base64 geom JSON) — the wire forms of a single frame the way
    ``Figure._push`` / ``_electron._route_change`` produce them."""
    p = next(iter(fig._plots_map.values()))
    p.set_data(_bright_frame(), clim=(0.0, 1.0))
    state = p.to_state_dict()
    # Real base64 form (what a save_html / non-binary host would send inline).
    b64_state = p.resolve_pixel_tokens(dict(state))
    geom_keys = getattr(p, "_GEOM_KEYS", frozenset())
    geom_b64 = {k: b64_state[k] for k in geom_keys if k in b64_state}
    raw = geom_b64["image_b64"]
    raw_bytes = base64.b64decode(raw)
    # Slim geom (LUT kept, pixels → token) — the binary path's JSON companion.
    slim = dict(geom_b64)
    import zlib
    slim["image_b64"] = f"\x00bin:{zlib.adler32(raw_bytes) & 0xFFFFFFFF}"
    return json.dumps(slim), raw_bytes, json.dumps(geom_b64)


def _mean_brightness(page):
    """Mean of the first channel across the plot canvas (0..255). A blank panel
    reads ~0 (black background)."""
    return page.evaluate(
        """() => {
            const cvs = Array.from(document.querySelectorAll('canvas'));
            for (const c of cvs) {
                if (c.width < 8 || c.height < 8) continue;
                const ctx = c.getContext('2d');
                if (!ctx) continue;
                try {
                    const d = ctx.getImageData(0, 0, c.width, c.height).data;
                    let s = 0, n = 0;
                    for (let i = 0; i < d.length; i += 4) { s += d[i]; n++; }
                    if (n) return s / n;
                } catch (_) { /* tainted */ }
            }
            return -1;
        }"""
    )


class TestFirstPaintRace:
    def _run(self, browser, *, binary: bool):
        # Build the page from a BLANK figure (initial state has no real pixels),
        # so the ONLY path to a painted frame is the one delivered pre-render.
        fig, ax = apl.subplots(1, 1, figsize=(FIG_W, FIG_H))
        ax.imshow(np.zeros((N, N), dtype=np.float32), cmap="gray",
                  vmin=0.0, vmax=1.0, gpu=False)
        pid, geom_trait = _panel_of(fig)

        # A separate figure produces the FRAME to deliver (same panel id so the
        # geom trait name matches — imshow assigns ids deterministically).
        fig2, ax2 = apl.subplots(1, 1, figsize=(FIG_W, FIG_H))
        ax2.imshow(np.zeros((N, N), dtype=np.float32), cmap="gray",
                   vmin=0.0, vmax=1.0, gpu=False)
        pid2, geom_trait2 = _panel_of(fig2)
        assert geom_trait == geom_trait2, "panel ids diverged; test assumption broken"
        slim_json, raw_bytes, b64_json = _geom_json_and_bytes(fig2)

        html = _gate_html(fig, strip_pixels=True)
        page, tmp = _open(browser, html)
        try:
            # Wait until the message listener is registered (it is — synchronously
            # at module eval) but render is still GATED.
            page.wait_for_function(
                "() => typeof window.__aplReleaseRender === 'function'",
                timeout=15_000)
            # Sanity: render has NOT run yet.
            assert page.evaluate("() => !window._aplReady"), \
                "render ran before the gate released — ordering not controlled"

            # Deliver the FIRST frame BEFORE render, exactly as the parent bridge
            # does: dispatch the same `message` event the iframe host listens for.
            if binary:
                page.evaluate(
                    """([trait, geomJson, bytesArr]) => {
                        const buf = new Uint8Array(bytesArr).buffer;
                        // 1) the slimmed geom JSON (LUT/flags + token) …
                        window.dispatchEvent(new MessageEvent('message', {
                          data: { type: 'awi_state', key: trait, value: geomJson }}));
                        // 2) … then the raw pixel bytes on the binary channel.
                        window.dispatchEvent(new MessageEvent('message', {
                          data: { type: 'awi_state_binary', key: 'image_b64',
                                  header: { geom: trait }, buffer: buf }}));
                    }""",
                    [geom_trait, slim_json, list(raw_bytes)],
                )
            else:
                page.evaluate(
                    """([trait, geomJson]) => {
                        window.dispatchEvent(new MessageEvent('message', {
                          data: { type: 'awi_state', key: trait, value: geomJson }}));
                    }""",
                    [geom_trait, b64_json],
                )

            # NOW release render — its INITIAL paint must show the delivered frame.
            page.evaluate("() => window.__aplReleaseRender()")
            page.wait_for_function("() => window._aplReady === true", timeout=15_000)
            page.evaluate(
                "() => new Promise(r => requestAnimationFrame(() => "
                "requestAnimationFrame(r)))")

            diag = page.evaluate("(pid) => globalThis.__apl_panelDiag(pid)", pid)
            bright = _mean_brightness(page)
        finally:
            page.close()
            tmp.unlink(missing_ok=True)

        assert diag is not None, "panel diag missing — render did not build the panel"
        assert diag["bytesFp"], (
            f"binary={binary}: panel has NO pixel bytes after first paint — the "
            f"frame delivered before render was lost (diag={diag})")
        # The bright frame is half-white: mean of the first channel over the whole
        # canvas is well above zero. A blank (black) panel reads ~0.
        assert bright > 20.0, (
            f"binary={binary}: panel is blank on first paint (mean brightness "
            f"{bright:.1f}) — the pre-render frame never painted")

    def test_binary_frame_before_render(self, _pw_browser):
        """Binary PLOTBIN path: raw bytes in the side-table before render()."""
        self._run(_pw_browser, binary=True)

    def test_base64_frame_before_render(self, _pw_browser):
        """Base64 geom-JSON path: pixels in the geom trait before render()."""
        self._run(_pw_browser, binary=False)

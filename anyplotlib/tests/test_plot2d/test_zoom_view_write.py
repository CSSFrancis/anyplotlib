"""
Zoom/pan write payload — the light ``panel_<id>_json`` trait must NOT carry the
heavy geometry (pixels / colormap LUT) on interaction writes.

Regression guard for the zoom-lag bug: the wheel/pan handlers serialise the
panel state back to ``panel_<id>_json`` on every mouse tick. ``_applyGeom``
splices the cached geometry (``image_b64`` / ``colormap_data`` / the binary
``image_b64_bytes``) into ``p.state`` so the renderer can draw, which means a
naive ``JSON.stringify(p.state)`` re-serialises — and re-transmits — the whole
frame every tick. On the binary path that is ``JSON.stringify`` of a Uint8Array
(a ``{"0":..,"1":..}`` object with one key per byte), which stalls zoom on large
images. ``_viewStateJson`` strips the cached geom keys before serialising, and
the interaction handlers use it instead of ``JSON.stringify(p.state)``.

The geom split is GPU-independent, so Playwright's WebGPU-less Chromium
(Canvas2D fallback) exercises the exact same write path the GPU path uses.
"""
from __future__ import annotations

import json

import numpy as np

import anyplotlib as apl


_GEOM_KEYS = ("image_b64", "colormap_data", "overlay_mask_b64",
              "image_b64_bytes", "overlay_mask_b64_bytes")


def _big_image(n=512):
    # A ramp big enough that its base64 pixels dominate any view-state JSON.
    row = np.linspace(0, 1, n, dtype=np.float32)
    return np.tile(row, (n, 1))


class TestZoomViewWrite:
    def test_view_json_excludes_geometry_keys(self, interact_page):
        fig, ax = apl.subplots(1, 1, figsize=(300, 300))
        p = ax.imshow(_big_image(), cmap="viridis", gpu="auto")
        page = interact_page(fig)
        page.wait_for_timeout(200)

        raw = page.evaluate("(pid) => globalThis.__apl_viewStateJson(pid)", p._id)
        assert raw, "probe __apl_viewStateJson did not return the view JSON"
        view = json.loads(raw)

        # The exact string the wheel/pan handler writes per tick must NOT carry
        # any heavy geometry key.
        for k in _GEOM_KEYS:
            assert k not in view, f"geom key {k!r} leaked into the light view write"

        # …but it MUST still carry the view state the handler is persisting.
        assert "zoom" in view, "view state (zoom) missing from the light write"

    def test_view_json_is_much_smaller_than_full_state(self, interact_page):
        fig, ax = apl.subplots(1, 1, figsize=(300, 300))
        p = ax.imshow(_big_image(), cmap="viridis", gpu="auto")
        page = interact_page(fig)
        page.wait_for_timeout(200)

        dbg = page.evaluate(
            "(pid) => { globalThis.__apl_setZoom(pid, 2.0, 0.5, 0.5);"
            "           return globalThis.__apl_zoom_dbg; }",
            p._id,
        )
        assert dbg is not None, "probe did not run — __apl_setZoom missing?"
        # The full-state stringify (OLD path) carries the pixels; the view-only
        # stringify (NEW path) must be a small fraction of it.
        assert dbg["len"] > 10_000, (
            f"test image too small to be a meaningful guard (full len={dbg['len']})"
        )
        assert dbg["viewLen"] < dbg["len"] / 4, (
            "view-state JSON still carries geometry: "
            f"viewLen={dbg['viewLen']} vs full len={dbg['len']}"
        )

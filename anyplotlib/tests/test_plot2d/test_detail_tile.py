"""Detail-tile viewport LOD — a hi-res tile for a logical sub-region is sampled by
the renderer when the zoom window is inside it, so a zoom-in shows crisp native
pixels WITHOUT transferring the whole full-res frame.

Playwright's bundled Chromium has no WebGPU, so these exercise the Canvas2D path
(the GPU path mirrors the same _detailUV math and is verified in the app on real
hardware). We prove the tile is actually sampled by making the tile's content
DIFFERENT from the base in the same region: after zooming into the region the
visible pixels must reflect the TILE, not the base.
"""
from __future__ import annotations

import json
import numpy as np

import anyplotlib as apl


class TestDetailTileState:
    def test_set_detail_populates_state(self):
        fig, ax = apl.subplots(1, 1)
        p = ax.imshow(np.zeros((64, 64), np.float32), vmin=0, vmax=1, gpu=False)
        tile = np.ones((32, 32), np.float32)
        p.set_detail(tile, 16, 48, 16, 48)
        assert p._state["detail_region"] == [16, 48, 16, 48]
        assert p._state["detail_width"] == 32 and p._state["detail_height"] == 32
        assert p._state["detail_b64"]                     # binary token or base64
        p.set_detail(None)
        assert p._state["detail_b64"] == "" and p._state["detail_region"] == []

    def test_set_data_clears_stale_detail(self):
        fig, ax = apl.subplots(1, 1)
        p = ax.imshow(np.zeros((64, 64), np.float32), vmin=0, vmax=1, gpu=False)
        p.set_detail(np.ones((32, 32), np.float32), 16, 48, 16, 48)
        assert p._state["detail_b64"]
        p.set_data(np.zeros((64, 64), np.float32))
        assert p._state["detail_b64"] == "", "a new base frame must clear the detail"


class TestDetailSeqAndForcePlain:
    """Regressions for the SpyDE movie viewer: (1) a live scrub while zoomed in must
    bump detail_seq every push so the renderer re-uploads the re-sampled tile (else the
    zoomed-in view freezes on the first frame); (2) tile=False forces a plain full-frame
    push even for a large frame / an already-tiled plot (so a pre-decimated frame isn't
    auto-tiled at the wrong logical size)."""

    def test_detail_seq_advances_per_push(self):
        from anyplotlib.callbacks import Event
        p = apl.subplots(1, 1)[1].imshow(np.zeros((10, 10), np.float32))
        p.set_data(np.random.RandomState(0).rand(4096, 4096).astype(np.float32),
                   clim=(0, 1), tile=True)
        p.callbacks.fire(Event("view_changed", zoom=4.0, center_x=0.5, center_y=0.5,
                               display_width=1000, display_height=1000))
        reg = list(p._state["detail_region"])
        seqs = [p._state["detail_seq"]]
        # Scrub frames: SAME region (zoom unchanged), new data each time.
        for i in range(3):
            p.set_data(np.random.RandomState(10 + i).rand(4096, 4096).astype(np.float32),
                       clim=(0, 1), tile=True)
            assert list(p._state["detail_region"]) == reg      # region unchanged
            seqs.append(p._state["detail_seq"])
        assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs), (
            f"detail_seq must advance per push (JS dedup key) — freeze bug: {seqs}")

    def test_tile_false_forces_plain_on_large_frame(self):
        p = apl.subplots(1, 1)[1].imshow(np.zeros((10, 10), np.float32))
        # A large frame that WOULD auto-tile, but tile=False → plain full-res push.
        p.set_data(np.random.RandomState(0).rand(1366, 1366).astype(np.float32),
                   clim=(0, 1), tile=False)
        assert p._state["tile_enabled"] is False
        assert p._state["image_width"] == 1366 and p._state["base_width"] == 0

    def test_tile_false_tears_down_existing_tiling(self):
        p = apl.subplots(1, 1)[1].imshow(np.zeros((10, 10), np.float32))
        p.set_data(np.random.RandomState(0).rand(4096, 4096).astype(np.float32),
                   clim=(0, 1), tile=True)
        assert p._state["tile_enabled"] is True
        # Now a tile=False frame must LEAVE tile mode (plain push, base_width=0).
        p.set_data(np.random.RandomState(1).rand(800, 800).astype(np.float32),
                   clim=(0, 1), tile=False)
        assert p._state["tile_enabled"] is False
        assert p._state["image_width"] == 800 and p._state["base_width"] == 0


class TestOverviewStaleness:
    """A zoomed-in scrub refreshes ONLY the detail tile (the overview base isn't
    visible, so re-encoding it per frame is wasted work). But the base then holds
    the PRE-scrub frame — a zoom-out (or a pan past the tile edge) would flash old
    data. Contract: the skipped overview is marked stale and re-sampled ONCE on
    the next view settle, riding the same push as the detail/clear."""

    def _zoomed_scrubbed_plot(self):
        from anyplotlib.callbacks import Event
        p = apl.subplots(1, 1)[1].imshow(np.zeros((10, 10), np.float32))
        p.set_data(np.random.RandomState(0).rand(4096, 4096).astype(np.float32),
                   clim=(0, 1), tile=True)
        p.callbacks.fire(Event("view_changed", zoom=4.0, center_x=0.5, center_y=0.5,
                               display_width=1000, display_height=1000))
        assert list(p._state["detail_region"])          # zoomed in, tile shown
        base_tok = p._state["image_b64"]
        # Scrub while zoomed: only the detail refreshes; the base is untouched
        # (the optimisation) but must now be flagged stale.
        p.set_data(np.random.RandomState(7).rand(4096, 4096).astype(np.float32),
                   clim=(0, 1), tile=True)
        assert p._state["image_b64"] == base_tok, "overview must NOT re-encode per scrub frame"
        assert p._overview_stale is True
        return p, base_tok

    def test_zoom_out_after_zoomed_scrub_refreshes_overview(self):
        from anyplotlib.callbacks import Event
        p, base_tok = self._zoomed_scrubbed_plot()
        # Zoom out below the tile threshold: the tile clears AND the stale
        # overview re-samples from the CURRENT frame (no pre-scrub flash).
        p.callbacks.fire(Event("view_changed", zoom=1.0, center_x=0.5, center_y=0.5,
                               display_width=1000, display_height=1000))
        assert p._state["detail_b64"] == "" and p._state["detail_region"] == []
        assert p._state["image_b64"] != base_tok, (
            "stale overview survived zoom-out — the view flashes the pre-scrub frame")
        assert p._overview_stale is False

    def test_settle_while_zoomed_refreshes_stale_overview(self):
        from anyplotlib.callbacks import Event
        p, base_tok = self._zoomed_scrubbed_plot()
        # A pan settle while STILL zoomed: the margin around a partially-covering
        # tile shows the base, so the stale overview refreshes here too.
        p.callbacks.fire(Event("view_changed", zoom=4.0, center_x=0.3, center_y=0.6,
                               display_width=1000, display_height=1000))
        assert p._state["image_b64"] != base_tok
        assert p._overview_stale is False
        assert list(p._state["detail_region"])          # new tile also landed

    def test_zoom_out_without_scrub_keeps_overview(self):
        from anyplotlib.callbacks import Event
        p = apl.subplots(1, 1)[1].imshow(np.zeros((10, 10), np.float32))
        p.set_data(np.random.RandomState(0).rand(4096, 4096).astype(np.float32),
                   clim=(0, 1), tile=True)
        p.callbacks.fire(Event("view_changed", zoom=4.0, center_x=0.5, center_y=0.5,
                               display_width=1000, display_height=1000))
        base_tok = p._state["image_b64"]
        # No scrub happened → zoom-out must NOT pay an overview re-encode.
        p.callbacks.fire(Event("view_changed", zoom=1.0, center_x=0.5, center_y=0.5,
                               display_width=1000, display_height=1000))
        assert p._state["image_b64"] == base_tok
        assert p._state["detail_b64"] == ""


class TestDetailTileCanvasRender:
    def test_zoom_out_strict_visible_rect_clips_data_markers(self, interact_page):
        img = np.zeros((64, 64), np.float32)
        fig, ax = apl.subplots(1, 1, figsize=(300, 300))
        p = ax.imshow(img, cmap="gray", vmin=0.0, vmax=1.0, gpu=False)
        # Large radius at the image corner would bleed into the zoom-out margin
        # without strict clipping to the shrunken visible rect.
        p.add_circles([[0.0, 0.0]], name="edge", radius=18,
                      edgecolors="#ffffff", facecolors="#ffffff")
        page = interact_page(fig)
        page.wait_for_timeout(250)
        page.evaluate("(pid) => globalThis.__apl_setZoom(pid, 0.75, 0.5, 0.5)", p._id)
        page.wait_for_timeout(120)

        outside_alpha = page.evaluate(
            """(pid) => {
                const st = JSON.parse(globalThis.__apl_viewStateJson(pid));
                const c = Array.from(document.querySelectorAll('canvas'))
                    .find(x => x.style && x.style.zIndex === '6');
                if (!c) throw new Error('markers canvas not found');
                const ctx = c.getContext('2d');
                const d = ctx.getImageData(0, 0, c.width, c.height).data;
                const iw = st.image_width, ih = st.image_height;
                const z = st.zoom || 1;
                const s = Math.min(c.width / iw, c.height / ih);
                const fw = iw * s, fh = ih * s;
                let x = (c.width - fw) / 2, y = (c.height - fh) / 2;
                let w = fw, h = fh;
                if (z < 1) {
                    w = fw * z; h = fh * z;
                    x += (fw - w) / 2; y += (fh - h) / 2;
                }
                let out = 0;
                for (let py = 0; py < c.height; py++) {
                    for (let px = 0; px < c.width; px++) {
                        if (px >= x && px <= x + w && py >= y && py <= y + h) continue;
                        out += d[(py * c.width + px) * 4 + 3];
                    }
                }
                return out;
            }""",
            p._id,
        )
        assert outside_alpha == 0, (
            f"markers leaked outside strict zoom-out visible rect: outside alpha={outside_alpha}")

    def test_display_markers_allow_clip_opt_out(self, interact_page):
        img = np.zeros((64, 64), np.float32)
        fig, ax = apl.subplots(1, 1, figsize=(300, 300))
        p = ax.imshow(img, cmap="gray", vmin=0.0, vmax=1.0, gpu=False)
        # Display-space marker near canvas top-left (outside zoom-out visible rect).
        # clip_display=False keeps it visible as a HUD-style annotation.
        hud = p.add_circles([[8.0, 8.0]], name="hud", radius=10,
                            edgecolors="#ffffff", facecolors="#ffffff",
                            transform="display")
        hud.set(clip_display=False)
        page = interact_page(fig)
        page.wait_for_timeout(250)
        page.evaluate("(pid) => globalThis.__apl_setZoom(pid, 0.75, 0.5, 0.5)", p._id)
        page.wait_for_timeout(120)

        outside_alpha = page.evaluate(
            """(pid) => {
                const st = JSON.parse(globalThis.__apl_viewStateJson(pid));
                const c = Array.from(document.querySelectorAll('canvas'))
                    .find(x => x.style && x.style.zIndex === '6');
                if (!c) throw new Error('markers canvas not found');
                const ctx = c.getContext('2d');
                const d = ctx.getImageData(0, 0, c.width, c.height).data;
                const iw = st.image_width, ih = st.image_height;
                const z = st.zoom || 1;
                const s = Math.min(c.width / iw, c.height / ih);
                const fw = iw * s, fh = ih * s;
                let x = (c.width - fw) / 2, y = (c.height - fh) / 2;
                let w = fw, h = fh;
                if (z < 1) {
                    w = fw * z; h = fh * z;
                    x += (fw - w) / 2; y += (fh - h) / 2;
                }
                let out = 0;
                for (let py = 0; py < c.height; py++) {
                    for (let px = 0; px < c.width; px++) {
                        if (px >= x && px <= x + w && py >= y && py <= y + h) continue;
                        out += d[(py * c.width + px) * 4 + 3];
                    }
                }
                return out;
            }""",
            p._id,
        )
        assert outside_alpha > 0, (
            "display markers with clip_display=False should remain visible outside the "
            "strict zoom-out visible rect")

    def test_tile_pixels_show_when_zoomed_into_region(self, interact_page):
        # BASE = pure black everywhere. TILE = mid-gray left half, white right half.
        # If the renderer samples the tile in the zoomed region, the visible pixels
        # are gray/white (from the tile), NOT black (base). Distinct values make it
        # unambiguous which source is showing.
        base = np.zeros((64, 64), np.float32)          # base → black
        tile = np.full((32, 32), 0.5, np.float32)      # tile left half → mid gray
        tile[:, 16:] = 1.0                             # tile right half → white
        fig, ax = apl.subplots(1, 1, figsize=(300, 300))
        p = ax.imshow(base, cmap="gray", vmin=0.0, vmax=1.0, gpu=False)
        p.set_detail(tile, 16, 48, 16, 48)             # tile covers image region [16,48]²
        page = interact_page(fig)
        page.wait_for_timeout(300)

        state = json.loads(page.evaluate("(pid) => globalThis.__apl_viewStateJson(pid)", p._id))
        assert state.get("detail_region") == [16, 48, 16, 48]

        # Zoom to exactly the tile region: zoom=2, center (0.5,0.5) → visible window
        # = 32×32 image px centered → [16,48] → the whole tile fills the view.
        page.evaluate("(pid) => globalThis.__apl_setZoom(pid, 2.0, 0.5, 0.5)", p._id)
        page.wait_for_timeout(200)

        # Sample the largest canvas (the image) across a mid scanline: the image is
        # centered/letterboxed, so probe inside the fit-rect (0.2 and 0.8 of width).
        info = page.evaluate("""() => {
            const cs = Array.from(document.querySelectorAll('canvas'));
            const c = cs.sort((a,b)=>b.width*b.height-a.width*a.height)[0];
            const ctx = c.getContext('2d');
            const w = c.width, h = c.height, y = (h*0.5)|0;
            const left  = Array.from(ctx.getImageData((w*0.30)|0, y, 1, 1).data);
            const right = Array.from(ctx.getImageData((w*0.70)|0, y, 1, 1).data);
            return { left, right };
        }""")
        lval, rval = info["left"][0], info["right"][0]
        # Left = tile mid-gray (~128), right = tile white (~255); NOT black (base=0).
        assert lval > 60, f"tile left half not shown (got {lval}, base-black leak?)"
        assert rval > 200, f"tile right (white) half not shown (got {rval})"
        assert rval > lval + 60, f"tile gray/white split not visible: L={lval} R={rval}"

    def test_partial_cover_stitches_tile_over_base(self, interact_page):
        # ANTI-FLASH: when zoomed IN but the visible window is LARGER than the tile
        # region (the zoom-OUT transition state, before a wider tile arrives), the
        # crisp tile must still show OVER its region while the base fills the margin —
        # NOT snap entirely to the blurry base (the old jarring flash). Base = black,
        # tile = white: tile region reads white, the margin outside reads base-black.
        base = np.zeros((64, 64), np.float32)          # base → black
        tile = np.ones((32, 32), np.float32)           # tile → white
        fig, ax = apl.subplots(1, 1, figsize=(300, 300))
        p = ax.imshow(base, cmap="gray", vmin=0.0, vmax=1.0, gpu=False)
        p.set_detail(tile, 16, 48, 16, 48)             # tile covers image region [16,48]²
        page = interact_page(fig)
        page.wait_for_timeout(300)
        # Zoom=1.5 centered: visible window = 64/1.5 ≈ 43 px centered → [~10.7, 53.3],
        # which is LARGER than the tile region [16,48] → partial cover (the overlay
        # path, not _detailUV). Centre must be tile-white; the corners base-black.
        page.evaluate("(pid) => globalThis.__apl_setZoom(pid, 1.5, 0.5, 0.5)", p._id)
        page.wait_for_timeout(200)
        info = page.evaluate("""() => {
            const cs = Array.from(document.querySelectorAll('canvas'));
            const c = cs.sort((a,b)=>b.width*b.height-a.width*a.height)[0];
            const ctx = c.getContext('2d');
            const w = c.width, h = c.height;
            const center = Array.from(ctx.getImageData((w*0.5)|0, (h*0.5)|0, 1, 1).data);
            const corner = Array.from(ctx.getImageData((w*0.12)|0, (h*0.5)|0, 1, 1).data);
            return { center: center[0], corner: corner[0] };
        }""")
        # Centre is inside the tile region → crisp white tile shows (NOT base-black).
        assert info["center"] > 200, (
            f"tile not stitched over base at partial cover (flash bug): {info}")
        # The margin outside the tile region → base (black), proving it's a COMPOSITE
        # (base + tile), not the tile stretched over everything.
        assert info["corner"] < 80, (
            f"margin should show the base, not the tile: {info}")

    def test_detail_tile_renders_via_BINARY_transport(self, interact_page):
        # THE bug: under binary transport the detail tile's pixels arrive as
        # detail_b64_bytes (a Uint8Array) and detail_b64 (the base64 string) is ABSENT
        # from state. The render gates (_detailUV / _detailOverlayRect / _gpuUploadDetail)
        # must detect the tile via _hasDetail (bytes OR string) — gating on detail_b64
        # alone made binary transport NEVER draw the detail (only the blurry overview),
        # so a zoomed-in movie showed a low-res upscale. Here: base black, tile white;
        # inject the tile as BYTES ONLY (detail_b64 empty) and zoom in → must be white.
        base = np.zeros((64, 64), np.float32)
        tile = np.ones((32, 32), np.float32)           # white tile
        fig, ax = apl.subplots(1, 1, figsize=(300, 300))
        p = ax.imshow(base, cmap="gray", vmin=0.0, vmax=1.0, gpu=False)
        p.set_detail(tile, 16, 48, 16, 48)             # build the tile bytes
        st = p._state
        # The quantised uint8 bytes anyplotlib would ship on the binary channel.
        from anyplotlib._utils import _normalize_image
        u8, _, _ = _normalize_image(tile, clim=(0.0, 1.0))
        page = interact_page(fig)
        page.wait_for_timeout(300)
        # Inject EXACTLY like binary transport: detail_b64='' (absent), the pixels in
        # a detail_b64_bytes Uint8Array on the geomCache, and the small region/size
        # fields on the light state.
        page.evaluate("""(args) => {
            const [pid, bytes, reg, dw, dh] = args;
            const u8 = new Uint8Array(bytes);
            const gname = 'panel_'+pid+'_geom';
            let geom = {}; try { geom = JSON.parse(window._aplModel.get(gname)||'{}'); } catch(_){}
            delete geom.detail_b64;                       // binary strips the string
            window._aplModel.set(gname, JSON.stringify(geom));
            // Stash bytes the way the binary handler does (geomCache::detail_b64).
            (globalThis.__apl_pixbytes ||= {})[gname+'::detail_b64'] = u8;
            window._aplModel.set(gname+'::detail_b64', u8.length+':bintest');
            const raw = JSON.parse(window._aplModel.get('panel_'+pid+'_json'));
            raw.detail_b64 = '';                          // NO base64 string
            raw.detail_region = reg; raw.detail_width = dw; raw.detail_height = dh;
            raw.detail_seq = 1;
            window._aplModel.set('panel_'+pid+'_json', JSON.stringify(raw));
            globalThis.__apl_setZoom(pid, 2.0, 0.5, 0.5); // window ⊆ [16,48]
        }""", [p._id, list(int(b) for b in u8.tobytes()), [16, 48, 16, 48],
               int(st["detail_width"]), int(st["detail_height"])])
        page.wait_for_timeout(200)
        center = page.evaluate("""() => {
            const cs = Array.from(document.querySelectorAll('canvas'));
            const c = cs.sort((a,b)=>b.width*b.height-a.width*a.height)[0];
            const ctx = c.getContext('2d');
            return ctx.getImageData((c.width*0.5)|0, (c.height*0.5)|0, 1, 1).data[0];
        }""")
        assert center > 200, (
            f"detail tile from BINARY bytes did not render (got {center}, base-black "
            f"leaked — _hasDetail gate bug)")

    def test_zoomed_out_uses_base_not_tile(self, interact_page):
        # At zoom 1 (whole image visible), the window is NOT inside the tile region,
        # so the base is shown — the tile only kicks in when zoomed into its region.
        base = np.full((64, 64), 0.25, np.float32)
        tile = np.full((32, 32), 1.0, np.float32)   # very bright tile
        fig, ax = apl.subplots(1, 1, figsize=(300, 300))
        p = ax.imshow(base, cmap="gray", vmin=0.0, vmax=1.0, gpu=False)
        p.set_detail(tile, 16, 48, 16, 48)
        page = interact_page(fig)
        page.wait_for_timeout(300)
        # zoom 1 → full image visible → tile NOT active → center pixel ≈ base (dark).
        px = page.evaluate("""() => {
            const c = document.querySelector('canvas');
            const ctx = c.getContext('2d');
            return Array.from(ctx.getImageData((c.width*0.5)|0, (c.height*0.5)|0, 1, 1).data);
        }""")
        # base 0.25 on gray → ~64/255; the bright tile (255) must NOT be showing.
        assert sum(px[:3]) < 350, f"tile leaked at zoom-out: {px[:3]}"

    def test_tiled_contrast_windows_via_LUT_no_reencode(self, interact_page):
        # A contrast change on a TILED plot must re-window via the LUT ONLY (move
        # display_min/display_max over the fixed raw_min/raw_max band) — no pixel
        # re-encode/re-transfer (the lag bug). We prove the DISPLAY changes: a mid-
        # gray overview gets brighter when the display window narrows toward it, all
        # by pushing only display_min/display_max (the bytes stay resident).
        # Non-uniform data (a horizontal ramp 0→1) so the raw band is real; the
        # centre pixel sits at ~0.5. A tiled plot (>threshold).
        img = np.tile(np.linspace(0, 1, 2048, dtype=np.float32), (2048, 1))
        fig, ax = apl.subplots(1, 1, figsize=(300, 300))
        p = ax.imshow(img, cmap="gray", vmin=0.0, vmax=1.0, gpu=False)
        assert p._state["tile_enabled"] is True
        page = interact_page(fig)
        page.wait_for_timeout(300)
        sample = """() => {
            const cs = Array.from(document.querySelectorAll('canvas'));
            const c = cs.sort((a,b)=>b.width*b.height-a.width*a.height)[0];
            return c.getContext('2d').getImageData((c.width*0.5)|0,(c.height*0.5)|0,1,1).data[0];
        }"""
        before = page.evaluate(sample)
        # Move the display window IN-BROWSER (like the live model would on a contrast
        # drag) — only display_min/display_max change; the resident bytes + fixed
        # raw_min/raw_max band are untouched. The centre pixel must re-window via the
        # LUT (no pixel re-encode). Window → [0.5,1.0] puts the centre value (~0.5) at
        # the dark end.
        page.evaluate("""(pid) => {
            const key = 'panel_'+pid+'_json';
            const st = JSON.parse(window._aplModel.get(key));
            st.display_min = 0.5; st.display_max = 1.0;
            window._aplModel.set(key, JSON.stringify(st));
        }""", p._id)
        page.wait_for_timeout(150)
        after = page.evaluate(sample)
        assert abs(after - before) > 20, (
            f"tiled contrast did not change the display via LUT: {before}→{after}")

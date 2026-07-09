"""Tiled large-image imshow — end-to-end.

Python side (no browser): tile="auto" builds an overview base + logical dims, and
the INTERNAL view_changed handler samples a detail tile from the backend on zoom.
Browser side (Canvas2D — WebGPU absent headless): the overview base renders at zoom
1, and a detail tile (what the internal loop would send) renders crisp when zoomed
into its region. (The JS→Python→JS round trip needs a real kernel, so the browser
test injects the tile into state directly; the Python test above covers the loop.)
"""
import json
import base64
import numpy as np
import anyplotlib as apl

from anyplotlib.tests._png_utils import compare_arrays_exact


class TestTiledConstruction:
    def test_auto_engages_over_threshold(self):
        p = apl.subplots(1, 1)[1].imshow(np.zeros((2048, 2048), np.float32))
        st = p._state
        assert st["tile_enabled"] is True
        assert st["image_width"] == 2048 and st["image_height"] == 2048    # logical
        assert 0 < st["base_width"] <= 1024                                # overview
        assert st["base_width"] < st["image_width"]

    def test_auto_off_under_threshold(self):
        p = apl.subplots(1, 1)[1].imshow(np.zeros((512, 512), np.float32))
        assert p._state["tile_enabled"] is False
        assert p._state["base_width"] == 0

    def test_tile_false_forces_off(self):
        p = apl.subplots(1, 1)[1].imshow(np.zeros((4096, 4096), np.float32), tile=False)
        assert p._state["tile_enabled"] is False

    def test_internal_loop_sets_tile_on_zoom(self):
        from anyplotlib.callbacks import Event
        big = np.random.RandomState(0).rand(4096, 4096).astype(np.float32)
        p = apl.subplots(1, 1)[1].imshow(big, vmin=0, vmax=1)
        p.callbacks.fire(Event("view_changed", zoom=4.0, center_x=0.5, center_y=0.5,
                               display_width=1000, display_height=1000))
        x0, x1, y0, y1 = p._state["detail_region"]
        assert 1900 <= (x1 - x0) <= 2100          # 1024 visible × 2.0 over-fetch
        assert p._state["detail_width"] <= 1000    # capped to panel px
        # zoom out clears
        p.callbacks.fire(Event("view_changed", zoom=1.0, center_x=0.5, center_y=0.5))
        assert p._state["detail_region"] == []

    def test_update_tile_source_keeps_view_refreshes_pixels(self):
        # Live data: the source changes but zoom/subselection persist, and the
        # overview + current detail tile refresh from the new frame.
        from anyplotlib.callbacks import Event
        a = np.zeros((4096, 4096), np.float32)
        b = np.full((4096, 4096), 0.9, np.float32)
        b[1408:2688, 1408:2688] = 0.5
        p = apl.subplots(1, 1)[1].imshow(a, cmap="gray", vmin=0, vmax=1)
        p.callbacks.fire(Event("view_changed", zoom=4.0, center_x=0.5, center_y=0.5,
                               display_width=1000, display_height=1000))
        reg = list(p._state["detail_region"])
        zoom = p._state["zoom"]
        assert len(reg) == 4
        p.update_tile_source(b)                       # swap data
        assert list(p._state["detail_region"]) == reg  # region persisted
        assert p._state["zoom"] == zoom                 # zoom persisted
        x0, x1, y0, y1 = reg
        crop = p._tile_backend.sample(x0, x1, y0, y1, 100, 100, "mean")
        # backend swapped a→b: the region (2× over-fetch → [1024:3072]) mixes b's 0.9
        # background with its 0.5 centre patch, so the mean is well above a's all-zero.
        assert 0.5 <= float(crop.mean()) <= 0.9
        # no-arg form (backend already mutated its own source)
        p._tile_backend.set_array(a)
        p.update_tile_source()
        assert p._state["base_width"] > 0

    def test_update_tile_source_noop_when_not_tiled(self):
        p = apl.subplots(1, 1)[1].imshow(np.zeros((64, 64), np.float32))
        p.update_tile_source(np.ones((64, 64), np.float32))   # no crash, no-op

    def test_custom_backend_is_used(self):
        from anyplotlib.callbacks import Event
        from anyplotlib.plot2d._tile_backend import NumpyTileBackend

        calls = []

        class SpyBackend(NumpyTileBackend):
            def sample(self, x0, x1, y0, y1, out_w, out_h, method="mean"):
                calls.append((x0, x1, y0, y1, out_w, out_h, method))
                return super().sample(x0, x1, y0, y1, out_w, out_h, method)

        b = SpyBackend(np.random.RandomState(0).rand(4096, 4096).astype(np.float32))
        p = apl.subplots(1, 1)[1].imshow(b, tile=True, tile_backend=b, vmin=0, vmax=1)
        assert calls, "backend.sample not called for the overview"
        overview_call = calls[0]
        assert overview_call[6] == "mean", (
            f"overview must use mean integration by default, got {overview_call[6]!r}")
        calls.clear()
        p.callbacks.fire(Event("view_changed", zoom=4.0, center_x=0.5, center_y=0.5,
                               display_width=1000, display_height=1000))
        assert calls, "backend.sample not called on zoom (the seam works)"


class TestOverviewMethod:
    """overview_method selects how the base overview texture is integrated.

    Default is "mean" (consistent with detail tiles so sparse images don't
    shift on zoom-in).  "subsample" restores the old fast nearest-neighbour
    path for consumers that can't afford a full-frame area-mean."""

    def _spy_backend(self):
        from anyplotlib.plot2d._tile_backend import NumpyTileBackend
        calls = []

        class SpyBackend(NumpyTileBackend):
            def sample(self, x0, x1, y0, y1, out_w, out_h, method="mean"):
                calls.append(method)
                return super().sample(x0, x1, y0, y1, out_w, out_h, method)

        b = SpyBackend(np.random.RandomState(0).rand(2048, 2048).astype(np.float32))
        return b, calls

    def test_default_overview_method_is_mean(self):
        b, calls = self._spy_backend()
        apl.subplots(1, 1)[1].imshow(b, tile=True, tile_backend=b, vmin=0, vmax=1)
        assert calls, "backend.sample never called"
        assert calls[0] == "mean", (
            f"default overview_method must be 'mean', got {calls[0]!r}")

    def test_overview_method_subsample_opts_out(self):
        b, calls = self._spy_backend()
        apl.subplots(1, 1)[1].imshow(b, tile=True, tile_backend=b, vmin=0, vmax=1,
                                     overview_method="subsample")
        assert calls, "backend.sample never called"
        assert calls[0] == "subsample", (
            f"overview_method='subsample' must reach backend, got {calls[0]!r}")

    def test_enable_tile_overview_method_propagates(self):
        b, calls = self._spy_backend()
        p = apl.subplots(1, 1)[1].imshow(np.zeros((10, 10)), vmin=0, vmax=1)
        calls.clear()
        p.enable_tile(b, overview_method="subsample")
        assert calls, "backend.sample never called by enable_tile"
        assert calls[0] == "subsample", (
            f"enable_tile overview_method must reach backend, got {calls[0]!r}")

    def test_enable_tile_none_preserves_existing_overview_method(self):
        """enable_tile(overview_method=None) must not reset the stored method."""
        b, calls = self._spy_backend()
        p = apl.subplots(1, 1)[1].imshow(b, tile=True, tile_backend=b,
                                          overview_method="subsample",
                                          vmin=0, vmax=1)
        calls.clear()
        # Re-enable without passing overview_method — should still use subsample.
        p.enable_tile(b)
        assert calls, "backend.sample never called on re-enable"
        assert calls[0] == "subsample", (
            "enable_tile() without overview_method must preserve the existing "
            f"setting; got {calls[0]!r}")


class TestSetDataRespectsTiling:
    """set_data on a plot ALREADY in tile mode must route through the tile pipeline,
    not clobber it. Regression for: a live consumer (movie navigator) that calls
    set_data per frame saw the image shrink to the overview size + lose its zoom
    detail (flash / snap-back), because set_data wrote a full-res base frame and
    reset image_width while base_width still named the old overview."""

    def _tiled(self, val=0.2):
        big = np.full((4096, 4096), val, np.float32)
        return apl.subplots(1, 1)[1].imshow(big, cmap="gray", vmin=0, vmax=1)

    def test_set_data_keeps_logical_size_and_overview(self):
        p = self._tiled(0.2)
        assert p._state["tile_enabled"] is True
        base_w0 = p._state["base_width"]
        assert 0 < base_w0 < p._state["image_width"] == 4096
        # A new same-size frame via set_data must NOT reset image_width to the frame
        # size with a stale base_width — that mismatch is the "shrinks to 1k" bug.
        p.set_data(np.full((4096, 4096), 0.7, np.float32), clim=(0, 1))
        assert p._state["image_width"] == 4096 and p._state["image_height"] == 4096
        assert 0 < p._state["base_width"] < 4096      # still an overview, not full-res
        assert p._state["tile_enabled"] is True
        # overview pixels reflect the NEW frame (0.7 over [0,1] → mid-bright), proving
        # the tile source swapped rather than a stale base persisting.
        ov = p._tile_backend.sample(0, 4096, 0, 4096, 64, 64, "mean")
        assert 0.6 < float(ov.mean()) < 0.8

    def test_set_data_preserves_zoom_and_detail(self):
        from anyplotlib.callbacks import Event
        p = self._tiled(0.2)
        # The frontend writes zoom/center into state on a real zoom; emulate that so we
        # can assert set_data preserves it (headless callbacks.fire only sets the tile).
        p._state["zoom"], p._state["center_x"], p._state["center_y"] = 4.0, 0.5, 0.5
        p.callbacks.fire(Event("view_changed", zoom=4.0, center_x=0.5, center_y=0.5,
                               display_width=1000, display_height=1000))
        reg = list(p._state["detail_region"])
        zoom = p._state["zoom"]
        assert len(reg) == 4 and zoom == 4.0
        # set_data must keep the zoom AND refresh the SAME detail region (live update),
        # not clear it (which snaps the view back to the blurry overview).
        p.set_data(np.full((4096, 4096), 0.7, np.float32), clim=(0, 1))
        assert p._state["zoom"] == zoom
        assert list(p._state["detail_region"]) == reg
        assert p._state["detail_b64"], "detail tile was cleared (snap-back bug)"
        # and the detail pixels reflect the new frame
        x0, x1, y0, y1 = reg
        crop = p._tile_backend.sample(x0, x1, y0, y1, 64, 64, "mean")
        assert 0.6 < float(crop.mean()) < 0.8

    def test_set_data_applies_new_contrast(self):
        p = self._tiled(0.2)
        p.set_data(np.full((4096, 4096), 5.0, np.float32), clim=(0, 10))
        assert p._state["display_min"] == 0 and p._state["display_max"] == 10

    def test_set_data_shape_change_rederives_size(self):
        p = self._tiled(0.2)
        # A different-size frame (e.g. signal axes changed): image_width must follow
        # the NEW frame and tiling stay on.
        p.set_data(np.full((2048, 3072), 0.5, np.float32), clim=(0, 1))
        assert p._state["image_width"] == 3072 and p._state["image_height"] == 2048
        assert p._state["tile_enabled"] is True
        assert 0 < p._state["base_width"] < 3072

    def test_set_data_no_stray_full_res_in_base(self):
        # The base texture (image_b64) must stay overview-sized, never balloon to the
        # full 4096² (which is the whole point of tiling — no full-frame transfer).
        p = self._tiled(0.2)
        p.set_data(np.full((4096, 4096), 0.7, np.float32), clim=(0, 1))
        base_px = p._state["base_width"] * p._state["base_height"]
        assert base_px <= 1024 * 1024, "base grew to full-res — tiling bypassed"


class TestSetDataAutoEnablesTiling:
    """A live consumer (e.g. the SpyDE movie viewer) starts with a small placeholder
    imshow, then set_data's the real large frames. set_data must AUTO-ENABLE tile mode
    on the first frame past TILE_THRESHOLD — so the consumer never hand-rolls a
    backend / calls enable_tile. Regression for SpyDE's tile path diverging from the
    (fixed) set_data path."""

    def _small(self, n=10):
        return apl.subplots(1, 1)[1].imshow(np.zeros((n, n), np.float32))

    def test_large_frame_auto_enables(self):
        p = self._small()
        assert p._state["tile_enabled"] is False
        p.set_data(np.full((4096, 4096), 0.5, np.float32), clim=(0, 1))
        assert p._state["tile_enabled"] is True
        assert p._state["image_width"] == 4096
        assert 0 < p._state["base_width"] <= 1024
        assert p._tile_backend is not None

    def test_small_frame_stays_untiled(self):
        p = self._small()
        p.set_data(np.full((512, 512), 0.5, np.float32), clim=(0, 1))
        assert p._state["tile_enabled"] is False
        assert p._state["image_width"] == 512

    def test_auto_enable_uses_full_res_contrast(self):
        # No clim → the range comes from the full-res frame (native extremes), not the
        # overview mean, so a subsequent zoom tile doesn't blow out to white.
        p = self._small()
        rng = np.random.RandomState(0)
        p.set_data(rng.rand(4096, 4096).astype(np.float32))     # NO clim
        assert p._state["tile_enabled"] is True
        assert p._state["display_min"] < 0.05
        assert p._state["display_max"] > 0.95

    def test_tile_false_never_auto_enables(self):
        p = apl.subplots(1, 1)[1].imshow(np.zeros((10, 10), np.float32), tile=False)
        p.set_data(np.full((4096, 4096), 0.5, np.float32), clim=(0, 1))
        assert p._state["tile_enabled"] is False               # honoured tile=False
        assert p._state["image_width"] == 4096                  # plain full-res path


class TestTilePayloadParity:
    """Parity guards for scenes where tile=True should be byte-identical to plain."""

    @staticmethod
    def _decoded_u8(plot):
        st = plot.resolve_pixel_tokens(plot.to_state_dict())
        raw = base64.b64decode(st["image_b64"])
        arr = np.frombuffer(raw, dtype=np.uint8).reshape(
            st["image_height"], st["image_width"]
        )
        return arr

    def test_forced_tile_matches_plain_bytes_for_1024_frame(self):
        # 1024x1024 avoids overview decimation while still exercising tile=True.
        img = np.random.RandomState(0).rand(1024, 1024).astype(np.float32)
        plain = apl.subplots(1, 1)[1].imshow(
            img, cmap="gray", vmin=0.0, vmax=1.0, tile=False, gpu=False
        )
        tiled = apl.subplots(1, 1)[1].imshow(
            img, cmap="gray", vmin=0.0, vmax=1.0, tile=True, gpu=False
        )
        a = self._decoded_u8(plain)
        b = self._decoded_u8(tiled)
        ok, msg = compare_arrays_exact(a, b)
        assert ok, f"plain vs tiled payload mismatch: {msg}"

    def test_set_data_stays_identical_between_plain_and_tile(self):
        base = np.zeros((1024, 1024), np.float32)
        nxt = np.random.RandomState(1).rand(1024, 1024).astype(np.float32)
        plain = apl.subplots(1, 1)[1].imshow(
            base, cmap="gray", vmin=0.0, vmax=1.0, tile=False, gpu=False
        )
        tiled = apl.subplots(1, 1)[1].imshow(
            base, cmap="gray", vmin=0.0, vmax=1.0, tile=True, gpu=False
        )
        plain.set_data(nxt, clim=(0.0, 1.0), tile=False)
        tiled.set_data(nxt, clim=(0.0, 1.0), tile=True)
        a = self._decoded_u8(plain)
        b = self._decoded_u8(tiled)
        ok, msg = compare_arrays_exact(a, b)
        assert ok, f"set_data parity mismatch: {msg}"


class TestTiledRenderCanvas:
    def test_overview_base_renders(self, interact_page):
        # A tiled imshow renders SOMETHING (the overview) on the Canvas2D path.
        img = np.tile(np.linspace(0, 1, 2048, dtype=np.float32), (2048, 1))
        fig, ax = apl.subplots(1, 1, figsize=(300, 300))
        p = ax.imshow(img, cmap="gray", vmin=0, vmax=1, gpu=False)
        page = interact_page(fig)
        page.wait_for_timeout(300)
        state = json.loads(page.evaluate("(pid) => globalThis.__apl_viewStateJson(pid)", p._id))
        assert state.get("tile_enabled") is True
        assert state.get("base_width", 0) > 0 and state["base_width"] < state["image_width"]
        px = page.evaluate("""() => {
            const cs = Array.from(document.querySelectorAll('canvas'));
            const c = cs.sort((a,b)=>b.width*b.height-a.width*a.height)[0];
            const d = c.getContext('2d').getImageData((c.width*0.7)|0,(c.height*0.5)|0,1,1).data;
            return d[0];
        }""")
        assert px > 0, "overview base did not render"

    def test_injected_detail_tile_renders_crisp_when_zoomed(self, interact_page):
        # Logical 2048² tiled image; base overview is a flat gray. Inject a detail
        # tile (gray/white split) for a region + zoom in → the tile's split must show
        # (proves the base-overview + detail-tile compose correctly under tile mode).
        base = np.full((2048, 2048), 0.3, np.float32)
        fig, ax = apl.subplots(1, 1, figsize=(300, 300))
        p = ax.imshow(base, cmap="gray", vmin=0, vmax=1, gpu=False)
        page = interact_page(fig)
        page.wait_for_timeout(300)
        # Inject a detail tile covering logical [768:1280]² (a 512² region), with a
        # left-gray/right-white split, and zoom to it.
        tile = np.full((256, 256), 0.5, np.float32)
        tile[:, 128:] = 1.0
        p.set_detail(tile, 768, 1280, 768, 1280)
        # Push the injected state into the browser + zoom so the window ⊆ the region.
        # detail_b64 is a GEOM key now (rides panel_<id>_geom, spliced from geomCache),
        # so inject it into the geom trait — setting it on the light view trait would
        # be overwritten by _applyGeom from the (empty) geomCache. The small
        # region/width/height fields stay on the light view trait.
        st = p._state
        page.evaluate("""(args) => {
            const [pid, detail, geomExtra] = args;
            // Merge detail_b64 into the geom trait so geomCache picks it up.
            const gname = 'panel_'+pid+'_geom';
            let geom = {};
            try { geom = JSON.parse(window._aplModel.get(gname) || '{}'); } catch (_) {}
            Object.assign(geom, geomExtra);
            window._aplModel.set(gname, JSON.stringify(geom));
            const raw = JSON.parse(window._aplModel.get('panel_'+pid+'_json'));
            Object.assign(raw, detail);
            window._aplModel.set('panel_'+pid+'_json', JSON.stringify(raw));
            globalThis.__apl_setZoom(pid, 4.0, 0.5, 0.5);
        }""", [p._id,
               {"detail_region": st["detail_region"],
                "detail_width": st["detail_width"], "detail_height": st["detail_height"],
                "detail_seq": st.get("detail_seq", 1)},
               {"detail_b64": st["detail_b64"]}])
        page.wait_for_timeout(200)
        info = page.evaluate("""() => {
            const cs = Array.from(document.querySelectorAll('canvas'));
            const c = cs.sort((a,b)=>b.width*b.height-a.width*a.height)[0];
            const ctx = c.getContext('2d'); const w=c.width,h=c.height,y=(h*0.5)|0;
            return { left: ctx.getImageData((w*0.30)|0,y,1,1).data[0],
                     right: ctx.getImageData((w*0.70)|0,y,1,1).data[0] };
        }""")
        # tile right (white) is brighter than tile left, and BOTH are brighter than
        # the flat base overview (0.3 → ~77) — so the injected detail tile is showing,
        # not the base. (Exact values depend on where the split lands in the fit-rect.)
        assert info["right"] > info["left"] + 30, (
            f"detail tile split not visible over the overview: {info}")
        assert info["left"] > 100, f"tile not shown — base(0.3~77) leaked: {info}"

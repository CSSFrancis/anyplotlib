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

import pytest
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


class TestTileBandOnPlaceholder:
    """Tile mode entered on a FLAT placeholder (zeros, before real data exists) derives
    the fixed quantisation band raw_min/raw_max from that placeholder — a degenerate
    (0, 0) — and nothing re-derived it on a later set_data. The two ends of the
    protocol then DISAGREED about what (0, 0) means: the Python encoder treats a
    degenerate band as unset and quantises over the display window, while the JS LUT
    honoured it literally, mapping every code below the display floor — a solid black
    pane beside perfectly healthy stats, on the WebGPU and Canvas2D paths alike, with
    no warning anywhere. GH #60."""

    @staticmethod
    def _placeholder():
        return apl.subplots(1, 1)[1].imshow(np.zeros((2048, 2048), np.float32))

    @staticmethod
    def _frame(mean=140.0, sd=30.0):
        return np.random.RandomState(0).normal(
            mean, sd, (2048, 2048)).astype(np.float32)

    def test_placeholder_band_starts_degenerate(self):
        # The starting condition the bug needs — documents WHY the guard exists.
        p = self._placeholder()
        assert p._state["tile_enabled"] is True
        assert p._state["raw_min"] == p._state["raw_max"]

    def test_set_data_rederives_degenerate_band(self):
        p = self._placeholder()
        p.set_data(self._frame(), clim=(35.0, 240.0))
        lo, hi = p._state["raw_min"], p._state["raw_max"]
        assert hi > lo, "degenerate band survived set_data"
        # Derived from the real FRAME (a native subsample of it), not from the clim.
        assert lo < 140.0 < hi and (hi - lo) > 100.0
        assert (p._state["display_min"], p._state["display_max"]) == (35.0, 240.0)

    def test_update_tile_source_rederives_degenerate_band(self):
        # The other live seam — a host swapping the backing array directly. This is
        # what downstream had to work around by pinning _state["raw_min"/"raw_max"].
        p = self._placeholder()
        p.update_tile_source(self._frame())
        assert p._state["raw_max"] > p._state["raw_min"]

    def test_valid_band_is_never_rederived(self):
        # The band is fixed ON PURPOSE: a contrast change must re-window in the LUT
        # with no pixel re-encode or re-transfer. Only a DEGENERATE band may be
        # replaced — a frame with a different range must not move a healthy one.
        p = apl.subplots(1, 1)[1].imshow(self._frame())
        band = (p._state["raw_min"], p._state["raw_max"])
        p.set_data(self._frame(mean=900.0, sd=5.0))
        assert (p._state["raw_min"], p._state["raw_max"]) == band

    def test_still_flat_frame_leaves_band_unset(self):
        # No honest range to derive → the band stays degenerate and BOTH ends fall
        # back to the display window. That agreement is the other half of the fix.
        p = self._placeholder()
        p.set_data(np.full((2048, 2048), 7.0, np.float32), clim=(0.0, 10.0))
        assert p._state["raw_min"] == p._state["raw_max"]
        assert p._tile_quant_clim() == (0.0, 10.0)


class TestSetTileBand:
    """`set_tile_band` — the public way to PIN the quantisation band, so a host with a
    known honest range (camera bit depth, detector saturation) stops reaching into
    `_plot2d._state["raw_min"/"raw_max"]` + `update_tile_source()`. GH #60."""

    @staticmethod
    def _tiled():
        return apl.subplots(1, 1)[1].imshow(
            np.random.RandomState(0).rand(2048, 2048).astype(np.float32))

    def test_pins_band_and_reencodes(self):
        p = self._tiled()
        before = base64.b64decode(
            p.resolve_pixel_tokens(p.to_state_dict())["image_b64"])
        p.set_tile_band(-100.0, 1000.0)
        assert (p._state["raw_min"], p._state["raw_max"]) == (-100.0, 1000.0)
        after = base64.b64decode(
            p.resolve_pixel_tokens(p.to_state_dict())["image_b64"])
        # The band the renderer reads the bytes with changed, so the bytes must too —
        # a pinned band that didn't re-encode is exactly the disagreement of GH #60.
        assert after != before, "band pinned but pixels not re-encoded"

    def test_pinned_band_survives_set_data(self):
        # The point of pinning: a later frame must not move the contrast.
        p = self._tiled()
        p.set_tile_band(0.0, 4095.0)
        p.set_data(np.random.RandomState(1).rand(2048, 2048).astype(np.float32))
        assert (p._state["raw_min"], p._state["raw_max"]) == (0.0, 4095.0)

    def test_pinning_recovers_a_placeholder_born_plot(self):
        # A source whose frames are still flat has no range to auto-derive; pinning
        # is the only way to get an honest band before real content arrives.
        p = apl.subplots(1, 1)[1].imshow(np.zeros((2048, 2048), np.float32))
        assert p._state["raw_min"] == p._state["raw_max"]      # nothing to derive
        p.set_tile_band(0.0, 255.0)
        assert p._tile_quant_clim() == (0.0, 255.0)

    def test_rejects_degenerate_range(self):
        p = self._tiled()
        band = (p._state["raw_min"], p._state["raw_max"])
        with pytest.raises(ValueError, match="vmax > vmin"):
            p.set_tile_band(5.0, 5.0)
        assert (p._state["raw_min"], p._state["raw_max"]) == band   # unchanged

    def test_rejects_untiled_plot(self):
        p = apl.subplots(1, 1)[1].imshow(np.zeros((64, 64), np.float32))
        with pytest.raises(RuntimeError, match="requires tile mode"):
            p.set_tile_band(0.0, 1.0)


class TestTileBandRenderCanvas:
    """The black-pane half of GH #60 in a real browser: a panel whose quantisation
    band is degenerate must still render its image, not a solid black rectangle."""

    @staticmethod
    def _panel_px(page):
        """min / max / mean red channel over the centre of the largest canvas."""
        return page.evaluate("""() => {
            const cs = Array.from(document.querySelectorAll('canvas'));
            const c = cs.sort((a,b)=>b.width*b.height-a.width*a.height)[0];
            const d = c.getContext('2d').getImageData(0,0,c.width,c.height).data;
            let lo=255, hi=0, sum=0, n=0;
            for(let y=(c.height*0.35)|0; y<(c.height*0.65)|0; y++)
              for(let x=(c.width*0.35)|0; x<(c.width*0.65)|0; x++){
                const v=d[(y*c.width+x)*4];
                if(v<lo) lo=v; if(v>hi) hi=v; sum+=v; n++;
              }
            return {lo, hi, mean: sum/n};
        }""")

    def test_degenerate_band_renders_display_mapped_bytes(self, interact_page):
        # The band legitimately STAYS degenerate here (a flat frame has no honest
        # range to derive), so this exercises the JS fallback on its own. The encoder
        # quantises 7.0 over the display window (0, 10) → code 178; honouring (0, 0)
        # in the LUT maps that to t≈0.07 → near-black, the fallback to ≈178 (mid gray).
        fig, ax = apl.subplots(1, 1, figsize=(300, 300))
        p = ax.imshow(np.zeros((2048, 2048), np.float32), cmap="gray", gpu=False)
        p.set_data(np.full((2048, 2048), 7.0, np.float32), clim=(0.0, 10.0))
        page = interact_page(fig)
        page.wait_for_timeout(300)
        st = json.loads(
            page.evaluate("(pid) => globalThis.__apl_viewStateJson(pid)", p._id))
        assert st["raw_min"] == st["raw_max"], "precondition: band must be degenerate"
        px = self._panel_px(page)
        assert px["mean"] > 120, f"degenerate band rendered near-black: {px}"

    def test_real_frame_after_placeholder_renders(self, interact_page):
        # The reported end-to-end case: tile mode born on a zeros placeholder, then a
        # real frame. A horizontal ramp survives the overview mean-downsample and the
        # canvas rescale, so "shows structure" is testable, not just "isn't black".
        ramp = np.tile(np.linspace(35, 240, 2048, dtype=np.float32), (2048, 1))
        fig, ax = apl.subplots(1, 1, figsize=(300, 300))
        p = ax.imshow(np.zeros((2048, 2048), np.float32), cmap="gray", gpu=False)
        p.set_data(ramp, clim=(35.0, 240.0))
        page = interact_page(fig)
        page.wait_for_timeout(300)
        px = self._panel_px(page)
        assert px["mean"] > 60, f"panel rendered black: {px}"
        assert px["hi"] - px["lo"] > 30, f"panel rendered flat, no structure: {px}"


class TestTilePayloadParity:
    """Parity guards for scenes where tile=True should match plain.

    At CONSTRUCTION both paths quantise over the same range, so the payloads are
    byte-identical. After ``set_data`` they need not be: the tiled path quantises
    over the FIXED band (raw_min/raw_max, the full-res data range) so a contrast
    change re-windows in the LUT with no pixel re-encode, while the plain path
    quantises over the caller's clim. The bytes then carry different codes for the
    same value and the LUT reconciles them — so the invariant to guard there is
    what the viewer SEES, not the wire bytes."""

    @staticmethod
    def _display_idx(plot):
        """Colormap index each pixel resolves to — the JS `_rawBand` + `_buildLut32`
        (linear) pipeline in numpy, i.e. what actually reaches the screen."""
        st = plot._state
        lo, hi = st["raw_min"], st["raw_max"]
        if lo is None or hi is None:
            lo, hi = st["display_min"], st["display_max"]
        elif not hi > lo:
            # Degenerate band: unset in tile mode (bytes are display-mapped), a
            # constant-value marker on the plain path. Mirrors _rawBand exactly.
            lo, hi = ((st["display_min"], st["display_max"])
                      if st["tile_enabled"] else (lo, hi))
        dmin, dmax = st["display_min"], st["display_max"]
        val = lo + (np.arange(256) / 255) * ((hi - lo) or 1)
        t = (val - dmin) / ((dmax - dmin) or 1)
        lut = np.clip(np.round(t * 255), 0, 255).astype(np.uint8)
        return lut[TestTilePayloadParity._decoded_u8(plot)]

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

    @pytest.mark.parametrize("base_kind", ["zeros-placeholder", "real-data"])
    def test_set_data_displays_the_same_plain_and_tiled(self, base_kind):
        # Both bases matter: "real-data" gives the tiled plot a valid band up front,
        # "zeros-placeholder" a degenerate one that set_data must re-derive (GH #60).
        # Either way the two plots must SHOW the same image.
        base = (np.zeros((1024, 1024), np.float32) if base_kind == "zeros-placeholder"
                else np.random.RandomState(9).rand(1024, 1024).astype(np.float32))
        nxt = np.random.RandomState(1).rand(1024, 1024).astype(np.float32)
        plain = apl.subplots(1, 1)[1].imshow(
            base, cmap="gray", vmin=0.0, vmax=1.0, tile=False, gpu=False
        )
        tiled = apl.subplots(1, 1)[1].imshow(
            base, cmap="gray", vmin=0.0, vmax=1.0, tile=True, gpu=False
        )
        plain.set_data(nxt, clim=(0.0, 1.0), tile=False)
        tiled.set_data(nxt, clim=(0.0, 1.0), tile=True)
        # The tiled plot quantises over its band, the plain one over the clim, so the
        # wire bytes may disagree by a rounding step — but once each is read back
        # through its OWN band, the displayed intensities must agree.
        d = np.abs(self._display_idx(plain).astype(np.int16)
                   - self._display_idx(tiled).astype(np.int16))
        assert d.max() <= 1, (
            f"plain vs tiled display mismatch: max |diff| = {d.max()} colormap "
            f"steps over {d.size} px ({int((d > 1).sum())} px worse than rounding)")


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

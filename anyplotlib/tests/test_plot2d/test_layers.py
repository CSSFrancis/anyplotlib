"""Multi-image LAYERS for Plot2D — Python (no browser) contract.

Covers the state schema after add/set/set_data/remove, z-order, shape
validation, tile-mode guards (both directions), the binary-transport wire route
+ ``resolve_pixel_tokens`` (cold path materialisation), and ``figure_state``
inclusion. The browser-side compositing (blended pixels, exportPNG capture,
visibility toggle, live set_data) is covered by ``test_layers_playwright.py``.
"""
from __future__ import annotations

import base64
import json

import numpy as np
import pytest

import anyplotlib as apl
from anyplotlib._utils import _build_tint_lut
from anyplotlib.plot2d import Layer


def _imshow(n=32, val=0.0):
    fig, ax = apl.subplots(1, 1, figsize=(300, 300))
    p = ax.imshow(np.full((n, n), val, np.float32), cmap="gray", vmin=0, vmax=1,
                  gpu=False)
    return fig, p


class TestAddLayerState:
    def test_add_layer_returns_handle_and_records_state(self):
        _fig, p = _imshow()
        lyr = p.add_layer(np.ones((32, 32), np.float32), cmap="magma",
                          alpha=0.5, clim=(0, 1))
        assert isinstance(lyr, Layer)
        assert p.layers == [lyr]
        entries = p._state["layers"]
        assert len(entries) == 1
        e = entries[0]
        assert e["id"] == lyr.id
        assert e["cmap"] == "magma"
        assert e["alpha"] == 0.5
        assert e["visible"] is True
        assert e["width"] == 32 and e["height"] == 32
        assert (e["clim_min"], e["clim_max"]) == (0.0, 1.0)
        # Pixel bytes present: base64 in the entry (non-binary host).
        assert e["image_b64"] and not e["image_b64"].startswith("\x00bin:")
        # Colormap LUT baked in for the JS compositor.
        assert len(e["colormap_data"]) == 256

    def test_pixel_key_is_a_geom_key(self):
        _fig, p = _imshow()
        lyr = p.add_layer(np.ones((32, 32), np.float32))
        pk = p._layer_pixel_key(lyr.id)
        # The heavy layer pixels ride a dynamic geom key so Figure._push splits
        # them off the light view trait and the binary route ships them.
        assert pk in p._GEOM_KEYS
        assert pk in p.to_state_dict()

    def test_default_cmap_and_alpha(self):
        _fig, p = _imshow()
        lyr = p.add_layer(np.ones((32, 32), np.float32))
        assert lyr.cmap == "magma"
        assert lyr.alpha == 0.5
        assert lyr.visible is True

    def test_auto_clim_when_none(self):
        _fig, p = _imshow()
        data = np.linspace(0, 4, 32 * 32, dtype=np.float32).reshape(32, 32)
        lyr = p.add_layer(data, clim=None)
        assert lyr.clim == (0.0, 4.0)

    def test_add_layer_alpha_out_of_range_raises(self):
        _fig, p = _imshow()
        with pytest.raises(ValueError):
            p.add_layer(np.ones((32, 32), np.float32), alpha=1.5)


class TestTintLut:
    """_build_tint_lut: 256×4 clear→colour ramp from a hex string."""

    def test_rrggbb_rgb_constant_alpha_ramp(self):
        lut = _build_tint_lut("#ff9800")
        assert len(lut) == 256
        assert all(len(e) == 4 for e in lut)
        # RGB is the tint at EVERY entry; alpha is the linear 0→255 ramp.
        assert all(e[:3] == [255, 152, 0] for e in lut)
        assert [e[3] for e in lut] == list(range(256))
        assert lut[0] == [255, 152, 0, 0]      # transparent at low intensity
        assert lut[255] == [255, 152, 0, 255]  # opaque tint at high intensity

    def test_rgb_shorthand(self):
        assert _build_tint_lut("#f00")[255] == [255, 0, 0, 255]
        assert _build_tint_lut("#f00") == _build_tint_lut("#ff0000")

    def test_invalid_colour_raises(self):
        for bad in ("red", "#12345", "#gggggg", "", None, 42):
            with pytest.raises(ValueError):
                _build_tint_lut(bad)


class TestTint:
    """add_layer(tint=) / Layer.set(tint=) — the clear→colour ramp mode."""

    def test_add_layer_tint_records_state(self):
        _fig, p = _imshow()
        lyr = p.add_layer(np.ones((32, 32), np.float32), tint="#ff0000",
                          alpha=0.8, clim=(0, 1))
        e = p._state["layers"][0]
        assert e["tint"] == "#ff0000"
        assert lyr.tint == "#ff0000"
        # colormap_data is the 256×4 tint LUT, not the named-cmap LUT.
        assert e["colormap_data"] == _build_tint_lut("#ff0000")
        # cmap is retained (set(cmap=...) reverts to it) but display is tinted.
        assert e["cmap"] == "magma"

    def test_default_tint_none_keeps_cmap_lut(self):
        _fig, p = _imshow()
        lyr = p.add_layer(np.ones((32, 32), np.float32), cmap="magma")
        e = p._state["layers"][0]
        assert e["tint"] is None and lyr.tint is None
        # Named-cmap LUT entries stay 3-channel (today's behaviour).
        assert all(len(c) == 3 for c in e["colormap_data"])

    def test_add_layer_invalid_tint_raises_before_mutation(self):
        _fig, p = _imshow()
        with pytest.raises(ValueError):
            p.add_layer(np.ones((32, 32), np.float32), tint="not-a-colour")
        assert p.layers == [] and p._state.get("layers", []) == []

    def test_set_tint_switches_lut(self):
        _fig, p = _imshow()
        lyr = p.add_layer(np.ones((32, 32), np.float32), cmap="magma")
        lyr.set(tint="#00ff00")
        e = p._state["layers"][0]
        assert lyr.tint == "#00ff00"
        assert e["colormap_data"] == _build_tint_lut("#00ff00")

    def test_set_cmap_clears_tint(self):
        _fig, p = _imshow()
        lyr = p.add_layer(np.ones((32, 32), np.float32), tint="#ff0000")
        lyr.set(cmap="viridis")
        e = p._state["layers"][0]
        assert lyr.tint is None and e["tint"] is None
        assert all(len(c) == 3 for c in e["colormap_data"])
        assert e["cmap"] == "viridis"

    def test_set_cmap_and_tint_together_raises(self):
        _fig, p = _imshow()
        lyr = p.add_layer(np.ones((32, 32), np.float32))
        with pytest.raises(ValueError, match="not both"):
            lyr.set(cmap="viridis", tint="#ff0000")

    def test_set_tint_none_leaves_tint_unchanged(self):
        _fig, p = _imshow()
        lyr = p.add_layer(np.ones((32, 32), np.float32), tint="#ff0000")
        lyr.set(alpha=0.3)   # tint=None default — no change
        assert lyr.tint == "#ff0000"

    def test_tint_survives_figure_state(self):
        from anyplotlib.embed import figure_state
        fig, ax = apl.subplots(1, 1, figsize=(200, 200))
        p = ax.imshow(np.zeros((16, 16), np.float32), cmap="gray",
                      vmin=0, vmax=1, gpu=False)
        p.add_layer(np.full((16, 16), 0.7, np.float32), tint="#ff9800")
        st = figure_state(fig)
        pj = json.loads(st[f"panel_{p._id}_json"])
        assert pj["layers"][0]["tint"] == "#ff9800"
        assert pj["layers"][0]["colormap_data"][255] == [255, 152, 0, 255]


class TestZOrder:
    def test_layers_kept_in_add_order(self):
        _fig, p = _imshow()
        a = p.add_layer(np.ones((32, 32), np.float32), cmap="magma")
        b = p.add_layer(np.ones((32, 32), np.float32), cmap="viridis")
        c = p.add_layer(np.ones((32, 32), np.float32), cmap="plasma")
        assert [l.id for l in p.layers] == [a.id, b.id, c.id]
        assert [e["id"] for e in p._state["layers"]] == [a.id, b.id, c.id]

    def test_ids_unique(self):
        _fig, p = _imshow()
        ids = {p.add_layer(np.ones((32, 32), np.float32)).id for _ in range(5)}
        assert len(ids) == 5


class TestSet:
    def test_partial_update_each_field(self):
        _fig, p = _imshow()
        lyr = p.add_layer(np.ones((32, 32), np.float32), cmap="magma",
                          alpha=0.5, clim=(0, 1))
        lyr.set(cmap="viridis")
        assert lyr.cmap == "viridis"
        assert p._state["layers"][0]["colormap_data"][0] is not None
        lyr.set(alpha=0.9)
        assert lyr.alpha == 0.9
        lyr.set(visible=False)
        assert lyr.visible is False
        # unaffected fields unchanged
        assert lyr.cmap == "viridis" and lyr.alpha == 0.9

    def test_set_clim_requantises(self):
        _fig, p = _imshow()
        data = np.full((32, 32), 5.0, np.float32)
        lyr = p.add_layer(data, clim=(0, 10))
        tok0 = p._state["layers"][0]["image_b64"]
        lyr.set(clim=(0, 5))
        assert lyr.clim == (0.0, 5.0)
        tok1 = p._state["layers"][0]["image_b64"]
        # A value of 5 over [0,10] is code ~127; over [0,5] it's ~255 → the bytes
        # (and thus the base64 / token) must change.
        assert tok0 != tok1

    def test_set_alpha_out_of_range_raises(self):
        _fig, p = _imshow()
        lyr = p.add_layer(np.ones((32, 32), np.float32))
        with pytest.raises(ValueError):
            lyr.set(alpha=-0.1)

    def test_set_returns_self_for_chaining(self):
        _fig, p = _imshow()
        lyr = p.add_layer(np.ones((32, 32), np.float32))
        assert lyr.set(alpha=0.3).set(cmap="viridis") is lyr

    def test_set_clim_none_is_a_noop(self):
        """clim=None means 'leave unchanged' — NOT reset to auto. Regression
        guard for the (fixed) misleading docstring/behaviour gap."""
        _fig, p = _imshow()
        data = np.full((32, 32), 5.0, np.float32)
        lyr = p.add_layer(data, clim=(0, 10))
        tok0 = p._state["layers"][0]["image_b64"]
        lyr.set(clim=None)  # explicit no-op call
        assert lyr.clim == (0.0, 10.0)
        assert p._state["layers"][0]["image_b64"] == tok0

    def test_set_clim_auto_resets_to_data_range(self):
        """clim='auto' is the new sentinel: recompute the display range from
        the layer's CURRENT data min/max, discarding the previous explicit
        clim — the only way back to auto after an explicit clim was set."""
        _fig, p = _imshow()
        data = np.linspace(2.0, 6.0, 32 * 32, dtype=np.float32).reshape(32, 32)
        lyr = p.add_layer(data, clim=(0, 100))  # explicit clim, far from data range
        assert lyr.clim == (0.0, 100.0)
        tok_explicit = p._state["layers"][0]["image_b64"]

        lyr.set(clim="auto")
        assert lyr.clim == (pytest.approx(2.0), pytest.approx(6.0))
        # And the pixels were re-quantised (not just the metadata) — different
        # window means a different code for the same data.
        assert p._state["layers"][0]["image_b64"] != tok_explicit

    def test_set_clim_auto_matches_add_layer_auto(self):
        """clim='auto' after set(...) must reproduce exactly what add_layer's
        own clim=None auto-ranging would have produced for the same data."""
        _fig, p1 = _imshow()
        data = np.linspace(-3.0, 9.0, 32 * 32, dtype=np.float32).reshape(32, 32)
        lyr1 = p1.add_layer(data, clim=(0, 1))
        lyr1.set(clim="auto")

        _fig2, p2 = _imshow()
        lyr2 = p2.add_layer(data, clim=None)  # auto from creation

        assert lyr1.clim == lyr2.clim
        assert (p1._state["layers"][0]["image_b64"]
                == p2._state["layers"][0]["image_b64"])

    def test_set_clim_invalid_string_raises(self):
        _fig, p = _imshow()
        lyr = p.add_layer(np.ones((32, 32), np.float32))
        with pytest.raises(ValueError):
            lyr.set(clim="not-a-valid-sentinel")


class TestSetData:
    def test_set_data_swaps_pixels_one_push(self):
        _fig, p = _imshow()
        lyr = p.add_layer(np.zeros((32, 32), np.float32), clim=(0, 1))
        tok0 = p._state["layers"][0]["image_b64"]
        lyr.set_data(np.ones((32, 32), np.float32))
        tok1 = p._state["layers"][0]["image_b64"]
        assert tok0 != tok1
        assert p._state["layers"][0]["width"] == 32

    def test_set_data_keeps_clim_window(self):
        _fig, p = _imshow()
        lyr = p.add_layer(np.full((32, 32), 1.0, np.float32), clim=(0, 10))
        assert lyr.clim == (0.0, 10.0)
        lyr.set_data(np.full((32, 32), 2.0, np.float32))
        # The layer keeps its clim window across a live frame swap.
        assert lyr.clim == (0.0, 10.0)

    def test_set_data_auto_clim_tracks_frame(self):
        _fig, p = _imshow()
        lyr = p.add_layer(np.zeros((32, 32), np.float32), clim=None)
        lyr.set_data(np.linspace(0, 8, 32 * 32, np.float32).reshape(32, 32))
        assert lyr.clim == (0.0, 8.0)

    def test_set_data_shape_mismatch_raises(self):
        _fig, p = _imshow()
        lyr = p.add_layer(np.zeros((32, 32), np.float32))
        with pytest.raises(ValueError):
            lyr.set_data(np.zeros((16, 16), np.float32))


class TestShapeValidation:
    def test_wrong_shape_raises(self):
        _fig, p = _imshow(n=32)
        with pytest.raises(ValueError, match="does not match the base image"):
            p.add_layer(np.ones((16, 16), np.float32))

    def test_non_2d_raises(self):
        _fig, p = _imshow(n=32)
        with pytest.raises(ValueError):
            p.add_layer(np.ones((32, 32, 3), np.float32))


class TestRemove:
    def test_remove_via_handle(self):
        _fig, p = _imshow()
        lyr = p.add_layer(np.ones((32, 32), np.float32))
        pk = p._layer_pixel_key(lyr.id)
        lyr.remove()
        assert p.layers == []
        assert p._state["layers"] == []
        assert pk not in p.to_state_dict()
        # A removed layer's key drops out of _GEOM_KEYS.
        assert pk not in p._GEOM_KEYS

    def test_remove_via_plot(self):
        _fig, p = _imshow()
        lyr = p.add_layer(np.ones((32, 32), np.float32))
        p.remove_layer(lyr)
        assert p.layers == []

    def test_remove_only_targeted_layer(self):
        _fig, p = _imshow()
        a = p.add_layer(np.ones((32, 32), np.float32), cmap="magma")
        b = p.add_layer(np.ones((32, 32), np.float32), cmap="viridis")
        p.remove_layer(a)
        assert [l.id for l in p.layers] == [b.id]
        assert p._layer_pixel_key(a.id) not in p.to_state_dict()
        assert p._layer_pixel_key(b.id) in p.to_state_dict()

    def test_removed_handle_raises_on_use(self):
        _fig, p = _imshow()
        lyr = p.add_layer(np.ones((32, 32), np.float32))
        lyr.remove()
        with pytest.raises(ValueError):
            lyr.set(alpha=0.5)

    def test_double_remove_is_noop(self):
        _fig, p = _imshow()
        lyr = p.add_layer(np.ones((32, 32), np.float32))
        lyr.remove()
        lyr.remove()   # no crash


class TestTileGuards:
    def test_add_layer_on_tiled_plot_raises(self):
        fig, ax = apl.subplots(1, 1)
        p = ax.imshow(np.zeros((2048, 2048), np.float32), vmin=0, vmax=1, gpu=False)
        assert p._tile_on
        with pytest.raises(RuntimeError, match="tile mode"):
            p.add_layer(np.ones((2048, 2048), np.float32))

    def test_enable_tile_on_layered_plot_raises(self):
        _fig, p = _imshow(n=64)
        p.add_layer(np.ones((64, 64), np.float32))
        with pytest.raises(RuntimeError, match="image layers"):
            p.enable_tile(np.zeros((2048, 2048), np.float32))

    def test_set_data_tile_true_on_layered_raises(self):
        # Same-shape frame (2048x2048 base + layer, 2048x2048 new frame) so
        # this exercises ONLY the tile-mode guard, not the (separate) shape
        # guard from TestTileGuards/TestShapeChangeNoLayers below. tile=False
        # on construction keeps the base itself plain (not auto-tiled) so
        # add_layer is allowed.
        fig, ax = apl.subplots(1, 1, figsize=(300, 300))
        p = ax.imshow(np.zeros((2048, 2048), np.float32), cmap="gray",
                      vmin=0, vmax=1, gpu=False, tile=False)
        p.add_layer(np.ones((2048, 2048), np.float32))
        with pytest.raises(RuntimeError, match="image layers"):
            p.set_data(np.zeros((2048, 2048), np.float32), tile=True)

    def test_large_set_data_on_layered_stays_plain(self):
        # Same-shape (base already 2048x2048, above TILE_THRESHOLD) so the new
        # frame's shape matches — isolates the tile-auto-enable guard from the
        # shape guard. tile=False on construction keeps the base plain so
        # add_layer is allowed; the guard under test is set_data's OWN
        # auto-tile decision on a later call, not the constructor's.
        fig, ax = apl.subplots(1, 1, figsize=(300, 300))
        p = ax.imshow(np.zeros((2048, 2048), np.float32), cmap="gray",
                      vmin=0, vmax=1, gpu=False, tile=False)
        p.add_layer(np.ones((2048, 2048), np.float32))
        # A large frame that would normally auto-enable tiling must stay plain.
        p.set_data(np.full((2048, 2048), 0.5, np.float32))
        assert p._tile_on is False

    def test_shape_changing_set_data_on_layered_plot_raises(self):
        """A layer keeps the (H, W) it had at add_layer time; JS fits every
        layer's bitmap into the base image's CURRENT fit-rect, so a
        shape-changing base set_data would silently stretch a stale-sized
        layer over the new image. Must raise instead of corrupting."""
        _fig, p = _imshow(n=32)
        p.add_layer(np.ones((32, 32), np.float32))
        with pytest.raises(ValueError, match="image layers"):
            p.set_data(np.zeros((16, 16), np.float32))
        # And the plot's own image is untouched by the rejected call.
        assert p._state["image_width"] == 32
        assert p._state["image_height"] == 32

    def test_same_shape_set_data_on_layered_plot_is_fine(self):
        """The guard only fires on an actual shape CHANGE — same-size updates
        (the common live-update case) must keep working."""
        _fig, p = _imshow(n=32)
        p.add_layer(np.ones((32, 32), np.float32))
        p.set_data(np.full((32, 32), 0.5, np.float32))  # must not raise
        assert p._state["image_width"] == 32
        assert p._state["image_height"] == 32


class TestShapeChangeNoLayers:
    """A plain (layer-free) plot must always accept a shape-changing
    set_data and refresh image_width/image_height to the new frame size —
    the ValueError guard in TestTileGuards is layers-only."""

    def test_shape_changing_set_data_updates_image_dims(self):
        _fig, p = _imshow(n=32)
        assert p._state["image_width"] == 32
        assert p._state["image_height"] == 32
        p.set_data(np.zeros((16, 24), np.float32))
        assert p._state["image_height"] == 16
        assert p._state["image_width"] == 24


class TestBinaryTransportRoute:
    """The layer pixel bytes must travel over BOTH transports: base64-in-JSON and
    the Electron PLOTBIN binary path (dynamic layer_<id>_b64 keys)."""

    def test_binary_route_ships_layer_frame(self, monkeypatch):
        monkeypatch.setenv("APL_BINARY_TRANSPORT", "1")
        from anyplotlib import _electron

        fig, ax = apl.subplots(1, 1, figsize=(200, 200))
        p = ax.imshow(np.zeros((16, 16), np.float32), cmap="gray",
                      vmin=0, vmax=1, gpu=False)
        fid = _electron.register(fig)

        captured = {"bin": [], "txt": []}
        monkeypatch.setattr(_electron, "emit",
                            lambda o: captured["txt"].append(o))
        monkeypatch.setattr(_electron, "emit_binary",
                            lambda f, k, h, pl: captured["bin"].append((k, h, len(pl))))

        lyr = p.add_layer(np.full((16, 16), 0.7, np.float32),
                          cmap="magma", clim=(0, 1))
        pk = p._layer_pixel_key(lyr.id)
        # In binary mode the layer entry / top-level key hold a bin TOKEN, not b64.
        sd = p.to_state_dict()
        assert sd[pk].startswith("\x00bin:")
        assert (p._id, pk) in fig._raw_pixels

        # Drive the geom trait change the way Figure._push would, carrying the
        # slimmed geom with the layer token.
        gname = f"panel_{p._id}_geom"
        _electron._route_change(fid, gname, json.dumps({pk: sd[pk]}))
        keys = [k for (k, _h, _n) in captured["bin"]]
        assert pk in keys, f"layer pixel frame not shipped as binary ({keys})"
        # The binary frame header names the geom trait so the renderer routes it.
        hdr = next(h for (k, h, _n) in captured["bin"] if k == pk)
        assert hdr.get("geom") == gname

    def test_resolve_pixel_tokens_materialises_layers(self, monkeypatch):
        monkeypatch.setenv("APL_BINARY_TRANSPORT", "1")
        from anyplotlib import _electron

        fig, ax = apl.subplots(1, 1, figsize=(200, 200))
        p = ax.imshow(np.zeros((16, 16), np.float32), cmap="gray",
                      vmin=0, vmax=1, gpu=False)
        _electron.register(fig)
        lyr = p.add_layer(np.full((16, 16), 0.7, np.float32), clim=(0, 1))
        pk = p._layer_pixel_key(lyr.id)

        d = p.to_state_dict()
        assert d[pk].startswith("\x00bin:")           # token before resolve
        p.resolve_pixel_tokens(d)
        # After resolve the top-level key AND the entry mirror hold real base64.
        assert not d[pk].startswith("\x00bin:") and len(d[pk]) > 0
        entry = d["layers"][0]
        assert not entry["image_b64"].startswith("\x00bin:")
        assert entry["image_b64"] == d[pk]
        # And it decodes to 16*16 uint8 bytes.
        assert len(base64.b64decode(d[pk])) == 16 * 16


class TestFigureStateRoundTrip:
    def test_figure_state_includes_layers(self):
        from anyplotlib.embed import figure_state
        fig, ax = apl.subplots(1, 1, figsize=(200, 200))
        p = ax.imshow(np.zeros((16, 16), np.float32), cmap="gray",
                      vmin=0, vmax=1, gpu=False)
        lyr = p.add_layer(np.full((16, 16), 0.7, np.float32),
                          cmap="magma", alpha=0.5, clim=(0, 1))
        st = figure_state(fig)
        pj = json.loads(st[f"panel_{p._id}_json"])
        assert "layers" in pj and len(pj["layers"]) == 1
        assert pj["layers"][0]["cmap"] == "magma"
        # The layer's pixels are inline (base64) somewhere the JS can reach: either
        # the geom trait's top-level key or the entry mirror.
        gj = json.loads(st[f"panel_{p._id}_geom"])
        pk = p._layer_pixel_key(lyr.id)
        assert pk in gj or len(pj["layers"][0]["image_b64"]) > 0

    def test_save_html_self_contained(self, tmp_path):
        fig, ax = apl.subplots(1, 1, figsize=(200, 200))
        p = ax.imshow(np.zeros((16, 16), np.float32), cmap="gray",
                      vmin=0, vmax=1, gpu=False)
        p.add_layer(np.full((16, 16), 0.7, np.float32), clim=(0, 1))
        out = fig.save_html(tmp_path / "layered.html")
        html = out.read_text(encoding="utf-8")
        # No unresolved binary tokens leak into the standalone HTML.
        assert "\x00bin:" not in html

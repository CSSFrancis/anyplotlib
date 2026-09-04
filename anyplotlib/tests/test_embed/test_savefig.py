"""``Figure.savefig``.

``savefig`` drives the JavaScript renderer in a headless browser, so the
interesting assertions are the ones only Python can get wrong: panel selection,
whether the viewer's live view survives the round trip, and whether a tiled
plot's full-resolution data actually reaches the page.

That last one is the headline case — ``tile='auto'`` is the default and
``TILE_THRESHOLD`` is 1024, so any image worth a native export is tiled and the
browser holds only an overview.
"""
from __future__ import annotations

import numpy as np
import pytest

import anyplotlib as apl
from anyplotlib._export import MAX_NATIVE_PIXELS, _temporarily_untiled
from anyplotlib.tests._png_utils import decode_png

FIGW, FIGH = 320, 260


def _ramp(n):
    """0..255 horizontal ramp, tiled down the rows."""
    return np.tile(np.linspace(0, 255, n, dtype=np.uint8), (n, 1))


def _read(path):
    return decode_png(path.read_bytes())


# ══════════════════════════════════════════════════════════════════════════════
# The ordinary paths
# ══════════════════════════════════════════════════════════════════════════════

class TestSavefigBasics:
    def test_writes_a_png_of_the_figure_size(self, tmp_path):
        fig, ax = apl.subplots(1, 1, figsize=(FIGW, FIGH))
        ax.imshow(_ramp(48), cmap="viridis", tile=False)
        out = fig.savefig(tmp_path / "fig.png")

        assert out.exists() and out.stat().st_size > 0
        arr = _read(out)
        # figure + the 8 px grid padding on each side, at dpr 1
        assert arr.shape[1] == FIGW + 16, arr.shape
        assert arr.shape[0] == FIGH + 16, arr.shape

    def test_theme_override(self, tmp_path):
        fig, ax = apl.subplots(1, 1, figsize=(FIGW, FIGH))
        ax.imshow(_ramp(48), cmap="viridis", tile=False)
        light = _read(fig.savefig(tmp_path / "l.png", theme="light"))
        dark = _read(fig.savefig(tmp_path / "d.png", theme="dark"))

        assert tuple(light[2, 2, :3]) == (0xF0, 0xF0, 0xF0), light[2, 2, :3]
        assert tuple(dark[2, 2, :3]) == (0x1E, 0x1E, 0x2E), dark[2, 2, :3]

    def test_panel_export_is_smaller_than_the_figure(self, tmp_path):
        fig, axes = apl.subplots(1, 2, figsize=(520, 240))
        p0 = axes[0].imshow(_ramp(48), cmap="viridis", tile=False)
        axes[1].imshow(_ramp(48), cmap="magma", tile=False)

        whole = _read(fig.savefig(tmp_path / "w.png"))
        one = _read(fig.savefig(tmp_path / "p.png", panel=p0))
        assert one.shape[1] < whole.shape[1], (one.shape, whole.shape)

    def test_panel_accepts_a_panel_id(self, tmp_path):
        fig, ax = apl.subplots(1, 1, figsize=(FIGW, FIGH))
        plot = ax.imshow(_ramp(48), tile=False)
        out = fig.savefig(tmp_path / "byid.png", panel=plot._id)
        assert out.exists()

    @pytest.mark.parametrize("kwargs,msg", [
        ({"source": "sideways"}, "source must be"),
        ({"theme": "chartreuse"}, "theme must be"),
    ])
    def test_bad_arguments_are_rejected(self, tmp_path, kwargs, msg):
        fig, ax = apl.subplots(1, 1, figsize=(FIGW, FIGH))
        ax.imshow(_ramp(16), tile=False)
        with pytest.raises(ValueError, match=msg):
            fig.savefig(tmp_path / "x.png", **kwargs)

    def test_unknown_panel_is_rejected(self, tmp_path):
        fig, ax = apl.subplots(1, 1, figsize=(FIGW, FIGH))
        ax.imshow(_ramp(16), tile=False)
        with pytest.raises(ValueError, match="no panel with id"):
            fig.savefig(tmp_path / "x.png", panel="nope")


# ══════════════════════════════════════════════════════════════════════════════
# source='native'
# ══════════════════════════════════════════════════════════════════════════════

class TestSavefigNative:
    def test_native_is_the_data_resolution(self, tmp_path):
        fig, ax = apl.subplots(1, 1, figsize=(FIGW, FIGH))
        plot = ax.imshow(_ramp(64), cmap="gray", vmin=0, vmax=255, tile=False)
        arr = _read(fig.savefig(tmp_path / "n.png", source="native", panel=plot))
        assert arr.shape[1] == 64, arr.shape
        assert arr.shape[0] == 64 + 12, arr.shape       # + the title strip

    def test_native_picks_the_only_2d_panel_without_panel_arg(self, tmp_path):
        fig, ax = apl.subplots(1, 1, figsize=(FIGW, FIGH))
        ax.imshow(_ramp(64), cmap="gray", tile=False)
        arr = _read(fig.savefig(tmp_path / "n.png", source="native"))
        assert arr.shape[1] == 64, arr.shape

    def test_native_on_a_multi_panel_figure_needs_panel(self, tmp_path):
        fig, axes = apl.subplots(1, 2, figsize=(520, 240))
        axes[0].imshow(_ramp(32), tile=False)
        axes[1].imshow(_ramp(32), tile=False)
        with pytest.raises(ValueError, match="panel="):
            fig.savefig(tmp_path / "n.png", source="native")

    def test_native_on_a_tiled_plot_is_full_resolution(self, tmp_path):
        """The headline case: a 1200 px image auto-tiles, so the browser holds
        only a downsampled overview.  savefig must re-encode the backend at full
        resolution.

        The probe is a one-pixel-period vertical stripe pattern — the overview
        is built by *averaging* blocks of source pixels, so it renders as a flat
        mid-grey.  Only genuinely full-resolution pixels alternate 0/255 column
        by column, which makes this a sharp discriminator (a ramp is not: at
        1200 px it only has 256 grey levels, so long constant runs are ordinary
        quantisation)."""
        n = 1200
        stripes = np.zeros((n, n), dtype=np.float32)
        stripes[:, 1::2] = 255.0
        fig, ax = apl.subplots(1, 1, figsize=(FIGW, FIGH))
        plot = ax.imshow(stripes, cmap="gray", vmin=0, vmax=255)
        assert plot.to_state_dict()["tile_enabled"], (
            "test premise broken: a 1200 px image should auto-enable tiling")

        arr = _read(fig.savefig(tmp_path / "big.png", source="native", panel=plot))
        assert arr.shape[1] == n, f"native export is {arr.shape[1]} px wide, want {n}"

        row = arr[-4, :n, 0].astype(int)          # inside the image, grayscale
        dark = row[0::2]
        light = row[1::2]
        assert dark.max() < 40, (
            f"even columns should be black, max is {dark.max()} — the export is "
            "an averaged overview, not the full-resolution data")
        assert light.min() > 215, (
            f"odd columns should be white, min is {light.min()} — the export is "
            "an averaged overview, not the full-resolution data")

    def test_native_on_a_tiled_plot_beats_the_view_export(self, tmp_path):
        """The same stripes exported as 'view' go through the overview and land
        on a much smaller canvas — the contrast between the two is the whole
        reason source='native' exists."""
        n = 1200
        stripes = np.zeros((n, n), dtype=np.float32)
        stripes[:, 1::2] = 255.0
        fig, ax = apl.subplots(1, 1, figsize=(FIGW, FIGH))
        plot = ax.imshow(stripes, cmap="gray", vmin=0, vmax=255)

        view = _read(fig.savefig(tmp_path / "v.png", panel=plot))
        native = _read(fig.savefig(tmp_path / "n.png", source="native", panel=plot))
        assert native.shape[1] > view.shape[1] * 3, (
            f"native {native.shape[1]} px vs view {view.shape[1]} px — native "
            "should be far larger for a 1200 px source in a 320 px figure")

    def test_untiling_restores_the_live_plot(self):
        """_temporarily_untiled edits the panel state in place; every key it
        touches must be back afterwards or the live figure would be corrupted."""
        fig, ax = apl.subplots(1, 1, figsize=(FIGW, FIGH))
        plot = ax.imshow(_ramp(1200).astype(np.float32), cmap="gray")
        before = dict(plot._state)
        before_tile_on = plot._tile_on

        with _temporarily_untiled(plot):
            assert plot._state["tile_enabled"] is False
            assert plot._state["image_width"] == 1200
            assert plot._tile_on is False

        assert plot._tile_on is before_tile_on
        changed = {k for k in before if plot._state.get(k) != before[k]}
        assert not changed, f"_temporarily_untiled leaked state keys: {changed}"

    def test_oversized_native_is_refused_before_materialising(self, monkeypatch):
        fig, ax = apl.subplots(1, 1, figsize=(FIGW, FIGH))
        plot = ax.imshow(_ramp(1200).astype(np.float32), cmap="gray")
        monkeypatch.setattr(plot._tile_backend.__class__, "full_shape",
                            property(lambda self: (40_000, 40_000)))
        with pytest.raises(ValueError, match="over the"):
            with _temporarily_untiled(plot):
                pass
        assert MAX_NATIVE_PIXELS == 1 << 28


# ══════════════════════════════════════════════════════════════════════════════
# The viewer's live view must survive the round trip
# ══════════════════════════════════════════════════════════════════════════════

class TestViewReconciliation:
    def test_sync_for_export_adopts_js_view_state(self):
        """Zoom/pan happen in the browser and are written to
        ``panel_<id>_json``; nothing on the Python side observes that trait, so
        without reconciliation every export would silently reset the view."""
        import json

        fig, ax = apl.subplots(1, 1, figsize=(FIGW, FIGH))
        plot = ax.imshow(_ramp(32), tile=False)
        trait = f"panel_{plot._id}_json"

        live = json.loads(getattr(fig, trait))
        live.update({"zoom": 3.0, "center_x": 0.25, "center_y": 0.75})
        setattr(fig, trait, json.dumps(live))

        fig._sync_for_export()

        assert plot._state["zoom"] == 3.0
        assert plot._state["center_x"] == 0.25
        assert plot._state["center_y"] == 0.75
        assert json.loads(getattr(fig, trait))["zoom"] == 3.0, (
            "the re-push must carry the adopted view back onto the trait")

    def test_sync_for_export_ignores_non_view_keys(self):
        """The trait carries the plot's whole state; only the keys the JS
        actually mutates may be merged back."""
        import json

        fig, ax = apl.subplots(1, 1, figsize=(FIGW, FIGH))
        plot = ax.imshow(_ramp(32), cmap="viridis", tile=False)
        trait = f"panel_{plot._id}_json"
        original_cmap = plot._state["colormap_name"]

        live = json.loads(getattr(fig, trait))
        live["colormap_name"] = "magma"
        setattr(fig, trait, json.dumps(live))

        fig._sync_for_export()
        assert plot._state["colormap_name"] == original_cmap, (
            "reconciliation must not adopt Python-authoritative state")

    def test_sync_for_export_survives_a_malformed_trait(self):
        fig, ax = apl.subplots(1, 1, figsize=(FIGW, FIGH))
        plot = ax.imshow(_ramp(32), tile=False)
        setattr(fig, f"panel_{plot._id}_json", "{not json")
        fig._sync_for_export()          # must not raise
        assert plot._state["zoom"] == 1

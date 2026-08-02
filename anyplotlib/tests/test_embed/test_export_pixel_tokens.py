"""
Snapshots must carry real pixels, never a dangling binary change-token.

Under the Electron binary transport (``APL_BINARY_TRANSPORT=1``) a panel's
image bytes do not travel in the state at all: ``Plot2D._encode_pixels`` writes
a ``"\\x00bin:<adler>"`` change-token and the real bytes ride a PLOTBIN frame
emitted by ``_electron._route_change``.  That split is right for a live wire and
wrong for a snapshot — ``save_html`` / ``to_html`` / ``figure_state`` produce a
document with no PLOTBIN behind it, so a token left in the state resolves to
nothing and the pixels are simply lost.

``Figure._sync_for_export`` therefore re-pushes with ``resolve_pixels=True``.
It has to say so explicitly because the transport gate is a process-global env
var, which is on in a host app even while that push is serialising a snapshot.

Regression: the re-push (added for widget-position capture) rewrote
``panel_<id>_json`` unconditionally with unresolved tokens, which both lost the
pixels and undid any materialisation a caller had done beforehand.  An overlay
LAYER was the visible casualty — ``_layerBytes`` in figure_esm.js bails on a
token (``b64.charCodeAt(0) === 0``), so the layer silently did not draw while
the base image, which is plain base64, still did.
"""
from __future__ import annotations

import json

import numpy as np
import pytest

import anyplotlib as apl
from anyplotlib.embed import figure_state


TOKEN = "\x00bin:"


@pytest.fixture
def binary_wire(monkeypatch):
    """Turn on the same env gate the Electron host sets."""
    monkeypatch.setenv("APL_BINARY_TRANSPORT", "1")


def _fig_with_layer():
    """A base image + one overlay layer, both on the token path.

    ``imshow`` encodes the base BEFORE the plot is attached to its Figure, so
    ``_encode_pixels`` finds no ``_raw_pixels`` side-table and falls back to
    base64 for it; ``add_layer`` runs after the attach and does produce a token.
    One ``set_data`` puts the base on the token path too — the state a live host
    is actually in once anything has redrawn.  (That asymmetry is why the
    regression looked so odd in the wild: the base image still rendered and only
    the overlay vanished.)
    """
    img = np.linspace(0, 1, 32 * 32, dtype=np.float32).reshape(32, 32)
    fig, ax = apl.subplots(1, 1, figsize=(300, 300))
    plot = ax.imshow(img, cmap="gray")
    plot.add_layer(img, cmap="magma", alpha=0.5)
    plot.set_data(img)
    return fig, plot


def _panel(state, plot):
    return json.loads(state[f"panel_{plot._id}_json"])


def _geom(state, plot):
    return json.loads(state[f"panel_{plot._id}_geom"])


def _is_b64(value):
    return isinstance(value, str) and value != "" and not value.startswith(TOKEN)


class TestSnapshotResolvesPixelTokens:
    def test_producer_really_emits_tokens(self, binary_wire):
        """Guard the premise: without this, the tests below prove nothing."""
        fig, plot = _fig_with_layer()
        state = plot.to_state_dict()
        assert state["image_b64"].startswith(TOKEN)
        assert state["layers"][0]["image_b64"].startswith(TOKEN)

    def test_base_image_is_inline_base64(self, binary_wire):
        fig, plot = _fig_with_layer()
        assert _is_b64(_geom(figure_state(fig), plot)["image_b64"])

    def test_layer_pixels_are_inline_base64(self, binary_wire):
        """The nested copy is the one figure_esm.js `_layerBytes` reads."""
        fig, plot = _fig_with_layer()
        layer = _panel(figure_state(fig), plot)["layers"][0]
        assert _is_b64(layer["image_b64"])

    def test_layer_geom_key_is_inline_base64(self, binary_wire):
        fig, plot = _fig_with_layer()
        geom = _geom(figure_state(fig), plot)
        assert _is_b64(geom[f"layer_{plot._state['layers'][0]['id']}_b64"])

    def test_no_token_survives_anywhere_in_the_snapshot(self, binary_wire):
        fig, plot = _fig_with_layer()
        blob = json.dumps(figure_state(fig))
        # json.dumps escapes NUL as \\u0000.
        assert "\\u0000bin:" not in blob

    def test_caller_materialisation_is_not_undone(self, binary_wire):
        """A host that resolves the traits itself before exporting keeps them.

        ``_sync_for_export`` rewrites ``panel_<id>_json`` unconditionally, so an
        unresolved re-push would clobber the caller's work — the exact shape of
        the reported regression.
        """
        fig, plot = _fig_with_layer()
        state = plot.to_state_dict()
        plot.resolve_pixel_tokens(state)
        resolved = state["layers"][0]["image_b64"]
        setattr(fig, f"panel_{plot._id}_json", json.dumps(state))

        after = _panel(figure_state(fig), plot)["layers"][0]["image_b64"]
        assert after == resolved

    def test_multi_layer_all_resolved(self, binary_wire):
        img = np.linspace(0, 1, 16 * 16, dtype=np.float32).reshape(16, 16)
        fig, ax = apl.subplots(1, 1, figsize=(300, 300))
        plot = ax.imshow(img, cmap="gray")
        for cmap in ("magma", "cividis", "plasma"):
            plot.add_layer(img, cmap=cmap, alpha=0.4)
        layers = _panel(figure_state(fig), plot)["layers"]
        assert len(layers) == 3
        assert all(_is_b64(ly["image_b64"]) for ly in layers)

    def test_widget_positions_still_reconciled(self, binary_wire):
        """The pixel fix must not cost the reason _sync_for_export exists."""
        fig, plot = _fig_with_layer()
        widget = plot.add_widget("rectangle", x=2, y=2, w=4, h=4)
        widget.set(x=21, y=23)
        got = _panel(figure_state(fig), plot)["overlay_widgets"][0]
        assert got["x"] == 21 and got["y"] == 23


class TestLiveWireStillUsesTokens:
    """The live path must keep its token/PLOTBIN split — that is the whole
    point of the binary transport, and resolving there would push megabytes of
    base64 through the comm on every scrub frame."""

    def test_ordinary_push_keeps_the_token(self, binary_wire):
        fig, plot = _fig_with_layer()
        fig._push(plot._id)
        geom = json.loads(getattr(fig, f"panel_{plot._id}_geom"))
        assert geom["image_b64"].startswith(TOKEN)
        layer_key = f"layer_{plot._state['layers'][0]['id']}_b64"
        assert geom[layer_key].startswith(TOKEN)

    def test_set_data_keeps_the_token(self, binary_wire):
        fig, plot = _fig_with_layer()
        plot.set_data(np.zeros((32, 32), dtype=np.float32))
        geom = json.loads(getattr(fig, f"panel_{plot._id}_geom"))
        assert geom["image_b64"].startswith(TOKEN)

    def test_push_after_export_returns_to_tokens(self, binary_wire):
        """An export must not leave the live wire on the base64 path."""
        fig, plot = _fig_with_layer()
        figure_state(fig)
        plot.set_data(np.ones((32, 32), dtype=np.float32))
        geom = json.loads(getattr(fig, f"panel_{plot._id}_geom"))
        assert geom["image_b64"].startswith(TOKEN)


class TestNoBinaryTransport:
    """With no binary wire the state was always inline base64; keep it so."""

    def test_snapshot_is_inline_base64(self, monkeypatch):
        monkeypatch.delenv("APL_BINARY_TRANSPORT", raising=False)
        fig, plot = _fig_with_layer()
        layer = _panel(figure_state(fig), plot)["layers"][0]
        assert _is_b64(layer["image_b64"])
        assert _is_b64(_geom(figure_state(fig), plot)["image_b64"])

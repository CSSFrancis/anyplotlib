"""
Unit tests for anyplotlib.embed — kernel-free embedding API.

Covers figure_state / to_html / save_html / esm_path / Figure.to_html, the
transport-agnostic FigureBridge (outbound forwarding, inbound event dispatch,
echo suppression, dynamic panel traits), and the navigated-page builders
pack_blocks / navigated_html.
"""
from __future__ import annotations

import json
import re

import numpy as np
import pytest

import anyplotlib as apl
from anyplotlib.embed import (
    FigureBridge, Ragged, esm_path, figure_state, navigated_html, pack_blocks,
    save_html, to_html,
)


def _fig_with_image():
    fig, ax = apl.subplots(1, 1, figsize=(320, 240))
    plot = ax.imshow(np.zeros((16, 16), dtype=np.float32))
    return fig, plot


class TestFigureState:
    def test_contains_core_keys(self):
        fig, plot = _fig_with_image()
        state = figure_state(fig)
        assert "layout_json" in state
        assert state["fig_width"] == 320
        assert f"panel_{plot._id}_json" in state

    def test_panel_state_is_json(self):
        fig, plot = _fig_with_image()
        state = figure_state(fig)
        panel = json.loads(state[f"panel_{plot._id}_json"])
        assert panel["kind"] == "2d"


class TestHtmlExport:
    def test_to_html_is_self_contained(self):
        fig, plot = _fig_with_image()
        html = to_html(fig)
        assert html.startswith("<!DOCTYPE html>")
        assert "function render" in html          # inlined ESM
        assert f"panel_{plot._id}_json" in html   # inlined state

    def test_figure_methods(self, tmp_path):
        fig, _ = _fig_with_image()
        assert fig.to_html() == to_html(fig)
        out = fig.save_html(tmp_path / "fig.html")
        assert out.read_text(encoding="utf-8") == fig.to_html()

    def test_save_html(self, tmp_path):
        fig, _ = _fig_with_image()
        p = save_html(fig, tmp_path / "plot.html", resizable=False)
        assert p.exists() and p.stat().st_size > 10_000

    def test_esm_path_exports_mount(self):
        src = esm_path().read_text(encoding="utf-8")
        assert "export function mount" in src
        assert "export function createLocalModel" in src


class TestFigureBridge:
    def test_outbound_forwarding(self):
        fig, plot = _fig_with_image()
        sent = []
        FigureBridge(fig, send=lambda k, v: sent.append(k))
        plot.set_title("hello")
        assert f"panel_{plot._id}_json" in sent

    def test_outbound_layout_changes(self):
        fig, _ = _fig_with_image()
        sent = []
        FigureBridge(fig, send=lambda k, v: sent.append(k))
        fig.fig_width = 500
        assert "fig_width" in sent and "layout_json" in sent

    def test_dynamic_panel_traits_forwarded(self):
        """Panels added AFTER bridge creation must still forward."""
        fig = apl.Figure(1, 2, figsize=(400, 200))
        sent = []
        FigureBridge(fig, send=lambda k, v: sent.append(k))
        plot = fig.add_subplot((0, 0)).plot(np.zeros(8))
        plot.set_title("late panel")
        assert f"panel_{plot._id}_json" in sent

    def test_inbound_event_dispatches_callbacks(self):
        fig, plot = _fig_with_image()
        bridge = FigureBridge(fig, send=lambda k, v: None)
        got = []

        @plot.add_event_handler("pointer_down")
        def on_down(event):
            got.append((event.event_type, event.xdata))

        bridge.receive("event_json", json.dumps({
            "panel_id": plot._id, "event_type": "pointer_down",
            "x": 5, "y": 6, "xdata": 1.5, "ydata": 2.5, "button": 0,
        }))
        assert got == [("pointer_down", 1.5)]

    def test_inbound_no_echo(self):
        """receive() must not re-send the same key back."""
        fig, plot = _fig_with_image()
        sent = []
        bridge = FigureBridge(fig, send=lambda k, v: sent.append(k))
        key = f"panel_{plot._id}_json"
        new_state = json.dumps({**plot.to_state_dict(), "title": "from js"})
        bridge.receive(key, new_state)
        assert key not in sent
        assert getattr(fig, key) == new_state

    def test_inbound_unknown_key_ignored(self):
        fig, _ = _fig_with_image()
        bridge = FigureBridge(fig, send=lambda k, v: None)
        bridge.receive("panel_doesnotexist_json", "{}")  # must not raise

    def test_snapshot_matches_figure_state(self):
        fig, _ = _fig_with_image()
        bridge = FigureBridge(fig, send=lambda k, v: None)
        assert bridge.snapshot() == figure_state(fig)

    def test_close_stops_forwarding(self):
        fig, plot = _fig_with_image()
        sent = []
        bridge = FigureBridge(fig, send=lambda k, v: sent.append(k))
        bridge.close()
        plot.set_title("after close")
        assert sent == []


class TestPackBlocks:
    def test_dense_round_trips_bit_exactly(self):
        rng = np.random.default_rng(3)
        first = rng.integers(0, 256, size=(4, 5, 6)).astype(np.uint8)
        second = rng.random((3, 7)).astype(np.float32)
        payload, manifest = pack_blocks({"first": first, "second": second})

        assert manifest["first"]["kind"] == "dense"
        assert manifest["first"]["shape"] == [4, 5, 6]
        assert manifest["second"]["dtype"] == "float32"
        for name, array in (("first", first), ("second", second)):
            entry = manifest[name]
            raw = payload[entry["offset"]:entry["offset"] + entry["nbytes"]]
            restored = np.frombuffer(raw, dtype=array.dtype).reshape(array.shape)
            assert np.array_equal(restored, array)

    def test_every_block_starts_on_an_aligned_offset(self):
        """A typed-array view can only start on a multiple of its item size."""
        payload, manifest = pack_blocks({
            "odd": np.zeros(5, dtype=np.uint8),
            "wide": np.arange(4, dtype=np.float64),
        })
        assert manifest["wide"]["offset"] % 8 == 0
        assert len(payload) >= manifest["wide"]["offset"] + manifest["wide"]["nbytes"]

    def test_ragged_round_trips_bit_exactly(self):
        offsets = np.array([0, 2, 2, 5], dtype=np.int32)
        columns = {"x": np.array([1.5, 2.5, 3.5, 4.5, 5.5], dtype=np.float32),
                   "intensity": np.arange(5, dtype=np.float32)}
        payload, manifest = pack_blocks({
            "spots": Ragged(offsets=offsets, columns=columns, nav_shape=(1, 3))})

        entry = manifest["spots"]
        assert entry["kind"] == "ragged" and entry["nav_shape"] == [1, 3]
        raw = payload[entry["offsets"]["offset"]:
                      entry["offsets"]["offset"] + entry["offsets"]["nbytes"]]
        assert np.array_equal(np.frombuffer(raw, dtype=np.int32), offsets)
        for name, values in columns.items():
            spec = entry["columns"][name]
            raw = payload[spec["offset"]:spec["offset"] + spec["nbytes"]]
            assert np.array_equal(np.frombuffer(raw, dtype=np.float32), values)

    def test_unviewable_dtype_is_refused(self):
        with pytest.raises(ValueError, match="cannot be viewed"):
            pack_blocks({"big": np.zeros(3, dtype=np.int64)})


class TestNavigatedHtml:
    def _figure(self):
        fig, axes = apl.subplots(1, 2, figsize=(400, 200))
        navigator = axes[0].imshow(np.zeros((4, 4), dtype=np.uint8))
        signal = axes[1].imshow(np.zeros((8, 8), dtype=np.uint8))
        return fig, navigator, signal

    def _bindings(self, navigator, signal):
        return [{"panel_id": navigator._id, "role": "navigator"},
                {"panel_id": signal._id, "role": "driven",
                 "frame": {"block": "cube", "kind": "image"}}]

    def test_page_is_self_contained(self):
        fig, navigator, signal = self._figure()
        cube = np.zeros((4, 4, 8, 8), dtype=np.uint8)
        html = navigated_html(fig, {"cube": cube},
                              self._bindings(navigator, signal),
                              title="Scan", caption="drag the crosshair")
        assert html.startswith("<!DOCTYPE html>")
        assert "mountNavigated" in html
        assert "export async function mountNavigated" in html  # the renderer, inlined
        assert re.search(r"https?://", html.replace("http://www.w3.org", "")) is None
        assert "Scan" in html and "drag the crosshair" in html

    def test_unknown_panel_is_refused(self):
        fig, navigator, signal = self._figure()
        with pytest.raises(ValueError, match="unknown panel"):
            navigated_html(fig, {"cube": np.zeros((4, 4, 8, 8), dtype=np.uint8)},
                           [{"panel_id": "nope", "role": "navigator"}])

    def test_unknown_block_is_refused(self):
        fig, navigator, signal = self._figure()
        bindings = self._bindings(navigator, signal)
        bindings[1]["frame"]["block"] = "missing"
        with pytest.raises(ValueError, match="unknown block"):
            navigated_html(fig, {"cube": np.zeros((4, 4, 8, 8), dtype=np.uint8)},
                           bindings)

    def test_state_dict_is_accepted_in_place_of_a_figure(self):
        fig, navigator, signal = self._figure()
        html = navigated_html(figure_state(fig),
                              {"cube": np.zeros((4, 4, 8, 8), dtype=np.uint8)},
                              self._bindings(navigator, signal))
        assert f"panel_{signal._id}_json" in html

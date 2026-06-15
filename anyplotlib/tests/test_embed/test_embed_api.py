"""
Unit tests for anyplotlib.embed — kernel-free embedding API.

Covers figure_state / to_html / save_html / esm_path / Figure.to_html and
the transport-agnostic FigureBridge (outbound forwarding, inbound event
dispatch, echo suppression, dynamic panel traits).
"""
from __future__ import annotations

import json

import numpy as np
import pytest

import anyplotlib as apl
from anyplotlib.embed import (
    FigureBridge, esm_path, figure_state, save_html, to_html,
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

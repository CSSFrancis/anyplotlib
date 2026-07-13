"""
tests/test_interactive/test_edit_chrome.py
==========================================

Unit tests for the Report-Builder edit-mode features:

Batch 1 — widget polish + ArrowWidget
  * ``show_handles`` lands in every 2-D widget's state / overlay_widgets
  * ``ArrowWidget`` state round-trip, adder defaults, dispatcher entry, JS-sync

Batch 2 — figure-level chrome + annotation layer
  * ``edit_chrome`` / ``selected_panel`` trait round-trips
  * ``set_figure_markers`` validation + id assignment + ``figure_markers``
  * ``_dispatch_event`` for ``figure_background`` (figure callbacks, not panel)
  * ``_dispatch_event`` for ``figure_marker`` pointer_up (updates list + fires)

The JS drag / hover / background-emit behaviour is covered by the Playwright
suite in ``test_edit_chrome_playwright.py``.
"""

from __future__ import annotations

import json
import numpy as np
import pytest

import anyplotlib as apl
from anyplotlib.widgets import ArrowWidget


def _simulate_js_event(fig, plot, event_type, *, widget_id=None, **fields):
    payload = {"source": "js", "panel_id": plot._id, "event_type": event_type}
    if widget_id is not None:
        payload["widget_id"] = widget_id if isinstance(widget_id, str) else widget_id._id
    payload.update(fields)
    fig._dispatch_event(json.dumps(payload))


# ═══════════════════════════════════════════════════════════════════════════
# Batch 1.1 — show_handles
# ═══════════════════════════════════════════════════════════════════════════

class TestShowHandles:
    def test_default_true_all_kinds(self):
        fig, ax = apl.subplots(1, 1)
        v = ax.imshow(np.zeros((32, 32)))
        widgets = [
            v.add_circle_widget(),
            v.add_rectangle_widget(),
            v.add_annular_widget(r_outer=10, r_inner=5),
            v.add_crosshair_widget(),
            v.add_polygon_widget(),
            v.add_label_widget(),
            v.add_arrow_widget(),
        ]
        for w in widgets:
            assert w.show_handles is True, w._type
            assert w.to_dict()["show_handles"] is True

    def test_false_carried_into_state(self):
        fig, ax = apl.subplots(1, 1)
        v = ax.imshow(np.zeros((32, 32)))
        w = v.add_rectangle_widget(show_handles=False)
        assert w.show_handles is False
        entry = next(e for e in v.to_state_dict()["overlay_widgets"]
                     if e["id"] == w.id)
        assert entry["show_handles"] is False

    def test_show_handles_via_add_widget_dispatcher(self):
        fig, ax = apl.subplots(1, 1)
        v = ax.imshow(np.zeros((32, 32)))
        w = v.add_widget("circle", show_handles=False)
        assert w.show_handles is False

    def test_serialization_present_for_every_kind(self):
        fig, ax = apl.subplots(1, 1)
        v = ax.imshow(np.zeros((32, 32)))
        v.add_circle_widget();      v.add_rectangle_widget()
        v.add_annular_widget(r_outer=10, r_inner=5)
        v.add_crosshair_widget();   v.add_polygon_widget()
        v.add_label_widget();       v.add_arrow_widget()
        entries = v.to_state_dict()["overlay_widgets"]
        assert all("show_handles" in e for e in entries)
        assert len(entries) == 7


# ═══════════════════════════════════════════════════════════════════════════
# Batch 1.2 — ArrowWidget
# ═══════════════════════════════════════════════════════════════════════════

class TestArrowWidget:
    def test_arrow_attributes(self):
        w = ArrowWidget(lambda: None, x=10, y=20, u=30, v=40)
        assert w.x == 10.0 and w.y == 20.0 and w.u == 30.0 and w.v == 40.0
        assert w._type == "arrow"
        assert w.linewidth == 2.0 and w.show_handles is True

    def test_to_dict_round_trip(self):
        w = ArrowWidget(lambda: None, x=1, y=2, u=3, v=4, color="#abc")
        d = w.to_dict()
        assert d["type"] == "arrow" and d["x"] == 1.0 and d["u"] == 3.0
        assert d["color"] == "#abc" and "id" in d

    def test_add_arrow_widget_defaults(self):
        # tail at 25%,25% of the image; u=v = 15% of the image (mirrors label).
        fig, ax = apl.subplots(1, 1)
        v = ax.imshow(np.zeros((40, 40)))
        w = v.add_arrow_widget()
        assert w.x == pytest.approx(40 * 0.25)
        assert w.y == pytest.approx(40 * 0.25)
        assert w.u == pytest.approx(40 * 0.15)
        assert w.v == pytest.approx(40 * 0.15)

    def test_add_arrow_widget_explicit(self):
        fig, ax = apl.subplots(1, 1)
        v = ax.imshow(np.zeros((32, 32)))
        w = v.add_arrow_widget(x=5, y=6, u=7, v=8, color="#f00", linewidth=3)
        assert (w.x, w.y, w.u, w.v) == (5.0, 6.0, 7.0, 8.0)
        assert w.color == "#f00" and w.linewidth == 3.0

    def test_dispatcher_entry(self):
        fig, ax = apl.subplots(1, 1)
        v = ax.imshow(np.zeros((32, 32)))
        w = v.add_widget("arrow", x=1, y=2, u=3, v=4)
        assert isinstance(w, ArrowWidget)
        assert (w.x, w.u) == (1.0, 3.0)

    def test_arrow_in_state_dict(self):
        fig, ax = apl.subplots(1, 1)
        v = ax.imshow(np.zeros((32, 32)))
        w = v.add_arrow_widget(x=1, y=2, u=3, v=4)
        entry = next(e for e in v.to_state_dict()["overlay_widgets"]
                     if e["id"] == w.id)
        assert entry["type"] == "arrow"
        assert entry["x"] == 1.0 and entry["v"] == 4.0

    def test_js_drag_syncs_all_fields(self):
        """A simulated JS drag emits x/y/u/v; _update_from_js syncs them back."""
        fig, ax = apl.subplots(1, 1)
        v = ax.imshow(np.zeros((32, 32)))
        w = v.add_arrow_widget(x=0, y=0, u=10, v=10)
        moves = []
        w.add_event_handler(lambda e: moves.append((w.x, w.y, w.u, w.v)),
                            "pointer_move")
        _simulate_js_event(fig, v, "pointer_move", widget_id=w,
                           x=5.0, y=6.0, u=15.0, v=16.0)
        assert moves == [(5.0, 6.0, 15.0, 16.0)]
        assert (w.x, w.y, w.u, w.v) == (5.0, 6.0, 15.0, 16.0)

    def test_js_head_resize_syncs_uv(self):
        fig, ax = apl.subplots(1, 1)
        v = ax.imshow(np.zeros((32, 32)))
        w = v.add_arrow_widget(x=4, y=4, u=8, v=8)
        _simulate_js_event(fig, v, "pointer_up", widget_id=w, u=20.0, v=2.0)
        assert w.u == 20.0 and w.v == 2.0


# ═══════════════════════════════════════════════════════════════════════════
# Batch 2.1 — Figure traits (edit_chrome / selected_panel / figure_markers_json)
# ═══════════════════════════════════════════════════════════════════════════

class TestFigureTraits:
    def test_edit_chrome_default_false(self):
        fig, ax = apl.subplots(1, 1)
        assert fig.edit_chrome is False

    def test_edit_chrome_round_trip(self):
        fig, ax = apl.subplots(1, 1)
        fig.edit_chrome = True
        assert fig.edit_chrome is True
        assert fig.traits(sync=True)["edit_chrome"] is not None

    def test_selected_panel_default_empty(self):
        fig, ax = apl.subplots(1, 1)
        assert fig.selected_panel == ""

    def test_selected_panel_round_trip(self):
        fig, ax = apl.subplots(1, 1)
        v = ax.imshow(np.zeros((8, 8)))
        fig.selected_panel = v._id
        assert fig.selected_panel == v._id

    def test_figure_markers_json_default_empty_list(self):
        fig, ax = apl.subplots(1, 1)
        assert json.loads(fig.figure_markers_json) == []

    def test_all_three_are_synced_traits(self):
        fig, ax = apl.subplots(1, 1)
        synced = fig.traits(sync=True)
        assert "edit_chrome" in synced
        assert "selected_panel" in synced
        assert "figure_markers_json" in synced


# ═══════════════════════════════════════════════════════════════════════════
# Batch 2.2 — set_figure_markers / figure_markers property
# ═══════════════════════════════════════════════════════════════════════════

class TestSetFigureMarkers:
    def test_set_and_read_back(self):
        fig, ax = apl.subplots(1, 1)
        fig.set_figure_markers([
            {"kind": "text", "x": 0.5, "y": 0.5, "text": "hi"},
            {"kind": "circle", "x": 0.2, "y": 0.3, "r": 0.1},
            {"kind": "rect", "x": 0.5, "y": 0.5, "w": 0.2, "h": 0.1},
            {"kind": "arrow", "x": 0.1, "y": 0.1, "u": 0.2, "v": 0.2},
        ])
        markers = fig.figure_markers
        assert [m["kind"] for m in markers] == ["text", "circle", "rect", "arrow"]

    def test_ids_assigned_when_missing(self):
        fig, ax = apl.subplots(1, 1)
        fig.set_figure_markers([{"kind": "text", "x": 0, "y": 0, "text": "a"}])
        assert fig.figure_markers[0]["id"]

    def test_existing_ids_preserved(self):
        fig, ax = apl.subplots(1, 1)
        fig.set_figure_markers([{"kind": "text", "x": 0, "y": 0, "text": "a",
                                 "id": "keepme"}])
        assert fig.figure_markers[0]["id"] == "keepme"

    def test_json_trait_syncs(self):
        fig, ax = apl.subplots(1, 1)
        fig.set_figure_markers([{"kind": "circle", "x": 0.5, "y": 0.5, "r": 0.1}])
        parsed = json.loads(fig.figure_markers_json)
        assert parsed[0]["kind"] == "circle" and parsed[0]["r"] == 0.1

    def test_bad_kind_raises(self):
        fig, ax = apl.subplots(1, 1)
        with pytest.raises(ValueError, match="kind must be one of"):
            fig.set_figure_markers([{"kind": "polygon", "x": 0, "y": 0}])

    def test_figure_markers_returns_copy(self):
        fig, ax = apl.subplots(1, 1)
        fig.set_figure_markers([{"kind": "text", "x": 0, "y": 0, "text": "a"}])
        got = fig.figure_markers
        got[0]["x"] = 999
        # Mutating the returned list must not desync the stored state.
        assert fig.figure_markers[0]["x"] == 0

    def test_empty_list_clears(self):
        fig, ax = apl.subplots(1, 1)
        fig.set_figure_markers([{"kind": "text", "x": 0, "y": 0, "text": "a"}])
        fig.set_figure_markers([])
        assert fig.figure_markers == []
        assert json.loads(fig.figure_markers_json) == []


# ═══════════════════════════════════════════════════════════════════════════
# Batch 2.3 — _dispatch_event figure-level routing
# ═══════════════════════════════════════════════════════════════════════════

class TestFigureBackgroundDispatch:
    def test_fires_figure_callback_not_panel(self):
        fig, ax = apl.subplots(1, 1)
        v = ax.imshow(np.zeros((16, 16)))
        fig_events, panel_events = [], []
        fig.add_event_handler(lambda e: fig_events.append(e), "pointer_down")
        v.add_event_handler(lambda e: panel_events.append(e), "pointer_down")

        fig._dispatch_event(json.dumps({
            "source": "js", "panel_id": "", "event_type": "pointer_down",
            "figure_background": True,
        }))
        assert len(fig_events) == 1
        assert panel_events == []

    def test_figure_event_source_is_figure(self):
        fig, ax = apl.subplots(1, 1)
        received = []
        fig.add_event_handler(lambda e: received.append(e.source), "pointer_down")
        fig._dispatch_event(json.dumps({
            "source": "js", "panel_id": "", "event_type": "pointer_down",
            "figure_background": True,
        }))
        assert received[0] is fig

    def test_panel_click_does_not_fire_figure(self):
        fig, ax = apl.subplots(1, 1)
        v = ax.imshow(np.zeros((16, 16)))
        fig_events = []
        fig.add_event_handler(lambda e: fig_events.append(e), "pointer_down")
        fig._dispatch_event(json.dumps({
            "source": "js", "panel_id": v._id, "event_type": "pointer_down",
        }))
        assert fig_events == []


class TestFigureMarkerDispatch:
    def test_pointer_up_updates_list_and_fires(self):
        fig, ax = apl.subplots(1, 1)
        fig.set_figure_markers([
            {"kind": "arrow", "x": 0.1, "y": 0.1, "u": 0.2, "v": 0.2, "id": "m1"}])
        fired = []
        fig.add_event_handler(lambda e: fired.append(e.last_widget_id), "pointer_up")

        fig._dispatch_event(json.dumps({
            "source": "js", "panel_id": "", "event_type": "pointer_up",
            "figure_marker": True, "marker_id": "m1",
            "x": 0.5, "y": 0.6, "u": 0.3, "v": 0.3,
        }))
        m = fig.figure_markers[0]
        assert (m["x"], m["y"], m["u"], m["v"]) == (0.5, 0.6, 0.3, 0.3)
        assert fired == ["m1"]

    def test_marker_json_converges(self):
        fig, ax = apl.subplots(1, 1)
        fig.set_figure_markers([
            {"kind": "text", "x": 0.1, "y": 0.1, "text": "hi", "id": "t1"}])
        fig._dispatch_event(json.dumps({
            "source": "js", "panel_id": "", "event_type": "pointer_up",
            "figure_marker": True, "marker_id": "t1", "x": 0.7, "y": 0.8,
        }))
        parsed = json.loads(fig.figure_markers_json)
        assert parsed[0]["x"] == 0.7 and parsed[0]["y"] == 0.8

    def test_unknown_marker_id_no_crash(self):
        fig, ax = apl.subplots(1, 1)
        fig.set_figure_markers([
            {"kind": "text", "x": 0.1, "y": 0.1, "text": "hi", "id": "t1"}])
        # Should not raise even if the id doesn't match.
        fig._dispatch_event(json.dumps({
            "source": "js", "panel_id": "", "event_type": "pointer_up",
            "figure_marker": True, "marker_id": "nope", "x": 0.7,
        }))
        assert fig.figure_markers[0]["x"] == 0.1

    def test_rect_marker_size_fields_update(self):
        fig, ax = apl.subplots(1, 1)
        fig.set_figure_markers([
            {"kind": "rect", "x": 0.5, "y": 0.5, "w": 0.2, "h": 0.1, "id": "r1"}])
        fig._dispatch_event(json.dumps({
            "source": "js", "panel_id": "", "event_type": "pointer_up",
            "figure_marker": True, "marker_id": "r1", "x": 0.3, "y": 0.4,
        }))
        m = fig.figure_markers[0]
        assert m["x"] == 0.3 and m["y"] == 0.4
        # w/h unchanged (not in the drag payload)
        assert m["w"] == 0.2 and m["h"] == 0.1

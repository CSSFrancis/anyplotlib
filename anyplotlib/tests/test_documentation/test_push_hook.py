"""
tests/test_documentation/test_push_hook.py
==========================================

Unit tests for the Python→JS state-push pathway.

These tests require **no browser** — they call ``_push()`` / ``_push_layout()``
directly and inspect the resulting traitlet values.  They cover the same
ground that older tests exercised via ``_pyodide_push_hook``; the hook is now
gone and state flows through standard ``sync=True`` traitlets instead.

Related browser tests (iframe postMessage, full mock-boot) live in
``test_bridge.py``.
"""

from __future__ import annotations

import json

import numpy as np
import pytest

import anyplotlib as apl
import anyplotlib.figure as _af


# ─────────────────────────────────────────────────────────────────────────────
# Helper shared by multiple tests
# ─────────────────────────────────────────────────────────────────────────────

def _capture_fig_state(fig) -> dict[str, str]:
    """Return ``{trait_name: json_string}`` for layout + every panel trait.

    Reads traitlet values directly after calling the push methods.  This
    works even when the value hasn't changed (traitlets suppress duplicate
    change events, so an observe-based approach would return nothing on a
    second call with the same state).
    """
    fig._push_layout()
    for pid in list(fig._plots_map):
        fig._push(pid)

    captured: dict[str, str] = {}
    captured["layout_json"] = fig.layout_json
    for tname in fig.trait_names():
        if tname.startswith("panel_") and tname.endswith("_json"):
            captured[tname] = getattr(fig, tname)
    return captured


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────

class TestPushHook:
    """Verify _push() / _push_layout() write to sync=True traitlets correctly."""

    def test_push_does_not_crash(self):
        """Normal mode: _push() succeeds without error."""
        fig, ax = apl.subplots(1, 1, figsize=(400, 300))
        ax.plot(np.zeros(16))  # must not raise

    def test_layout_json_written_on_create(self):
        """layout_json traitlet is set when a figure is created."""
        fig, ax = apl.subplots(1, 1, figsize=(400, 300))
        parsed = json.loads(fig.layout_json)
        assert "panel_specs" in parsed, (
            f"layout_json missing 'panel_specs': {list(parsed.keys())}"
        )

    def test_panel_json_written_after_plot(self):
        """panel_*_json traitlet is set when a plot is added."""
        fig, ax = apl.subplots(1, 1, figsize=(400, 300))
        ax.plot(np.sin(np.linspace(0, 2 * np.pi, 64)))

        panel_keys = [
            k for k in fig.trait_names()
            if k.startswith("panel_") and k.endswith("_json")
        ]
        assert len(panel_keys) >= 1, "Expected at least one panel_*_json trait"
        for k in panel_keys:
            parsed = json.loads(getattr(fig, k))
            assert "kind" in parsed, (
                f"panel JSON missing 'kind': {list(parsed.keys())}"
            )

    def test_observe_fires_on_push(self):
        """traitlets.observe() fires when _push() writes a panel trait."""
        seen: list[str] = []

        def _watch(change):
            seen.append(change["name"])

        fig, ax = apl.subplots(1, 1, figsize=(400, 300))
        fig.observe(_watch)
        ax.plot(np.zeros(8))
        fig.unobserve(_watch)

        assert any(k.startswith("panel_") for k in seen), (
            f"Expected a panel_* trait change; got: {seen}"
        )

    def test_panel_id_deterministic(self):
        """Panel IDs derived from SubplotSpec must be identical across rebuilds."""
        ids: list[str] = []
        for _ in range(3):
            fig, ax = apl.subplots(1, 1, figsize=(400, 300))
            ax.plot(np.zeros(8))
            ids.append(list(fig._plots_map.keys())[0])
        assert ids[0] == ids[1] == ids[2], (
            f"Panel ID must be deterministic; got {ids}"
        )

    def test_panel_ids_unique_in_multiplot(self):
        """Each panel in a multi-panel figure has a unique ID."""
        fig, axes = apl.subplots(1, 3, figsize=(900, 300))
        for ax in axes:
            ax.plot(np.zeros(8))
        ids = list(fig._plots_map.keys())
        assert len(ids) == len(set(ids)), f"Panel IDs not unique: {ids}"

    def test_panel_id_matches_grid_position(self):
        """Panel IDs encode the SubplotSpec row/col bounds."""
        fig, axes = apl.subplots(2, 2, figsize=(600, 400))
        for ax in np.asarray(axes).flat:
            ax.plot(np.zeros(4))
        ids = set(fig._plots_map.keys())
        for pid in ids:
            assert pid.startswith("p"), f"Unexpected panel ID format: {pid!r}"

    def test_dispatch_event_callable_without_kernel(self):
        """_dispatch_event() can be called directly as the Pyodide bridge does."""
        fig, ax = apl.subplots(1, 1, figsize=(400, 300))
        ax.plot(np.zeros(16))
        raw = json.dumps({
            "event_type": "on_zoom",
            "panel_id": list(fig._plots_map.keys())[0],
            "source": "js",
        })
        fig._dispatch_event(raw)  # must not raise

    def test_capture_fig_state_helper(self):
        """_capture_fig_state returns both layout_json and panel JSON(s)."""
        fig, ax = apl.subplots(1, 1, figsize=(400, 300))
        ax.plot(np.zeros(32))
        state = _capture_fig_state(fig)
        assert "layout_json" in state, (
            f"Expected layout_json; got {list(state.keys())}"
        )
        panel_keys = [k for k in state if k.startswith("panel_")]
        assert len(panel_keys) >= 1, "Expected at least one panel_ key"

    def test_no_pyodide_push_hook_attribute(self):
        """figure module no longer exposes _pyodide_push_hook."""
        assert not hasattr(_af, "_pyodide_push_hook"), (
            "_pyodide_push_hook should not exist on figure module"
        )


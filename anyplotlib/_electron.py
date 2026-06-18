"""
_electron.py
============
Electron app bridge for anyplotlib figures.

Registers figures so their trait changes are forwarded to the Electron
renderer via stdout, and provides dispatch_event() so the renderer can
send interaction events back to Python.
"""
from __future__ import annotations

import json
import sys
import uuid

_figures: dict[str, object] = {}   # fig_id -> Figure


def register(fig) -> str:
    """Register *fig* for bidirectional state sync and return its fig_id."""
    fig_id = uuid.uuid4().hex[:8]
    _figures[fig_id] = fig

    def _on_change(change):
        name = change["name"]
        value = change["new"]
        if isinstance(value, (bytes, bytearray)):
            import base64
            value = {"buffer": base64.b64encode(value).decode()}
        emit({"type": "state_update", "fig_id": fig_id, "key": name, "value": value})

    for name in fig.traits(sync=True):
        if not name.startswith("_"):
            try:
                fig.observe(_on_change, names=[name])
            except Exception:
                pass

    return fig_id


def resize_figure(fig_id: str, width: int, height: int) -> None:
    """Update fig_width / fig_height and push new layout to the iframe."""
    fig = _figures.get(fig_id)
    if fig is None:
        return
    try:
        # Batch both trait changes so _on_resize fires only once each.
        with fig.hold_trait_notifications():
            fig.fig_width  = int(width)
            fig.fig_height = int(height)
    except Exception:
        pass


def dispatch_event(fig_id: str, event_json: str) -> None:
    """Apply a frontend interaction event to the registered figure."""
    fig = _figures.get(fig_id)
    if fig is None:
        return
    try:
        # Figure.show() registers Figure objects which use _dispatch_event(raw_json_str).
        # Standalone widgets use _update_from_js(dict, event_type).
        if hasattr(fig, "_dispatch_event"):
            fig._dispatch_event(event_json)
        elif hasattr(fig, "_update_from_js"):
            fig._update_from_js(json.loads(event_json))
    except Exception:
        pass


def emit(obj: dict) -> None:
    sys.stdout.write(f"PLOTAPP:{json.dumps(obj, default=str)}\n")
    sys.stdout.flush()

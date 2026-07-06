"""
_electron.py
============
Electron app bridge for anyplotlib figures.

Registers figures so their trait changes are forwarded to the Electron
renderer via stdout, and provides dispatch_event() so the renderer can
send interaction events back to Python.
"""
from __future__ import annotations

import base64
import json
import os
import sys
import uuid

from anyplotlib._binary_frame import encode_frame

_figures: dict[str, object] = {}   # fig_id -> Figure

# Opt-in binary transport for large image pixels (Electron host only). When on,
# the big ``image_b64`` / ``overlay_mask_b64`` pixel traits are shipped as a raw
# PLOTBIN binary frame (no base64, no JSON for the pixels) instead of a giant
# base64 string in the state_update JSON — the base64 encode + 5.6MB JSON line +
# JS atob cost ~200 ms/frame on a 4k movie. Off by default (base64 path) so this
# is zero-risk until the host opts in; SpyDE sets APL_BINARY_TRANSPORT=1.
_BINARY_TRANSPORT = os.environ.get("APL_BINARY_TRANSPORT") == "1"
# State keys whose value is a base64 pixel string worth sending as binary.
_BINARY_KEYS = frozenset({"image_b64", "overlay_mask_b64"})


def _route_change(fig_id: str, name: str, value) -> None:
    """Forward ONE trait change to the host — as a raw PLOTBIN binary frame for a
    large image pixel trait (when binary transport is enabled), else as a
    base64-in-JSON ``state_update``. Extracted from the observer so it's unit-
    testable without a real Figure/stdout."""
    # Binary fast path: a large base64 pixel string → raw PLOTBIN frame. The
    # renderer rebuilds the same bytes from the ArrayBuffer (no atob). We decode
    # the base64 back to bytes here (cheap vs the ~200 ms transport it saves); a
    # later change can keep the raw bytes upstream to skip even this decode.
    #
    # The big pixel strings ride INSIDE a panel geometry trait — ``panel_<pid>_geom``
    # is a JSON string ``{"image_b64": <b64>, "colormap_data": …, …}`` (see
    # Figure._push). So for binary transport we parse that JSON, pull the pixel
    # keys out, ship each as a raw PLOTBIN frame, and send the REST of the geom
    # (small: LUT + flags) as the normal state_update. A bare pixel trait (not
    # nested) is handled too, for robustness.
    if _BINARY_TRANSPORT and isinstance(value, str) and value:
        if name.startswith("panel_") and name.endswith("_geom"):
            try:
                geom = json.loads(value)
            except Exception:
                geom = None
            if isinstance(geom, dict) and any(k in geom for k in _BINARY_KEYS):
                sent_binary = False
                for k in list(geom.keys()):
                    if k in _BINARY_KEYS and isinstance(geom[k], str) and geom[k]:
                        try:
                            raw = base64.b64decode(geom.pop(k))
                            # key carries the geom trait + which pixel field, so the
                            # renderer routes it back into the right panel state.
                            emit_binary(fig_id, k,
                                        {"nbytes": len(raw), "geom": name}, raw)
                            sent_binary = True
                        except Exception:
                            pass   # leave it in geom → goes via JSON below
                if sent_binary:
                    # Send the slimmed geom (LUT etc., pixels removed) as JSON.
                    emit({"type": "state_update", "fig_id": fig_id, "key": name,
                          "value": json.dumps(geom)})
                    return
        elif name in _BINARY_KEYS:
            try:
                raw = base64.b64decode(value)
                emit_binary(fig_id, name, {"nbytes": len(raw)}, raw)
                return
            except Exception:
                pass   # fall back to the base64-in-JSON path below
    if isinstance(value, (bytes, bytearray)):
        value = {"buffer": base64.b64encode(value).decode()}
    emit({"type": "state_update", "fig_id": fig_id, "key": name, "value": value})


def register(fig) -> str:
    """Register *fig* for bidirectional state sync and return its fig_id."""
    fig_id = uuid.uuid4().hex[:8]
    _figures[fig_id] = fig

    def _on_change(change):
        _route_change(fig_id, change["name"], change["new"])

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


def emit_binary(fig_id: str, key: str, header: dict, payload: bytes) -> None:
    """Write a raw PLOTBIN binary frame to stdout (pixels, no base64/JSON).

    Goes to the RAW ``sys.stdout.buffer`` so the payload is bytes on the wire; the
    Electron host demuxes ``PLOTBIN:`` frames from the same stdout stream that
    carries the text ``PLOTAPP:`` lines. Flushed so the host sees it promptly."""
    frame = encode_frame(fig_id, key, header, payload)
    buf = getattr(sys.stdout, "buffer", None)
    if buf is None:            # no binary stdout (unusual) → base64 fallback
        emit({"type": "state_update", "fig_id": fig_id, "key": key,
              "value": base64.b64encode(payload).decode()})
        return
    # NOTE: a host that redirects sys.stdout (e.g. SpyDE points sys.stdout at
    # stderr to keep the protocol channel clean) MUST patch emit_binary to write
    # to its real protocol stdout — otherwise these bytes go to the wrong stream.
    # Flush the TEXT stream first so any pending PLOTAPP: line is on the wire
    # before this binary frame — the host demuxes a single ordered byte stream.
    sys.stdout.flush()
    buf.write(frame)
    buf.flush()

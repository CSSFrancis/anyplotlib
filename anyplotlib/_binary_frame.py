"""
_binary_frame.py — a tiny length-prefixed binary wire format for shipping raw
image pixels to an Electron host without base64-in-JSON.

Used ONLY by the Electron transport (``_electron.py``); Jupyter / Pyodide /
standalone keep the base64-in-JSON path untouched. The format is a single
self-describing frame written to a byte stream (stdout), interleaved with the
existing text ``PLOTAPP:{json}\\n`` lines:

    PLOTBIN:<header_len>:<payload_len>\\n<header_json_bytes><payload_bytes>

- ``PLOTBIN:`` is the ASCII marker (distinct from ``PLOTAPP:``) so a host reading
  the raw stream can tell a binary frame from a text line.
- ``<header_len>`` / ``<payload_len>`` are ASCII decimal byte counts.
- ``<header_json_bytes>`` is UTF-8 JSON: ``{fig_id, key, ...metadata}`` (dims,
  dtype, clim — everything the renderer needs EXCEPT the pixels).
- ``<payload_bytes>`` is the raw payload (e.g. the single-channel uint8 image),
  exactly ``payload_len`` bytes, NO base64, NO JSON.

Both the Python producer and the JS host use this one definition, so the wire
format has a single source of truth and can be unit-tested in isolation (the
producer's ``encode_frame`` round-trips through ``decode_frame`` without any
Electron / stdout involved).
"""
from __future__ import annotations

import json

MARKER = b"PLOTBIN:"


def encode_frame(fig_id: str, key: str, header: dict, payload: bytes) -> bytes:
    """Serialise one binary frame to bytes (marker + lengths + header + payload).

    ``header`` is arbitrary JSON-able metadata; ``fig_id`` and ``key`` are merged
    in (so the decoder always recovers them). ``payload`` is the raw bytes."""
    hdr = dict(header or {})
    hdr["fig_id"] = fig_id
    hdr["key"] = key
    hdr_bytes = json.dumps(hdr, default=str).encode("utf-8")
    prefix = MARKER + f"{len(hdr_bytes)}:{len(payload)}\n".encode("ascii")
    return prefix + hdr_bytes + bytes(payload)


def decode_frame(buf: bytes):
    """Parse ONE complete frame from ``buf`` (as produced by ``encode_frame``).

    Returns ``(header_dict, payload_bytes, n_consumed)`` where ``n_consumed`` is
    the number of bytes the frame occupied. Raises ``ValueError`` if ``buf`` does
    not begin with a complete frame. (A streaming host uses ``parse_prefix`` +
    incremental reads instead; this is the whole-buffer convenience for tests.)"""
    if not buf.startswith(MARKER):
        raise ValueError("not a PLOTBIN frame")
    nl = buf.find(b"\n")
    if nl < 0:
        raise ValueError("incomplete PLOTBIN prefix (no newline)")
    prefix = buf[len(MARKER):nl].decode("ascii")
    hdr_len_s, pay_len_s = prefix.split(":")
    hdr_len, pay_len = int(hdr_len_s), int(pay_len_s)
    start = nl + 1
    end_hdr = start + hdr_len
    end_pay = end_hdr + pay_len
    if len(buf) < end_pay:
        raise ValueError("incomplete PLOTBIN frame (truncated body)")
    header = json.loads(buf[start:end_hdr].decode("utf-8"))
    payload = buf[end_hdr:end_pay]
    return header, payload, end_pay


def parse_prefix(line: bytes):
    """Parse a ``PLOTBIN:<hlen>:<plen>`` prefix line (the bytes up to, not
    including, the newline). Returns ``(header_len, payload_len)``. For a
    streaming host that reads the prefix line, then exactly ``header_len +
    payload_len`` more bytes."""
    if not line.startswith(MARKER):
        raise ValueError("not a PLOTBIN prefix")
    hdr_len_s, pay_len_s = line[len(MARKER):].decode("ascii").split(":")
    return int(hdr_len_s), int(pay_len_s)

"""
Binary transport wire format + Electron routing.

The PLOTBIN framing (_binary_frame) is the single source of truth shared by the
Python producer and the JS host, so it's unit-tested here in isolation — no
Electron, no stdout — plus the _electron routing that decides base64 vs binary.
Runs in the normal CI matrix.
"""
from __future__ import annotations

import base64
import importlib
import json

import numpy as np
import pytest

from anyplotlib import _binary_frame as bf


class TestFrameRoundTrip:
    def test_encode_decode_roundtrip(self):
        payload = np.arange(256, dtype=np.uint8).tobytes()
        frame = bf.encode_frame("fig1", "image_b64",
                                {"w": 16, "h": 16, "dtype": "uint8"}, payload)
        header, out, n = frame, None, 0
        header, out, n = bf.decode_frame(frame)
        assert header["fig_id"] == "fig1"
        assert header["key"] == "image_b64"
        assert header["w"] == 16 and header["h"] == 16
        assert out == payload
        assert n == len(frame)

    def test_payload_bytes_are_raw_not_base64(self):
        # The whole point: the payload on the wire is the raw bytes, not base64.
        payload = bytes([0, 255, 128, 7, 200])
        frame = bf.encode_frame("f", "image_b64", {}, payload)
        # The raw payload appears verbatim at the tail.
        assert frame.endswith(payload)
        # And it is NOT the base64 text of the payload.
        assert base64.b64encode(payload) not in frame

    def test_marker_and_prefix(self):
        payload = b"\x01\x02\x03\x04"
        frame = bf.encode_frame("f", "k", {"a": 1}, payload)
        assert frame.startswith(bf.MARKER)
        nl = frame.find(b"\n")
        hlen, plen = bf.parse_prefix(frame[:nl])
        assert plen == len(payload)
        # header_len covers the merged fig_id/key/metadata JSON.
        hdr = json.loads(frame[nl + 1:nl + 1 + hlen])
        assert hdr == {"a": 1, "fig_id": "f", "key": "k"}

    def test_binary_safe_payload(self):
        # A payload containing the marker bytes / newlines must survive (length-
        # prefixed, not delimiter-scanned).
        payload = bf.MARKER + b"\n:123:\nPLOTAPP:{}" + bytes(range(256))
        frame = bf.encode_frame("f", "k", {}, payload)
        header, out, n = bf.decode_frame(frame)
        assert out == payload

    def test_truncated_frame_raises(self):
        payload = b"abcdefgh"
        frame = bf.encode_frame("f", "k", {}, payload)
        with pytest.raises(ValueError):
            bf.decode_frame(frame[:-2])          # payload cut short

    def test_two_frames_concatenated(self):
        # A host reads frame 1, then continues at n_consumed for frame 2.
        f1 = bf.encode_frame("a", "k", {}, b"first")
        f2 = bf.encode_frame("b", "k", {}, b"second-longer")
        buf = f1 + f2
        h1, p1, n1 = bf.decode_frame(buf)
        assert p1 == b"first" and h1["fig_id"] == "a"
        h2, p2, n2 = bf.decode_frame(buf[n1:])
        assert p2 == b"second-longer" and h2["fig_id"] == "b"


class TestElectronRouting:
    def _reload_electron(self, monkeypatch, binary: bool):
        monkeypatch.setenv("APL_BINARY_TRANSPORT", "1" if binary else "0")
        import anyplotlib._electron as el
        importlib.reload(el)
        return el

    def _geom_value(self, pixels: np.ndarray) -> str:
        # The real wire shape: image_b64 nested in a panel geom JSON string.
        return json.dumps({
            "image_b64": base64.b64encode(pixels.tobytes()).decode(),
            "colormap_data": [[0, 0, 0]],
        })

    def test_geom_pixels_go_binary_when_enabled(self, monkeypatch):
        el = self._reload_electron(monkeypatch, binary=True)
        captured = {"json": []}
        monkeypatch.setattr(el, "emit_binary",
                            lambda *a: captured.setdefault("bin", a))
        monkeypatch.setattr(el, "emit", lambda o: captured["json"].append(o))

        pixels = np.arange(64, dtype=np.uint8)
        el._route_change("figX", "panel_p1_geom", self._geom_value(pixels))

        # Pixels shipped as a binary frame…
        assert "bin" in captured, "geom image_b64 should route to emit_binary"
        fig_id, key, header, raw = captured["bin"]
        assert key == "image_b64"
        assert header["geom"] == "panel_p1_geom"
        assert raw == pixels.tobytes()
        # …and the SLIMMED geom (pixels removed, LUT kept) goes as one JSON update.
        assert len(captured["json"]) == 1
        slim = json.loads(captured["json"][0]["value"])
        assert "image_b64" not in slim
        assert slim["colormap_data"] == [[0, 0, 0]]

    def test_geom_stays_base64_when_disabled(self, monkeypatch):
        el = self._reload_electron(monkeypatch, binary=False)
        captured = {"json": []}
        monkeypatch.setattr(el, "emit_binary",
                            lambda *a: captured.setdefault("bin", a))
        monkeypatch.setattr(el, "emit", lambda o: captured["json"].append(o))
        pixels = np.arange(64, dtype=np.uint8)
        geom = self._geom_value(pixels)
        el._route_change("figX", "panel_p1_geom", geom)
        assert "bin" not in captured
        assert captured["json"][0]["value"] == geom   # unchanged, pixels included

    def test_non_geom_key_never_binary(self, monkeypatch):
        el = self._reload_electron(monkeypatch, binary=True)
        captured = {"json": []}
        monkeypatch.setattr(el, "emit_binary",
                            lambda *a: captured.setdefault("bin", a))
        monkeypatch.setattr(el, "emit", lambda o: captured["json"].append(o))
        el._route_change("figX", "fig_width", 640)    # a small scalar trait
        assert "bin" not in captured
        assert captured["json"][0]["value"] == 640

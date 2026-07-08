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

    def test_detail_tile_goes_binary(self, monkeypatch):
        # The zoom DETAIL TILE must ship over PLOTBIN too — else with binary
        # transport on, its "\x00bin:" token stays in the geom JSON, the bytes are
        # never sent, and the renderer can't decode it → the crisp zoom tile never
        # displays (only the downsampled overview base shows). Regression for
        # detail_b64 missing from _BINARY_KEYS.
        el = self._reload_electron(monkeypatch, binary=True)
        assert "detail_b64" in el._BINARY_KEYS   # sanity: the key is registered
        captured = {"json": [], "bin": []}
        monkeypatch.setattr(el, "emit_binary",
                            lambda *a: captured["bin"].append(a))
        monkeypatch.setattr(el, "emit", lambda o: captured["json"].append(o))
        tile = np.arange(49, dtype=np.uint8)   # a 7x7 detail tile
        geom = json.dumps({
            "detail_b64": base64.b64encode(tile.tobytes()).decode(),
            "detail_region": [0, 7, 0, 7], "detail_width": 7, "detail_height": 7,
            "colormap_data": [[0, 0, 0]],
        })
        el._route_change("figX", "panel_p1_geom", geom)
        keys = [a[1] for a in captured["bin"]]
        assert "detail_b64" in keys, f"detail tile did not go binary: {keys}"
        # the slimmed geom drops the pixel key but keeps the small region metadata
        slim = json.loads(captured["json"][0]["value"])
        assert "detail_b64" not in slim
        assert slim["detail_region"] == [0, 7, 0, 7]


class TestRawPixelSideChannel:
    """The zero-copy fast path: set_data stashes RAW uint8 bytes on the Figure's
    _raw_pixels side-table + puts a tiny token in image_b64, and _route_change
    ships those bytes straight to PLOTBIN — no base64 encode/decode round-trip."""

    def _reload_electron(self, monkeypatch, binary: bool):
        monkeypatch.setenv("APL_BINARY_TRANSPORT", "1" if binary else "0")
        import anyplotlib._electron as el
        importlib.reload(el)
        return el

    def test_set_data_stashes_raw_bytes_and_tokenises(self, monkeypatch):
        # Binary transport ON: set_data must NOT base64-encode the pixels into
        # _state; it stashes raw bytes on the figure and leaves a token.
        monkeypatch.setenv("APL_BINARY_TRANSPORT", "1")
        import anyplotlib as apl
        fig, ax = apl.subplots(1, 1)
        img = np.arange(64, dtype=np.uint8).reshape(8, 8)
        p = ax.imshow(img)
        p.set_data(img.astype(float))

        tok = p._state["image_b64"]
        assert isinstance(tok, str) and tok.startswith("\x00bin:"), \
            "binary path should leave a change-token, not base64, in _state"
        raw = fig._raw_pixels.get((p._id, "image_b64"))
        assert raw is not None and len(raw) == 64, "raw bytes not stashed on figure"
        # to_state_dict passes the token through (wire form); resolve_pixel_tokens
        # materialises real base64 for a cold consumer (save_html / standalone).
        assert p.to_state_dict()["image_b64"] == tok
        st = p.resolve_pixel_tokens(p.to_state_dict())
        assert base64.b64decode(st["image_b64"]) == raw

    def test_route_change_ships_raw_bytes_no_reencode(self, monkeypatch):
        # A geom whose image_b64 is a TOKEN → _route_change must pull the bytes
        # from fig._raw_pixels (NOT base64-decode the token) and emit them raw.
        el = self._reload_electron(monkeypatch, binary=True)

        class _FakeFig:
            _raw_pixels = {("p1", "image_b64"): b"\x01\x02\x03\x04rawpixels"}
        monkeypatch.setitem(el._figures, "figX", _FakeFig())

        captured = {"json": []}
        monkeypatch.setattr(el, "emit_binary",
                            lambda *a: captured.setdefault("bin", a))
        monkeypatch.setattr(el, "emit", lambda o: captured["json"].append(o))

        geom = json.dumps({"image_b64": "\x00bin:12345",
                           "colormap_data": [[1, 2, 3]]})
        el._route_change("figX", "panel_p1_geom", geom)

        assert "bin" in captured, "token geom should route to emit_binary"
        _fig_id, key, header, raw = captured["bin"]
        assert key == "image_b64"
        assert raw == b"\x01\x02\x03\x04rawpixels", "must ship the side-table bytes verbatim"
        # slimmed geom drops the pixel key, keeps the LUT
        slim = json.loads(captured["json"][0]["value"])
        assert "image_b64" not in slim and slim["colormap_data"] == [[1, 2, 3]]

    def test_route_change_falls_back_to_base64_without_sidetable(self, monkeypatch):
        # Robustness: a REAL base64 geom (initial frame / no side-table entry)
        # still decodes correctly through the same path.
        el = self._reload_electron(monkeypatch, binary=True)
        captured = {"json": []}
        monkeypatch.setattr(el, "emit_binary",
                            lambda *a: captured.setdefault("bin", a))
        monkeypatch.setattr(el, "emit", lambda o: captured["json"].append(o))

        pixels = np.arange(16, dtype=np.uint8)
        geom = json.dumps({"image_b64": base64.b64encode(pixels.tobytes()).decode(),
                           "colormap_data": [[0, 0, 0]]})
        el._route_change("figY", "panel_pz_geom", geom)   # figY not in _figures
        assert "bin" in captured
        assert captured["bin"][3] == pixels.tobytes()

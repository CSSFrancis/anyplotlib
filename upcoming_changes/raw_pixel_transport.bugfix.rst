The Electron binary pixel transport now ships the RAW uint8 image bytes end to
end, instead of base64-encoding them in ``set_data`` only to base64-decode them
straight back in the routing layer. ``Plot2D.set_data`` stashes the raw bytes on
the Figure's ``_raw_pixels`` side-table and leaves a tiny content-checksum
change-token in ``image_b64``; ``_electron._route_change`` ships those bytes to a
PLOTBIN frame directly. This removes the ~20 ms base64 encode, the ~17 ms decode,
and the megabyte ``json.dumps`` of the pixel string from every scrub frame — a
2.2x faster ``set_data`` (≈98 ms → ≈44 ms on a 2048² frame) and ~25% less
bytes-on-wire. Non-Electron hosts (Jupyter / Pyodide / standalone / ``save_html``)
are unchanged: they have no PLOTBIN channel, so the token is resolved back to
inline base64 via ``Plot2D.resolve_pixel_tokens`` when the figure state is
serialised for them.

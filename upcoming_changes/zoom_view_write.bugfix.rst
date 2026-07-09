Interactive zoom/pan on a 2-D image no longer re-serialises (and re-transmits)
the full image on every mouse tick. The wheel/pan/orbit handlers write only the
light *view* state back to the ``panel_<id>_json`` trait now, excluding the
cached geometry (pixels, colormap LUT) that ``_applyGeom`` splices into the panel
state for drawing. Previously the whole frame was ``JSON.stringify``-d per tick —
catastrophically so on the binary transport, where the pixel buffer is a
``Uint8Array`` that stringifies to a ``{"0":..,"1":..}`` object with one key per
byte — which stalled zoom on large images.

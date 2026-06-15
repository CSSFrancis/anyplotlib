Heavy plot geometry now travels on a separate sync channel and is
re-transmitted only when it actually changes.  ``Plot2D`` and ``Plot3D``
panels split their large, slow-changing state (vertex/face/image buffers,
per-point colours, colormap LUTs) into a ``panel_<id>_geom`` trait keyed by
a content hash; the light view payload references it by revision and the JS
renderer splices the cached geometry back in.  Consequently view-only
updates — ``set_highlight``, ``set_view``, ``set_zoom``, plane-widget drags,
titles — no longer re-send the panel's geometry.  Combined with
``Figure.batch()`` coalescing, the voxel grain explorer's per-crosshair
wire traffic drops ~65% (1155 -> 400 KB/frame at 192-cubed), the main
source of Pyodide lag.  Plots that declare no geometry keys (e.g. ``Plot1D``)
keep the prior single-trait behaviour unchanged.

:meth:`PlotXY.pcolormesh` now renders a **regular, uniformly spaced scalar
mesh** as a single stretched RGBA raster instead of one polygon per cell — the
fast path for dense orientation-density / IPF heatmaps. Irregular meshes,
colour-string ``c``, or an explicit ``edgecolor`` keep the per-cell polygon
path. The win is twofold: the image is encoded once and travels on the deduped
geometry channel (a view-only pan/zoom never re-transmits it), and the renderer
blits it in a single ``drawImage`` whose cost is independent of cell count —
so a 256×256 heatmap draws as fast as a 32×32 one.

The underlying primitive is exposed directly as :meth:`PlotXY.add_raster`
(also on :class:`Plot1D`): an RGBA image drawn between data-coordinate
``extent`` corners, with an optional ``clip_path`` polygon (e.g. the curved
fundamental-sector boundary). Image bytes ride the geometry channel
(``Plot1D._GEOM_KEYS``) and the decoded bitmap is cached on the marker set.
Pass ``smooth=True`` (on either ``add_raster`` or ``pcolormesh``) to bilinearly
interpolate the raster for a continuous heat field; the default keeps crisp
nearest-neighbour cells.

New example ``Examples/Interactive/plot_ipf_density_map.py`` — a linked IPF
orientation map + density heat map where the modal (peak-density) bin is the
"best-fit" orientation, ringed on the IPF and highlighted on the map.

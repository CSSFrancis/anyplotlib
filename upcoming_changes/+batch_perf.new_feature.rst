``Figure.batch()`` coalesces panel pushes: every plot mutation inside the
``with fig.batch():`` block is serialised and transferred at most once per
panel when the block exits, instead of once per mutation.  Linked-view
handlers (e.g. the voxel grain explorer's crosshairs, which touch 5 panels
per mouse event) drop from ~8 full-state pushes per frame to one per changed
panel — a large reduction in comm traffic that removes most of the lag under
Pyodide and remote kernels.  ``set_highlight`` / ``set_view`` / ``set_zoom``
on 3-D panels now route through this coalescing path so re-aiming the camera
or moving the highlight never re-transmits the panel's (potentially hundreds
of KB) unchanged geometry.  RGB ``imshow`` updates also skip the unused
colormap-LUT rebuild.

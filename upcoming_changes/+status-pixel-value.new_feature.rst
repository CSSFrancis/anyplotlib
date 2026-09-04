The 2-D hover readout now also names the **value** of the pixel under the
cursor — ``v:<value>`` for a colourmapped image, ``rgb:r,g,b`` for a true-colour
one — alongside the existing physical and pixel coordinates. It is exact:
integer data whose range fits the 256 transferred codes is inverted locally,
and for anything wider the renderer asks Python for the true value once the
cursor dwells on a pixel (``imshow(..., probe_exact=True)`` by default, tunable
via :meth:`~anyplotlib.Plot2D.set_value_probe`), falling back to the quantised
estimate when no kernel can answer. Zoomed into a detail tile the value comes
from the tile's native pixels rather than the coarser overview.
The **v** key toggles the on-image pill, and
:meth:`~anyplotlib.Plot2D.set_readout_visible` turns it off from Python while
keeping the readout live: embedding hosts receive every update through
``mount()``'s ``opts.onReadout`` callback and an ``apl:readout`` DOM event — so
an Electron app can render position and value in its own status bar instead,
where it covers no data. 2-D pointer events also carry ``img_x``/``img_y`` now,
the cursor's position in image pixels.

``Plot2D.set_overlay_mask`` now works in TILE mode. The renderer sizes the mask
against ``base_width || image_width`` -- the tile overview grid -- but tile mode
sets ``image_width`` to the full native frame, so the shape check accepted only
the one shape the renderer silently discards (``maskCache = null``, no error) and
rejected the one that actually renders. On a 4096x4096 tiled plot neither a
1024x1024 nor a 4096x4096 mask could be drawn: the first raised ``ValueError``,
the second encoded 22.4 MB the renderer dropped. Both shapes are now accepted and
a full-resolution mask is reduced to the overview grid with a block ANY -- never
a subsample, so an object a few pixels across cannot vanish into a skipped
sample.

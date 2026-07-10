Tile mode: a data update while zoomed in (``update_tile_source`` with a detail
tile shown) refreshes only the detail tile, leaving the overview base on the
old frame — zooming out then flashed the pre-update frame. The skipped
overview is now marked stale and re-sampled once on the next view settle
(riding the same push as the detail/clear), preserving the per-frame skip
optimisation while never exposing stale base pixels.

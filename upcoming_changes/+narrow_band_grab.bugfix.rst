Fixed the band-style :class:`~anyplotlib.widgets.RangeWidget` being impossible
to drag by its body when narrow. Each edge claimed a fixed ±12 px grab zone, so
a band under ~24 px wide on screen (routine when zoomed out, or when its span is
capped) had no grabbable middle: aiming at the body to translate the band caught
an edge and resized it instead. Each edge now takes at most a third of the
band's width, leaving the middle third for the move handle. Wide bands are
unaffected.

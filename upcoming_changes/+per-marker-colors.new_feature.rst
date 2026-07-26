``edgecolors`` and ``facecolors`` accept a sequence of colours parallel to the
markers — matplotlib's ``edgecolors=[...]`` / scatter ``c=[...]`` — for every
marker type on both 1-D and 2-D panels, where previously only ``points`` and
``polygons`` on 1-D panels honoured it.  A short sequence cycles.

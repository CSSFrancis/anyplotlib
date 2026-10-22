Added rotation, anchor alignment and ``$...$`` TeX typesetting to ``texts``
markers (wire fields ``rotation`` in radians, ``halign``, ``valign``):
labels anchor at their offset point, rotate counter-clockwise like
matplotlib's, and math markup renders through the existing axis-label TeX
engine instead of showing raw dollars.

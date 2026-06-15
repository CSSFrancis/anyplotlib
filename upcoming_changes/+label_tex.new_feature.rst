Axis labels, titles, and colorbar labels now accept a ``fontsize`` keyword
(``set_xlabel("...", fontsize=14)``), and a new ``set_tick_label_size()``
controls tick-number size. Label strings support a mini-TeX subset inside
``$...$`` — superscripts (``$10^{-3}$``), subscripts (``$E_F$``), Greek
letters, and common symbols (``\times``, ``\AA``, ``\degree``) — rendered
natively on the canvas. Logarithmic tick labels now draw true superscripts.

Text is never clipped: the 2D title strip grows to fit large or TeX titles,
the colorbar (strip + label) now reserves real layout space instead of
overflowing the panel edge, rotated y-labels stay inside their gutter at any
size, and edge tick labels are nudged inward rather than cut off.

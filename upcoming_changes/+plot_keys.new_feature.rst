Added :meth:`~anyplotlib.Plot2D.add_key` for pinning a floating image *key* over
a panel — an inverse pole figure triangle over an orientation map, a hue wheel
over a polarization field, a phase key over a segmentation.  A key is the scale
bar's sibling: it floats in screen space and neither pans nor zooms with the
data, it takes an RGBA image so a triangle or a disc needs no rectangular card
around it, and ``labels=`` annotates the picture itself (an IPF triangle's
corner indices) in fractions of the key image.  Optional ``bgcolor`` /
``border`` / ``alpha`` give it a card when the data underneath is busy, and
``hover_only=True`` reveals it only while the pointer is over the panel.
Available on every panel type, and included in PNG export.

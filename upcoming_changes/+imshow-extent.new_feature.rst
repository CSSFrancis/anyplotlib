Added ``extent=(left, right, bottom, top)`` to :meth:`Axes.imshow
<anyplotlib.Axes.imshow>` and :meth:`Plot2D.set_extent_edges
<anyplotlib.Plot2D.set_extent_edges>`, which calibrate an image from its
outer edges the way matplotlib's ``imshow(extent=...)`` does.

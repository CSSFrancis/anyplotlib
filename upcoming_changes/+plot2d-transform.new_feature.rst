Added :attr:`~anyplotlib.Plot2D.transform` (an :class:`~anyplotlib.ImageTransform`),
:meth:`~anyplotlib.Plot2D.data_to_pixel`, :meth:`~anyplotlib.Plot2D.pixel_to_data`
and read-only :attr:`~anyplotlib.Plot2D.x_axis` / :attr:`~anyplotlib.Plot2D.y_axis`
for converting between calibrated data units and the image-pixel coordinates
that 2-D widgets and markers use, including offset, non-unit, descending and
non-uniform axes.

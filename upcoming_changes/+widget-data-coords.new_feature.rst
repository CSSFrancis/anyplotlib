Added ``coords="data"`` to every :class:`~anyplotlib.Plot2D` ``add_*_widget``
method (and :meth:`~anyplotlib.Plot2D.add_widget`): the widget then takes and
reports its geometry — attribute reads, :meth:`~anyplotlib.Widget.get`,
:meth:`~anyplotlib.Widget.to_dict`, :meth:`~anyplotlib.Widget.set` and so the
values seen in drag callbacks — in the panel's calibrated axis units instead
of image pixels.  See :attr:`~anyplotlib.Widget.coords` and
:meth:`~anyplotlib.Widget.set_coords`; 1-D and bar widget methods accept
``coords="data"`` too.

Added ``coords="data"`` to the :class:`~anyplotlib.Plot2D` marker methods and
:meth:`MarkerRegistry.add <anyplotlib.markers.MarkerRegistry.add>`: positions
and data-sized lengths are then given in the panel's calibrated axis units
and converted to image pixels on every render, so the markers follow
:meth:`~anyplotlib.Plot2D.set_extent`.  See
:attr:`MarkerGroup.coords <anyplotlib.markers.MarkerGroup.coords>`.

The colorbar strip is no longer drawn flush against the image: there is now a
6 px gap, taken out of the image width so the strip cannot be pushed off the
panel, and settable with :meth:`~anyplotlib.Plot2D.set_colorbar_pad`.  This
shifts every colorbar plot by 4 px.

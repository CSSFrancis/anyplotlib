:meth:`~anyplotlib.Figure.save_html`, :func:`~anyplotlib.embed.to_html` and
:func:`~anyplotlib.embed.figure_state` now capture the view the reader is
actually looking at. Zoom, pan, orbit and the colorbar / scale-mode shortcuts
are applied in the browser and written back to the panel traits, but nothing on
the Python side read them back, so every snapshot silently reset the figure to
the view it was created with. Those keys are now reconciled into the plot state
before a snapshot is taken.

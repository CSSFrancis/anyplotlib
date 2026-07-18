Insets can now be dragged and resized directly in the renderer's edit mode
(``edit_chrome``): drag the body to move an inset (a corner-stacked inset
converts to a free anchor and its siblings re-stack), or drag the bottom-right
grip to resize it (min 64 px per dimension). On release the renderer emits a
new figure-level ``inset_geometry_change`` event carrying the final
``anchor``/``w_frac``/``h_frac`` (figure fractions), which
:meth:`~anyplotlib.figure.Figure.add_event_handler` handlers can observe to
persist the layout. The same geometry is applied programmatically via the new
:meth:`~anyplotlib.axes.InsetAxes.set_geometry` (``anchor``, ``w_frac``,
``h_frac``). Off edit mode the affordances are hidden and the inset is inert.

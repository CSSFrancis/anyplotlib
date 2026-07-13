Extended :class:`~anyplotlib.Figure` edit-mode interaction:

* Circle and rectangle overlay widgets are now **resizable via visible nodes** —
  a circle draws a centre (move) node and an east-point radius node; a rectangle
  draws all four corner nodes (opposite corner anchored on drag).  Drawn only
  when ``show_handles`` is ``True``, with matching resize cursors.
* :class:`~anyplotlib.widgets.ArrowWidget` **tail is now a reshape node**:
  dragging the tail moves it while the head stays anchored (dragging the shaft
  still moves the whole arrow; the head node still re-aims it).
* The selected-panel and hover **outlines are fully inset** (``outline-offset:
  -2px``) so an edge/corner panel's ring is no longer clipped at the figure's
  right/bottom edge.
* **Panel drag-swap** under ``edit_chrome``: each grid panel shows a move grip
  in its top-left corner; dragging it over a *different* panel emits a
  figure-level ``pointer_up`` event with ``panel_swap: true`` and
  ``source_panel_id`` / ``target_panel_id`` (new :class:`~anyplotlib.Event`
  fields).  anyplotlib performs no layout change itself — the host swaps and
  rebuilds.  Releasing on the source panel or empty space cancels cleanly; the
  grip is inert when ``edit_chrome`` is off.
* The JS ``mount()`` embedding entry point accepts an ``onResize({width,
  height})`` callback, fired (debounced) when the **root container resizes**, so
  an embedding host can relayout the figure to its new box.

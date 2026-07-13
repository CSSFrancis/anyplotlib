Added figure-level edit-mode chrome to :class:`~anyplotlib.Figure`: the
``edit_chrome`` and ``selected_panel`` traits (per-panel hover / selection
outlines), figure-background click events, and a figure-level annotation layer
(``set_figure_markers`` / ``figure_markers``, positioned in figure fractions and
always included in ``exportPNG``) with figure-level callbacks via
``add_event_handler``.

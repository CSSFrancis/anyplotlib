Added :meth:`Figure.on_close <anyplotlib.Figure.on_close>`, the
:attr:`~anyplotlib.Figure.closed` and :attr:`~anyplotlib.Figure.displayed`
flags and an idempotent :meth:`Figure.display <anyplotlib.Figure.display>`;
:meth:`~anyplotlib.Figure.close` now also fires ``close`` on the figure's own
callbacks (before the panels'), and still hides the figure if a handler raises.

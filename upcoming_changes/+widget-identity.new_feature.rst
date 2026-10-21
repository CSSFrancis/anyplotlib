Added read-only :attr:`~anyplotlib.Widget.plot` (the owning plot, ``None``
once removed) and :attr:`~anyplotlib.Widget.kind` (``"rectangle"``,
``"vline"``, …) so code holding only a widget handle can find its plot and
type without private attributes.

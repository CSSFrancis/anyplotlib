Added a public ``notify`` keyword to :meth:`~anyplotlib.Widget.set`
(``widget.set(x=..., notify=False)``) to move a widget from Python without
firing its ``pointer_move`` handlers; ``_notify`` remains as an alias.

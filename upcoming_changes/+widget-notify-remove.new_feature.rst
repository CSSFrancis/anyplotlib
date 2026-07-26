:meth:`Widget.set` takes ``_notify=False`` to move a widget without firing
``pointer_move`` callbacks, so a handler that writes back to its own widget no
longer feeds into itself.  Widgets also gained a
:meth:`~anyplotlib.widgets.Widget.remove` method.

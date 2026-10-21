Fixed :meth:`~anyplotlib.callbacks._EventMixin.add_event_handler` raising
``AttributeError`` for bound methods, and made ``remove_handler(obj.method)``
find a handler registered as ``obj.method``.

:meth:`Figure.close <anyplotlib.Figure.close>` now runs the figure-level and
each panel's ``close`` handlers independently: a handler that raises no
longer skips the remaining ones.  The figure is still marked closed and
hidden, and the first exception is re-raised once all handlers have run.

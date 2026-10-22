:meth:`Figure.get_axes <anyplotlib.Figure.get_axes>` now lists every grid
axes the figure created, including ones with no plot attached yet, as
matplotlib does — so ``fig, ax = apl.subplots(1, 1); fig.get_axes()[0] is ax``.
Floating insets are still not listed.

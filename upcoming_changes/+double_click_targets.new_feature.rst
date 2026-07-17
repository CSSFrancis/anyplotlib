Double-clicking a plot's text chrome now reports which element was hit. The
``double_click`` :class:`~anyplotlib.callbacks.Event` gains a ``target`` field
naming the hit element — one of ``'title'``, ``'x_label'``, ``'x_ticks'``,
``'y_label'``, ``'y_ticks'``, ``'colorbar_label'`` or ``'legend'`` — so a host
can open the right edit affordance for the axis label vs the ticks vs the title
vs the colorbar label vs the legend. The axis gutters, colorbar strip and title
band each get their own hit-test (2-D panels emit from the separate axis/title
canvases; 1-D panels zone-split the single canvas around the plot rect and
legend box). A plain plot-area double-click is unchanged and carries no
``target`` (``event.target is None``), so existing handlers keep working.

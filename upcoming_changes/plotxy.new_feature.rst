Added :meth:`Axes.axes2d` / :class:`PlotXY` — a blank **data-coordinate
2-D axis** (matplotlib ``transData`` + ``PathCollection`` model). Set
``xlim``/``ylim`` (+ ``aspect="equal"``) and draw ``scatter``/``plot``/``fill``/
``text`` as collection-style artists in data coords — the surface needed for
stereographic / IPF / pole-figure plots (e.g. an orix plotting backend).

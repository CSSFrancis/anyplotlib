Added :meth:`Axes.axes2d` / :class:`PlotXY` — a blank **data-coordinate
2-D axis** (matplotlib ``transData`` + ``PathCollection`` model). Set
``xlim``/``ylim`` (+ ``aspect="equal"``) and draw ``scatter``/``plot``/``fill``/
``text`` as collection-style artists in data coords — the surface needed for
stereographic / IPF / pole-figure plots (e.g. an orix plotting backend).
``scatter(c=[...])`` honours per-point face/edge colours, and ``aspect="equal"``
applies matplotlib's ``apply_aspect`` in the renderer (the panel box is shrunk
and centred so one data unit spans equal pixels on x and y).
:meth:`PlotXY.pcolormesh` draws a data-coord quad mesh (per-cell colours via a
polygon ``PathCollection``); masked / non-finite cells are skipped, so an
``orix`` pole-density histogram renders natively as an IPF density heatmap. A
marker group (and ``pcolormesh``) accepts a ``clip_path`` — a data-coord polygon
the group is clipped to (matplotlib ``set_clip_path``), e.g. the curved sector
boundary so the mesh's edge cells don't overflow it.

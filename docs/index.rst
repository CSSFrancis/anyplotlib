========================
anyplotlib Documentation
========================

anyplotlib is a lightweight, interactive plotting library for Jupyter notebooks and JupyterLab,
backed by `anywidget <https://anywidget.dev/>`_ and a pure-JavaScript canvas renderer. It follows
the object-oriented Matplotlib API — create a ``Figure``, call methods on ``Axes`` — while
delivering real-time interactivity and high performance on large datasets through canvas-based
blitting instead of SVG.

.. grid:: 2 3 3 3
   :gutter: 2

   .. grid-item-card::
      :link: getting_started
      :link-type: doc

      :octicon:`rocket;2em;sd-text-info` Getting Started
      ^^^

      New to anyplotlib? The getting started guide walks through installation and
      your first interactive figure in a Jupyter notebook.

   .. grid-item-card::
      :link: api/index
      :link-type: doc

      :octicon:`code-square;2em;sd-text-info` API Reference
      ^^^

      Full documentation of the anyplotlib API — ``Figure``, ``Axes``, plot classes,
      markers, widgets, and callbacks — with parameter descriptions and type signatures.

   .. grid-item-card::
      :link: auto_examples/index
      :link-type: doc

      :octicon:`zap;2em;sd-text-info` Examples
      ^^^

      Gallery of short, self-contained examples showing 1-D signals, 2-D images,
      3-D surfaces, bar charts, interactive widgets, and more.

.. toctree::
   :hidden:
   :maxdepth: 2

   getting_started
   api/index
   auto_examples/index

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`

========================
anyplotlib Documentation
========================

anyplotlib is a lightweight, interactive plotting library for Jupyter notebooks and JupyterLab,
backed by `anywidget <https://anywidget.dev/>`_ and a pure-JavaScript canvas renderer. It follows
the object-oriented Matplotlib API — create a ``Figure``, call methods on ``Axes`` — while
delivering real-time interactivity and high performance on large datasets through canvas-based
blitting instead of SVG.

.. grid:: 2
   :gutter: 3

   .. grid-item::
      :columns: 7

      .. anywidget-figure:: ../Examples/Interactive/plot_3d_spectral_viewer.py
         :width: 100%
         :height: 400px
         :interactive:

   .. grid-item::
      :columns: 5

      .. raw:: html

         <p style="margin-top:1rem;margin-bottom:4px;font-weight:600;color:var(--pst-color-primary,#0d6efd);">
           ⚡ Try it out — no install needed
         </p>
         <p style="margin-top:0;font-size:0.9em;color:var(--pst-color-text-muted,#6c757d);">
           Drag the crosshair to update the spectrum live &middot;
           press <kbd>i</kbd> on the image to switch to an 8&times;8 integration window &middot;
           press <kbd>s</kbd> on the spectrum to filter the image by energy range.
         </p>


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

   .. grid-item-card::
      :link: auto_examples/Benchmarks/plot_benchmark_comparison
      :link-type: doc

      :octicon:`graph;2em;sd-text-info` Performance
      ^^^

      Why anyplotlib is fast: compact binary encoding, browser-side LUT
      colormapping, canvas blitting, and incremental traitlet pushes —
      plus an honest look at current limitations.

   .. grid-item-card::
      :link: benchmarking
      :link-type: doc

      :octicon:`tools;2em;sd-text-info` Benchmarking
      ^^^

      Developer guide: running the Python and JS benchmark suites, updating
      baselines, best practices, and the CI strategy that makes timing
      comparisons hardware-agnostic.

   .. grid-item-card::
      :link: dev/index
      :link-type: doc

      :octicon:`people;2em;sd-text-info` Developer Docs
      ^^^

      Contributing guide: environment setup, architecture overview, writing
      tests, Sphinx documentation, and interactive Sphinx Gallery examples.

.. toctree::
   :hidden:
   :maxdepth: 2

   getting_started
   api/index
   auto_examples/index
   Performance <auto_examples/Benchmarks/plot_benchmark_comparison>
   benchmarking
   dev/index

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`

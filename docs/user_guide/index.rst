==============
User Guide
==============

The user guide walks through using anyplotlib in a Jupyter notebook or
JupyterLab — from installation to interactive event handling and exporting
figures.

.. toctree::
   :hidden:
   :maxdepth: 2

   getting_started
   events
   embedding
   exporting

.. grid:: 2
   :gutter: 2

   .. grid-item-card::
      :link: getting_started
      :link-type: doc

      :octicon:`rocket;2em;sd-text-info` Getting Started
      ^^^

      Installation and your first interactive figure in a Jupyter
      notebook — creating a ``Figure``, calling methods on ``Axes``,
      and displaying it.

   .. grid-item-card::
      :link: events
      :link-type: doc

      :octicon:`zap;2em;sd-text-info` Event System
      ^^^

      Interactive event handling — ``pointer_down``, ``pointer_settled``,
      ``key_down``, and more. Includes a comparison with Matplotlib and
      pygfx and an implementation-status table.

   .. grid-item-card::
      :link: embedding
      :link-type: doc

      :octicon:`package;2em;sd-text-info` Embedding
      ^^^

      Using anyplotlib outside Jupyter — Electron apps, web pages, and
      live Python↔JS synchronisation from a standalone Python process.

   .. grid-item-card::
      :link: exporting
      :link-type: doc

      :octicon:`download;2em;sd-text-info` Exporting Images
      ^^^

      Saving and copying figures as PNG — the right-click menu, ``Ctrl+C``,
      light/dark output, native-resolution export, ``Figure.savefig``, and
      adding your own save formats from an embedding application.

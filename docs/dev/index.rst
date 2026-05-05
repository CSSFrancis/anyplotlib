=======================
Developer Documentation
=======================

This guide covers everything you need to contribute to anyplotlib —
from setting up your environment to writing documentation and interactive
gallery examples.

.. contents:: On this page
   :local:
   :depth: 2

----

Environment Setup
=================

anyplotlib uses `uv <https://github.com/astral-sh/uv>`_ for dependency
management.

.. code-block:: bash

   # Clone and install all dev dependencies
   git clone https://github.com/CSSFrancis/anyplotlib.git
   cd anyplotlib
   uv sync

   # Run the full test suite
   uv run pytest tests/

   # Quick smoke tests (no pytest overhead)
   uv run python test_figure.py
   uv run python test_pcolormesh.py

The ``dev`` dependency group (declared in ``pyproject.toml``) pulls in
``pytest``, ``playwright``, ``sphinx``, ``docutils``, and other tools
needed for both tests and docs builds.

----

Architecture Overview
=====================

The library is split into a small number of focused modules.

.. list-table::
   :header-rows: 1
   :widths: 25 75

   * - File
     - Purpose
   * - ``figure.py``
     - ``Figure`` — the only ``anywidget.AnyWidget`` subclass.
       Owns all traitlets and is the Python ↔ JS bridge.
   * - ``figure_plots.py``
     - ``Plot2D``, ``Plot1D``, ``PlotMesh``, ``Plot3D``, ``Axes``,
       ``GridSpec``, ``subplots()``.  Plain Python classes — *no* traitlets.
   * - ``figure_esm.js``
     - Pure-JS canvas renderer (≈ 4 000 lines).
   * - ``markers.py``
     - Static visual overlays (circles, arrows, lines, etc.).
   * - ``widgets.py``
     - Interactive draggable overlays (``RectangleWidget``,
       ``CrosshairWidget``, etc.).
   * - ``callbacks.py``
     - Multi-tier event system (``on_change`` / ``on_release``).
   * - ``sphinx_anywidget/``
     - Sphinx extension for interactive docs via Pyodide.

**Python → JS flow:** ``plot._push()`` → ``figure._push(panel_id)`` →
serialises ``_state`` to JSON → writes to the dynamic traitlet
``panel_{id}_json`` (``sync=True``) → JS observer re-renders.

**JS → Python flow:** JS writes back to ``panel_{id}_json`` after a drag →
Python observer calls ``Widget._update_from_js()`` and fires callbacks.

----

Running & Writing Tests
=======================

Tests live in ``tests/``

Run the full suite::

   uv run pytest tests/

Run a specific module::

   uv run pytest tests/test_sphinx_anywidget.py -v

The Playwright end-to-end tests (``test_pyodide_e2e.py``) require the
Playwright browsers.  Install them once with::

   uv run playwright install chromium

----

Writing Sphinx Documentation
=============================

The docs are built with `Sphinx <https://www.sphinx-doc.org/>`_ using the
`pydata-sphinx-theme <https://pydata-sphinx-theme.readthedocs.io/>`_.

.. code-block:: bash

   # Build HTML docs (outputs to build/html/)
   make html

   # Wipe build artefacts and rebuild from scratch
   make clean && make html

The conf.py lives at ``docs/conf.py`` and already registers these
extensions:

* ``sphinx.ext.autodoc`` / ``autosummary`` — API reference from docstrings.
* ``sphinx_gallery.gen_gallery`` — auto-generates the Examples gallery.
* ``anyplotlib.sphinx_anywidget`` — interactive Pyodide figures.
* ``sphinx_design`` — grid cards used on the index page.

Adding a new RST page
---------------------

1. Create ``docs/my_page.rst``.
2. Add it to the ``toctree`` in ``docs/index.rst``::

      .. toctree::
         :hidden:
         :maxdepth: 2

         my_page

Embedding a static figure in RST
---------------------------------

Use the ``.. anywidget-figure::`` directive to embed an anyplotlib figure
directly from a Python script, without Sphinx Gallery::

   .. anywidget-figure:: ../Examples/PlotTypes/plot_image2d.py

The directive executes the script, captures the widget, renders it as a
self-contained iframe, and embeds it in the page.

Embedding an interactive figure in RST
----------------------------------------

Add the ``:interactive:`` flag to enable the ⚡ Pyodide activation badge::

   .. anywidget-figure:: ../Examples/PlotTypes/plot_image2d.py
      :interactive:

When a reader clicks the badge, Pyodide boots in the browser, installs the
anyplotlib wheel that was built at docs-build time, re-executes the script,
and re-wires all live callbacks — no server required.

You can also control the display width::

   .. anywidget-figure:: ../Examples/PlotTypes/plot_image2d.py
      :interactive:
      :width: 500

Declaring extra Pyodide packages
---------------------------------

If your example script needs additional pure-Python packages available in
Pyodide, declare them at the top of the file::

   _PYODIDE_PACKAGES = ["scipy", "scikit-image"]

The ``sphinx_anywidget`` extension (and the Sphinx Gallery scraper) detect
this list automatically and pass it to ``micropip`` before executing the
example.

----

Writing Sphinx Gallery Examples
================================

All gallery examples live under ``Examples/`` and are picked up by
Sphinx Gallery.  Sub-directories become gallery sections.

.. code-block:: text

   Examples/
     README.rst          ← gallery landing-page text
     PlotTypes/          ← "Plot Types" section
       README.rst
       plot_image2d.py
       plot_spectra1d.py
       ...
     Interactive/
     Markers/
     Widgets/
     Benchmarks/

Naming rules
------------

* Files **must** be named ``plot_*.py`` — Sphinx Gallery ignores anything
  else (controlled by ``filename_pattern = r"/plot_"`` in ``conf.py``).
* Each sub-directory needs a ``README.rst`` for the section heading.

Docstring structure
-------------------

Every example file must start with a module-level docstring.  Sphinx
Gallery uses the first heading as the gallery card title::

   """
   My Example Title
   ================

   A short description shown in the gallery card.  Can span multiple
   paragraphs and use any RST.
   """

   import numpy as np
   import anyplotlib as apl

   fig, ax = apl.subplots(1, 1, figsize=(400, 300))
   ax.plot(np.sin(np.linspace(0, 6, 200)))
   fig

Sectioning code with ``# %%``
------------------------------

Split an example into multiple narrative sections using ``# %%`` comments.
Everything after ``# %%`` up to the next ``# %%`` (or end of file) is a
separate code block with its own prose cell::

   # %%
   # Adjusting the colour map
   # -------------------------
   # :meth:`~anyplotlib.figure_plots.Plot2D.set_colormap` switches the palette.

   v.set_colormap("viridis")
   fig

Making a gallery figure interactive
------------------------------------

To enable the ⚡ Pyodide activation badge on a gallery figure, end the
code block that produces the widget with a ``# Interactive`` comment
(case-insensitive)::

   fig, ax = apl.subplots(1, 1, figsize=(640, 400))
   ax.imshow(data, cmap="inferno")
   fig  # Interactive

The ``AnywidgetScraper`` (registered in ``conf.py`` as an
``image_scrapers`` entry) detects the comment and:

1. Embeds the full example source in a ``<script type="text/x-python">``
   tag inside the rendered HTML page.
2. Adds an ⚡ activation badge to the figure iframe.

Without the comment the figure is rendered as a plain static iframe.

.. note::

   Only **one** code block per example file needs (or should have) the
   ``# Interactive`` tag — typically the first block that produces the
   main figure.  Subsequent ``# %%`` sections render as plain static
   iframes.

How the scraper and thumbnail pipeline work
--------------------------------------------

The ``ViewerScraper`` (an alias for ``AnywidgetScraper``) is called by
Sphinx Gallery for every code block that produces an output.  It:

1. Launches a headless Chromium browser (via Playwright) to render a
   dark-theme PNG thumbnail.
2. Writes a self-contained iframe HTML file to
   ``docs/_static/viewer_widgets/<fig_id>.html``.
3. Returns RST containing a ``.. raw:: html`` iframe block, and — when
   interactive — an additional ``<script type="text/x-python">`` block
   with the full example source embedded as a JSON-escaped attribute.

The Pyodide bridge (``anywidget_bridge.js``) listens for the activation
click, boots Pyodide, installs the ``anyplotlib`` wheel, re-runs the
source, and postMessages trait updates into the matching iframe.

Complete minimal example
-------------------------

.. code-block:: python

   """
   Sine Wave
   =========

   A simple animated sine wave demonstrating the 1-D plot API.
   """
   # _PYODIDE_PACKAGES = []   # no extra deps needed

   import numpy as np
   import anyplotlib as apl

   x = np.linspace(0, 2 * np.pi, 500)

   fig, ax = apl.subplots(1, 1, figsize=(500, 300))
   ax.plot(x, np.sin(x), color="#4fc3f7", linewidth=2)
   fig  # Interactive

   # %%
   # Adding a second harmonic
   # ------------------------
   # Overlay a second plot object on the same axes.

   ax.plot(x, 0.5 * np.sin(2 * x), color="#ff6e40", linewidth=1)
   fig

----

Changelog Management
====================

anyplotlib uses `towncrier <https://towncrier.readthedocs.io/>`_ for
changelogs.  Add a news fragment for every user-visible change:

.. code-block:: bash

   # <issue_number>.<type>.rst  where type is one of:
   #   new_feature | bugfix | deprecation | removal | doc | maintenance
   echo "- Fixed the thing." > upcoming_changes/42.bugfix.rst

   # Preview what the next changelog entry will look like
   uv run towncrier --draft

   # Build the changelog (done by maintainers before a release)
   uv run towncrier build --version 0.2.0

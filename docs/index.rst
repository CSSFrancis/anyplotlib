viewer
======

.. toctree::
   :maxdepth: 2
   :caption: Contents

   getting_started
   api/index
   auto_examples/index

Welcome to **viewer** – a lightweight, interactive viewer for 1-D signals and
2-D images, backed by `anywidget <https://anywidget.dev/>`_ and a pure-JavaScript
canvas renderer.

The two main classes are:

* :class:`~viewer.viewer1d.Viewer1D` – an interactive 1-D line-plot widget.
* :class:`~viewer.viewer2d.Viewer2D` – an interactive 2-D image widget with
  histogram, colour-map controls, and overlay support.

Both widgets render inside any Jupyter / JupyterLab session and fall back to a
static PNG thumbnail in environments that only support ``image/png`` (e.g.
PyCharm notebook preview).

Indices and tables
------------------

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`


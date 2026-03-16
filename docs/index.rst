anyplotlib
==========

.. toctree::
   :maxdepth: 2
   :caption: Contents

   getting_started
   api/index
   auto_examples/index

Welcome to **anyplotlib** – a lightweight, interactive viewer for 1-D signals and
2-D images, backed by `anywidget <https://anywidget.dev/>`_ and a pure-JavaScript
canvas renderer.  The goal is to duplicate and extend the interactive plotting capabilities of Matplotlib,
although the scope is intentionally limited in the following ways:

1. This uses the object-oriented API of Matplotlib, not the stateful pyplot interface. This means there is
   no ``plt.imshow`` or ``plt.plot`` — instead, you create a figure object and call methods on axes to add
   data and customize the plot. This is a deliberate choice to avoid the pitfalls of the stateful API.

   .. code-block:: python

      import anyplotlib as apl
      import matplotlib.pyplot as plt

      # matplotlib:
      fig, axs = plt.subplots(1, 1)
      axs.imshow(...)

      # anyplotlib equivalent:
      fig, axs = apl.subplots(1, 1)
      axs.imshow(...)

2. In matplotlib they use vector graphics (SVG) to render the plot, which is great for static images.  It's especially
   great for making publication-quality figures.  (If you haven't tried inkscape + matplotlib SVG output,
   it's pretty amazing.) For interactivity, it can be slow.  Anyplotlib uses a pure-JavaScript canvas renderer which is
   much faster for interactive applications, but the quality of the output is not as good as vector graphics.  This is a
   trade-off that we are willing to make for the sake of interactivity.

3. Matplotlib supports a wide range of marker styles, line styles, and other plot elements.  Anyplotlib focuses on a
   core set of features that are most commonly used in scientific plotting.  This means that some of the more
   esoteric features of Matplotlib may not be available in Anyplotlib. In general we try to match the lower level
   ``collections`` API of Matplotlib.

4. Each collection, plot, image is rendered as a single object on the canvas.  This is highly performant and more
   importantly allows for blitting. This is one of the main reasons why the ``ipympl`` backend of Matplotlib is so slow.

5. Finally ``anyplotlib`` uses ``AnyWidget`` as the underlying widget framework.  This means that it can be used in any
   environment that supports ``AnyWidget``, including Jupyter notebooks, JupyterLab, and PyCharm notebook preview.  Under
   the hood, ``AnyWidget`` uses a pure-JavaScript implementation of the widget protocol, which allows for fast rendering
   and interactivity.

**Disclaimer**: This project is in the early stages of development.  Additionally many of the
JavaScript code was optimised using LLMs. That being said, the JavaScript/Python code is fairly minimal
and not too difficult to understand.

**Disclaimer #2**: Mostly this project is to see *if* something like this is possible; it remains to be
seen if this can be developed into a full-fledged plotting library.  The hope is that it can.

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`


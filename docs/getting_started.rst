Getting Started
===============

Installation
------------

Install via pip from PyPI (recommended)::

    pip install anyplotlib

Or clone the repository and install from source::

    git clone https://github.com/CSSFrancis/anyplotlib.git
    cd anyplotlib
    uv sync          # or `pip install -e .`

Quick start
-----------

1-D plot
~~~~~~~~

.. code-block:: python

    import numpy as np
    import anyplotlib as vw

    x = np.linspace(0, 4 * np.pi, 512)
    signal = np.sin(x)

    fig, ax = vw.subplots(1, 1, figsize=(620, 320))
    v = ax.plot(signal, axes=[x], units="rad")
    v  # display in a Jupyter cell

**Supported construction parameters**

+---------------+---------------+-------------------------------------------+
| Parameter     | Default       | Description                               |
+===============+===============+===========================================+
| ``color``     | ``"#4fc3f7"`` | CSS colour string for the line.           |
+---------------+---------------+-------------------------------------------+
| ``linewidth`` | ``1.5``       | Stroke width in pixels.                   |
+---------------+---------------+-------------------------------------------+
| ``label``     | ``""``        | Legend label (empty = no legend entry).   |
+---------------+---------------+-------------------------------------------+
| ``units``     | ``"px"``      | X-axis label (e.g. ``"eV"``, ``"s"``).   |
+---------------+---------------+-------------------------------------------+
| ``y_units``   | ``""``        | Y-axis label.                             |
+---------------+---------------+-------------------------------------------+

.. note::
    ``linestyle``, ``alpha``, and ``marker`` / ``markersize`` are **not yet
    supported**.  Use :meth:`~anyplotlib.figure_plots.Plot1D.add_points` or
    the other ``add_*`` marker methods to place symbols at explicit data
    coordinates.

**What you can do with the returned** ``Plot1D`` **object**

* ``v.update(new_data)`` — replace y-data live (x-axis range recalculated
  automatically).
* ``v.add_line(data, x_axis=x, color="…", label="…")`` — overlay additional
  curves; returns an ID you can pass to ``v.remove_line(lid)``.
* ``v.add_span(v0, v1, axis="x")`` — shade a region along x or y.
* ``v.set_view(x0, x1)`` / ``v.reset_view()`` — programmatic pan/zoom
  (users can also pan/zoom interactively with the mouse and press **R** to
  reset).
* ``v.add_vline_widget(x)`` / ``v.add_hline_widget(y)`` /
  ``v.add_range_widget(x0, x1)`` — draggable overlays that report their
  position back to Python via ``on_changed`` / ``on_release`` callbacks.
* ``v.add_points(offsets)`` / ``v.add_circles(offsets)`` /
  ``v.add_vlines(x_values)`` / ``v.add_hlines(y_values)`` / … —
  static marker collections at explicit data coordinates.

See :class:`~anyplotlib.figure_plots.Plot1D` for the full API reference, and
the :doc:`auto_examples/index` gallery (e.g. *1D Spectra*) for worked
examples.

2-D image
~~~~~~~~~

.. code-block:: python

    import numpy as np
    import anyplotlib as vw

    data = np.random.default_rng(0).standard_normal((256, 256))
    fig, ax = vw.subplots(1, 1, figsize=(500, 500))
    v = ax.imshow(data, units="px")
    v  # display in a Jupyter cell

Bar chart
~~~~~~~~~

.. code-block:: python

    import numpy as np
    import anyplotlib as vw

    values = np.array([42, 55, 48, 63, 71, 68], dtype=float)
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun"]

    fig, ax = vw.subplots(1, 1, figsize=(560, 320))
    bar = ax.bar(values, x_labels=months, color="#4fc3f7", show_values=True)
    bar  # display in a Jupyter cell

For more elaborate usage, see the :doc:`auto_examples/index` gallery or
the :doc:`api/index`.

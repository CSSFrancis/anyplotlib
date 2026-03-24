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

.. list-table::
   :header-rows: 1
   :widths: 18 18 64

   * - Parameter
     - Default
     - Description
   * - ``color``
     - ``"#4fc3f7"``
     - CSS colour string for the line.
   * - ``linewidth``
     - ``1.5``
     - Stroke width in pixels.
   * - ``linestyle`` (``ls``)
     - ``"solid"``
     - Dash pattern: ``"solid"``, ``"dashed"``, ``"dotted"``,
       ``"dashdot"``.  Shorthands ``"-"``, ``"--"``, ``":"``, ``"-."``
       also accepted.
   * - ``alpha``
     - ``1.0``
     - Line opacity (0 = transparent, 1 = fully opaque).
   * - ``marker``
     - ``"none"``
     - Per-point symbol: ``"o"`` (circle), ``"s"`` (square),
       ``"^"``/``"v"`` (triangles), ``"D"`` (diamond),
       ``"+"``/``"x"`` (stroke-only), or ``"none"``.
   * - ``markersize``
     - ``4.0``
     - Marker radius / half-side in pixels.
   * - ``label``
     - ``""``
     - Legend label (empty string = no legend entry).
   * - ``units``
     - ``"px"``
     - X-axis label (e.g. ``"eV"``, ``"s"``).
   * - ``y_units``
     - ``""``
     - Y-axis label.

**Linestyle examples**

.. code-block:: python

    t = np.linspace(0, 2 * np.pi, 256)
    fig, ax = vw.subplots(1, 1, figsize=(620, 320))
    plot = ax.plot(np.sin(t),        linestyle="solid",   color="#4fc3f7", label="solid")
    plot.add_line(np.sin(t) + 0.6,   linestyle="dashed",  color="#ff7043", label="dashed")
    plot.add_line(np.sin(t) + 1.2,   linestyle="dotted",  color="#aed581", label="dotted")
    plot.add_line(np.sin(t) + 1.8,   linestyle="dashdot", color="#ce93d8", label="dashdot")
    fig

**Alpha (transparency) example**

.. code-block:: python

    fig, ax = vw.subplots(1, 1, figsize=(620, 320))
    plot = ax.plot(np.sin(t), color="#4fc3f7", alpha=0.4, label="sin")
    plot.add_line(np.cos(t), color="#ff7043", alpha=0.4, label="cos")
    fig

**Marker example**

.. code-block:: python

    t_sparse = np.linspace(0, 2 * np.pi, 24)   # few points → visible markers
    fig, ax = vw.subplots(1, 1, figsize=(620, 320))
    plot = ax.plot(np.sin(t_sparse), marker="o", markersize=5, color="#4fc3f7", label="o")
    plot.add_line(np.sin(t_sparse) + 0.8, marker="s", markersize=5, color="#ff7043", label="s")
    plot.add_line(np.sin(t_sparse) + 1.6, marker="D", markersize=5, color="#aed581", label="D")
    fig

**Post-construction setters**

All line properties can be changed after creation without recreating the panel::

    v.set_color("#ff7043")
    v.set_linewidth(2.5)
    v.set_linestyle("dashed")   # or "--"
    v.set_alpha(0.6)
    v.set_marker("o", markersize=6)

**What you can do with the returned** ``Plot1D`` **object**

* ``v.update(new_data)`` — replace y-data live (y-axis range recalculated
  automatically).
* ``v.add_line(data, x_axis=x, color="…", linestyle="…", alpha=…,
  marker="…", label="…")`` — overlay additional curves; the y-axis range
  expands automatically to include the new data.  Returns an ID you can pass
  to ``v.remove_line(lid)``.
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
the :doc:`auto_examples/index` gallery (e.g. *1D Line Styles* or *1D Spectra*)
for worked examples.

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

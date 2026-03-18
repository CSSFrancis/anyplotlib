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

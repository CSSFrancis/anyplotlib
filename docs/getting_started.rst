Getting Started
===============

Installation
------------

Clone the repository and install with ``uv`` (or pip)::

    git clone https://github.com/your-org/viewer.git
    cd viewer
    uv sync          # installs the project + all dependencies

Quick start
-----------

1-D viewer
~~~~~~~~~~

.. code-block:: python

    import numpy as np
    from viewer import Viewer1D

    x = np.linspace(0, 4 * np.pi, 512)
    signal = np.sin(x)

    v = Viewer1D(signal, x_axis=x, units="rad")
    v  # display in a Jupyter cell

2-D viewer
~~~~~~~~~~

.. code-block:: python

    import numpy as np
    from viewer import Viewer2D

    data = np.random.default_rng(0).standard_normal((256, 256))
    v = Viewer2D(data, units="px")
    v  # display in a Jupyter cell

For more elaborate usage, see the :doc:`auto_examples/index` gallery or
the :doc:`api/index`.



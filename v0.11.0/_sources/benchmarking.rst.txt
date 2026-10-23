.. _benchmarking:

Benchmarking
============

anyplotlib ships two benchmark suites that cover the Python serialisation
pipeline (``tests/test_benchmarks_py.py``) and JS render performance via
headless Chromium (``tests/test_benchmarks.py``).

Running locally
---------------

.. code-block:: bash

   # Python suite — fast (~30 s), no browser needed
   uv run pytest tests/test_benchmarks_py.py -v

   # JS suite — requires Playwright + Chromium (~3 min)
   uv run pytest tests/test_benchmarks.py -v

   # Add 4 096² / 8 192² image scenarios (slow, opt-in)
   uv run pytest tests/test_benchmarks_py.py --run-slow -v

Updating committed baselines
-----------------------------

Run ``--update-benchmarks`` after an intentional performance change to
refresh ``tests/benchmarks/baselines.json``:

.. code-block:: bash

   uv run pytest tests/test_benchmarks_py.py tests/test_benchmarks.py \
       --update-benchmarks -v

Commit the result so local runs and the performance table stay accurate.

CI — hardware-agnostic comparison
----------------------------------

Absolute ms values are meaningless across different runners, so CI never
compares against the committed baselines file.  Instead it checks out both
the base branch and the head branch **on the same runner in the same job**
and compares them — only the ratio matters, hardware differences cancel out.

.. code-block:: text

   1. Checkout BASE  →  pytest --update-benchmarks --baselines-path /tmp/ci_baselines.json
   2. Checkout HEAD  →  pytest --baselines-path /tmp/ci_baselines.json
      Pass / fail is based on the ratio, not absolute ms.

The ``--baselines-path`` flag redirects reads and writes without touching
the committed ``tests/benchmarks/baselines.json``.

Threshold: **1.50 ×** (50 % slower → failure, 25 % → warning).

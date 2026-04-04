.. _performance:

Performance
===========

anyplotlib is designed for **real-time data updates** in a live Jupyter session.
This page explains the architectural decisions that make per-frame updates fast,
where the remaining costs sit, and where the current limitations are.

For measured timings see the :doc:`auto_examples/Benchmarks/index` gallery.

----

Why anyplotlib is fast
-----------------------

.. rubric:: (a) Compact binary encoding: float → uint8 → base64

Colormapped 2-D data is reduced from 64-bit floats to **8-bit palette indices**
before it leaves Python.  A 1 024² image goes from a 4 MB float32 array to a
1 MB uint8 array; base64-encoding that produces a **~1.3 MB ASCII blob** —
roughly the same size as a JPEG thumbnail.

Plotly and Bokeh serialise every floating-point sample as a JSON decimal
string, typically 8–12 characters each.  For a 1 024² heatmap that is
**~10 MB of JSON** versus anyplotlib's 1.3 MB base64 string — nearly an 8×
difference before the browser receives a single byte.

+------------------+-------------------------------+----------------------+
| Library          | 1 024² payload format         | Approx. size         |
+==================+===============================+======================+
| anyplotlib       | base64(uint8 raw pixels)      | ~1.3 MB              |
+------------------+-------------------------------+----------------------+
| Plotly           | JSON float array              | ~10 MB               |
+------------------+-------------------------------+----------------------+
| Bokeh            | JSON float array (json_item)  | ~10 MB               |
+------------------+-------------------------------+----------------------+
| matplotlib/ipympl| PNG buffer (lossless)         | ~0.5–2 MB (variable) |
+------------------+-------------------------------+----------------------+

.. rubric:: (b) LUT colormapping in the browser (``_buildLut32``)

Python never converts uint8 indices to RGB triples.
Instead, the colormap is serialised once as a compact 256-entry lookup table
(``state["colormap_data"]``).  The browser function ``_buildLut32`` (line 471
of ``figure_esm.js``) expands each index to an RGBA ``Uint32`` in a tight
256-iteration loop, then hands the resulting ``Uint8ClampedArray`` directly to
``createImageBitmap``.

This means colormap changes and display-range tweaks (``vmin`` / ``vmax``)
are **free from Python's perspective** — only the 256-entry LUT array changes,
not the pixel payload.

.. rubric:: (c) Canvas blitting — pan and zoom without re-serialisation

Once a frame has been decoded into an ``ImageBitmap`` it is cached in
``p.blitCache``.  Pan and zoom operations (``_blit2d``, lines 518–539) call
``ctx.drawImage(bitmap, srcX, srcY, visW, visH, destX, destY, destW, destH)``
— a single GPU-accelerated compositing call — without touching Python at all.

Only when the underlying data array changes (a new ``plot.update()`` call)
does Python re-encode and push a new base64 string.  For interactive
exploration of a fixed dataset the marginal per-frame cost from Python is
**zero**.

.. rubric:: (d) No SVG / DOM per point overhead

Plotly's scatter and heatmap renderers build SVG ``<path>`` elements or
WebGL buffers from the JSON payload.  Every zoom or pan event that triggers a
re-render reconstructs DOM nodes.  anyplotlib's canvas renderer has a fixed
DOM: two ``<canvas>`` layers (plot + overlay) per panel, regardless of dataset
size.  For large 1-D datasets the ``draw1d`` function (line 1 260 of
``figure_esm.js``) iterates over pre-sent coordinates in a tight
``ctx.lineTo`` loop with no heap allocation per point.

.. rubric:: (e) Incremental traitlet pushes

anyplotlib uses ``anywidget``'s ``sync=True`` traitlets.  Only changed state
fields are serialised into the ``panel_{id}_json`` traitlet on each push.
A pan/zoom event updates only ``center_x``, ``center_y``, and ``zoom`` — the
``image_b64`` blob is unchanged and is not re-transmitted.

----

Python → JS pipeline stages
----------------------------

The table below shows typical costs on an Apple M1 Air (from
``tests/benchmarks/baselines.json``):

+---------------------------------------------------+-------+--------+--------+--------+---------+
| Stage                                             | 64²   | 256²   | 512²   | 1024²  | 2048²   |
+===================================================+=======+========+========+========+=========+
| ``_normalize_image`` (NumPy cast + scale + uint8) | 0.013 | 0.091  | 0.577  | 3.85   | 29.67   |
+---------------------------------------------------+-------+--------+--------+--------+---------+
| ``_encode_bytes`` (base64)                        | 0.007 | 0.098  | 0.451  | 2.21   | 11.28   |
+---------------------------------------------------+-------+--------+--------+--------+---------+
| ``json.dumps(to_state_dict())``                   | 0.081 | 0.266  | 0.875  | 3.16   | 12.93   |
+---------------------------------------------------+-------+--------+--------+--------+---------+
| **``plot.update()`` (full round-trip)**            | 0.219 | 0.646  | 2.36   | 9.23   | 36.11   |
+---------------------------------------------------+-------+--------+--------+--------+---------+

All timings in **milliseconds (min over 15 calls)**.  The ``update()`` row
includes all stages above plus ``_build_colormap_lut`` and traitlet dispatch.

For a 512² image anyplotlib completes a full Python-side update in **~2.4 ms**


----

Limitations
-----------

.. rubric:: 1-D serialisation uses JSON float arrays

The current ``Plot1D.to_state_dict()`` converts x/y arrays with
``array.tolist()`` before ``json.dumps``.  This is the same O(N × bytes-per-float)
cost as Plotly and Bokeh.  For 100 000-point line plots the round-trip is
**~7 ms** — acceptable for interactive drag events but not for high-frequency
streaming.

A future ``uint16``-quantised path (similar to the 2-D uint8 encoding) would
reduce 1-D payload sizes by ~4× and bring the serialisation cost below 2 ms
for 100 k points.

.. rubric:: 2-D LUT resolution is 8 bit (256 colours)

The uint8 encoding maps each float to one of 256 palette entries.
For scientific visualisation at display resolution this is indistinguishable
from a full 64-bit render, but histogram-equalisation or very shallow
gradients may show banding if ``vmin`` / ``vmax`` clip a narrow data range.
Use ``display_min`` / ``display_max`` to focus the LUT on the region of
interest.

.. rubric:: No GPU-side streaming

anyplotlib does not use ``OffscreenCanvas`` or ``ImageData`` worker threads.
All pixel expansion (LUT → RGBA) happens on the main browser thread via
``_buildLut32``.  For arrays larger than ~4 096² this becomes perceptible
(> 16 ms frame budget).  The ``--run-slow`` test flag covers those sizes
explicitly.

----

Benchmark gallery
-----------------

.. toctree::
   :hidden:

   auto_examples/Benchmarks/index

See the :doc:`auto_examples/Benchmarks/index` gallery for live-timed
comparisons of anyplotlib, matplotlib, Plotly, and Bokeh across a range
of 2-D image sizes and 1-D line lengths.


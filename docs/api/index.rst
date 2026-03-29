=============
API Reference
=============

The anyplotlib public API is organized into five modules below.
Click a card to browse the module page, or use the summary tables to jump
directly to a class or function.

.. toctree::
   :hidden:
   :maxdepth: 2

   figure
   figure_plots
   markers
   widgets
   callbacks

.. grid:: 2 3 3 3
   :gutter: 2

   .. grid-item-card::
      :link: figure
      :link-type: doc

      :octicon:`browser;2em;sd-text-info` Figure
      ^^^

      The :class:`~anyplotlib.Figure` widget and the
      :func:`~anyplotlib.subplots` factory — the main entry point
      for creating interactive figures.

   .. grid-item-card::
      :link: figure_plots
      :link-type: doc

      :octicon:`graph;2em;sd-text-info` Axes & Plots
      ^^^

      :class:`~anyplotlib.Axes` and the five plot classes:
      :class:`~anyplotlib.Plot1D`, :class:`~anyplotlib.Plot2D`,
      :class:`~anyplotlib.PlotMesh`, :class:`~anyplotlib.Plot3D`,
      :class:`~anyplotlib.PlotBar`.

   .. grid-item-card::
      :link: figure_plots
      :link-type: doc

      :octicon:`rows;2em;sd-text-info` Layout
      ^^^

      :class:`~anyplotlib.GridSpec` and :class:`~anyplotlib.SubplotSpec`
      for building flexible multi-panel figure layouts.

   .. grid-item-card::
      :link: markers
      :link-type: doc

      :octicon:`dot-fill;2em;sd-text-info` Markers
      ^^^

      Static visual overlays — circles, arrows, lines, rectangles,
      polygons, text, and more — drawn on top of any plot.

   .. grid-item-card::
      :link: widgets
      :link-type: doc

      :octicon:`sliders;2em;sd-text-info` Interactive Widgets
      ^^^

      Draggable overlays such as :class:`~anyplotlib.CrosshairWidget`
      and :class:`~anyplotlib.RectangleWidget` that report position
      back to Python.

   .. grid-item-card::
      :link: callbacks
      :link-type: doc

      :octicon:`bell;2em;sd-text-info` Callbacks
      ^^^

      The :class:`~anyplotlib.CallbackRegistry` two-tier event system
      (``on_change`` for live frames, ``on_release`` for settled state)
      and the :class:`~anyplotlib.Event` dataclass.


Figure
------

.. currentmodule:: anyplotlib

.. autosummary::
   :toctree: generated/
   :nosignatures:
   :template: class.rst

   Figure

.. autosummary::
   :toctree: generated/
   :nosignatures:

   subplots


Axes & Plots
------------

.. autosummary::
   :toctree: generated/
   :nosignatures:
   :template: class.rst

   Axes
   Plot1D
   Plot2D
   PlotMesh
   Plot3D
   PlotBar


Layout
------

.. autosummary::
   :toctree: generated/
   :nosignatures:
   :template: class.rst

   GridSpec
   SubplotSpec


Markers
-------

.. currentmodule:: anyplotlib.markers

.. autosummary::
   :toctree: generated/
   :nosignatures:
   :template: class.rst

   MarkerGroup
   MarkerTypeDict
   MarkerRegistry


Interactive Widgets
-------------------

.. currentmodule:: anyplotlib

.. autosummary::
   :toctree: generated/
   :nosignatures:
   :template: class.rst

   Widget
   RectangleWidget
   CircleWidget
   AnnularWidget
   CrosshairWidget
   PolygonWidget
   LabelWidget
   VLineWidget
   HLineWidget
   RangeWidget


Callbacks
---------

.. autosummary::
   :toctree: generated/
   :nosignatures:
   :template: class.rst

   CallbackRegistry
   Event


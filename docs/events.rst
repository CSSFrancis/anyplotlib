.. _events:

============
Event System
============

anyplotlib uses a unified event system inspired by
`pygfx/rendercanvas <https://github.com/pygfx/rendercanvas>`_ with
anyplotlib-specific extensions. Every plot class (:class:`~anyplotlib.Plot1D`,
:class:`~anyplotlib.Plot2D`, :class:`~anyplotlib.PlotMesh`,
:class:`~anyplotlib.Plot3D`, :class:`~anyplotlib.PlotBar`) and every
interactive widget shares the same API.


Quick start
-----------

.. code-block:: python

    import numpy as np
    import anyplotlib as apl

    fig, ax = apl.subplots(1, 1, figsize=(600, 400))
    plot = ax.imshow(np.random.default_rng(0).standard_normal((128, 128)))

    # Direct call
    def on_press(event):
        print(f"clicked at data ({event.xdata:.2f}, {event.ydata:.2f})")

    plot.add_event_handler(on_press, "pointer_down")

    # Decorator form — equivalent
    @plot.add_event_handler("pointer_down")
    def on_press(event):
        print(f"clicked at data ({event.xdata:.2f}, {event.ydata:.2f})")

    # Multiple types in one call
    @plot.add_event_handler("pointer_down", "pointer_up")
    def on_press_release(event):
        print(event.event_type, event.button)

    # Wildcard — fires for every event type
    @plot.add_event_handler("*")
    def log_all(event):
        print(event)

    # Remove by CID
    cid = plot.add_event_handler(on_press, "pointer_down")
    plot.remove_handler(cid)

    # Remove by function reference
    plot.remove_handler(on_press)


Event types
-----------

.. list-table::
   :header-rows: 1
   :widths: 22 78

   * - Event type
     - Trigger
   * - ``pointer_down``
     - Mouse button pressed inside the panel.
   * - ``pointer_up``
     - Mouse button released.
   * - ``pointer_move``
     - Pointer moved (drag or hover).
   * - ``pointer_settled``
     - Pointer held still for ≥ *ms* milliseconds within ± *delta* pixels.
       Zero-cost when no handler is connected (timer never created).
   * - ``pointer_enter``
     - Cursor enters the panel.
   * - ``pointer_leave``
     - Cursor leaves the panel.
   * - ``double_click``
     - Double-click.
   * - ``wheel``
     - Scroll wheel or trackpad pinch.
   * - ``key_down``
     - Key pressed while panel has focus.
   * - ``key_up``
     - Key released.
   * - ``*``
     - Wildcard — handler receives every dispatched event type.


``pointer_settled`` thresholds
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    # Default: 300 ms dwell, 4-pixel radius
    @plot.add_event_handler("pointer_settled")
    def on_settle(event):
        update_tooltip(event.xdata, event.ydata)

    # Custom thresholds
    @plot.add_event_handler("pointer_settled", ms=500, delta=8)
    def on_settle_slow(event):
        run_expensive_query(event.xdata, event.ydata)

The timer is activated when the first ``pointer_settled`` handler connects and
deactivated (zeroed out) when the last one disconnects, so there is no JS
overhead when the event is unused.


Event object
------------

Every handler receives a single :class:`~anyplotlib.callbacks.Event` instance.
All fields are top-level attributes — there is no nested ``data`` dict.

Universal fields (every event)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 18 18 64

   * - Field
     - Type
     - Description
   * - ``event_type``
     - ``str``
     - e.g. ``"pointer_down"``, ``"key_up"``
   * - ``source``
     - ``object``
     - The plot or widget that fired the event.
   * - ``time_stamp``
     - ``float``
     - ``perf_counter()`` at fire time (seconds).
   * - ``modifiers``
     - ``list[str]``
     - Active modifier keys: ``"ctrl"``, ``"shift"``, ``"alt"``, ``"meta"``.
       Empty list when none held.
   * - ``stop_propagation``
     - ``bool``
     - Set to ``True`` inside a handler to prevent remaining handlers
       in the same dispatch from running.

Pointer fields
~~~~~~~~~~~~~~

Present on ``pointer_down``, ``pointer_up``, ``pointer_move``,
``pointer_settled``, ``pointer_enter``, ``pointer_leave``, ``double_click``.

.. list-table::
   :header-rows: 1
   :widths: 18 18 64

   * - Field
     - Type
     - Description
   * - ``x``, ``y``
     - ``float | None``
     - Canvas pixel coordinates within the panel.
   * - ``button``
     - ``int | None``
     - Which button was pressed or released: 0 = left, 1 = middle, 2 = right.
       ``None`` on ``pointer_move``, ``pointer_enter``, ``pointer_leave``,
       ``pointer_settled``.
   * - ``buttons``
     - ``int``
     - Bitmask of *currently held* buttons (useful on ``pointer_enter`` to
       detect dragging into the panel).
   * - ``xdata``, ``ydata``
     - ``float | None``
     - Data-space coordinates. Available on Plot1D, Plot2D, PlotMesh.
       ``None`` on Plot3D (use ``ray`` instead) and PlotBar.
   * - ``ray``
     - ``dict | None``
     - Plot3D only: ``{"origin": [x,y,z], "direction": [dx,dy,dz]}``.
       ``None`` on all other plot types.
   * - ``line_id``
     - ``str | None``
     - Plot1D only. Set to the overlay line's ID when the pointer is over a
       named line; ``None`` when over the primary line or empty space.
   * - ``dwell_ms``
     - ``float | None``
     - ``pointer_settled`` only: actual elapsed dwell time in milliseconds.

PlotBar additional fields on ``pointer_down``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 20 18 62

   * - Field
     - Type
     - Description
   * - ``bar_index``
     - ``int | None``
     - Index of the bar that was pressed; ``None`` when the press missed all
       bars.
   * - ``value``
     - ``float | None``
     - Bar height at ``bar_index``; ``None`` on miss.
   * - ``x_label``
     - ``str | None``
     - Category label of the pressed bar; ``None`` when none is set or on miss.
   * - ``group_index``
     - ``int | None``
     - Group index for grouped-bar charts; ``None`` for simple bars or on miss.

Wheel fields
~~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 18 18 64

   * - Field
     - Type
     - Description
   * - ``x``, ``y``
     - ``float | None``
     - Pointer position at scroll time.
   * - ``dx``, ``dy``
     - ``float | None``
     - Scroll deltas (positive = down/right).

Key fields
~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 18 18 64

   * - Field
     - Type
     - Description
   * - ``key``
     - ``str | None``
     - Key name: ``"q"``, ``"Enter"``, ``"ArrowLeft"``, etc. (DOM
       ``KeyboardEvent.key`` values).
   * - ``x``, ``y``
     - ``float | None``
     - Pointer position at keypress time (useful for placing UI elements at
       the cursor).
   * - ``last_widget_id``
     - ``str | None``
     - ID of the last overlay widget the user clicked, or ``None``.
       Lets key handlers operate on the most-recently-selected widget.


Per-line filtering on Plot1D
----------------------------

Lines returned by :meth:`~anyplotlib.Plot1D.add_line` expose their own
``add_event_handler``. Internally this connects to the plot-level
``pointer_move`` / ``pointer_down`` and filters by ``line_id``, so no new
mechanism is required.

.. code-block:: python

    t = np.linspace(0, 2 * np.pi, 256)
    fig, ax = apl.subplots(1, 1, figsize=(600, 300))
    plot = ax.plot(np.sin(t))
    overlay = plot.add_line(np.cos(t), color="#ff7043")

    @overlay.add_event_handler("pointer_down")
    def on_pick(event):
        print(f"picked overlay line at xdata={event.xdata:.3f}")


Pause and hold
--------------

Both are context managers available on every plot and widget.

**Pause** (suppress — events are dropped):

.. code-block:: python

    with plot.pause_events():               # suppress all types
        update_all_panels()

    with plot.pause_events("pointer_move"): # suppress specific type(s)
        do_something()

**Hold** (buffer — events are queued and flushed on exit):

.. code-block:: python

    with plot.hold_events():                    # buffer all types
        do_something()

    with plot.hold_events("pointer_settled"):   # buffer specific type(s) only
        do_something()

Both support nesting via a depth counter. When both are active for the same
type, *pause wins*: events are dropped, not buffered.


Priority ordering
-----------------

Handlers fire in ascending ``order`` value (default ``0``). Lower values fire
first:

.. code-block:: python

    plot.add_event_handler(fast_handler,   "pointer_move", order=-1)
    plot.add_event_handler(normal_handler, "pointer_move")       # order=0
    plot.add_event_handler(slow_handler,   "pointer_move", order=1)


Comparison with Matplotlib and pygfx
-------------------------------------

Design goals: align naming with pygfx/rendercanvas (which inherits from DOM
conventions), fill the gaps in the old ``on_click``/``on_release``/``on_key``
API, and add anyplotlib-specific extensions (``pointer_settled``,
``pause_events``, ``hold_events``).

API mapping
~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 30 35 35

   * - anyplotlib (new)
     - Matplotlib equivalent
     - pygfx / rendercanvas equivalent
   * - ``add_event_handler(fn, "pointer_down")``
     - ``fig.canvas.mpl_connect("button_press_event", fn)``
     - ``renderer.add_event_handler(fn, "pointer_down")``
   * - ``add_event_handler(fn, "pointer_up")``
     - ``fig.canvas.mpl_connect("button_release_event", fn)``
     - ``renderer.add_event_handler(fn, "pointer_up")``
   * - ``add_event_handler(fn, "pointer_move")``
     - ``fig.canvas.mpl_connect("motion_notify_event", fn)``
     - ``renderer.add_event_handler(fn, "pointer_move")``
   * - ``add_event_handler(fn, "pointer_settled", ms=300)``
     - *(no equivalent — requires manual timer)*
     - *(no equivalent)*
   * - ``add_event_handler(fn, "pointer_enter")``
     - ``fig.canvas.mpl_connect("axes_enter_event", fn)``
     - ``renderer.add_event_handler(fn, "pointer_enter")``
   * - ``add_event_handler(fn, "pointer_leave")``
     - ``fig.canvas.mpl_connect("axes_leave_event", fn)``
     - ``renderer.add_event_handler(fn, "pointer_leave")``
   * - ``add_event_handler(fn, "double_click")``
     - *(detect via button_press_event + dblclick guard)*
     - ``renderer.add_event_handler(fn, "double_click")``
   * - ``add_event_handler(fn, "wheel")``
     - ``fig.canvas.mpl_connect("scroll_event", fn)``
     - ``renderer.add_event_handler(fn, "wheel")``
   * - ``add_event_handler(fn, "key_down")``
     - ``fig.canvas.mpl_connect("key_press_event", fn)``
     - ``renderer.add_event_handler(fn, "key_down")``
   * - ``add_event_handler(fn, "key_up")``
     - ``fig.canvas.mpl_connect("key_release_event", fn)``
     - ``renderer.add_event_handler(fn, "key_up")``
   * - ``add_event_handler(fn, "*")``
     - *(no wildcard — register for each type separately)*
     - ``renderer.add_event_handler(fn, "*")``
   * - ``plot.pause_events()``
     - *(no equivalent)*
     - *(no equivalent)*
   * - ``plot.hold_events()``
     - *(no equivalent)*
     - *(no equivalent)*
   * - ``remove_handler(cid)``
     - ``fig.canvas.mpl_disconnect(cid)``
     - ``renderer.remove_event_handler(fn, "pointer_down")``

Event field mapping
~~~~~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 28 35 37

   * - anyplotlib field
     - Matplotlib equivalent
     - pygfx equivalent
   * - ``event.xdata``, ``event.ydata``
     - ``event.xdata``, ``event.ydata``
     - ``event.x``, ``event.y`` *(data-space)*
   * - ``event.x``, ``event.y``
     - ``event.x``, ``event.y`` *(canvas pixels)*
     - ``event.x``, ``event.y`` *(canvas pixels)*
   * - ``event.button``
     - ``event.button`` (1=left, 2=middle, 3=right)
     - ``event.button`` (0=left, 1=middle, 2=right)
   * - ``event.modifiers``
     - ``event.key`` *(only first modifier)*
     - ``event.modifiers`` *(list)*
   * - ``event.key``
     - ``event.key``
     - ``event.key``
   * - ``event.dwell_ms``
     - *(absent)*
     - *(absent)*
   * - ``event.line_id``
     - *(absent — use pick_event)*
     - *(absent)*
   * - ``event.bar_index``
     - *(absent — use pick_event)*
     - *(absent)*
   * - ``event.ray``
     - *(absent)*
     - *(absent — 3-D not a focus of rendercanvas)*

.. note::
   Matplotlib uses a 1-based button numbering (1=left, 2=middle, 3=right).
   anyplotlib and pygfx both follow the DOM convention (0=left, 1=middle,
   2=right).


Implementation status
---------------------

The table below tracks what is implemented, partially implemented, or planned
for each event type and plot class.  ✓ = fully implemented,
◑ = partial / known gap, ✗ = not yet implemented.

Event types
~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 22 16 16 16 16 14

   * - Event type
     - Plot1D
     - Plot2D
     - PlotMesh
     - Plot3D
     - PlotBar
   * - ``pointer_down``
     - ✓ |br| *(on mouseup,* |br| *click-detection)*
     - ✓ |br| *(on mouseup,* |br| *click-detection)*
     - ✓ |br| *(on mouseup,* |br| *click-detection)*
     - ✗ |br| *(drag start,* |br| *not emitted)*
     - ✓ |br| *(on mousedown)*
   * - ``pointer_up``
     - ✓
     - ✓
     - ✓
     - ✓
     - ✗
   * - ``pointer_move``
     - ✓
     - ✓
     - ✓
     - ✓
     - ✓
   * - ``pointer_settled``
     - ✓
     - ✓
     - ✓
     - ✓
     - ✓
   * - ``pointer_enter``
     - ✓
     - ✓
     - ✓
     - ✓
     - ✓
   * - ``pointer_leave``
     - ✓
     - ✓
     - ✓
     - ✓
     - ✓
   * - ``double_click``
     - ✓
     - ✓
     - ✓
     - ✗
     - ✓
   * - ``wheel``
     - ✓
     - ✓
     - ✓
     - ✓
     - ✓
   * - ``key_down``
     - ✓
     - ✓
     - ✓
     - ✓
     - ✓
   * - ``key_up``
     - ✓
     - ✓
     - ✓
     - ✓
     - ✓

.. |br| raw:: html

   <br/>

Event fields
~~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 22 16 16 16 16 14

   * - Field
     - Plot1D
     - Plot2D
     - PlotMesh
     - Plot3D
     - PlotBar
   * - ``x``, ``y`` *(canvas px)*
     - ✓
     - ✓
     - ✓
     - ✓
     - ✓
   * - ``button``
     - ✓
     - ✓
     - ✓
     - ✓
     - ✓
   * - ``buttons``
     - ✓
     - ✓
     - ✓
     - ✓
     - ✓
   * - ``modifiers``
     - ✓
     - ✓
     - ✓
     - ✓
     - ✓
   * - ``xdata``, ``ydata``
     - ✓
     - ✓
     - ✓
     - ✗ *(always None)*
     - ✗ *(always None)*
   * - ``ray``
     - ✗ *(always None)*
     - ✗ *(always None)*
     - ✗ *(always None)*
     - ✗ *(not yet impl.)*
     - ✗ *(always None)*
   * - ``line_id``
     - ✓
     - n/a
     - n/a
     - n/a
     - n/a
   * - ``dwell_ms``
     - ✓
     - ✓
     - ✓
     - ✓
     - ✓
   * - ``bar_index``, ``value``, |br| ``x_label``, ``group_index``
     - n/a
     - n/a
     - n/a
     - n/a
     - ✓ *(pointer_down only)*
   * - ``dx``, ``dy``
     - ✓ *(wheel only)*
     - ✓ *(wheel only)*
     - ✓ *(wheel only)*
     - ✓ *(wheel only)*
     - ✓ *(wheel only)*
   * - ``last_widget_id``
     - ✓ *(key events)*
     - ✓ *(key events)*
     - ✓ *(key events)*
     - ✓ *(key events)*
     - ✓ *(key events)*

Known gaps and planned work
~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 40 60

   * - Gap
     - Notes
   * - **Plot3D** ``pointer_down`` not emitted
     - Mousedown starts azimuth/elevation drag; a separate
       ``pointer_down`` signal is not yet emitted. Tracked as a known
       limitation.
   * - **Plot3D** ``double_click`` not emitted
     - The dblclick DOM listener is not attached to the 3-D canvas.
   * - **Plot3D** ``pointer_up`` emits on document ``mouseup``
     - Works correctly but always emits even if the press started outside
       the panel.
   * - ``ray`` field not populated on Plot3D
     - The ``{"origin": …, "direction": …}`` 3-D ray-cast is not yet
       computed; the field is always ``None``.
   * - ``pointer_down`` on Plot1D/2D/PlotMesh uses click-detection
     - Fires on ``mouseup`` after a short-distance, short-duration
       gesture — not on the raw ``mousedown``. This matches typical
       click semantics but differs from the DOM ``mousedown`` event.
   * - PlotBar ``pointer_up`` not emitted
     - The bar canvas has no ``mouseup`` listener; only ``pointer_down``
       (on ``mousedown``) is emitted.
   * - Touch events not supported
     - ``pointer_down`` / ``pointer_move`` / ``pointer_up`` are currently
       mouse-only; touch and stylus events are not forwarded.


API Reference
-------------

.. seealso::

   :class:`~anyplotlib.callbacks.Event`
      Full field reference for the event dataclass.

   :class:`~anyplotlib.CallbackRegistry`
      Low-level registry: ``connect``, ``disconnect``, ``fire``,
      ``pause_events``, ``hold_events``.

   :doc:`api/callbacks`
      Autogenerated API documentation for both classes.

   :doc:`auto_examples/index`
      Gallery of interactive examples using ``add_event_handler``.

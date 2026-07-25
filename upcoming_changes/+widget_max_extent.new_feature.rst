Added ``max_extent=`` to :class:`~anyplotlib.widgets.RangeWidget` and
:class:`~anyplotlib.widgets.RectangleWidget` (and the matching
``add_range_widget`` / ``add_rectangle_widget`` factories) — a size cap enforced
*while dragging*, so the widget physically stops growing instead of being
clamped after the fact. The dragged edge/corner pins and the opposite one stays
put, so the selection never jumps under the cursor. ``RangeWidget`` takes a span
width in data units; ``RectangleWidget`` takes a scalar (both axes) or a
``(max_w, max_h)`` pair. Default ``None`` leaves widgets unbounded.

Use it when a widget's size drives real downstream work — e.g. an integrating
selector whose span is a number of frames to read.

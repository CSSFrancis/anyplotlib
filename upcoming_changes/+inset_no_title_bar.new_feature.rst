An :meth:`~anyplotlib.figure.Figure.add_inset` with no title (the default,
``title=""``) now renders with NO title-bar strip at all — a clean bordered
plot box, content filling the whole area, instead of a useless empty header.
A titled inset is unchanged: its bar renders as before, with click-to-toggle
minimize. A title-less inset has no minimize affordance (there is no bar to
click), but drag-to-move / drag-to-resize in edit mode still work exactly as
before, since those gestures are wired on the inset body, not the bar.

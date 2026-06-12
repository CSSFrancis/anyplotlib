"""
Key-Press Widget Placement
==========================

Demonstrates the ``key_down`` event handler API: press a key while the plot
is focused to add an overlay widget centred on the current cursor position,
or press **Backspace / Delete** to remove the last widget you clicked.

**Key bindings**

+-------------------------------+---------------------------+
| Key                           | Action                    |
+===============================+===========================+
| ``q``                         | Add a rectangle           |
+-------------------------------+---------------------------+
| ``w``                         | Add a circle              |
+-------------------------------+---------------------------+
| ``e``                         | Add an annulus            |
+-------------------------------+---------------------------+
| ``Backspace`` (macOS ⌫)       | Remove last-clicked       |
| ``Delete`` (Windows / Linux)  |                           |
+-------------------------------+---------------------------+

**Built-in 2-D shortcuts** (not overridden in this example):

+-------+---------------------------+
| Key   | Action                    |
+=======+===========================+
| ``r`` | Reset zoom / pan          |
+-------+---------------------------+
| ``c`` | Toggle colorbar           |
+-------+---------------------------+
| ``l`` | Toggle log scale          |
+-------+---------------------------+
| ``s`` | Toggle symlog scale       |
+-------+---------------------------+

The cursor coordinates are available as ``event.xdata`` and ``event.ydata``
in image-pixel space (column, row), so widgets are centred exactly where
the cursor was when the key was pressed.

.. note::
   Move the mouse over the image first so the plot panel receives focus,
   then press a key.  On macOS the backspace key (⌫) is used for deletion;
   on Windows / Linux use the **Delete** key.
"""

import numpy as np
import anyplotlib as apl

# ── Synthetic test image ──────────────────────────────────────────────────────
rng = np.random.default_rng(0)
N = 256
x = np.linspace(0, 4 * np.pi, N)
XX, YY = np.meshgrid(x, x)
data = np.sin(XX) * np.cos(YY) + 0.15 * rng.standard_normal((N, N))

# ── Figure ────────────────────────────────────────────────────────────────────
fig, ax = apl.subplots(figsize=(520, 520))
plot = ax.imshow(data)

# ── Key handlers ─────────────────────────────────────────────────────────────

@plot.add_event_handler("key_down")
def add_rectangle(event):
    """Press 'q' — add a rectangle centred on the cursor."""
    if event.key != 'q':
        return
    cx, cy = event.xdata, event.ydata
    half_w, half_h = N * 0.08, N * 0.08
    plot.add_widget(
        "rectangle",
        x=cx - half_w, y=cy - half_h,
        w=half_w * 2,  h=half_h * 2,
        color="#ffd54f",
    )


@plot.add_event_handler("key_down")
def add_circle(event):
    """Press 'w' — add a circle centred on the cursor."""
    if event.key != 'w':
        return
    plot.add_widget(
        "circle",
        cx=event.xdata, cy=event.ydata,
        r=N * 0.07,
        color="#80cbc4",
    )


@plot.add_event_handler("key_down")
def add_annulus(event):
    """Press 'e' — add an annulus centred on the cursor."""
    if event.key != 'e':
        return
    plot.add_widget(
        "annular",
        cx=event.xdata, cy=event.ydata,
        r_outer=N * 0.12,
        r_inner=N * 0.06,
        color="#ce93d8",
    )


# macOS sends 'Backspace' for the ⌫ key; Windows/Linux send 'Delete'.
# Register both so the example works cross-platform.
@plot.add_event_handler("key_down")
def delete_last(event):
    """Press Backspace/Delete — remove the last widget that was clicked."""
    if event.key not in ('Backspace', 'Delete'):
        return
    wid = event.last_widget_id
    if wid and wid in {w.id for w in plot.list_widgets()}:
        plot.remove_widget(wid)


# ── Catch-all handler (optional) — log every registered key press ─────────────

@plot.add_event_handler("key_down")
def log_key(event):
    xdata = event.xdata
    ydata = event.ydata
    pos = f"({xdata:.1f}, {ydata:.1f})" if xdata is not None else "n/a"
    print(f"[key_down] key={event.key!r}  img={pos}"
          f"  last_widget={event.last_widget_id!r}")

fig  # Interactive

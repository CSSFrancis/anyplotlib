"""
Key-Press Widget Placement
==========================

Demonstrates the ``on_key`` callback API: press a key while the plot is
focused to add an overlay widget centred on the current cursor position,
or press **Delete** to remove the last widget you clicked.

**Key bindings**

+-------+---------------------------+
| Key   | Action                    |
+=======+===========================+
| ``q`` | Add a rectangle           |
+-------+---------------------------+
| ``w`` | Add a circle              |
+-------+---------------------------+
| ``e`` | Add an annulus            |
+-------+---------------------------+
| ``Delete`` | Remove last-clicked  |
+-------+---------------------------+

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

The cursor coordinates reported in the event (``event.img_x``,
``event.img_y``) are in image-pixel space, so widgets are centred exactly
where the cursor was when the key was pressed.

.. note::
   Move the mouse over the image first so the plot panel receives focus,
   then press a key.
"""

import numpy as np
import anyplotlib as vw

# ── Synthetic test image ──────────────────────────────────────────────────────
rng = np.random.default_rng(0)
N = 256
x = np.linspace(0, 4 * np.pi, N)
XX, YY = np.meshgrid(x, x)
data = np.sin(XX) * np.cos(YY) + 0.15 * rng.standard_normal((N, N))

# ── Figure ────────────────────────────────────────────────────────────────────
fig, ax = vw.subplots(figsize=(520, 520))
plot = ax.imshow(data)

# ── Key handlers ─────────────────────────────────────────────────────────────

@plot.on_key('q')
def add_rectangle(event):
    """Press 'q' — add a rectangle centred on the cursor."""
    cx, cy = event.img_x, event.img_y
    half_w, half_h = N * 0.08, N * 0.08
    plot.add_widget(
        "rectangle",
        x=cx - half_w, y=cy - half_h,
        w=half_w * 2,  h=half_h * 2,
        color="#ffd54f",
    )


@plot.on_key('w')
def add_circle(event):
    """Press 'w' — add a circle centred on the cursor."""
    plot.add_widget(
        "circle",
        cx=event.img_x, cy=event.img_y,
        r=N * 0.07,
        color="#80cbc4",
    )


@plot.on_key('e')
def add_annulus(event):
    """Press 'e' — add an annulus centred on the cursor."""
    plot.add_widget(
        "annular",
        cx=event.img_x, cy=event.img_y,
        r_outer=N * 0.12,
        r_inner=N * 0.06,
        color="#ce93d8",
    )


@plot.on_key('Delete')
def delete_last(event):
    """Press Delete — remove the last widget that was clicked / dragged."""
    wid = event.last_widget_id
    if wid and wid in {w.id for w in plot.list_widgets()}:
        plot.remove_widget(wid)


# ── Catch-all handler (optional) — print every registered key press ──────────

@plot.on_key
def log_key(event):
    print(f"[on_key] key={event.key!r}  img=({event.img_x:.1f}, {event.img_y:.1f})"
          f"  last_widget={event.last_widget_id!r}")

fig


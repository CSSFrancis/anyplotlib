"""
Interactive figure annotations — double-click to add, drag to place
===================================================================

anyplotlib has a *figure-level* annotation layer that floats above the panels,
positioned in **figure fractions** (0…1, origin top-left) rather than any
panel's data coordinates.  Set it with
:meth:`~anyplotlib.Figure.set_figure_markers`; the supported kinds are
``"text"``, ``"circle"``, ``"rect"`` and ``"arrow"``.

Turn on ``fig.edit_chrome`` and every annotation becomes draggable in the
browser.  Combine that with a ``double_click`` handler and you get a simple
annotate-by-clicking workflow: double-click a feature to drop a labelled
arrow, then drag it to line it up.  Positions round-trip back to Python via
:attr:`~anyplotlib.Figure.figure_markers`.
"""
import numpy as np
import anyplotlib as apl

rng  = np.random.default_rng(7)
data = rng.standard_normal((160, 160)).cumsum(0).cumsum(1)
data = (data - data.min()) / (data.max() - data.min())

fig, ax = apl.subplots(1, 1, figsize=(520, 520))
v = ax.imshow(data, cmap="magma", units="px")

# Enable the editable-annotation ("report builder") mode so figure markers are
# hit-testable and draggable, and the figure emits background/marker events.
fig.edit_chrome = True

# %%
# Seed a couple of annotations
# ----------------------------
# Each marker is a dict with a ``kind`` and fraction-space geometry.  A text
# label and an arrow pointing into the image to start with.

fig.set_figure_markers([
    {"kind": "text", "x": 0.5, "y": 0.06,
     "text": "Double-click a feature to annotate it",
     "color": "#ffffff", "fontsize": 14},
    {"kind": "arrow", "x": 0.20, "y": 0.30, "u": 0.12, "v": 0.12,
     "color": "#ffd54f", "linewidth": 2},
])

fig

# %%
# Double-click to drop a new annotation
# -------------------------------------
# On a single-panel figure the panel nearly fills the canvas, so we turn the
# click's device pixels into a figure fraction with the panel's
# ``display_width`` / ``display_height`` and append an arrow + label there.
# Because ``edit_chrome`` is on, the new marker is immediately draggable.


def _on_double_click(event):
    if event.x is None or event.display_width is None:
        return
    fx = float(np.clip(event.x / event.display_width, 0.02, 0.98))
    fy = float(np.clip(event.y / event.display_height, 0.02, 0.98))
    markers = fig.figure_markers            # current list (a copy)
    n = sum(1 for m in markers if m["kind"] == "text")
    markers.append({"kind": "arrow", "x": fx, "y": fy,
                    "u": 0.08, "v": -0.08, "color": "#40c4ff", "linewidth": 2})
    markers.append({"kind": "text", "x": fx + 0.08, "y": fy - 0.10,
                    "text": f"mark {n}", "color": "#40c4ff", "fontsize": 13})
    fig.set_figure_markers(markers)


v.add_event_handler(_on_double_click, "double_click")

fig.set_help(
    "Double-click on the image to drop a labelled arrow.\n"
    "Drag any annotation to reposition it (edit mode is on)."
)

fig  # Interactive

# %%
# Read the placements back
# ------------------------
# After the user drags things around, ``fig.figure_markers`` reflects the
# current fraction positions — persist them, export them, or feed them into a
# report.

for m in fig.figure_markers:
    print(m["kind"], round(m["x"], 3), round(m["y"], 3))

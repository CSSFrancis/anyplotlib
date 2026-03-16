# AGENTS.md — anyplotlib Codebase Guide

## Architecture Overview

`anyplotlib` is a Jupyter-compatible interactive plotting library. The key architectural split:

- **`Figure`** (`figure.py`) — the only `anywidget.AnyWidget` subclass. Owns all traitlets and is the Python↔JS bridge.
- **Plot objects** (`figure_plots.py`) — `Plot2D`, `Plot1D`, `PlotMesh`, `Plot3D` are **plain Python classes**, not widgets. They hold state in `_state` dicts and push to the Figure.
- **`figure_esm.js`** — pure-JS canvas renderer; all rendering logic lives here.
- **`markers.py`** — static visual overlays (circles, arrows, lines, etc.) with a two-level dict registry: `plot.markers[type][name]`.
- **`widgets.py`** — interactive draggable overlays (`RectangleWidget`, `CrosshairWidget`, etc.) that receive JS position updates.
- **`callbacks.py`** — two-tier event system (`on_change` for live drag frames, `on_release` for settled state).

## Python ↔ JS Data Flow

**Python → JS (push):** Every plot state mutation calls `plot._push()` → `figure._push(panel_id)` → serialises `_state` to JSON → writes to the dynamic traitlet `panel_{id}_json` (tagged `sync=True`) → JS observes and re-renders.

**JS → Python (events/widgets):** JS writes back to `panel_{id}_json` after a drag → Python observer calls `Widget._update_from_js()` and fires callbacks. Interaction events (zoom, rotate) come through the separate `event_json` traitlet → dispatched by `Figure._on_event()` → `plot.callbacks.fire(event)`.

**Adding state fields:** Add to `_state` in the constructor, include in `to_state_dict()`, and handle in `figure_esm.js`.

## Key Patterns

**`_push()` contract:** Any mutation to a plot's `_state` must end with `self._push()`. Forgetting this means changes won't appear in JS.

**Marker kwargs use matplotlib names** — translated to wire format in `MarkerGroup.to_wire()`:
```python
plot.add_circles(offsets, name="g1", facecolors="#f00", edgecolors="#fff", radius=5)
plot.markers["circles"]["g1"].set(radius=8)   # live update
```

**Widget (interactive overlay) pattern:**
```python
wid = plot.add_widget("crosshair", cx=64, cy=64)

@plot.on_change(wid)    # fires every drag frame — keep fast
def live(event): readout.value = f"({event.cx:.1f}, {event.cy:.1f})"

@plot.on_release(wid)   # fires once on settle — safe for expensive work
def done(event): recompute(event.cx, event.cy)
```

**`subplots` squeeze behaviour** mirrors matplotlib: `(1,1)` → scalar `Axes`; `(1,N)` → 1-D array `(N,)`; `(M,N)` → 2-D array `(M,N)`.

**`GridSpec` indexing** mirrors matplotlib exactly, including negative indices, slices, and multi-cell spans — see `tests/test_gridspec.py`.

## Developer Workflows

```bash
# Install (uses uv)
uv sync

# Run the full test suite
uv run pytest tests/

# Smoke tests (no pytest needed)
uv run python test_figure.py
uv run python test_pcolormesh.py

# Build docs (Sphinx Gallery, outputs to build/html/)
make html
make clean   # wipe build artefacts
```

## Key Files

| File | Purpose |
|------|---------|
| `anyplotlib/figure.py` | `Figure` widget; layout engine; JS↔Python dispatch |
| `anyplotlib/figure_plots.py` | All plot classes, `Axes`, `GridSpec`, `subplots()` |
| `anyplotlib/figure_esm.js` | All JS canvas rendering |
| `anyplotlib/markers.py` | Static marker collections; `to_wire()` translation |
| `anyplotlib/widgets.py` | Interactive overlay widgets |
| `anyplotlib/callbacks.py` | `CallbackRegistry`, `Event` dataclass |
| `anyplotlib/_repr_utils.py` | Self-contained iframe HTML for Sphinx Gallery / non-kernel use |
| `tests/test_events.py` | Callback system tests (good reference for event API) |
| `tests/test_gridspec.py` | Layout / sizing pipeline tests |
| `Examples/` | Gallery examples (files must be named `plot_*.py`) |

## Important Constraints

- The **OO API only** — no `plt.plot()` style. Always create a `Figure` and call methods on `Axes`.
- Plot objects (`Plot2D` etc.) store all display state in `self._state` (plain dict). Never add traitlets to them.
- `Figure` adds per-panel traits **dynamically** (`add_traits(panel_{id}_json=...)`); check `has_trait()` before accessing.
- `_pushing` set on `Figure` prevents echo loops: when Python pushes a trait change the JS observer is skipped.
- Colormap LUTs are built from matplotlib (`_build_colormap_lut`) and serialised as `[[r,g,b], ...]` in `_state["colormap_data"]`.
- Docs examples in `Examples/` must have a module-level docstring (first lines) for Sphinx Gallery to pick them up.
- When possible stop and ask questions. If you're unsure about how something works. 

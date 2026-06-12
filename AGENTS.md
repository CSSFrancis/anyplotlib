# AGENTS.md — anyplotlib Codebase Guide

## Architecture Overview

`anyplotlib` is a Jupyter-compatible interactive plotting library. The key architectural split:

- **`Figure`** (`anyplotlib/figure/_figure.py`) — the only `anywidget.AnyWidget` subclass. Owns all traitlets and is the Python↔JS bridge.
- **Plot objects** (`plot1d/`, `plot2d/`, `plot3d/`) — `Plot1D`, `PlotBar`, `Plot2D`, `PlotMesh`, `Plot3D` are **plain Python classes**, not widgets. They hold state in `_state` dicts and push to the Figure. Shared behaviour lives in `_base_plot.py` (`_BasePlot`, `_PanelMixin`, `_MarkerMixin`).
- **`Axes`** (`axes/_axes.py`) — grid-cell container; factory methods (`imshow`, `plot`, `bar`, `pcolormesh`, `plot_surface`, …) create plot objects and attach them.
- **`figure_esm.js`** — pure-JS canvas renderer (~4,400 lines); all rendering logic lives here. **Read `anyplotlib/FIGURE_ESM.md` first** — it is the section map.
- **`markers.py`** — static visual overlays (circles, arrows, lines, etc.) with a two-level dict registry: `plot.markers[type][name]`.
- **`widgets/`** — interactive draggable overlays (`RectangleWidget`, `CrosshairWidget`, etc.) that receive JS position updates.
- **`callbacks.py`** — event system: `Event` dataclass, `CallbackRegistry` (priority ordering, wildcard, pause/hold), `_EventMixin` (`add_event_handler`).
- **`embed.py`** — Jupyter-free embedding (Electron / web pages): `figure_state()`, `to_html()`/`save_html()`, `esm_path()`, and `FigureBridge` (transport-agnostic live Python↔JS sync). The JS counterpart is the `mount(el, state, opts)` export in `figure_esm.js`. See `docs/embedding.rst`.
- **`sphinx_anywidget/`** — Sphinx extension that makes anywidget figures live in docs pages via Pyodide (wheel builder, gallery scraper, `anywidget-figure` directive, `static/anywidget_bridge.js`).

## Package layout

```
anyplotlib/
├── __init__.py          # public API re-exports
├── _base_plot.py        # _BasePlot, _PanelMixin, _MarkerMixin
├── _utils.py            # b64 encoding, linestyle/colormap helpers
├── _repr_utils.py       # self-contained iframe HTML for non-kernel use
├── callbacks.py         # Event, CallbackRegistry, _EventMixin
├── markers.py           # MarkerRegistry, MarkerGroup
├── figure_esm.js        # the entire JS renderer (see FIGURE_ESM.md)
├── figure/              # Figure widget, GridSpec/SubplotSpec, subplots()
├── axes/                # Axes, InsetAxes
├── plot1d/              # Plot1D, Line1D, PlotBar
├── plot2d/              # Plot2D, PlotMesh
├── plot3d/              # Plot3D (surface / scatter / line)
├── widgets/             # Widget base + 1D/2D widget classes
├── sphinx_anywidget/    # Sphinx/Pyodide extension (own test suite)
└── tests/               # main test suite, grouped by area
```

## Python ↔ JS Data Flow

**Python → JS (push):** Every plot state mutation calls `plot._push()` → `figure._push(panel_id)` → serialises `_state` to JSON → writes to the dynamic traitlet `panel_{id}_json` (tagged `sync=True`) → JS observes and re-renders.

**JS → Python (events/widgets):** JS interaction events (drags, clicks, zoom, keys) come through the `event_json` traitlet → dispatched by `Figure._dispatch_event()` → `Widget._update_from_js()` for widget drags, then `plot.callbacks.fire(event)`.

**Adding state fields:** Add to `_state` in the constructor, include in `to_state_dict()`, and handle in `figure_esm.js`.

## Key Patterns

**`_push()` contract:** Any mutation to a plot's `_state` must end with `self._push()`. Forgetting this means changes won't appear in JS.

**Marker kwargs use matplotlib names** — translated to wire format in `MarkerGroup.to_wire()`:
```python
plot.add_circles(offsets, name="g1", facecolors="#f00", edgecolors="#fff", radius=5)
plot.markers["circles"]["g1"].set(radius=8)   # live update
```

**Widget (interactive overlay) pattern:** handlers register on the widget (or plot) via `add_event_handler` — directly or as a decorator:
```python
wid = plot.add_widget("crosshair", cx=64, cy=64)

@wid.add_event_handler("pointer_move")   # fires every drag frame — keep fast
def live(event): readout.value = f"({wid.cx:.1f}, {wid.cy:.1f})"

@wid.add_event_handler("pointer_up")     # fires once on release — safe for expensive work
def done(event): recompute(wid.cx, wid.cy)

@plot.add_event_handler("pointer_settled", ms=400)   # dwell-based settling
def settled(event): ...
```

**Label sizes and mini-TeX:** all label setters take an optional `fontsize` (CSS px), and label strings support a TeX subset inside `$...$` (superscripts `$10^{-3}$`, subscripts `$E_F$`, Greek `\alpha`, symbols `\times \AA \degree`) parsed at draw time by `_drawTex` in `figure_esm.js` — Python stores strings verbatim:
```python
plot.set_xlabel(r"$q_x$ ($\AA^{-1}$)", fontsize=13)
plot.set_tick_label_size(11)
```

**`subplots` squeeze behaviour** mirrors matplotlib: `(1,1)` → scalar `Axes`; `(1,N)`/`(N,1)` → 1-D array; `(M,N)` → 2-D array.

**`GridSpec` indexing** mirrors matplotlib exactly, including negative indices, slices, and multi-cell spans — see `tests/test_layouts/test_gridspec.py`.

## Developer Workflows

```bash
# Install (uses uv)
uv sync
uv run playwright install chromium   # one-time: browser for rendering tests

# Run the full test suite (pytest testpaths cover both suites)
uv run pytest

# Run a quick subset without coverage output
uv run pytest anyplotlib/tests/test_plot1d -q --no-cov

# Build docs (Sphinx Gallery, outputs to build/html/)
make html
make clean   # wipe build artefacts
```

Changelog entries: add a fragment file to `upcoming_changes/` (e.g.
`123.new_feature.rst`) — towncrier assembles `CHANGELOG.rst` at release time.

## Key Files

| File | Purpose |
|------|---------|
| `anyplotlib/figure/_figure.py` | `Figure` widget; layout engine; JS↔Python dispatch |
| `anyplotlib/figure/_gridspec.py` | `GridSpec`, `SubplotSpec` |
| `anyplotlib/figure/_subplots.py` | `subplots()` factory |
| `anyplotlib/axes/_axes.py` | `Axes` — plot factory methods |
| `anyplotlib/figure_esm.js` | All JS canvas rendering (~4,400 lines) |
| `anyplotlib/FIGURE_ESM.md` | Section map for `figure_esm.js` — read this before editing the JS |
| `anyplotlib/markers.py` | Static marker collections; `to_wire()` translation |
| `anyplotlib/widgets/` | Interactive overlay widgets |
| `anyplotlib/callbacks.py` | `CallbackRegistry`, `Event` dataclass, `_EventMixin` |
| `anyplotlib/tests/test_interactive/` | Callback + widget tests (good reference for event API) |
| `anyplotlib/tests/test_layouts/` | GridSpec / sizing pipeline / visual baseline tests |
| `Examples/` | Gallery examples (files must be named `plot_*.py`) |

## Important Constraints

- The **OO API only** — no `plt.plot()` style. Always create a `Figure` and call methods on `Axes`.
- Use **`import anyplotlib as apl`** in all examples, docs, and docstrings.
- Plot objects (`Plot2D` etc.) store all display state in `self._state` (plain dict). Never add traitlets to them.
- `Figure` adds per-panel traits **dynamically** (`add_traits(panel_{id}_json=...)`); check `has_trait()` before accessing.
- Colormap LUTs are built via colorcet (`_build_colormap_lut` in `_utils.py`) and serialised as `[[r,g,b], ...]` in `_state["colormap_data"]`; matplotlib is only a fallback and not a dependency.
- Docs examples in `Examples/` must have a module-level docstring (first lines) for Sphinx Gallery to pick them up; they are executed by `tests/test_examples`.
- Playwright tests share a session-scoped Chromium fixture (`anyplotlib/conftest.py`); they **error** (not skip) if browsers are missing — run `uv run playwright install chromium` first.
- When possible stop and ask questions if you're unsure about how something works.

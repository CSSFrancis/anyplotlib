# anyplotlib

[![codecov](https://codecov.io/gh/CSSFrancis/anyplotlib/branch/main/graph/badge.svg)](https://codecov.io/gh/CSSFrancis/anyplotlib)
[![Tests](https://github.com/CSSFrancis/anyplotlib/actions/workflows/tests.yml/badge.svg)](https://github.com/CSSFrancis/anyplotlib/actions/workflows/tests.yml)

**anyplotlib** is a fast, interactive plotting library for Jupyter, built on
[anywidget](https://anywidget.dev/) and a pure-JavaScript canvas renderer.
It follows matplotlib's object-oriented API — create a `Figure`, call methods
on `Axes` — so switching is often a one-line change:

```python
import anyplotlib as apl

fig, ax = apl.subplots(1, 1)        # same shape as plt.subplots(1, 1)
ax.imshow(data)                     # pan, zoom, and inspect — live
fig                                 # display in a Jupyter cell
```

If you have used matplotlib's OO interface, you already know most of
anyplotlib. What you gain is interactivity that stays fast on large data —
without a kernel round-trip per frame.

## Why another plotting library?

Matplotlib is a superb tool for publication-quality static figures, but its
interactive notebook story (`ipympl`) re-renders the whole figure on the
Python side for every frame. anyplotlib makes the opposite trade-off:

- **All rendering happens in the browser.** Python serialises compact state
  (raw image bytes, base64-encoded float arrays) once; pan/zoom/drag never
  touch the kernel.
- **Each image, line collection, or marker group is a single canvas object**,
  so blitting works and drag interactions run at full frame rate.
- **The scope is deliberately limited.** The OO API only (no `plt.plot()`
  global state), a curated set of plot types and marker styles, and raster
  canvas output rather than vector graphics. For print-quality SVG/PDF
  figures, matplotlib remains the right tool.

## Features

- **Plot types** — `plot` (1-D lines with markers, linestyles, legends, log y),
  `imshow` (2-D images with colormaps, colorbars, scale bars, overlay masks),
  `pcolormesh` (non-uniform 2-D meshes), `bar` (grouped, horizontal, log,
  value labels), and 3-D `plot_surface` / `scatter3d` / `plot3d`.
- **Layouts** — `subplots`, matplotlib-compatible `GridSpec` indexing
  (slices, spans, negative indices), `width_ratios`/`height_ratios`,
  `sharex`/`sharey` linked pan-zoom, and floating inset axes with
  minimize/maximize.
- **Markers** — static overlays (points, circles, ellipses, rectangles,
  polygons, arrows, line segments, text, h/v lines) with matplotlib-style
  kwargs and live `.set()` updates.
- **Widgets** — draggable overlays (`RectangleWidget`, `CircleWidget`,
  `AnnularWidget`, `CrosshairWidget`, `PolygonWidget`, `VLineWidget`,
  `HLineWidget`, `RangeWidget`, …) that report positions back to Python.
- **Events** — a two-tier callback system: `pointer_move` fires every drag
  frame for cheap updates; `pointer_settled` / `pointer_up` fire once for
  expensive recomputation. Plus `key_down`, `wheel`, `double_click`, and
  per-line scoped handlers.
- **Interactive docs** — the bundled `anyplotlib.sphinx_anywidget` extension
  makes any anywidget figure live in Sphinx Gallery pages via Pyodide — no
  kernel or server needed.
- **Embeddable anywhere** — figures don't require Jupyter. Export
  self-contained HTML (`fig.save_html("plot.html")`), mount the renderer
  directly in an Electron app or web page via the JS `mount()` API, or run a
  live Python backend over any transport with `anyplotlib.embed.FigureBridge`
  (full callback support). See the embedding guide in the docs.

```python
import numpy as np
import anyplotlib as apl

fig, (ax_img, ax_spec) = apl.subplots(1, 2, figsize=(900, 400))
img  = ax_img.imshow(stack.mean(axis=2), cmap="viridis")
spec = ax_spec.plot(stack[64, 64], units="eV")

cross = img.add_widget("crosshair", cx=64, cy=64)

@cross.add_event_handler("pointer_move")   # every drag frame — keep it cheap
def update(event):
    spec.set_data(stack[int(cross.cy), int(cross.cx)])
```

## Installation

```bash
pip install anyplotlib
```

Works anywhere anywidget does: JupyterLab, Jupyter Notebook, VS Code,
PyCharm, Google Colab, and marimo. Dependencies are intentionally light:
`anywidget`, `numpy`, `traitlets`, and `colorcet` (no matplotlib required).

## Documentation

Full docs, a live example gallery (interactive in the browser — no install),
and the event-system guide are at
**[cssfrancis.github.io/anyplotlib](https://cssfrancis.github.io/anyplotlib/)**.

## Development

```bash
git clone https://github.com/CSSFrancis/anyplotlib
cd anyplotlib
uv sync                              # install with dev dependencies
uv run playwright install chromium   # browsers for rendering tests
uv run pytest                        # full suite (unit + Playwright + visual)
make html                            # build the docs locally
```

The architecture is a single `anywidget.AnyWidget` (`Figure`) that owns all
traitlets; plot objects are plain Python classes that serialise their state
dicts to per-panel traits, and `figure_esm.js` renders them. See
[AGENTS.md](AGENTS.md) for the codebase guide and
[`anyplotlib/FIGURE_ESM.md`](anyplotlib/FIGURE_ESM.md) for a map of the JS
renderer.

## License

MIT — see [LICENSE](LICENSE).

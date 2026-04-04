"""
Plot Update Comparison
======================

There are a couple of different "costs" asscociated with rendering plots and images. There is
usually a Python-side cost as well as a browser-side rendering cost. We've broken down those
two costs here comparing different libraries for the first cost.  The second is harder to
measure.  We've done it for anyplotlib but doing it for `ipympl`, bokeh and plotly is a
little more difficult.

* **Python pre-render** — everything that happens in the Python process before
  bytes reach the browser (``timeit``-measured, no browser needed).
* **JS canvas render** — the actual canvas paint time measured inside headless
  Chromium via Playwright (anyplotlib only; see the third and fourth charts).

.. note::

   The Python-side timings are pure-Python ``timeit`` benchmarks — no browser
   is involved.  The JS render timings use Playwright's
   ``requestAnimationFrame`` loop and ``window._aplTiming`` to measure
   inter-frame intervals in a real Chromium renderer.

What each Python measurement covers
-------------------------------------

+---------------+---------------------------------------------------------------+
| Library       | What is timed                                                 |
+===============+===============================================================+
| anyplotlib    | ``plot.update(data)`` — float → uint8 normalise → base64      |
|               | encode → LUT rebuild → state-dict assembly → json.dumps →     |
|               | traitlet dispatch to JS renderer.                             |
+---------------+---------------------------------------------------------------+
| ipympl        | ``im.set_data(data); fig.canvas.draw()`` — fully rasterises   |
|               | the figure to an Agg pixel buffer, then encodes it as a PNG   |
|               | blob ready for the ipympl comm channel.  This is the complete |
|               | Python-side cost before the PNG is sent to the browser.       |
+---------------+---------------------------------------------------------------+
| Plotly        | ``fig.data[0].z = data.tolist(); fig.to_json()`` — builds the |
|               | full JSON blob that Plotly.js receives; every float becomes a |
|               | decimal string.  Plotly.js WebGL/SVG render is additional.    |
+---------------+---------------------------------------------------------------+
| Bokeh         | ``source.data = {"image": [data]}; json_item(p)`` — builds    |
|               | the full JSON document patch that Bokeh.js receives.  Canvas  |
|               | render is additional.                                         |
+---------------+---------------------------------------------------------------+

"""
# sphinx_gallery_start_ignore
from __future__ import annotations

import pathlib
import tempfile
import timeit
import warnings

import matplotlib
matplotlib.use("Agg")   # must be set before pyplot import — used for ipympl measurement
import matplotlib.pyplot as plt
import numpy as np

# ---------------------------------------------------------------------------
# Optional library imports — degrade gracefully if not installed
# ---------------------------------------------------------------------------

try:
    from playwright.sync_api import sync_playwright as _sync_playwright
    _HAS_PLAYWRIGHT = True
except ImportError:
    _HAS_PLAYWRIGHT = False
    warnings.warn("Playwright not installed — JS render timing omitted.", stacklevel=1)

try:
    import plotly.graph_objects as _go
    _HAS_PLOTLY = True
except ImportError:
    _HAS_PLOTLY = False
    warnings.warn("Plotly not installed — Plotly bars omitted.", stacklevel=1)

try:
    from bokeh.plotting import figure as _bk_figure
    from bokeh.models import ColumnDataSource as _CDS
    from bokeh.embed import json_item as _json_item
    _HAS_BOKEH = True
except ImportError:
    _HAS_BOKEH = False
    warnings.warn("Bokeh not installed — Bokeh bars omitted.", stacklevel=1)

import anyplotlib as apl

# ---------------------------------------------------------------------------
# Timing helpers
# ---------------------------------------------------------------------------

_REPEATS = 5
_NUMBER  = 3


def _timeit_min_ms(stmt) -> float:
    """Return the best (minimum) per-call time in milliseconds."""
    raw = timeit.repeat(stmt=stmt, number=_NUMBER, repeat=_REPEATS)
    return min(t / _NUMBER * 1000 for t in raw)


# rAF-paced bench loop — mirrors tests/conftest.py _run_bench.
# Each frame perturbs one state field so the blit-cache is invalidated and
# the full decode → LUT → render path executes every cycle.
_JS_BENCH = """
([panelId, nWarmup, nSamples, field, delta]) =>
  new Promise((resolve, reject) => {
    const total = nWarmup + nSamples;
    let i = 0;
    function step() {
      if (i >= total) {
        resolve(window._aplTiming ? window._aplTiming[panelId] : null);
        return;
      }
      const key = 'panel_' + panelId + '_json';
      try {
        const st = JSON.parse(window._aplModel.get(key));
        st[field] = (st[field] || 0) + delta;
        window._aplModel.set(key, JSON.stringify(st));
      } catch(e) { reject(e); return; }
      if (i === nWarmup - 1) {
        if (window._aplTiming) delete window._aplTiming[panelId];
      }
      i++;
      requestAnimationFrame(step);
    }
    requestAnimationFrame(step);
  })
"""


def _measure_js_ms_all(pairs, n_warmup=3, n_samples=12):
    """Measure JS render time for a list of (widget, panel_id, field, delta).

    Opens each widget in a shared headless Chromium session, runs the rAF
    bench loop, and returns a list of mean_ms values (None on failure).
    Only called when _HAS_PLAYWRIGHT is True.
    """
    from anyplotlib._repr_utils import build_standalone_html

    results_js = []
    tmp_files = []
    try:
        with _sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-setuid-sandbox"],
            )
            for pair in pairs:
                widget, panel_id, field, delta = pair[:4]
                # Per-pair timeout: large images take longer to decode and paint.
                # Formula: max(30_000, sz*sz // 200) — scales from 30 s up for 4K+.
                timeout_ms = pair[4] if len(pair) > 4 else 60_000
                html = build_standalone_html(widget, resizable=False)
                html = html.replace(
                    "renderFn({ model, el });",
                    "renderFn({ model, el }); window._aplReady = true;",
                )
                html = html.replace(
                    "const model   = makeModel(STATE);",
                    "const model   = makeModel(STATE);\nwindow._aplModel = model;",
                )
                with tempfile.NamedTemporaryFile(
                    suffix=".html", mode="w", encoding="utf-8", delete=False
                ) as fh:
                    fh.write(html)
                    tmp = pathlib.Path(fh.name)
                tmp_files.append(tmp)
                try:
                    page = browser.new_page()
                    page.goto(tmp.as_uri())
                    page.wait_for_function(
                        "() => window._aplReady === true", timeout=timeout_ms
                    )
                    page.evaluate(
                        "() => new Promise(r =>"
                        " requestAnimationFrame(() => requestAnimationFrame(r)))"
                    )
                    timing = page.evaluate(
                        _JS_BENCH,
                        [panel_id, n_warmup, n_samples, field, delta],
                    )
                    page.close()
                    results_js.append(timing["mean_ms"] if timing else None)
                except Exception:
                    results_js.append(None)
            browser.close()
    finally:
        for tmp in tmp_files:
            tmp.unlink(missing_ok=True)
    return results_js


# ---------------------------------------------------------------------------
# Benchmark configuration
# ---------------------------------------------------------------------------

_SIZES_2D      = [64, 256, 512, 1024, 2048]
_SIZES_1D = [100, 1_000, 10_000, 100_000]

rng = np.random.default_rng(42)

# Pre-generate fixed frames so array creation is outside the timing loops.
_frames_2d = {s: rng.uniform(size=(s, s)).astype(np.float32) for s in _SIZES_2D}
_frames_1d = {n: np.cumsum(rng.standard_normal(n)).astype(np.float32)
              for n in _SIZES_1D}

_LIBRARIES = ["anyplotlib", "ipympl", "plotly", "bokeh"]

results_2d: dict[str, dict[int, float | None]] = {lib: {} for lib in _LIBRARIES}
results_1d: dict[str, dict[int, float | None]] = {lib: {} for lib in _LIBRARIES}

# ---------------------------------------------------------------------------
# 2-D image benchmark
# ---------------------------------------------------------------------------

for sz in _SIZES_2D:
    data = _frames_2d[sz]

    # ── anyplotlib: normalize → uint8 → base64 → LUT → json push ────────────
    _fig_apl, _ax_apl = apl.subplots(1, 1, figsize=(min(sz, 640), min(sz, 640)))
    _plot_apl = _ax_apl.imshow(data)
    _update_frames = [rng.uniform(size=(sz, sz)).astype(np.float32)
                      for _ in range(_NUMBER)]
    _idx = [0]

    def _make_apl_update(plot, frames, idx):
        def _fn():
            plot.update(frames[idx[0] % len(frames)])
            idx[0] += 1
        return _fn

    results_2d["anyplotlib"][sz] = _timeit_min_ms(
        _make_apl_update(_plot_apl, _update_frames, _idx)
    )

    # ── ipympl: set_data + full Agg rasterisation (PNG comm pathway) ────────
    _fig_mpl, _ax_mpl = plt.subplots()
    _im_mpl = _ax_mpl.imshow(data, cmap="viridis")
    _canvas_mpl = _fig_mpl.canvas
    _new_mpl = rng.uniform(size=(sz, sz)).astype(np.float32)

    def _make_mpl_update(im, canvas, new_data):
        def _fn():
            im.set_data(new_data)
            canvas.draw()
        return _fn

    results_2d["ipympl"][sz] = _timeit_min_ms(
        _make_mpl_update(_im_mpl, _canvas_mpl, _new_mpl)
    )
    plt.close(_fig_mpl)

    # ── Plotly: assign z list + serialise to JSON ────────────────────────────
    if _HAS_PLOTLY:
        _pgo_fig = _go.Figure(_go.Heatmap(z=data.tolist()))
        _new_plotly = rng.uniform(size=(sz, sz)).astype(np.float32).tolist()

        def _make_plotly_update(fig, new_z):
            def _fn():
                fig.data[0].z = new_z
                fig.to_json()
            return _fn

        results_2d["plotly"][sz] = _timeit_min_ms(
            _make_plotly_update(_pgo_fig, _new_plotly)
        )
    else:
        results_2d["plotly"][sz] = None

    # ── Bokeh: replace source.data + serialise full document ────────────────
    if _HAS_BOKEH:
        _bk_src = _CDS(data={"image": [data], "x": [0], "y": [0],
                              "dw": [sz], "dh": [sz]})
        _bk_plot = _bk_figure(width=400, height=400)
        _bk_plot.image(image="image", x="x", y="y", dw="dw", dh="dh",
                       source=_bk_src, palette="Viridis256")
        _new_bokeh = rng.uniform(size=(sz, sz)).astype(np.float32)

        def _make_bokeh_update(src, new_data, plot, w, h):
            def _fn():
                src.data = {"image": [new_data], "x": [0], "y": [0],
                            "dw": [w], "dh": [h]}
                _json_item(plot)
            return _fn

        results_2d["bokeh"][sz] = _timeit_min_ms(
            _make_bokeh_update(_bk_src, _new_bokeh, _bk_plot, sz, sz)
        )
    else:
        results_2d["bokeh"][sz] = None

# ---------------------------------------------------------------------------
# 1-D line benchmark
# ---------------------------------------------------------------------------

for n_pts in _SIZES_1D:
    xs = np.arange(n_pts, dtype=np.float32)
    ys = _frames_1d[n_pts]

    # ── anyplotlib ───────────────────────────────────────────────────────────
    _fig_apl1, _ax_apl1 = apl.subplots(1, 1, figsize=(640, 320))
    _plot_apl1 = _ax_apl1.plot(ys)
    _new_ys_apl = rng.standard_normal(n_pts).cumsum().astype(np.float32)

    def _make_apl1d(plot, new_y):
        def _fn(): plot.update(new_y)
        return _fn

    results_1d["anyplotlib"][n_pts] = _timeit_min_ms(
        _make_apl1d(_plot_apl1, _new_ys_apl)
    )

    # ── ipympl: set_ydata + full Agg rasterisation (PNG comm pathway) ───────
    _fig_mpl1, _ax_mpl1 = plt.subplots()
    (_line_mpl,) = _ax_mpl1.plot(xs, ys)
    _new_ys_mpl = rng.standard_normal(n_pts).cumsum().astype(np.float32)

    def _make_mpl1d(line, canvas, new_y):
        def _fn():
            line.set_ydata(new_y)
            canvas.draw()
        return _fn

    results_1d["ipympl"][n_pts] = _timeit_min_ms(
        _make_mpl1d(_line_mpl, _fig_mpl1.canvas, _new_ys_mpl)
    )
    plt.close(_fig_mpl1)

    # ── Plotly ───────────────────────────────────────────────────────────────
    if _HAS_PLOTLY:
        _pgo_fig1 = _go.Figure(_go.Scatter(x=xs.tolist(), y=ys.tolist()))
        _new_ys_plotly = rng.standard_normal(n_pts).cumsum().astype(np.float32).tolist()

        def _make_plotly1d(fig, new_y):
            def _fn():
                fig.data[0].y = new_y
                fig.to_json()
            return _fn

        results_1d["plotly"][n_pts] = _timeit_min_ms(
            _make_plotly1d(_pgo_fig1, _new_ys_plotly)
        )
    else:
        results_1d["plotly"][n_pts] = None

    # ── Bokeh ─────────────────────────────────────────────────────────────────
    if _HAS_BOKEH:
        _bk_src1 = _CDS(data={"x": xs.tolist(), "y": ys.tolist()})
        _bk_plot1 = _bk_figure(width=600, height=300)
        _bk_plot1.line("x", "y", source=_bk_src1)
        _new_ys_bokeh = rng.standard_normal(n_pts).cumsum().astype(np.float32).tolist()

        def _make_bokeh1d(src, plot, new_x, new_y):
            def _fn():
                src.data = {"x": new_x, "y": new_y}
                _json_item(plot)
            return _fn

        results_1d["bokeh"][n_pts] = _timeit_min_ms(
            _make_bokeh1d(_bk_src1, _bk_plot1, xs.tolist(), _new_ys_bokeh)
        )
    else:
        results_1d["bokeh"][n_pts] = None

# ---------------------------------------------------------------------------
# JS render timing — anyplotlib only (headless Chromium via Playwright)
# ---------------------------------------------------------------------------
# _recordFrame() in figure_esm.js timestamps the *start* of every draw call,
# so the inter-frame interval captured by _aplTiming approximates the full
# JS render cycle: JSON.parse → uint8 decode → LUT expand → ImageBitmap →
# ctx.drawImage (2-D) or ctx.lineTo loop (1-D).

results_2d_js: dict[int, float | None] = {s: None for s in _SIZES_2D}
results_1d_js: dict[int, float | None] = {n: None for n in _SIZES_1D}

if _HAS_PLAYWRIGHT:
    _pairs_2d_js = []
    for _sz in _SIZES_2D:
        _fjs, _ajs = apl.subplots(1, 1, figsize=(min(_sz, 640), min(_sz, 640)))
        _pjs = _ajs.imshow(_frames_2d[_sz])
        # Timeout scales with image area: larger images take longer to decode
        # and paint in Chromium.  Formula: max(30 s, sz²/200) ms.
        _js_timeout = max(30_000, _sz * _sz // 200)
        _pairs_2d_js.append((_fjs, _pjs._id, "display_min", 1e-4, _js_timeout))

    for _sz, _t in zip(_SIZES_2D, _measure_js_ms_all(_pairs_2d_js)):
        results_2d_js[_sz] = _t

    _pairs_1d_js = []
    for _npts in _SIZES_1D:
        _fjs1, _ajs1 = apl.subplots(1, 1, figsize=(640, 320))
        _pjs1 = _ajs1.plot(_frames_1d[_npts])
        _pairs_1d_js.append((_fjs1, _pjs1._id, "view_x0", 1e-4))

    for _npts, _t in zip(_SIZES_1D, _measure_js_ms_all(_pairs_1d_js)):
        results_1d_js[_npts] = _t

# ---------------------------------------------------------------------------
# Chart helpers
# ---------------------------------------------------------------------------

_COLORS = {
    "anyplotlib": "#1976D2",
    "ipympl":     "#E64A19",
    "plotly":     "#7B1FA2",
    "bokeh":      "#2E7D32",
}

# Short legend labels shown inside the anyplotlib bar chart.
_LABELS = {
    "anyplotlib": "anyplotlib  (float→uint8→b64→json→traitlet)",
    "ipympl":     "ipympl      (set_data + Agg render → PNG comm)",
    "plotly":     "Plotly      (z=list + to_json)",
    "bokeh":      "Bokeh       (source.data + json_item)",
}


def _results_to_array(results, sizes):
    """Build a (N_sizes, N_libs) float array.

    Missing entries (None) become 0.0 — valid JSON, and invisible on a
    log-scale axis where 0 is clamped to 1e-10 below the visible range.
    Using NaN would produce bare ``NaN`` tokens that JSON.parse rejects,
    silently blanking the chart.
    """
    rows = []
    for s in sizes:
        rows.append([
            results[lib].get(s) if results[lib].get(s) is not None else 0.0
            for lib in _LIBRARIES
        ])
    return np.array(rows, dtype=float)


# ---------------------------------------------------------------------------
# Chart 1 — 2-D image update  (Python pre-render, all four libraries)
# ---------------------------------------------------------------------------

_size_labels_2d = [f"{s}²" for s in _SIZES_2D]
_heights_2d = _results_to_array(results_2d, _SIZES_2D)

fig2d, ax2d = apl.subplots(1, 1, figsize=(900, 480))
ax2d.bar(
    _size_labels_2d,
    _heights_2d,
    group_labels=[_LABELS[lib] for lib in _LIBRARIES],
    group_colors=[_COLORS[lib] for lib in _LIBRARIES],
    log_scale=True,
    show_values=False,
    width=0.85,
    y_units="ms per call (log scale)",
    units="Array size",
)
fig2d
# sphinx_gallery_end_ignore

# %%
# 1-D line update comparison  (Python pre-render)
# ------------------------------------------------

# sphinx_gallery_start_ignore

_size_labels_1d = [f"{n:,}" for n in _SIZES_1D]
_heights_1d = _results_to_array(results_1d, _SIZES_1D)

fig1d, ax1d = apl.subplots(1, 1, figsize=(900, 480))
ax1d.bar(
    _size_labels_1d,
    _heights_1d,
    group_labels=[_LABELS[lib] for lib in _LIBRARIES],
    group_colors=[_COLORS[lib] for lib in _LIBRARIES],
    log_scale=True,
    show_values=False,
    width=0.85,
    y_units="ms per call (log scale)",
    units="Number of points",
)
fig1d
# sphinx_gallery_end_ignore

# %%
# anyplotlib: Python prep vs JS canvas render
# -------------------------------------------
#
# The two charts above show only the Python-side cost.  The charts below add
# the JS render time for anyplotlib measured inside a real Chromium renderer
# via Playwright (``window._aplTiming`` populated by ``_recordFrame()`` in
# ``figure_esm.js``).  The sum of both bars is the **total time-to-pixel**
# for an anyplotlib update.
#
# For ipympl, Plotly, and Bokeh the browser render cost is additional but not
# captured here — measuring it requires running their respective JS engines in
# a live browser session.
#
# .. note::
#
#    If Playwright is not installed the JS bars are absent (zero height) and
#    a ``UserWarning`` is emitted at import time.  Install Playwright
#    (``pip install playwright && playwright install chromium``) to populate
#    the JS timing columns.

# sphinx_gallery_start_ignore

_apl_py_2d = np.array([results_2d["anyplotlib"].get(s, 0.0) or 0.0
                        for s in _SIZES_2D])
_apl_js_2d = np.array([results_2d_js.get(s) or 0.0 for s in _SIZES_2D])
_breakdown_2d = np.column_stack([_apl_py_2d, _apl_js_2d])

fig_bd2d, ax_bd2d = apl.subplots(1, 1, figsize=(700, 400))
ax_bd2d.bar(
    _size_labels_2d,
    _breakdown_2d,
    group_labels=["Python prep", "JS canvas render"],
    group_colors=["#1976D2", "#4CAF50"],
    log_scale=True,
    show_values=False,
    width=0.7,
    y_units="ms per call (log scale)",
    units="Array size  —  anyplotlib 2-D imshow",
)
fig_bd2d
# sphinx_gallery_end_ignore

#%%

# sphinx_gallery_start_ignore
_apl_py_1d = np.array([results_1d["anyplotlib"].get(n, 0.0) or 0.0
                        for n in _SIZES_1D])
_apl_js_1d = np.array([results_1d_js.get(n) or 0.0 for n in _SIZES_1D])
_breakdown_1d = np.column_stack([_apl_py_1d, _apl_js_1d])

fig_bd1d, ax_bd1d = apl.subplots(1, 1, figsize=(700, 400))
ax_bd1d.bar(
    _size_labels_1d,
    _breakdown_1d,
    group_labels=["Python prep", "JS canvas render"],
    group_colors=["#1976D2", "#4CAF50"],
    log_scale=True,
    show_values=False,
    width=0.7,
    y_units="ms per call (log scale)",
    units="Number of points  —  anyplotlib 1-D line",
)
fig_bd1d
# sphinx_gallery_end_ignore

#%%

"""
Library Update-Speed Comparison
================================

Times the **full Python-side cost** of pushing one data frame from Python to
the browser for four plotting libraries.  Every measurement goes from "change
the data" to "Python has done everything it can before the browser takes over".

.. note::

   These are pure-Python ``timeit`` benchmarks — no browser is involved.
   The goal is to isolate the CPU work that happens *before* bytes leave the
   kernel.  Browser render time (typically 1–20 ms) is additional for all
   libraries.

What each measurement covers
------------------------------

+---------------+---------------------------------------------------------------+
| Library       | What is timed                                                 |
+===============+===============================================================+
| anyplotlib    | ``plot.update(data)`` — float → uint8 normalise → base64      |
|               | encode → LUT rebuild → state-dict assembly → json.dumps       |
+---------------+---------------------------------------------------------------+
| matplotlib    | ``im.set_data(data); fig.canvas.draw()`` — marks data stale,  |
|               | then **fully rasterises** the figure to an Agg pixel buffer.  |
|               | This is equivalent to what ipympl does before sending a PNG   |
|               | over the comm channel.                                        |
+---------------+---------------------------------------------------------------+
| Plotly        | ``fig.data[0].z = data.tolist(); fig.to_json()`` — builds the |
|               | JSON blob that Plotly.js receives; every float becomes a      |
|               | decimal string.  Plotly.js WebGL/SVG render is additional.    |
+---------------+---------------------------------------------------------------+
| Bokeh         | ``source.data = {"image": [data]}; json_item(p)`` — builds    |
|               | the JSON document patch that Bokeh.js receives.  Canvas       |
|               | render is additional.                                         |
+---------------+---------------------------------------------------------------+

Skipping large Plotly / Bokeh sizes
-------------------------------------
Plotly and Bokeh are skipped for 2-D arrays larger than 512² because their
JSON float serialisation becomes impractically large (~10 MB for 1024² vs
anyplotlib's ~1.3 MB base64 blob).  The skipped bars are marked ``—`` on the
chart.
"""
from __future__ import annotations

import json
import pathlib
import timeit
import warnings

import matplotlib
matplotlib.use("Agg")          # must be set before pyplot import
import matplotlib.pyplot as plt
import numpy as np

# ---------------------------------------------------------------------------
# Optional library imports — degrade gracefully if not installed
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Benchmark configuration
# ---------------------------------------------------------------------------

_SIZES_2D      = [64, 256, 512, 1024, 2048]
_SKIP_ABOVE_2D = 512        # Plotly / Bokeh JSON size becomes untenable above this

_SIZES_1D = [100, 1_000, 10_000, 100_000]

rng = np.random.default_rng(42)

# Pre-generate fixed frames so array creation is outside the timing loops.
_frames_2d = {s: rng.uniform(size=(s, s)).astype(np.float32) for s in _SIZES_2D}
_frames_1d = {n: np.cumsum(rng.standard_normal(n)).astype(np.float32)
              for n in _SIZES_1D}

_LIBRARIES = ["anyplotlib", "matplotlib", "plotly", "bokeh"]

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
    # Pre-generate update frames so creation cost is excluded.
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

    # ── matplotlib: set_data + full Agg rasterisation ───────────────────────
    _fig_mpl, _ax_mpl = plt.subplots()
    _im_mpl = _ax_mpl.imshow(data, cmap="viridis")
    _canvas_mpl = _fig_mpl.canvas
    _new_mpl = rng.uniform(size=(sz, sz)).astype(np.float32)

    def _make_mpl_update(im, canvas, new_data):
        def _fn():
            im.set_data(new_data)
            canvas.draw()
        return _fn

    results_2d["matplotlib"][sz] = _timeit_min_ms(
        _make_mpl_update(_im_mpl, _canvas_mpl, _new_mpl)
    )
    plt.close(_fig_mpl)

    # ── Plotly: assign z list + serialise to JSON ────────────────────────────
    if _HAS_PLOTLY and sz <= _SKIP_ABOVE_2D:
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
    if _HAS_BOKEH and sz <= _SKIP_ABOVE_2D:
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

    # ── matplotlib ───────────────────────────────────────────────────────────
    _fig_mpl1, _ax_mpl1 = plt.subplots()
    (_line_mpl,) = _ax_mpl1.plot(xs, ys)
    _new_ys_mpl = rng.standard_normal(n_pts).cumsum().astype(np.float32)

    def _make_mpl1d(line, canvas, new_y):
        def _fn():
            line.set_ydata(new_y)
            canvas.draw()
        return _fn

    results_1d["matplotlib"][n_pts] = _timeit_min_ms(
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
# Chart helpers
# ---------------------------------------------------------------------------

_COLORS = {
    "anyplotlib": "#1976D2",
    "matplotlib": "#E64A19",
    "plotly":     "#7B1FA2",
    "bokeh":      "#2E7D32",
}

# Human-readable description of what each measurement covers (for the legend).
_LABELS = {
    "anyplotlib": "anyplotlib  (float→uint8→b64→json)",
    "matplotlib": "matplotlib  (set_data + Agg render)",
    "plotly":     "Plotly      (z=list + to_json)",
    "bokeh":      "Bokeh       (source.data + json_item)",
}


def _grouped_bar(ax, sizes, results, size_labels, title, ylabel,
                 skip_note=None):
    """Draw a grouped bar chart on *ax* (log-scale Y)."""
    n_sizes = len(sizes)
    n_libs  = len(_LIBRARIES)
    width   = 0.78 / n_libs
    x       = np.arange(n_sizes)

    for i, lib in enumerate(_LIBRARIES):
        vals   = [results[lib].get(s) for s in sizes]
        color  = _COLORS[lib]
        offset = (i - (n_libs - 1) / 2) * width

        present = [(j, v) for j, v in enumerate(vals) if v is not None]
        missing = [j for j, v in enumerate(vals) if v is None]

        if present:
            jj, vv = zip(*present)
            bars = ax.bar(
                [x[j] + offset for j in jj],
                vv,
                width=width * 0.88,
                label=_LABELS[lib],
                color=color,
                alpha=0.88,
                zorder=3,
            )
            for bar, v in zip(bars, vv):
                label_str = f"{v:.2f}" if v < 10 else f"{v:.1f}"
                ax.text(
                    bar.get_x() + bar.get_width() / 2,
                    bar.get_height() * 1.18,
                    label_str,
                    ha="center", va="bottom",
                    fontsize=6, color=color, fontweight="bold",
                )

        for j in missing:
            ax.text(
                x[j] + offset, ax.get_ylim()[0] if ax.get_yscale() == "log" else 0,
                "n/a",
                ha="center", va="bottom",
                fontsize=6, color=color, alpha=0.55, style="italic",
            )

    ax.set_yscale("log")
    ax.set_xticks(x)
    ax.set_xticklabels(size_labels, fontsize=9)
    ax.set_xlabel("Array size", fontsize=9)
    ax.set_ylabel(ylabel, fontsize=9)
    ax.set_title(title, fontsize=10, pad=8)
    ax.legend(fontsize=7.5, loc="upper left")
    ax.grid(axis="y", linestyle="--", alpha=0.35, zorder=0)

    if skip_note:
        ax.text(0.99, 0.02, skip_note, transform=ax.transAxes,
                fontsize=7, ha="right", va="bottom", color="#666",
                style="italic")


# ---------------------------------------------------------------------------
# Figure 1 — 2-D image update
# ---------------------------------------------------------------------------

fig2d, ax2d = plt.subplots(figsize=(10, 5.5), layout="constrained")
_grouped_bar(
    ax2d,
    sizes=_SIZES_2D,
    results=results_2d,
    size_labels=[f"{s}²" for s in _SIZES_2D],
    title="2-D image update — full Python-side cost  (lower is better)",
    ylabel="time per call (ms, log scale)",
    skip_note=(
        "Plotly / Bokeh omitted above 512²:\n"
        "1024² JSON payload ≈ 10 MB  vs  anyplotlib ≈ 1.3 MB base64"
    ),
)
fig2d.tight_layout(pad=1.2)
plt.show()

# %%
# 1-D line update comparison
# --------------------------
#
# For 1-D line plots anyplotlib currently serialises arrays via
# ``array.tolist()`` (plain JSON floats) — the same path as Plotly and Bokeh —
# so the costs are comparable at all sizes.  anyplotlib's advantage is
# concentrated in the 2-D image path where uint8 base64 encoding gives a
# dramatically smaller payload and eliminates the per-float text conversion.

fig1d, ax1d = plt.subplots(figsize=(10, 5.5), layout="constrained")
_grouped_bar(
    ax1d,
    sizes=_SIZES_1D,
    results=results_1d,
    size_labels=[f"{n:,}" for n in _SIZES_1D],
    title="1-D line update — full Python-side cost  (lower is better)",
    ylabel="time per call (ms, log scale)",
)
fig1d.tight_layout(pad=1.2)
plt.show()





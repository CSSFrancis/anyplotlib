"""
Tests for arbitrary inset placement (``anchor=``) and mark_inset-style region
indications / callouts (``InsetAxes.indicate_region`` / ``clear_indication``).

Unit tests (no browser)
-----------------------
  * ``add_inset(..., anchor=(x, y))`` state: anchor in inset_specs, corner None.
  * corner-only path still defaults (anchor None); anchor supersedes corner.
  * ``indicate_region`` serialises into ``layout.indications`` and round-trips
    through ``figure_state`` (save_html path).
  * replace + clear semantics.

Playwright tests (headless Chromium, via the public ``mount()`` handle)
-----------------------------------------------------------------------
  * Anchored inset's DOM top-left sits at ``anchor × figure``.
  * The callout canvas paints the dashed rect at the parent region AND leader
    lines between rect and inset (colour-pixel assertions).
  * The rect tracks parent zoom/pan (change the view → the rect bbox moves).
  * Minimizing the inset hides the leaders (rect stays).
  * ``exportPNG`` composites the indication (colour present only with it).
"""
from __future__ import annotations

import base64
import json
import pathlib
import tempfile

import numpy as np
import pytest

import anyplotlib as apl
from anyplotlib.axes import InsetAxes
from anyplotlib.embed import esm_path, figure_state
from anyplotlib.tests._png_utils import decode_png


# ═══════════════════════════════════════════════════════════════════════════
# Unit tests
# ═══════════════════════════════════════════════════════════════════════════

def _make_fig():
    fig, ax = apl.subplots(1, 1, figsize=(640, 480))
    ax.imshow(np.zeros((64, 64), dtype=np.float32))
    return fig, ax


def _inset_spec(fig, plot_id):
    layout = json.loads(fig.layout_json)
    return next(s for s in layout["inset_specs"] if s["id"] == plot_id)


# ── anchored placement ────────────────────────────────────────────────────

def test_add_inset_anchor_state():
    fig, _ = _make_fig()
    inset = fig.add_inset(0.3, 0.25, anchor=(0.55, 0.10), title="Callout")
    plot = inset.imshow(np.zeros((32, 32), dtype=np.float32))

    assert isinstance(inset, InsetAxes)
    assert inset.anchor == (0.55, 0.10)
    assert inset.corner is None

    spec = _inset_spec(fig, plot._id)
    assert spec["anchor"] == [0.55, 0.10]
    assert spec["corner"] is None


def test_add_inset_corner_default_has_no_anchor():
    fig, _ = _make_fig()
    inset = fig.add_inset(0.3, 0.3, corner="top-left")
    plot = inset.imshow(np.zeros((16, 16), dtype=np.float32))

    assert inset.anchor is None
    assert inset.corner == "top-left"
    spec = _inset_spec(fig, plot._id)
    assert spec["anchor"] is None
    assert spec["corner"] == "top-left"


def test_anchor_supersedes_corner():
    """Passing both anchor and a corner keeps the anchor and drops the corner."""
    fig, _ = _make_fig()
    inset = fig.add_inset(0.3, 0.3, corner="bottom-right", anchor=(0.2, 0.3))
    inset.imshow(np.zeros((16, 16), dtype=np.float32))
    assert inset.anchor == (0.2, 0.3)
    assert inset.corner is None


def test_anchor_inset_state_transitions_work():
    """minimize / maximize / restore still function for an anchored inset."""
    fig, _ = _make_fig()
    inset = fig.add_inset(0.3, 0.3, anchor=(0.5, 0.5))
    plot = inset.imshow(np.zeros((16, 16), dtype=np.float32))

    inset.minimize()
    assert _inset_spec(fig, plot._id)["inset_state"] == "minimized"
    inset.maximize()
    assert _inset_spec(fig, plot._id)["inset_state"] == "maximized"
    inset.restore()
    assert _inset_spec(fig, plot._id)["inset_state"] == "normal"


def test_anchor_repr():
    fig, _ = _make_fig()
    inset = fig.add_inset(0.3, 0.3, anchor=(0.4, 0.2))
    inset.imshow(np.zeros((16, 16), dtype=np.float32))
    r = repr(inset)
    assert "anchor=(0.4, 0.2)" in r
    assert "corner" not in r


# ── indicate_region / clear_indication ────────────────────────────────────

def test_indicate_region_state():
    fig, ax = _make_fig()
    inset = fig.add_inset(0.3, 0.3, anchor=(0.55, 0.1))
    inset.imshow(np.zeros((16, 16), dtype=np.float32))

    inset.indicate_region(ax._plot, (10, 12, 20, 24),
                          color="#00ff00", linestyle="dashed", linewidth=2.0)

    layout = json.loads(fig.layout_json)
    assert "indications" in layout
    assert len(layout["indications"]) == 1
    ind = layout["indications"][0]
    assert ind["inset_id"] == inset._plot._id
    assert ind["parent_id"] == ax._plot._id
    assert ind["region"] == [10.0, 12.0, 20.0, 24.0]
    assert ind["color"] == "#00ff00"
    assert ind["linestyle"] == "dashed"
    assert ind["linewidth"] == 2.0
    # property mirror
    assert inset.indication["region"] == [10.0, 12.0, 20.0, 24.0]


def test_indicate_region_defaults():
    fig, ax = _make_fig()
    inset = fig.add_inset(0.3, 0.3, corner="top-right")
    inset.imshow(np.zeros((16, 16), dtype=np.float32))
    inset.indicate_region(ax._plot, (5, 5, 10, 10))
    ind = json.loads(fig.layout_json)["indications"][0]
    assert ind["color"] == "#ff9800"
    assert ind["linestyle"] == "dashed"
    assert ind["linewidth"] == 1.5


def test_indicate_region_replaces_previous():
    """A second indicate_region REPLACES the first for the same inset."""
    fig, ax = _make_fig()
    inset = fig.add_inset(0.3, 0.3, anchor=(0.55, 0.1))
    inset.imshow(np.zeros((16, 16), dtype=np.float32))

    inset.indicate_region(ax._plot, (10, 10, 20, 20))
    inset.indicate_region(ax._plot, (30, 30, 8, 8), color="#123456")

    inds = json.loads(fig.layout_json)["indications"]
    assert len(inds) == 1
    assert inds[0]["region"] == [30.0, 30.0, 8.0, 8.0]
    assert inds[0]["color"] == "#123456"


def test_clear_indication():
    fig, ax = _make_fig()
    inset = fig.add_inset(0.3, 0.3, anchor=(0.55, 0.1))
    inset.imshow(np.zeros((16, 16), dtype=np.float32))
    inset.indicate_region(ax._plot, (10, 10, 20, 20))
    assert len(json.loads(fig.layout_json)["indications"]) == 1

    inset.clear_indication()
    assert json.loads(fig.layout_json)["indications"] == []
    assert inset.indication is None
    # idempotent
    inset.clear_indication()
    assert json.loads(fig.layout_json)["indications"] == []


def test_indicate_region_bad_parent_raises():
    fig, _ = _make_fig()
    inset = fig.add_inset(0.3, 0.3, anchor=(0.5, 0.1))
    inset.imshow(np.zeros((16, 16), dtype=np.float32))

    class _NoId:
        pass

    with pytest.raises(ValueError, match="panel id"):
        inset.indicate_region(_NoId(), (0, 0, 1, 1))


def test_indicate_region_foreign_figure_parent_raises():
    """A parent_plot registered on a DIFFERENT Figure must be rejected — it
    has a real panel id (so it passes the earlier no-id check) but isn't one
    of this inset's own figure's panels."""
    fig, ax = _make_fig()
    inset = fig.add_inset(0.3, 0.3, anchor=(0.5, 0.1))
    inset.imshow(np.zeros((16, 16), dtype=np.float32))

    other_fig, other_ax = _make_fig()  # a second, unrelated figure

    with pytest.raises(ValueError, match="not registered"):
        inset.indicate_region(other_ax._plot, (0, 0, 1, 1))
    # And the inset's own indication is untouched by the rejected call.
    assert inset.indication is None


def test_indicate_region_foreign_inset_parent_raises():
    """Same check, but the foreign parent is itself an inset (on the other
    figure) rather than a grid panel — _plots_map covers both."""
    fig, ax = _make_fig()
    inset = fig.add_inset(0.3, 0.3, anchor=(0.5, 0.1))
    inset.imshow(np.zeros((16, 16), dtype=np.float32))

    other_fig, _ = _make_fig()
    other_inset = other_fig.add_inset(0.2, 0.2, anchor=(0.1, 0.1))
    other_plot = other_inset.imshow(np.zeros((8, 8), dtype=np.float32))

    with pytest.raises(ValueError, match="not registered"):
        inset.indicate_region(other_plot, (0, 0, 1, 1))


@pytest.mark.parametrize("region", [
    (0, 0, 0, 10),        # w == 0
    (0, 0, 10, 0),        # h == 0
    (0, 0, -5, 10),       # w < 0
    (0, 0, 10, -5),       # h < 0
    (float("nan"), 0, 10, 10),
    (0, float("nan"), 10, 10),
    (0, 0, float("nan"), 10),
    (0, 0, 10, float("nan")),
    (0, 0, float("inf"), 10),
    (0, 0, 10, 10, 99),   # wrong length (too many)
    (0, 0, 10),           # wrong length (too few)
])
def test_indicate_region_degenerate_region_raises(region):
    fig, ax = _make_fig()
    inset = fig.add_inset(0.3, 0.3, anchor=(0.5, 0.1))
    inset.imshow(np.zeros((16, 16), dtype=np.float32))

    with pytest.raises(ValueError):
        inset.indicate_region(ax._plot, region)


def test_indicate_region_out_of_bounds_is_allowed():
    """A region that extends outside the parent's data bounds is allowed BY
    DESIGN (clipping is a visual concern, not a validation error) — only
    degenerate/non-finite values are rejected."""
    fig, ax = _make_fig()   # parent image is 64x64
    inset = fig.add_inset(0.3, 0.3, anchor=(0.5, 0.1))
    inset.imshow(np.zeros((16, 16), dtype=np.float32))

    # Region far outside the 64x64 parent image bounds — must NOT raise.
    inset.indicate_region(ax._plot, (1000, 1000, 50, 50))
    assert inset.indication is not None
    assert inset.indication["region"] == [1000.0, 1000.0, 50.0, 50.0]


def test_two_insets_two_indications():
    fig, ax = _make_fig()
    i1 = fig.add_inset(0.25, 0.25, anchor=(0.6, 0.05))
    i1.imshow(np.zeros((16, 16), dtype=np.float32))
    i2 = fig.add_inset(0.25, 0.25, anchor=(0.6, 0.6))
    i2.imshow(np.zeros((16, 16), dtype=np.float32))
    i1.indicate_region(ax._plot, (5, 5, 10, 10))
    i2.indicate_region(ax._plot, (40, 40, 10, 10))

    inds = json.loads(fig.layout_json)["indications"]
    assert len(inds) == 2
    ids = {ind["inset_id"] for ind in inds}
    assert ids == {i1._plot._id, i2._plot._id}


# ── indicate_point ─────────────────────────────────────────────────────────

def test_indicate_point_state():
    fig, ax = _make_fig()
    inset = fig.add_inset(0.3, 0.3, anchor=(0.55, 0.1))
    inset.imshow(np.zeros((16, 16), dtype=np.float32))

    inset.indicate_point(ax._plot, (20, 30), color="#00ff00",
                         linestyle="solid", linewidth=2.0, marker_size=7.0)

    ind = json.loads(fig.layout_json)["indications"][0]
    assert ind["inset_id"] == inset._plot._id
    assert ind["parent_id"] == ax._plot._id
    assert ind["point"] == [20.0, 30.0]
    assert "region" not in ind
    assert ind["color"] == "#00ff00"
    assert ind["linestyle"] == "solid"
    assert ind["linewidth"] == 2.0
    assert ind["marker_size"] == 7.0
    assert inset.indication["point"] == [20.0, 30.0]


def test_indicate_point_defaults():
    fig, ax = _make_fig()
    inset = fig.add_inset(0.3, 0.3, corner="top-right")
    inset.imshow(np.zeros((16, 16), dtype=np.float32))
    inset.indicate_point(ax._plot, (5, 5))
    ind = json.loads(fig.layout_json)["indications"][0]
    assert ind["color"] == "#ff9800"
    assert ind["linestyle"] == "dashed"
    assert ind["linewidth"] == 1.5
    assert ind["marker_size"] == 5.0


def test_indicate_point_replaces_region_and_vice_versa():
    """point and region share the one _indication slot — each replaces the
    other (an inset carries at most one indication)."""
    fig, ax = _make_fig()
    inset = fig.add_inset(0.3, 0.3, anchor=(0.55, 0.1))
    inset.imshow(np.zeros((16, 16), dtype=np.float32))

    inset.indicate_region(ax._plot, (10, 10, 20, 20))
    inset.indicate_point(ax._plot, (40, 40))
    inds = json.loads(fig.layout_json)["indications"]
    assert len(inds) == 1
    assert inds[0]["point"] == [40.0, 40.0] and "region" not in inds[0]

    inset.indicate_region(ax._plot, (1, 2, 3, 4))
    inds = json.loads(fig.layout_json)["indications"]
    assert len(inds) == 1
    assert inds[0]["region"] == [1.0, 2.0, 3.0, 4.0] and "point" not in inds[0]


def test_clear_indication_clears_point():
    fig, ax = _make_fig()
    inset = fig.add_inset(0.3, 0.3, anchor=(0.55, 0.1))
    inset.imshow(np.zeros((16, 16), dtype=np.float32))
    inset.indicate_point(ax._plot, (10, 10))
    inset.clear_indication()
    assert json.loads(fig.layout_json)["indications"] == []
    assert inset.indication is None


def test_indicate_point_bad_parent_raises():
    fig, _ = _make_fig()
    inset = fig.add_inset(0.3, 0.3, anchor=(0.5, 0.1))
    inset.imshow(np.zeros((16, 16), dtype=np.float32))

    class _NoId:
        pass

    with pytest.raises(ValueError, match="panel id"):
        inset.indicate_point(_NoId(), (0, 0))


def test_indicate_point_foreign_figure_parent_raises():
    fig, ax = _make_fig()
    inset = fig.add_inset(0.3, 0.3, anchor=(0.5, 0.1))
    inset.imshow(np.zeros((16, 16), dtype=np.float32))
    other_fig, other_ax = _make_fig()
    with pytest.raises(ValueError, match="not registered"):
        inset.indicate_point(other_ax._plot, (0, 0))
    assert inset.indication is None


@pytest.mark.parametrize("point", [
    (float("nan"), 0),
    (0, float("nan")),
    (float("inf"), 0),
    (0, 1, 2),            # wrong length (too many)
    (0,),                 # wrong length (too few)
    "nope",
])
def test_indicate_point_degenerate_point_raises(point):
    fig, ax = _make_fig()
    inset = fig.add_inset(0.3, 0.3, anchor=(0.5, 0.1))
    inset.imshow(np.zeros((16, 16), dtype=np.float32))
    with pytest.raises(ValueError):
        inset.indicate_point(ax._plot, point)


@pytest.mark.parametrize("ms", [0, -1, float("nan"), float("inf")])
def test_indicate_point_bad_marker_size_raises(ms):
    fig, ax = _make_fig()
    inset = fig.add_inset(0.3, 0.3, anchor=(0.5, 0.1))
    inset.imshow(np.zeros((16, 16), dtype=np.float32))
    with pytest.raises(ValueError, match="marker_size"):
        inset.indicate_point(ax._plot, (5, 5), marker_size=ms)


def test_indicate_point_out_of_bounds_is_allowed():
    """Same policy as indicate_region: outside the parent's data bounds is a
    visual-clipping concern, not a validation error."""
    fig, ax = _make_fig()   # parent image is 64x64
    inset = fig.add_inset(0.3, 0.3, anchor=(0.5, 0.1))
    inset.imshow(np.zeros((16, 16), dtype=np.float32))
    inset.indicate_point(ax._plot, (1000, 1000))
    assert inset.indication["point"] == [1000.0, 1000.0]


# ── figure_state / save_html round-trip ───────────────────────────────────

def test_indication_survives_figure_state_roundtrip():
    """The indication lives in layout_json (a synced trait) so figure_state()
    — the exact state mount()/save_html feed the renderer — carries it."""
    fig, ax = _make_fig()
    inset = fig.add_inset(0.3, 0.25, anchor=(0.55, 0.1))
    inset.imshow(np.zeros((16, 16), dtype=np.float32))
    inset.indicate_region(ax._plot, (10, 10, 20, 20), color="#abcdef")

    state = figure_state(fig)
    layout = json.loads(state["layout_json"])
    assert layout["indications"][0]["color"] == "#abcdef"
    # anchor placement also survives
    assert layout["inset_specs"][0]["anchor"] == [0.55, 0.1]


def test_save_html_contains_indication():
    fig, ax = _make_fig()
    inset = fig.add_inset(0.3, 0.25, anchor=(0.55, 0.1))
    inset.imshow(np.zeros((16, 16), dtype=np.float32))
    inset.indicate_region(ax._plot, (10, 10, 20, 20), color="#abcdef")

    html = fig.to_html()
    assert "indications" in html
    assert "#abcdef" in html


# ═══════════════════════════════════════════════════════════════════════════
# Playwright tests — public mount() handle
# ═══════════════════════════════════════════════════════════════════════════

_MOUNT_PAGE = """<!DOCTYPE html>
<html><head><meta charset="utf-8"/>
<style>html,body{margin:0;padding:0;}</style></head>
<body><div id="host"></div>
<script type="module">
const STATE = __STATE__;
const esmSource = __ESM__;
const blobUrl = URL.createObjectURL(new Blob([esmSource], {type: "text/javascript"}));
import(blobUrl).then(mod => {
  window._handle = mod.mount(document.getElementById("host"), STATE, {});
  window._aplReady = true;
}).catch(err => { document.body.textContent = "mount error: " + err; });
</script></body></html>
"""


@pytest.fixture
def mount_page(_pw_browser):
    """Open a figure via the public mount() API; return the live Page."""
    pages, paths = [], []

    def _open(fig):
        html = (_MOUNT_PAGE
                .replace("__STATE__", json.dumps(figure_state(fig)))
                .replace("__ESM__", json.dumps(esm_path().read_text(encoding="utf-8"))))
        with tempfile.NamedTemporaryFile(
            suffix=".html", mode="w", encoding="utf-8", delete=False
        ) as fh:
            fh.write(html)
            tmp = pathlib.Path(fh.name)
        paths.append(tmp)
        page = _pw_browser.new_page()
        pages.append(page)
        page.goto(tmp.as_uri())
        page.wait_for_function("() => window._aplReady === true", timeout=15_000)
        # Three rAFs: layout settle + the deferred first callout draw.
        page.evaluate(
            "() => new Promise(r => requestAnimationFrame(() => "
            "requestAnimationFrame(() => requestAnimationFrame(r))))"
        )
        return page

    yield _open
    for p in pages:
        try:
            p.close()
        except Exception:
            pass
    for f in paths:
        f.unlink(missing_ok=True)


# JS helpers evaluated in-page ------------------------------------------------

# Bounding box (in callout-canvas CSS px) of pixels whose colour matches `rgb`
# within a per-channel tolerance. Returns null when no such pixel exists.
_COLOR_BBOX_JS = """
([rgb, tol]) => {
  const cv = window._handle.api.calloutCanvas;
  const dpr = window.devicePixelRatio || 1;
  const ctx = cv.getContext('2d');
  const img = ctx.getImageData(0, 0, cv.width, cv.height);
  const d = img.data, W = cv.width, H = cv.height;
  let minX=1e9,minY=1e9,maxX=-1,maxY=-1,count=0;
  for (let y=0;y<H;y++) for (let x=0;x<W;x++){
    const i=(y*W+x)*4;
    if (d[i+3] < 40) continue;                 // ~transparent
    if (Math.abs(d[i]-rgb[0])<=tol && Math.abs(d[i+1]-rgb[1])<=tol
        && Math.abs(d[i+2]-rgb[2])<=tol){
      count++;
      if(x<minX)minX=x; if(x>maxX)maxX=x;
      if(y<minY)minY=y; if(y>maxY)maxY=y;
    }
  }
  if(count===0) return null;
  // Return in CSS px (divide by dpr) for stable, resolution-independent asserts.
  return {minX:minX/dpr,minY:minY/dpr,maxX:maxX/dpr,maxY:maxY/dpr,count};
}
"""


def _color_bbox(page, rgb, tol=40):
    return page.evaluate(_COLOR_BBOX_JS, [list(rgb), tol])


def _inset_dom_rect(page, plot_id):
    return page.evaluate(
        """(pid) => {
            const p = window._handle.api.panels.get(pid);
            const r = p.insetDiv.getBoundingClientRect();
            const base = window._handle.api.calloutCanvas.getBoundingClientRect();
            return {left: r.left - base.left, top: r.top - base.top,
                    width: r.width, height: r.height};
        }""",
        plot_id,
    )


def _set_parent_view(page, parent_id, zoom, cx, cy):
    """Set the parent panel's zoom/center in the model and force a redraw."""
    page.evaluate(
        """([pid, zoom, cx, cy]) => {
            const key = 'panel_' + pid + '_json';
            const st = JSON.parse(window._handle.get(key));
            st.zoom = zoom; st.center_x = cx; st.center_y = cy;
            // Mark as a Python-driven view so _preserveView doesn't restore the
            // old (identity) view over the one we're setting.
            st._view_from_python = true;
            window._handle.set(key, JSON.stringify(st));
        }""",
        [parent_id, zoom, cx, cy],
    )
    page.evaluate("() => new Promise(r => requestAnimationFrame("
                  "() => requestAnimationFrame(r)))")


# ── the figure the Playwright tests share ──────────────────────────────────

def _callout_fig(color="#00ff00", region=(8, 8, 24, 24), anchor=(0.55, 0.08)):
    """640×480 image + anchored inset with a bright-colour indication.

    A pure primary colour (#00ff00 lime) is used so the callout ink is trivially
    distinguishable from the grayscale parent image and any theme chrome.
    """
    fig, ax = apl.subplots(1, 1, figsize=(640, 480))
    parent = ax.imshow(np.zeros((64, 64), dtype=np.float32),
                       cmap="gray", vmin=0.0, vmax=1.0)
    inset = fig.add_inset(0.30, 0.30, anchor=anchor, title="Callout")
    inset.imshow(np.zeros((32, 32), dtype=np.float32))
    inset.indicate_region(parent, region, color=color, linewidth=2.5)
    return fig, ax, parent, inset


class TestAnchoredPlacement:
    def test_anchored_inset_dom_position(self, mount_page):
        """The anchored inset's DOM top-left sits at anchor × figure size."""
        fig, ax = apl.subplots(1, 1, figsize=(640, 480))
        ax.imshow(np.zeros((64, 64), dtype=np.float32))
        inset = fig.add_inset(0.30, 0.25, anchor=(0.55, 0.10))
        plot = inset.imshow(np.zeros((16, 16), dtype=np.float32))

        page = mount_page(fig)
        rect = _inset_dom_rect(page, plot._id)
        # anchor (0.55, 0.10) of 640×480 → (352, 48), a few px tolerance.
        assert abs(rect["left"] - 0.55 * 640) <= 3, rect
        assert abs(rect["top"] - 0.10 * 480) <= 3, rect
        # width ≈ 0.30 * 640 = 192
        assert abs(rect["width"] - 0.30 * 640) <= 4, rect


# ── title-bar auto-hide (empty-title insets have no header strip) ──────────

def _inset_page_rect(page, plot_id):
    """Absolute PAGE coordinates of the inset's insetDiv (for page.mouse.*)."""
    return page.evaluate(
        """(pid) => {
            const p = window._handle.api.panels.get(pid);
            const r = p.insetDiv.getBoundingClientRect();
            return {left: r.left, top: r.top, width: r.width, height: r.height};
        }""",
        plot_id,
    )


def _title_bar_info(page, plot_id):
    """Return {display, height, insetH, contentH} for the given inset's DOM."""
    return page.evaluate(
        """(pid) => {
            const p = window._handle.api.panels.get(pid);
            const tb = p.titleBar;
            const cs = getComputedStyle(tb);
            return {
                display: cs.display,
                tbHeight: tb.getBoundingClientRect().height,
                insetHeight: p.insetDiv.getBoundingClientRect().height,
                contentHeight: p.contentDiv.getBoundingClientRect().height,
            };
        }""",
        plot_id,
    )


class TestInsetTitleBarAutoHide:
    """An inset with no title (default) renders with NO title-bar strip at
    all — a clean bordered plot box, content filling the whole area.  A
    titled inset keeps its bar (and click-to-minimize on it)."""

    def test_default_title_has_no_bar(self, mount_page):
        """title omitted (default "") → title bar is display:none and the
        inset's total height equals just the content height (no header gap)."""
        fig, ax = apl.subplots(1, 1, figsize=(640, 480))
        ax.imshow(np.zeros((64, 64), dtype=np.float32))
        inset = fig.add_inset(0.30, 0.25, anchor=(0.1, 0.1))  # no title=
        plot = inset.imshow(np.zeros((16, 16), dtype=np.float32))

        page = mount_page(fig)
        info = _title_bar_info(page, plot._id)
        assert info["display"] == "none", info
        assert info["tbHeight"] == 0, info
        # No phantom header gap: inset box height == content height, modulo
        # the insetDiv's own 1px top+bottom border (getBoundingClientRect
        # includes the border box).
        assert abs(info["insetHeight"] - info["contentHeight"]) <= 2, info

    def test_empty_string_title_has_no_bar(self, mount_page):
        """Explicit title="" behaves the same as omitting it."""
        fig, ax = apl.subplots(1, 1, figsize=(640, 480))
        ax.imshow(np.zeros((64, 64), dtype=np.float32))
        inset = fig.add_inset(0.30, 0.25, anchor=(0.1, 0.1), title="")
        plot = inset.imshow(np.zeros((16, 16), dtype=np.float32))

        page = mount_page(fig)
        info = _title_bar_info(page, plot._id)
        assert info["display"] == "none", info

    def test_whitespace_title_has_no_bar(self, mount_page):
        """A whitespace-only title counts as empty (trimmed before the check)."""
        fig, ax = apl.subplots(1, 1, figsize=(640, 480))
        ax.imshow(np.zeros((64, 64), dtype=np.float32))
        inset = fig.add_inset(0.30, 0.25, anchor=(0.1, 0.1), title="   ")
        plot = inset.imshow(np.zeros((16, 16), dtype=np.float32))

        page = mount_page(fig)
        info = _title_bar_info(page, plot._id)
        assert info["display"] == "none", info

    def test_titled_inset_keeps_bar(self, mount_page):
        """A non-empty title still renders its title-bar strip as before."""
        fig, ax = apl.subplots(1, 1, figsize=(640, 480))
        ax.imshow(np.zeros((64, 64), dtype=np.float32))
        inset = fig.add_inset(0.30, 0.25, anchor=(0.1, 0.1), title="Zoom")
        plot = inset.imshow(np.zeros((16, 16), dtype=np.float32))

        page = mount_page(fig)
        info = _title_bar_info(page, plot._id)
        assert info["display"] == "flex", info
        assert info["tbHeight"] > 0, info
        # Titled inset box is taller than its content (title strip on top).
        assert info["insetHeight"] > info["contentHeight"], info

    def test_titled_inset_click_still_minimizes(self, mount_page):
        """Clicking the title bar of a TITLED inset still toggles minimize —
        the auto-hide change must not break the existing affordance.

        The click handler (a) optimistically collapses contentDiv locally via
        _applyAllInsetStates and (b) emits inset_state_change on event_json —
        there is no live Python bridge in this harness to push an updated
        layout_json back, so assert on those two directly-observable effects
        rather than layout_json (which only a real host round-trip updates).
        """
        fig, ax = apl.subplots(1, 1, figsize=(640, 480))
        ax.imshow(np.zeros((64, 64), dtype=np.float32))
        inset = fig.add_inset(0.30, 0.25, anchor=(0.1, 0.1), title="Zoom")
        plot = inset.imshow(np.zeros((16, 16), dtype=np.float32))

        page = mount_page(fig)
        rect = _inset_page_rect(page, plot._id)
        page.mouse.click(rect["left"] + rect["width"] / 2, rect["top"] + 5)
        page.wait_for_timeout(80)

        content_display = page.evaluate(
            """(pid) => window._handle.api.panels.get(pid).contentDiv.style.display""",
            plot._id,
        )
        assert content_display == "none", content_display

        # event_json is a synced trait; read it directly since this harness
        # has no onEvent callback wired.
        last_event = page.evaluate(
            "() => { try { return JSON.parse(window._handle.get('event_json')); } "
            "catch(_) { return null; } }"
        )
        assert last_event is not None
        assert last_event["event_type"] == "inset_state_change"
        assert last_event["new_state"] == "minimized"

    def test_titleless_inset_body_drag_still_moves_it(self, mount_page):
        """No title bar → no minimize affordance, but drag-to-move (edit mode)
        still works because the drag pointerdown listens on insetDiv itself,
        not the title bar. Real mouse drag on the content area must emit
        inset_geometry_change with a shifted anchor."""
        fig, ax = apl.subplots(1, 1, figsize=(640, 480))
        ax.imshow(np.zeros((64, 64), dtype=np.float32))
        inset = fig.add_inset(0.25, 0.22, anchor=(0.1, 0.1))  # title-less
        plot = inset.imshow(np.zeros((16, 16), dtype=np.float32))

        page = mount_page(fig)
        page.evaluate("() => { window._handle.set('edit_chrome', true); }")
        page.wait_for_timeout(60)

        rect = _inset_page_rect(page, plot._id)
        cx = rect["left"] + rect["width"] / 2
        cy = rect["top"] + rect["height"] / 2

        page.mouse.move(cx, cy)
        page.mouse.down()
        page.mouse.move(cx + 40, cy + 25, steps=10)
        page.mouse.up()
        page.wait_for_timeout(120)

        # Read the authoritative anchor back off the model (the mount() bridge
        # writes inset_geometry_change to event_json; simplest robust check is
        # that the DOM actually moved to the new position).
        new_rect = _inset_page_rect(page, plot._id)
        assert abs(new_rect["left"] - rect["left"]) > 15 or \
            abs(new_rect["top"] - rect["top"]) > 15, (
            f"title-less inset body drag did not move it: before={rect} after={new_rect}"
        )


class TestCalloutRendering:
    def test_dashed_rect_and_leaders_present(self, mount_page):
        """The callout canvas paints lime ink spanning FROM the parent region
        (top-left of figure) TO the inset (right side) — i.e. rect + leaders."""
        fig, ax, parent, inset = _callout_fig(color="#00ff00",
                                              region=(8, 8, 24, 24),
                                              anchor=(0.55, 0.08))
        page = mount_page(fig)

        bbox = _color_bbox(page, (0, 255, 0))
        assert bbox is not None, "no lime callout pixels found"
        assert bbox["count"] > 30, f"too little callout ink: {bbox}"

        # Rect lives in the parent image (left ~half); the inset is anchored at
        # x=0.55 → the leaders extend the lime ink rightward to the inset's near
        # (left) edge at ≈0.55×640=352. So the ink reaches close to that edge.
        assert bbox["minX"] < 0.5 * 640, f"rect not on the left: {bbox}"
        inset_left = 0.55 * 640
        assert bbox["maxX"] >= inset_left - 6, (
            f"leaders don't reach the inset (left≈{inset_left}): {bbox}"
        )
        # And the horizontal span is wide (rect + leaders), not just a small rect.
        assert (bbox["maxX"] - bbox["minX"]) > 120, f"span too narrow: {bbox}"

    def test_rect_at_expected_parent_location(self, mount_page):
        """A small region near the parent's top-left maps to lime ink near the
        parent image's top-left (no zoom: image fills the panel)."""
        # region (4,4,12,12) on a 64px image, panel ~ full width.
        fig, ax, parent, inset = _callout_fig(color="#00ff00",
                                              region=(4, 4, 12, 12),
                                              anchor=(0.6, 0.5))
        page = mount_page(fig)
        bbox = _color_bbox(page, (0, 255, 0))
        assert bbox is not None
        # The rect's own top-left corner should be well within the top-left
        # quadrant of the figure (region 4/64 ≈ 6% into a ~full-panel image).
        assert bbox["minX"] < 0.25 * 640, bbox
        assert bbox["minY"] < 0.30 * 480, bbox

    def test_minimize_hides_leaders(self, mount_page):
        """Minimizing the inset drops the leader ink but keeps the rect."""
        fig, ax, parent, inset = _callout_fig(color="#00ff00",
                                              region=(8, 8, 24, 24),
                                              anchor=(0.55, 0.08))
        page = mount_page(fig)

        full = _color_bbox(page, (0, 255, 0))
        assert full is not None

        # Minimize the inset by updating layout_json's inset_state (this is what
        # the Python side does on a title-bar click → _push_layout → applyLayout).
        page.evaluate(
            """(pid) => {
                const layout = JSON.parse(window._handle.get('layout_json'));
                for (const s of layout.inset_specs)
                    if (s.id === pid) s.inset_state = 'minimized';
                window._handle.set('layout_json', JSON.stringify(layout));
            }""",
            inset._plot._id,
        )
        page.evaluate("() => new Promise(r => requestAnimationFrame("
                      "() => requestAnimationFrame(() => requestAnimationFrame(r))))")

        mini = _color_bbox(page, (0, 255, 0))
        assert mini is not None, "rect vanished when minimized (should stay)"
        # Leaders reached toward the inset (x≈352); minimized ink stops at the
        # rect's own right edge (well left of the inset).
        assert mini["maxX"] < full["maxX"] - 15, (
            f"leaders still present when minimized: full={full} mini={mini}"
        )

    def test_rect_tracks_parent_zoom(self, mount_page):
        """Zooming the parent moves the dashed rect (it is mapped through the
        parent's data→screen transform every draw)."""
        # Small region near the parent's TOP-LEFT so zooming to the CENTRE of
        # the image pushes the rect up-and-left (or off) — a clear position
        # shift that doesn't depend on clip behaviour.
        fig, ax, parent, inset = _callout_fig(color="#00ff00",
                                              region=(4, 4, 10, 10),
                                              anchor=(0.55, 0.55))
        page = mount_page(fig)

        before = _color_bbox(page, (0, 255, 0))
        assert before is not None
        # Record where the rect's top-left corner sits before zoom.
        before_min = (before["minX"], before["minY"])

        # Zoom 2× centred on the IMAGE centre (0.5, 0.5): the top-left region
        # moves further toward the top-left corner (its data coord is far from
        # the new view centre), so the rect's min corner shifts measurably.
        _set_parent_view(page, parent._id, zoom=2.0, cx=0.5, cy=0.5)
        after = _color_bbox(page, (0, 255, 0))
        assert after is not None, "callout gone after zoom"
        after_min = (after["minX"], after["minY"])

        shift = ((after_min[0] - before_min[0]) ** 2
                 + (after_min[1] - before_min[1]) ** 2) ** 0.5
        assert shift > 15, (
            f"rect did not move on zoom (shift={shift:.1f}px): "
            f"before={before} after={after}"
        )

    def test_empty_overlays_do_not_shadow_panel_content(self, mount_page):
        """A figure with NO indication (and no figure markers) must keep both
        figure-level overlay canvases (callout + figMarker) collapsed to a 0×0
        backing store.

        Regression: those overlays used to size themselves to the FULL figure
        even when empty, making them the largest transparent canvases in the
        DOM — which shadowed the panel content for any consumer/test that
        samples "the largest canvas" (this is exactly what broke the tiled-image
        render tests). The largest canvas must be a panel content canvas, and
        it must have real (non-transparent) pixels.
        """
        fig, ax = apl.subplots(1, 1, figsize=(300, 300))
        ax.imshow(np.tile(np.linspace(0, 1, 64, dtype=np.float32), (64, 1)),
                  cmap="gray", vmin=0.0, vmax=1.0)
        page = mount_page(fig)

        info = page.evaluate(
            """() => {
                const co = window._handle.api.calloutCanvas;
                const fm = window._handle.api.figMarkerCanvas;
                const cs = Array.from(document.querySelectorAll('canvas'))
                    .sort((a, b) => b.width * b.height - a.width * a.height);
                const largest = cs[0];
                const px = largest.getContext('2d').getImageData(
                    (largest.width * 0.5) | 0, (largest.height * 0.5) | 0, 1, 1).data[0];
                return {
                    callout: [co.width, co.height],
                    figMarker: [fm.width, fm.height],
                    largest: [largest.width, largest.height],
                    isOverlay: largest === co || largest === fm,
                    largestPx: px,
                };
            }"""
        )
        assert info["callout"] == [0, 0], (
            f"empty callout canvas not collapsed: {info}")
        assert info["figMarker"] == [0, 0], (
            f"empty figMarker canvas not collapsed: {info}")
        assert not info["isOverlay"], (
            f"an empty overlay is the largest canvas (shadows panels): {info}")
        assert info["largestPx"] > 0, (
            f"largest canvas has no rendered content: {info}")


def _point_callout_fig(color="#00ff00", point=(8, 8), anchor=(0.55, 0.55)):
    """640×480 image + anchored inset with a bright point indication."""
    fig, ax = apl.subplots(1, 1, figsize=(640, 480))
    parent = ax.imshow(np.zeros((64, 64), dtype=np.float32),
                       cmap="gray", vmin=0.0, vmax=1.0)
    inset = fig.add_inset(0.30, 0.30, anchor=anchor, title="Point")
    inset.imshow(np.zeros((32, 32), dtype=np.float32))
    inset.indicate_point(parent, point, color=color, linewidth=2.5,
                         marker_size=6.0)
    return fig, ax, parent, inset


class TestPointCalloutRendering:
    def test_marker_and_leader_present(self, mount_page):
        """Lime ink spans FROM the marked point (top-left of the parent) TO the
        inset (bottom-right) — i.e. marker + leader both drew."""
        fig, ax, parent, inset = _point_callout_fig(point=(8, 8),
                                                    anchor=(0.55, 0.55))
        page = mount_page(fig)

        bbox = _color_bbox(page, (0, 255, 0))
        assert bbox is not None, "no lime point-callout pixels found"
        assert bbox["count"] > 20, f"too little callout ink: {bbox}"
        # Marker sits near the parent's top-left; the leader reaches toward the
        # inset anchored at (0.55, 0.55) → wide diagonal span in BOTH axes.
        assert bbox["minX"] < 0.25 * 640, f"marker not near top-left: {bbox}"
        assert bbox["minY"] < 0.30 * 480, f"marker not near top-left: {bbox}"
        assert bbox["maxX"] >= 0.55 * 640 - 6, (
            f"leader doesn't reach the inset's left edge: {bbox}")
        assert bbox["maxY"] >= 0.55 * 480 - 6, (
            f"leader doesn't reach the inset's top edge: {bbox}")

    def test_minimize_hides_leader_keeps_marker(self, mount_page):
        fig, ax, parent, inset = _point_callout_fig(point=(8, 8),
                                                    anchor=(0.55, 0.55))
        page = mount_page(fig)
        full = _color_bbox(page, (0, 255, 0))
        assert full is not None

        page.evaluate(
            """(pid) => {
                const layout = JSON.parse(window._handle.get('layout_json'));
                for (const s of layout.inset_specs)
                    if (s.id === pid) s.inset_state = 'minimized';
                window._handle.set('layout_json', JSON.stringify(layout));
            }""",
            inset._plot._id,
        )
        page.evaluate("() => new Promise(r => requestAnimationFrame("
                      "() => requestAnimationFrame(() => requestAnimationFrame(r))))")

        mini = _color_bbox(page, (0, 255, 0))
        assert mini is not None, "marker vanished when minimized (should stay)"
        # The leader reached toward the inset; minimized ink is just the small
        # marker, so the ink extent collapses back toward the point.
        assert mini["maxX"] < full["maxX"] - 15, (
            f"leader still present when minimized: full={full} mini={mini}")
        assert (mini["maxX"] - mini["minX"]) < 30, (
            f"minimized ink wider than a marker: {mini}")

    def test_marker_tracks_parent_zoom(self, mount_page):
        """Zooming the parent moves the marker (mapped through the parent's
        data→screen transform every draw)."""
        fig, ax, parent, inset = _point_callout_fig(point=(8, 8),
                                                    anchor=(0.55, 0.55))
        page = mount_page(fig)
        before = _color_bbox(page, (0, 255, 0))
        assert before is not None

        _set_parent_view(page, parent._id, zoom=2.0, cx=0.5, cy=0.5)
        after = _color_bbox(page, (0, 255, 0))
        assert after is not None, "point callout gone after zoom"
        shift = ((after["minX"] - before["minX"]) ** 2
                 + (after["minY"] - before["minY"]) ** 2) ** 0.5
        assert shift > 15, (
            f"marker did not move on zoom (shift={shift:.1f}px): "
            f"before={before} after={after}")

    def test_export_png_includes_point_indication(self, mount_page):
        fig, ax, parent, inset = _point_callout_fig(point=(20, 20),
                                                    anchor=(0.55, 0.1))
        page = mount_page(fig)
        res = page.evaluate(
            "() => window._handle.exportPNG({}).then(r => ({dataUrl:r.dataUrl}))")
        raw = base64.b64decode(res["dataUrl"].split(",", 1)[1])
        arr = decode_png(raw)
        d = np.abs(arr[..., :3].astype(np.int32) - np.array([0, 255, 0]))
        n = int(((d <= 40).all(axis=-1)).sum())
        assert n > 20, f"point indication missing from export ({n} lime px)"


class TestCalloutExport:
    def _decode(self, data_url):
        raw = base64.b64decode(data_url.split(",", 1)[1])
        return decode_png(raw)

    def _closest(self, arr, rgb, tol=40):
        d = np.abs(arr[..., :3].astype(np.int32) - np.asarray(rgb, np.int32))
        return int(((d <= tol).all(axis=-1)).sum())

    def test_export_png_includes_indication(self, mount_page):
        """exportPNG composites the callout: lime ink present WITH an indication
        and absent from an otherwise-identical figure WITHOUT one."""
        fig, ax, parent, inset = _callout_fig(color="#00ff00",
                                              region=(8, 8, 24, 24),
                                              anchor=(0.55, 0.08))
        page = mount_page(fig)
        res = page.evaluate(
            "() => window._handle.exportPNG({}).then(r => ({dataUrl:r.dataUrl}))")
        arr = self._decode(res["dataUrl"])
        n_with = self._closest(arr, (0, 255, 0))
        assert n_with > 50, f"indication missing from export ({n_with} lime px)"

        # Control: same figure minus the indication → little/no lime.
        fig2, ax2 = apl.subplots(1, 1, figsize=(640, 480))
        ax2.imshow(np.zeros((64, 64), dtype=np.float32),
                   cmap="gray", vmin=0.0, vmax=1.0)
        i2 = fig2.add_inset(0.30, 0.30, anchor=(0.55, 0.08))
        i2.imshow(np.zeros((32, 32), dtype=np.float32))
        page2 = mount_page(fig2)
        res2 = page2.evaluate(
            "() => window._handle.exportPNG({}).then(r => ({dataUrl:r.dataUrl}))")
        arr2 = self._decode(res2["dataUrl"])
        n_without = self._closest(arr2, (0, 255, 0))
        assert n_without < n_with // 4, (
            f"control has too much lime: with={n_with} without={n_without}"
        )

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

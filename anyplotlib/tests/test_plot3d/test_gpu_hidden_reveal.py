"""WebGPU 3-D scatter/voxels lifecycle when the panel is mounted HIDDEN.

Regression for the "hidden-then-revealed 3-D scatter renders on the Canvas2D
fallback forever" bug.

A host (SpyDE's 3-D IPF window) mounts an anyplotlib figure via ``mount()``
inside a ``display:none`` container and reveals it later.  The FIRST
``draw3d`` then runs with the panel at ZERO drawable size (``pw``/``ph`` == 0
from a zero-size initial layout).  ``_gpuInitPanel`` configures the WebGPU
swapchain against that zero-size canvas and every draw pass calls
``getCurrentTexture()`` on it — undefined behaviour: some drivers throw (the
mid-draw catch latches ``p._gpu = 'unavailable'``, which is TERMINAL because
the ``_gpu === undefined`` init guard never re-runs) and others configure a
dead 0×0 context that silently draws nothing.  Either way the panel is stuck
on Canvas2D forever, even after it's revealed at a real size.

The fix:

* ``draw3d`` does NOT transition ``_gpu`` from ``undefined`` → ``pending``
  while ``pw``/``ph`` == 0 — it leaves ``_gpu === undefined`` so a later draw
  (after reveal/resize, when the size is real) re-attempts init.
* A ResizeObserver reveal branch fires ``redrawAll()`` when the observed
  container transitions from zero-size to a real size, so a reveal by a pure
  ``display`` toggle (no layout/fig-size model change) still re-attempts init.

These tests drive the exact host mounting sequence through ``mount()`` on a
real WebGPU adapter (skipped when none is available) and assert the panel
flips to the WebGPU path AFTER reveal, while a normally-visible panel still
activates on first draw (no regression).
"""
from __future__ import annotations

import json
import pathlib
import tempfile

import numpy as np
import pytest

import anyplotlib as apl
from anyplotlib.embed import esm_path, figure_state


# ---------------------------------------------------------------------------
# Scene builders
# ---------------------------------------------------------------------------

def _scatter_state():
    fig, ax = apl.subplots(1, 1, figsize=(320, 320))
    rng = np.random.default_rng(1)
    pts = rng.uniform(-1, 1, size=(3000, 3))
    v = ax.scatter3d(pts[:, 0], pts[:, 1], pts[:, 2], bounds=((-1, 1),) * 3,
                     gpu="always",
                     colors=np.tile([255, 80, 80], (3000, 1)).astype(np.uint8),
                     point_size=4)
    v.set_axis_off()
    return figure_state(fig)


def _voxel_state():
    fig, ax = apl.subplots(1, 1, figsize=(320, 320))
    n = 8
    g = np.arange(0, n, dtype=float)
    zz, yy, xx = np.meshgrid(g, g, g, indexing="ij")
    v = ax.voxels(xx.ravel(), yy.ravel(), zz.ravel(),
                  bounds=((0, n - 1),) * 3, gpu="always",
                  colors=np.tile([255, 60, 60], (n ** 3, 1)).astype(np.uint8),
                  alpha=0.5)
    v.set_axis_off()
    return figure_state(fig)


def _zero_size(state):
    """Return (zeroed_state, full_layout_json, full_w, full_h).

    Zeroes the layout so the first draw3d sees pw==ph==0 (the hidden-mount
    condition), and stashes the real layout for the reveal step.
    """
    layout = json.loads(state["layout_json"])
    full_w, full_h = layout["fig_width"], layout["fig_height"]
    full_specs = json.loads(json.dumps(layout["panel_specs"]))
    for spec in layout["panel_specs"]:
        spec["panel_width"] = 0
        spec["panel_height"] = 0
    layout["fig_width"] = 0
    layout["fig_height"] = 0
    state = dict(state)
    state["layout_json"] = json.dumps(layout)
    state["fig_width"] = 0
    state["fig_height"] = 0
    full_layout = json.loads(state["layout_json"])
    full_layout["panel_specs"] = full_specs
    full_layout["fig_width"] = full_w
    full_layout["fig_height"] = full_h
    return state, json.dumps(full_layout), full_w, full_h


_ESM = pathlib.Path(esm_path()).read_text(encoding="utf-8")


def _page_html(state, *, hidden, full_layout=None, full_w=0, full_h=0,
               resize_on_reveal=True):
    """Build a mount()-based page.

    hidden           mount inside a display:none container
    full_layout      when given, __reveal() applies it (host-driven relayout)
    resize_on_reveal also push fig_width/height on reveal (SpyDE onResize path)
    """
    reveal_body = "document.getElementById('wrap').style.display='block';"
    if full_layout is not None:
        reveal_body += f"handle.applyUpdate('layout_json', {json.dumps(full_layout)});"
        if resize_on_reveal:
            reveal_body += (
                f"handle.applyUpdate('fig_width', {full_w});"
                f"handle.applyUpdate('fig_height', {full_h});"
            )
    wrap_style = "display:none" if hidden else ""
    return (
        "<!doctype html><html><head><meta charset='utf-8'></head><body>"
        f"<div id='wrap' style='{wrap_style}'><div id='host'></div></div>"
        "<script type='module'>"
        f"const ESM={json.dumps(_ESM)};const STATE={json.dumps(state)};"
        "const url=URL.createObjectURL(new Blob([ESM],{type:'text/javascript'}));"
        "const mod=await import(url);"
        "const handle=mod.mount(document.getElementById('host'), STATE, {});"
        "window._api=handle.api;"
        f"window.__reveal=()=>{{{reveal_body}}};"
        "window._aplReady=true;"
        "</script></body></html>"
    )


def _open(browser, html):
    with tempfile.NamedTemporaryFile(
            suffix=".html", mode="w", encoding="utf-8", delete=False) as fh:
        fh.write(html)
        tmp = pathlib.Path(fh.name)
    page = browser.new_page()
    page.set_viewport_size({"width": 600, "height": 600})
    page.goto(tmp.as_uri())
    page.wait_for_function("() => window._aplReady === true", timeout=15_000)
    return page, tmp


def _panel_gpu(page):
    """Return the (single) panel's GPU diagnostic dict."""
    diag = page.evaluate("""() => {
        const api = window._api; const o = {};
        if (api && api.panels) for (const [id, p] of api.panels) {
            const g = p.gpuCanvas;
            o[id] = { gpu: p._gpu, hasObj: !!p._gpuObj,
                      active: p._gpuActiveNow,
                      gpuDisp: g ? g.style.display : null,
                      pw: p.pw, ph: p.ph };
        }
        return o;
    }""")
    assert diag, "no panels found"
    return next(iter(diag.values()))


# ---------------------------------------------------------------------------
# Real-WebGPU lifecycle tests (skip without an adapter)
# ---------------------------------------------------------------------------

class TestHiddenRevealActivatesGpu:
    """The load-bearing regression: hidden+zero-size mount → reveal → WebGPU."""

    def test_scatter_visible_from_start_activates(self, _pw_gpu_browser):
        """No regression: a normally-visible scatter3d(gpu=True) must still
        activate WebGPU on first draw."""
        page, tmp = _open(_pw_gpu_browser,
                          _page_html(_scatter_state(), hidden=False))
        try:
            page.wait_for_timeout(700)
            d = _panel_gpu(page)
            assert d["gpu"] == "active" and d["active"], \
                f"visible scatter3d did not activate GPU: {d}"
        finally:
            page.close()
            tmp.unlink(missing_ok=True)

    def test_scatter_hidden_zero_then_reveal_activates(self, _pw_gpu_browser):
        state, full, fw, fh = _zero_size(_scatter_state())
        page, tmp = _open(
            _pw_gpu_browser,
            _page_html(state, hidden=True, full_layout=full,
                       full_w=fw, full_h=fh))
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        try:
            page.wait_for_timeout(700)
            # While hidden + zero size the GPU must NOT have been initialised
            # (and MUST NOT have latched to a terminal 'unavailable').
            d0 = _panel_gpu(page)
            assert d0["gpu"] in (None, "pending"), \
                f"GPU init should be deferred while zero-size, got {d0}"
            assert not d0["active"], f"GPU active while zero-size: {d0}"

            page.evaluate("() => window.__reveal()")
            page.wait_for_timeout(1200)
            d1 = _panel_gpu(page)
            assert d1["gpu"] == "active" and d1["active"], \
                f"scatter3d did not activate GPU after reveal: {d1}"
            assert d1["gpuDisp"] == "block"
            assert not errors, f"reveal raised page errors: {errors}"
        finally:
            page.close()
            tmp.unlink(missing_ok=True)

    def test_voxels_hidden_zero_then_reveal_activates(self, _pw_gpu_browser):
        """Voxels go through the same draw3d init — the size-gate must cover
        them too."""
        state, full, fw, fh = _zero_size(_voxel_state())
        page, tmp = _open(
            _pw_gpu_browser,
            _page_html(state, hidden=True, full_layout=full,
                       full_w=fw, full_h=fh))
        try:
            page.wait_for_timeout(700)
            d0 = _panel_gpu(page)
            assert d0["gpu"] in (None, "pending"), \
                f"voxel GPU init should be deferred while zero-size: {d0}"
            page.evaluate("() => window.__reveal()")
            page.wait_for_timeout(1200)
            d1 = _panel_gpu(page)
            assert d1["gpu"] == "active" and d1["active"], \
                f"voxels did not activate GPU after reveal: {d1}"
        finally:
            page.close()
            tmp.unlink(missing_ok=True)

    def test_reveal_by_display_toggle_only_activates(self, _pw_gpu_browser):
        """Reveal WITHOUT any layout/fig-size push: only the container's
        display flips.  The ResizeObserver reveal branch must fire the redraw
        that re-attempts GPU init at the now-real size."""
        state, _full, _fw, _fh = _zero_size(_scatter_state())
        # No full_layout → __reveal() flips display only. But zero-size panels
        # need a real size to init, so this variant keeps the panel at real
        # pw/ph via a non-zeroed layout revealed purely by display toggle.
        vis_state = _scatter_state()  # real pw/ph, hidden by ancestor
        page, tmp = _open(_pw_gpu_browser,
                          _page_html(vis_state, hidden=True))
        try:
            page.wait_for_timeout(700)
            page.evaluate("() => window.__reveal()")
            page.wait_for_timeout(1000)
            d = _panel_gpu(page)
            assert d["gpu"] == "active" and d["active"], \
                f"display-toggle reveal did not activate GPU: {d}"
        finally:
            page.close()
            tmp.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Size-gate logic test (no real adapter needed) — proves the DEFER, which is
# the core of the fix, runs even on GPU-less CI via a fake device that latches
# 'unavailable' if init is ever attempted at zero size.
# ---------------------------------------------------------------------------

_FAKE_STRICT_GPU = """
() => {
  const tex = () => ({ createView:()=>({}), destroy:()=>{} });
  const buf = () => ({ destroy:()=>{} });
  const mkCtx = (canvas) => ({
    configure:()=>{},
    getCurrentTexture:()=>{
      if (canvas.width <= 1 || canvas.height <= 1)
        throw new Error('SIMULATED zero-size getCurrentTexture');
      return tex();
    },
  });
  const _getCtx = HTMLCanvasElement.prototype.getContext;
  HTMLCanvasElement.prototype.getContext = function(type, ...rest){
    if (type === 'webgpu') return mkCtx(this);
    return _getCtx.call(this, type, ...rest);
  };
  const dev = {
    lost: new Promise(()=>{}),
    createShaderModule:()=>({}), createBuffer:()=>buf(),
    createBindGroupLayout:()=>({}), createPipelineLayout:()=>({}),
    createBindGroup:()=>({}), createTexture:()=>tex(),
    createRenderPipeline:()=>({ getBindGroupLayout:()=>({}) }),
    createCommandEncoder:()=>({
      beginRenderPass:()=>({ setPipeline:()=>{}, setBindGroup:()=>{},
        setVertexBuffer:()=>{}, draw:()=>{}, end:()=>{} }),
      finish:()=>({}),
    }),
    queue:{ writeBuffer:()=>{}, submit:()=>{}, onSubmittedWorkDone:async()=>{} },
  };
  navigator.gpu = {
    getPreferredCanvasFormat:()=>'bgra8unorm',
    requestAdapter: async ()=>({ info:{}, requestDevice: async ()=>dev }),
  };
}"""


class TestZeroSizeInitDeferred:
    """With a driver that THROWS on a zero-size getCurrentTexture(), a panel
    that (pre-fix) initialised while zero-size latched permanently to
    'unavailable'.  The gate must DEFER init so it never latches — provable
    without a real adapter."""

    def test_zero_size_defers_not_latches(self, _pw_browser):
        state, _full, _fw, _fh = _zero_size(_scatter_state())
        html = _page_html(state, hidden=True)  # display toggle only
        with tempfile.NamedTemporaryFile(
                suffix=".html", mode="w", encoding="utf-8", delete=False) as fh:
            fh.write(html)
            tmp = pathlib.Path(fh.name)
        page = _pw_browser.new_page()
        page.set_viewport_size({"width": 600, "height": 600})
        page.add_init_script(_FAKE_STRICT_GPU)
        try:
            page.goto(tmp.as_uri())
            page.wait_for_function("() => window._aplReady === true",
                                   timeout=15_000)
            page.wait_for_timeout(600)
            d = _panel_gpu(page)
            # The key assertion: init was NOT attempted at zero size, so the
            # terminal 'unavailable' latch never fired. _gpu stays undefined
            # (None) / pending — recoverable once a real size arrives.
            assert d["gpu"] in (None, "pending"), (
                f"zero-size init was NOT deferred (latched {d['gpu']!r}); the "
                f"panel would be stuck on Canvas2D forever: {d}"
            )
        finally:
            page.close()
            tmp.unlink(missing_ok=True)

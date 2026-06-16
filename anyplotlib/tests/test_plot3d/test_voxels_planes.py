"""
Tests for the 'voxels' geometry and 3-D PlaneWidget slice selectors.
"""
from __future__ import annotations

import json

import numpy as np
import pytest

import anyplotlib as apl


def _voxels(**kwargs):
    fig, ax = apl.subplots(1, 1, figsize=(320, 320))
    g = np.arange(0, 8, dtype=float)
    zz, yy, xx = np.meshgrid(g, g, g, indexing="ij")
    return ax.voxels(xx.ravel(), yy.ravel(), zz.ravel(),
                     bounds=((0, 7),) * 3, **kwargs)


class TestVoxelsState:
    def test_geom_and_alpha_state(self):
        v = _voxels(size=1.0, alpha=0.2)
        assert v._state["geom_type"] == "voxels"
        assert v._state["voxel_size"] == 1.0
        assert v._state["voxel_alpha"] == 0.2
        assert v._state["voxel_slice_alpha"] == 0.95

    def test_per_voxel_colors_allowed(self):
        colors = np.zeros((512, 3), dtype=np.uint8)
        v = _voxels(colors=colors)
        assert v._state["point_colors_b64"] != ""

    def test_set_point_colors_after_construction(self):
        """The orthoslice explorer re-cuts slab voxels each drag via
        set_data + set_point_colors, so voxels must accept post-hoc
        per-voxel colours (not just at construction)."""
        v = _voxels()
        v.set_point_colors(np.zeros((512, 3), dtype=np.uint8))
        assert v._state["point_colors_b64"] != ""
        v.set_point_colors(None)
        assert v._state["point_colors_b64"] == ""

    def test_set_voxel_alpha(self):
        v = _voxels()
        v.set_voxel_alpha(0.1, slice_alpha=0.8)
        assert v._state["voxel_alpha"] == 0.1
        assert v._state["voxel_slice_alpha"] == 0.8


class TestPlaneWidget:
    def test_add_plane_serialises(self):
        v = _voxels()
        pw = v.add_widget("plane", axis="z", position=4, color="#40c4ff")
        ws = v._state["overlay_widgets"]
        assert len(ws) == 1
        assert ws[0]["type"] == "plane"
        assert ws[0]["axis"] == "z"
        assert ws[0]["position"] == 4.0

    def test_invalid_axis_raises(self):
        v = _voxels()
        with pytest.raises(ValueError, match="axis must be"):
            v.add_widget("plane", axis="w", position=0)

    def test_only_plane_kind(self):
        v = _voxels()
        with pytest.raises(ValueError, match="only 'plane'"):
            v.add_widget("crosshair")

    def test_set_position_from_python(self):
        v = _voxels()
        pw = v.add_widget("plane", axis="x", position=2)
        pw.set(position=5)
        assert pw.position == 5

    def test_remove_widget(self):
        v = _voxels()
        pw = v.add_widget("plane", axis="y", position=3)
        v.remove_widget(pw)
        v._push()
        assert v._state["overlay_widgets"] == []

    def test_js_drag_event_round_trip(self):
        """A JS plane-drag message must update position and fire callbacks."""
        v = _voxels()
        pw = v.add_widget("plane", axis="z", position=4)
        fig = v._fig
        got = []

        @pw.add_event_handler("pointer_move")
        def on_drag(event):
            got.append(pw.position)

        fig._dispatch_event(json.dumps({
            "panel_id": v._id, "widget_id": pw.id,
            "event_type": "pointer_move", "axis": "z", "position": 6.25,
        }))
        assert got == [6.25]
        assert pw.position == 6.25


class TestVoxelRendering:
    def test_voxels_render_with_slice_emphasis(self, interact_page):
        """Voxels render; an on-plane slice draws more saturated ink."""
        colors = np.full((512, 3), [255, 0, 0], dtype=np.uint8)
        v = _voxels(colors=colors, alpha=0.15)
        v.set_axis_off()
        v.add_widget("plane", axis="z", position=3, alpha=0.0)  # invisible plane
        page = interact_page(v._fig)
        page.wait_for_timeout(250)

        res = page.evaluate("""() => {
            const c = [...document.querySelectorAll('canvas')].find(x => x.style.position === 'relative' && x.style.display !== 'none');
            const d = c.getContext('2d').getImageData(0,0,c.width,c.height).data;
            let pale = 0, strong = 0;
            for (let i = 0; i < d.length; i += 4) {
                const r = d[i], g = d[i+1], b = d[i+2];
                if (r > 180 && g < 160 && b < 160) {
                    if (g > 60) pale++; else strong++;   // strong = opaque red
                }
            }
            return { pale, strong };
        }""")
        assert res["pale"] > 500, f"translucent voxel ink missing: {res}"
        assert res["strong"] > 200, f"opaque slice-plane voxels missing: {res}"

    def test_voxel_gpu_canvas_layering(self, interact_page):
        """The 3-D voxel panel stacks a gpuCanvas (z-index 0, WebGPU voxels)
        below the plotCanvas (z-index 1, decorations).  In canvas mode the
        plotCanvas MUST keep an opaque background; the renderer only flips it
        to ``transparent`` while the GPU path is active, so the GPU-drawn
        voxels beneath aren't hidden by an opaque overlay.

        Regression for: large voxel volumes rendering "empty" (only planes +
        highlight visible) in PyCharm's WebGPU-enabled JCEF, because the
        opaque plotCanvas painted over the gpuCanvas.  The active-GPU swap is
        hardware-verified via native wgpu; CI has no adapter, so here we lock
        the DOM stacking + the canvas-mode opaque-background invariant.
        """
        colors = np.full((512, 3), [255, 0, 0], dtype=np.uint8)
        v = _voxels(colors=colors, alpha=0.4)
        v.set_axis_off()
        page = interact_page(v._fig)
        page.wait_for_timeout(200)

        layout = page.evaluate("""() => {
            const cs = [...document.querySelectorAll('canvas')];
            const gpu  = cs.find(x => x.style.zIndex === '0');
            const plot = cs.find(x => x.style.zIndex === '1');
            return {
                hasGpu: !!gpu,
                gpuBelow: !!gpu && !!plot,
                plotBg: plot ? plot.style.background : null,
                gpuDisp: gpu ? gpu.style.display : null,
            };
        }""")
        assert layout["hasGpu"], "3-D voxel panel must create a gpuCanvas"
        assert layout["gpuDisp"] == "none", \
            "gpuCanvas stays hidden in canvas mode (no WebGPU adapter in CI)"
        # Canvas mode: plotCanvas keeps an opaque bg (NOT transparent), so the
        # canvas-drawn voxels read against a solid panel background.
        assert layout["plotBg"] and layout["plotBg"] != "transparent", \
            f"canvas-mode plotCanvas must stay opaque, got {layout['plotBg']!r}"

    def test_plane_drag_in_browser(self, interact_page):
        """Dragging a plane widget must change its position in the model."""
        v = _voxels(alpha=0.1)
        v.set_axis_off()
        pw = v.add_widget("plane", axis="z", position=3, alpha=0.3)
        fig = v._fig
        page = interact_page(fig)
        page.wait_for_timeout(250)

        def js_position():
            return page.evaluate(f"""() => {{
                const st = JSON.parse(window._aplModel.get('panel_{v._id}_json'));
                return st.overlay_widgets[0].position;
            }}""")

        assert abs(js_position() - 3) < 1e-6
        # Locate the plane via its fully-opaque cyan border pixels, then drag
        # from its centroid upward (the z screen-direction at the default view)
        centre = page.evaluate("""() => {
            const c = [...document.querySelectorAll('canvas')].find(x => x.style.position === 'relative' && x.style.display !== 'none');
            const r = c.getBoundingClientRect();
            const d = c.getContext('2d').getImageData(0,0,c.width,c.height).data;
            let sx = 0, sy = 0, n = 0;
            for (let y = 0; y < c.height; y++) for (let x = 0; x < c.width; x++) {
                const i = (y * c.width + x) * 4;
                if (d[i] < 60 && d[i+1] > 200 && d[i+2] > 230) {
                    sx += x; sy += y; n++;
                }
            }
            return n ? { x: r.left + sx / n, y: r.top + sy / n, n } : null;
        }""")
        assert centre is not None, "plane border pixels not found on canvas"
        page.mouse.move(centre["x"], centre["y"])
        page.mouse.down()
        page.mouse.move(centre["x"], centre["y"] - 50, steps=8)
        page.mouse.up()
        page.wait_for_timeout(250)
        moved = js_position()
        assert abs(moved - 3) > 0.5, (
            f"plane did not move on drag (position still {moved})")


class TestPlaneDragNoSnapBack:
    """Regression: a view-only push (set_highlight / set_view) must NOT clobber
    a plane widget's live position — the "snap-back" symptom."""

    def _voxels_with_plane(self):
        fig, ax = apl.subplots(1, 1, figsize=(320, 320))
        g = np.arange(0, 8, dtype=float)
        zz, yy, xx = np.meshgrid(g, g, g, indexing="ij")
        v = ax.voxels(xx.ravel(), yy.ravel(), zz.ravel(), bounds=((0, 7),) * 3)
        pw = v.add_widget("plane", axis="z", position=4)
        return fig, v, pw

    def test_to_state_dict_reflects_live_widget(self):
        fig, v, pw = self._voxels_with_plane()
        pw.set(position=2.7)
        st = v.to_state_dict()
        z = next(w["position"] for w in st["overlay_widgets"]
                 if w["type"] == "plane" and w["axis"] == "z")
        assert z == 2.7, f"to_state_dict serialised a stale plane position: {z}"

    def test_set_highlight_preserves_plane_position(self):
        fig, v, pw = self._voxels_with_plane()
        pw.set(position=2.7)                 # simulate a mid-drag float position
        v.set_highlight(1, 2, 3)             # view-only push on the same panel
        import json
        st = json.loads(getattr(fig, f"panel_{v._id}_json"))
        z = next(w["position"] for w in st["overlay_widgets"]
                 if w["type"] == "plane" and w["axis"] == "z")
        assert z == 2.7, f"set_highlight snapped the plane back to {z} (want 2.7)"

    def test_set_view_preserves_plane_position(self):
        fig, v, pw = self._voxels_with_plane()
        pw.set(position=5.3)
        v.set_view(azimuth=10, elevation=20)
        import json
        st = json.loads(getattr(fig, f"panel_{v._id}_json"))
        z = next(w["position"] for w in st["overlay_widgets"]
                 if w["type"] == "plane" and w["axis"] == "z")
        assert z == 5.3, f"set_view snapped the plane back to {z} (want 5.3)"

"""
tests/test_plot3d/test_patches.py
=================================

Regions and paths on 3-D panels (``Plot3D.add_patch``) — see
``Examples/Interactive/plot_kikuchi_sphere.py``.

Covers:
  * geodesic densification: edges become great-circle arcs about the centre
  * validation: shape, frame, antipodal and centre-sitting points
  * the handle: live ``set`` and ``remove`` through a light push
  * Playwright: a "data" patch turns with set_rotation and a "world" patch
    does not; the part behind the centre is drawn dimmer than the front
"""
from __future__ import annotations

import json

import numpy as np
import pytest

import anyplotlib as apl


def _unit_sphere_panel():
    fig, ax = apl.subplots(1, 1, figsize=(320, 320))
    plot = ax.scatter3d([0.0], [0.0], [0.0], point_size=0.1,
                        bounds=((-1, 1),) * 3, azimuth=0.0, elevation=0.0)
    plot.set_axis_off()
    return fig, plot


def _square(half_angle_deg=20, centre=(0.0, -1.0, 0.0)):
    """Four corners of a square cap facing *centre* on the unit sphere."""
    t = np.tan(np.radians(half_angle_deg))
    c = np.asarray(centre, float)
    # Two directions perpendicular to the centre direction.
    u = np.cross(c, [0, 0, 1]) if abs(c[2]) < 0.9 else np.cross(c, [1, 0, 0])
    u /= np.linalg.norm(u)
    v = np.cross(c, u)
    corners = [c + t * (su * u + sv * v)
               for su, sv in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
    return np.array([p / np.linalg.norm(p) for p in corners])


def _wire(plot):
    return plot._state["patches"]


# ---------------------------------------------------------------------------
# Python API
# ---------------------------------------------------------------------------

class TestGeodesic:
    def test_edges_stay_on_the_sphere(self):
        _, plot = _unit_sphere_panel()
        plot.add_patch(_square(40))
        pts = np.reshape(_wire(plot)[0]["points"], (-1, 3))
        np.testing.assert_allclose(np.linalg.norm(pts, axis=1), 1.0, atol=1e-6)
        assert len(pts) > 4 * 10, "edges were not subdivided"

    def test_steps_are_at_most_two_degrees(self):
        _, plot = _unit_sphere_panel()
        plot.add_patch(_square(40))
        pts = np.reshape(_wire(plot)[0]["points"], (-1, 3))
        closed = np.vstack([pts, pts[:1]])
        cosines = np.einsum("ij,ij->i", closed[:-1], closed[1:])
        assert np.degrees(np.arccos(np.clip(cosines, -1, 1))).max() <= 2.0 + 1e-6

    def test_straight_edges_when_not_geodesic(self):
        _, plot = _unit_sphere_panel()
        plot.add_patch(_square(40), geodesic=False)
        assert len(_wire(plot)[0]["points"]) == 4 * 3

    def test_open_path_keeps_its_last_point(self):
        _, plot = _unit_sphere_panel()
        path = np.array([[1.0, 0, 0], [0, 1.0, 0]])
        plot.add_patch(path, closed=False)
        pts = np.reshape(_wire(plot)[0]["points"], (-1, 3))
        np.testing.assert_allclose(pts[0], path[0])
        np.testing.assert_allclose(pts[-1], path[1])

    def test_antipodal_edge_is_rejected(self):
        _, plot = _unit_sphere_panel()
        with pytest.raises(ValueError, match="opposite"):
            plot.add_patch([[1, 0, 0], [-1, 0, 0], [0, 1, 0]])

    def test_point_at_the_centre_is_rejected(self):
        _, plot = _unit_sphere_panel()
        with pytest.raises(ValueError, match="centre"):
            plot.add_patch([[0, 0, 0], [1, 0, 0], [0, 1, 0]])


class TestHandle:
    def test_defaults_and_validation(self):
        _, plot = _unit_sphere_panel()
        patch = plot.add_patch(_square(), label="detector")
        wire = _wire(plot)[0]
        assert wire["frame"] == "data" and wire["closed"] is True
        assert wire["label"] == "detector" and patch.name == wire["id"]
        with pytest.raises(ValueError):
            plot.add_patch(_square(), frame="screen")
        with pytest.raises(ValueError):
            plot.add_patch(np.zeros((4, 2)))
        with pytest.raises(ValueError):
            plot.add_patch([[1, 0, 0], [0, 1, 0]])          # closed needs 3

    def test_set_and_remove_are_light_pushes(self):
        fig, plot = _unit_sphere_panel()
        patch = plot.add_patch(_square(), name="det")
        patch.set(facecolor="#00ff00", frame="world", points=_square(10))
        light = json.loads(getattr(fig, f"panel_{plot._id}_json"))
        assert "vertices_b64" not in light
        (wire,) = light["patches"]
        assert wire["facecolor"] == "#00ff00" and wire["frame"] == "world"
        assert plot.patches["det"] is patch
        patch.remove()
        assert _wire(plot) == [] and "det" not in plot.patches

    def test_duplicate_name_replaces(self):
        _, plot = _unit_sphere_panel()
        plot.add_patch(_square(), name="det")
        plot.add_patch(_square(10), name="det")
        assert len(_wire(plot)) == 1


# ---------------------------------------------------------------------------
# Rendering (Playwright)
# ---------------------------------------------------------------------------

_GREEN = """() => {
    const c = [...document.querySelectorAll('canvas')].find(
        x => x.style.position === 'relative' && x.style.display !== 'none');
    const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
    let sx = 0, sy = 0, n = 0, peak = 0;
    for (let y = 0; y < c.height; y++) for (let x = 0; x < c.width; x++) {
        const i = (y * c.width + x) * 4;
        const g = d[i+1] - Math.max(d[i], d[i+2]);
        if (g > 25) { sx += x; sy += y; n++; peak = Math.max(peak, g); }
    }
    return n ? { x: sx / n / c.width, y: sy / n / c.height, n, peak } : null;
}"""


def _rotation_about_z(degrees):
    a = np.radians(degrees)
    return np.array([[np.cos(a), -np.sin(a), 0], [np.sin(a), np.cos(a), 0],
                     [0, 0, 1]])


class TestRendering:
    @pytest.mark.parametrize("frame, moves", [("data", True), ("world", False)])
    def test_frame_decides_whether_the_patch_turns(self, interact_page,
                                                   frame, moves):
        """A cap facing the camera, then the model turned 60° about z: a
        "data" patch swings off to the side, a "world" patch stays put."""
        _, still = _unit_sphere_panel()
        still.add_patch(_square(15), frame=frame, facecolor="#00ff00",
                        edgecolor="#00ff00", alpha=0.6)
        before = interact_page(still._fig).evaluate(_GREEN)

        _, turned = _unit_sphere_panel()
        turned.add_patch(_square(15), frame=frame, facecolor="#00ff00",
                         edgecolor="#00ff00", alpha=0.6)
        turned.set_rotation(_rotation_about_z(60))
        after = interact_page(turned._fig).evaluate(_GREEN)

        assert abs(before["x"] - 0.5) < 0.03, before
        if moves:
            assert after["x"] > 0.6, after
        else:
            assert abs(after["x"] - before["x"]) < 0.01, (before, after)

    def test_far_side_is_dimmer(self, interact_page):
        _, front = _unit_sphere_panel()
        front.add_patch(_square(15), facecolor="#00ff00", edgecolor="#00ff00",
                        alpha=0.6)
        _, back = _unit_sphere_panel()
        back.add_patch(_square(15, centre=(0, 1, 0)), facecolor="#00ff00",
                       edgecolor="#00ff00", alpha=0.6)
        near = interact_page(front._fig).evaluate(_GREEN)
        far = interact_page(back._fig).evaluate(_GREEN)
        assert far is not None, "the far-side patch was not drawn at all"
        assert far["peak"] < 0.7 * near["peak"], (near, far)

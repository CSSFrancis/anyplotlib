"""
tests/test_plot3d/test_model_rotation.py
========================================

Model rotation on 3-D panels (``Plot3D.set_rotation`` / ``set_drag_mode``) —
see ``Examples/Interactive/plot_kikuchi_sphere.py``.

Covers:
  * validation: shape, orthonormality, and reflections are rejected
  * the push is targeted (no geometry) and flagged so it never moves the camera
  * a viewer's "rotate" drag reaches ``Plot3D.rotation`` and ``Event.rotation``
  * Playwright: the rotation turns the drawing, and a drag edits the rotation
    while leaving the camera where it was
"""
from __future__ import annotations

import json

import numpy as np
import pytest

import anyplotlib as apl
from anyplotlib.tests.test_interactive._event_test_utils import (
    _collect_events, _get_events,
)


def _rotation_about(axis, degrees):
    """Right-handed rotation by *degrees* about unit *axis* (Rodrigues)."""
    k = np.asarray(axis, float) / np.linalg.norm(axis)
    K = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
    a = np.radians(degrees)
    return np.eye(3) + np.sin(a) * K + (1 - np.cos(a)) * K @ K


def _one_point(**kwargs):
    """A single red point on the +x axis of an origin-centred unit box."""
    fig, ax = apl.subplots(1, 1, figsize=(320, 320))
    plot = ax.scatter3d([1.0], [0.0], [0.0], colors=["#ff0000"], point_size=10,
                        bounds=((-1, 1),) * 3, azimuth=0.0, elevation=0.0,
                        **kwargs)
    plot.set_axis_off()
    return fig, plot


def _dispatch(fig, plot, event_type, **fields):
    payload = {"source": "js", "panel_id": plot._id, "event_type": event_type}
    payload.update(fields)
    fig._dispatch_event(json.dumps(payload))


# ---------------------------------------------------------------------------
# Python API
# ---------------------------------------------------------------------------

class TestSetRotation:
    def test_default_is_identity(self):
        _, plot = _one_point()
        np.testing.assert_array_equal(plot.rotation, np.eye(3))
        assert plot._state["drag_mode"] == "orbit"

    def test_round_trips(self):
        _, plot = _one_point()
        R = _rotation_about([1, 2, 3], 40)
        plot.set_rotation(R)
        np.testing.assert_allclose(plot.rotation, R)

    def test_none_restores_identity(self):
        _, plot = _one_point()
        plot.set_rotation(_rotation_about([0, 0, 1], 30))
        plot.set_rotation(None)
        np.testing.assert_array_equal(plot.rotation, np.eye(3))

    @pytest.mark.parametrize("bad", [
        np.eye(2),                         # wrong shape
        2 * np.eye(3),                     # scales
        [[1, 0.2, 0], [0, 1, 0], [0, 0, 1]],   # shears
        np.diag([1.0, 1.0, -1.0]),         # reflection
        np.full((3, 3), np.nan),
    ])
    def test_rejects_anything_but_a_proper_rotation(self, bad):
        _, plot = _one_point()
        with pytest.raises(ValueError):
            plot.set_rotation(bad)

    def test_push_carries_no_geometry_and_leaves_the_camera(self):
        fig, plot = _one_point()
        plot.set_rotation(_rotation_about([0, 1, 0], 90))
        light = json.loads(getattr(fig, f"panel_{plot._id}_json"))
        assert "vertices_b64" not in light
        assert light["_rotation_from_python"] is True
        assert light["_view_from_python"] is False
        # The flags must not persist past the push they belong to.
        assert plot._state["_rotation_from_python"] is False

    def test_drag_mode_validation(self):
        _, plot = _one_point()
        plot.set_drag_mode("rotate")
        assert plot._state["drag_mode"] == "rotate"
        with pytest.raises(ValueError):
            plot.set_drag_mode("spin")


class TestRotationFromViewer:
    def test_drag_updates_rotation_and_event(self):
        fig, plot = _one_point()
        seen = []
        plot.add_event_handler("pointer_up")(lambda e: seen.append(e.rotation))
        R = _rotation_about([1, 0, 0], 25)
        _dispatch(fig, plot, "pointer_up", rotation=list(R.ravel()))
        np.testing.assert_allclose(plot.rotation, R)
        np.testing.assert_allclose(np.reshape(seen[0], (3, 3)), R)

    def test_export_keeps_the_viewers_rotation(self):
        fig, plot = _one_point()
        R = _rotation_about([0, 0, 1], 60)
        live = json.loads(getattr(fig, f"panel_{plot._id}_json"))
        live["rotation"] = list(R.ravel())
        setattr(fig, f"panel_{plot._id}_json", json.dumps(live))
        fig._reconcile_js_view_state()
        np.testing.assert_allclose(plot.rotation, R)


# ---------------------------------------------------------------------------
# Rendering + interaction (Playwright)
# ---------------------------------------------------------------------------

_RED_CENTROID = """() => {
    const c = [...document.querySelectorAll('canvas')].find(
        x => x.style.position === 'relative' && x.style.display !== 'none');
    const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
    let sx = 0, sy = 0, n = 0;
    for (let y = 0; y < c.height; y++) for (let x = 0; x < c.width; x++) {
        const i = (y * c.width + x) * 4;
        if (d[i] > 200 && d[i+1] < 60 && d[i+2] < 60) { sx += x; sy += y; n++; }
    }
    return n ? { x: sx / n / c.width, y: sy / n / c.height } : null;
}"""


class TestRendering:
    def test_rotation_moves_the_point(self, interact_page):
        """At azimuth 0, elevation 0 the camera shows +x to the right and +z
        up; turning +x onto +z must carry the point from the right to the top."""
        _, before = _one_point()
        right = interact_page(before._fig).evaluate(_RED_CENTROID)

        _, after = _one_point()
        after.set_rotation(_rotation_about([0, 1, 0], -90))   # x → z
        top = interact_page(after._fig).evaluate(_RED_CENTROID)

        assert right["x"] > 0.6 and abs(right["y"] - 0.5) < 0.1, right
        assert top["y"] < 0.4 and abs(top["x"] - 0.5) < 0.1, top

    def test_point_turned_toward_the_camera_lands_dead_centre(self, interact_page):
        """At elevation 0 the camera faces −y.  This also pins elevation 0
        itself: it was read with ``|| 30`` and so drawn from 30° up."""
        _, plot = _one_point()
        plot.set_rotation(_rotation_about([0, 0, 1], -90))   # x → −y
        centre = interact_page(plot._fig).evaluate(_RED_CENTROID)
        assert abs(centre["x"] - 0.5) < 0.03 and abs(centre["y"] - 0.5) < 0.03, centre

    def test_rotate_drag_turns_the_model_not_the_camera(self, interact_page):
        fig, plot = _one_point()
        plot.set_drag_mode("rotate")
        page = interact_page(fig)
        _collect_events(page)

        box = page.evaluate("""() => {
            const c = [...document.querySelectorAll('canvas')].find(
                x => x.style.position === 'relative' && x.style.display !== 'none');
            const r = c.getBoundingClientRect();
            return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
        }""")
        page.mouse.move(box["x"], box["y"])
        page.mouse.down()
        page.mouse.move(box["x"], box["y"] - 60, steps=10)   # drag up
        page.mouse.up()

        state = page.evaluate(
            f"() => JSON.parse(window._aplModel.get('panel_{plot._id}_json'))")
        assert state["azimuth"] == 0 and state["elevation"] == 0
        R = np.reshape(state["rotation"], (3, 3))
        np.testing.assert_allclose(R @ R.T, np.eye(3), atol=1e-9)
        assert np.linalg.det(R) == pytest.approx(1.0)
        # Dragging up rolls the front of the sphere upward: about the screen's
        # x axis, which is the data's x axis at this camera — so +x stays put
        # and the point does not move, while -y (the side facing the camera)
        # comes up and +y goes down.
        np.testing.assert_allclose(R[:, 0], [1, 0, 0], atol=1e-9)
        assert R[2, 1] < -0.3

        ups = _get_events(page, "pointer_up")
        assert ups and len(ups[-1]["rotation"]) == 9

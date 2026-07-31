"""
tests/test_interactive/test_star_globe_linking.py
=================================================

The linked celestial globe / sky map explorer
(``Examples/Interactive/plot_star_globe_explorer.py``).

Two things are worth pinning:

* the **coordinate identity** the whole demo rests on — orbiting the globe
  chooses a zenith, and a zenith IS a local sidereal time and a latitude;
* the **event wiring** — a 3-D orbit reaches Python carrying its camera
  angles, and the map overlays follow.  ``Event.azimuth``/``elevation`` exist
  precisely for this: a JS-side drag does not sync back into ``Plot3D._state``,
  so without them a handler cannot react to an orbit at all.

The browser cannot exercise the coupling: the callbacks live in Python, and a
plain ``mount()`` page has no kernel behind it.  So the drag is injected the
way the real bridge injects it — as an ``event_json`` payload.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib

import numpy as np
import pytest

import anyplotlib as apl


EXAMPLE = (pathlib.Path(__file__).parents[3]
           / "Examples" / "Interactive" / "plot_star_globe_explorer.py")


@pytest.fixture(scope="module")
def demo():
    """Execute the example once and hand back its module namespace."""
    spec = importlib.util.spec_from_file_location("_star_globe_demo", EXAMPLE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# The coordinate identity
# ---------------------------------------------------------------------------

class TestZenithMapping:
    def test_round_trips(self, demo):
        for lst, lat in [(0.0, 0.0), (5.5, 35.0), (18.25, -42.0), (23.9, 89.0)]:
            az, el = demo.zenith_to_camera(lst, lat)
            back_lst, back_lat = demo.camera_to_zenith(az, el)
            assert back_lst == pytest.approx(lst, abs=1e-9)
            assert back_lat == pytest.approx(lat, abs=1e-9)

    def test_matches_the_renderer_convention(self, demo):
        """``azimuth = RA + 90°`` is what actually centres that RA on screen.

        Cross-check against the other example: azimuth 172.5 is the angle that
        puts Orion (RA 5.5 h) in the middle of the globe.
        """
        az, el = demo.zenith_to_camera(5.5, 35.0)
        assert az == pytest.approx(172.5)
        assert el == pytest.approx(35.0)

    def test_azimuth_wraps(self, demo):
        assert demo.camera_to_zenith(90.0, 0.0)[0] == pytest.approx(0.0)
        assert demo.camera_to_zenith(-270.0, 0.0)[0] == pytest.approx(0.0)


class TestHorizon:
    def test_every_point_is_ninety_degrees_from_the_zenith(self, demo):
        lst, lat = 7.0, 40.0
        segs = demo.horizon_segments(lst, lat)
        assert len(segs) > 100
        # Map pixels back to sky coordinates and check the angular distance.
        px = segs[:, 0, :]
        ra_h = px[:, 0] / (demo.TEX_W - 1) * 24.0
        dec_d = 90.0 - px[:, 1] / (demo.TEX_H - 1) * 180.0
        sep = np.degrees(demo.angsep(
            np.radians(ra_h * 15.0), np.radians(dec_d),
            np.radians(lst * 15.0), np.radians(lat)))
        assert np.allclose(sep, 90.0, atol=0.5), f"sep range {sep.min()}..{sep.max()}"

    def test_no_segment_spans_the_wrap(self, demo):
        """A curve crossing RA 0h must be cut, not drawn back across the map."""
        for lst in (0.0, 6.0, 12.0, 23.5):
            segs = demo.horizon_segments(lst, 20.0)
            span = np.abs(segs[:, 0, 0] - segs[:, 1, 0])
            assert span.max() < demo.TEX_W / 2

    def test_pole_zenith_is_the_celestial_equator(self, demo):
        """At the pole the horizon IS the equator — the demo's punchline."""
        segs = demo.horizon_segments(3.0, 90.0)
        dec = 90.0 - segs[:, 0, 1] / (demo.TEX_H - 1) * 180.0
        assert np.allclose(dec, 0.0, atol=0.5)


class TestVisibleStars:
    def test_only_stars_above_the_horizon(self, demo):
        lst, lat = 5.5, 35.0
        pts = demo.visible_stars(lst, lat)
        assert 0 < len(pts) < len(demo.STARS)
        ra_h = pts[:, 0] / (demo.TEX_W - 1) * 24.0
        dec_d = 90.0 - pts[:, 1] / (demo.TEX_H - 1) * 180.0
        alt = 90.0 - np.degrees(demo.angsep(
            np.radians(ra_h * 15.0), np.radians(dec_d),
            np.radians(lst * 15.0), np.radians(lat)))
        assert (alt > -0.5).all()

    def test_north_pole_hides_the_southern_sky(self, demo):
        pts = demo.visible_stars(0.0, 89.9)
        dec_d = 90.0 - pts[:, 1] / (demo.TEX_H - 1) * 180.0
        assert (dec_d > -1.0).all()
        # Sirius (dec -16.7) is down; Polaris (dec +89.3) is up.
        assert len(pts) > 5


# ---------------------------------------------------------------------------
# Event wiring
# ---------------------------------------------------------------------------

def _orbit(fig, panel_id, azimuth, elevation):
    """Inject a 3-D orbit exactly as the JS renderer emits it."""
    fig.event_json = json.dumps({
        "source": "js", "panel_id": panel_id, "event_type": "pointer_move",
        "azimuth": azimuth, "elevation": elevation, "zoom": 1.0,
        "x": 10, "y": 10,
    })


class TestEventCarriesCameraAngles:
    def test_azimuth_and_elevation_reach_the_handler(self):
        fig, ax = apl.subplots(1, 1, figsize=(240, 240))
        surf = ax.plot_surface(*np.meshgrid(np.linspace(0, 1, 4),
                                            np.linspace(0, 1, 4))
                               + (np.zeros((4, 4)),))
        seen = {}

        @surf.add_event_handler("pointer_move")
        def _grab(event):
            seen["az"] = event.azimuth
            seen["el"] = event.elevation

        _orbit(fig, surf._id, 123.5, -17.25)
        assert seen == {"az": 123.5, "el": -17.25}

    def test_absent_angles_stay_none(self):
        """A 2-D pointer_move carries no camera, and must not invent one."""
        fig, ax = apl.subplots(1, 1, figsize=(240, 240))
        img = ax.imshow(np.zeros((8, 8)))
        seen = {}

        @img.add_event_handler("pointer_move")
        def _grab(event):
            seen["az"] = event.azimuth

        fig.event_json = json.dumps({
            "source": "js", "panel_id": img._id,
            "event_type": "pointer_move", "x": 1, "y": 1})
        assert seen == {"az": None}


class TestCoupling:
    def test_orbiting_the_globe_moves_the_map_overlays(self, demo):
        before = np.asarray(demo.zenith._data["offsets"])[0]
        # Put RA 12h / dec 0 overhead and confirm the map follows.
        az, el = demo.zenith_to_camera(12.0, 0.0)
        _orbit(demo.fig, demo.globe._id, az, el)
        after = np.asarray(demo.zenith._data["offsets"])[0]
        assert after != pytest.approx(before)
        assert after[0] == pytest.approx(demo.sky_pixel(12.0, 0.0)[0], abs=1.0)
        assert after[1] == pytest.approx(demo.sky_pixel(12.0, 0.0)[1], abs=1.0)

    def test_orbiting_moves_the_sliders_but_not_the_globe(self, demo):
        az, el = demo.zenith_to_camera(9.0, 20.0)
        _orbit(demo.fig, demo.globe._id, az, el)
        assert demo.lst_line.x == pytest.approx(9.0, abs=1e-6)
        assert demo.lat_line.x == pytest.approx(20.0, abs=1e-6)

    def test_the_title_reports_the_zenith(self, demo):
        az, el = demo.zenith_to_camera(15.25, -33.0)
        _orbit(demo.fig, demo.globe._id, az, el)
        title = demo.sky_map._state["title"]
        assert "15.2" in title and "-33" in title

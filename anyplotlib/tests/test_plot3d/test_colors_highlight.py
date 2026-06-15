"""
Tests for Plot3D per-point scatter colors, the highlight point, and the
bounds override — the capabilities behind the IPF explorer example.
"""
from __future__ import annotations

import base64

import numpy as np
import pytest

import anyplotlib as apl


def _scatter(**kwargs):
    fig, ax = apl.subplots(1, 1, figsize=(300, 300))
    pts = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]])
    return ax.scatter3d(pts[:, 0], pts[:, 1], pts[:, 2], **kwargs)


class TestPointColors:
    def test_hex_list(self):
        v = _scatter(colors=["#ff0000", "#00ff00", "#0000ff"])
        raw = base64.b64decode(v._state["point_colors_b64"])
        assert list(raw) == [255, 0, 0, 0, 255, 0, 0, 0, 255]

    def test_float_array(self):
        v = _scatter(colors=np.array([[1, 0, 0], [0, 1, 0], [0, 0, 1.0]]))
        raw = base64.b64decode(v._state["point_colors_b64"])
        assert list(raw) == [255, 0, 0, 0, 255, 0, 0, 0, 255]

    def test_wrong_length_raises(self):
        with pytest.raises(ValueError, match="2 colors for 3 points"):
            _scatter(colors=["#ff0000", "#00ff00"])

    def test_colors_on_surface_raises(self):
        fig, ax = apl.subplots(1, 1)
        g = np.linspace(0, 1, 4)
        XX, YY = np.meshgrid(g, g)
        with pytest.raises(ValueError, match="only supported for scatter"):
            apl.Plot3D("surface", XX, YY, XX * YY, colors=["#fff"] * 16)

    def test_set_point_colors_update_and_clear(self):
        v = _scatter()
        assert v._state["point_colors_b64"] == ""
        v.set_point_colors(["#112233"] * 3)
        assert v._state["point_colors_b64"] != ""
        v.set_point_colors(None)
        assert v._state["point_colors_b64"] == ""


class TestHighlight:
    def test_set_and_clear(self):
        v = _scatter()
        v.set_highlight(0.1, 0.2, 0.3, color="#ffffff", size=9)
        hl = v._state["highlight"]
        assert hl == {"x": 0.1, "y": 0.2, "z": 0.3,
                      "color": "#ffffff", "size": 9.0}
        v.clear_highlight()
        assert v._state["highlight"] is None


class TestSphere:
    def test_set_and_clear(self):
        v = _scatter(bounds=((-1, 1),) * 3)
        v.set_sphere(1.0, color="#777777", alpha=0.2, wireframe=False)
        assert v._state["sphere"] == {"radius": 1.0, "color": "#777777",
                                      "alpha": 0.2, "wireframe": False}
        v.clear_sphere()
        assert v._state["sphere"] is None

    def test_sphere_renders_silhouette(self, interact_page):
        """The shaded disk + wireframe must add substantial ink, bounded by
        the silhouette circle."""
        def ink(with_sphere):
            v = _scatter(bounds=((-1, 1),) * 3, point_size=2)
            v.set_axis_off()
            if with_sphere:
                v.set_sphere(1.0)
            page = interact_page(v._fig)
            page.wait_for_timeout(200)
            return page.evaluate("""() => {
                const c = [...document.querySelectorAll('canvas')].find(x => x.style.position === 'relative' && x.style.display !== 'none');
                const d = c.getContext('2d').getImageData(0,0,c.width,c.height).data;
                // count pixels that differ from the corner background
                const bg = [d[0], d[1], d[2]];
                let n = 0;
                for (let i = 0; i < d.length; i += 4) {
                    if (Math.abs(d[i]-bg[0])+Math.abs(d[i+1]-bg[1])
                        +Math.abs(d[i+2]-bg[2]) > 24) n++;
                }
                return n;
            }""")

        without = ink(False)
        with_s = ink(True)
        assert with_s > without + 2000, (
            f"sphere added too little ink: {without} -> {with_s}")


class TestBoundsOverride:
    def test_bounds_fix_data_bounds(self):
        v = _scatter(bounds=((-1, 1), (-1, 1), (-1, 1)))
        assert v._state["data_bounds"] == {
            "xmin": -1.0, "xmax": 1.0, "ymin": -1.0, "ymax": 1.0,
            "zmin": -1.0, "zmax": 1.0}

    def test_set_data_preserves_bounds(self):
        v = _scatter(bounds=((-1, 1),) * 3)
        v.set_data([0.5], [0.5], [0.5])
        assert v._state["data_bounds"]["xmin"] == -1.0

    def test_default_bounds_fit_data(self):
        v = _scatter()
        assert v._state["data_bounds"]["xmax"] == 1.0
        assert v._state["data_bounds"]["xmin"] == 0.0


class TestRendering:
    def test_colored_points_and_highlight_render(self, interact_page):
        """Pure-coloured points and a white highlight must appear on canvas."""
        v = _scatter(colors=["#ff0000", "#00ff00", "#0000ff"],
                     point_size=10, bounds=((-1, 1),) * 3)
        v.set_axis_off()
        v.set_highlight(-0.6, -0.6, -0.6, color="#ffffff", size=9)
        fig = v._fig
        page = interact_page(fig)
        page.wait_for_timeout(200)

        found = page.evaluate("""() => {
            const c = [...document.querySelectorAll('canvas')].find(x => x.style.position === 'relative' && x.style.display !== 'none');
            const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
            const seen = { red: false, green: false, blue: false, white: false };
            for (let i = 0; i < d.length; i += 4) {
                const r = d[i], g = d[i+1], b = d[i+2];
                if (r > 220 && g < 60 && b < 60) seen.red = true;
                if (g > 220 && r < 60 && b < 60) seen.green = true;
                if (b > 220 && r < 60 && g < 60) seen.blue = true;
                if (r > 240 && g > 240 && b > 240) seen.white = true;
            }
            return seen;
        }""")
        assert found["red"] and found["green"] and found["blue"], (
            f"per-point colours missing from canvas: {found}")
        assert found["white"], f"highlight dot missing from canvas: {found}"

    def test_highlight_moves_with_set_view(self, interact_page):
        """After rotate-to-face, the highlight must sit near panel centre."""
        v = _scatter(bounds=((-1, 1),) * 3, point_size=2)
        v.set_axis_off()
        d = np.array([0.3, 0.4, 0.866])
        d = d / np.linalg.norm(d)
        v.set_highlight(*d, color="#ff00ff", size=8)
        # Turntable face-camera: el = asin(vz), az = atan2(vx, -vy)
        el = float(np.degrees(np.arcsin(np.clip(d[2], -1, 1))))
        az = float(np.degrees(np.arctan2(d[0], -d[1])))
        v.set_view(azimuth=az, elevation=el)
        page = interact_page(v._fig)
        page.wait_for_timeout(200)

        pos = page.evaluate("""() => {
            const c = [...document.querySelectorAll('canvas')].find(x => x.style.position === 'relative' && x.style.display !== 'none');
            const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
            let sx = 0, sy = 0, n = 0;
            for (let y = 0; y < c.height; y++) for (let x = 0; x < c.width; x++) {
                const i = (y * c.width + x) * 4;
                if (d[i] > 220 && d[i+1] < 80 && d[i+2] > 220) { sx += x; sy += y; n++; }
            }
            return n ? { x: sx / n, y: sy / n, n, w: c.width, h: c.height } : null;
        }""")
        assert pos is not None, "magenta highlight not found on canvas"
        # Facing the camera ⇒ projected at the panel centre (within tolerance)
        assert abs(pos["x"] - pos["w"] / 2) < 6, f"highlight off-centre x: {pos}"
        assert abs(pos["y"] - pos["h"] / 2) < 6, f"highlight off-centre y: {pos}"

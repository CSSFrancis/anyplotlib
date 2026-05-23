"""
tests/test_plot3d.py
====================

Tests for Plot3D — surface, scatter, and line geometry types.
Mirrors the Examples/plot_3d.py gallery example.

Covers:
  * plot_surface with 2-D meshgrid arrays
  * scatter3d
  * plot3d (line)
  * set_data() — replace geometry
  * set_colormap() — change colormap
  * set_view() — azimuth and elevation
  * set_zoom()
  * State dict keys and shape sanity checks
  * Validation: bad geom_type, bad surface array shapes
"""
from __future__ import annotations

import numpy as np
import pytest

import anyplotlib as apl
from anyplotlib.plot3d import Plot3D


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _surface():
    x = np.linspace(-2, 2, 10)
    y = np.linspace(-2, 2, 10)
    XX, YY = np.meshgrid(x, y)
    ZZ = np.sin(np.sqrt(XX ** 2 + YY ** 2))
    fig, ax = apl.subplots(1, 1)
    return ax.plot_surface(XX, YY, ZZ, colormap="viridis"), XX, YY, ZZ


def _scatter():
    rng = np.random.default_rng(1)
    n = 50
    x, y, z = rng.uniform(-1, 1, n), rng.uniform(-1, 1, n), rng.uniform(-1, 1, n)
    fig, ax = apl.subplots(1, 1)
    return ax.scatter3d(x, y, z, color="#4fc3f7", point_size=3), x, y, z


def _line():
    t = np.linspace(0, 4 * np.pi, 50)
    x, y, z = np.cos(t), np.sin(t), t / (4 * np.pi)
    fig, ax = apl.subplots(1, 1)
    return ax.plot3d(x, y, z, color="#ff7043"), x, y, z


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------

class TestPlot3DConstruction:

    def test_surface_kind(self):
        surf, *_ = _surface()
        assert surf._state["kind"] == "3d"
        assert surf._state["geom_type"] == "surface"

    def test_scatter_kind(self):
        sc, *_ = _scatter()
        assert sc._state["geom_type"] == "scatter"

    def test_line_kind(self):
        ln, *_ = _line()
        assert ln._state["geom_type"] == "line"

    def test_surface_has_vertices(self):
        surf, *_ = _surface()
        assert surf._state["vertices_count"] == 100   # 10×10 grid

    def test_surface_has_faces(self):
        surf, *_ = _surface()
        assert surf._state["faces_count"] > 0

    def test_scatter_no_faces(self):
        sc, *_ = _scatter()
        assert sc._state["faces_count"] == 0

    def test_colormap_name_stored(self):
        surf, *_ = _surface()
        assert surf._state["colormap_name"] == "viridis"

    def test_colormap_data_is_list(self):
        surf, *_ = _surface()
        lut = surf._state["colormap_data"]
        assert isinstance(lut, list)
        assert len(lut) == 256

    def test_default_azimuth_elevation(self):
        surf, *_ = _surface()
        assert surf._state["azimuth"] == pytest.approx(-60.0)
        assert surf._state["elevation"] == pytest.approx(30.0)

    def test_labels_stored(self):
        x = np.linspace(-1, 1, 5)
        y = np.linspace(-1, 1, 5)
        XX, YY = np.meshgrid(x, y)
        ZZ = XX * YY
        fig, ax = apl.subplots(1, 1)
        surf = ax.plot_surface(XX, YY, ZZ, x_label="a", y_label="b", z_label="c")
        assert surf._state["x_label"] == "a"
        assert surf._state["y_label"] == "b"
        assert surf._state["z_label"] == "c"

    def test_bad_geom_type(self):
        x = np.array([0.0, 1.0])
        with pytest.raises(ValueError):
            Plot3D("cube", x, x, x)

    def test_surface_1d_xy_arrays(self):
        """plot_surface also accepts 1-D x/y + 2-D z (meshgrid already done)."""
        x = np.linspace(-1, 1, 5)
        y = np.linspace(-1, 1, 5)
        ZZ = np.ones((5, 5))
        fig, ax = apl.subplots(1, 1)
        surf = ax.plot_surface(x, y, ZZ)
        assert surf._state["vertices_count"] == 25

    def test_surface_1d_xy_shape_mismatch(self):
        x = np.linspace(-1, 1, 4)
        y = np.linspace(-1, 1, 5)
        ZZ = np.ones((5, 5))
        with pytest.raises(ValueError):
            fig, ax = apl.subplots(1, 1)
            ax.plot_surface(x, y, ZZ)

    def test_surface_bad_array_shape(self):
        x = np.array([1.0, 2.0])   # 1-D but z is also 1-D → invalid
        with pytest.raises(ValueError):
            Plot3D("surface", x, x, x)


# ---------------------------------------------------------------------------
# Mutations
# ---------------------------------------------------------------------------

class TestPlot3DMutations:

    def test_set_colormap(self):
        surf, *_ = _surface()
        surf.set_colormap("plasma")
        assert surf._state["colormap_name"] == "plasma"
        assert isinstance(surf._state["colormap_data"], list)

    def test_set_view_azimuth(self):
        surf, *_ = _surface()
        surf.set_view(azimuth=45.0)
        assert surf._state["azimuth"] == pytest.approx(45.0)

    def test_set_view_elevation(self):
        surf, *_ = _surface()
        surf.set_view(elevation=60.0)
        assert surf._state["elevation"] == pytest.approx(60.0)

    def test_set_view_both(self):
        surf, *_ = _surface()
        surf.set_view(azimuth=30.0, elevation=40.0)
        assert surf._state["azimuth"] == pytest.approx(30.0)
        assert surf._state["elevation"] == pytest.approx(40.0)

    def test_set_zoom(self):
        surf, *_ = _surface()
        surf.set_zoom(2.0)
        assert surf._state["zoom"] == pytest.approx(2.0)

    def test_set_data_surface(self):
        surf, XX, YY, ZZ = _surface()
        ZZ2 = np.cos(np.sqrt(XX ** 2 + YY ** 2))
        surf.set_data(XX, YY, ZZ2)
        # vertices_count should stay the same (same grid)
        assert surf._state["vertices_count"] == 100

    def test_set_data_scatter(self):
        sc, x, y, z = _scatter()
        sc.set_data(x * 2, y * 2, z * 2)
        bounds = sc._state["data_bounds"]
        assert bounds["xmax"] > bounds["xmin"]

    def test_set_data_line(self):
        ln, x, y, z = _line()
        ln.set_data(x[::-1], y[::-1], z[::-1])
        assert ln._state["vertices_count"] == len(x)

    def test_set_data_surface_bad_shape(self):
        surf, XX, YY, ZZ = _surface()
        x = np.array([1.0, 2.0])
        with pytest.raises(ValueError):
            surf.set_data(x, x, x)

    def test_set_view_clears_view_from_python(self):
        surf, *_ = _surface()
        surf.set_view(azimuth=10.0)
        assert surf._state["_view_from_python"] is False

    def test_set_zoom_clears_view_from_python(self):
        surf, *_ = _surface()
        surf.set_zoom(1.5)
        assert surf._state["_view_from_python"] is False

    def test_reset_view_restores_defaults(self):
        surf, *_ = _surface()
        surf.set_view(azimuth=90.0, elevation=10.0)
        surf.set_zoom(3.0)
        surf.reset_view()
        assert surf._state["azimuth"]   == pytest.approx(-60.0)
        assert surf._state["elevation"] == pytest.approx(30.0)
        assert surf._state["zoom"]      == pytest.approx(1.0)
        assert surf._state["_view_from_python"] is False

    def test_reset_view_uses_constructor_angles(self):
        x = np.linspace(-1, 1, 5)
        y = np.linspace(-1, 1, 5)
        XX, YY = np.meshgrid(x, y)
        ZZ = XX * YY
        fig, ax = apl.subplots(1, 1)
        surf = ax.plot_surface(XX, YY, ZZ, azimuth=15.0, elevation=45.0, zoom=2.0)
        surf.set_view(azimuth=0.0, elevation=0.0)
        surf.reset_view()
        assert surf._state["azimuth"]   == pytest.approx(15.0)
        assert surf._state["elevation"] == pytest.approx(45.0)
        assert surf._state["zoom"]      == pytest.approx(2.0)

    def test_set_xlabel(self):
        surf, *_ = _surface()
        surf.set_xlabel("time")
        assert surf._state["x_label"] == "time"

    def test_set_ylabel(self):
        surf, *_ = _surface()
        surf.set_ylabel("depth")
        assert surf._state["y_label"] == "depth"

    def test_set_zlabel(self):
        surf, *_ = _surface()
        surf.set_zlabel("intensity")
        assert surf._state["z_label"] == "intensity"

    def test_set_title(self):
        surf, *_ = _surface()
        surf.set_title("My Surface")
        assert surf._state["title"] == "My Surface"


# ===========================================================================
# repr() uses vertices_count, not len(vertices)
# ===========================================================================

class TestPlot3DRepr:
    def test_repr_uses_vertices_count(self):
        """repr() must read vertices_count, not len(state['vertices'])."""

        class _FakePlot3D(Plot3D):
            def __init__(self):
                self._state = {"geom_type": "mesh", "vertices_count": 42}
                self._id = ""
                self._fig = None

        assert "n_vertices=42" in repr(_FakePlot3D())

    def test_repr_zero_when_count_zero(self):
        class _FakePlot3D(Plot3D):
            def __init__(self):
                self._state = {"geom_type": "scatter", "vertices_count": 0}
                self._id = ""
                self._fig = None

        assert "n_vertices=0" in repr(_FakePlot3D())

    def test_repr_on_real_line(self):
        _, x, y, z = _line()
        # _line() creates a Plot3D via plot3d(); repr must not raise and must
        # show the correct vertex count.
        from anyplotlib.plot3d._plot3d import Plot3D as _P3D
        # find the plot object returned by _line
        ln, *_ = _line()
        r = repr(ln)
        assert "n_vertices=" in r
        # vertex count must equal len(x), not 0
        assert f"n_vertices={len(x)}" in r



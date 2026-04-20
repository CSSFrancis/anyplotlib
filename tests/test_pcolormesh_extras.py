"""
tests/test_pcolormesh_extras.py
================================

Tests for PlotMesh (pcolormesh) mirroring Examples/plot_pcolormesh.py.

Covers:
  * Basic construction with non-uniform edges
  * set_colormap()
  * set_data() — data replacement
  * add_circles / add_lines marker helpers
  * Restriction to circles+lines only
  * State dict keys
"""
from __future__ import annotations

import numpy as np
import pytest

import anyplotlib as apl
from anyplotlib.figure_plots import PlotMesh


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mesh(M=8, N=12):
    rng = np.random.default_rng(42)
    data = rng.standard_normal((M, N))
    x_edges = np.linspace(0, N, N + 1)
    y_edges = np.linspace(0, M, M + 1)
    fig, ax = apl.subplots(1, 1)
    return ax.pcolormesh(data, x_edges=x_edges, y_edges=y_edges)


def _log_mesh():
    """Mesh with non-uniform (log-spaced) x edges, as in the gallery example."""
    M, N = 32, 48
    rng = np.random.default_rng(1)
    data = np.sin(np.linspace(0, 3 * np.pi, N)) + np.cos(np.linspace(0, 2 * np.pi, M))[:, None]
    data += rng.normal(scale=0.15, size=(M, N))
    x_edges = np.logspace(-1, 2, N + 1)
    y_edges = np.linspace(0, 100, M + 1)
    fig, ax = apl.subplots(1, 1)
    return ax.pcolormesh(data, x_edges=x_edges, y_edges=y_edges, units="arb.")


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------

class TestPlotMeshConstruction:

    def test_kind_is_2d(self):
        mesh = _mesh()
        assert mesh._state["kind"] == "2d"

    def test_is_mesh_flag(self):
        mesh = _mesh()
        assert mesh._state["is_mesh"] is True

    def test_x_axis_has_edges(self):
        mesh = _mesh(M=8, N=12)
        # x_axis stores edges (N+1 values)
        assert len(mesh._state["x_axis"]) == 13

    def test_y_axis_has_edges(self):
        mesh = _mesh(M=8, N=12)
        assert len(mesh._state["y_axis"]) == 9

    def test_units_stored(self):
        mesh = _log_mesh()
        assert mesh._state["units"] == "arb."

    def test_log_x_edges(self):
        """Non-uniform (log-spaced) edges should be accepted without error."""
        mesh = _log_mesh()
        assert mesh._state["image_width"] == 48

    def test_default_colormap(self):
        mesh = _mesh()
        assert "colormap_name" in mesh._state

    def test_wrong_x_edge_count(self):
        data = np.ones((8, 12))
        x_edges = np.linspace(0, 10, 10)   # should be 13
        y_edges = np.linspace(0, 8, 9)
        with pytest.raises(ValueError):
            fig, ax = apl.subplots(1, 1)
            ax.pcolormesh(data, x_edges=x_edges, y_edges=y_edges)

    def test_wrong_y_edge_count(self):
        data = np.ones((8, 12))
        x_edges = np.linspace(0, 12, 13)
        y_edges = np.linspace(0, 10, 5)   # should be 9
        with pytest.raises(ValueError):
            fig, ax = apl.subplots(1, 1)
            ax.pcolormesh(data, x_edges=x_edges, y_edges=y_edges)


# ---------------------------------------------------------------------------
# Mutations
# ---------------------------------------------------------------------------

class TestPlotMeshMutations:

    def test_set_colormap(self):
        mesh = _mesh()
        mesh.set_colormap("viridis")
        assert mesh._state["colormap_name"] == "viridis"

    def test_set_colormap_updates_lut(self):
        mesh = _mesh()
        mesh.set_colormap("plasma")
        lut = mesh._state["colormap_data"]
        assert isinstance(lut, list)
        assert len(lut) == 256

    def test_set_data_same_shape(self):
        mesh = _mesh(M=8, N=12)
        new_data = np.ones((8, 12))
        mesh.set_data(new_data)
        assert mesh._state["image_width"] == 12

    def test_set_data_with_new_units(self):
        mesh = _mesh()
        mesh.set_data(np.zeros((8, 12)), units="nm")
        assert mesh._state["units"] == "nm"

    def test_set_data_wrong_ndim(self):
        mesh = _mesh()
        with pytest.raises(ValueError):
            mesh.set_data(np.zeros(12))

    def test_set_data_wrong_x_edges(self):
        mesh = _mesh(M=8, N=12)
        new_data = np.zeros((8, 12))
        bad_x = np.linspace(0, 10, 5)
        with pytest.raises(ValueError):
            mesh.set_data(new_data, x_edges=bad_x)


# ---------------------------------------------------------------------------
# Markers
# ---------------------------------------------------------------------------

class TestPlotMeshMarkers:

    def test_add_circles(self):
        mesh = _mesh()
        pts = np.array([[2.0, 2.0], [6.0, 4.0]])
        mesh.add_circles(pts, name="peaks", radius=0.5, edgecolors="#ff1744")
        assert "peaks" in mesh.markers["circles"]

    def test_add_circles_labels(self):
        mesh = _mesh()
        pts = np.array([[1.0, 2.0], [5.0, 4.0], [9.0, 6.0], [11.0, 2.0]])
        mesh.add_circles(pts, name="pks", radius=0.3,
                         edgecolors="#ff1744", facecolors="#ff174433",
                         labels=["A", "B", "C", "D"])
        wl = mesh.markers.to_wire_list()
        assert any(w.get("labels") == ["A", "B", "C", "D"] for w in wl)

    def test_add_lines(self):
        mesh = _mesh()
        segs = [[[1.0, 1.0], [5.0, 5.0]], [[5.0, 5.0], [10.0, 2.0]]]
        mesh.add_lines(segs, name="path", edgecolors="#00e5ff")
        assert "path" in mesh.markers["lines"]

    def test_arrows_disallowed_on_mesh(self):
        mesh = _mesh()
        with pytest.raises(ValueError, match="not allowed"):
            mesh.add_arrows([[0.0, 0.0]], [1.0], [1.0])

    def test_ellipses_disallowed_on_mesh(self):
        mesh = _mesh()
        with pytest.raises(ValueError, match="not allowed"):
            mesh.add_ellipses([[0.0, 0.0]], widths=5, heights=3)

    def test_circles_set(self):
        mesh = _mesh()
        mesh.add_circles([[2.0, 2.0]], name="c", radius=1.0)
        mesh.markers["circles"]["c"].set(radius=2.0)
        assert mesh.markers["circles"]["c"]._data["radius"] == 2.0

    def test_to_wire_list_contains_circles(self):
        mesh = _mesh()
        mesh.add_circles([[2.0, 2.0]], name="spot")
        wl = mesh.markers.to_wire_list()
        assert any(w["type"] == "circles" for w in wl)


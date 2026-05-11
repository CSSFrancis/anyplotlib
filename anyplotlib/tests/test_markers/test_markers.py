"""
tests/test_markers.py
=====================

Tests for the marker system (MarkerGroup, MarkerTypeDict, MarkerRegistry)
and the high-level add_* helpers on Plot2D, Plot1D, and PlotMesh.

Exercises all marker types from the Examples/Markers gallery:
  circles, arrows, ellipses, lines, rectangles, squares, polygons, texts,
  points, vlines, hlines.

Also covers:
  * set() — live update
  * remove() / clear()
  * auto-naming (circles_1, circles_2, …)
  * to_wire() output structure for every type
  * to_wire() validation errors
  * MarkerTypeDict dict-like interface (contains, iter, len, keys/values/items, pop)
  * MarkerRegistry allowed-type restriction
"""
from __future__ import annotations

import numpy as np
import pytest

import anyplotlib as apl
from anyplotlib.markers import MarkerGroup, MarkerTypeDict, MarkerRegistry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_plot2d():
    fig, ax = apl.subplots(1, 1)
    data = np.random.default_rng(0).standard_normal((64, 64))
    return ax.imshow(data)


def _make_plot1d():
    fig, ax = apl.subplots(1, 1)
    return ax.plot(np.sin(np.linspace(0, 2 * np.pi, 128)))


def _make_mesh():
    fig, ax = apl.subplots(1, 1)
    data = np.ones((8, 12))
    x_edges = np.linspace(0, 12, 13)
    y_edges = np.linspace(0, 8, 9)
    return ax.pcolormesh(data, x_edges=x_edges, y_edges=y_edges)


# ---------------------------------------------------------------------------
# MarkerGroup — to_wire() for every type
# ---------------------------------------------------------------------------

def _push_noop():
    pass


class TestMarkerGroupToWire:

    def _group(self, mtype, **kwargs):
        return MarkerGroup(mtype, "g1", kwargs, _push_noop)

    # ── 2-D types ───────────────────────────────────────────────────────────

    def test_circles_basic(self):
        g = self._group("circles", offsets=[[10.0, 20.0], [30.0, 40.0]], radius=5)
        w = g.to_wire("gid")
        assert w["type"] == "circles"
        assert len(w["offsets"]) == 2
        assert len(w["sizes"]) == 2
        assert w["sizes"][0] == pytest.approx(5.0)

    def test_circles_with_facecolors(self):
        g = self._group("circles", offsets=[[0.0, 0.0]], facecolors="#ff0000", alpha=0.5)
        w = g.to_wire("gid")
        assert "fill_color" in w
        assert w["fill_alpha"] == pytest.approx(0.5)

    def test_arrows_basic(self):
        g = self._group("arrows", offsets=[[0.0, 0.0]], U=1.0, V=2.0, linewidths=2.0)
        w = g.to_wire("gid")
        assert w["type"] == "arrows"
        assert len(w["U"]) == 1
        assert len(w["V"]) == 1
        assert w["linewidth"] == pytest.approx(2.0)

    def test_ellipses_basic(self):
        g = self._group("ellipses",
                        offsets=[[32.0, 32.0], [64.0, 96.0]],
                        widths=30, heights=14, angles=[0.0, 45.0])
        w = g.to_wire("gid")
        assert w["type"] == "ellipses"
        assert len(w["widths"]) == 2
        assert len(w["heights"]) == 2

    def test_ellipses_with_fill(self):
        g = self._group("ellipses", offsets=[[0.0, 0.0]], widths=10, heights=5,
                        facecolors="#00ff00", alpha=0.4)
        w = g.to_wire("gid")
        assert "fill_color" in w

    def test_lines_single_segment(self):
        g = self._group("lines", segments=[[0.0, 0.0], [10.0, 10.0]])
        w = g.to_wire("gid")
        assert w["type"] == "lines"
        assert len(w["segments"]) == 1

    def test_lines_multi_segment(self):
        segs = [[[0.0, 0.0], [5.0, 5.0]], [[5.0, 5.0], [10.0, 0.0]]]
        g = self._group("lines", segments=segs)
        w = g.to_wire("gid")
        assert len(w["segments"]) == 2

    def test_lines_bad_shape(self):
        g = self._group("lines", segments=[[[0.0, 0.0], [1.0, 2.0], [3.0, 4.0]]])
        with pytest.raises(ValueError):
            g.to_wire("gid")

    def test_rectangles_basic(self):
        g = self._group("rectangles", offsets=[[10.0, 10.0]], widths=20, heights=10)
        w = g.to_wire("gid")
        assert w["type"] == "rectangles"

    def test_rectangles_with_fill(self):
        g = self._group("rectangles", offsets=[[0.0, 0.0]], widths=5, heights=5,
                        facecolors="#0000ff", alpha=0.2)
        w = g.to_wire("gid")
        assert "fill_color" in w

    def test_squares_basic(self):
        g = self._group("squares", offsets=[[32.0, 32.0]], widths=20, angles=[15.0])
        w = g.to_wire("gid")
        assert w["type"] == "squares"

    def test_squares_with_fill(self):
        g = self._group("squares", offsets=[[0.0, 0.0]], widths=10,
                        facecolors="#ff00ff", alpha=0.3)
        w = g.to_wire("gid")
        assert "fill_color" in w

    def test_polygons_basic(self):
        tri = [[0.0, 0.0], [10.0, 0.0], [5.0, 8.0]]
        g = self._group("polygons", vertices_list=[tri])
        w = g.to_wire("gid")
        assert w["type"] == "polygons"
        assert len(w["vertices_list"]) == 1

    def test_polygons_with_fill(self):
        tri = [[0.0, 0.0], [10.0, 0.0], [5.0, 8.0]]
        g = self._group("polygons", vertices_list=[tri], facecolors="#aaa", alpha=0.5)
        w = g.to_wire("gid")
        assert "fill_color" in w

    def test_polygons_bad_vertex(self):
        bad = [[0.0, 0.0], [1.0, 1.0]]   # only 2 points — must be ≥3
        g = self._group("polygons", vertices_list=[bad])
        with pytest.raises(ValueError):
            g.to_wire("gid")

    def test_texts_basic(self):
        g = self._group("texts", offsets=[[10.0, 20.0]], texts=["hello"], fontsize=14)
        w = g.to_wire("gid")
        assert w["type"] == "texts"
        assert w["texts"] == ["hello"]
        assert w["fontsize"] == 14

    # ── 1-D types ───────────────────────────────────────────────────────────

    def test_points_basic(self):
        g = self._group("points", offsets=[1.0, 2.0, 3.0], sizes=7, color="#ff0000")
        w = g.to_wire("gid")
        assert w["type"] == "points"
        assert len(w["offsets"]) == 3

    def test_points_with_fill(self):
        g = self._group("points", offsets=[1.0], facecolors="#00ff00", alpha=0.6)
        w = g.to_wire("gid")
        assert "fill_color" in w

    def test_vlines_basic(self):
        g = self._group("vlines", offsets=[1.0, 2.5, 4.0])
        w = g.to_wire("gid")
        assert w["type"] == "vlines"
        assert len(w["offsets"]) == 3
        assert all(len(r) == 1 for r in w["offsets"])

    def test_hlines_basic(self):
        g = self._group("hlines", offsets=[0.5, 1.0])
        w = g.to_wire("gid")
        assert w["type"] == "hlines"
        assert len(w["offsets"]) == 2

    def test_unknown_type_raises(self):
        g = self._group("stars", offsets=[[0.0, 0.0]])
        with pytest.raises(ValueError, match="Unknown marker type"):
            g.to_wire("gid")

    # ── Optional common fields ───────────────────────────────────────────────

    def test_label_included(self):
        g = self._group("circles", offsets=[[0.0, 0.0]], label="my label")
        w = g.to_wire("gid")
        assert w["label"] == "my label"

    def test_labels_included(self):
        g = self._group("circles", offsets=[[0.0, 0.0], [1.0, 1.0]],
                        labels=["A", "B"])
        w = g.to_wire("gid")
        assert w["labels"] == ["A", "B"]

    def test_hover_edgecolors(self):
        g = self._group("circles", offsets=[[0.0, 0.0]], hover_edgecolors="#ff0")
        w = g.to_wire("gid")
        assert w["hover_color"] == "#ff0"

    def test_hover_facecolors(self):
        g = self._group("circles", offsets=[[0.0, 0.0]], hover_facecolors="#0f0")
        w = g.to_wire("gid")
        assert w["hover_facecolor"] == "#0f0"


# ---------------------------------------------------------------------------
# MarkerGroup — set() triggers push
# ---------------------------------------------------------------------------

class TestMarkerGroupSet:

    def test_set_updates_data(self):
        calls = []
        g = MarkerGroup("circles", "g", {"offsets": [[0.0, 0.0]], "radius": 5},
                        lambda: calls.append(1))
        g.set(radius=10)
        assert g._data["radius"] == 10
        assert len(calls) == 1

    def test_count_zero_when_no_offsets(self):
        g = MarkerGroup("circles", "g", {}, _push_noop)
        assert g._count() == 0


# ---------------------------------------------------------------------------
# MarkerTypeDict
# ---------------------------------------------------------------------------

class TestMarkerTypeDict:

    def _td(self):
        calls = []
        td = MarkerTypeDict("circles", lambda: calls.append(1))
        return td, calls

    def test_setitem_triggers_push(self):
        td, calls = self._td()
        g = MarkerGroup("circles", "g", {"offsets": [[0.0, 0.0]]}, _push_noop)
        td["g"] = g
        assert len(calls) == 1

    def test_delitem_triggers_push(self):
        td, calls = self._td()
        g = MarkerGroup("circles", "g", {"offsets": [[0.0, 0.0]]}, _push_noop)
        td._groups["g"] = g
        del td["g"]
        assert len(calls) == 1

    def test_contains(self):
        td, _ = self._td()
        g = MarkerGroup("circles", "g", {}, _push_noop)
        td._groups["g"] = g
        assert "g" in td
        assert "x" not in td

    def test_iter(self):
        td, _ = self._td()
        g = MarkerGroup("circles", "g", {}, _push_noop)
        td._groups["g"] = g
        assert list(td) == ["g"]

    def test_len(self):
        td, _ = self._td()
        assert len(td) == 0
        td._groups["a"] = MarkerGroup("circles", "a", {}, _push_noop)
        assert len(td) == 1

    def test_keys_values_items(self):
        td, _ = self._td()
        g = MarkerGroup("circles", "g", {}, _push_noop)
        td._groups["g"] = g
        assert "g" in td.keys()
        assert g in td.values()
        assert ("g", g) in td.items()

    def test_pop_triggers_push(self):
        td, calls = self._td()
        g = MarkerGroup("circles", "g", {}, _push_noop)
        td._groups["g"] = g
        result = td.pop("g")
        assert result is g
        assert len(calls) == 1

    def test_pop_default(self):
        td, _ = self._td()
        result = td.pop("missing", None)
        assert result is None

    def test_to_wire_list(self):
        td, _ = self._td()
        g = MarkerGroup("circles", "g", {"offsets": [[5.0, 5.0]]}, _push_noop)
        td._groups["g"] = g
        wl = td.to_wire_list()
        assert len(wl) == 1
        assert wl[0]["type"] == "circles"


# ---------------------------------------------------------------------------
# MarkerRegistry
# ---------------------------------------------------------------------------

class TestMarkerRegistry:

    def _reg(self, allowed=None):
        calls = []
        reg = MarkerRegistry(lambda: calls.append(1), allowed=allowed)
        return reg, calls

    def test_auto_creates_type_dict(self):
        reg, _ = self._reg()
        td = reg["circles"]
        assert isinstance(td, MarkerTypeDict)
        assert "circles" in reg

    def test_allowed_restriction(self):
        reg, _ = self._reg(allowed=frozenset({"circles"}))
        with pytest.raises(ValueError, match="not allowed"):
            reg["arrows"]

    def test_add_returns_marker_group(self):
        reg, calls = self._reg()
        g = reg.add("circles", name="g1", offsets=[[0.0, 0.0]], radius=5)
        assert isinstance(g, MarkerGroup)
        assert len(calls) == 1

    def test_add_auto_name(self):
        reg, _ = self._reg()
        g1 = reg.add("circles", offsets=[[0.0, 0.0]])
        g2 = reg.add("circles", offsets=[[1.0, 1.0]])
        assert g1._name == "circles_1"
        assert g2._name == "circles_2"

    def test_remove(self):
        reg, calls = self._reg()
        reg.add("circles", name="g1", offsets=[[0.0, 0.0]])
        n_before = len(calls)
        reg.remove("circles", "g1")
        assert len(calls) > n_before

    def test_clear(self):
        reg, calls = self._reg()
        reg.add("circles", name="g1", offsets=[[0.0, 0.0]])
        reg.clear()
        assert "circles" not in reg

    def test_iter(self):
        reg, _ = self._reg()
        reg.add("circles", name="g1", offsets=[[0.0, 0.0]])
        assert "circles" in list(reg)

    def test_to_wire_list(self):
        reg, _ = self._reg()
        reg.add("circles", name="g1", offsets=[[10.0, 20.0]], radius=4)
        wl = reg.to_wire_list()
        assert len(wl) == 1
        assert wl[0]["type"] == "circles"

    def test_auto_name_with_custom_names(self):
        """Auto-naming should not be confused by custom-named groups."""
        reg, _ = self._reg()
        reg.add("circles", name="my_spot", offsets=[[0.0, 0.0]])
        g = reg.add("circles", offsets=[[1.0, 1.0]])
        assert g._name == "circles_1"


# ---------------------------------------------------------------------------
# Plot2D high-level add_* helpers (from Examples/Markers)
# ---------------------------------------------------------------------------

class TestPlot2DMarkerHelpers:

    def test_add_circles(self):
        v = _make_plot2d()
        centres = np.array([[10.0, 20.0], [30.0, 40.0]])
        v.add_circles(centres, name="spots", radius=10,
                      edgecolors="#ff1744", facecolors="#ff174433",
                      labels=["A", "B"])
        assert "spots" in v.markers["circles"]
        wl = v.markers.to_wire_list()
        assert any(w["type"] == "circles" for w in wl)

    def test_add_circles_set(self):
        v = _make_plot2d()
        v.add_circles([[5.0, 5.0]], name="c", radius=5)
        v.markers["circles"]["c"].set(radius=12, edgecolors="#ffcc00")
        assert v.markers["circles"]["c"]._data["radius"] == 12

    def test_add_arrows(self):
        v = _make_plot2d()
        tails = np.array([[20.0, 20.0], [60.0, 60.0]])
        U = np.array([5.0, -5.0])
        V = np.array([5.0, -5.0])
        v.add_arrows(tails, U, V, name="flow", edgecolors="#76ff03")
        assert "flow" in v.markers["arrows"]

    def test_add_arrows_set(self):
        v = _make_plot2d()
        v.add_arrows([[5.0, 5.0]], [1.0], [1.0], name="arr")
        v.markers["arrows"]["arr"].set(edgecolors="#ff9100", linewidths=2.5)
        assert v.markers["arrows"]["arr"]._data["edgecolors"] == "#ff9100"

    def test_add_ellipses(self):
        v = _make_plot2d()
        centres = np.array([[32.0, 32.0], [64.0, 96.0]])
        v.add_ellipses(centres, widths=30, heights=14, angles=[0.0, 45.0],
                       name="grains", edgecolors="#ff9100")
        assert "grains" in v.markers["ellipses"]

    def test_add_ellipses_set(self):
        v = _make_plot2d()
        v.add_ellipses([[0.0, 0.0]], widths=10, heights=5, name="e")
        v.markers["ellipses"]["e"].set(widths=20)
        assert v.markers["ellipses"]["e"]._data["widths"] == 20

    def test_add_rectangles(self):
        v = _make_plot2d()
        centres = np.array([[20.0, 20.0], [50.0, 50.0]])
        v.add_rectangles(centres, widths=22, heights=14, name="boxes",
                         edgecolors="#00e5ff")
        assert "boxes" in v.markers["rectangles"]

    def test_add_rectangles_set(self):
        v = _make_plot2d()
        v.add_rectangles([[5.0, 5.0]], widths=10, heights=5, name="r")
        v.markers["rectangles"]["r"].set(widths=20, heights=10)
        assert v.markers["rectangles"]["r"]._data["widths"] == 20

    def test_add_squares(self):
        v = _make_plot2d()
        centres = np.array([[32.0, 32.0], [64.0, 64.0]])
        v.add_squares(centres, widths=20, angles=[0, 15], name="tiles")
        assert "tiles" in v.markers["squares"]

    def test_add_squares_set(self):
        v = _make_plot2d()
        v.add_squares([[5.0, 5.0]], widths=10, name="s")
        v.markers["squares"]["s"].set(widths=20, edgecolors="#e040fb")
        assert v.markers["squares"]["s"]._data["widths"] == 20

    def test_add_polygons(self):
        v = _make_plot2d()
        tri = [[10.0, 5.0], [20.0, 25.0], [0.0, 25.0]]
        v.add_polygons([tri], name="poly", edgecolors="#ff9100")
        assert "poly" in v.markers["polygons"]

    def test_add_texts(self):
        v = _make_plot2d()
        v.add_texts([[10.0, 10.0], [30.0, 30.0]], texts=["A", "B"],
                    name="labels", color="#ffffff", fontsize=12)
        assert "labels" in v.markers["texts"]

    def test_add_lines_2d(self):
        v = _make_plot2d()
        segs = [[[5.0, 5.0], [20.0, 20.0]], [[20.0, 20.0], [40.0, 5.0]]]
        v.add_lines(segs, name="segs")
        assert "segs" in v.markers["lines"]

    def test_remove_marker(self):
        v = _make_plot2d()
        v.add_circles([[0.0, 0.0]], name="c")
        v.remove_marker("circles", "c")
        assert "c" not in v.markers["circles"]

    def test_clear_markers(self):
        v = _make_plot2d()
        v.add_circles([[0.0, 0.0]], name="c1")
        v.add_circles([[1.0, 1.0]], name="c2")
        v.clear_markers()
        assert v.markers.to_wire_list() == []

    def test_list_markers(self):
        v = _make_plot2d()
        v.add_circles([[0.0, 0.0], [1.0, 1.0]], name="c")
        info = v.list_markers()
        assert any(d["name"] == "c" and d["n"] == 2 for d in info)


# ---------------------------------------------------------------------------
# Plot1D marker helpers
# ---------------------------------------------------------------------------

class TestPlot1DMarkerHelpers:

    def test_add_points(self):
        v = _make_plot1d()
        offsets = np.column_stack([[1.0, 2.0, 3.0], [0.5, 0.8, 0.3]])
        v.add_points(offsets, name="peaks", sizes=7, color="#ff1744")
        assert "peaks" in v.markers["points"]

    def test_add_vlines(self):
        v = _make_plot1d()
        v.add_vlines([1.0, 2.0, 3.0], name="marks", color="#00e5ff")
        assert "marks" in v.markers["vlines"]

    def test_add_hlines(self):
        v = _make_plot1d()
        v.add_hlines([0.5, -0.5], name="levels", color="#ff9100")
        assert "levels" in v.markers["hlines"]

    def test_remove_marker_1d(self):
        v = _make_plot1d()
        v.add_vlines([1.0], name="m")
        v.remove_marker("vlines", "m")
        assert "m" not in v.markers["vlines"]

    def test_clear_markers_1d(self):
        v = _make_plot1d()
        v.add_vlines([1.0], name="v1")
        v.add_hlines([0.5], name="h1")
        v.clear_markers()
        assert v.markers.to_wire_list() == []


# ---------------------------------------------------------------------------
# PlotMesh marker helpers
# ---------------------------------------------------------------------------

class TestPlotMeshMarkerHelpers:

    def test_add_circles_mesh(self):
        mesh = _make_mesh()
        pts = np.array([[2.0, 2.0], [6.0, 4.0]])
        mesh.add_circles(pts, name="peaks", radius=0.5, edgecolors="#ff1744")
        assert "peaks" in mesh.markers["circles"]

    def test_add_lines_mesh(self):
        mesh = _make_mesh()
        segs = [[[1.0, 1.0], [5.0, 5.0]]]
        mesh.add_lines(segs, name="path", edgecolors="#00e5ff")
        assert "path" in mesh.markers["lines"]

    def test_mesh_disallows_arrows(self):
        mesh = _make_mesh()
        with pytest.raises(ValueError, match="not allowed"):
            mesh.add_arrows([[0.0, 0.0]], [1.0], [1.0])


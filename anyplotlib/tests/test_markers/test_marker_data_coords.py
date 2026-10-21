"""
Markers in calibrated data coordinates (``coords="data"``).

On a 2-D panel ``transform="data"`` positions are image pixels.  A group
created with ``coords="data"`` keeps calibrated values and converts them to
pixels on serialisation — so it also follows a re-calibration.

12 rows × 25 columns throughout, so a swapped axis cannot pass.
"""
from __future__ import annotations

import numpy as np
import pytest

import anyplotlib as apl

H, W = 12, 25
X = 10.0 + 0.5 * np.arange(W)       # col = (x - 10) / 0.5
Y = -3.0 + 0.25 * np.arange(H)      # row = (y + 3) / 0.25


def _plot(**kwargs):
    fig, ax = apl.subplots(1, 1)
    return ax.imshow(np.zeros((H, W)), axes=[X, Y], **kwargs)


def _wire(group):
    return group.to_wire("g")


class TestPositions:
    def test_circles(self):
        g = _plot().add_circles([[11.0, -2.0], [12.0, -1.0]], radius=1.0,
                                coords="data")
        w = _wire(g)
        np.testing.assert_allclose(w["offsets"], [[2.0, 4.0], [4.0, 8.0]])
        assert w["sizes"] == pytest.approx([2.0, 2.0])     # radius follows x
        # The group keeps what the caller gave it.
        assert g._data["offsets"] == [[11.0, -2.0], [12.0, -1.0]]
        assert g.coords == "data"

    def test_single_pair_offsets(self):
        g = _plot().add_circles([11.0, -2.0], coords="data")
        np.testing.assert_allclose(_wire(g)["offsets"], [[2.0, 4.0]])

    def test_lines_segments(self):
        g = _plot().add_lines([[[10.0, -3.0], [12.0, -2.0]]], coords="data")
        np.testing.assert_allclose(_wire(g)["segments"], [[[0.0, 0.0], [4.0, 4.0]]])

    def test_lines_ndarray_segments(self):
        segs = np.array([[[10.0, -3.0], [12.0, -2.0]],
                         [[11.0, -1.0], [13.0, 0.0]]])
        g = _plot().add_lines(segs, coords="data")
        np.testing.assert_allclose(_wire(g)["segments"][1], [[2.0, 8.0], [6.0, 12.0]])

    def test_polygons(self):
        g = _plot().add_polygons([[(10.0, -3.0), (12.0, -3.0), (12.0, -2.0)]],
                                 coords="data")
        np.testing.assert_allclose(_wire(g)["vertices_list"],
                                   [[[0.0, 0.0], [4.0, 0.0], [4.0, 4.0]]])

    def test_texts(self):
        g = _plot().add_texts([[11.0, -2.0]], ["a"], coords="data")
        np.testing.assert_allclose(_wire(g)["offsets"], [[2.0, 4.0]])

    def test_add_text_single(self):
        plot = _plot()
        plot.add_text(11.0, -2.0, "a", coords="data")
        wire = plot.to_state_dict()["markers"][0]
        np.testing.assert_allclose(wire["offsets"], [[2.0, 4.0]])

    def test_registry_add(self):
        g = _plot().markers.add("circles", offsets=[[11.0, -2.0]], radius=0.5,
                                coords="data")
        np.testing.assert_allclose(_wire(g)["offsets"], [[2.0, 4.0]])
        assert _wire(g)["sizes"] == pytest.approx([1.0])


class TestLengths:
    def test_rectangles(self):
        g = _plot().add_rectangles([[11.0, -2.0]], widths=1.0, heights=[0.5],
                                   coords="data")
        w = _wire(g)
        assert w["widths"] == pytest.approx([2.0])
        assert w["heights"] == pytest.approx([2.0])

    def test_ellipses_and_squares(self):
        plot = _plot()
        e = plot.add_ellipses([[11.0, -2.0]], widths=[2.0], heights=[1.0],
                              coords="data")
        assert _wire(e)["widths"] == pytest.approx([4.0])
        assert _wire(e)["heights"] == pytest.approx([4.0])
        sq = plot.add_squares([[11.0, -2.0]], widths=1.0, coords="data")
        assert _wire(sq)["widths"] == pytest.approx([2.0])

    def test_arrows_signed(self):
        g = _plot(origin="lower").add_arrows([[11.0, -2.0]], U=[1.0], V=[0.5],
                                             coords="data")
        w = _wire(g)
        assert w["U"] == pytest.approx([2.0])
        assert w["V"] == pytest.approx([-2.0])   # +y is up the screen

    def test_px_sizes_untouched(self):
        g = _plot().add_circles([[11.0, -2.0]], radius=6, size_units="px",
                                coords="data")
        w = _wire(g)
        np.testing.assert_allclose(w["offsets"], [[2.0, 4.0]])
        assert w["sizes"] == pytest.approx([6.0])


class TestBehaviour:
    def test_default_is_pixel(self):
        g = _plot().add_circles([[2.0, 4.0]])
        assert g.coords == "pixel"
        np.testing.assert_allclose(_wire(g)["offsets"], [[2.0, 4.0]])

    def test_set_in_data(self):
        g = _plot().add_circles([[11.0, -2.0]], coords="data")
        g.set(offsets=[[12.0, -1.0]])
        np.testing.assert_allclose(_wire(g)["offsets"], [[4.0, 8.0]])

    def test_set_coords(self):
        g = _plot().add_circles([[2.0, 4.0]])
        g.set(coords="data", offsets=[[11.0, -2.0]])
        assert g.coords == "data"
        np.testing.assert_allclose(_wire(g)["offsets"], [[2.0, 4.0]])
        assert "coords" not in g._data

    def test_invalid_coords(self):
        with pytest.raises(ValueError, match="coords"):
            _plot().add_circles([[1.0, 2.0]], coords="screen")
        g = _plot().add_circles([[1.0, 2.0]])
        with pytest.raises(ValueError, match="coords"):
            g.set(coords="screen")

    def test_follows_recalibration(self):
        plot = _plot()
        plot.add_circles([[12.0, -1.0]], coords="data")
        plot.set_extent(2 * X, 2 * Y)
        wire = plot.to_state_dict()["markers"][0]
        # 12 is now column 1 (x = 20 + col), -1 is now between rows.
        np.testing.assert_allclose(wire["offsets"], [[-8.0, 10.0]])

    def test_axes_transform_not_converted(self):
        g = _plot().add_circles([[0.5, 0.5]], transform="axes", coords="data")
        np.testing.assert_allclose(_wire(g)["offsets"], [[0.5, 0.5]])

    def test_empty_offsets(self):
        g = _plot().add_lines(np.zeros((0, 2, 2)), coords="data")
        assert _wire(g)["segments"] == []

    def test_mesh(self):
        fig, ax = apl.subplots(1, 1)
        xe = 5.0 + 2.0 * np.arange(W + 1)
        ye = np.linspace(0.0, 1.2, H + 1)
        plot = ax.pcolormesh(np.zeros((H, W)), x_edges=xe, y_edges=ye)
        g = plot.add_circles([[6.0, 0.05]], coords="data")
        np.testing.assert_allclose(_wire(g)["offsets"], [[0.0, 0.0]], atol=1e-12)

    def test_1d_accepts_and_ignores(self):
        fig, ax = apl.subplots(1, 1)
        plot = ax.plot(np.arange(48.0))
        g = plot.markers.add("vlines", offsets=[3.0], coords="data")
        assert _wire(g)["offsets"] == [[3.0]]

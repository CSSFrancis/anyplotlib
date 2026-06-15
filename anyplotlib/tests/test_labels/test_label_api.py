"""
Unit tests for the label font-size API and TeX pass-through.

Covers:
  * fontsize kwarg on set_xlabel / set_ylabel / set_zlabel / set_title /
    set_colorbar_label for every panel type
  * fontsize=None leaves the size state untouched (JS falls back to defaults)
  * set_tick_label_size
  * TeX-formatted label strings are stored verbatim (parsing happens in JS)
"""
from __future__ import annotations

import numpy as np
import pytest

import anyplotlib as apl


def _imshow():
    fig, ax = apl.subplots(1, 1)
    return ax.imshow(np.zeros((8, 8)))


def _plot():
    fig, ax = apl.subplots(1, 1)
    return ax.plot(np.zeros(16))


def _bar():
    fig, ax = apl.subplots(1, 1)
    return ax.bar(["a", "b"], [1.0, 2.0])


def _surface():
    fig, ax = apl.subplots(1, 1)
    g = np.linspace(-1, 1, 8)
    XX, YY = np.meshgrid(g, g)
    return ax.plot_surface(XX, YY, XX * YY)


class TestFontsizeKwarg:
    def test_plot2d_xlabel_fontsize(self):
        v = _imshow()
        v.set_xlabel("x", fontsize=14)
        assert v._state["x_label"] == "x"
        assert v._state["x_label_size"] == 14.0

    def test_plot2d_ylabel_fontsize(self):
        v = _imshow()
        v.set_ylabel("y", fontsize=16)
        assert v._state["y_label"] == "y"
        assert v._state["y_label_size"] == 16.0

    def test_plot2d_colorbar_label_fontsize(self):
        v = _imshow()
        v.set_colorbar_label("counts", fontsize=13)
        assert v._state["colorbar_label"] == "counts"
        assert v._state["colorbar_label_size"] == 13.0

    def test_plot1d_label_fontsize_maps_to_units(self):
        v = _plot()
        v.set_xlabel("eV", fontsize=12)
        v.set_ylabel("counts", fontsize=11)
        assert v._state["units"] == "eV"
        assert v._state["x_label_size"] == 12.0
        assert v._state["y_units"] == "counts"
        assert v._state["y_label_size"] == 11.0

    def test_plotbar_label_fontsize(self):
        v = _bar()
        v.set_xlabel("category", fontsize=12)
        v.set_ylabel("value", fontsize=13)
        assert v._state["x_label_size"] == 12.0
        assert v._state["y_label_size"] == 13.0

    def test_plot3d_label_fontsize(self):
        v = _surface()
        v.set_xlabel("x", fontsize=14)
        v.set_ylabel("y", fontsize=15)
        v.set_zlabel("z", fontsize=16)
        assert v._state["x_label_size"] == 14.0
        assert v._state["y_label_size"] == 15.0
        assert v._state["z_label_size"] == 16.0

    def test_title_fontsize_all_panel_types(self):
        for make in (_imshow, _plot, _bar, _surface):
            v = make()
            v.set_title("T", fontsize=12)
            assert v._state["title"] == "T"
            assert v._state["title_size"] == 12.0


class TestFontsizeNoneKeepsState:
    def test_none_does_not_create_size_key(self):
        v = _imshow()
        v.set_xlabel("x")
        assert "x_label_size" not in v._state

    def test_none_does_not_overwrite_previous_size(self):
        v = _imshow()
        v.set_xlabel("x", fontsize=18)
        v.set_xlabel("renamed")          # no fontsize — keep 18
        assert v._state["x_label"] == "renamed"
        assert v._state["x_label_size"] == 18.0


class TestTickLabelSize:
    @pytest.mark.parametrize("make", [_imshow, _plot, _bar])
    def test_set_tick_label_size(self, make):
        v = make()
        v.set_tick_label_size(14)
        assert v._state["tick_size"] == 14.0


class TestTexPassThrough:
    """Python stores TeX strings verbatim; all parsing happens at JS draw time."""

    def test_tex_label_stored_verbatim(self):
        v = _imshow()
        label = r"$q$ ($\AA^{-1}$)"
        v.set_xlabel(label)
        assert v._state["x_label"] == label

    def test_tex_exponent_title(self):
        v = _plot()
        v.set_title(r"Intensity $\times 10^{-3}$")
        assert v._state["title"] == r"Intensity $\times 10^{-3}$"

    def test_tex_subscript_colorbar(self):
        v = _imshow()
        v.set_colorbar_label(r"$E_F$ (eV)")
        assert v._state["colorbar_label"] == r"$E_F$ (eV)"

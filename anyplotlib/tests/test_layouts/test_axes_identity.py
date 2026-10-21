"""
Public Axes identity: ``figure``, ``primary_plot``, ``plots``, ``image_plot``.
"""
from __future__ import annotations

import numpy as np
import pytest

import anyplotlib as apl


def test_figure():
    fig, ax = apl.subplots(1, 1)
    assert ax.figure is fig


def test_figure_on_grid_and_inset():
    fig, axes = apl.subplots(1, 2)
    assert all(a.figure is fig for a in axes)
    inset = fig.add_inset(0.3, 0.3)
    assert inset.figure is fig


def test_figure_same_assignment_is_noop():
    fig, ax = apl.subplots(1, 1)
    ax.figure = fig            # matplotlib-style code does this
    assert ax.figure is fig


def test_figure_reassign_raises():
    fig, ax = apl.subplots(1, 1)
    other, _ = apl.subplots(1, 1)
    with pytest.raises(AttributeError):
        ax.figure = other


def test_empty_axes():
    fig, ax = apl.subplots(1, 1)
    assert ax.primary_plot is None
    assert ax.plots == ()
    assert ax.image_plot is None
    assert ax.has_plot is False


def test_image():
    fig, ax = apl.subplots(1, 1)
    plot = ax.imshow(np.zeros((12, 25)))
    assert ax.primary_plot is plot
    assert ax.plots == (plot,)
    assert ax.image_plot is plot
    assert ax.has_plot


def test_mesh_is_image():
    fig, ax = apl.subplots(1, 1)
    plot = ax.pcolormesh(np.zeros((12, 25)))
    assert ax.image_plot is plot


def test_line_is_not_image():
    fig, ax = apl.subplots(1, 1)
    plot = ax.plot(np.arange(48.0))
    assert ax.primary_plot is plot
    assert ax.image_plot is None


def test_overlays_do_not_shadow_primary():
    fig, ax = apl.subplots(1, 1)
    plot = ax.plot(np.arange(48.0))
    plot.add_line(np.arange(48.0) * 2)
    plot.add_vline_widget(3.0)
    plot.add_vlines([1.0, 2.0])
    assert ax.primary_plot is plot
    assert ax.plots == (plot,)

    fig, ax = apl.subplots(1, 1)
    img = ax.imshow(np.zeros((12, 25)))
    img.add_widget("crosshair")
    img.add_lines([[[0, 0], [3, 3]]])
    assert ax.image_plot is img and ax.primary_plot is img


def test_replacing_plot():
    fig, ax = apl.subplots(1, 1)
    ax.imshow(np.zeros((12, 25)))
    line = ax.plot(np.arange(48.0))
    assert ax.primary_plot is line
    assert ax.image_plot is None


def test_read_only():
    fig, ax = apl.subplots(1, 1)
    with pytest.raises(AttributeError):
        ax.primary_plot = None
    with pytest.raises(AttributeError):
        ax.plots = ()

"""
tests/test_markers/test_marker_transforms.py
=============================================
Tests for the coordinate transform parameter on marker collections.

Exercises: transform="data" (default), transform="axes", transform="display",
invalid transform, all add_* methods on both Plot1D and Plot2D, and that
set() preserves the transform.
"""
from __future__ import annotations

import numpy as np
import pytest

import anyplotlib as apl
from anyplotlib.markers import MarkerGroup


def _push_noop():
    pass


def _group(mtype, **kwargs):
    return MarkerGroup(mtype, "g1", kwargs, _push_noop)


def _make_plot2d():
    fig, ax = apl.subplots(1, 1)
    return ax.imshow(np.zeros((32, 32)))


def _make_plot1d():
    fig, ax = apl.subplots(1, 1)
    return ax.plot(np.zeros(32))


# ---------------------------------------------------------------------------
# MarkerGroup — wire-format round-trips
# ---------------------------------------------------------------------------

class TestTransformWireFormat:

    def test_transform_default_is_data(self):
        g = _group("circles", offsets=[[1.0, 2.0]], radius=5)
        w = g.to_wire("gid")
        assert w["transform"] == "data"

    def test_transform_axes_round_trips(self):
        g = _group("texts", offsets=[[0.05, 0.95]], texts=["(3, 7)"],
                   transform="axes")
        w = g.to_wire("gid")
        assert w["transform"] == "axes"

    def test_transform_display_round_trips(self):
        g = _group("circles", offsets=[[8.0, 8.0]], transform="display")
        w = g.to_wire("gid")
        assert w["transform"] == "display"

    def test_clip_display_defaults_true(self):
        g = _group("circles", offsets=[[8.0, 8.0]], transform="display")
        w = g.to_wire("gid")
        assert w["clip_display"] is True

    def test_clip_display_round_trips_false(self):
        g = _group("circles", offsets=[[8.0, 8.0]], transform="display",
                   clip_display=False)
        w = g.to_wire("gid")
        assert w["clip_display"] is False

    def test_transform_data_explicit(self):
        g = _group("rectangles", offsets=[[0.0, 0.0]], widths=10, heights=10,
                   transform="data")
        w = g.to_wire("gid")
        assert w["transform"] == "data"

    def test_all_2d_types_emit_transform(self):
        types_and_kwargs = [
            ("circles",    dict(offsets=[[1, 2]], radius=5)),
            ("arrows",     dict(offsets=[[1, 2]], U=1, V=1)),
            ("ellipses",   dict(offsets=[[1, 2]], widths=4, heights=3)),
            ("lines",      dict(segments=[[[0, 0], [1, 1]]])),
            ("rectangles", dict(offsets=[[1, 2]], widths=4, heights=3)),
            ("squares",    dict(offsets=[[1, 2]], widths=4)),
            ("polygons",   dict(vertices_list=[[[0,0],[1,0],[0.5,1]]])),
            ("texts",      dict(offsets=[[1, 2]], texts=["hi"])),
        ]
        for mtype, kwargs in types_and_kwargs:
            g = _group(mtype, transform="axes", **kwargs)
            w = g.to_wire("gid")
            assert w["transform"] == "axes", f"Failed for type {mtype!r}"

    def test_1d_types_emit_transform(self):
        types_and_kwargs = [
            ("points", dict(offsets=[1.0, 2.0])),
            ("vlines", dict(offsets=[1.0, 2.0])),
            ("hlines", dict(offsets=[1.0, 2.0])),
        ]
        for mtype, kwargs in types_and_kwargs:
            g = _group(mtype, transform="axes", **kwargs)
            w = g.to_wire("gid")
            assert w["transform"] == "axes", f"Failed for type {mtype!r}"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class TestTransformValidation:

    def test_invalid_transform_raises_on_init(self):
        with pytest.raises(ValueError, match="transform"):
            _group("circles", offsets=[[1, 2]], transform="screen")

    def test_invalid_transform_raises_on_set(self):
        g = _group("circles", offsets=[[1, 2]])
        with pytest.raises(ValueError, match="transform"):
            g.set(transform="bad")

    def test_valid_transforms_do_not_raise(self):
        for tfm in ("data", "axes", "display"):
            _group("circles", offsets=[[1, 2]], transform=tfm)  # no error

    def test_invalid_clip_display_raises(self):
        with pytest.raises(ValueError, match="clip_display"):
            _group("circles", offsets=[[1, 2]], clip_display="nope")

    def test_invalid_clip_display_raises_on_set(self):
        g = _group("circles", offsets=[[1, 2]])
        with pytest.raises(ValueError, match="clip_display"):
            g.set(clip_display=1)


# ---------------------------------------------------------------------------
# set() preserves transform
# ---------------------------------------------------------------------------

class TestTransformPreservedOnSet:

    def test_set_does_not_reset_transform(self):
        g = _group("circles", offsets=[[1, 2]], radius=5, transform="axes")
        g.set(radius=10)
        w = g.to_wire("gid")
        assert w["transform"] == "axes"

    def test_set_can_update_transform(self):
        g = _group("circles", offsets=[[1, 2]], transform="axes")
        g.set(transform="display")
        w = g.to_wire("gid")
        assert w["transform"] == "display"


# ---------------------------------------------------------------------------
# Plot2D add_* methods accept transform kwarg
# ---------------------------------------------------------------------------

class TestPlot2DTransformKwarg:

    def setup_method(self):
        self.plot = _make_plot2d()

    def test_add_circles_transform_axes(self):
        g = self.plot.add_circles([[10, 10]], name="c", transform="axes")
        wire = self.plot.markers.to_wire_list()
        assert wire[0]["transform"] == "axes"

    def test_add_points_transform_axes(self):
        g = self.plot.add_points([[10, 10]], name="p", transform="axes")
        wire = self.plot.markers.to_wire_list()
        assert wire[0]["transform"] == "axes"

    def test_add_texts_transform_axes(self):
        g = self.plot.add_texts([[0.05, 0.95]], ["label"], name="t",
                                transform="axes")
        wire = self.plot.markers.to_wire_list()
        assert wire[0]["transform"] == "axes"

    def test_add_rectangles_transform_display(self):
        g = self.plot.add_rectangles([[5, 5]], widths=10, heights=10, name="r",
                                     transform="display")
        wire = self.plot.markers.to_wire_list()
        assert wire[0]["transform"] == "display"

    def test_add_rectangles_clip_display_false(self):
        self.plot.add_rectangles([[5, 5]], widths=10, heights=10, name="r2",
                                 transform="display", clip_display=False)
        wire = self.plot.markers.to_wire_list()
        assert wire[0]["clip_display"] is False

    def test_add_arrows_transform_axes(self):
        g = self.plot.add_arrows([[5, 5]], U=1, V=1, name="a", transform="axes")
        wire = self.plot.markers.to_wire_list()
        assert wire[0]["transform"] == "axes"

    def test_add_ellipses_transform_axes(self):
        g = self.plot.add_ellipses([[5, 5]], widths=4, heights=3, name="e",
                                   transform="axes")
        wire = self.plot.markers.to_wire_list()
        assert wire[0]["transform"] == "axes"

    def test_add_lines_transform_axes(self):
        g = self.plot.add_lines([[[0, 0], [1, 1]]], name="l", transform="axes")
        wire = self.plot.markers.to_wire_list()
        assert wire[0]["transform"] == "axes"

    def test_add_squares_transform_axes(self):
        g = self.plot.add_squares([[5, 5]], widths=4, name="s", transform="axes")
        wire = self.plot.markers.to_wire_list()
        assert wire[0]["transform"] == "axes"

    def test_add_polygons_transform_axes(self):
        verts = [[[0, 0], [1, 0], [0.5, 1]]]
        g = self.plot.add_polygons(verts, name="pg", transform="axes")
        wire = self.plot.markers.to_wire_list()
        assert wire[0]["transform"] == "axes"

    def test_default_transform_is_data(self):
        g = self.plot.add_texts([[5, 5]], ["hi"], name="t2")
        wire = self.plot.markers.to_wire_list()
        assert wire[0]["transform"] == "data"


# ---------------------------------------------------------------------------
# Plot1D add_* methods accept transform kwarg
# ---------------------------------------------------------------------------

class TestPlot1DTransformKwarg:

    def setup_method(self):
        self.plot = _make_plot1d()

    def test_add_vlines_transform_axes(self):
        self.plot.add_vlines([0.5], name="v", transform="axes")
        wire = self.plot.markers.to_wire_list()
        assert wire[0]["transform"] == "axes"

    def test_add_hlines_transform_axes(self):
        self.plot.add_hlines([0.5], name="h", transform="axes")
        wire = self.plot.markers.to_wire_list()
        assert wire[0]["transform"] == "axes"

    def test_add_texts_transform_axes(self):
        self.plot.add_texts([[0.05, 0.95]], ["label"], name="t",
                            transform="axes")
        wire = self.plot.markers.to_wire_list()
        assert wire[0]["transform"] == "axes"

    def test_default_transform_is_data(self):
        self.plot.add_vlines([0.5], name="v2")
        wire = self.plot.markers.to_wire_list()
        assert wire[0]["transform"] == "data"

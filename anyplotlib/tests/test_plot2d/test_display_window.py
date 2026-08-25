"""
tests/test_plot2d/test_display_window.py
========================================
``Plot2D.set_display_window`` — moving the contrast window WITHOUT re-quantising.

The distinction from ``set_clim`` is the whole point, so these pin it from both
sides: ``set_clim`` re-encodes the frame and collapses ``raw_*`` onto the new
band; ``set_display_window`` leaves the codes and the band alone and moves only
the window the LUT maps through.

That difference is what decides whether a SERIALISED figure can have a working
contrast control. A page saved after ``set_clim`` holds codes saturated outside
the band it was saved with, so widening in JS recovers nothing; quantised over a
wide band and windowed with ``set_display_window``, the same page can be
re-windowed either way with no Python behind it.
"""
from __future__ import annotations

import numpy as np

import anyplotlib as apl


def _plot(data=None):
    fig, ax = apl.subplots(1, 1)
    if data is None:
        data = np.arange(64, dtype=float).reshape(8, 8)
    return ax.imshow(data)


class TestWindowMoves:
    def test_it_sets_both_ends(self):
        p = _plot()
        p.set_display_window(10.0, 40.0)
        assert p._state["display_min"] == 10.0
        assert p._state["display_max"] == 40.0

    def test_either_end_alone_leaves_the_other(self):
        p = _plot()
        p.set_display_window(10.0, 40.0)
        p.set_display_window(vmax=25.0)
        assert p._state["display_min"] == 10.0
        assert p._state["display_max"] == 25.0

    def test_it_pushes_so_the_change_reaches_js(self):
        # The _push() contract: a mutation that does not push never appears.
        p = _plot()
        seen = []
        p._push = lambda *a, **k: seen.append(1)
        p.set_display_window(1.0, 2.0)
        assert seen, "set_display_window did not push"


class TestPixelsStayPut:
    """The defining property. If the codes move, this is just a slow set_clim."""

    def test_the_encoded_pixels_are_untouched(self):
        p = _plot()
        before = p._state["image_b64"]
        p.set_display_window(10.0, 40.0)
        assert p._state["image_b64"] == before

    def test_the_quantisation_band_is_untouched(self):
        p = _plot()
        raw_before = (p._state["raw_min"], p._state["raw_max"])
        p.set_display_window(10.0, 40.0)
        assert (p._state["raw_min"], p._state["raw_max"]) == raw_before

    def test_set_clim_by_contrast_re_encodes_and_collapses_the_band(self):
        # The counterpart, asserted here so the pair cannot silently converge.
        p = _plot()
        before = p._state["image_b64"]
        p.set_clim(10.0, 40.0)
        assert p._state["image_b64"] != before
        assert p._state["raw_min"] == p._state["display_min"] == 10.0
        assert p._state["raw_max"] == p._state["display_max"] == 40.0


class TestHeadroomForASerialisedFigure:
    def test_a_wide_band_keeps_room_to_window_in_both_directions(self):
        # Quantise over the full range, then narrow: the codes still span the
        # whole range, so a reader can widen back out. This is exactly what an
        # exported page needs and what set_clim cannot give it.
        data = np.arange(256, dtype=float).reshape(16, 16)
        fig, ax = apl.subplots(1, 1)
        p = ax.imshow(data, vmin=0.0, vmax=255.0)

        p.set_display_window(100.0, 150.0)
        assert p._state["raw_min"] == 0.0 and p._state["raw_max"] == 255.0
        assert (p._state["display_min"], p._state["display_max"]) == (100.0, 150.0)

        # …and back out past the narrow window, still against the full band.
        p.set_display_window(0.0, 255.0)
        assert (p._state["display_min"], p._state["display_max"]) == (0.0, 255.0)
        assert p._state["raw_min"] == 0.0 and p._state["raw_max"] == 255.0

    def test_set_clim_first_would_have_thrown_that_away(self):
        data = np.arange(256, dtype=float).reshape(16, 16)
        fig, ax = apl.subplots(1, 1)
        p = ax.imshow(data, vmin=0.0, vmax=255.0)

        p.set_clim(100.0, 150.0)
        # Everything outside 100–150 is saturated in the codes now, so the band
        # a serialised page could re-window within has collapsed to the window.
        assert p._state["raw_min"] == 100.0 and p._state["raw_max"] == 150.0


class TestRgbAndTile:
    def test_an_rgb_frame_windows_the_same_way(self):
        rgb = np.zeros((8, 8, 3), np.uint8)
        fig, ax = apl.subplots(1, 1)
        p = ax.imshow(rgb)
        p.set_display_window(0.2, 0.8)
        assert (p._state["display_min"], p._state["display_max"]) == (0.2, 0.8)

    def test_it_matches_what_set_clim_already_does_in_tile_mode(self):
        # set_clim's tile branch is this method's behaviour, inlined. Pin that
        # they agree so the two cannot drift apart.
        data = np.arange(256, dtype=float).reshape(16, 16)
        fig, ax = apl.subplots(1, 1)
        p = ax.imshow(data, vmin=0.0, vmax=255.0)
        p._tile_on = True
        before = p._state["image_b64"]

        p.set_clim(60.0, 90.0)
        via_clim = (p._state["display_min"], p._state["display_max"],
                    p._state["raw_min"], p._state["raw_max"],
                    p._state["image_b64"] == before)

        p._tile_on = False
        p.set_display_window(60.0, 90.0)
        via_window = (p._state["display_min"], p._state["display_max"],
                      p._state["raw_min"], p._state["raw_max"],
                      p._state["image_b64"] == before)
        assert via_clim == via_window

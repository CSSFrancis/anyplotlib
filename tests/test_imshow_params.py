"""
tests/test_imshow_params.py
============================
Tests for the new cmap, vmin, vmax, and origin parameters on Axes.imshow().
"""
import base64
import numpy as np
import pytest
import anyplotlib as apl


# 4×4 ramp: values 0..15 (row 0 = [0,1,2,3], row 3 = [12,13,14,15])
DATA = np.arange(16, dtype=float).reshape(4, 4)
X    = np.array([1.0, 2.0, 3.0, 4.0])
Y    = np.array([10.0, 20.0, 30.0, 40.0])


def _decoded(v):
    """Return the stored uint8 image as a (H, W) array."""
    raw = base64.b64decode(v._state["image_b64"])
    return np.frombuffer(raw, dtype=np.uint8).reshape(
        v._state["image_height"], v._state["image_width"]
    )


# ── cmap ─────────────────────────────────────────────────────────────────────

class TestCmap:
    def test_default_cmap_is_gray(self):
        fig, ax = apl.subplots()
        v = ax.imshow(DATA)
        assert v._state["colormap_name"] == "gray"

    def test_cmap_sets_colormap_name(self):
        fig, ax = apl.subplots()
        v = ax.imshow(DATA, cmap="viridis")
        assert v._state["colormap_name"] == "viridis"

    def test_cmap_builds_lut(self):
        fig, ax = apl.subplots()
        v = ax.imshow(DATA, cmap="inferno")
        lut = v._state["colormap_data"]
        assert len(lut) == 256
        assert len(lut[0]) == 3   # [r, g, b]

    def test_cmap_none_uses_gray(self):
        fig, ax = apl.subplots()
        v = ax.imshow(DATA, cmap=None)
        assert v._state["colormap_name"] == "gray"


# ── vmin / vmax ───────────────────────────────────────────────────────────────

class TestVminVmax:
    def test_default_uses_data_range(self):
        fig, ax = apl.subplots()
        v = ax.imshow(DATA)
        assert v._state["display_min"] == pytest.approx(0.0)
        assert v._state["display_max"] == pytest.approx(15.0)

    def test_vmin_sets_display_min(self):
        fig, ax = apl.subplots()
        v = ax.imshow(DATA, vmin=3.0)
        assert v._state["display_min"] == pytest.approx(3.0)
        assert v._state["display_max"] == pytest.approx(15.0)  # unchanged

    def test_vmax_sets_display_max(self):
        fig, ax = apl.subplots()
        v = ax.imshow(DATA, vmax=12.0)
        assert v._state["display_min"] == pytest.approx(0.0)   # unchanged
        assert v._state["display_max"] == pytest.approx(12.0)

    def test_vmin_vmax_together(self):
        fig, ax = apl.subplots()
        v = ax.imshow(DATA, vmin=3.0, vmax=12.0)
        assert v._state["display_min"] == pytest.approx(3.0)
        assert v._state["display_max"] == pytest.approx(12.0)

    def test_raw_range_unaffected_by_vmin_vmax(self):
        """raw_min/raw_max always reflect the actual data range."""
        fig, ax = apl.subplots()
        v = ax.imshow(DATA, vmin=3.0, vmax=12.0)
        assert v._state["raw_min"] == pytest.approx(0.0)
        assert v._state["raw_max"] == pytest.approx(15.0)

    def test_set_clim_still_works_after_construction(self):
        fig, ax = apl.subplots()
        v = ax.imshow(DATA, vmin=3.0, vmax=12.0)
        v.set_clim(vmin=1.0, vmax=14.0)
        assert v._state["display_min"] == pytest.approx(1.0)
        assert v._state["display_max"] == pytest.approx(14.0)


# ── origin ────────────────────────────────────────────────────────────────────

class TestOrigin:
    def test_upper_is_default(self):
        fig, ax = apl.subplots()
        v = ax.imshow(DATA)
        assert v._origin == "upper"

    def test_upper_keeps_y_axis_order(self):
        fig, ax = apl.subplots()
        v = ax.imshow(DATA, axes=[X, Y], origin="upper")
        assert v._state["y_axis"][0]  == pytest.approx(10.0)  # top of image
        assert v._state["y_axis"][-1] == pytest.approx(40.0)  # bottom

    def test_upper_row0_at_top(self):
        """With origin='upper', row 0 of data (min values) is stored first."""
        fig, ax = apl.subplots()
        v = ax.imshow(DATA, origin="upper")
        stored = _decoded(v)
        assert stored[0, 0] == 0    # row 0, col 0 → value 0 → uint8 min

    def test_lower_reverses_y_axis(self):
        fig, ax = apl.subplots()
        v = ax.imshow(DATA, axes=[X, Y], origin="lower")
        assert v._state["y_axis"][0]  == pytest.approx(40.0)  # max at top
        assert v._state["y_axis"][-1] == pytest.approx(10.0)  # min at bottom

    def test_lower_default_y_axis_reversed(self):
        """Without explicit axes, origin='lower' still reverses default y."""
        fig, ax = apl.subplots()
        v = ax.imshow(DATA, origin="lower")
        assert v._state["y_axis"][0] > v._state["y_axis"][-1]

    def test_lower_flips_data(self):
        """With origin='lower', row 0 of original data appears at the bottom."""
        fig, ax = apl.subplots()
        v = ax.imshow(DATA, origin="lower")
        stored = _decoded(v)
        # Original row 0 (all small values) is now at the bottom after flip.
        # The max value (15) ends up at stored[0, -1] after flipud, and the
        # min value (0) ends up at stored[-1, 0], so check row extremes.
        assert stored[0, :].max() == 255   # top row contains the global max
        assert stored[-1, :].min() == 0    # bottom row contains the global min

    def test_lower_set_data_reapplies_flip(self):
        """set_data() with origin='lower' automatically re-flips new data."""
        fig, ax = apl.subplots()
        v = ax.imshow(DATA, origin="lower")
        v.set_data(DATA)
        stored = _decoded(v)
        assert stored[0, :].max() == 255
        assert stored[-1, :].min() == 0

    def test_lower_set_data_reverses_new_y_axis(self):
        fig, ax = apl.subplots()
        v = ax.imshow(DATA, origin="lower")
        v.set_data(DATA, y_axis=Y)
        assert v._state["y_axis"][0]  == pytest.approx(40.0)
        assert v._state["y_axis"][-1] == pytest.approx(10.0)

    def test_invalid_origin_raises(self):
        fig, ax = apl.subplots()
        # 'lower' is a valid origin — must not raise
        v = ax.imshow(DATA, origin="lower")
        # An unrecognised string must raise ValueError
        with pytest.raises(ValueError):
            ax.imshow(DATA, origin="bottom")


# ── combined ─────────────────────────────────────────────────────────────────

class TestCombined:
    def test_all_params_together(self):
        fig, ax = apl.subplots()
        v = ax.imshow(DATA, cmap="inferno", vmin=2.0, vmax=13.0,
                      origin="lower", axes=[X, Y])
        assert v._state["colormap_name"] == "inferno"
        assert v._state["display_min"]   == pytest.approx(2.0)
        assert v._state["display_max"]   == pytest.approx(13.0)
        assert v._state["y_axis"][0]     == pytest.approx(40.0)  # reversed
        stored = _decoded(v)
        assert stored[0, :].max() == 255   # flipped: top row has max value


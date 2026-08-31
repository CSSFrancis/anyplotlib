"""NumpyTileBackend + the TileBackend protocol — the pluggable sampling seam."""
import numpy as np
import pytest

from anyplotlib.plot2d._tile_backend import (
    NumpyTileBackend, TileBackend, _acc_dtype, as_tile_backend,
)


class TestNumpyBackendGeometry:
    def test_reports_shape_dtype_origin_extent(self):
        a = np.zeros((600, 800), np.uint16)
        b = NumpyTileBackend(a, extent=(0.0, 8.0, 0.0, 6.0), origin="lower")
        assert b.full_shape == (600, 800)
        assert b.dtype == np.uint16
        assert b.origin == "lower"
        assert b.extent() == (0.0, 8.0, 0.0, 6.0)

    def test_default_extent_is_none(self):
        assert NumpyTileBackend(np.zeros((4, 4))).extent() is None

    def test_rejects_non_2d(self):
        with pytest.raises(ValueError):
            NumpyTileBackend(np.zeros((4, 4, 4)))

    def test_satisfies_protocol(self):
        assert isinstance(NumpyTileBackend(np.zeros((4, 4))), TileBackend)


class TestSampleMean:
    def test_full_region_mean_matches_block_mean(self):
        a = np.random.RandomState(0).randint(0, 4000, (64, 64)).astype(np.uint16)
        b = NumpyTileBackend(a)
        out = b.sample(0, 64, 0, 64, 16, 16, "mean")
        assert out.shape == (16, 16)
        ref = a.astype(np.float32).reshape(16, 4, 16, 4).mean(axis=(1, 3))
        np.testing.assert_allclose(out, ref, rtol=1e-4)

    def test_mean_preserves_hot_pixel_energy(self):
        a = np.zeros((16, 16), np.float32)
        a[5, 5] = 1600.0
        out = NumpyTileBackend(a).sample(0, 16, 0, 16, 4, 4, "mean")
        assert out.max() == pytest.approx(1600.0 / 16)   # spread, not dropped

    def test_subregion(self):
        a = np.arange(64 * 64, dtype=np.float32).reshape(64, 64)
        out = NumpyTileBackend(a).sample(16, 48, 16, 48, 8, 8, "mean")
        assert out.shape == (8, 8)
        ref = a[16:48, 16:48].reshape(8, 4, 8, 4).mean(axis=(1, 3))
        np.testing.assert_allclose(out, ref, rtol=1e-4)


class TestSampleDtypes:
    """A box mean must mean the same thing in every dtype the caller can hand us.

    The accumulator used to be a blanket ``uint32`` for anything integral, which
    wrapped every negative value and overflowed anything wider than 16 bits."""

    @pytest.mark.parametrize("dt", [np.int8, np.int16, np.int32, np.int64])
    @pytest.mark.parametrize("shape,out", [((64, 64), 16), ((63, 65), 16)])
    def test_negative_integers_survive_the_mean(self, dt, shape, out):
        # Both grids on purpose: (64, 64) takes the divisible reshape-reduce,
        # (63, 65) the ragged strided accumulate. uint32 got the first one silently
        # wrong (-100 read as ~4.29e9) and made the second raise.
        a = np.full(shape, -100, dt)
        got = NumpyTileBackend(a).sample(0, shape[1], 0, shape[0], out, out, "mean")
        np.testing.assert_allclose(got, -100.0)

    def test_mixed_sign_block_averages_to_zero(self):
        a = np.tile(np.array([-50, 50], np.int16), (32, 32))
        out = NumpyTileBackend(a).sample(0, 64, 0, 64, 16, 16, "mean")
        np.testing.assert_allclose(out, 0.0, atol=1e-5)

    @pytest.mark.parametrize("dt,val", [(np.int32, 2_000_000),
                                        (np.uint32, 4_000_000_000),
                                        (np.int64, 3_000_000_000),
                                        (np.uint64, 5_000_000_000)])
    def test_wide_integers_do_not_overflow(self, dt, val):
        # 64 terms of these all exceed uint32; the sum has to widen, not wrap.
        a = np.full((64, 64), val, dt)
        out = NumpyTileBackend(a).sample(0, 64, 0, 64, 8, 8, "mean")
        np.testing.assert_allclose(out, float(val), rtol=1e-6)

    def test_bool_mean_is_the_fraction_set(self):
        a = np.zeros((16, 16), bool)
        a[::2] = True                          # every other row
        out = NumpyTileBackend(a).sample(0, 16, 0, 16, 4, 4, "mean")
        np.testing.assert_allclose(out, 0.5)

    @pytest.mark.parametrize("dt", [np.float16, np.float32, np.float64,
                                    np.uint8, np.uint16, np.int16, np.int64, np.bool_])
    @pytest.mark.parametrize("shape,out", [((64, 64), 16), ((128, 128), 32)])
    def test_mean_matches_an_exact_block_mean(self, dt, shape, out):
        rs = np.random.RandomState(0)
        h, w = shape
        if dt is np.bool_:
            a = rs.rand(h, w) > 0.5
        elif np.issubdtype(dt, np.integer):
            info = np.iinfo(dt)
            a = rs.randint(max(info.min, -20000), min(info.max, 20000), shape).astype(dt)
        else:
            a = ((rs.rand(h, w) - 0.5) * 2000).astype(dt)
        got = NumpyTileBackend(a).sample(0, w, 0, h, out, out, "mean")
        sy, sx = h // out, w // out
        ref = a.astype(np.float64).reshape(out, sy, out, sx).mean(axis=(1, 3))
        # A mixed-sign block can average to ~0, so the bound that matters is
        # absolute and set by the SOURCE magnitude, not by the mean it lands on.
        np.testing.assert_allclose(got, ref, rtol=2e-6,
                                   atol=1e-5 * float(np.abs(a).max()))

    def test_float64_input_is_not_narrowed_before_the_sum(self):
        # The mean is returned as float32 either way, so the extra mantissa is not
        # observable — the RANGE is. 16 terms of 1e37 overflow a float32
        # accumulator to inf; the mean itself is an ordinary float32.
        a = np.full((64, 64), 1e37, np.float64)
        out = NumpyTileBackend(a).sample(0, 64, 0, 64, 16, 16, "mean")
        assert np.isfinite(out).all()
        np.testing.assert_allclose(out, 1e37, rtol=1e-6)

    @pytest.mark.parametrize("dt", [np.uint16, np.int16, np.float32])
    def test_ragged_grid_averages_over_valid_pixels_only(self, dt):
        # 100 // 32 = 3, so the last block of each axis is partial: the count has to
        # follow the block, not assume a full 3x3.
        a = np.arange(100 * 100, dtype=np.float64).reshape(100, 100) % 1000
        a = a.astype(dt)
        got = NumpyTileBackend(a).sample(0, 100, 0, 100, 32, 32, "mean")
        ref = np.array([[a[i * 3:(i + 1) * 3, j * 3:(j + 1) * 3].astype(np.float64).mean()
                         for j in range(34)] for i in range(34)])
        yi = (np.arange(32) * 34 // 32).clip(0, 33)
        np.testing.assert_allclose(got, ref[yi][:, yi], rtol=2e-6)


class TestAccumulatorDtype:
    @pytest.mark.parametrize("dt,expect", [
        (np.uint8, np.uint32), (np.uint16, np.uint32), (np.bool_, np.uint32),
        (np.int8, np.int32), (np.int16, np.int32),
        (np.float16, np.float32), (np.float32, np.float32), (np.float64, np.float64),
    ])
    def test_narrow_dtypes_keep_a_cheap_same_signedness_accumulator(self, dt, expect):
        assert _acc_dtype(np.dtype(dt), 64) == np.dtype(expect)

    def test_accumulator_widens_with_the_block(self):
        # uint16 x 64 fits uint32; uint16 x 2**24 does not.
        assert _acc_dtype(np.dtype(np.uint16), 64) == np.dtype(np.uint32)
        assert _acc_dtype(np.dtype(np.uint16), 2 ** 24) == np.dtype(np.uint64)

    def test_signedness_is_preserved(self):
        for dt in (np.int8, np.int16, np.int32, np.int64):
            assert _acc_dtype(np.dtype(dt), 64).kind in "if"


class TestSampleSubsampleMax:
    def test_subsample_drops_between_grid(self):
        a = np.zeros((16, 16), np.float32)
        a[5, 5] = 100.0                       # off the /4 grid
        out = NumpyTileBackend(a).sample(0, 16, 0, 16, 4, 4, "subsample")
        assert out.max() == 0.0               # dropped by nearest sampling

    def test_max_keeps_the_peak(self):
        a = np.zeros((16, 16), np.float32)
        a[5, 5] = 100.0
        out = NumpyTileBackend(a).sample(0, 16, 0, 16, 4, 4, "max")
        assert out.max() == 100.0             # block max keeps the peak


class TestSampleShapesAndClamp:
    def test_out_shape_is_exact(self):
        a = np.zeros((100, 137), np.float32)
        for (ow, oh) in [(50, 50), (33, 41), (200, 10)]:
            out = NumpyTileBackend(a).sample(0, 137, 0, 100, ow, oh, "mean")
            assert out.shape == (oh, ow)

    def test_upsample_when_out_bigger_than_region(self):
        a = np.arange(16, dtype=np.float32).reshape(4, 4)
        out = NumpyTileBackend(a).sample(0, 4, 0, 4, 8, 8, "mean")
        assert out.shape == (8, 8)            # nearest upsample

    def test_region_is_clamped(self):
        a = np.ones((32, 32), np.float32)
        out = NumpyTileBackend(a).sample(-10, 999, -10, 999, 16, 16, "mean")
        assert out.shape == (16, 16)          # clamped to [0, 32], no crash


class TestSetArray:
    def test_set_array_swaps_source(self):
        b = NumpyTileBackend(np.zeros((32, 32), np.float32))
        b.set_array(np.full((32, 32), 7.0, np.float32))
        assert b.sample(0, 32, 0, 32, 4, 4, "mean").max() == pytest.approx(7.0)


class TestAsTileBackend:
    def test_wraps_ndarray(self):
        b = as_tile_backend(np.zeros((8, 8)))
        assert isinstance(b, NumpyTileBackend)

    def test_passes_backend_through(self):
        inner = NumpyTileBackend(np.zeros((8, 8)))
        assert as_tile_backend(inner) is inner

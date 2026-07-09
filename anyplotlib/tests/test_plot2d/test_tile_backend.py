"""NumpyTileBackend + the TileBackend protocol — the pluggable sampling seam."""
import numpy as np
import pytest

from anyplotlib.plot2d._tile_backend import (
    NumpyTileBackend, TileBackend, as_tile_backend,
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

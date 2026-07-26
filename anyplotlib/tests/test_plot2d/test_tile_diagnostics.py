"""The [TILEDBG] diagnostics must cost NOTHING unless debug logging is on.

``_on_view_changed_internal`` reports the distinct-value counts of the backend's
raw native crop and of the sampled tile, which is genuinely useful (it catches a
backend that hands back a downsample instead of native pixels). But both are
``np.unique`` — full sorts — and they were passed as ARGUMENTS to ``_TLOG.debug``.
Lazy %-formatting does not help there: the arguments are evaluated before the
call, so every pan/zoom paid for them at any log level. Measured on a 4096² frame
with VIEW_OVERFETCH=2.0, where the over-fetched crop is the whole image: 259 ms
per pan for the raw crop plus 12 ms for the tile.

These tests pin the GUARD, not the message text.
"""
from __future__ import annotations

import logging

import numpy as np

import anyplotlib as apl
from anyplotlib.callbacks import Event
import anyplotlib.plot2d._plot2d as _p2


TILE_LOG = "anyplotlib.tile"


def _tiled_plot(edge=1024):
    p = apl.subplots(1, 1)[1].imshow(np.zeros((10, 10), np.float32))
    p.set_data(np.random.RandomState(0).rand(edge, edge).astype(np.float32),
               clim=(0, 1), tile=True)
    return p


def _pan(p, zoom=4.0, cx=0.5, cy=0.5):
    p.callbacks.fire(Event("view_changed", zoom=zoom, center_x=cx, center_y=cy,
                           display_width=800, display_height=800))


class _CountUnique:
    """Count np.unique calls without changing what it returns."""

    def __init__(self, monkeypatch):
        self.n = 0
        real = np.unique
        def counting(*a, **k):
            self.n += 1
            return real(*a, **k)
        monkeypatch.setattr(_p2.np, "unique", counting)


class TestFetchDiagnosticIsGuarded:
    def test_pan_does_no_sorting_at_info_level(self, monkeypatch):
        logger = logging.getLogger(TILE_LOG)
        monkeypatch.setattr(logger, "level", logging.INFO)
        p = _tiled_plot()
        counter = _CountUnique(monkeypatch)      # after setup, so only the pan counts
        _pan(p)
        assert p._state["detail_region"], "the detail tile must still be fetched"
        assert counter.n == 0, (
            f"np.unique ran {counter.n}x on a pan with debug logging off — the "
            f"[TILEDBG] diagnostic is unguarded again (259 ms/pan on a 4096² frame)")

    def test_diagnostic_still_runs_at_debug_level(self, monkeypatch, caplog):
        logger = logging.getLogger(TILE_LOG)
        monkeypatch.setattr(logger, "level", logging.DEBUG)
        p = _tiled_plot()
        counter = _CountUnique(monkeypatch)
        with caplog.at_level(logging.DEBUG, logger=TILE_LOG):
            _pan(p)
        assert counter.n >= 1, "the distinct-value diagnostic must survive at DEBUG"
        assert any("view_changed FETCH" in r.message for r in caplog.records), \
            "the FETCH line itself must still be emitted at DEBUG"

    def test_tile_content_is_unchanged_by_the_guard(self, monkeypatch):
        """The guard must not alter what gets displayed — same region, same tile."""
        logger = logging.getLogger(TILE_LOG)
        p = _tiled_plot()
        monkeypatch.setattr(logger, "level", logging.DEBUG)
        _pan(p, zoom=4.0)
        dbg = (list(p._state["detail_region"]), p._state["detail_width"],
               p._state["detail_height"], p._state["detail_b64"])
        p2 = _tiled_plot()
        monkeypatch.setattr(logger, "level", logging.INFO)
        _pan(p2, zoom=4.0)
        quiet = (list(p2._state["detail_region"]), p2._state["detail_width"],
                 p2._state["detail_height"], p2._state["detail_b64"])
        assert dbg == quiet

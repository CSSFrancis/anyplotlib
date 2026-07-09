"""Rapid successive frame updates must always END on the LAST-arrived frame.

Regression guard for the movie-playback / fast-navigator-scrub freeze class of
bug: a live consumer pushes a NEW image frame on every tick (20 fps playback,
or a fast drag), and the display must converge on the frame that arrived LAST.
Frame skipping / newest-wins coalescing is fine — dropping intermediate frames
is expected — but the render caches (GPU texture ``bytesKey`` / Canvas2D
``blitCache.bytesKey``) must NOT latch a stale frame and skip the final
re-upload. A too-weak content key (e.g. a 4-byte sampled fingerprint that
collides across frames) would freeze the display on an early frame even though
byte-distinct frames kept arriving — exactly the reported freeze.

The scene is a moving BRIGHT VERTICAL BAND whose x-position encodes the frame
index (like ``load_test_data_movie``'s per-frame index band), so the rendered
band column tells us WHICH frame is on screen. We push all N frames rapid-fire
via ``requestAnimationFrame`` (no per-frame settle — the coalescing regime) and
then assert the on-screen band sits at the LAST frame's column.

Runs on real WebGPU (``gpu=True``) and on the Canvas2D reference (``gpu=False``)
in the same browser, and covers both the PLAIN large-image path and the TILE
path (>1024 edge → overview + detail), since both have their own dedup key.
"""
from __future__ import annotations

import json

import numpy as np
import pytest

import anyplotlib as apl
from anyplotlib.tests._png_utils import decode_png

FIG_W, FIG_H = 400, 300
N_FRAMES = 8


def _band_frame(n: int, frame_idx: int, n_frames: int) -> np.ndarray:
    """A dim gradient with a BRIGHT vertical band whose column encodes the frame
    index — same idea as the SpyDE synthetic movie's per-frame index band."""
    yy, xx = np.mgrid[0:n, 0:n].astype(np.float32)
    img = (xx / n) * 0.15 + (yy / n) * 0.15
    bw = max(2, n // 16)
    x0 = int((frame_idx + 1) * n / (n_frames + 2))
    img[:, x0:x0 + bw] = 1.0
    return img


def _band_col_frac(frame_idx: int, n_frames: int) -> float:
    """The band's LEFT-edge x-position as a fraction of image width (matches
    ``_band_frame``'s ``x0``)."""
    return (frame_idx + 1) / (n_frames + 2)


def _frames_state(n: int, *, gpu: bool, tile) -> tuple[str, list[str]]:
    """Build a plot and return (panel_id, [state_json per frame]).

    Each frame's state JSON is captured from ``to_state_dict()`` after a
    ``set_data`` of that frame (standalone host → real base64 pixels), so the
    browser can push them one-by-one with no Python kernel in the loop.
    """
    fig, ax = apl.subplots(1, 1, figsize=(FIG_W, FIG_H))
    p = ax.imshow(_band_frame(n, 0, N_FRAMES), cmap="viridis",
                  vmin=0.0, vmax=1.0, gpu=gpu, tile=tile)
    states = []
    for i in range(N_FRAMES):
        p.set_data(_band_frame(n, i, N_FRAMES), clim=(0.0, 1.0))
        states.append(json.dumps(p.resolve_pixel_tokens(p.to_state_dict())))
    return fig, p, states


def _push_frames_rapid(page, panel_id: str, states: list[str]) -> None:
    """Push every state JSON into ``panel_<id>_json`` back-to-back, one per
    ``requestAnimationFrame`` (the rapid-update / coalescing regime), then let
    the final frame settle with two more rAFs."""
    page.evaluate(
        """([pid, states]) => new Promise((resolve) => {
            const key = 'panel_' + pid + '_json';
            let i = 0;
            function step() {
                if (i >= states.length) {
                    // let the LAST frame commit (device queue + compositor)
                    requestAnimationFrame(() =>
                      requestAnimationFrame(() =>
                        requestAnimationFrame(resolve)));
                    return;
                }
                window._aplModel.set(key, states[i]);
                i++;
                requestAnimationFrame(step);
            }
            requestAnimationFrame(step);
        })""",
        [panel_id, states],
    )


def _band_center_frac(page) -> float:
    """Screenshot ``#widget-root``, find the brightest column across the plot
    area, and return its x-position as a fraction of the plot width."""
    arr = decode_png(page.locator("#widget-root").screenshot())
    h, w = arr.shape[:2]
    # Green channel peaks for viridis' bright end (the band value 1.0 → yellow).
    col_bright = arr[:, :, 1].astype(np.float32).mean(axis=0)
    # Ignore the axis gutter on the left/right by trimming a margin.
    m = int(w * 0.16)
    inner = col_bright[m:w - m]
    peak = int(np.argmax(inner)) + m
    return peak / float(w)


def _run(page_open, *, gpu: bool, tile, n: int):
    # Reference: the LAST frame pushed ALONE and allowed to settle — this is the
    # ground truth for "the last frame is on screen". Calibration-free (same
    # padding/letterbox as the rapid-push page), so it isolates the freeze.
    fig_ref, plot_ref, states_ref = _frames_state(n, gpu=gpu, tile=tile)
    page_ref = page_open(fig_ref, expect_gpu=gpu)
    _push_frames_rapid(page_ref, plot_ref._id, states_ref[-1:])  # last frame only
    ref_frac = _band_center_frac(page_ref)

    # An EARLY frame alone — the position a stale-frame freeze would show.
    fig_e, plot_e, states_e = _frames_state(n, gpu=gpu, tile=tile)
    page_e = page_open(fig_e, expect_gpu=gpu)
    _push_frames_rapid(page_e, plot_e._id, states_e[:1])         # first frame only
    early_frac = _band_center_frac(page_e)

    # The gap between the first and last band positions must be resolvable — the
    # scene is built that way; guard the guard.
    assert abs(ref_frac - early_frac) > 0.15, (
        f"gpu={gpu} tile={tile}: first ({early_frac:.3f}) and last "
        f"({ref_frac:.3f}) band positions too close — bad scene")

    # The real test: push ALL frames rapid-fire (coalescing regime) and confirm
    # the band lands at the LAST frame's column, NOT a stale earlier one.
    fig, plot, states = _frames_state(n, gpu=gpu, tile=tile)
    page = page_open(fig, expect_gpu=gpu)
    _push_frames_rapid(page, plot._id, states)
    got = _band_center_frac(page)

    d_last = abs(got - ref_frac)
    d_early = abs(got - early_frac)
    assert d_last < d_early and d_last < 0.05, (
        f"gpu={gpu} tile={tile}: after rapid push the band is at {got:.3f} "
        f"(last={ref_frac:.3f}, first={early_frac:.3f}) — display froze on a "
        f"stale frame instead of converging on the LAST frame")


class TestRapidFrameUpdate:
    """The last pushed frame must always be the one rendered."""

    def test_plain_gpu(self, gpu_interact_page):
        _run(gpu_interact_page, gpu=True, tile=False, n=1200)

    def test_plain_cpu(self, gpu_interact_page):
        _run(gpu_interact_page, gpu=False, tile=False, n=1200)

    def test_tile_gpu(self, gpu_interact_page):
        _run(gpu_interact_page, gpu=True, tile=True, n=1400)

    def test_tile_cpu(self, gpu_interact_page):
        _run(gpu_interact_page, gpu=False, tile=True, n=1400)

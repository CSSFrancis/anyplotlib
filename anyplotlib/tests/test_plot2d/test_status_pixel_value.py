"""Hover readout: the 2-D status bar names the VALUE of the pixel under the
cursor next to its physical + pixel coordinates.

Three precision tiers, all covered here:

* **Invertible codes** — an integral source whose range fits the 256 codes is
  reconstructed EXACTLY from the bytes the renderer already holds, no kernel
  needed (``raw_is_int`` / ``_codeToValue``).
* **Quantised estimate** — anything wider resolves to ``range/255``; the
  assertions allow exactly that one step and no more.
* **Exact probe** — on a dwell the renderer asks Python for the true value and
  swaps it in (``value_probe`` → ``Plot2D._answer_value_probe``).  The test pages have
  no live kernel, so the JS half is driven by injecting the answer into the panel
  state and the Python half by dispatching the event directly.
"""
from __future__ import annotations

import json
import pathlib
import re
import tempfile

import numpy as np
import pytest

import anyplotlib as apl
from anyplotlib.tests.test_interactive._event_test_utils import (
    _collect_events, _get_events,
)

IMG = 64
FIG = 320

_OVERLAY = "[...document.querySelectorAll('canvas')].find(x => x.style.zIndex === '5')"


def _hover_pixel(page, plot, ix, iy):
    """Move the mouse to the centre of logical image pixel (ix, iy); return the
    status-bar text the renderer wrote (or None when it stayed hidden)."""
    pt = page.evaluate(
        "([pid, ix, iy]) => globalThis.__apl_imgToCanvas(pid, ix, iy)",
        [plot._id, ix, iy])
    assert pt, "__apl_imgToCanvas returned no point — panel not a live 2-D panel?"
    box = page.evaluate(
        f"() => {{ const c = {_OVERLAY}; const r = c.getBoundingClientRect();"
        f"  return {{x: r.x, y: r.y}}; }}")
    page.mouse.move(box["x"] + pt[0], box["y"] + pt[1])
    page.wait_for_timeout(60)
    status = page.evaluate("(pid) => globalThis.__apl_statusText(pid)", plot._id)
    assert status is not None, "no status bar on the panel"
    return status["text"] if status["shown"] else None


def _value_of(text):
    """The number after ``v:`` in a status-bar line."""
    m = re.search(r"v:(-?[\d.]+(?:[eE][-+]?\d+)?)", text or "")
    assert m, f"no v:<value> in status text {text!r}"
    return float(m.group(1))


def _set_probe_answer(page, plot, col, row, value):
    """Inject the answer Python would push for a dwell probe (the test page has no
    kernel, so this stands in for the round trip)."""
    page.evaluate(
        """([pid, col, row, value]) => {
            const key = 'panel_' + pid + '_json';
            const st = JSON.parse(window._aplModel.get(key));
            st.probe_x = col; st.probe_y = row; st.probe_value = value;
            window._aplModel.set(key, JSON.stringify(st));
        }""", [plot._id, col, row, value])
    page.wait_for_timeout(60)


def _watch_readout(page):
    """Record every ``apl:readout`` payload the figure dispatches to its host."""
    page.evaluate("""() => {
        window._aplReadouts = [];
        document.addEventListener('apl:readout',
            (e) => window._aplReadouts.push(e.detail), true);
    }""")


def _readouts(page):
    return page.evaluate("() => window._aplReadouts")


class TestScalarPixelValue:
    def test_value_shown_with_pixel_and_physical_coords(self, interact_page):
        """x/y in axis units, [ix, iy] in pixels, and now v:<value> — all three."""
        data = np.arange(IMG * IMG, dtype=np.float32).reshape(IMG, IMG)
        fig, ax = apl.subplots(1, 1, figsize=(FIG, FIG))
        plot = ax.imshow(data, cmap="gray", gpu=False, units="nm",
                         axes=[np.linspace(0, 6.3, IMG), np.linspace(0, 6.3, IMG)])
        page = interact_page(fig)

        step = (float(data.max()) - float(data.min())) / 255.0
        for ix, iy in [(10, 20), (0, 0), (IMG - 1, IMG - 1), (33, 5)]:
            text = _hover_pixel(page, plot, ix, iy)
            assert text, f"status bar hidden while hovering pixel ({ix}, {iy})"
            assert f"[{ix}, {iy}]" in text, f"pixel coords wrong: {text!r}"
            assert "nm" in text, f"physical coords/units missing: {text!r}"
            expected = float(data[iy, ix])
            got = _value_of(text)
            assert abs(got - expected) <= step, (
                f"pixel ({ix}, {iy}): status shows v:{got}, data is {expected} "
                f"(one quantisation step is {step:.3f}) — text {text!r}")

    def test_value_shown_without_explicit_axes(self, interact_page):
        """No axis arrays given (coords fall back to pixel indices in "px") — the
        value rides along the same way."""
        data = np.linspace(0.0, 1.0, IMG * IMG, dtype=np.float32).reshape(IMG, IMG)
        fig, ax = apl.subplots(1, 1, figsize=(FIG, FIG))
        plot = ax.imshow(data, cmap="gray", gpu=False)
        page = interact_page(fig)

        text = _hover_pixel(page, plot, 12, 40)
        assert text and "[12, 40]" in text and "px" in text, f"coords wrong: {text!r}"
        assert abs(_value_of(text) - float(data[40, 12])) <= 1.0 / 255.0, text

    def test_constant_image_reads_exact_value(self, interact_page):
        """raw_min == raw_max (a flat frame): every code is that one value, exactly."""
        fig, ax = apl.subplots(1, 1, figsize=(FIG, FIG))
        plot = ax.imshow(np.full((32, 32), 7.5, np.float32), cmap="gray", gpu=False)
        page = interact_page(fig)

        text = _hover_pixel(page, plot, 16, 16)
        assert _value_of(text) == 7.5, text

    def test_reports_data_not_the_display_window(self, interact_page):
        """vmin/vmax clip the COLORMAP, not the data: a pixel far above vmax still
        reads its own value (the codes span the data range, the LUT does the
        clipping) — the readout is a data probe, not a colour probe."""
        data = np.zeros((32, 32), np.float32)
        data[8, 8] = 100.0                      # saturates the display window
        fig, ax = apl.subplots(1, 1, figsize=(FIG, FIG))
        plot = ax.imshow(data, cmap="gray", vmin=0.0, vmax=2.0, gpu=False)
        page = interact_page(fig)

        assert _value_of(_hover_pixel(page, plot, 8, 8)) == 100.0
        assert _value_of(_hover_pixel(page, plot, 0, 0)) == 0.0

    def test_set_data_clim_saturates_the_readout(self, interact_page):
        """``set_data(clim=…)`` quantises over the clim itself (so the signal keeps
        all 256 codes instead of a hot pixel stealing them) — outliers therefore
        saturate the readout at the band edge, which is the honest report of what
        crossed the wire."""
        data = np.zeros((32, 32), np.float32)
        data[8, 8] = 100.0
        fig, ax = apl.subplots(1, 1, figsize=(FIG, FIG))
        plot = ax.imshow(data, cmap="gray", gpu=False)
        plot.set_data(data, clim=(0.0, 2.0))
        page = interact_page(fig)

        assert _value_of(_hover_pixel(page, plot, 8, 8)) == 2.0, "must clamp to the clim"

    def test_value_hidden_off_image(self, interact_page):
        """Cursor in the letterbox margin beside the image → the bar hides, value
        and all (a wide image in a square panel leaves margin inside the canvas)."""
        fig, ax = apl.subplots(1, 1, figsize=(FIG, FIG))
        plot = ax.imshow(np.zeros((32, IMG), np.float32), cmap="gray", gpu=False)
        page = interact_page(fig)

        assert _hover_pixel(page, plot, 32, 16) is not None      # on the image
        assert _hover_pixel(page, plot, 32, -8) is None          # above it


class TestMeshPixelValue:
    def test_pcolormesh_cell_value(self, interact_page):
        """Mesh panels share the 2-D hover handler — the readout names the cell
        value under the cursor (from the resampled display grid it draws)."""
        data = np.arange(16 * 16, dtype=np.float32).reshape(16, 16)
        fig, ax = apl.subplots(1, 1, figsize=(FIG, FIG))
        plot = ax.pcolormesh(data, x_edges=np.arange(17.0),
                             y_edges=np.arange(17.0), units="keV")
        page = interact_page(fig)

        step = (float(data.max()) - float(data.min())) / 255.0
        text = _hover_pixel(page, plot, 5, 9)
        assert abs(_value_of(text) - float(data[9, 5])) <= step, text


class TestRgbPixelValue:
    def test_rgb_image_shows_channel_triplet(self, interact_page):
        """True-colour images have no scalar value — report the RGB channels."""
        rgb = np.zeros((16, 16, 3), np.uint8)
        rgb[:, :, 0] = 255                                  # pure red
        rgb[4, 6] = (10, 20, 30)                            # one known pixel
        fig, ax = apl.subplots(1, 1, figsize=(FIG, FIG))
        plot = ax.imshow(rgb, gpu=False)
        page = interact_page(fig)

        assert "rgb:255,0,0" in _hover_pixel(page, plot, 2, 2)
        assert "rgb:10,20,30" in _hover_pixel(page, plot, 6, 4)


class TestDetailTilePixelValue:
    def test_zoomed_readout_comes_from_the_detail_tile(self, interact_page):
        """Zoomed into a detail region, the screen shows the TILE's native pixels —
        so the readout must come from the tile too, not the coarser base."""
        fig, ax = apl.subplots(1, 1, figsize=(FIG, FIG))
        plot = ax.imshow(np.zeros((IMG, IMG), np.float32),
                         cmap="gray", vmin=0.0, vmax=1.0, gpu=False)
        # Base is all 0; the tile covering [16:48, 16:48] is all 1. (State must be
        # final before the page opens — the test page is a snapshot, no kernel.)
        plot.set_detail(np.ones((32, 32), np.float32), 16, 48, 16, 48)
        page = interact_page(fig)
        # zoom 2 centred → the visible window is exactly the tile region.
        page.evaluate("(pid) => globalThis.__apl_setZoom(pid, 2.0, 0.5, 0.5)", plot._id)
        page.wait_for_timeout(120)

        text = _hover_pixel(page, plot, 32, 32)
        assert abs(_value_of(text) - 1.0) <= 1.0 / 255.0, (
            f"zoomed readout ignored the detail tile (base value leaked): {text!r}")


class TestDetailBandState:
    """The tile's quantisation band travels with it — the renderer cannot
    reconstruct tile values without it, and it need not match the base band."""

    def test_set_detail_records_band(self):
        p = apl.subplots(1, 1)[1].imshow(np.zeros((64, 64), np.float32),
                                         vmin=0.0, vmax=2.0)
        p.set_detail(np.ones((32, 32), np.float32), 16, 48, 16, 48)
        assert p._state["detail_min"] == 0.0 and p._state["detail_max"] == 2.0

    def test_clearing_detail_clears_band(self):
        p = apl.subplots(1, 1)[1].imshow(np.zeros((64, 64), np.float32),
                                         vmin=0.0, vmax=2.0)
        p.set_detail(np.ones((32, 32), np.float32), 16, 48, 16, 48)
        p.set_detail(None)
        assert p._state["detail_min"] is None and p._state["detail_max"] is None

    def test_new_base_frame_clears_band(self):
        p = apl.subplots(1, 1)[1].imshow(np.zeros((64, 64), np.float32),
                                         vmin=0.0, vmax=2.0)
        p.set_detail(np.ones((32, 32), np.float32), 16, 48, 16, 48)
        p.set_data(np.zeros((64, 64), np.float32))
        assert p._state["detail_min"] is None and p._state["detail_max"] is None


# ══════════════════════════════════════════════════════════════════════════════
# Tier 1 — invertible codes: exact values with NO round trip
# ══════════════════════════════════════════════════════════════════════════════

class TestIntegerCodesAreExact:
    """An integral source whose range fits in 256 codes is fully recoverable from
    the bytes already in the browser — interpolating the band instead would report
    e.g. 6.27 for a 7. No kernel involved, so this holds in a static HTML export."""

    def test_uint8_values_are_exact(self, interact_page):
        rng = np.random.default_rng(0)
        data = rng.integers(3, 201, size=(32, 32)).astype(np.uint8)
        fig, ax = apl.subplots(1, 1, figsize=(FIG, FIG))
        plot = ax.imshow(data, cmap="gray", gpu=False)
        assert plot._state["raw_is_int"] is True
        page = interact_page(fig)

        for ix, iy in [(0, 0), (7, 3), (31, 31), (12, 20)]:
            text = _hover_pixel(page, plot, ix, iy)
            assert _value_of(text) == float(data[iy, ix]), (
                f"pixel ({ix}, {iy}) must read its exact integer: {text!r}")

    def test_small_range_int_labels_are_exact(self, interact_page):
        """A label/mask map (0..4) — every class index must read back exactly."""
        data = (np.arange(16 * 16).reshape(16, 16) % 5).astype(np.int32)
        fig, ax = apl.subplots(1, 1, figsize=(FIG, FIG))
        plot = ax.imshow(data, cmap="gray", gpu=False)
        page = interact_page(fig)

        for ix, iy in [(0, 0), (1, 0), (2, 0), (3, 0), (4, 0), (9, 7)]:
            assert _value_of(_hover_pixel(page, plot, ix, iy)) == float(data[iy, ix])

    def test_float_source_is_not_claimed_exact(self):
        """Float data gets no invertibility promise (0.5 is not recoverable)."""
        p = apl.subplots(1, 1)[1].imshow(np.linspace(0, 1, 64).reshape(8, 8))
        assert p._state["raw_is_int"] is False

    def test_wide_int_range_stays_quantised(self, interact_page):
        """Range beyond 255 levels genuinely loses information — the readout must
        land within one step (and the probe, with no kernel here, changes nothing)."""
        data = (np.arange(32 * 32, dtype=np.uint16) * 60).reshape(32, 32)
        fig, ax = apl.subplots(1, 1, figsize=(FIG, FIG))
        plot = ax.imshow(data, cmap="gray", gpu=False)
        page = interact_page(fig)

        step = (float(data.max()) - float(data.min())) / 255.0
        assert step > 1, "test needs a range wider than 255 levels"
        got = _value_of(_hover_pixel(page, plot, 20, 20))
        assert abs(got - float(data[20, 20])) <= step

    def test_tile_overview_is_not_claimed_exact(self):
        """A mean-reduced overview holds averages, not the source integers."""
        big = (np.arange(1500 * 1500, dtype=np.uint16) % 4000).reshape(1500, 1500)
        p = apl.subplots(1, 1)[1].imshow(big, tile=True)
        assert p._state["tile_enabled"] is True
        assert p._state["raw_is_int"] is False


# ══════════════════════════════════════════════════════════════════════════════
# Tier 3 — the exact-value probe (JS half)
# ══════════════════════════════════════════════════════════════════════════════

class TestExactProbeFrontend:
    def _wide_plot(self, interact_page, **kw):
        data = (np.arange(32 * 32, dtype=np.uint16) * 60).reshape(32, 32)
        fig, ax = apl.subplots(1, 1, figsize=(FIG, FIG))
        plot = ax.imshow(data, cmap="gray", gpu=False, **kw)
        page = interact_page(fig)
        _collect_events(page)
        return data, plot, page

    def test_probe_fires_after_dwell(self, interact_page):
        data, plot, page = self._wide_plot(interact_page)
        assert plot._state["probe_ms"] == 250, "probe is on by default"
        _hover_pixel(page, plot, 11, 6)
        page.wait_for_timeout(500)                      # outlast the dwell
        evs = _get_events(page, "value_probe")
        assert evs, "no value_probe emitted after the cursor dwelled"
        assert (evs[-1]["img_x"], evs[-1]["img_y"]) == (11, 6), evs[-1]

    def test_probe_not_emitted_when_disabled(self, interact_page):
        data, plot, page = self._wide_plot(interact_page, probe_exact=False)
        assert plot._state["probe_ms"] == 0
        _hover_pixel(page, plot, 11, 6)
        page.wait_for_timeout(500)
        assert not _get_events(page, "value_probe"), (
            "probe_exact=False must not send anything to Python")

    def test_probe_answer_replaces_quantised_value(self, interact_page):
        data, plot, page = self._wide_plot(interact_page)
        exact = float(data[6, 11])
        quantised = _value_of(_hover_pixel(page, plot, 11, 6))
        assert quantised != exact, "test needs a lossy band"
        _set_probe_answer(page, plot, 11, 6, exact)
        assert _value_of(_hover_pixel(page, plot, 11, 6)) == exact

    def test_probe_answer_refreshes_a_stationary_cursor(self, interact_page):
        """The answer lands while the cursor is still — no mousemove follows, so the
        state observer has to refresh the bar itself."""
        data, plot, page = self._wide_plot(interact_page)
        exact = float(data[6, 11])
        _hover_pixel(page, plot, 11, 6)                 # park the cursor
        _set_probe_answer(page, plot, 11, 6, exact)     # answer, no further move
        text = page.evaluate("(pid) => globalThis.__apl_statusText(pid)",
                             plot._id)["text"]
        assert _value_of(text) == exact, (
            f"status bar did not pick up the probe answer in place: {text!r}")

    def test_stale_probe_answer_is_ignored(self, interact_page):
        """An answer for a different pixel must not be shown for this one."""
        data, plot, page = self._wide_plot(interact_page)
        _set_probe_answer(page, plot, 30, 30, -12345.0)
        text = _hover_pixel(page, plot, 11, 6)
        assert _value_of(text) != -12345.0, f"stale answer leaked: {text!r}"

    def test_rgb_image_never_probes(self, interact_page):
        """True-colour channels are already exact — no round trip is warranted."""
        rgb = np.zeros((16, 16, 3), np.uint8)
        rgb[:, :, 1] = 128
        fig, ax = apl.subplots(1, 1, figsize=(FIG, FIG))
        plot = ax.imshow(rgb, gpu=False)
        page = interact_page(fig)
        _collect_events(page)
        _hover_pixel(page, plot, 8, 8)
        page.wait_for_timeout(500)
        assert not _get_events(page, "value_probe")


# ══════════════════════════════════════════════════════════════════════════════
# Tier 3 — the exact-value probe (Python half)
# ══════════════════════════════════════════════════════════════════════════════

class TestExactProbeBackend:
    """``value_probe`` → the exact value, pushed back with the pixel it belongs to."""

    def _probe(self, fig, plot, col, row):
        fig._dispatch_event(json.dumps({
            "event_type": "value_probe", "panel_id": plot._id,
            "img_x": col, "img_y": row, "x": 10, "y": 10,
        }))
        return plot._state

    def test_answers_through_the_real_dispatch(self):
        data = (np.arange(64 * 64, dtype=np.uint16) * 15).reshape(64, 64)
        fig, ax = apl.subplots(1, 1)
        plot = ax.imshow(data)
        st = self._probe(fig, plot, 33, 5)
        assert (st["probe_x"], st["probe_y"]) == (33, 5)
        assert st["probe_value"] == float(data[5, 33])

    def test_origin_lower_maps_to_the_displayed_pixel(self):
        data = (np.arange(16 * 16, dtype=np.uint16)).reshape(16, 16)
        fig, ax = apl.subplots(1, 1)
        plot = ax.imshow(data, origin="lower")
        # Display row 0 is the LAST array row when origin='lower'.
        st = self._probe(fig, plot, 3, 0)
        assert st["probe_value"] == float(data[-1, 3])

    def test_tile_mode_probes_full_resolution(self):
        """The overview in state is decimated; the answer must come from the
        backend's native pixels, not the average the base texture holds."""
        big = (np.arange(1500 * 1500, dtype=np.uint16) % 5000).reshape(1500, 1500)
        fig, ax = apl.subplots(1, 1)
        plot = ax.imshow(big, tile=True)
        st = self._probe(fig, plot, 700, 800)
        assert st["probe_value"] == float(big[800, 700])

    def test_out_of_bounds_is_ignored(self):
        fig, ax = apl.subplots(1, 1)
        plot = ax.imshow(np.zeros((8, 8), np.uint8))
        st = self._probe(fig, plot, 99, 3)
        assert st["probe_value"] is None

    def test_disabled_probe_ignores_the_event(self):
        fig, ax = apl.subplots(1, 1)
        plot = ax.imshow(np.arange(64, dtype=np.uint16).reshape(8, 8),
                         probe_exact=False)
        st = self._probe(fig, plot, 3, 3)
        assert st["probe_value"] is None

    def test_new_frame_clears_a_stale_answer(self):
        data = np.arange(64, dtype=np.uint16).reshape(8, 8)
        fig, ax = apl.subplots(1, 1)
        plot = ax.imshow(data)
        self._probe(fig, plot, 3, 3)
        assert plot._state["probe_value"] is not None
        plot.set_data(data * 2)
        assert plot._state["probe_value"] is None, (
            "an answer for the OLD frame must not survive a new one")

    def test_set_value_probe_toggles(self):
        plot = apl.subplots(1, 1)[1].imshow(np.zeros((8, 8), np.uint8))
        plot.set_value_probe(False)
        assert plot._state["probe_ms"] == 0
        plot.set_value_probe(True, ms=80)
        assert plot._state["probe_ms"] == 80

    def test_img_coords_reach_python_handlers(self):
        """img_x/img_y are now real Event fields, so a user handler can index the
        source array directly instead of mapping axis units back."""
        seen = []
        fig, ax = apl.subplots(1, 1)
        plot = ax.imshow(np.zeros((8, 8), np.uint8))
        plot.add_event_handler("pointer_down")(lambda e: seen.append((e.img_x, e.img_y)))
        fig._dispatch_event(json.dumps({
            "event_type": "pointer_down", "panel_id": plot._id,
            "img_x": 2.5, "img_y": 6.5, "xdata": 2.5, "ydata": 6.5,
        }))
        assert seen == [(2.5, 6.5)]


# ══════════════════════════════════════════════════════════════════════════════
# Toggling the overlay + handing the readout to an embedding host
# ══════════════════════════════════════════════════════════════════════════════

class TestReadoutVisibility:
    def test_hidden_overlay_still_reports_to_the_host(self, interact_page):
        """set_readout_visible(False) drops the on-image pill but keeps computing the
        readout — that is what lets an Electron app draw it in its own status line."""
        data = np.arange(16 * 16, dtype=np.uint8).reshape(16, 16)
        fig, ax = apl.subplots(1, 1, figsize=(FIG, FIG))
        plot = ax.imshow(data, cmap="gray", gpu=False)
        plot.set_readout_visible(False)
        assert plot._state["readout_visible"] is False
        page = interact_page(fig)
        _watch_readout(page)

        assert _hover_pixel(page, plot, 5, 9) is None, "pill must stay hidden"
        outs = _readouts(page)
        assert outs, "host got no readout while the overlay was hidden"
        last = outs[-1]
        assert (last["col"], last["row"]) == (5, 9)
        assert last["value"] == float(data[9, 5]) and last["exact"] is True
        assert "[5, 9]" in last["text"]

    def test_visible_overlay_also_reports_to_the_host(self, interact_page):
        data = np.arange(16 * 16, dtype=np.uint8).reshape(16, 16)
        fig, ax = apl.subplots(1, 1, figsize=(FIG, FIG))
        plot = ax.imshow(data, cmap="gray", gpu=False)
        page = interact_page(fig)
        _watch_readout(page)

        text = _hover_pixel(page, plot, 5, 9)
        assert text, "pill should be visible by default"
        assert _readouts(page)[-1]["text"] == text

    def test_leaving_the_image_clears_the_host_readout(self, interact_page):
        fig, ax = apl.subplots(1, 1, figsize=(FIG, FIG))
        plot = ax.imshow(np.zeros((32, IMG), np.uint8), cmap="gray", gpu=False)
        page = interact_page(fig)
        _watch_readout(page)

        _hover_pixel(page, plot, 32, 16)
        assert _readouts(page)[-1] is not None
        _hover_pixel(page, plot, 32, -8)          # into the letterbox margin
        assert _readouts(page)[-1] is None, (
            "host must be told the cursor left so it can clear its display")

    def test_toggle_is_live(self, interact_page):
        """Flipping the flag on a running figure takes effect without a reload."""
        fig, ax = apl.subplots(1, 1, figsize=(FIG, FIG))
        plot = ax.imshow(np.zeros((16, 16), np.uint8), cmap="gray", gpu=False)
        page = interact_page(fig)
        assert _hover_pixel(page, plot, 8, 8) is not None
        page.evaluate(
            """([pid]) => {
                const key = 'panel_' + pid + '_json';
                const st = JSON.parse(window._aplModel.get(key));
                st.readout_visible = false;
                window._aplModel.set(key, JSON.stringify(st));
            }""", [plot._id])
        assert _hover_pixel(page, plot, 8, 8) is None


_MOUNT_READOUT_PAGE = """<!DOCTYPE html>
<html><head><meta charset="utf-8"/>
<style>html,body{margin:0;padding:0;}</style></head>
<body><div id="host"></div>
<script type="module">
const STATE = __STATE__;
const esmSource = __ESM__;
const blobUrl = URL.createObjectURL(new Blob([esmSource], {type: "text/javascript"}));
window._readouts = [];
import(blobUrl).then(mod => {
  window._handle = mod.mount(document.getElementById("host"), STATE, {
    onReadout: (info) => window._readouts.push(info),
  });
  window._aplReady = true;
}).catch(err => { document.body.textContent = "mount error: " + err; });
</script></body></html>
"""


class TestMountReadoutCallback:
    """The Electron contract: mount(el, state, {onReadout}) — the host renders the
    position/value wherever it likes (e.g. the window's bottom-right corner)."""

    @pytest.fixture
    def readout_mount_page(self, _pw_browser):
        from anyplotlib.embed import esm_path, figure_state
        pages, paths = [], []

        def _open(fig):
            html = (_MOUNT_READOUT_PAGE
                    .replace("__STATE__", json.dumps(figure_state(fig)))
                    .replace("__ESM__",
                             json.dumps(esm_path().read_text(encoding="utf-8"))))
            with tempfile.NamedTemporaryFile(suffix=".html", mode="w",
                                             encoding="utf-8", delete=False) as fh:
                fh.write(html)
                tmp = pathlib.Path(fh.name)
            paths.append(tmp)
            page = _pw_browser.new_page()
            pages.append(page)
            page.goto(tmp.as_uri())
            page.wait_for_function("() => window._aplReady === true", timeout=15_000)
            page.evaluate("() => new Promise(r => requestAnimationFrame("
                          "() => requestAnimationFrame(r)))")
            return page

        yield _open
        for p in pages:
            try:
                p.close()
            except Exception:
                pass
        for path in paths:
            path.unlink(missing_ok=True)

    def test_on_readout_callback_receives_the_value(self, readout_mount_page):
        data = np.arange(16 * 16, dtype=np.uint8).reshape(16, 16)
        fig, ax = apl.subplots(1, 1, figsize=(FIG, FIG))
        plot = ax.imshow(data, cmap="gray", gpu=False)
        plot.set_readout_visible(False)          # host draws it instead
        page = readout_mount_page(fig)

        pt = page.evaluate("([pid, ix, iy]) => globalThis.__apl_imgToCanvas(pid, ix, iy)",
                           [plot._id, 5, 9])
        box = page.evaluate(
            f"() => {{ const c = {_OVERLAY}; const r = c.getBoundingClientRect();"
            f"  return {{x: r.x, y: r.y}}; }}")
        page.mouse.move(box["x"] + pt[0], box["y"] + pt[1])
        page.wait_for_timeout(80)

        outs = page.evaluate("() => window._readouts")
        assert outs, "mount(opts.onReadout) was never called"
        last = outs[-1]
        assert (last["col"], last["row"]) == (5, 9)
        assert last["value"] == float(data[9, 5])
        assert last["exact"] is True
        # And the built-in pill really is gone in the embedded page.
        shown = page.evaluate("(pid) => globalThis.__apl_statusText(pid).shown",
                              plot._id)
        assert shown is False


class TestProbeStaleness:
    """A parked cursor must never keep showing the PREVIOUS frame's exact value —
    the movie-scrub case, where only the pixels change under a still mouse."""

    def test_detail_tile_push_invalidates_the_answer(self):
        data = np.arange(64 * 64, dtype=np.uint16).reshape(64, 64)
        fig, ax = apl.subplots(1, 1)
        plot = ax.imshow(data, vmin=0, vmax=4095)
        fig._dispatch_event(json.dumps({
            "event_type": "value_probe", "panel_id": plot._id,
            "img_x": 20, "img_y": 20}))
        assert plot._state["probe_value"] is not None
        plot.set_detail(np.ones((32, 32), np.uint16), 16, 48, 16, 48)
        assert plot._state["probe_value"] is None

    def test_tiled_scrub_invalidates_the_answer(self):
        big = (np.arange(1500 * 1500, dtype=np.uint16) % 5000).reshape(1500, 1500)
        fig, ax = apl.subplots(1, 1)
        plot = ax.imshow(big, tile=True)
        fig._dispatch_event(json.dumps({
            "event_type": "value_probe", "panel_id": plot._id,
            "img_x": 700, "img_y": 800}))
        assert plot._state["probe_value"] == float(big[800, 700])
        plot.update_tile_source((big + 1).astype(np.uint16))
        assert plot._state["probe_value"] is None, (
            "a scrubbed frame must void the previous frame's exact value")

    def test_mesh_set_data_invalidates_the_answer(self):
        data = np.arange(16 * 16, dtype=np.uint16).reshape(16, 16)
        fig, ax = apl.subplots(1, 1)
        plot = ax.pcolormesh(data, x_edges=np.arange(17.0), y_edges=np.arange(17.0))
        fig._dispatch_event(json.dumps({
            "event_type": "value_probe", "panel_id": plot._id,
            "img_x": 5, "img_y": 9}))
        assert plot._state["probe_value"] == float(data[9, 5])
        plot.set_data(data * 3)
        assert plot._state["probe_value"] is None
        # …and the next probe answers from the NEW frame, not the stale copy.
        fig._dispatch_event(json.dumps({
            "event_type": "value_probe", "panel_id": plot._id,
            "img_x": 5, "img_y": 9}))
        assert plot._state["probe_value"] == float(data[9, 5] * 3)

    def test_probe_is_not_a_user_event(self):
        """It is renderer plumbing: a wildcard handler must not see it, and
        pause_events() must not stall the readout."""
        seen = []
        fig, ax = apl.subplots(1, 1)
        plot = ax.imshow(np.arange(64, dtype=np.uint16).reshape(8, 8))
        plot.add_event_handler("*")(lambda e: seen.append(e.event_type))
        with plot.pause_events():
            fig._dispatch_event(json.dumps({
                "event_type": "value_probe", "panel_id": plot._id,
                "img_x": 3, "img_y": 3}))
        assert seen == [], f"value_probe leaked into user handlers: {seen}"
        assert plot._state["probe_value"] is not None, (
            "the readout must keep working while user events are paused")

    def test_frontend_rearms_after_a_frame_lands(self, interact_page):
        """With the cursor parked, a state push re-arms the dwell probe — so the
        value becomes exact again once a scrub settles, without a mouse move."""
        data = (np.arange(32 * 32, dtype=np.uint16) * 60).reshape(32, 32)
        fig, ax = apl.subplots(1, 1, figsize=(FIG, FIG))
        plot = ax.imshow(data, cmap="gray", gpu=False)
        page = interact_page(fig)
        _collect_events(page)

        _hover_pixel(page, plot, 9, 4)
        page.wait_for_timeout(500)
        assert _get_events(page, "value_probe"), "first dwell probe missing"
        # A new frame arrives (probe fields cleared, as Python does) — no mousemove.
        page.evaluate(
            """([pid]) => {
                const key = 'panel_' + pid + '_json';
                const st = JSON.parse(window._aplModel.get(key));
                st.probe_x = null; st.probe_y = null; st.probe_value = null;
                window._aplModel.set(key, JSON.stringify(st));
            }""", [plot._id])
        page.wait_for_timeout(500)
        probes = _get_events(page, "value_probe")
        assert len(probes) >= 2, (
            "a settled frame under a parked cursor must re-probe for the new pixels")
        assert (probes[-1]["img_x"], probes[-1]["img_y"]) == (9, 4)


class TestReadoutKeyToggle:
    """`v` over the plot hides/shows the pill — the same family as r/c/l/s."""

    def _hover(self, page, plot, ix, iy):
        return _hover_pixel(page, plot, ix, iy)

    def test_v_toggles_the_pill(self, interact_page):
        fig, ax = apl.subplots(1, 1, figsize=(FIG, FIG))
        plot = ax.imshow(np.zeros((16, 16), np.uint8), cmap="gray", gpu=False)
        page = interact_page(fig)
        _watch_readout(page)

        assert self._hover(page, plot, 8, 8) is not None
        page.keyboard.press("v")
        assert self._hover(page, plot, 8, 8) is None, "v must hide the pill"
        page.keyboard.press("v")
        assert self._hover(page, plot, 8, 8) is not None, "v again must restore it"

    def test_hidden_by_key_still_reports_to_the_host(self, interact_page):
        fig, ax = apl.subplots(1, 1, figsize=(FIG, FIG))
        plot = ax.imshow(np.arange(256, dtype=np.uint8).reshape(16, 16),
                         cmap="gray", gpu=False)
        page = interact_page(fig)
        _watch_readout(page)

        self._hover(page, plot, 8, 8)
        page.keyboard.press("v")
        self._hover(page, plot, 9, 8)
        assert _readouts(page)[-1]["col"] == 9, (
            "host must keep receiving the readout while the pill is toggled off")

    def test_state_push_does_not_undo_the_toggle(self, interact_page):
        """A movie scrub pushes state every frame; it must not re-show the pill the
        viewer just dismissed."""
        fig, ax = apl.subplots(1, 1, figsize=(FIG, FIG))
        plot = ax.imshow(np.zeros((16, 16), np.uint8), cmap="gray", gpu=False)
        page = interact_page(fig)

        self._hover(page, plot, 8, 8)
        page.keyboard.press("v")
        page.evaluate(
            """([pid]) => {                       // a Python-style state push
                const key = 'panel_' + pid + '_json';
                const st = JSON.parse(window._aplModel.get(key));
                st.title = 'frame 2';
                window._aplModel.set(key, JSON.stringify(st));
            }""", [plot._id])
        page.wait_for_timeout(80)
        assert self._hover(page, plot, 8, 8) is None

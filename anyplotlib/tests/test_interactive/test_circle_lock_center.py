"""
tests/test_interactive/test_circle_lock_center.py
=================================================

``lock_center`` — a circle whose centre is fixed by the data.

Why it exists: a ring measured on a power spectrum is centred on the DC term.
Its centre is not a free parameter, so a draggable one is a control that can
only ever be wrong — and a ring nudged off-centre silently corrupts every
radius measured from it.

Why it is enforced in the HIT-TEST and not afterwards. The obvious
implementation is a Python handler that watches the widget and snaps the centre
back when the drag settles. It cannot work: ``_doDrag2d`` recomputes the
position every frame from its own grab-time snapshot, so a pushed-back centre
is overwritten on the next mousemove. The ring tracks the cursor for the whole
drag and jumps back on release, which reads as a broken lock rather than a
locked ring. Refusing the grab is the only place the constraint holds.

Coordinate system mirrors figure_esm.js — see ``_img_to_page``.
"""
from __future__ import annotations

import numpy as np
import pytest

import anyplotlib as apl
from anyplotlib.widgets import CircleWidget
from anyplotlib.tests.test_interactive._event_test_utils import (
    _collect_events, _get_events,
)

FIG_W, FIG_H = 400, 300


# ═══════════════════════════════════════════════════════════════════════════
# 1. Python API — the flag has to reach the JS renderer to do anything
# ═══════════════════════════════════════════════════════════════════════════

class TestLockCenterAttribute:
    def test_defaults_to_unlocked(self):
        w = CircleWidget(lambda: None, cx=16, cy=16, r=6)
        assert w.lock_center is False

    def test_stores_the_flag(self):
        w = CircleWidget(lambda: None, cx=16, cy=16, r=6, lock_center=True)
        assert w.lock_center is True

    def test_reaches_the_state_dict(self):
        """JS reads the widget dict, so the flag has to survive to_dict()."""
        w = CircleWidget(lambda: None, cx=16, cy=16, r=6, lock_center=True)
        assert w.to_dict()["lock_center"] is True

    def test_add_circle_widget_passes_it_through(self):
        fig, ax = apl.subplots(1, 1, figsize=(FIG_W, FIG_H))
        v = ax.imshow(np.zeros((32, 32), dtype=np.float32))
        w = v.add_circle_widget(cx=16, cy=16, r=6, lock_center=True)
        assert w.lock_center is True

    def test_add_circle_widget_defaults_to_unlocked(self):
        fig, ax = apl.subplots(1, 1, figsize=(FIG_W, FIG_H))
        v = ax.imshow(np.zeros((32, 32), dtype=np.float32))
        assert v.add_circle_widget(cx=16, cy=16, r=6).lock_center is False


# ═══════════════════════════════════════════════════════════════════════════
# 2. Real drags in a real browser — the only place the constraint is enforced
# ═══════════════════════════════════════════════════════════════════════════

_OVERLAY_RECT_JS = """() => {
    for (const cv of document.querySelectorAll('canvas')) {
        if (getComputedStyle(cv).pointerEvents === 'all') {
            const r = cv.getBoundingClientRect();
            return {left:r.left, top:r.top, w:r.width, h:r.height};
        }
    }
    return null;
}"""


def _img_to_page(page, ix, iy, iw=32, ih=32):
    """Image px → page coords, for an overlay laid out 'contain' with no zoom."""
    r = page.evaluate(_OVERLAY_RECT_JS)
    assert r is not None, "overlay canvas not found"
    s = min(r["w"] / iw, r["h"] / ih)
    ox = (r["w"] - iw * s) / 2.0
    oy = (r["h"] - ih * s) / 2.0
    return r["left"] + ox + ix * s, r["top"] + oy + iy * s


def _setup(interact_page, lock_center):
    fig, ax = apl.subplots(1, 1, figsize=(FIG_W, FIG_H))
    v = ax.imshow(np.zeros((32, 32), dtype=np.float32))
    v.add_circle_widget(cx=16, cy=16, r=6, color="#ff0000",
                        lock_center=lock_center)
    page = interact_page(fig)
    _collect_events(page)
    return page


def _drag(page, frm, to, steps=8):
    page.mouse.move(*_img_to_page(page, *frm))
    page.mouse.down()
    page.mouse.move(*_img_to_page(page, *to), steps=steps)
    page.mouse.up()
    page.wait_for_timeout(80)


@pytest.mark.usefixtures("interact_page")
class TestLockedCentreDrag:
    def test_body_drag_does_not_move_a_locked_circle(self, interact_page):
        """THE regression. Grab the centre and pull: nothing about the widget
        may change — not even transiently, which is why the assertion is on
        every event and not only the last one."""
        page = _setup(interact_page, lock_center=True)

        _drag(page, (16, 16), (24, 24))

        moved = [e for e in _get_events(page)
                 if e.get("cx") is not None
                 and (abs(e["cx"] - 16.0) > 0.5 or abs(e["cy"] - 16.0) > 0.5)]
        assert not moved, (
            f"a locked circle's centre moved during the drag: {moved[:3]}")

    def test_an_unlocked_circle_still_moves(self, interact_page):
        """The counterpart, so a lock that accidentally applied to every circle
        would fail here rather than passing the whole file."""
        page = _setup(interact_page, lock_center=False)

        _drag(page, (16, 16), (20, 22))

        last = _get_events(page, "pointer_up")[-1]
        assert last["cx"] > 16.0 and last["cy"] > 16.0
        assert last["r"] == pytest.approx(6.0, abs=0.5)

    def test_the_radius_handle_still_drags_when_locked(self, interact_page):
        """A locked centre must not cost the measurement. The handle sits at
        the east point (cx+r, cy) = (22, 16); drag it out to (26, 16)."""
        page = _setup(interact_page, lock_center=True)

        _drag(page, (22, 16), (26, 16))

        ups = _get_events(page, "pointer_up")
        assert ups, "the radius drag should still emit a pointer_up"
        last = ups[-1]
        assert last["r"] > 6.0, "the radius handle stopped working under the lock"
        assert last["cx"] == pytest.approx(16.0, abs=0.5)
        assert last["cy"] == pytest.approx(16.0, abs=0.5)

    def test_a_locked_ring_band_is_not_grabbable_either(self, interact_page):
        """Not just the centre hotspot: the ring BAND is the circle's move
        target, and it is the part a user actually grabs. (22, 16) is the
        handle, so aim at the west point (10, 16) — same band, no handle."""
        page = _setup(interact_page, lock_center=True)

        _drag(page, (10, 16), (4, 16))

        moved = [e for e in _get_events(page)
                 if e.get("cx") is not None and abs(e["cx"] - 16.0) > 0.5]
        assert not moved, f"the ring band dragged the locked circle: {moved[:3]}"

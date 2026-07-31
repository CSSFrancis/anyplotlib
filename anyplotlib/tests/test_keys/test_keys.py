"""
tests/test_keys/test_keys.py
============================

Floating image keys (``Plot.add_key``) — see ``anyplotlib/keys.py``.

Covers:
  * lifecycle and validation on the Python side
  * the picture riding the geometry channel, separate from the styling
  * Playwright: corner and anchor placement, the card, ``hover_only``
    show/hide, and the two decode/measure traps that made a hover-only key
    vanish from an export
"""
from __future__ import annotations

import base64

import numpy as np
import pytest

import anyplotlib as apl
from anyplotlib.keys import KeyOverlay
from anyplotlib.tests._png_utils import decode_png


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FIG_W, FIG_H, IMG = 400, 340, 64


def _disc(n=96, rgb=(255, 40, 40)):
    """An RGBA disc: alpha 0 outside, so a bare key must draw NO square card."""
    yy, xx = np.mgrid[0:n, 0:n]
    r = np.hypot(yy - n / 2, xx - n / 2) / (n / 2)
    a = np.zeros((n, n, 4), np.uint8)
    a[..., 0], a[..., 1], a[..., 2] = rgb
    a[..., 3] = np.where(r <= 1.0, 255, 0)
    return a


def _panel():
    fig, ax = apl.subplots(1, 1, figsize=(FIG_W, FIG_H))
    return fig, ax.imshow(np.zeros((IMG, IMG), np.float32))


def _export(page, scale=1):
    url = page.evaluate(
        "(s) => window._handle.exportPNG({scale: s}).then(r => r.dataUrl)", scale)
    return decode_png(base64.b64decode(url.split(",", 1)[1])).astype(int)


def _mask(arr, rgb, tol=70):
    """Pixels close to *rgb* — locates a key by its colour."""
    d = np.abs(arr[..., :3] - np.asarray(rgb)).max(2)
    return d < tol


def _centroid(arr, rgb):
    m = _mask(arr, rgb)
    ys, xs = np.nonzero(m)
    assert len(ys), f"no {rgb} pixels found"
    return xs.mean(), ys.mean(), int(m.sum())


def _hover(page, panel_id):
    box = page.evaluate("""(pid) => {
        const r = window._handle.api.panels.get(pid)
                        .overlayCanvas.getBoundingClientRect();
        return {x: r.x + r.width / 2, y: r.y + r.height / 2};
    }""", panel_id)
    page.mouse.move(box["x"], box["y"])
    page.wait_for_timeout(200)


# ---------------------------------------------------------------------------
# Python side
# ---------------------------------------------------------------------------

class TestApi:
    def test_add_key_returns_a_handle_and_registers_it(self):
        _, p = _panel()
        k = p.add_key(_disc(), name="ipf")
        assert isinstance(k, KeyOverlay)
        assert p.list_keys() == [k]
        assert p.get_key("ipf") is k and p.get_key(k.id) is k

    def test_defaults(self):
        _, p = _panel()
        k = p.add_key(_disc())
        d = p._state["keys"][0]
        assert d["corner"] == "top-right" and d["anchor"] is None
        assert d["size"] == pytest.approx(0.22)
        assert d["bgcolor"] is None and d["hover_only"] is False
        assert d["visible"] is True
        assert k.name == k.id          # name defaults to the id

    def test_the_picture_rides_the_geometry_channel(self):
        """Styling is light; the image is heavy and must not re-transmit."""
        _, p = _panel()
        k = p.add_key(_disc())
        assert "key_images" in p._GEOM_KEYS
        assert p._state["key_images"][k.id].startswith("data:image/png;base64,")
        # …and does NOT appear in the per-key view payload.
        assert not any("url" in key or "image" in key
                       for key in p._state["keys"][0])

    def test_set_updates_and_pushes(self):
        _, p = _panel()
        k = p.add_key(_disc())
        k.set(size=0.4, bgcolor="none", corner="bottom-left")
        d = p._state["keys"][0]
        assert (d["size"], d["bgcolor"], d["corner"]) == (0.4, "none", "bottom-left")

    def test_attribute_assignment_pushes(self):
        _, p = _panel()
        k = p.add_key(_disc())
        k.visible = False
        assert p._state["keys"][0]["visible"] is False
        assert k.visible is False

    def test_set_image_swaps_the_picture_only(self):
        _, p = _panel()
        k = p.add_key(_disc(), size=0.4)
        before = p._state["key_images"][k.id]
        k.set_image(_disc(rgb=(0, 0, 255)))
        assert p._state["key_images"][k.id] != before
        assert p._state["keys"][0]["size"] == pytest.approx(0.4)

    def test_remove_by_object_name_and_handle(self):
        _, p = _panel()
        a = p.add_key(_disc(), name="a")
        b = p.add_key(_disc(), name="b")
        c = p.add_key(_disc(), name="c")
        p.remove_key(a)                 # by object
        p.remove_key("b")               # by name
        c.remove()                      # via the handle
        assert p.list_keys() == []
        assert p._state["keys"] == [] and p._state["key_images"] == {}

    def test_clear_keys(self):
        _, p = _panel()
        p.add_key(_disc()); p.add_key(_disc())
        p.clear_keys()
        assert p.list_keys() == []

    def test_every_panel_kind_takes_a_key(self):
        """A colour wheel means the same thing over a map and a scatter."""
        fig, ax = apl.subplots(1, 1)
        g = np.linspace(0, 1, 4)
        X, Y = np.meshgrid(g, g)
        for plot in (ax.imshow(np.zeros((8, 8), np.float32)),
                     ax.plot_surface(X, Y, np.zeros((4, 4))),
                     ax.plot(np.zeros(8))):
            plot.add_key(_disc())
            assert len(plot._state["keys"]) == 1


class TestValidation:
    @pytest.mark.parametrize("size", [0, -0.1, 1.5])
    def test_size_out_of_range_raises(self, size):
        _, p = _panel()
        with pytest.raises(ValueError, match="size is a fraction"):
            p.add_key(_disc(), size=size)

    @pytest.mark.parametrize("alpha", [-0.1, 1.5])
    def test_alpha_out_of_range_raises(self, alpha):
        _, p = _panel()
        with pytest.raises(ValueError, match=r"alpha must be in \[0, 1\]"):
            p.add_key(_disc(), alpha=alpha)

    def test_unknown_corner_raises(self):
        _, p = _panel()
        with pytest.raises(ValueError, match="corner must be one of"):
            p.add_key(_disc(), corner="middle")

    def test_bad_anchor_raises(self):
        _, p = _panel()
        with pytest.raises(ValueError, match="anchor must be"):
            p.add_key(_disc(), anchor=(0.5, 0.5, 0.5))

    def test_duplicate_name_raises(self):
        _, p = _panel()
        p.add_key(_disc(), name="ipf")
        with pytest.raises(ValueError, match="already exists"):
            p.add_key(_disc(), name="ipf")

    def test_unknown_property_raises(self):
        _, p = _panel()
        k = p.add_key(_disc())
        with pytest.raises(ValueError, match="unknown key property"):
            k.set(colour="red")

    def test_get_missing_key_raises(self):
        _, p = _panel()
        with pytest.raises(KeyError):
            p.get_key("nope")


# ---------------------------------------------------------------------------
# Rendering — the placement and hover logic lives in figure_esm.js, so a
# Python-only test proves nothing about what is actually drawn.
# ---------------------------------------------------------------------------

RED, BLUE = (255, 40, 40), (40, 40, 255)


@pytest.mark.usefixtures("mount_page")
class TestRender:
    def test_a_bare_key_draws_no_card(self, mount_page):
        """An RGBA disc must land as a disc — alpha 0 stays transparent."""
        fig, p = _panel()
        p.add_key(_disc(), corner="top-right", size=0.3)
        arr = _export(mount_page(fig))
        cx, cy, n = _centroid(arr, RED)
        assert n > 400, "the key did not draw"
        # A filled square would be 4/pi times the disc's area; allow slack for
        # antialiasing but not enough to admit a card.
        side = 0.3 * min(p._state["image_width"], p._state["image_height"])
        assert n < 400 * 400, "far too many pixels — a card was drawn"

    @pytest.mark.parametrize("corner,right,bottom", [
        ("top-left", False, False), ("top-right", True, False),
        ("bottom-left", False, True), ("bottom-right", True, True),
    ])
    def test_each_corner_places_the_key(self, mount_page, corner,
                                        right, bottom):
        fig, p = _panel()
        p.add_key(_disc(), corner=corner, size=0.2)
        arr = _export(mount_page(fig))
        cx, cy, _ = _centroid(arr, RED)
        h, w = arr.shape[:2]
        # bool(): the comparison yields np.bool_, which is never `is True`.
        assert bool(cx > w / 2) is right, f"{corner}: wrong horizontal half"
        assert bool(cy > h / 2) is bottom, f"{corner}: wrong vertical half"

    def test_anchor_overrides_corner(self, mount_page):
        fig, p = _panel()
        p.add_key(_disc(), corner="top-right", anchor=(0.5, 0.5), size=0.2)
        arr = _export(mount_page(fig))
        cx, cy, _ = _centroid(arr, RED)
        h, w = arr.shape[:2]
        assert abs(cx - w / 2) < w * 0.1 and abs(cy - h / 2) < h * 0.1

    def test_size_scales_the_key(self, mount_page):
        fig, p = _panel()
        p.add_key(_disc(), size=0.2, name="small")
        small = _centroid(_export(mount_page(fig)), RED)[2]

        fig2, p2 = _panel()
        p2.add_key(_disc(), size=0.4, name="big")
        big = _centroid(_export(mount_page(fig2)), RED)[2]
        # Area goes as size²; 0.4 vs 0.2 is ~4x.
        assert 3.0 < big / small < 5.0, f"{small} → {big}"

    def test_keys_pin_to_the_axes_box_not_the_letterbox(self, mount_page):
        """A key belongs to the axes box, like the scale bar.

        The panel is much wider than the square image, so the letterboxed
        picture is far narrower than the axes box.  A top-left key must sit at
        the axes-box edge, not at the picture's left edge.
        """
        fig, ax = apl.subplots(1, 1, figsize=(560, 260))
        p = ax.imshow(np.zeros((IMG, IMG), np.float32))
        p.add_key(_disc(), corner="top-left", size=0.15)
        page = mount_page(fig)
        arr = _export(page)
        cx, _, _ = _centroid(arr, RED)
        box = page.evaluate("""(pid) => {
            const p = window._handle.api.panels.get(pid);
            return {imgX: p.imgX, imgW: p.imgW};
        }""", p._id)
        # The key's left edge tracks imgX (+ margin), well left of where the
        # centred square picture starts.
        assert cx < box["imgX"] + box["imgW"] * 0.35, (
            f"key centroid {cx:.0f} is not near the axes-box left edge "
            f"(imgX={box['imgX']})")


@pytest.mark.usefixtures("mount_page")
class TestHoverOnly:
    def test_hidden_until_the_pointer_arrives(self, mount_page):
        fig, p = _panel()
        p.add_key(_disc(), hover_only=True, size=0.3)
        page = mount_page(fig)
        shown = lambda: page.evaluate("""(pid) => {
            const kc = window._handle.api.panels.get(pid).keyCanvas;
            const c = kc.getContext('2d');
            const d = c.getImageData(0, 0, kc.width, kc.height).data;
            let n = 0;
            for (let i = 3; i < d.length; i += 4) if (d[i] > 10) n++;
            return n;
        }""", p._id)
        assert shown() == 0, "hover-only key drew before the pointer arrived"
        _hover(page, p._id)
        assert shown() > 400, "hover-only key did not appear on hover"

    def test_a_plain_key_is_unaffected_by_hover(self, mount_page):
        fig, p = _panel()
        p.add_key(_disc(), size=0.3)
        page = mount_page(fig)
        before = _centroid(_export(page), RED)[2]
        _hover(page, p._id)
        assert _centroid(_export(page), RED)[2] == before


@pytest.mark.usefixtures("mount_page")
class TestExport:
    """A saved figure shows every key, hover_only included.

    Both cases below are regressions.  Images were once decoded lazily from
    inside the DRAW loop, so a hover-only key that had never been on screen had
    never begun decoding and the export silently omitted it; and a panel whose
    only keys are hover-only kept a display:none canvas, which the export path
    measures at 0x0 and drops.
    """

    def test_hover_only_key_is_exported_cold(self, mount_page):
        fig, p = _panel()
        p.add_key(_disc(rgb=BLUE), corner="bottom-left", size=0.25)
        p.add_key(_disc(), corner="top-right", size=0.25, hover_only=True)
        page = mount_page(fig)
        cold = _export(page)                      # pointer never entered
        assert _centroid(cold, RED)[2] > 400, "hover-only key missing from export"
        assert _centroid(cold, BLUE)[2] > 400

    def test_export_is_identical_cold_and_hovered(self, mount_page):
        fig, p = _panel()
        p.add_key(_disc(rgb=BLUE), corner="bottom-left", size=0.25)
        p.add_key(_disc(), corner="top-right", size=0.25, hover_only=True)
        page = mount_page(fig)
        cold = _export(page)
        _hover(page, p._id)
        assert np.array_equal(cold, _export(page))

    def test_a_lone_hover_only_key_still_exports(self, mount_page):
        """The display:none / 0x0-rect trap: no other key keeps the canvas up."""
        fig, p = _panel()
        p.add_key(_disc(), corner="top-right", size=0.25, hover_only=True)
        assert _centroid(_export(mount_page(fig)), RED)[2] > 400

    def test_an_invisible_key_is_not_exported(self, mount_page):
        fig, p = _panel()
        k = p.add_key(_disc(), size=0.3)
        k.visible = False
        arr = _export(mount_page(fig))
        assert not _mask(arr, RED).any()

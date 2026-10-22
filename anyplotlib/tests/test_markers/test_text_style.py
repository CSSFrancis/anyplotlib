"""
Font weight and outline (halo) for ``texts`` markers (GH #66).

``add_texts`` / ``add_text`` drew every label in a fixed ``{fs}px sans-serif``
with no way to make it bold or give it an outline, so a label over a busy image
was only as legible as its size allowed.  ``fontweight`` threads through to the
canvas font the way ``fontsize`` does; ``outline_color`` / ``outline_width``
stroke a halo under the fill.

Rotation, anchor alignment and ``$...$`` TeX routing for ``texts`` markers
extend the same thread: wire fields ``rotation`` (radians),
``halign``/``valign``, and the JS renderer typesets math segments instead of
showing raw markup.
"""
from __future__ import annotations

import numpy as np
import pytest

import anyplotlib as apl

RED, BLUE = (255, 0, 0), (0, 0, 255)


def _count(img: np.ndarray, rgb, tol: int = 60) -> int:
    a = img[..., :3].astype(int)
    return int((np.abs(a - np.array(rgb)).sum(axis=-1) < tol).sum())


def _plot2d():
    fig, ax = apl.subplots(1, 1, figsize=(400, 400))
    return fig, ax.imshow(np.zeros((40, 40), dtype=np.float32))


def _plot1d():
    fig, ax = apl.subplots(1, 1, figsize=(400, 400))
    return fig, ax.plot(np.zeros(40))


# Where a label lands well inside the plot area on each kind of panel.
_PLACE = {_plot2d: dict(offsets=[[4, 20]]),
          _plot1d: dict(offsets=[[0.1, 0.6]], transform="axes")}


# ══════════════════════════════════════════════════════════════════════════════
# API + wire format
# ══════════════════════════════════════════════════════════════════════════════

class TestWire:
    @pytest.mark.parametrize("make", [_plot2d, _plot1d])
    def test_defaults_are_normal_weight_and_no_outline(self, make):
        _, plot = make()
        w = plot.add_texts([[5, 5]], ["a"]).to_wire("gid")
        assert w["fontweight"] == "normal"
        assert "outline_color" not in w and "outline_width" not in w

    @pytest.mark.parametrize("make", [_plot2d, _plot1d])
    def test_weight_and_outline_reach_the_wire(self, make):
        _, plot = make()
        g = plot.add_texts([[5, 5]], ["a"], fontweight="bold",
                           outline_color="#000000", outline_width=4)
        w = g.to_wire("gid")
        assert w["fontweight"] == "bold"
        assert w["outline_color"] == "#000000"
        assert w["outline_width"] == 4.0

    def test_outline_width_defaults_when_only_the_colour_is_given(self):
        _, plot = _plot2d()
        w = plot.add_texts([[5, 5]], ["a"], outline_color="#fff").to_wire("gid")
        assert w["outline_width"] == 3.0

    def test_numeric_weight(self):
        _, plot = _plot2d()
        assert plot.add_texts([[5, 5]], ["a"], fontweight=600).to_wire("gid")[
            "fontweight"] == 600

    def test_add_text_forwards_the_style(self):
        _, plot = _plot2d()
        h = plot.add_text(5, 5, "a", fontweight="bold", outline_color="#000")
        w = h._group.to_wire("gid")
        assert (w["fontweight"], w["outline_color"]) == ("bold", "#000")

    def test_set_updates_live(self):
        _, plot = _plot2d()
        g = plot.add_texts([[5, 5]], ["a"])
        g.set(fontweight="bold", outline_color="#123456")
        w = plot._state["markers"][0]
        assert (w["fontweight"], w["outline_color"]) == ("bold", "#123456")
        g.set(outline_color=None)
        assert "outline_color" not in plot._state["markers"][0]

    @pytest.mark.parametrize("make", [_plot2d, _plot1d])
    def test_defaults_are_unrotated_left_top(self, make):
        _, plot = make()
        w = plot.add_texts([[5, 5]], ["a"]).to_wire("gid")
        assert w["rotation"] == 0.0
        assert (w["halign"], w["valign"]) == ("left", "top")

    @pytest.mark.parametrize("make", [_plot2d, _plot1d])
    def test_rotation_and_alignment_reach_the_wire(self, make):
        _, plot = make()
        w = plot.add_texts(
            [[5, 5]], ["a"], rotation=1.5707963,
            horizontalalignment="right", verticalalignment="bottom",
        ).to_wire("gid")
        assert w["rotation"] == pytest.approx(1.5707963)
        assert (w["halign"], w["valign"]) == ("right", "bottom")

    def test_mathtext_string_passes_through_the_wire(self):
        _, plot = _plot2d()
        w = plot.add_texts(
            [[5, 5]], [r"$\mathrm{Fe}_{\mathrm{Ka}}$"]
        ).to_wire("gid")
        assert w["texts"] == [r"$\mathrm{Fe}_{\mathrm{Ka}}$"]

    def test_registry_path_accepts_the_fields(self):
        # The registry API (what non-plot callers such as the hyperspy
        # backend use) takes the same style kwargs into the group data.
        _, plot = _plot2d()
        g = plot.markers.add("texts", offsets=[[5, 5]], texts=["a"],
                             rotation=0.25, horizontalalignment="center")
        w = g.to_wire("gid")
        assert w["rotation"] == pytest.approx(0.25)
        assert w["halign"] == "center"

    def test_set_updates_rotation_live(self):
        _, plot = _plot2d()
        g = plot.add_texts([[5, 5]], ["a"])
        g.set(rotation=0.5, horizontalalignment="center")
        w = plot._state["markers"][0]
        assert w["rotation"] == pytest.approx(0.5)
        assert w["halign"] == "center"


class TestValidation:
    @pytest.mark.parametrize("bad", ["heavy", "", 0, 1001, True, None])
    def test_bad_weight_is_refused(self, bad):
        _, plot = _plot2d()
        with pytest.raises(ValueError, match="fontweight"):
            plot.add_texts([[5, 5]], ["a"], fontweight=bad)

    @pytest.mark.parametrize("bad", [-1, "3", float("nan")])
    def test_bad_outline_width_is_refused(self, bad):
        _, plot = _plot2d()
        with pytest.raises(ValueError, match="outline_width"):
            plot.add_texts([[5, 5]], ["a"], outline_color="#000",
                           outline_width=bad)

    def test_bad_outline_colour_is_refused(self):
        _, plot = _plot2d()
        with pytest.raises(ValueError, match="outline_color"):
            plot.add_texts([[5, 5]], ["a"], outline_color=(0, 0, 0))

    def test_set_refuses_before_touching_the_group(self):
        _, plot = _plot2d()
        g = plot.add_texts([[5, 5]], ["a"])
        with pytest.raises(ValueError):
            g.set(fontweight="extra-bold")
        assert g._data["fontweight"] == "normal"

    @pytest.mark.parametrize("bad", ["90", None, float("nan"), float("inf"), True])
    def test_bad_rotation_is_refused(self, bad):
        _, plot = _plot2d()
        with pytest.raises(ValueError, match="rotation"):
            plot.add_texts([[5, 5]], ["a"], rotation=bad)

    @pytest.mark.parametrize("bad", ["centre", "top", None])
    def test_bad_horizontalalignment_is_refused(self, bad):
        _, plot = _plot2d()
        with pytest.raises(ValueError, match="horizontalalignment"):
            plot.add_texts([[5, 5]], ["a"], horizontalalignment=bad)

    @pytest.mark.parametrize("bad", ["middle", "left", None])
    def test_bad_verticalalignment_is_refused(self, bad):
        _, plot = _plot2d()
        with pytest.raises(ValueError, match="verticalalignment"):
            plot.add_texts([[5, 5]], ["a"], verticalalignment=bad)


# ══════════════════════════════════════════════════════════════════════════════
# Rendering
# ══════════════════════════════════════════════════════════════════════════════

class TestRendering:
    @pytest.mark.parametrize("make", [_plot2d, _plot1d])
    def test_bold_puts_more_ink_down(self, take_screenshot, make):
        ink = {}
        for weight in ("normal", "bold"):
            fig, plot = make()
            plot.add_texts(texts=["WWWW"], color="#ff0000", fontsize=28,
                           fontweight=weight, **_PLACE[make])
            ink[weight] = _count(take_screenshot(fig), RED)
        assert ink["normal"] > 0, "the label did not render"
        assert ink["bold"] > ink["normal"] * 1.15, ink

    @pytest.mark.parametrize("make", [_plot2d, _plot1d])
    def test_outline_draws_a_halo_in_its_own_colour(self, take_screenshot, make):
        fig, plot = make()
        plot.add_texts(texts=["HALO"], color="#0000ff", fontsize=28,
                       **_PLACE[make])
        base = take_screenshot(fig)

        fig, plot = make()
        plot.add_texts(texts=["HALO"], color="#0000ff", fontsize=28,
                       outline_color="#ff0000", outline_width=4, **_PLACE[make])
        halo = take_screenshot(fig)

        assert _count(base, RED) == 0
        assert _count(halo, RED) > 100, "no outline pixels on the canvas"
        # The fill sits on top of the stroke: the glyph body keeps its colour.
        assert _count(halo, BLUE) > 0.5 * _count(base, BLUE)

    @pytest.mark.parametrize("make", [_plot2d, _plot1d])
    def test_bold_survives_tex_typesetting(self, take_screenshot, make):
        # _drawTex rebuilds the canvas font, so the marker's weight must be
        # handed to it or math labels silently drop back to normal.
        ink = {}
        for weight in ("normal", "bold"):
            fig, plot = make()
            plot.add_texts(texts=[r"$\mathrm{WWWW}$"], color="#ff0000",
                           fontsize=28, fontweight=weight, **_PLACE[make])
            ink[weight] = _count(take_screenshot(fig), RED)
        assert ink["normal"] > 0, "the label did not render"
        assert ink["bold"] > ink["normal"] * 1.15, ink

    @pytest.mark.parametrize("text", ["$$$", "Cost $5"])
    def test_odd_dollars_stay_literal(self, take_screenshot, text):
        # Like matplotlib, an odd dollar count is plain text: the dollars
        # are drawn, not swallowed as math delimiters.
        ink = {}
        for s in (text, text.replace("$", "")):
            fig, plot = _plot2d()
            plot.add_texts(texts=[s], color="#ff0000", fontsize=28,
                           **_PLACE[_plot2d])
            ink[s] = _count(take_screenshot(fig), RED)
        assert ink[text] > ink[text.replace("$", "")] + 20, ink

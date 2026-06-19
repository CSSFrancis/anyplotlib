"""
PlotXY — the blank data-coordinate 2-D axis (matplotlib ``transData`` +
``PathCollection`` model): ``axes2d`` + ``scatter`` / ``plot`` / ``fill`` /
``text`` in data coords, with ``set_xlim`` / ``set_ylim`` / ``set_aspect``.
"""
import numpy as np

import anyplotlib as apl


def test_axes2d_creates_plotxy():
    fig, ax = apl.subplots()
    xy = ax.axes2d(xlim=(-1, 1), ylim=(-0.5, 0.9), aspect="equal")
    assert isinstance(xy, apl.PlotXY)
    assert xy.get_xlim() == (-1.0, 1.0)
    assert xy.get_ylim() == (-0.5, 0.9)
    assert xy.get_aspect() == "equal"


def test_set_lims_and_aspect():
    fig, ax = apl.subplots()
    xy = ax.axes2d()
    xy.set_xlim(-2, 3)
    xy.set_ylim(-1, 5)
    assert xy.get_xlim() == (-2.0, 3.0)
    assert xy.get_ylim() == (-1.0, 5.0)
    xy.set_aspect("equal")
    assert xy.get_aspect() == "equal"
    xy.set_aspect("auto")
    assert xy.get_aspect() is None


def test_artists_are_data_coord_collections():
    fig, ax = apl.subplots()
    xy = ax.axes2d(xlim=(0, 1), ylim=(0, 1))
    xy.scatter([0.1, 0.9], [0.2, 0.8], c=["#ff0000", "#00ff00"], s=8)
    xy.plot([0, 1, 0.5], [0, 0, 1], color="#ffffff")
    xy.fill([0, 1, 0.5], [0, 0, 1], facecolor="#eeeeee")
    xy.text(0.5, 0.95, r"$[111]$")

    types = {m["type"] for m in xy.list_markers()}
    assert {"points", "lines", "polygons", "texts"} <= types

    d = xy.to_state_dict()
    # Reuses the 1-D data→canvas transform (matplotlib transLimits→transAxes),
    # so every collection is in DATA coords — not image pixels.
    assert d["kind"] == "1d"
    for grp in d["markers"]:
        assert grp.get("transform", "data") == "data"


def test_scatter_returns_collection_with_offsets():
    fig, ax = apl.subplots()
    xy = ax.axes2d()
    xy.scatter(np.array([0.0, 0.5, 1.0]), np.array([0.0, 0.5, 1.0]), s=6)
    # PathCollection-style: one collection holding all three offsets.
    pts = next(m for m in xy.list_markers() if m["type"] == "points")
    assert pts["n"] == 3


def test_render_is_chromatic(take_screenshot):
    """End-to-end: a filled triangle + coloured scatter + labels in data coords
    must actually draw (canvas is chromatic, not blank)."""
    fig, ax = apl.subplots(figsize=(360, 320))
    xy = ax.axes2d(xlim=(-0.05, 0.4), ylim=(-0.05, 0.4), aspect="equal")
    xy.fill([0.0, 0.36, 0.0, 0.0], [0.0, 0.0, 0.36, 0.0],
            facecolor="#223", edgecolor="#ffffff")
    xy.scatter([0.05, 0.2, 0.3], [0.05, 0.1, 0.02],
               c=["#ff3030", "#30ff60", "#3060ff"], s=10)
    xy.text(0.0, 0.37, "[111]", color="#ffffff")

    arr = take_screenshot(fig)               # H×W×C uint8
    rgb = arr[..., :3].astype(int)
    spread = int((rgb.max(axis=2) - rgb.min(axis=2)).max())
    assert spread > 60                       # genuinely coloured, not greyscale

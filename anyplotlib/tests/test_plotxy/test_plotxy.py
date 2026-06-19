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


def _red_bbox(arr):
    """(x0, x1, y0, y1) bounding box of red-ish pixels, or None."""
    rgb = arr[..., :3].astype(int)
    mask = (rgb[..., 0] > 150) & (rgb[..., 1] < 90) & (rgb[..., 2] < 90)
    ys, xs = np.where(mask)
    if xs.size == 0:
        return None
    return int(xs.min()), int(xs.max()), int(ys.min()), int(ys.max())


def test_aspect_equal_renders_square(take_screenshot):
    """Equal x & y spans drawn into a WIDE (2:1) panel: ``aspect="equal"`` must
    apply matplotlib's ``apply_aspect`` — shrink + centre the data box to a
    square (one data unit equal px on x & y), NOT stretch it to the panel."""
    fig, ax = apl.subplots(figsize=(640, 320))
    xy = ax.axes2d(xlim=(0, 1), ylim=(0, 1), aspect="equal")
    xy.fill([0, 1, 0], [0, 0, 1], facecolor="#ff0000", edgecolor="#ff0000", alpha=1.0)

    bb = _red_bbox(take_screenshot(fig))
    assert bb is not None
    w, h = bb[1] - bb[0], bb[3] - bb[2]
    assert 0.8 < (w / h) < 1.25               # ~square, not stretched 2:1


def test_pcolormesh_builds_polygon_mesh():
    """``pcolormesh`` → one polygons collection, one quad per (N, M) cell;
    masked / non-finite cells are dropped (so an orix sector histogram clips
    itself to the fundamental sector)."""
    fig, ax = apl.subplots()
    xy = ax.axes2d()
    xe = np.linspace(0, 1, 4)            # 3 columns of cells
    ye = np.linspace(0, 1, 3)            # 2 rows of cells
    X, Y = np.meshgrid(xe, ye, indexing="ij")        # (4, 3) corners
    field = np.arange(3 * 2).reshape(3, 2).astype(float)   # (3, 2) cells
    xy.pcolormesh(X, Y, field)
    poly = next(g for g in xy.to_state_dict()["markers"] if g["type"] == "polygons")
    assert len(poly["vertices_list"]) == 6                 # 3*2 cells
    assert isinstance(poly["fill_color"], list)            # per-cell colours
    assert len(poly["fill_color"]) == 6

    masked = np.ma.array(field, mask=[[True, False], [False, False], [False, False]])
    xy2 = ax.axes2d()
    xy2.pcolormesh(X, Y, masked)
    poly2 = next(g for g in xy2.to_state_dict()["markers"] if g["type"] == "polygons")
    assert len(poly2["vertices_list"]) == 5                # one cell masked out


def test_pcolormesh_renders_gradient(take_screenshot):
    """A scalar field drawn as a data-coord quad mesh (matplotlib ``pcolormesh``)
    must render many distinct colormap colours — the primitive an IPF / pole
    density heatmap needs."""
    fig, ax = apl.subplots(figsize=(320, 300))
    xy = ax.axes2d(xlim=(0, 1), ylim=(0, 1), aspect="equal")
    n = 16
    xe = ye = np.linspace(0, 1, n + 1)
    X, Y = np.meshgrid(xe, ye, indexing="ij")
    gx, gy = np.meshgrid(np.linspace(0, 1, n), np.linspace(0, 1, n), indexing="ij")
    xy.pcolormesh(X, Y, gx + gy, cmap="viridis")          # smooth ramp

    arr = take_screenshot(fig)
    rgb = arr[..., :3].astype(int)
    assert int((rgb.max(2) - rgb.min(2)).max()) > 60       # chromatic
    cols = {tuple(c) for c in rgb.reshape(-1, 3)[::29]}
    assert len(cols) > 20                                  # a gradient, not flat


def test_aspect_auto_fills_panel(take_screenshot):
    """Without ``aspect="equal"`` the same triangle stretches to fill the wide
    panel (the data box follows the panel aspect) — the contrast that proves the
    equal-aspect step is actually doing something."""
    fig, ax = apl.subplots(figsize=(640, 320))
    xy = ax.axes2d(xlim=(0, 1), ylim=(0, 1))          # aspect None → fill panel
    xy.fill([0, 1, 0], [0, 0, 1], facecolor="#ff0000", edgecolor="#ff0000", alpha=1.0)

    bb = _red_bbox(take_screenshot(fig))
    assert bb is not None
    w, h = bb[1] - bb[0], bb[3] - bb[2]
    assert (w / h) > 1.4                       # stretched wide (panel is 2:1)

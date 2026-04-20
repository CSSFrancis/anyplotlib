"""
Tests for InsetAxes — floating overlay inset panels.

Covers:
  - Creation via fig.add_inset()
  - layout_json inset_specs content
  - All four corners
  - Multi-inset stacking (same corner)
  - State transitions (minimize / maximize / restore)
  - Python-side property inset_state
  - _on_event dispatch for on_inset_state_change
  - pcolormesh and 1D insets
  - Invalid corner raises ValueError
  - Figure resize keeps inset fracs correct
  - plot._id registered in _plots_map
"""
import json
import numpy as np
import pytest
import anyplotlib as apl
from anyplotlib.figure_plots import InsetAxes


# ── helpers ──────────────────────────────────────────────────────────────────

def _make_fig():
    fig, ax = apl.subplots(1, 1, figsize=(640, 480))
    ax.imshow(np.zeros((64, 64)))
    return fig


def _inset_spec(fig, plot_id):
    layout = json.loads(fig.layout_json)
    return next(s for s in layout["inset_specs"] if s["id"] == plot_id)


# ── creation ─────────────────────────────────────────────────────────────────

def test_add_inset_returns_inset_axes():
    fig = _make_fig()
    inset = fig.add_inset(0.3, 0.3, corner="top-right", title="T")
    assert isinstance(inset, InsetAxes)


def test_inset_imshow_returns_plot2d():
    from anyplotlib import Plot2D
    fig   = _make_fig()
    inset = fig.add_inset(0.3, 0.3)
    plot  = inset.imshow(np.zeros((32, 32)))
    assert isinstance(plot, Plot2D)


def test_inset_plot_returns_plot1d():
    from anyplotlib import Plot1D
    fig   = _make_fig()
    inset = fig.add_inset(0.3, 0.2, corner="bottom-left")
    plot  = inset.plot(np.zeros(64))
    assert isinstance(plot, Plot1D)


def test_inset_pcolormesh_returns_plotmesh():
    from anyplotlib import PlotMesh
    fig   = _make_fig()
    inset = fig.add_inset(0.3, 0.3, corner="bottom-right")
    plot  = inset.pcolormesh(np.zeros((8, 8)),
                              np.linspace(0, 1, 9), np.linspace(0, 1, 9))
    assert isinstance(plot, PlotMesh)


# ── layout JSON ──────────────────────────────────────────────────────────────

def test_inset_spec_in_layout_json():
    fig   = _make_fig()
    inset = fig.add_inset(0.25, 0.25, corner="top-left", title="Phase")
    plot  = inset.imshow(np.zeros((32, 32)))

    layout = json.loads(fig.layout_json)
    assert "inset_specs" in layout
    assert len(layout["inset_specs"]) == 1
    spec = layout["inset_specs"][0]
    assert spec["id"]    == plot._id
    assert spec["kind"]  == "2d"
    assert spec["corner"] == "top-left"
    assert spec["title"]  == "Phase"
    assert spec["w_frac"] == pytest.approx(0.25)
    assert spec["h_frac"] == pytest.approx(0.25)
    assert spec["inset_state"] == "normal"


def test_multiple_insets_in_layout():
    fig = _make_fig()
    for corner in ("top-right", "top-left", "bottom-right", "bottom-left"):
        inset = fig.add_inset(0.2, 0.2, corner=corner, title=corner)
        inset.imshow(np.zeros((16, 16)))

    layout = json.loads(fig.layout_json)
    assert len(layout["inset_specs"]) == 4
    corners = {s["corner"] for s in layout["inset_specs"]}
    assert corners == {"top-right", "top-left", "bottom-right", "bottom-left"}


def test_inset_panel_width_height_computed_from_fracs():
    fig = _make_fig()  # 640×480
    inset = fig.add_inset(0.25, 0.30, corner="top-right")
    inset.imshow(np.zeros((32, 32)))

    spec = _inset_spec(fig, inset._plot._id)
    assert spec["panel_width"]  == max(64, round(640 * 0.25))
    assert spec["panel_height"] == max(64, round(480 * 0.30))


def test_inset_registered_in_plots_map():
    fig   = _make_fig()
    inset = fig.add_inset(0.3, 0.3)
    plot  = inset.imshow(np.zeros((32, 32)))
    assert plot._id in fig._plots_map
    assert plot._id in fig._insets_map


# ── stacking (same corner) ───────────────────────────────────────────────────

def test_two_insets_same_corner():
    fig = _make_fig()
    i1  = fig.add_inset(0.25, 0.25, corner="top-right", title="A")
    i1.imshow(np.zeros((32, 32)))
    i2  = fig.add_inset(0.25, 0.25, corner="top-right", title="B")
    i2.imshow(np.zeros((32, 32)))

    layout = json.loads(fig.layout_json)
    tr = [s for s in layout["inset_specs"] if s["corner"] == "top-right"]
    assert len(tr) == 2


# ── state transitions ────────────────────────────────────────────────────────

@pytest.mark.parametrize("method,expected", [
    ("minimize", "minimized"),
    ("maximize", "maximized"),
    ("restore",  "normal"),
])
def test_state_transition(method, expected):
    fig   = _make_fig()
    inset = fig.add_inset(0.3, 0.3)
    plot  = inset.imshow(np.zeros((32, 32)))

    getattr(inset, method)()
    assert inset.inset_state == expected
    assert _inset_spec(fig, plot._id)["inset_state"] == expected


def test_state_idempotent():
    """Calling minimize() twice doesn't trigger an extra _push_layout."""
    fig   = _make_fig()
    inset = fig.add_inset(0.3, 0.3)
    inset.imshow(np.zeros((32, 32)))

    inset.minimize()
    layout_before = fig.layout_json
    inset.minimize()  # already minimized — should be a no-op
    assert fig.layout_json == layout_before


def test_restore_from_minimized():
    fig   = _make_fig()
    inset = fig.add_inset(0.3, 0.3)
    inset.imshow(np.zeros((32, 32)))
    inset.minimize()
    inset.restore()
    assert inset.inset_state == "normal"


def test_maximize_then_restore():
    fig   = _make_fig()
    inset = fig.add_inset(0.3, 0.3)
    inset.imshow(np.zeros((32, 32)))
    inset.maximize()
    assert inset.inset_state == "maximized"
    inset.restore()
    assert inset.inset_state == "normal"


# ── on_inset_state_change event (JS→Python path) ─────────────────────────────

def test_on_event_inset_state_change():
    fig   = _make_fig()
    inset = fig.add_inset(0.3, 0.3)
    plot  = inset.imshow(np.zeros((32, 32)))

    # Simulate a JS button click delivering on_inset_state_change
    fig.event_json = json.dumps({
        "source":     "js",
        "panel_id":   plot._id,
        "event_type": "on_inset_state_change",
        "new_state":  "minimized",
    })

    assert inset.inset_state == "minimized"
    assert _inset_spec(fig, plot._id)["inset_state"] == "minimized"


def test_on_event_inset_state_restore_via_event():
    fig   = _make_fig()
    inset = fig.add_inset(0.3, 0.3)
    plot  = inset.imshow(np.zeros((32, 32)))
    inset.minimize()

    fig.event_json = json.dumps({
        "source":     "js",
        "panel_id":   plot._id,
        "event_type": "on_inset_state_change",
        "new_state":  "normal",
    })
    assert inset.inset_state == "normal"


# ── figure resize updates inset dimensions ───────────────────────────────────

def test_resize_updates_inset_panel_size():
    fig   = _make_fig()
    inset = fig.add_inset(0.3, 0.3)
    plot  = inset.imshow(np.zeros((32, 32)))

    fig.fig_width  = 800
    fig.fig_height = 600

    spec = _inset_spec(fig, plot._id)
    assert spec["panel_width"]  == max(64, round(800 * 0.3))
    assert spec["panel_height"] == max(64, round(600 * 0.3))


# ── corner validation ─────────────────────────────────────────────────────────

def test_invalid_corner_raises():
    fig = _make_fig()
    with pytest.raises(ValueError, match="corner"):
        fig.add_inset(0.3, 0.3, corner="centre").imshow(np.zeros((4, 4)))


# ── repr ─────────────────────────────────────────────────────────────────────

def test_repr():
    fig   = _make_fig()
    inset = fig.add_inset(0.28, 0.28, corner="top-right", title="T")
    inset.imshow(np.zeros((32, 32)))
    r = repr(inset)
    assert "InsetAxes" in r
    assert "top-right" in r
    assert "normal" in r


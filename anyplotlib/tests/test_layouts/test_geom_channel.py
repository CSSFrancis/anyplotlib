"""Tests for the geometry channel: heavy geometry rides a separate trait and
is re-sent only when it actually changes (view updates don't re-transmit it)."""
from __future__ import annotations

import json
import numpy as np
import anyplotlib as apl


def _scatter():
    fig = apl.Figure(figsize=(300, 300))
    ax = fig.add_subplot(apl.GridSpec(1, 1)[0, 0])
    v = ax.scatter3d(np.zeros(8), np.zeros(8), np.zeros(8),
                     bounds=((-1, 1),) * 3,
                     colors=np.tile([1, 2, 3], (8, 1)).astype(np.uint8))
    return fig, v


class TestGeomChannel:
    def test_geom_trait_allocated(self):
        fig, v = _scatter()
        assert fig.has_trait(f"panel_{v._id}_geom")

    def test_view_trait_excludes_geometry(self):
        fig, v = _scatter()
        view = json.loads(getattr(fig, f"panel_{v._id}_json"))
        for k in ("vertices_b64", "faces_b64", "point_colors_b64", "colormap_data"):
            assert k not in view, f"{k} leaked into the view trait"
        assert view["_geom_rev"] >= 1

    def test_geom_trait_contains_geometry(self):
        fig, v = _scatter()
        geom = json.loads(getattr(fig, f"panel_{v._id}_geom"))
        assert "vertices_b64" in geom and "point_colors_b64" in geom

    def test_highlight_does_not_resend_geometry(self):
        fig, v = _scatter()
        gkey = f"panel_{v._id}_geom"
        before = getattr(fig, gkey)
        rev_before = json.loads(getattr(fig, f"panel_{v._id}_json"))["_geom_rev"]
        v.set_highlight(0.1, 0.2, 0.3)
        assert getattr(fig, gkey) == before, "geometry re-sent on highlight move"
        rev_after = json.loads(getattr(fig, f"panel_{v._id}_json"))["_geom_rev"]
        assert rev_after == rev_before, "geom_rev bumped without geometry change"
        assert json.loads(getattr(fig, f"panel_{v._id}_json"))["highlight"]["x"] == 0.1

    def test_view_change_does_not_resend_geometry(self):
        fig, v = _scatter()
        before = getattr(fig, f"panel_{v._id}_geom")
        v.set_view(azimuth=42, elevation=15)
        assert getattr(fig, f"panel_{v._id}_geom") == before
        assert json.loads(getattr(fig, f"panel_{v._id}_json"))["azimuth"] == 42

    def test_geometry_change_bumps_rev_and_resends(self):
        fig, v = _scatter()
        gkey = f"panel_{v._id}_geom"
        before = getattr(fig, gkey)
        rev_before = json.loads(getattr(fig, f"panel_{v._id}_json"))["_geom_rev"]
        v.set_data(np.ones(8) * 3, np.ones(8) * 4, np.ones(8) * 5)  # new geometry
        assert getattr(fig, gkey) != before, "geometry change not re-sent"
        rev_after = json.loads(getattr(fig, f"panel_{v._id}_json"))["_geom_rev"]
        assert rev_after == rev_before + 1, "geom_rev not bumped on geometry change"

    def test_plot_without_geom_keys_unaffected(self):
        # Plot1D declares no _GEOM_KEYS → single-trait path, no geom trait.
        fig = apl.Figure(figsize=(300, 200))
        ax = fig.add_subplot(apl.GridSpec(1, 1)[0, 0])
        p = ax.plot(np.sin(np.linspace(0, 6, 64)))
        assert not fig.has_trait(f"panel_{p._id}_geom")
        view = json.loads(getattr(fig, f"panel_{p._id}_json"))
        assert "data_b64" in view   # geometry stays inline for non-split plots

"""Smoke test — run with: python3 test_figure.py"""
import numpy as np
import viewer as vw
import json

# --- subplots 2x1 ---
fig, axs = vw.subplots(2, 1, figsize=(400, 300))
assert axs.shape == (2,), f"Expected shape (2,), got {axs.shape}"

v2d = axs[0].imshow(np.random.rand(64, 64))
v1d = axs[1].plot(np.sin(np.linspace(0, 6, 128)))

# layout_json sanity
L = json.loads(fig.layout_json)
assert L["nrows"] == 2, f"nrows={L['nrows']}"
assert len(L["panel_specs"]) == 2, f"panel_specs={L['panel_specs']}"

# panel trait exists
assert fig.has_trait(f"panel_{v2d._id}_json"), "missing panel trait for v2d"
assert fig.has_trait(f"panel_{v1d._id}_json"), "missing panel trait for v1d"

# marker add
mg = v2d.add_circles(np.array([[16., 16.], [32., 32.]]),
                     name="g1", facecolors="red", radius=5)
assert v2d.markers["circles"]["g1"]._data["radius"] == 5

# marker live update
v2d.markers["circles"]["g1"].set(radius=8)
assert v2d.markers["circles"]["g1"]._data["radius"] == 8

# auto-name
mg2 = v2d.add_circles(np.array([[48., 48.]]), radius=3)
assert "circles_1" in v2d.markers["circles"], \
    f"auto-name failed: {list(v2d.markers['circles'].keys())}"

# 1D markers
v1d.add_vlines([1.0, 2.0, 3.0], name="peaks")
assert "peaks" in v1d.markers["vlines"]

# GridSpec
gs = vw.GridSpec(2, 3, width_ratios=[2, 1, 1])
s = gs[0, :]
assert s.col_start == 0 and s.col_stop == 3
s2 = gs[1, 1]
assert s2.row_start == 1 and s2.col_start == 1

# subplots squeeze shapes
fig1, ax1 = vw.subplots(1, 1)
assert not hasattr(ax1, 'shape'), "1x1 should return scalar Axes"

fig2, axs2 = vw.subplots(1, 3)
assert axs2.shape == (3,), f"1x3 should be 1-D, got {axs2.shape}"

fig3, axs3 = vw.subplots(2, 2)
assert axs3.shape == (2, 2), f"2x2 should be 2-D, got {axs3.shape}"

print("ALL TESTS PASSED")


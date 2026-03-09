"""Quick smoke-test for PlotMesh / pcolormesh support."""
import numpy as np
from anyplotlib.figure_plots import PlotMesh, _resample_mesh
from anyplotlib.markers import MarkerRegistry

# ── _resample_mesh ────────────────────────────────────────────────────────────
x_edges = np.logspace(-1, 2, 13)   # 12 cols, 13 edges
y_edges = np.linspace(0, 10, 9)    # 8 rows, 9 edges
data = np.arange(8 * 12, dtype=float).reshape(8, 12)

out = _resample_mesh(data, x_edges, y_edges)
assert out.shape == (8, 12), f"wrong shape {out.shape}"
print("_resample_mesh OK:", out.shape)

# Uniform edges → identity (each output cell maps to same input cell)
x_uni = np.arange(13, dtype=float)
y_uni = np.arange(9, dtype=float)
out_uni = _resample_mesh(data, x_uni, y_uni)
assert (out_uni == data).all(), "uniform resample should be identity"
print("_resample_mesh uniform identity OK")

# ── PlotMesh construction ─────────────────────────────────────────────────────
mesh = PlotMesh(data, x_edges=x_edges, y_edges=y_edges, units="nm")
assert mesh._state["is_mesh"] is True
assert mesh._state["kind"] == "2d"
assert len(mesh._state["x_axis"]) == 13   # edges, not centres
assert len(mesh._state["y_axis"]) == 9
assert mesh._state["image_width"] == 12
assert mesh._state["image_height"] == 8
assert "scale_x" not in mesh._state
assert "scale_y" not in mesh._state
print("PlotMesh state OK")

# ── Default edges ─────────────────────────────────────────────────────────────
m2 = PlotMesh(data)
assert m2._state["x_axis"] == list(np.arange(13, dtype=float))
assert m2._state["y_axis"] == list(np.arange(9, dtype=float))
print("Default edges OK")

# ── Edge-length validation ────────────────────────────────────────────────────
try:
    PlotMesh(data, x_edges=np.arange(10))   # should be 13
    raise AssertionError("should have raised")
except ValueError as e:
    print(f"Edge validation OK: {e}")

# ── Marker restriction — only circles and lines ───────────────────────────────
try:
    mesh.markers.add("rectangles", "r1", offsets=[[1, 1]], widths=[5], heights=[5])
    raise AssertionError("rectangles should have been rejected")
except ValueError as e:
    print(f"Marker restriction OK (rectangles): {e}")

try:
    mesh.markers.add("arrows", "a1", offsets=[[1, 1]], U=[1], V=[0])
    raise AssertionError("arrows should have been rejected")
except ValueError as e:
    print(f"Marker restriction OK (arrows): {e}")

# Circles and lines should work
mesh.add_circles([[1.0, 2.0], [5.0, 7.0]], name="pts", radius=2)
mesh.add_lines([[[1.0, 2.0], [5.0, 7.0]]], name="segs")
print("add_circles + add_lines OK")

# ── to_state_dict ─────────────────────────────────────────────────────────────
sd = mesh.to_state_dict()
assert sd["is_mesh"] is True
assert sd["x_axis"] == x_edges.tolist()
assert len(sd["markers"]) == 2
print("to_state_dict OK")

# ── update() ─────────────────────────────────────────────────────────────────
mesh.update(data * 2)
print("update() (no push, fig=None) OK")

# update with new edges
new_x = np.linspace(0, 1, 13)
mesh.update(data, x_edges=new_x)
assert mesh._state["x_axis"] == new_x.tolist()
print("update() with new x_edges OK")

# ── Axes.pcolormesh integration ───────────────────────────────────────────────
import anyplotlib as vw
fig, ax = vw.subplots(1, 1, figsize=(400, 400))
m = ax.pcolormesh(data, x_edges=x_edges, y_edges=y_edges, units="nm")
assert isinstance(m, PlotMesh)
assert m._fig is fig
print("Axes.pcolormesh integration OK")

# ── layout kind is '2d' for PlotMesh ─────────────────────────────────────────
import json
layout = json.loads(fig.layout_json)
panel = layout["panel_specs"][0]
assert panel["kind"] == "2d"
print("layout kind='2d' for PlotMesh OK")

print()
print("All checks passed!")


"""
Inverse Pole Figure (IPF) Density Map
=====================================

An EBSD-style orientation explorer pairing a map with a *density* IPF:

* **Left panel** — IPF-Z orientation map of a synthetic polycrystal, colored
  with the standard cubic IPF key (red = ⟨001⟩, green = ⟨011⟩, blue = ⟨111⟩).
* **Right panel** — the **inverse pole figure as a density heat map**: every
  grain's sample-Z direction (in crystal coords, folded into the cubic
  fundamental sector) is stereographically projected and binned, then drawn as
  a smooth heat map clipped to the curved sector boundary.

The **best-fit orientation** is the *modal* (peak-density) bin of the heat map:
it is ringed on the IPF and the grains nearest that orientation are highlighted
on the map.  Drag the crosshair on the map: a marker tracks where the grain
under the cursor lands in the IPF.

The heat map uses :meth:`~anyplotlib.plotxy.PlotXY.pcolormesh` on a regular
grid, which renders as a single stretched raster — fast to load and to update,
even for fine grids.
"""

import numpy as np
import anyplotlib as apl

rng = np.random.default_rng(42)

# ── 1. Synthetic polycrystal: nearest-seed grain map ────────────────────────
H = W = 192
N_GRAINS = 400

seeds = rng.uniform(0, [H, W], size=(N_GRAINS, 2))
yy, xx = np.mgrid[0:H, 0:W]
d2 = (yy[..., None] - seeds[:, 0]) ** 2 + (xx[..., None] - seeds[:, 1]) ** 2
grain_id = np.argmin(d2, axis=-1)                       # (H, W) labels


# ── 2. Random orientation per grain (uniform rotations via quaternions) ─────
def random_rotations(n):
    """Uniform random rotation matrices, shape (n, 3, 3) (Shoemake method)."""
    u1, u2, u3 = rng.random((3, n))
    q = np.stack([
        np.sqrt(1 - u1) * np.sin(2 * np.pi * u2),
        np.sqrt(1 - u1) * np.cos(2 * np.pi * u2),
        np.sqrt(u1) * np.sin(2 * np.pi * u3),
        np.sqrt(u1) * np.cos(2 * np.pi * u3),
    ], axis=1)                                          # (n, 4) unit quats
    x, y, z, w = q.T
    return np.stack([
        np.stack([1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)], -1),
        np.stack([2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)], -1),
        np.stack([2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)], -1),
    ], axis=1)


rotations = random_rotations(N_GRAINS)

# Sample-Z expressed in each grain's crystal frame: d = Rᵀ · ẑ
dirs = rotations[:, 2, :]                               # row 2 of R == Rᵀ·ẑ

# Add a mild crystallographic texture so the IPF has a real modal peak (a
# fully random polycrystal would give a featureless density).  Pull a third of
# the grains toward a preferred sample-Z direction with Gaussian scatter.
n_tex = N_GRAINS // 3
pref = np.array([0.18, 0.62, 0.77])                    # near the 011–111 edge
pref /= np.linalg.norm(pref)
scatter = pref + rng.normal(scale=0.18, size=(n_tex, 3))
dirs[:n_tex] = scatter / np.linalg.norm(scatter, axis=1, keepdims=True)

# ── 3. Reduce to the cubic fundamental sector and IPF-color ────────────────
# For cubic symmetry, sorting |components| ascending lands every direction
# in the standard 001–011–111 stereographic triangle (a ≤ b ≤ c).
reduced = np.sort(np.abs(dirs), axis=1)                 # (N_GRAINS, 3)
a, b, c = reduced.T

# Classic IPF key: distance to each triangle corner → R, G, B
rgb = np.stack([c - b, b - a, a], axis=1)
rgb /= rgb.max(axis=1, keepdims=True) + 1e-12           # vivid normalisation
grain_rgb_u8 = (rgb * 255).astype(np.uint8)             # (N_GRAINS, 3)

ipf_map = grain_rgb_u8[grain_id]                        # (H, W, 3) true-color


# ── 4. Stereographic projection into the IPF triangle ──────────────────────
def stereo(v):
    """Equal-angle (stereographic) projection of upper-hemisphere unit dirs."""
    v = np.atleast_2d(v).astype(float)
    v = v / np.linalg.norm(v, axis=-1, keepdims=True)
    x, y, z = v[..., 0], v[..., 1], v[..., 2]
    denom = 1.0 + z
    return np.stack([x / denom, y / denom], axis=-1)


def _arc(v0, v1, n=160):
    """Great-circle arc between two unit vectors, projected to the plane."""
    v0 = v0 / np.linalg.norm(v0)
    v1 = v1 / np.linalg.norm(v1)
    omega = np.arccos(np.clip(v0 @ v1, -1, 1))
    t = np.linspace(0, 1, n)[:, None]
    s = (np.sin((1 - t) * omega) * v0 + np.sin(t * omega) * v1) / np.sin(omega)
    return stereo(s)


# Fundamental-sector corners and curved boundary (001 → 011 → 111 → 001)
C001 = np.array([0.0, 0.0, 1.0])
C011 = np.array([0.0, 1.0, 1.0])
C111 = np.array([1.0, 1.0, 1.0])
boundary = np.concatenate([_arc(C001, C011), _arc(C011, C111), _arc(C111, C001)])

P = stereo(reduced)                                     # (N_GRAINS, 2) projected dirs
x0, x1 = float(boundary[:, 0].min()), float(boundary[:, 0].max())
y0, y1 = float(boundary[:, 1].min()), float(boundary[:, 1].max())


# ── 5. Density histogram on a regular grid → heat map ──────────────────────
def _in_polygon(px, py, poly):
    """Vectorised ray-casting point-in-polygon test (no SciPy/Matplotlib)."""
    px = np.asarray(px); py = np.asarray(py)
    inside = np.zeros(px.shape, dtype=bool)
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]; xj, yj = poly[j]
        cond = ((yi > py) != (yj > py)) & \
               (px < (xj - xi) * (py - yi) / (yj - yi + 1e-30) + xi)
        inside ^= cond
        j = i
    return inside


N = 128
xe = np.linspace(x0, x1, N + 1)
ye = np.linspace(y0, y1, N + 1)
counts, _, _ = np.histogram2d(P[:, 0], P[:, 1], bins=[xe, ye])   # (Nx, Ny)
H_density = counts.T                                            # (Ny, Nx): rows=y

# Smooth a little so the modal peak is robust (separable box blur).
def _blur(a, k=3):
    pad = k // 2
    ap = np.pad(a, pad, mode="edge")
    out = np.zeros_like(a)
    for dy in range(k):
        for dx in range(k):
            out += ap[dy:dy + a.shape[0], dx:dx + a.shape[1]]
    return out / (k * k)


H_density = _blur(H_density, 3)

# Mask cells whose centre falls outside the curved fundamental sector.
xc = 0.5 * (xe[:-1] + xe[1:])
yc = 0.5 * (ye[:-1] + ye[1:])
XC, YC = np.meshgrid(xc, yc)                             # (Ny, Nx)
sector_mask = _in_polygon(XC.ravel(), YC.ravel(), boundary).reshape(XC.shape)
H_masked = np.ma.array(H_density, mask=~sector_mask)

# Corner grids for pcolormesh (regular → renders as a single fast raster).
Xg, Yg = np.meshgrid(xe, ye)


# ── 6. Best fit = modal (peak-density) orientation ─────────────────────────
flat = np.where(sector_mask, H_density, -np.inf)
pj, pi = np.unravel_index(np.argmax(flat), flat.shape)  # row (y), col (x)
peak_xy = np.array([xc[pi], yc[pj]])

# Invert the stereographic projection at the peak → unit direction → grains.
def stereo_inv(xy):
    sx, sy = xy
    r2 = sx * sx + sy * sy
    z = (1 - r2) / (1 + r2)
    s = (1 + z)
    return np.array([sx * s, sy * s, z])


best_dir = stereo_inv(peak_xy)
best_dir /= np.linalg.norm(best_dir)
# Grains whose reduced direction is within ~5° of the modal direction.
cos_thresh = np.cos(np.radians(5.0))
near = (reduced @ best_dir) >= cos_thresh               # (N_GRAINS,) bool
best_grain_highlight = near[grain_id]                   # (H, W) mask


# ── 7. Figure: orientation map + IPF density heat map ──────────────────────
fig, (ax_map, ax_ipf) = apl.subplots(
    1, 2, figsize=(900, 440),
    help="Drag the crosshair on the map: a marker tracks the grain's\n"
         "direction in the IPF.  The ring marks the modal (best-fit) orientation.")

vmap = ax_map.imshow(ipf_map)
vmap.set_title("IPF-Z orientation map")
# Highlight the grains matching the modal orientation.
vmap.set_overlay_mask(best_grain_highlight, color="#ffffff", alpha=0.45)
cross = vmap.add_widget("crosshair", cx=W // 2, cy=H // 2, color="#ffffff")

vden = ax_ipf.axes2d(xlim=(x0 - 0.02, x1 + 0.02), ylim=(y0 - 0.02, y1 + 0.02),
                     aspect="equal")
vden.set_title("Inverse pole figure — orientation density")
# The heat map: regular grid → single stretched raster, clipped to the sector.
# ``smooth=True`` bilinearly interpolates the density for a continuous field
# (drop it for crisp per-bin cells).
vden.pcolormesh(Xg, Yg, H_masked, cmap="viridis", clip_path=boundary,
                smooth=True, name="density")
# Sector outline + corner labels on top.  Drawn as ONE closed polygon stroke
# (not disjoint segments) so the curved boundary is a single antialiased path
# with smooth joins — this is what visually cleans the clipped raster edge.
vden.add_polygons([boundary.tolist()], name="sector",
                  facecolors=None, edgecolors="#ffffff", linewidths=1.4)
vden.add_texts(
    [stereo(C001)[0], stereo(C011)[0], stereo(C111)[0]],
    ["[001]", "[011]", "[111]"], name="corners", color="#ffffff", fontsize=12)
# Best-fit ring at the modal bin.
vden.add_circles([peak_xy], name="best", radius=9,
                 edgecolors="#ff1744", facecolors="#ff174400", linewidths=2.0)


# ── 8. Crosshair → mark the hovered grain's direction in the IPF ───────────
def show_grain(gid: int) -> None:
    gp = stereo(reduced[gid])[0]
    with fig.batch():
        vden.add_circles([gp], name="hover", radius=6,
                         edgecolors="#ffffff", facecolors="#ffffff66",
                         linewidths=1.5)


@cross.add_event_handler("pointer_move")
def on_move(event):
    ix = int(np.clip(round(cross.cx), 0, W - 1))
    iy = int(np.clip(round(cross.cy), 0, H - 1))
    show_grain(int(grain_id[iy, ix]))


show_grain(int(grain_id[H // 2, W // 2]))

fig  # Interactive

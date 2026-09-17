"""
Inverse Pole Figure (IPF) Explorer
==================================

An EBSD-style orientation explorer for a synthetic polycrystal:

* **Left panel** — IPF-Z orientation map, colored with the standard cubic
  IPF key (red = ⟨001⟩, green = ⟨011⟩, blue = ⟨111⟩).  Rendered as a
  true-color RGB image.
* **Right panel** — the *reduced 3-D inverse pole figure*: every grain's
  sample-Z direction, expressed in crystal coordinates and folded into the
  cubic fundamental sector, plotted as an IPF-colored point cloud on a
  shaded, wireframed unit sphere.

Drag the crosshair on the map: the grain's orientation is marked with a
highlighted dot on the sphere, and the sphere **rotates so that direction
faces you**.  Drag on the sphere to orbit freely; the next crosshair move
re-aims the camera.
"""

import numpy as np
import anyplotlib as apl

rng = np.random.default_rng(42)

# ── 1. Synthetic polycrystal: nearest-seed grain map ────────────────────────
H = W = 192
N_GRAINS = 60

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

# ── 3. Reduce to the cubic fundamental sector and IPF-color ────────────────
# For cubic symmetry, sorting |components| ascending lands every direction
# in the standard 001–011–111 stereographic triangle.
reduced = np.sort(np.abs(dirs), axis=1)                 # (a ≤ b ≤ c)
a, b, c = reduced.T

# Classic IPF key: distance to each triangle corner → R, G, B
rgb = np.stack([c - b, b - a, a], axis=1)
rgb /= rgb.max(axis=1, keepdims=True) + 1e-12           # vivid normalisation
grain_rgb_u8 = (rgb * 255).astype(np.uint8)             # (N_GRAINS, 3)

ipf_map = grain_rgb_u8[grain_id]                        # (H, W, 3) true-color


# ── 4. Figure: RGB map + reduced 3-D IPF point cloud ───────────────────────
fig, (ax_map, ax_ipf) = apl.subplots(
    1, 2, figsize=(880, 420),
    help="Drag the crosshair: the sphere rotates to face that grain's\n"
         "crystal direction.  Drag the sphere to orbit freely.")

vmap = ax_map.imshow(ipf_map)                           # (H, W, 3) → RGB
vmap.set_title("IPF-Z orientation map")
cross = vmap.add_widget("crosshair", cx=W // 2, cy=H // 2, color="#ffffff")

# reduced directions live on the unit sphere → fix bounds to keep the
# origin centred and the geometry origin-true
vipf = ax_ipf.scatter3d(
    reduced[:, 0], reduced[:, 1], reduced[:, 2],
    colors=grain_rgb_u8, point_size=6,
    x_label="[100]", y_label="[010]", z_label="[001]",
    bounds=((-1, 1),) * 3, zoom=1.4,
)
vipf.set_title("Reduced 3D IPF (cubic fundamental sector)")
# Shaded unit sphere with lat/long wireframe behind the direction vectors
vipf.set_sphere(1.0)


# ── 5. Crosshair → highlight + rotate-to-face ───────────────────────────────
def face_camera(v):
    """(azimuth°, elevation°) that aim the camera straight down *v*.

    With the turntable camera, the view faces unit vector ``v`` when
    ``el = asin(vz)`` and ``az = atan2(vx, -vy)``.
    """
    vx, vy, vz = v
    el = np.degrees(np.arcsin(np.clip(vz, -1.0, 1.0)))
    az = np.degrees(np.arctan2(vx, -vy))
    return az, el


def show_orientation(gid: int) -> None:
    v = reduced[gid]
    vipf.set_highlight(*v, color="#ffffff", size=8)
    az, el = face_camera(v)
    vipf.set_view(azimuth=az, elevation=el)


@cross.add_event_handler("pointer_move")
def on_move(event):
    ix = int(np.clip(round(cross.cx), 0, W - 1))
    iy = int(np.clip(round(cross.cy), 0, H - 1))
    show_orientation(int(grain_id[iy, ix]))


show_orientation(int(grain_id[H // 2, W // 2]))

fig  # Interactive

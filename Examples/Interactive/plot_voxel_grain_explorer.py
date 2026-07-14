"""
3-D Voxel Grain Explorer
========================

An orthoslice viewer for a synthetic 3-D polycrystal (voxel grain map),
in the style of EBSD/tomography volume browsers:

* **Top row** — the three orthogonal slices (XY, XZ, YZ) through the
  current voxel, rendered as true-colour IPF-RGB images.  Each carries a
  draggable crosshair; the three crosshairs are **linked**: dragging one
  moves the slice planes of the other two views.
* **Bottom left** — the grain volume rendered as **translucent shaded
  voxels** with three draggable **plane widgets** (the slice selectors in
  3-D).  Voxels lying on a selected plane render more opaque, so the
  current slices glow inside the volume.  Drag a plane along its normal to
  re-slice — the 2-D views follow.
* **Bottom right** — the *reduced 3-D inverse pole figure*: the selected
  voxel's grain orientation is highlighted on the wireframed unit sphere,
  which **rotates to face that crystal direction**.

Everything is bidirectionally linked: drag a crosshair OR a 3-D plane and
the other views re-cut, the voxel highlight moves, and the IPF re-aims.
Drag empty space on either 3-D panel to orbit it freely.
"""

import numpy as np
import anyplotlib as apl

rng = np.random.default_rng(11)

# ── 1. Synthetic 3-D polycrystal: nearest-seed voxel grain map ──────────────
N = 48                       # volume is N³ voxels, indexed V[z, y, x]
N_GRAINS = 40

seeds = rng.uniform(0, N, size=(N_GRAINS, 3))            # (z, y, x)
zz, yy, xx = np.mgrid[0:N, 0:N, 0:N]
gid  = np.zeros((N, N, N), dtype=np.int32)
best = np.full((N, N, N), np.inf)
for g, (sz, sy, sx) in enumerate(seeds):
    d = (zz - sz) ** 2 + (yy - sy) ** 2 + (xx - sx) ** 2
    closer = d < best
    gid[closer] = g
    best[closer] = d[closer]


# ── 2. Orientations, cubic fundamental-sector reduction, IPF colours ────────
def random_rotations(n):
    """Uniform random rotation matrices, shape (n, 3, 3) (Shoemake method)."""
    u1, u2, u3 = rng.random((3, n))
    q = np.stack([
        np.sqrt(1 - u1) * np.sin(2 * np.pi * u2),
        np.sqrt(1 - u1) * np.cos(2 * np.pi * u2),
        np.sqrt(u1) * np.sin(2 * np.pi * u3),
        np.sqrt(u1) * np.cos(2 * np.pi * u3),
    ], axis=1)
    x, y, z, w = q.T
    return np.stack([
        np.stack([1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)], -1),
        np.stack([2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)], -1),
        np.stack([2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)], -1),
    ], axis=1)


rotations = random_rotations(N_GRAINS)
dirs      = rotations[:, 2, :]                            # Rᵀ·ẑ per grain
reduced   = np.sort(np.abs(dirs), axis=1)                 # cubic 001–011–111
a, b, c   = reduced.T
rgb = np.stack([c - b, b - a, a], axis=1)
rgb /= rgb.max(axis=1, keepdims=True) + 1e-12
grain_rgb_u8 = (rgb * 255).astype(np.uint8)               # (N_GRAINS, 3)

# ── 3. Voxels for the 3-D volume view ───────────────────────────────────────
# Rather than a sparse random subsample of the whole volume (where the
# highlight marker floats in empty space because almost no cube sits at the
# selected voxel), render the voxels that actually lie ON the three slice
# planes.  This anchors the highlight exactly where the slices intersect,
# shows real slice contents in 3-D, and scales: the on-plane count is
# ~3·(N/step)² regardless of N, so it stays fast even for a 256³ volume.
VSTEP = max(1, N // 48)        # in-plane downsample → ~48² cubes per plane

# Voxel cube size in data units.  A touch larger than VSTEP so the three
# slabs read as solid sheets rather than a dotted grid.
VOXSIZE = float(VSTEP) * 1.3


def slice_voxels(ix, iy, iz):
    """Voxel centres + colours lying on the x=ix, y=iy, z=iz planes."""
    s = VSTEP
    rng_ax = np.arange(0, N, s)
    parts = []
    # z = iz plane  (vary x, y)
    yy2, xx2 = np.meshgrid(rng_ax, rng_ax, indexing="ij")
    parts.append(np.column_stack([xx2.ravel(), yy2.ravel(),
                                  np.full(xx2.size, iz)]))
    # y = iy plane  (vary x, z)
    zz2, xx2 = np.meshgrid(rng_ax, rng_ax, indexing="ij")
    parts.append(np.column_stack([xx2.ravel(), np.full(xx2.size, iy),
                                  zz2.ravel()]))
    # x = ix plane  (vary y, z)
    zz2, yy2 = np.meshgrid(rng_ax, rng_ax, indexing="ij")
    parts.append(np.column_stack([np.full(yy2.size, ix), yy2.ravel(),
                                  zz2.ravel()]))
    pts = np.vstack(parts)                                   # (M, 3) as (x,y,z)
    cols = grain_rgb_u8[gid[pts[:, 2], pts[:, 1], pts[:, 0]]]  # gid[z,y,x]
    return pts, cols

# ── 4. Figure: 3 slices on top, volume + IPF below ──────────────────────────
gs  = apl.GridSpec(2, 3)
fig = apl.Figure(figsize=(960, 640),
                 help="Drag a crosshair: the other two slices re-cut, the\n"
                      "3-D voxel highlight moves, and the IPF sphere rotates\n"
                      "to the selected grain's crystal direction.\n"
                      "Drag the 3-D panels to orbit them freely.")

ax_xy  = fig.add_subplot(gs[0, 0])
ax_xz  = fig.add_subplot(gs[0, 1])
ax_yz  = fig.add_subplot(gs[0, 2])
ax_vol = fig.add_subplot(gs[1, 0])
ax_ipf = fig.add_subplot(gs[1, 1:3])

ix, iy, iz = N // 2, N // 2, N // 2                       # integer slice indices
fx, fy, fz = float(ix), float(iy), float(iz)              # smooth highlight pos

px = [np.arange(N)] * 2                                   # pixel axes → gutters

v_xy = ax_xy.imshow(grain_rgb_u8[gid[iz]],       axes=px, units="vox")
v_xz = ax_xz.imshow(grain_rgb_u8[gid[:, iy, :]], axes=px, units="vox")
v_yz = ax_yz.imshow(grain_rgb_u8[gid[:, :, ix]], axes=px, units="vox")
v_xy.set_xlabel("x"); v_xy.set_ylabel("y")
v_xz.set_xlabel("x"); v_xz.set_ylabel("z")
v_yz.set_xlabel("y"); v_yz.set_ylabel("z")

cw_xy = v_xy.add_widget("crosshair", cx=ix, cy=iy, color="#ffffff")
cw_xz = v_xz.add_widget("crosshair", cx=ix, cy=iz, color="#ffffff")
cw_yz = v_yz.add_widget("crosshair", cx=iy, cy=iz, color="#ffffff")

_vpts, _vcols = slice_voxels(ix, iy, iz)
v_vol = ax_vol.voxels(
    _vpts[:, 0], _vpts[:, 1], _vpts[:, 2], colors=_vcols,
    size=VOXSIZE, alpha=0.55,
    x_label="x", y_label="y", z_label="z",
    bounds=((0, N - 1),) * 3, zoom=1.1,
    # gpu="auto" (default): ~7k cubes is over the ~1k voxel threshold, so the
    # WebGPU instanced path handles each drag re-slice when WebGPU is present.
)
v_vol.set_title("Grain volume — drag a plane to re-slice")

# Three draggable slice-selector planes; on-plane voxels render opaque
pw_yz = v_vol.add_widget("plane", axis="x", position=ix, color="#ff5252", alpha=0.18)
pw_xz = v_vol.add_widget("plane", axis="y", position=iy, color="#69f0ae", alpha=0.18)
pw_xy = v_vol.add_widget("plane", axis="z", position=iz, color="#40c4ff", alpha=0.18)

v_ipf = ax_ipf.scatter3d(
    reduced[:, 0], reduced[:, 1], reduced[:, 2],
    colors=grain_rgb_u8, point_size=6,
    x_label="[100]", y_label="[010]", z_label="[001]",
    bounds=((-1, 1),) * 3, zoom=1.4,
)
v_ipf.set_title("Reduced 3D IPF")
v_ipf.set_sphere(1.0)


# ── 5. Linked updates ────────────────────────────────────────────────────────
def face_camera(v):
    """Turntable (az°, el°) aiming the camera straight down unit vector v."""
    el = np.degrees(np.arcsin(np.clip(v[2], -1.0, 1.0)))
    az = np.degrees(np.arctan2(v[0], -v[1]))
    return az, el


_busy = [False]   # programmatic widget.set() fires callbacks — guard re-entry


def update(source: str) -> None:
    """Re-cut the other slices, move crosshairs/highlights, re-aim the IPF."""
    _busy[0] = True
    try:
      # Coalesce every panel mutation below into one push per panel — without
      # this, a single crosshair drag fires ~8 full-state pushes across the
      # comm boundary, which is the main source of Pyodide lag.
      with fig.batch():
        if source != "xy":
            v_xy.set_data(grain_rgb_u8[gid[iz]])
            cw_xy.set(cx=ix, cy=iy)
        if source != "xz":
            v_xz.set_data(grain_rgb_u8[gid[:, iy, :]])
            cw_xz.set(cx=ix, cy=iz)
        if source != "yz":
            v_yz.set_data(grain_rgb_u8[gid[:, :, ix]])
            cw_yz.set(cx=iy, cy=iz)
        v_xy.set_title(f"XY slice — z={iz}")
        v_xz.set_title(f"XZ slice — y={iy}")
        v_yz.set_title(f"YZ slice — x={ix}")

        # 3-D slice-selector planes follow at the SMOOTH position (skipped for
        # the one being dragged, so its own live position isn't overwritten).
        if source != "px":
            pw_yz.set(position=fx)
        if source != "py":
            pw_xz.set(position=fy)
        if source != "pz":
            pw_xy.set(position=fz)

        # Re-cut the 3-D slab voxels to the new slice indices so the volume
        # view shows the actual slice contents (bounded ~3·(N/VSTEP)² voxels).
        _p, _c = slice_voxels(ix, iy, iz)
        v_vol.set_data(_p[:, 0], _p[:, 1], _p[:, 2])
        v_vol.set_point_colors(_c)

        # Highlight tracks the SMOOTH plane positions (fx,fy,fz) so the marker
        # glides with the planes instead of jumping by whole voxels.
        v_vol.set_highlight(fx, fy, fz, color="#ffffff", size=7)

        g = int(gid[iz, iy, ix])
        v_ipf.set_highlight(*reduced[g], color="#ffffff", size=8)
        az, el = face_camera(reduced[g])
        v_ipf.set_view(azimuth=az, elevation=el)
    finally:
        _busy[0] = False


def _clipf(v):
    """Clamp a float position to the volume range (kept smooth for the marker)."""
    return float(np.clip(v, 0.0, N - 1))


def _i(v):
    """Round a float position to the nearest integer slice index."""
    return int(round(v))


@cw_xy.add_event_handler("pointer_move")
def _moved_xy(event):
    global ix, iy, fx, fy
    if _busy[0]:
        return
    fx, fy = _clipf(cw_xy.cx), _clipf(cw_xy.cy)
    ix, iy = _i(fx), _i(fy)
    update("xy")


@cw_xz.add_event_handler("pointer_move")
def _moved_xz(event):
    global ix, iz, fx, fz
    if _busy[0]:
        return
    fx, fz = _clipf(cw_xz.cx), _clipf(cw_xz.cy)
    ix, iz = _i(fx), _i(fz)
    update("xz")


@cw_yz.add_event_handler("pointer_move")
def _moved_yz(event):
    global iy, iz, fy, fz
    if _busy[0]:
        return
    fy, fz = _clipf(cw_yz.cx), _clipf(cw_yz.cy)
    iy, iz = _i(fy), _i(fz)
    update("yz")


@pw_yz.add_event_handler("pointer_move")
def _plane_x(event):
    global ix, fx
    if _busy[0]:
        return
    fx = _clipf(pw_yz.position)
    ix = _i(fx)
    update("px")


@pw_xz.add_event_handler("pointer_move")
def _plane_y(event):
    global iy, fy
    if _busy[0]:
        return
    fy = _clipf(pw_xz.position)
    iy = _i(fy)
    update("py")


@pw_xy.add_event_handler("pointer_move")
def _plane_z(event):
    global iz, fz
    if _busy[0]:
        return
    fz = _clipf(pw_xy.position)
    iz = _i(fz)
    update("pz")


update("none")

fig  # Interactive

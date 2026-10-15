"""
Turning a crystal — Kikuchi sphere and detector
===============================================

In electron backscatter diffraction (EBSD) every lattice plane of a crystal
scatters electrons into a band on a sphere around the sample — a *Kikuchi
band*, as wide as twice the plane's Bragg angle.  The bands are fixed to the
crystal, so the sphere turns with it.  A flat detector, fixed in the
microscope, only sees the patch of that sphere facing it; turn the crystal
and a different patch, with a different set of bands, lands on the detector.

* **Left** — the band sphere of nickel (face-centred cubic) at 20 kV,
  wrapped onto a sphere with :meth:`~anyplotlib.Plot3D.set_texture`.
  :meth:`~anyplotlib.Plot3D.set_drag_mode` ``("rotate")`` makes a drag turn
  the *crystal* under a fixed camera, rather than walk the camera around it:
  drag to roll it, **Shift**-drag to spin it about the line of sight.
* **Right** — what a detector facing you records: the same sphere projected
  from its centre onto a flat screen (a gnomonic projection), recomputed in
  Python from :attr:`~anyplotlib.Plot3D.rotation` on every drag frame.

The camera's azimuth and elevation can only aim it, which is two degrees of
freedom.  An orientation has three, which is why the crystal's orientation
is a separate rotation matrix (:meth:`~anyplotlib.Plot3D.set_rotation`) that
the camera then looks at.

The band model is kinematic and deliberately small — each plane family draws
a flat band weighted by a falling atomic scattering factor — so it shows
where the bands are, not their real intensity profiles.
"""
import itertools

import numpy as np

import anyplotlib as apl

# ── The crystal: nickel, fcc, a = 0.3524 nm, at 20 kV ───────────────────────
LATTICE_NM = 0.3524
VOLTAGE_V = 20e3


def electron_wavelength_nm(volts):
    """Relativistic electron wavelength."""
    h, m0, e, c = 6.62607e-34, 9.10938e-31, 1.602177e-19, 2.997925e8
    momentum = np.sqrt(2 * m0 * e * volts * (1 + e * volts / (2 * m0 * c**2)))
    return h / momentum * 1e9


WAVELENGTH_NM = electron_wavelength_nm(VOLTAGE_V)


def fcc_planes(max_index=3):
    """One normal per band — ±(hkl) is the same plane — for the families an
    fcc lattice reflects: h, k, l all odd or all even."""
    planes = []
    for hkl in itertools.product(range(-max_index, max_index + 1), repeat=3):
        h, k, l = hkl
        if hkl == (0, 0, 0) or len({h % 2, k % 2, l % 2}) != 1:
            continue
        first_nonzero = next(v for v in hkl if v != 0)
        if first_nonzero < 0:                      # keep one of ±(hkl)
            continue
        planes.append(hkl)
    return np.array(planes, dtype=float)


PLANES = fcc_planes()
G_LENGTH = np.linalg.norm(PLANES, axis=1) / LATTICE_NM          # nm⁻¹
BRAGG = np.arcsin(WAVELENGTH_NM * G_LENGTH / 2)                  # rad
WEIGHT = np.exp(-0.12 * np.sum(PLANES**2, axis=1))  # scattering falls with |g|
NORMALS = PLANES / np.linalg.norm(PLANES, axis=1, keepdims=True)


def band_intensity(directions):
    """Kinematic band intensity for unit *directions* (…, 3) in the crystal
    frame: inside a band means within its Bragg angle of the plane.

    Bragg angles are a degree or two, so the sine of the angle from the
    plane (a dot product) stands in for the angle itself, and the band edge
    is a short linear ramp.  Done in blocks so the (directions × planes)
    table stays a few MB.
    """
    flat = directions.reshape(-1, 3).astype(np.float32)
    normals = NORMALS.astype(np.float32)
    half_width = np.sin(BRAGG).astype(np.float32)
    edge = (0.3 * half_width).astype(np.float32)
    weight = WEIGHT.astype(np.float32)
    out = np.empty(len(flat), np.float32)
    for start in range(0, len(flat), 32768):
        sine_from_plane = np.abs(flat[start:start + 32768] @ normals.T)
        inside = np.clip((half_width - sine_from_plane) / edge + 0.5, 0, 1)
        out[start:start + 32768] = inside @ weight
    return out.reshape(directions.shape[:-1])


def to_grey(values):
    low, high = np.percentile(values, [1, 99.5])
    return np.clip((values - low) / (high - low), 0, 1)


# ── The sphere: longitude along the columns, latitude down the rows ─────────
# The texture is sampled on a finer copy of the same grid, so the image lines
# up with set_texture's default parametric mapping.
def sphere_grid(rows, cols):
    longitude = np.linspace(0, 2 * np.pi, cols)
    latitude = np.linspace(np.pi / 2, -np.pi / 2, rows)
    LON, LAT = np.meshgrid(longitude, latitude)
    return np.stack([np.cos(LAT) * np.cos(LON),
                     np.cos(LAT) * np.sin(LON),
                     np.sin(LAT)], axis=-1)


grey = (to_grey(band_intensity(sphere_grid(512, 1024))) * 255).astype(np.uint8)
texture = np.repeat(grey[..., None], 3, axis=-1)       # set_texture wants RGB
mesh = sphere_grid(49, 97)                 # coarse: the texture carries detail

# ── The detector: a flat screen facing the camera ───────────────────────────
# At azimuth 0 and elevation 0 the camera looks along +y, so the face of the
# sphere toward it is −y, with +x to the right and +z up on screen.  The
# detector sits on that side; the pattern centre is straight ahead.
DETECTOR_PX = 200
HALF_FIELD = np.tan(np.radians(48))       # ±48° from the pattern centre
u = np.linspace(-HALF_FIELD, HALF_FIELD, DETECTOR_PX)
U, W = np.meshgrid(u, u[::-1])            # row 0 is the top of the screen
rays = np.stack([U, -np.ones_like(U), W], axis=-1)
rays /= np.linalg.norm(rays, axis=-1, keepdims=True)    # microscope frame


def detector_pattern(rotation):
    """What the detector records with the crystal turned by *rotation*.

    *rotation* maps crystal directions into the microscope frame, so a ray
    arriving at the detector came from crystal direction ``rotationᵀ · ray``.
    """
    return to_grey(band_intensity(rays @ rotation))


def facing_direction(rotation):
    """The crystal direction at the pattern centre, as a short [uvw]."""
    d = rotation.T @ np.array([0.0, -1.0, 0.0])
    return "[" + " ".join(f"{v:+.2f}" for v in d) + "]"


def bunge(phi1, Phi, phi2):
    """Rotation from Bunge Euler angles in degrees (z-x-z)."""
    a, b, c = np.radians([phi1, Phi, phi2])

    def rz(t):
        return np.array([[np.cos(t), -np.sin(t), 0],
                         [np.sin(t), np.cos(t), 0], [0, 0, 1]])

    rx = np.array([[1, 0, 0], [0, np.cos(b), -np.sin(b)],
                   [0, np.sin(b), np.cos(b)]])
    return rz(a) @ rx @ rz(c)


start = bunge(20, 40, 15)

# ── Figure ──────────────────────────────────────────────────────────────────
fig, (ax_sphere, ax_detector) = apl.subplots(
    1, 2, figsize=(900, 450),
    help="Drag the sphere to turn the crystal; Shift-drag spins it about\n"
         "the line of sight.  The detector shows the patch facing you.")

sphere = ax_sphere.plot_surface(mesh[..., 0], mesh[..., 1], mesh[..., 2],
                                bounds=((-1, 1),) * 3,
                                azimuth=0, elevation=0, zoom=1.35)
sphere.set_axis_off()
sphere.set_texture(texture, shade=True, cull_backfaces=True)
sphere.set_rotation(start)
sphere.set_drag_mode("rotate")
sphere.set_title("Kikuchi sphere · Ni, 20 kV")

detector = ax_detector.imshow(detector_pattern(start), cmap="gray",
                              vmin=0, vmax=1)
detector.set_title(f"Detector · centre {facing_direction(start)}")


@sphere.add_event_handler("pointer_move")
def follow_the_crystal(event):
    # Every drag frame: ~40k rays against ~50 bands is a few milliseconds.
    if event.rotation is None:         # a wheel zoom, not a turn
        return
    rotation = sphere.rotation
    detector.set_data(detector_pattern(rotation), clim=(0, 1))
    detector.set_title(f"Detector · centre {facing_direction(rotation)}")


fig  # Interactive

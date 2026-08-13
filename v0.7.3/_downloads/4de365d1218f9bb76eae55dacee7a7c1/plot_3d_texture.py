"""
Textured 3-D surfaces — a celestial globe
=========================================

:meth:`~anyplotlib.Plot3D.set_texture` wraps an image around any 3-D
surface, so the picture follows the geometry as you orbit it.  Here we
build an equirectangular star map from a real bright-star catalogue and
project it onto the celestial sphere.

Drag to spin the globe, scroll to zoom, press **R** to reset the view.

.. note::
   You are looking at the sky from the *outside*, the way a physical
   celestial globe is made — so the constellations read mirrored compared
   with lying on your back and looking up.
"""
import numpy as np

import anyplotlib as apl

# ── A real bright-star catalogue ──────────────────────────────────────────────
# name, right ascension (hours), declination (degrees), visual magnitude.
# Positions are J2000, rounded to about an arcminute — plenty for a chart
# this size, but not a substitute for a proper catalogue.
STARS = {
    "Sirius":     (6.752, -16.72, -1.46),
    "Canopus":    (6.399, -52.70, -0.74),
    "Rigil Kent": (14.660, -60.83, -0.27),
    "Arcturus":   (14.261, 19.18, -0.05),
    "Vega":       (18.615, 38.78, 0.03),
    "Capella":    (5.278, 46.00, 0.08),
    "Rigel":      (5.242, -8.20, 0.13),
    "Procyon":    (7.655, 5.22, 0.34),
    "Achernar":   (1.629, -57.24, 0.46),
    "Betelgeuse": (5.919, 7.41, 0.50),
    "Hadar":      (14.064, -60.37, 0.61),
    "Altair":     (19.846, 8.87, 0.77),
    "Acrux":      (12.443, -63.10, 0.77),
    "Aldebaran":  (4.599, 16.51, 0.85),
    "Spica":      (13.420, -11.16, 1.04),
    "Antares":    (16.490, -26.43, 1.09),
    "Pollux":     (7.755, 28.03, 1.14),
    "Fomalhaut":  (22.961, -29.62, 1.16),
    "Deneb":      (20.690, 45.28, 1.25),
    "Mimosa":     (12.795, -59.69, 1.25),
    "Regulus":    (10.140, 11.97, 1.35),
    "Adhara":     (6.977, -28.97, 1.50),
    "Castor":     (7.577, 31.89, 1.58),
    "Shaula":     (17.560, -37.10, 1.62),
    "Gacrux":     (12.520, -57.11, 1.63),
    "Bellatrix":  (5.418, 6.35, 1.64),
    "Elnath":     (5.438, 28.61, 1.65),
    "Miaplacidus": (9.220, -69.72, 1.67),
    "Alnilam":    (5.604, -1.20, 1.69),
    "Alnair":     (22.137, -46.96, 1.74),
    "Alioth":     (12.900, 55.96, 1.76),
    "Alnitak":    (5.679, -1.94, 1.77),
    "Dubhe":      (11.062, 61.75, 1.79),
    "Mirfak":     (3.405, 49.86, 1.79),
    "Wezen":      (7.140, -26.39, 1.83),
    "Kaus Aust.": (18.403, -34.38, 1.85),
    "Alkaid":     (13.792, 49.31, 1.85),
    "Avior":      (8.375, -59.51, 1.86),
    "Sargas":     (17.622, -43.00, 1.86),
    "Menkalinan": (5.992, 44.95, 1.90),
    "Atria":      (16.811, -69.03, 1.91),
    "Alhena":     (6.628, 16.40, 1.93),
    "Peacock":    (20.427, -56.74, 1.94),
    "Polaris":    (2.530, 89.26, 1.98),
    "Mirzam":     (6.378, -17.96, 1.98),
    "Alphard":    (9.460, -8.66, 2.00),
    "Hamal":      (2.120, 23.46, 2.00),
    "Diphda":     (0.727, -17.99, 2.04),
    "Nunki":      (18.921, -26.30, 2.05),
    "Menkent":    (14.112, -36.37, 2.06),
    "Mirach":     (1.162, 35.62, 2.06),
    "Alpheratz":  (0.140, 29.09, 2.06),
    "Rasalhague": (17.582, 12.56, 2.08),
    "Kochab":     (14.845, 74.16, 2.08),
    "Algieba":    (10.333, 19.84, 2.08),
    "Saiph":      (5.796, -9.67, 2.09),
    "Tiaki":      (22.711, -46.88, 2.11),
    "Algol":      (3.136, 40.96, 2.12),
    "Denebola":   (11.818, 14.57, 2.14),
    "Muhlifain":  (12.692, -48.96, 2.20),
    "Aspidiske":  (9.285, -59.28, 2.21),
    "Alphecca":   (15.578, 26.71, 2.22),
    "Sadr":       (20.370, 40.26, 2.23),
    "Mizar":      (13.399, 54.93, 2.23),
    "Eltanin":    (17.943, 51.49, 2.23),
    "Suhail":     (9.133, -43.43, 2.23),
    "Schedar":    (0.675, 56.54, 2.24),
    "Mintaka":    (5.533, -0.30, 2.25),
    "Caph":       (0.153, 59.15, 2.28),
    "Gamma Cas":  (0.945, 60.72, 2.47),
    "Merak":      (11.030, 56.38, 2.37),
    "Enif":       (21.737, 9.88, 2.38),
    "Phecda":     (11.897, 53.69, 2.44),
    "Ruchbah":    (1.430, 60.24, 2.68),
    "Delta Cru":  (12.252, -58.75, 2.79),
    "Alcyone":    (3.792, 24.11, 2.87),
    "Megrez":     (12.257, 57.03, 3.31),
    "Segin":      (1.907, 63.67, 3.38),
    "Meissa":     (5.585, 9.93, 3.39),
}

# Constellation figures, as chains of catalogue names.
FIGURES = [
    # Orion
    ["Betelgeuse", "Bellatrix", "Mintaka", "Rigel"],
    ["Mintaka", "Alnilam", "Alnitak", "Saiph"],
    ["Betelgeuse", "Alnitak"],
    ["Bellatrix", "Meissa", "Betelgeuse"],
    # Ursa Major — the Plough / Big Dipper
    ["Dubhe", "Merak", "Phecda", "Megrez", "Dubhe"],
    ["Megrez", "Alioth", "Mizar", "Alkaid"],
    # Cassiopeia — the W (crosses RA 0h, so the drawing must wrap)
    ["Segin", "Ruchbah", "Gamma Cas", "Schedar", "Caph"],
    # Crux — the Southern Cross
    ["Acrux", "Gacrux"],
    ["Mimosa", "Delta Cru"],
    # Gemini, and the Summer Triangle asterism
    ["Castor", "Pollux"],
    ["Vega", "Deneb", "Altair", "Vega"],
]

# ── Build the equirectangular sky image ───────────────────────────────────────
# Columns run 0h → 24h of right ascension, rows +90° → −90° of declination.
# That is exactly the parametric order set_texture() maps by default.
TEX_W, TEX_H = 1440, 720

# North galactic pole and galactic centre (J2000) — used to lay the Milky Way
# band down where it actually belongs rather than freehand.
NGP_RA, NGP_DEC = np.radians(192.85948), np.radians(27.12825)
GC_RA, GC_DEC = np.radians(266.41684), np.radians(-29.00781)


def _sky_pixel(ra_h, dec_deg):
    """Catalogue coordinates → (column, row) in the texture."""
    return (ra_h / 24.0 * (TEX_W - 1), (90.0 - dec_deg) / 180.0 * (TEX_H - 1))


def _angsep(ra, dec, ra0, dec0):
    """Great-circle angle between (ra, dec) and a fixed direction, in radians."""
    return np.arccos(np.clip(
        np.sin(dec) * np.sin(dec0) + np.cos(dec) * np.cos(dec0) * np.cos(ra - ra0),
        -1.0, 1.0))


def _splat(img, x, y, radius, rgb, amp):
    """Add a small Gaussian blob, wrapping in RA and clipping at the poles."""
    r = int(np.ceil(3 * radius))
    xs = np.arange(int(round(x)) - r, int(round(x)) + r + 1)
    ys = np.arange(int(round(y)) - r, int(round(y)) + r + 1)
    ys = ys[(ys >= 0) & (ys < img.shape[0])]
    if len(ys) == 0:
        return
    g = (np.exp(-((ys[:, None] - y) ** 2 + (xs[None, :] - x) ** 2)
                / (2 * radius ** 2)) * amp)
    img[np.ix_(ys, xs % img.shape[1])] += g[..., None] * np.asarray(rgb)


def _stroke(img, p0, p1, rgb, amp):
    """Draw a line between two texture points, taking the short way in RA."""
    (x0, y0), (x1, y1) = p0, p1
    if abs(x1 - x0) > img.shape[1] / 2:
        x1 += img.shape[1] if x0 > x1 else -img.shape[1]
    n = int(max(abs(x1 - x0), abs(y1 - y0))) * 2 + 2
    xs = (np.linspace(x0, x1, n).astype(int)) % img.shape[1]
    ys = np.clip(np.linspace(y0, y1, n), 0, img.shape[0] - 1).astype(int)
    img[ys, xs] = np.maximum(img[ys, xs], np.asarray(rgb) * amp)


rng = np.random.default_rng(20260730)

ra_grid = np.linspace(0, 2 * np.pi, TEX_W)[None, :]
dec_grid = np.radians(np.linspace(90, -90, TEX_H))[:, None]

sky = np.zeros((TEX_H, TEX_W, 3), np.float32)

# Deep-space background, a touch bluer toward the poles.
sky[:] = np.array([0.020, 0.028, 0.062], np.float32)
sky += (np.abs(np.sin(dec_grid)) ** 3 * 0.02)[..., None]

# The Milky Way: a band along galactic latitude 0, brightest toward the
# galactic centre in Sagittarius, mottled by dust lanes.
gal_lat = np.arcsin(np.sin(dec_grid) * np.sin(NGP_DEC)
                    + np.cos(dec_grid) * np.cos(NGP_DEC)
                    * np.cos(ra_grid - NGP_RA))
band = np.exp(-(gal_lat / np.radians(11.0)) ** 2)
band = band * (0.45 + 0.85 * np.exp(-(_angsep(ra_grid, dec_grid, GC_RA, GC_DEC)
                                      / np.radians(55.0)) ** 2))
dust = np.zeros((TEX_H, TEX_W), np.float32)
amp = 1.0
for k in range(1, 6):                          # cheap fBm, no scipy needed
    dust += amp * (np.sin(3 * k * ra_grid + rng.uniform(0, 2 * np.pi))
                   * np.sin(2.5 * k * (dec_grid + np.pi / 2)
                            + rng.uniform(0, 2 * np.pi)))
    amp *= 0.55
band = band * np.clip(0.72 + 0.28 * dust, 0.25, 1.0)
sky += band[..., None] * np.array([0.46, 0.44, 0.55], np.float32)

# Background field: uniform on the sphere (density ∝ cos δ), thickened in
# the galactic plane where the real sky is crowded.
n_faint = 24_000
f_ra = rng.uniform(0, TEX_W, n_faint)
f_dec = np.degrees(np.arcsin(rng.uniform(-1, 1, n_faint)))
fx = f_ra.astype(int) % TEX_W
fy = ((90.0 - f_dec) / 180.0 * (TEX_H - 1)).astype(int)
keep = rng.random(n_faint) < (0.22 + 0.78 * band[fy, fx])
fx, fy = fx[keep], fy[keep]
sky[fy, fx] += rng.uniform(0.25, 0.95, (len(fx), 1)).astype(np.float32)

# Constellation figures, under the named stars.
for chain in FIGURES:
    for a, b in zip(chain, chain[1:]):
        _stroke(sky, _sky_pixel(*STARS[a][:2]), _sky_pixel(*STARS[b][:2]),
                (0.30, 0.58, 0.85), 1.0)

# The named stars themselves: brighter and fatter with decreasing magnitude.
for name, (ra_h, dec_deg, mag) in STARS.items():
    x, y = _sky_pixel(ra_h, dec_deg)
    scale = 10 ** (-0.4 * mag)                 # linear flux from magnitude
    _splat(sky, x, y, 1.3 + 2.0 * scale ** 0.35, (1.0, 0.97, 0.90),
           0.85 + 2.2 * scale ** 0.30)

sky_u8 = (np.clip(sky, 0, 1) * 255).astype(np.uint8)

# ── The globe ─────────────────────────────────────────────────────────────────
# Longitude along the columns and latitude down the rows, matching the image.
# A coarse grid is fine — the texture carries the detail, and fewer triangles
# means a smoother spin.
NDEC, NRA = 49, 97
ra = np.linspace(0, 2 * np.pi, NRA)            # RA 0h → 24h, seam closes
dec = np.linspace(np.pi / 2, -np.pi / 2, NDEC)  # +90° → −90°
RA, DEC = np.meshgrid(ra, dec)
X = np.cos(DEC) * np.cos(RA)
Y = np.cos(DEC) * np.sin(RA)
Z = np.sin(DEC)

# The camera faces the sphere point (RA α, Dec δ) at
# ``elevation = δ`` and ``azimuth = atan2(cos δ cos α, −cos δ sin α)``.
# These angles put Orion — the easiest figure to pick out — near the middle.
fig, ax = apl.subplots(1, 1, figsize=(520, 520))
globe = ax.plot_surface(X, Y, Z,
                        bounds=((-1, 1),) * 3,   # keeps the sphere a true circle
                        azimuth=172, elevation=6)
globe.set_axis_off()                             # the globe *is* the subject
globe.set_texture(sky_u8, cull_backfaces=True)   # closed surface → safe to cull
globe.set_title("the celestial sphere")

fig

# %%
# The source image
# ----------------
# Nothing about the image is special — it is an ordinary ``(H, W, 3)`` array,
# shown here in the same panel type you would use for any picture.  Because
# the sphere's columns run 0h → 24h of right ascension and its rows +90° →
# −90° of declination, the default parametric mapping lines the two up with
# no extra work.

fig2, ax2 = apl.subplots(1, 1, figsize=(900, 470))
sky_map = ax2.imshow(sky_u8)
sky_map.set_title("an equirectangular star map — 0h to 24h left to right, "
                  "+90$\\degree$ to −90$\\degree$ top to bottom")

for name in ("Sirius", "Betelgeuse", "Rigel", "Vega", "Deneb", "Altair",
             "Polaris", "Arcturus", "Antares", "Acrux", "Canopus", "Spica",
             "Aldebaran", "Regulus", "Fomalhaut", "Capella"):
    ra_h, dec_deg, _ = STARS[name]
    x, y = _sky_pixel(ra_h, dec_deg)
    # Marker text anchors on its left, so flip long labels inward near the
    # right-hand edge rather than letting them run off the map.
    flip = x > TEX_W * 0.88
    sky_map.add_text(x + (-10 - 6 * len(name) if flip else 10), y - 4, name,
                     color="#ffd54f", fontsize=9)

fig2

# %%
# Any surface, not just spheres
# -----------------------------
# The mapping is parametric — the image's left edge goes to the grid's first
# column, its top row to the grid's first row — so the same call drapes an
# image over an open surface.  ``shade=True`` adds diffuse lighting, which is
# what makes the relief read as relief.
#
# Leave ``cull_backfaces`` off here: culling is only safe on a *closed*
# surface, and it would make this one vanish when viewed from below.

gx = np.linspace(-3, 3, 90)
gy = np.linspace(-3, 3, 90)
GX, GY = np.meshgrid(gx, gy)
GZ = 0.55 * np.exp(-((GX - 0.8) ** 2 + (GY - 0.4) ** 2) / 1.6) \
     - 0.35 * np.exp(-((GX + 1.1) ** 2 + (GY + 1.0) ** 2) / 0.9) \
     + 0.12 * np.sin(2.2 * GX) * np.cos(2.0 * GY)

# A bright graticule makes both effects easy to see: the grid bends with the
# relief, and the lighting picks out the hill and the hollow.  Any
# ``(H, W, 3|4)`` array works here, as do the raw bytes of a PNG/JPEG or a
# path to one.
mx, my = np.meshgrid(np.arange(600), np.arange(400))
chart = np.stack([
    (60 + 190 * mx / 600),
    (110 + 90 * my / 400),
    (200 - 120 * mx / 600),
], -1).astype(np.uint8)
chart[(mx % 40 < 2) | (my % 40 < 2)] = 245           # graticule

fig3, ax3 = apl.subplots(1, 1, figsize=(560, 470))
terrain = ax3.plot_surface(GX, GY, GZ, azimuth=-58, elevation=38,
                           x_label="x", y_label="y", z_label="height")
terrain.set_texture(chart, shade=True)
terrain.set_title("an image draped over an open surface")

fig3

# %%
# Live updates
# ------------
# :meth:`~anyplotlib.Plot3D.set_texture` re-wraps without rebuilding the
# panel, so the image and the mapping options can both be swapped on the fly
# — here to burn a coordinate grid onto the same globe.
# :meth:`~anyplotlib.Plot3D.clear_texture` drops back to the colormapped
# Z surface.

sky_grid = sky.copy()
ra_lines = np.zeros(TEX_W, bool)
ra_lines[(np.arange(TEX_W) * 24 // TEX_W) % 2 == 0] = True   # every 2 h
ra_lines &= np.r_[True, np.diff((np.arange(TEX_W) * 24 // TEX_W)) != 0]
for x in np.nonzero(ra_lines)[0]:
    sky_grid[:, x] = np.maximum(sky_grid[:, x], (0.10, 0.30, 0.34))
for dec_deg in range(-75, 90, 15):
    y = int((90 - dec_deg) / 180 * (TEX_H - 1))
    lit = (0.22, 0.55, 0.60) if dec_deg == 0 else (0.10, 0.30, 0.34)
    sky_grid[y] = np.maximum(sky_grid[y], lit)

globe.set_texture((np.clip(sky_grid, 0, 1) * 255).astype(np.uint8),
                  cull_backfaces=True)
globe.set_view(azimuth=200, elevation=25)
globe.set_title("the celestial sphere, with an RA/Dec grid")

fig

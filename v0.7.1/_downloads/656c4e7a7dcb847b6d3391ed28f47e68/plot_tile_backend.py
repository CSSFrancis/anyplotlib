"""
Custom Tile Backend — pan & zoom a huge image you never hold in memory
======================================================================

For a very large image, anyplotlib does not need the whole array.  It asks a
:class:`~anyplotlib.plot2d._tile_backend.TileBackend` for a downsampled
*overview* to use as the base texture, and then — on every zoom / pan — for a
crisp *detail tile* of just the visible region at the panel's resolution.
anyplotlib owns that zoom/pan → re-tile lifecycle; the backend owns the data.

A backend is any object implementing the ``TileBackend`` protocol:

``full_shape`` (H, W), ``dtype``, ``origin``, ``extent()``, and
``sample(x0, x1, y0, y1, out_w, out_h, method)`` — return the logical region
``[y0:y1, x0:x1]`` resampled to ``(out_h, out_w)``.

Because ``sample`` is called *on demand*, the source never has to exist in
full.  Here we make a **procedural** backend that computes a Mandelbrot fractal
for whatever region is requested — a 65 536 × 65 536 "image" (4.3 gigapixels)
that is generated tile-by-tile as you explore it.  The array is never
materialised; only the small tiles you look at are ever computed.
"""
import numpy as np
import anyplotlib as apl

# %%
# A procedural tile backend
# -------------------------
# The Mandelbrot escape count over a data-space window.  The full logical
# image is ``SIZE x SIZE`` pixels mapping to the complex plane
# ``[-2.5, 1.0] x [-1.75, 1.75]``, but no pixel is computed until ``sample``
# is called for it.

SIZE = 65_536  # 65k x 65k logical pixels ≈ 4.3 gigapixels — never allocated
CX0, CX1 = -2.5, 1.0
CY0, CY1 = -1.75, 1.75


class MandelbrotTileBackend:
    """A ``TileBackend`` that synthesises fractal tiles on demand."""

    max_iter = 80

    @property
    def full_shape(self):
        return (SIZE, SIZE)

    @property
    def dtype(self):
        return np.dtype("uint16")  # escape counts

    @property
    def origin(self):
        return "lower"  # row 0 at the bottom (matches the y data-axis below)

    def extent(self):
        # Data-space (x0, x1, y0, y1) the image spans, or None for pixel
        # coordinates.  Return None here and set the coordinate axes explicitly
        # on imshow (below) so the ticks read as real/imaginary values.
        return None

    def sample(self, x0, x1, y0, y1, out_w, out_h, method="mean"):
        # Only the requested window is ever evaluated, at exactly the output
        # resolution the panel asked for — so a zoomed-in tile is as sharp as a
        # zoomed-out overview is cheap.  The escape loop is written for speed
        # (it runs once per pan/zoom), using three tricks over the textbook
        # version:
        #   * real / imag ``float32`` arithmetic instead of complex128 — half
        #     the memory traffic and no complex-multiply overhead;
        #   * the escape test is ``|z|² > 4`` (``zr² + zi²``), avoiding the
        #     ``sqrt`` in ``abs``;
        #   * no shrinking boolean mask.  Instead we ``counts += inside`` every
        #     iteration (a cheap bool→uint add): each pixel's count is simply
        #     how many steps it stayed inside.  Escaped pixels keep iterating to
        #     ``inf``, which is harmless — ``inf > 4`` just keeps them counted
        #     out.  This is ~3× faster on the overview and ~8× faster on a
        #     deep-zoom tile (where nothing escapes early, so a mask never
        #     shrinks and the old code crawled).
        cr = (CX0 + (np.linspace(x0, x1, out_w, dtype=np.float32) / SIZE)
              * (CX1 - CX0))[np.newaxis, :]
        ci = (CY0 + (np.linspace(y0, y1, out_h, dtype=np.float32) / SIZE)
              * (CY1 - CY0))[:, np.newaxis]
        cr = np.ascontiguousarray(np.broadcast_to(cr, (out_h, out_w)))
        ci = np.ascontiguousarray(np.broadcast_to(ci, (out_h, out_w)))

        zr = np.zeros((out_h, out_w), np.float32)
        zi = np.zeros((out_h, out_w), np.float32)
        counts = np.zeros((out_h, out_w), np.uint16)
        zr2 = np.empty_like(zr)
        zi2 = np.empty_like(zr)
        tmp = np.empty_like(zr)
        # Escaped pixels run off to ±inf; the inf−inf / inf·0 they produce is
        # expected and never touches `counts` (an escaped pixel already fails
        # the `<= 4` test), so silence the overflow/invalid warnings.
        with np.errstate(over="ignore", invalid="ignore"):
            for i in range(self.max_iter):
                np.multiply(zr, zr, out=zr2)
                np.multiply(zi, zi, out=zi2)
                inside = (zr2 + zi2) <= 4.0
                counts += inside                 # still-inside pixels tick up
                # z ← z² + c   (in real / imag form; the shared temporaries
                # above keep this allocation-free inside the loop).
                np.multiply(zr, zi, out=tmp)
                tmp *= 2.0
                tmp += ci                        # zi_next = 2·zr·zi + ci
                np.subtract(zr2, zi2, out=zr)
                zr += cr                         # zr_next = zr² − zi² + cr
                zi, tmp = tmp, zi                # swap in the new zi
                if i % 16 == 15 and not inside.any():
                    break                        # whole tile escaped — done
        return counts


# %%
# Wire it into a plot
# -------------------
# Pass the backend as ``tile_backend=``.  The ``data`` argument is just a
# placeholder — the backend's ``full_shape`` drives the axes, and ``tile=True``
# forces the tiled path.  Zoom and pan to stream sharp detail tiles; anyplotlib
# computes only what is on screen.
#
# **Tiling and the GPU cooperate.** With ``gpu="auto"`` (the default) and a
# WebGPU-capable browser, the downsampled overview is uploaded once as a GPU
# texture and drawn by the shader-side colormap, and the crisp detail tile for
# the visible region is stitched on top of it each frame.  The logical image
# here is 4.3 gigapixels, which is far above the ~1-megapixel threshold that
# switches the WebGPU image path on under ``"auto"`` — so the base raster is
# GPU-composited rather than blitted on the CPU.  (Headless/off-screen renders,
# like this gallery's static thumbnail, have no WebGPU and fall back to
# Canvas2D; the live "Run in browser" version above uses the GPU when your
# browser supports it.)

backend = MandelbrotTileBackend()

# Coordinate axes spanning the logical image, mapped to the complex plane so
# ticks read as real / imaginary values (the tiling still works in pixels).
x_axis = np.linspace(CX0, CX1, SIZE)
y_axis = np.linspace(CY0, CY1, SIZE)

fig, ax = apl.subplots(1, 1, figsize=(560, 560))
v = ax.imshow(
    np.zeros((2, 2)),          # placeholder; overview comes from backend.sample
    axes=[x_axis, y_axis],
    tile_backend=backend,
    tile=True,
    gpu="auto",                # WebGPU texture path when available (see above)
    cmap="inferno",
    units="Re / Im",
)
fig.set_help(
    "Scroll to zoom, drag to pan.\n"
    "Each view fetches a fresh detail tile — the 4.3 GP fractal is\n"
    "generated on demand and never held in memory."
)

fig  # Interactive

# %%
# Is the GPU actually painting?
# -----------------------------
# Read :attr:`~anyplotlib.Plot2D.gpu_active` to see which path ran.  anyplotlib
# updates it automatically once the browser reports back after the first frame:
# ``True`` when the WebGPU image path is live, ``False`` on the Canvas2D
# fallback.  It is ``False`` here because the gallery build is headless (no
# WebGPU); open the live "Run in browser" version above and read ``v.gpu_active``
# to confirm the accelerated path on your own machine.

print("gpu_active:", v.gpu_active)

# %%
# Swap in a real source
# ---------------------
# The same protocol wraps any large source without changing the plot: back
# ``sample`` with a memory-mapped file, a dask/zarr chunk store, or a
# GPU-resident tensor.  For an in-memory ndarray you don't need a custom class
# at all — :func:`~anyplotlib.plot2d._tile_backend.as_tile_backend` (used
# internally when you pass a plain array with ``tile="auto"``) wraps it in the
# default :class:`~anyplotlib.plot2d._tile_backend.NumpyTileBackend`.
#
# .. note::
#
#    ``sample`` should be reasonably fast — it runs once per view change.  A
#    slow source (network, disk) still works, but pan/zoom will feel as
#    responsive as the slowest ``sample`` call.

"""
plot2d/_transform.py
====================
Data ↔ image-pixel coordinate transform for 2-D panels.

Overlay widgets and ``transform="data"`` markers on a :class:`Plot2D` are
positioned in **image pixels**: column / row indices into the displayed frame
where integer *i* is the *centre* of pixel *i* (row 0 at the top, ``origin``
already applied).  Users usually think in the calibrated units of the axes
passed to :meth:`~anyplotlib.Axes.imshow` / :meth:`Plot2D.set_extent`.
:class:`ImageTransform` converts between the two.

The mapping mirrors the renderer exactly (``_axisValToImg2d`` /
``_imgToAxisVal2d`` in ``figure_esm.js``):

* ``imshow`` axes hold one value per pixel **centre**, so ``x_axis[i]`` sits at
  pixel ``i``.  Between samples the mapping is linear; beyond either end it
  continues the end segment linearly, so a coordinate half a pixel outside the
  first centre lands on the image edge.
* ``pcolormesh`` axes hold the ``n + 1`` cell **edges**, so ``x_edges[i]`` sits
  at pixel ``i - 0.5``.

Axes may be ascending or descending (``origin="lower"`` reverses ``y_axis``),
uniform or not.  Length conversions use the average pixel size unless an
``at=`` position is given, in which case the local pixel size there is used —
which only matters for a non-uniform axis.
"""

from __future__ import annotations

import numpy as np

__all__ = ["ImageTransform"]


def _as_out(value, result):
    """Return a Python float for scalar input, an ndarray otherwise."""
    if np.ndim(value) == 0:
        return float(result)
    return result


class _AxisMap:
    """Piecewise-linear map between one axis' values and pixel positions."""

    __slots__ = ("values", "pixels")

    def __init__(self, values: np.ndarray, pixels: np.ndarray):
        self.values = values
        self.pixels = pixels

    @classmethod
    def for_axis(cls, axis, n: int, is_mesh: bool) -> "_AxisMap":
        arr = np.asarray(axis, dtype=float).ravel()
        m = len(arr) - 1
        if is_mesh:
            # n + 1 cell edges: edge i is the leading edge of pixel i.
            pix = np.arange(m + 1, dtype=float) - 0.5
        elif m >= 1:
            # One value per pixel centre.  In tile mode the axis can be
            # shorter than the logical image, so stretch it over n pixels,
            # exactly as the renderer does.
            pix = np.arange(m + 1, dtype=float) * ((n - 1) / m if n > 1 else 0.0)
        else:
            pix = np.zeros(len(arr))
        return cls(arr, pix)

    # ------------------------------------------------------------------
    def _single(self):
        """``(origin_value, origin_pixel)`` for an axis with < 2 samples."""
        if len(self.values) == 0:
            return 0.0, 0.0
        return float(self.values[0]), float(self.pixels[0])

    def _check(self) -> None:
        if len(self.values) >= 2 and self.values[-1] == self.values[0]:
            raise ValueError(
                "axis is degenerate (first and last values are equal); "
                "cannot convert between data and pixel coordinates")

    @staticmethod
    def _interp(v, xp, fp):
        """``np.interp`` continued linearly past both ends; *xp* may descend."""
        if xp[-1] < xp[0]:
            xp, fp = xp[::-1], fp[::-1]
        v = np.asarray(v, dtype=float)
        out = np.asarray(np.interp(v, xp, fp), dtype=float)
        dx0 = xp[1] - xp[0]
        dx1 = xp[-1] - xp[-2]
        s0 = (fp[1] - fp[0]) / dx0 if dx0 else 0.0
        s1 = (fp[-1] - fp[-2]) / dx1 if dx1 else 0.0
        out = np.where(v < xp[0], fp[0] + (v - xp[0]) * s0, out)
        out = np.where(v > xp[-1], fp[-1] + (v - xp[-1]) * s1, out)
        return out

    def to_pixel(self, value):
        if len(self.values) < 2:
            v0, p0 = self._single()
            return _as_out(value, np.asarray(value, dtype=float) - v0 + p0)
        self._check()
        return _as_out(value, self._interp(value, self.values, self.pixels))

    def to_value(self, pixel):
        if len(self.values) < 2:
            v0, p0 = self._single()
            return _as_out(pixel, np.asarray(pixel, dtype=float) - p0 + v0)
        self._check()
        # pixels always ascend, so interpolate values over them directly.
        return _as_out(pixel, self._interp(pixel, self.pixels, self.values))

    def scale(self) -> float:
        """Signed average data units per pixel (negative for a descending axis)."""
        if len(self.values) < 2:
            return 1.0
        self._check()
        span = self.pixels[-1] - self.pixels[0]
        return float((self.values[-1] - self.values[0]) / span) if span else 1.0

    def length_to_pixels(self, length, at=None):
        length = np.asarray(length, dtype=float)
        if at is None:
            return _as_out(length, np.abs(length / self.scale()))
        a = np.asarray(at, dtype=float)
        res = np.abs(np.asarray(self.to_pixel(a + length)) - np.asarray(self.to_pixel(a)))
        return _as_out(length, res)

    def pixels_to_length(self, pixels, at=None):
        pixels = np.asarray(pixels, dtype=float)
        if at is None:
            return _as_out(pixels, np.abs(pixels * self.scale()))
        p = np.asarray(self.to_pixel(np.asarray(at, dtype=float)))
        res = np.abs(np.asarray(self.to_value(p + pixels)) - np.asarray(self.to_value(p)))
        return _as_out(pixels, res)


class ImageTransform:
    """Converts between calibrated data coordinates and image pixels.

    Obtain one from :attr:`Plot2D.transform`.  It is a live view: it reads the
    plot's current axes on every call, so it stays correct after
    :meth:`Plot2D.set_extent` or ``set_data(x_axis=..., y_axis=...)``.

    *Image pixels* are the coordinates overlay widgets and ``transform="data"``
    markers use on a 2-D panel: ``(column, row)`` into the displayed frame,
    integer *i* is the centre of pixel *i*, row 0 at the top.  *Data* means the
    calibrated values of the panel's ``x_axis`` / ``y_axis``.

    Point methods accept a scalar or an array; a scalar in gives a ``float``
    out.  :meth:`data_to_pixel` / :meth:`pixel_to_data` take ``(x, y)`` pairs
    with the same shape rules as :meth:`~anyplotlib.Plot2D.data_to_display`.

    Examples
    --------
    >>> import numpy as np
    >>> import anyplotlib as apl
    >>> fig, ax = apl.subplots()
    >>> x = 10.0 + 0.5 * np.arange(25)          # 25 columns, 0.5 nm apart
    >>> y = -3.0 + 0.25 * np.arange(12)         # 12 rows, 0.25 nm apart
    >>> plot = ax.imshow(np.zeros((12, 25)), axes=[x, y], units="nm")
    >>> plot.transform.x_to_pixel(11.0)
    2.0
    >>> plot.transform.pixel_to_data([2, 4]).tolist()
    [11.0, -2.0]
    >>> plot.transform.x_length_to_pixels(1.5)
    3.0
    """

    def __init__(self, plot):
        self._plot = plot

    # ── calibration (live) ────────────────────────────────────────────────
    def _maps(self) -> tuple[_AxisMap, _AxisMap]:
        st = self._plot._state
        is_mesh = bool(st.get("is_mesh"))
        n_x = int(st.get("image_width") or len(st["x_axis"]))
        n_y = int(st.get("image_height") or len(st["y_axis"]))
        return (_AxisMap.for_axis(st["x_axis"], n_x, is_mesh),
                _AxisMap.for_axis(st["y_axis"], n_y, is_mesh))

    @property
    def x_scale(self) -> float:
        """Average data units per image pixel along x (signed: negative when
        the x axis descends)."""
        return self._maps()[0].scale()

    @property
    def y_scale(self) -> float:
        """Average data units per image pixel along y, signed.  Positive when
        y grows *downwards* on screen (the ``origin="upper"`` default),
        negative for ``origin="lower"``."""
        return self._maps()[1].scale()

    # ── single-axis points ────────────────────────────────────────────────
    def x_to_pixel(self, x):
        """Data x (scalar or array) → image column (fractional)."""
        return self._maps()[0].to_pixel(x)

    def y_to_pixel(self, y):
        """Data y (scalar or array) → image row (fractional)."""
        return self._maps()[1].to_pixel(y)

    def pixel_to_x(self, px):
        """Image column (scalar or array) → data x."""
        return self._maps()[0].to_value(px)

    def pixel_to_y(self, py):
        """Image row (scalar or array) → data y."""
        return self._maps()[1].to_value(py)

    # ── lengths ───────────────────────────────────────────────────────────
    def x_length_to_pixels(self, length, at=None):
        """A length along x in data units → a (non-negative) number of pixels.

        Parameters
        ----------
        length : float or array-like
            Length in data units.  The sign is ignored.
        at : float or array-like, optional
            Data x where the length starts.  Only matters for a non-uniform
            axis; by default the average pixel size is used.
        """
        return self._maps()[0].length_to_pixels(length, at)

    def y_length_to_pixels(self, length, at=None):
        """A length along y in data units → pixels.  See :meth:`x_length_to_pixels`."""
        return self._maps()[1].length_to_pixels(length, at)

    def pixels_to_x_length(self, pixels, at=None):
        """A number of pixels along x → a (non-negative) length in data units.

        ``at`` is the data x where the span starts (non-uniform axes only).
        """
        return self._maps()[0].pixels_to_length(pixels, at)

    def pixels_to_y_length(self, pixels, at=None):
        """A number of pixels along y → a length in data units.  See
        :meth:`pixels_to_x_length`."""
        return self._maps()[1].pixels_to_length(pixels, at)

    # ── (x, y) pairs ──────────────────────────────────────────────────────
    @staticmethod
    def _pairs(points):
        pts = np.atleast_2d(np.asarray(points, dtype=float))
        if pts.shape[-1] != 2:
            raise ValueError(f"points must have shape (N, 2); got {pts.shape}")
        return pts

    def data_to_pixel(self, points):
        """``(x, y)`` data pairs → ``(column, row)`` image-pixel pairs.

        Parameters
        ----------
        points : array-like
            A single ``(x, y)`` pair or an ``(N, 2)`` sequence of them.

        Returns
        -------
        numpy.ndarray
            Same shape as *points*.
        """
        pts = self._pairs(points)
        mx, my = self._maps()
        out = np.column_stack([np.asarray(mx.to_pixel(pts[:, 0])),
                               np.asarray(my.to_pixel(pts[:, 1]))])
        return out if np.ndim(points) == 2 else out[0]

    def pixel_to_data(self, points):
        """``(column, row)`` image-pixel pairs → ``(x, y)`` data pairs.

        The inverse of :meth:`data_to_pixel`, with the same shape rules.
        """
        pts = self._pairs(points)
        mx, my = self._maps()
        out = np.column_stack([np.asarray(mx.to_value(pts[:, 0])),
                               np.asarray(my.to_value(pts[:, 1]))])
        return out if np.ndim(points) == 2 else out[0]

    def __repr__(self) -> str:
        try:
            return (f"ImageTransform(x_scale={self.x_scale:.4g}, "
                    f"y_scale={self.y_scale:.4g})")
        except ValueError:
            return "ImageTransform(degenerate)"

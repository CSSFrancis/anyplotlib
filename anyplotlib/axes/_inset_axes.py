"""
axes/_inset_axes.py
===================
Floating overlay inset (not in the grid).
"""

from __future__ import annotations

import math
import uuid as _uuid

from anyplotlib.axes._axes import Axes
from anyplotlib.plot1d import PlotBar
from anyplotlib.plot2d import Plot2D, PlotMesh
from anyplotlib.plot3d import Plot3D


def _plot_kind(plot) -> str:
    """Return the JS panel-kind string for a plot object.

    Used in ``Figure._push_layout()`` and ``InsetAxes.__repr__``.
    """
    if isinstance(plot, Plot3D):
        return "3d"
    if isinstance(plot, (Plot2D, PlotMesh)):
        return "2d"
    if isinstance(plot, PlotBar):
        return "bar"
    return "1d"


_VALID_CORNERS = ("top-right", "top-left", "bottom-right", "bottom-left")


class InsetAxes(Axes):
    """A floating inset sub-plot that overlays the main Figure grid.

    Created via :meth:`Figure.add_inset`.  Supports the same plot-factory
    methods as :class:`Axes` (``imshow``, ``plot``, ``pcolormesh``, etc.).

    The inset is positioned at a corner of the figure and can be minimized
    (title bar only), maximized (expanded to fill ~72% of the figure), or
    restored to its normal size.

    Parameters
    ----------
    fig : Figure
    w_frac, h_frac : float
        Width and height as fractions of the figure dimensions (0–1).
    corner : str, optional
        One of ``"top-right"``, ``"top-left"``, ``"bottom-right"``,
        ``"bottom-left"``.  Default ``"top-right"``.  Mutually exclusive with
        *anchor* — pass exactly one.
    anchor : (x_frac, y_frac), optional
        Position of the inset's TOP-LEFT corner as fractions of the figure
        size (0–1), measured from the figure's top-left.  When given, the
        inset floats freely at that anchor instead of snapping to a corner
        (``corner`` is then ignored / ``None``).  Minimize / maximize / restore
        all still work: a minimized anchored inset collapses to its title bar
        in place, a maximized one floats centred, and restore returns it to the
        anchor.
    title : str, optional
        Text shown in the inset title bar.  Default ``""``.

    Examples
    --------
    >>> fig, ax = apl.subplots(1, 1, figsize=(640, 480))
    >>> ax.imshow(data)
    >>> inset = fig.add_inset(0.3, 0.25, corner="top-right", title="Zoom")
    >>> inset.imshow(data[64:128, 64:128])
    >>> # arbitrary placement:
    >>> free = fig.add_inset(0.3, 0.25, anchor=(0.55, 0.1), title="Callout")
    >>> free.imshow(data[64:128, 64:128])
    """

    def __init__(self, fig, w_frac: float, h_frac: float, *,
                 corner: str = "top-right", anchor=None, title: str = ""):
        if anchor is not None:
            ax_, ay_ = anchor
            self.anchor = (float(ax_), float(ay_))
            # anchor placement supersedes corner; keep corner=None so both the
            # layout math and the callout corner-pairing know it is free-floating.
            self.corner = None
        else:
            if corner not in _VALID_CORNERS:
                raise ValueError(
                    f"corner must be one of {_VALID_CORNERS!r}, got {corner!r}"
                )
            self.anchor = None
            self.corner = corner
        # Pass a dummy SubplotSpec so Axes.__init__ doesn't fail — InsetAxes
        # never occupies a grid cell, only overlays the figure.
        from anyplotlib.figure._gridspec import SubplotSpec
        super().__init__(fig, SubplotSpec(None, 0, 1, 0, 1))
        self.w_frac = w_frac
        self.h_frac = h_frac
        self.title  = title
        self._inset_state: str = "normal"
        # Region indication (mark_inset-style callout) tied to this inset, or
        # None.  Set via :meth:`indicate_region`, cleared via
        # :meth:`clear_indication`.  Persisted in Figure.layout_json.
        self._indication: dict | None = None

    # ── state API ─────────────────────────────────────────────────────────

    @property
    def inset_state(self) -> str:
        """Current state: ``"normal"``, ``"minimized"``, or ``"maximized"``."""
        return self._inset_state

    def minimize(self) -> None:
        """Collapse the inset to its title bar only (idempotent)."""
        if self._inset_state == "minimized":
            return
        self._inset_state = "minimized"
        self._fig._push_layout()

    def maximize(self) -> None:
        """Expand the inset to ~72 % of the figure, centred (idempotent)."""
        if self._inset_state == "maximized":
            return
        self._inset_state = "maximized"
        self._fig._push_layout()

    def restore(self) -> None:
        """Return the inset to its normal corner position (idempotent)."""
        if self._inset_state == "normal":
            return
        self._inset_state = "normal"
        self._fig._push_layout()

    # ── region indication (mark_inset-style callout) ──────────────────────

    def indicate_region(self, parent_plot, region, *,
                        color: str = "#ff9800",
                        linestyle: str = "dashed",
                        linewidth: float = 1.5) -> "InsetAxes":
        """Draw a callout tying this inset to a region of *parent_plot*.

        Renders — on the parent panel's overlay — a rectangle around *region*
        (in the parent image's DATA coordinates) plus two leader lines joining
        the rectangle's corners that face the inset to the inset's nearest
        corners, the classic matplotlib ``mark_inset`` look.  The rectangle
        tracks the parent's zoom / pan and the leaders follow the inset as it
        moves or minimizes (leaders hide while the inset is minimized).

        Calling ``indicate_region`` again REPLACES any previous indication for
        this inset.  Remove it with :meth:`clear_indication`.

        Parameters
        ----------
        parent_plot : Plot2D
            The parent image plot the region lives on.  Must be a 2-D image
            panel in the SAME figure as this inset (typically the panel the
            inset overlays) — a plot registered on a different ``Figure``
            raises ``ValueError``.
        region : (x, y, w, h)
            The source rectangle in the parent image's data coordinates:
            top-left ``(x, y)`` plus width and height.  The values follow the
            same convention as the parent's axes (pixel indices for an
            uncalibrated image; physical units when the axes are calibrated).
            All four must be finite; ``w`` and ``h`` must be strictly
            positive.  The rectangle MAY extend outside the parent's data
            bounds (e.g. a region near an edge) — that is allowed by design
            and simply clips visually; only degenerate/non-finite values are
            rejected.
        color : str, optional
            Stroke colour of both the rectangle and the leader lines.
            Default warm orange ``"#ff9800"``.
        linestyle : str, optional
            ``"dashed"`` (default), ``"solid"``, or ``"dotted"``.
        linewidth : float, optional
            Stroke width in CSS px.  Default ``1.5``.

        Returns
        -------
        InsetAxes
            ``self``, for chaining.

        Raises
        ------
        ValueError
            If ``parent_plot`` has no panel id, is not registered on this
            inset's Figure, or ``region`` is not 4 finite numbers with
            ``w > 0`` and ``h > 0``.
        """
        pid = getattr(parent_plot, "_id", None)
        if pid is None:
            raise ValueError("indicate_region: parent_plot has no panel id "
                             "(attach it to the figure first)")
        if self._fig._plots_map.get(pid) is not parent_plot:
            raise ValueError(
                "indicate_region: parent_plot is not registered on this "
                "inset's Figure — pass a plot created on the same figure "
                "as this inset (fig.add_inset / fig.subplots)")
        try:
            x, y, w, h = (float(v) for v in region)
        except (TypeError, ValueError):
            raise ValueError(
                f"indicate_region: region must be 4 numbers (x, y, w, h), "
                f"got {region!r}") from None
        if not all(math.isfinite(v) for v in (x, y, w, h)):
            raise ValueError(
                f"indicate_region: region values must be finite, got "
                f"(x={x}, y={y}, w={w}, h={h})")
        if not (w > 0 and h > 0):
            raise ValueError(
                f"indicate_region: region width and height must be > 0, "
                f"got (w={w}, h={h})")
        self._indication = {
            "parent_id": pid,
            "region":    [x, y, w, h],
            "color":     color,
            "linestyle": linestyle,
            "linewidth": float(linewidth),
        }
        self._fig._push_layout()
        return self

    def clear_indication(self) -> None:
        """Remove any region indication attached to this inset (idempotent)."""
        if self._indication is None:
            return
        self._indication = None
        self._fig._push_layout()

    @property
    def indication(self) -> "dict | None":
        """The current region-indication spec (``dict``) or ``None``."""
        return self._indication

    # ── internal ──────────────────────────────────────────────────────────

    def _attach(self, plot) -> None:
        """Register the plot on this inset via Figure._register_inset."""
        if self._plot is not None:
            panel_id = self._plot._id
        else:
            panel_id = str(_uuid.uuid4())[:8]
        plot._id  = panel_id
        plot._fig = self._fig
        self._plot = plot
        self._fig._register_inset(self, plot)

    def __repr__(self) -> str:
        kind = _plot_kind(self._plot) if self._plot else "empty"
        pos = (f"anchor={self.anchor!r}" if self.anchor is not None
               else f"corner={self.corner!r}")
        return (
            f"InsetAxes({pos}, "
            f"size=({self.w_frac:.2f}, {self.h_frac:.2f}), "
            f"state={self._inset_state!r}, kind={kind!r})"
        )

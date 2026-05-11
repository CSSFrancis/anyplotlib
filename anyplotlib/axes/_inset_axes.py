"""
axes/_inset_axes.py
===================
Floating overlay inset (not in the grid).
"""

from __future__ import annotations

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
        ``"bottom-left"``.  Default ``"top-right"``.
    title : str, optional
        Text shown in the inset title bar.  Default ``""``.

    Examples
    --------
    >>> fig, ax = apl.subplots(1, 1, figsize=(640, 480))
    >>> ax.imshow(data)
    >>> inset = fig.add_inset(0.3, 0.25, corner="top-right", title="Zoom")
    >>> inset.imshow(data[64:128, 64:128])
    """

    def __init__(self, fig, w_frac: float, h_frac: float, *,
                 corner: str = "top-right", title: str = ""):
        if corner not in _VALID_CORNERS:
            raise ValueError(
                f"corner must be one of {_VALID_CORNERS!r}, got {corner!r}"
            )
        # Pass a dummy SubplotSpec so Axes.__init__ doesn't fail — InsetAxes
        # never occupies a grid cell, only overlays the figure.
        from anyplotlib.figure._gridspec import SubplotSpec
        super().__init__(fig, SubplotSpec(None, 0, 1, 0, 1))
        self.w_frac = w_frac
        self.h_frac = h_frac
        self.corner = corner
        self.title  = title
        self._inset_state: str = "normal"

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
        return (
            f"InsetAxes(corner={self.corner!r}, "
            f"size=({self.w_frac:.2f}, {self.h_frac:.2f}), "
            f"state={self._inset_state!r}, kind={kind!r})"
        )

"""
widgets/_widgets3d.py
=====================
Interactive overlay widgets for 3-D panels.
"""

from __future__ import annotations

from typing import Callable

from anyplotlib.widgets._base import Widget


class PlaneWidget(Widget):
    """A draggable axis-aligned plane in a 3-D panel.

    Rendered as a translucent quad spanning the panel's bounds,
    perpendicular to *axis* at *position*.  Drag it in the browser to slide
    it along its normal — ideal as a slice selector for voxel volumes.
    Voxels lying on a plane are rendered more opaque (see
    :meth:`~anyplotlib.Axes.voxels`).

    Parameters
    ----------
    axis : ``"x"`` | ``"y"`` | ``"z"``
        The plane's normal axis.
    position : float
        Position along *axis* in data coordinates.
    color : str, optional
        CSS colour of the plane fill and border.
    alpha : float, optional
        Fill opacity (0–1).  Default 0.12.

    Examples
    --------
    >>> pw = vol.add_widget("plane", axis="z", position=24)
    >>> @pw.add_event_handler("pointer_move")
    ... def on_drag(event):
    ...     print("slice now at", pw.position)
    >>> pw.set(position=10)        # move it from Python
    """

    def __init__(self, push_fn: Callable, axis: str = "z",
                 position: float = 0.0, color: str = "#00e5ff",
                 alpha: float = 0.12):
        if axis not in ("x", "y", "z"):
            raise ValueError(f"axis must be 'x', 'y', or 'z', got {axis!r}")
        super().__init__("plane", push_fn,
                         axis=axis, position=float(position),
                         color=color, alpha=float(alpha))

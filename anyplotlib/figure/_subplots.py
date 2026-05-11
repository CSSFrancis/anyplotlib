"""
figure/_subplots.py
===================
Factory function mirroring matplotlib.pyplot.subplots.
"""

from __future__ import annotations

import numpy as np

from anyplotlib.figure._figure import Figure
from anyplotlib.figure._gridspec import GridSpec
from anyplotlib.axes import Axes


def subplots(nrows=1, ncols=1, *,
             sharex=False, sharey=False,
             figsize=(640, 480),
             width_ratios=None,
             height_ratios=None,
             gridspec_kw=None,
             display_stats=False,
             help=""):
    """Create a :class:`Figure` and a grid of :class:`~anyplotlib.figure_plots.Axes`.

    Mirrors :func:`matplotlib.pyplot.subplots`.

    Parameters
    ----------
    nrows, ncols : int
        Number of rows and columns in the grid.
    sharex, sharey : bool
        Link pan/zoom across all panels on the respective axis.
    figsize : (width, height)
        Figure size in CSS pixels.  Default ``(640, 480)``.
    width_ratios : list of float, optional
        Relative column widths.  Equivalent to
        ``gridspec_kw={"width_ratios": ...}``.
    height_ratios : list of float, optional
        Relative row heights.  Equivalent to
        ``gridspec_kw={"height_ratios": ...}``.
    gridspec_kw : dict, optional
        Extra keyword arguments forwarded to :class:`GridSpec`.
        Recognised keys: ``width_ratios``, ``height_ratios``.
    display_stats : bool, optional
        Show per-panel FPS / frame-time overlay.  Default False.
    help : str, optional
        Help text shown when the user clicks the **?** badge on the figure.
        Newlines (``\\n``) create separate lines in the card.  The badge is
        hidden when *help* is empty (default).  Suppressed globally when
        ``apl.show_help = False``.

    Returns
    -------
    fig : Figure
    axs : Axes  or  numpy array of Axes
        - Single cell  → scalar ``Axes``.
        - Single row   → 1-D array of shape ``(ncols,)``.
        - Single column → 1-D array of shape ``(nrows,)``.
        - Otherwise    → 2-D array of shape ``(nrows, ncols)``.

    Examples
    --------
    >>> import anyplotlib as vw
    >>> import numpy as np
    >>> fig, axs = vw.subplots(2, 1, figsize=(640, 600))
    >>> v2d = axs[0].imshow(np.random.rand(128, 128))
    >>> v1d = axs[1].plot(np.sin(np.linspace(0, 6.28, 256)))
    >>> fig
    """
    # Merge gridspec_kw into width_ratios / height_ratios (matplotlib compat)
    if gridspec_kw:
        width_ratios  = gridspec_kw.get("width_ratios",  width_ratios)
        height_ratios = gridspec_kw.get("height_ratios", height_ratios)

    fig = Figure(
        nrows=nrows, ncols=ncols, figsize=figsize,
        width_ratios=width_ratios, height_ratios=height_ratios,
        sharex=sharex, sharey=sharey,
        display_stats=display_stats,
        help=help,
    )
    # Build the GridSpec from the Figure's own stored ratios so there is
    # exactly one source of truth.
    gs = GridSpec(
        nrows, ncols,
        width_ratios=fig._width_ratios,
        height_ratios=fig._height_ratios,
    )
    axes_grid = np.empty((nrows, ncols), dtype=object)
    for r in range(nrows):
        for c in range(ncols):
            axes_grid[r, c] = fig.add_subplot(gs[r, c])

    if nrows == 1 and ncols == 1:
        return fig, axes_grid[0, 0]
    if nrows == 1:
        return fig, axes_grid[0, :]
    if ncols == 1:
        return fig, axes_grid[:, 0]
    return fig, axes_grid

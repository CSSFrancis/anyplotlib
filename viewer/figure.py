from __future__ import annotations
import json, pathlib
import anywidget, numpy as np, traitlets
from viewer.figure_plots import GridSpec, SubplotSpec, Axes, Plot2D, PlotMesh, Plot3D

__all__ = ["Figure", "GridSpec", "SubplotSpec", "subplots"]

_HERE = pathlib.Path(__file__).parent
_ESM_SOURCE = (_HERE / "figure_esm.js").read_text(encoding="utf-8")


class Figure(anywidget.AnyWidget):
    """Multi-panel interactive figure widget.

    Create via :func:`subplots` or directly::

        fig = Figure(2, 2, figsize=(800, 600))
        ax  = fig.add_subplot((0, 0))
        v2d = ax.imshow(data)
    """

    layout_json = traitlets.Unicode("{}").tag(sync=True)
    fig_width   = traitlets.Int(640).tag(sync=True)
    fig_height  = traitlets.Int(480).tag(sync=True)
    _esm = _ESM_SOURCE

    def __init__(self, nrows=1, ncols=1, figsize=(640, 480),
                 width_ratios=None, height_ratios=None,
                 sharex=False, sharey=False, **kwargs):
        super().__init__(**kwargs)
        self._nrows = nrows
        self._ncols = ncols
        self._width_ratios  = list(width_ratios)  if width_ratios  else [1] * ncols
        self._height_ratios = list(height_ratios) if height_ratios else [1] * nrows
        self._sharex = sharex
        self._sharey = sharey
        self._axes_map: dict  = {}
        self._plots_map: dict = {}
        with self.hold_trait_notifications():
            self.fig_width  = figsize[0]
            self.fig_height = figsize[1]
        self._push_layout()

    # ── subplot creation ──────────────────────────────────────────────────────
    def add_subplot(self, spec) -> Axes:
        """Add a subplot cell and return its :class:`Axes`.

        Parameters
        ----------
        spec : SubplotSpec | int | (row, col) tuple
            - ``SubplotSpec``: used directly (e.g. from ``GridSpec[r, c]``).
            - ``int``: converted to ``(row, col)`` via ``divmod(spec, ncols)``,
              matching ``matplotlib.Figure.add_subplot(num)`` numbering.
            - ``(row, col)`` tuple: selects a single cell.
        """
        if isinstance(spec, SubplotSpec):
            pass  # use as-is
        elif isinstance(spec, int):
            row, col = divmod(spec, self._ncols)
            spec = SubplotSpec(None, row, row + 1, col, col + 1)
        elif isinstance(spec, tuple):
            row, col = spec
            spec = SubplotSpec(None, row, row + 1, col, col + 1)
        else:
            raise TypeError(f"add_subplot: unsupported spec type {type(spec)!r}")
        return Axes(self, spec)

    # ── internal registration (called by Axes._attach) ────────────────────────
    def _register_panel(self, ax: Axes, plot) -> None:
        pid = plot._id
        if not self.has_trait(f"panel_{pid}_json"):
            self.add_traits(**{f"panel_{pid}_json": traitlets.Unicode("{}").tag(sync=True)})
        self._plots_map[pid] = plot
        self._axes_map[pid]  = ax
        self._push(pid)
        self._push_layout()

    def _push(self, panel_id: str) -> None:
        """Serialise one panel and write to its trait."""
        plot = self._plots_map.get(panel_id)
        if plot is None:
            return
        tname = f"panel_{panel_id}_json"
        if not self.has_trait(tname):
            return
        setattr(self, tname, json.dumps(plot.to_state_dict()))

    # ── layout ────────────────────────────────────────────────────────────────
    def _compute_cell_sizes(self) -> dict:
        fw, fh = self.fig_width, self.fig_height
        wr, hr = self._width_ratios, self._height_ratios
        wsum, hsum = sum(wr), sum(hr)

        # Step 1: raw pixel size per grid track (float precision)
        col_px = [fw * w / wsum for w in wr]
        row_px = [fh * h / hsum for h in hr]

        # Step 2: aspect-lock every 2D panel by shrinking its track(s).
        # Multiple passes let interactions between panels converge.
        for _ in range(4):
            for pid, ax in self._axes_map.items():
                plot = self._plots_map.get(pid)
                if not isinstance(plot, (Plot2D, PlotMesh)):
                    continue
                s  = ax._spec
                cw = sum(col_px[s.col_start:s.col_stop])
                ch = sum(row_px[s.row_start:s.row_stop])
                iw = plot._state.get("image_width",  1)
                ih = plot._state.get("image_height", 1)
                if iw <= 0 or ih <= 0 or ch == 0:
                    continue
                ar = iw / ih
                if cw / ch > ar:               # wider than image -> shrink cols
                    new_cw = ch * ar
                    span   = max(1, s.col_stop - s.col_start)
                    for c in range(s.col_start, s.col_stop):
                        col_px[c] = new_cw / span
                else:                          # taller than image -> shrink rows
                    new_ch = cw / ar
                    span   = max(1, s.row_stop - s.row_start)
                    for r in range(s.row_start, s.row_stop):
                        row_px[r] = new_ch / span

        # Step 3: every panel gets the pixel size of its track span.
        # All panels sharing a row/col automatically have identical dimensions.
        sizes: dict = {}
        for pid, ax in self._axes_map.items():
            s  = ax._spec
            pw = int(round(sum(col_px[s.col_start:s.col_stop])))
            ph = int(round(sum(row_px[s.row_start:s.row_stop])))
            sizes[pid] = (max(64, pw), max(64, ph))
        return sizes

    def _push_layout(self) -> None:
        cell_sizes = self._compute_cell_sizes()
        all_ids    = list(self._axes_map.keys())
        share_groups: dict = {}

        def _mg(flag, key):
            if flag is True and len(all_ids) > 1:
                share_groups[key] = [list(all_ids)]
            elif isinstance(flag, list):
                share_groups[key] = flag

        _mg(self._sharex, "x")
        _mg(self._sharey, "y")

        panel_specs = []
        for pid, ax in self._axes_map.items():
            s        = ax._spec
            pw, ph   = cell_sizes.get(pid, (200, 200))
            plot     = self._plots_map.get(pid)
            panel_specs.append({
                "id":           pid,
                "kind":         "3d" if isinstance(plot, Plot3D) else ("2d" if isinstance(plot, (Plot2D, PlotMesh)) else "1d"),
                "row_start":    s.row_start,
                "row_stop":     s.row_stop,
                "col_start":    s.col_start,
                "col_stop":     s.col_stop,
                "panel_width":  pw,
                "panel_height": ph,
            })

        self.layout_json = json.dumps({
            "nrows":          self._nrows,
            "ncols":          self._ncols,
            "width_ratios":   self._width_ratios,
            "height_ratios":  self._height_ratios,
            "fig_width":      self.fig_width,
            "fig_height":     self.fig_height,
            "panel_specs":    panel_specs,
            "share_groups":   share_groups,
        })

    @traitlets.observe("fig_width", "fig_height")
    def _on_resize(self, change) -> None:
        self._push_layout()
        for pid in self._plots_map:
            self._push(pid)

    # ── helpers ───────────────────────────────────────────────────────────────
    def get_axes(self) -> list:
        return sorted(self._axes_map.values(),
                      key=lambda a: (a._spec.row_start, a._spec.col_start))

    def _repr_html_(self) -> str:
        """Return a self-contained iframe embedding the live widget.

        Used by Sphinx Gallery (via :class:`~docs._sg_html_scraper.ViewerScraper`)
        and by any HTML-capable notebook frontend that falls back to
        ``_repr_html_`` instead of the full ipywidgets protocol.
        """
        from viewer._repr_utils import repr_html_iframe
        return repr_html_iframe(self)

    def __repr__(self) -> str:
        return (f"Figure({self._nrows}x{self._ncols}, "
                f"panels={len(self._plots_map)}, "
                f"size={self.fig_width}x{self.fig_height})")


# ---------------------------------------------------------------------------
# subplots — module-level convenience
# ---------------------------------------------------------------------------

def subplots(nrows=1, ncols=1, *,
             sharex=False, sharey=False,
             figsize=(640, 480),
             width_ratios=None,
             height_ratios=None,
             gridspec_kw=None):
    """Create a :class:`Figure` and a grid of :class:`~viewer.figure_plots.Axes`.

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
    >>> import viewer as vw
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



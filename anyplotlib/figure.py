"""
figure.py
=========

Top-level :class:`Figure` widget and the :func:`subplots` factory.

``Figure`` is the only ``anywidget.AnyWidget`` subclass in anyplotlib.
It owns all traitlets and acts as the Python ↔ JavaScript bridge.
Use :func:`subplots` (the recommended entry-point) or construct a
``Figure`` directly and call :meth:`Figure.add_subplot` to attach data.

Example
-------
.. code-block:: python

    import numpy as np
    import anyplotlib as apl

    fig, axs = apl.subplots(1, 2, figsize=(800, 400))
    axs[0].imshow(np.random.standard_normal((128, 128)))
    axs[1].plot(np.sin(np.linspace(0, 6.28, 256)))
    fig
"""

from __future__ import annotations
import json, pathlib
import anywidget, numpy as np, traitlets
from anyplotlib.figure_plots import GridSpec, SubplotSpec, Axes, Plot2D, PlotMesh, Plot3D, PlotBar
from anyplotlib.callbacks import Event

__all__ = ["Figure", "GridSpec", "SubplotSpec", "subplots"]

_HERE = pathlib.Path(__file__).parent
_ESM_SOURCE = (_HERE / "figure_esm.js").read_text(encoding="utf-8")


class Figure(anywidget.AnyWidget):
    """Multi-panel interactive figure widget.

    The top-level container for all plots and the only ``anywidget.AnyWidget``
    subclass in anyplotlib. It owns all traitlets and acts as the Python ↔
    JavaScript bridge via the ``figure_esm.js`` canvas renderer.

    Create via :func:`subplots` (recommended) or directly::

        fig = Figure(2, 2, figsize=(800, 600))
        ax  = fig.add_subplot((0, 0))
        v2d = ax.imshow(data)

    Parameters
    ----------
    nrows, ncols : int, optional
        Grid dimensions. Default 1 row, 1 column.
    figsize : (width, height), optional
        Figure size in CSS pixels. Default ``(640, 480)``.
    width_ratios : list of float, optional
        Relative column widths. Length must equal *ncols*.
    height_ratios : list of float, optional
        Relative row heights. Length must equal *nrows*.
    sharex, sharey : bool, optional
        Link pan/zoom across all panels on the respective axis.
        Default False (independent pan/zoom per panel).


    See Also
    --------
    subplots : Recommended factory for creating Figure and Axes grid.
    """

    layout_json    = traitlets.Unicode("{}").tag(sync=True)
    fig_width      = traitlets.Int(640).tag(sync=True)
    fig_height     = traitlets.Int(480).tag(sync=True)
    # Bidirectional JS event bus: JS writes interaction events here, Python reads them.
    event_json     = traitlets.Unicode("{}").tag(sync=True)
    # When True the JS renderer shows a per-panel FPS / frame-time overlay.
    display_stats  = traitlets.Bool(False).tag(sync=True)
    # Figure-level help text shown in a '?' badge overlay in JS.
    # Empty string means no badge.  Gated by apl.show_help at the Python level.
    help_text      = traitlets.Unicode("").tag(sync=True)
    _esm = _ESM_SOURCE
    # Static CSS injected by anywidget alongside _esm.
    # .apl-scale-wrap  — outer container; width:100% means it always fills
    #                    the cell without any JS width updates.
    # .apl-outer       — the figure root; will-change:transform pre-promotes
    #                    it to a GPU compositing layer so transform:scale()
    #                    changes cost zero layout/paint passes.
    _css = """\
.apl-scale-wrap {
    display: block;
    width: 100%;
    overflow: visible;
    position: relative;
    line-height: 0;
}
.apl-outer {
    display: inline-block;
    position: relative;
    user-select: none;
    z-index: 1;
    isolation: isolate;
    will-change: transform;
    transform-origin: top left;
    vertical-align: top;
    /* min-width: max-content prevents the inline-block from shrinking when
       the parent container (scaleWrap, width:100%) narrows because the
       Jupyter cell is narrower than the figure's native width.  Without
       this, outerDiv.offsetWidth collapses to cellW, causing _applyScale()
       to compute s = cellW/cellW = 1.0 (no-op) instead of the correct
       s = cellW/nativeW < 1. */
    min-width: max-content;
}
"""

    def __init__(self, nrows=1, ncols=1, figsize=(640, 480),
                 width_ratios=None, height_ratios=None,
                 sharex=False, sharey=False,
                 display_stats=False, help="", **kwargs):
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
            self.fig_width     = figsize[0]
            self.fig_height    = figsize[1]
            self.display_stats = display_stats
            self.help_text     = self._resolve_help(help)
        self._push_layout()

    @staticmethod
    def _resolve_help(text: str) -> str:
        """Return *text* if ``apl.show_help`` is True (default), else ``""``."""
        try:
            import anyplotlib as _apl
            if not getattr(_apl, "show_help", True):
                return ""
        except ImportError:
            pass
        return text or ""

    def set_help(self, text: str) -> None:
        """Set (or clear) the figure-level help text shown in the **?** badge.

        Parameters
        ----------
        text : str
            Help string displayed when the user clicks the **?** badge.
            Pass an empty string (or ``""`` ) to remove the badge entirely.
            Newlines (``\\n``) are respected in the card.

        Examples
        --------
        >>> fig.set_help("Drag peak: move μ/A\\nPress f: least-squares fit")
        >>> fig.set_help("")   # hide the badge
        """
        self.help_text = self._resolve_help(text)

    # ── subplot creation ──────────────────────────────────────────────────────
    def add_subplot(self, spec) -> Axes:
        """Add a subplot cell and return its :class:`Axes`.

        Parameters
        ----------
        spec : SubplotSpec or int or tuple of (row, col)
            Which grid cell(s) to occupy.  A :class:`SubplotSpec` is used
            directly (e.g. from ``GridSpec[r, c]``).  An :class:`int` is
            converted via ``divmod(spec, ncols)``, matching
            ``matplotlib.Figure.add_subplot`` numbering.  A ``(row, col)``
            tuple selects a single cell.

        Returns
        -------
        Axes
            The subplot axes object. Call plotting methods like ``.imshow()``,
            ``.plot()``, ``.bar()`` to attach data.

        Raises
        ------
        TypeError
            If *spec* is not a SubplotSpec, int, or tuple.

        Examples
        --------
        >>> fig = Figure(2, 2)
        >>> ax1 = fig.add_subplot(0)       # top-left (via numbering)
        >>> ax2 = fig.add_subplot((0, 1))  # top-right (via tuple)
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

        # Grid tracks are pure ratio math — no aspect-locking.
        # Rule: col_px[i] = fw * width_ratios[i] / Σ width_ratios (and analogous
        # for rows).  Every panel gets exactly the canvas size its cell specifies;
        # images are rendered "contain" (letterboxed) in JS if needed.
        col_px = [fw * w / wsum for w in wr]
        row_px = [fh * h / hsum for h in hr]

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
                "kind":         ("3d"  if isinstance(plot, Plot3D)
                             else "2d"  if isinstance(plot, (Plot2D, PlotMesh))
                             else "bar" if isinstance(plot, PlotBar)
                             else "1d"),
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

    @traitlets.observe("event_json")
    def _on_event(self, change) -> None:
        """Dispatch a JS interaction event to the relevant plot and widget callbacks."""
        raw = change["new"]
        if not raw or raw == "{}":
            return
        try:
            msg = json.loads(raw)
        except Exception:
            return

        # Echo guard — Python-originated pushes must not loop back
        if msg.get("source") == "python":
            return

        panel_id   = msg.get("panel_id", "")
        event_type = msg.get("event_type", "on_changed")
        widget_id  = msg.get("widget_id")
        data = {k: v for k, v in msg.items()
                if k not in ("source", "panel_id", "event_type", "widget_id")}

        plot = self._plots_map.get(panel_id)
        if plot is None:
            return

        source = None
        if widget_id and hasattr(plot, "_widgets"):
            widget = plot._widgets.get(widget_id)
            if widget is not None:
                widget._update_from_js(data, event_type)
                source = widget

        if hasattr(plot, "callbacks"):
            event = Event(event_type=event_type, source=source, data=data)
            plot.callbacks.fire(event)

    def _push_widget(self, panel_id: str, widget_id: str, fields: dict) -> None:
        """Send a targeted widget-position update to JS (no image data)."""
        payload = {"source": "python", "panel_id": panel_id,
                   "widget_id": widget_id}
        payload.update(fields)
        self.event_json = json.dumps(payload)

    # ── helpers ───────────────────────────────────────────────────────────────
    def get_axes(self) -> list:
        """Return a list of all Axes, sorted by grid position.

        Returns
        -------
        list of Axes
            Axes sorted by (row_start, col_start) to match typical left-to-right,
            top-to-bottom iteration order.
        """
        return sorted(self._axes_map.values(),
                      key=lambda a: (a._spec.row_start, a._spec.col_start))

    def _repr_html_(self) -> str:
        """Return a self-contained iframe embedding the live widget.

        Used by Sphinx Gallery (via :class:`~docs._sg_html_scraper.ViewerScraper`)
        and by any HTML-capable notebook frontend that falls back to
        ``_repr_html_`` instead of the full ipywidgets protocol.

        Returns
        -------
        str
            HTML string containing an embedded iframe with srcdoc attribute.
        """
        from anyplotlib._repr_utils import repr_html_iframe
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



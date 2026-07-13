"""
figure/_figure.py
=================
Top-level Figure widget (the single anywidget.AnyWidget subclass).
"""

from __future__ import annotations

import contextlib
import json
import pathlib
import time

import anywidget
import traitlets

import uuid as _uuid

from anyplotlib.axes import Axes, InsetAxes
from anyplotlib.axes._inset_axes import _plot_kind
from anyplotlib.figure._gridspec import SubplotSpec
from anyplotlib.callbacks import CallbackRegistry, Event, _EventMixin
from anyplotlib._repr_utils import repr_html_iframe


# Recognised figure-level annotation kinds and the fields each carries (beyond
# ``id`` + ``kind``). Positions/sizes are all in FIGURE FRACTIONS (0..1, origin
# top-left), so a marker keeps its relative place across figure resizes.
_FIGURE_MARKER_KINDS = {"text", "circle", "rect", "arrow"}

_HERE = pathlib.Path(__file__).parent.parent
_ESM_SOURCE = (_HERE / "figure_esm.js").read_text(encoding="utf-8")


def _binary_wire() -> bool:
    """True when the Electron binary pixel transport is live, so a pixel
    change-token in the panel state should stay a token (the real bytes ride
    PLOTBIN) rather than being resolved to inline base64. Read fresh from the
    environment — the same gate ``Plot2D._encode_pixels`` uses — so producer and
    serializer never disagree."""
    import os
    return os.environ.get("APL_BINARY_TRANSPORT") == "1"


class Figure(anywidget.AnyWidget, _EventMixin):
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
    # ── Edit-mode chrome (Report Builder) ─────────────────────────────────────
    # edit_chrome     — when True the JS renderer shows per-panel hover outlines,
    #                   makes figure-level markers hit-testable/draggable, and
    #                   emits figure-background clicks.  When False all of this
    #                   is inert — normal interaction is untouched.
    # selected_panel  — a panel id (or "") that gets a persistent solid outline;
    #                   all others clear.  Pure JS-local DOM styling, no export.
    edit_chrome    = traitlets.Bool(False).tag(sync=True)
    selected_panel = traitlets.Unicode("").tag(sync=True)
    # Figure-level annotation layer: a JSON list of marker dicts positioned in
    # FIGURE FRACTIONS, drawn over all panels.  See set_figure_markers.
    figure_markers_json = traitlets.Unicode("[]").tag(sync=True)
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
        self._insets_map: dict = {}
        self._hspace: float | None = None
        self._wspace: float | None = None
        self._batching: bool = False
        self._batch_dirty: set = set()
        # Geometry-channel bookkeeping (per panel id): a monotonic revision
        # and the last geometry dict sent, so geometry is re-transmitted only
        # when its values genuinely change.
        self._geom_rev: dict = {}
        self._geom_last: dict = {}
        # Raw pixel side-table for the Electron BINARY transport: maps
        # ``(panel_id, pixel_key)`` → the raw ``bytes`` of the current frame.
        # When binary transport is active, ``Plot2D.set_data`` stashes the
        # uint8 image bytes here (and puts a tiny change-token in the geom
        # field instead of a 5.6 MB base64 string), so ``_electron._route_change``
        # ships them straight to a PLOTBIN frame with NO base64 encode/decode
        # and NO megabyte JSON. Empty (and ignored) on every non-Electron path.
        self._raw_pixels: dict = {}
        # Figure-level (not per-panel) callback registry + the _EventMixin API
        # (add_event_handler / remove_handler / pause_events / hold_events).
        # Fired for figure-background clicks and figure-marker pointer events.
        self.callbacks: CallbackRegistry = CallbackRegistry()
        # Authoritative Python-side copy of the figure-level annotation list.
        self._figure_markers: list = []
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

    def subplots_adjust(self, hspace: float | None = None,
                        wspace: float | None = None) -> None:
        """Set the spacing between subplot panels.

        Only the arguments that are explicitly provided are updated; omitting
        an argument leaves the current value unchanged.

        Parameters
        ----------
        hspace : float, optional
            Fraction of the average row height to use as vertical gap between
            panels.  ``0.1`` adds a gap of 10 % of the mean row height.
            ``None`` (default) leaves the current hspace unchanged.
        wspace : float, optional
            Fraction of the average column width to use as horizontal gap.
            ``None`` (default) leaves the current wspace unchanged.
        """
        if hspace is not None:
            self._hspace = float(hspace)
        if wspace is not None:
            self._wspace = float(wspace)
        self._push_layout()

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
            # Auto-sync Figure grid to the parent GridSpec when the GridSpec is
            # larger than the Figure's current dimensions.  This allows the
            # common workflow:
            #   gs = GridSpec(2, 2, height_ratios=[3, 1])
            #   fig = Figure(figsize=(...))   # defaults to nrows=1, ncols=1
            #   fig.add_subplot(gs[0, :])     # Figure adopts 2×2 from GridSpec
            # without requiring the user to repeat nrows/ncols/ratios on Figure.
            gs = spec._gs
            if gs is not None:
                if gs.nrows > self._nrows:
                    self._nrows = gs.nrows
                    self._height_ratios = list(gs.height_ratios)
                if gs.ncols > self._ncols:
                    self._ncols = gs.ncols
                    self._width_ratios = list(gs.width_ratios)
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
        # Plots that declare _GEOM_KEYS get a second trait carrying only the
        # heavy geometry, re-sent only when that geometry changes.  The light
        # view trait then references it by revision so JS reuses the cached
        # decode across view-only updates (highlight, camera, planes).
        if getattr(plot, "_GEOM_KEYS", None) and not self.has_trait(f"panel_{pid}_geom"):
            self.add_traits(**{f"panel_{pid}_geom": traitlets.Unicode("{}").tag(sync=True)})
            self._geom_rev[pid] = 0
            self._geom_last[pid] = None
        self._plots_map[pid] = plot
        self._axes_map[pid]  = ax
        self._push(pid)
        self._push_layout()

    def _push(self, panel_id: str) -> None:
        """Serialise one panel and write to its trait.

        Inside a :meth:`batch` block, pushes are coalesced: each panel is
        recorded as dirty and serialised + sent exactly once when the block
        exits, no matter how many mutations touched it.  This collapses the
        many per-frame pushes of a linked-view update (set_data + set_title +
        widget moves on the same panel) into one serialise/transfer per panel
        — the dominant cost over a Pyodide comm boundary.
        """
        plot = self._plots_map.get(panel_id)
        if plot is None:
            return
        if self._batching:
            self._batch_dirty.add(panel_id)
            return
        tname = f"panel_{panel_id}_json"
        if not self.has_trait(tname):
            return

        state = plot.to_state_dict()
        geom_keys = getattr(plot, "_GEOM_KEYS", None)
        gname = f"panel_{panel_id}_geom"
        # ``state`` may carry a ``"\x00bin:…"`` pixel change-token (binary
        # transport: the real bytes ride PLOTBIN via ``_route_change``). Keep
        # the token when that channel is live; otherwise — a standalone /
        # save_html / Jupyter figure with no binary channel — materialise the
        # real base64 inline so the pixels actually travel. ``_binary_wire``
        # matches the producer's gate (``Plot2D._encode_pixels``).
        if geom_keys and not _binary_wire() and hasattr(plot, "resolve_pixel_tokens"):
            plot.resolve_pixel_tokens(state)
        if geom_keys and self.has_trait(gname):
            # Split heavy geometry into its own channel.  Detect change by
            # comparing the geom values themselves (the b64 strings / LUT
            # lists) against the last-sent snapshot — a reference/equality
            # check that avoids re-serialising hundreds of KB on every
            # view-only frame.  Only on a real change do we serialise the
            # geom blob, bump the revision, and write the geom trait.
            geom = {k: state.pop(k) for k in geom_keys if k in state}
            if geom != self._geom_last.get(panel_id):
                self._geom_last[panel_id] = geom
                self._geom_rev[panel_id] = self._geom_rev.get(panel_id, 0) + 1
                setattr(self, gname, json.dumps(geom, sort_keys=True))
            state["_geom_rev"] = self._geom_rev.get(panel_id, 0)
            setattr(self, tname, json.dumps(state))
        else:
            setattr(self, tname, json.dumps(state))

    @contextlib.contextmanager
    def batch(self):
        """Coalesce all panel pushes within the block into one push per panel.

        Use around multi-panel updates (e.g. a linked-view crosshair handler)
        so a single mouse event produces one serialise + transfer per panel
        instead of one per mutation — a large win under Pyodide / remote
        kernels where every push crosses a comm boundary.

        ::

            with fig.batch():
                v_xz.set_data(slice_xz)
                v_yz.set_data(slice_yz)
                cross.set(cx=..., cy=...)
        """
        if self._batching:          # already batching — nest transparently
            yield
            return
        self._batching = True
        self._batch_dirty = set()
        try:
            yield
        finally:
            self._batching = False
            dirty, self._batch_dirty = self._batch_dirty, set()
            # One push per dirty panel — no matter how many mutations touched
            # it during the block.  hold_trait_notifications coalesces the
            # underlying comm traffic into a single sync.
            with self.hold_trait_notifications():
                for pid in dirty:
                    self._push(pid)

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
                "kind":         _plot_kind(plot) if plot else "1d",
                "row_start":    s.row_start,
                "row_stop":     s.row_stop,
                "col_start":    s.col_start,
                "col_stop":     s.col_stop,
                "panel_width":  pw,
                "panel_height": ph,
            })

        inset_specs = []
        indications = []
        for pid, inset_ax in self._insets_map.items():
            plot = self._plots_map.get(pid)
            pw = max(64, round(self.fig_width  * inset_ax.w_frac))
            ph = max(64, round(self.fig_height * inset_ax.h_frac))
            inset_specs.append({
                "id":           pid,
                "kind":         _plot_kind(plot) if plot else "1d",
                "w_frac":       inset_ax.w_frac,
                "h_frac":       inset_ax.h_frac,
                # corner is None for anchor-placed insets; anchor is None for
                # corner-placed ones.  JS picks the placement mode by which is set.
                "corner":       inset_ax.corner,
                "anchor":       list(inset_ax.anchor)
                                if getattr(inset_ax, "anchor", None) is not None
                                else None,
                "title":        inset_ax.title,
                "panel_width":  pw,
                "panel_height": ph,
                "inset_state":  inset_ax._inset_state,
            })
            # Region indication (mark_inset callout) is keyed by the inset id.
            ind = getattr(inset_ax, "_indication", None)
            if ind is not None:
                indications.append({"inset_id": pid, **ind})

        self.layout_json = json.dumps({
            "nrows":          self._nrows,
            "ncols":          self._ncols,
            "width_ratios":   self._width_ratios,
            "height_ratios":  self._height_ratios,
            "fig_width":      self.fig_width,
            "fig_height":     self.fig_height,
            "panel_specs":    panel_specs,
            "share_groups":   share_groups,
            "inset_specs":    inset_specs,
            "indications":    indications,
            "hspace":         self._hspace,
            "wspace":         self._wspace,
        })

    # ── inset creation ────────────────────────────────────────────────────────
    def add_inset(self, w_frac: float, h_frac: float, *,
                  corner: str = "top-right", anchor=None,
                  title: str = "") -> "InsetAxes":
        """Create and return a floating inset axes.

        The inset overlays the figure at the specified corner (default) or at
        an arbitrary *anchor* position.  Call plot-factory methods on the
        returned :class:`InsetAxes` to attach data::

            inset = fig.add_inset(0.3, 0.25, corner="top-right", title="Zoom")
            inset.imshow(data)    # returns Plot2D
            inset.plot(profile)   # returns Plot1D

            # arbitrary placement (top-left corner at 55% across, 10% down):
            free = fig.add_inset(0.3, 0.25, anchor=(0.55, 0.10))
            free.imshow(data)

        Parameters
        ----------
        w_frac, h_frac : float
            Width and height as fractions of the figure size (0–1).
        corner : str, optional
            Positioning corner: ``"top-right"`` (default), ``"top-left"``,
            ``"bottom-right"``, or ``"bottom-left"``.  Mutually exclusive with
            *anchor*.
        anchor : (x_frac, y_frac), optional
            Position of the inset's TOP-LEFT corner as fractions of the figure
            size (0–1), from the figure's top-left.  When given, the inset
            floats at that anchor and *corner* is ignored.  Use this for
            free placement (e.g. a callout panel next to the region it marks).
        title : str, optional
            Text displayed in the inset title bar.

        Returns
        -------
        InsetAxes
        """
        return InsetAxes(self, w_frac, h_frac, corner=corner,
                         anchor=anchor, title=title)

    def _register_inset(self, inset_ax: "InsetAxes", plot) -> None:
        """Register an inset plot, allocating its trait and updating layout."""
        pid = plot._id
        if not self.has_trait(f"panel_{pid}_json"):
            self.add_traits(**{f"panel_{pid}_json": traitlets.Unicode("{}").tag(sync=True)})
        self._plots_map[pid]  = plot
        self._insets_map[pid] = inset_ax
        self._push(pid)
        self._push_layout()

    @traitlets.observe("fig_width", "fig_height")
    def _on_resize(self, change) -> None:
        self._push_layout()
        for pid in self._plots_map:
            self._push(pid)

    @traitlets.observe("event_json")
    def _on_event(self, change) -> None:
        """Dispatch a JS interaction event to the relevant plot and widget callbacks."""
        self._dispatch_event(change["new"])

    def _dispatch_event(self, raw: str) -> None:
        """Process a raw JSON event string from the JS side.

        Called by ``_on_event`` (traitlets observer) and also directly by the
        Pyodide bridge (``anywidget_bridge.js``) when forwarding user interaction
        events from the iframe back to Python callbacks.

        Parameters
        ----------
        raw : str
            JSON-encoded event message.  Expected keys: ``event_type``,
            ``panel_id``, and optionally ``source``, ``widget_id``, plus
            any event-specific payload fields.
        """
        if not raw or raw == "{}":
            return
        try:
            msg = json.loads(raw)
        except Exception:
            return

        if msg.get("source") == "python":
            return

        panel_id   = msg.get("panel_id", "")
        event_type = msg.get("event_type", "pointer_move")
        widget_id  = msg.get("widget_id")

        # ── Figure-level events (edit mode) — handled BEFORE per-panel lookup ──
        # A click on the bare figure background (no panel underneath).
        if msg.get("figure_background"):
            self._fire_figure_event(event_type, msg)
            return

        # A drag/click on a figure-level annotation marker.  On pointer_up the
        # JS ships the marker's updated FRACTION fields; merge them into the
        # stored list so Python state converges, then fire figure callbacks.
        if msg.get("figure_marker"):
            self._apply_figure_marker_event(msg)
            self._fire_figure_event(event_type, msg)
            return

        # Inset state changes handled before regular plot dispatch
        if event_type == "inset_state_change":
            inset_ax = self._insets_map.get(panel_id)
            if inset_ax is not None:
                new_state = msg.get("new_state", "normal")
                if new_state in ("normal", "minimized", "maximized"):
                    inset_ax._inset_state = new_state
                    self._push_layout()
            return

        plot = self._plots_map.get(panel_id)
        if plot is None:
            if event_type == "view_changed":
                import logging
                # WARNING so SpyDE's log stream forwards it (it drops non-spyde.* INFO).
                logging.getLogger("anyplotlib.tile").warning(
                    "[TILE] view_changed for UNKNOWN panel %r (have %r) — dropped",
                    panel_id, list(self._plots_map.keys()))
            return

        if event_type == "view_changed":
            import logging
            logging.getLogger("anyplotlib.tile").warning(
                "[TILE] view_changed RECEIVED panel=%s zoom=%s center=(%s,%s) disp=(%s,%s)",
                panel_id, msg.get("zoom"), msg.get("center_x"), msg.get("center_y"),
                msg.get("display_width"), msg.get("display_height"))

        # GPU activation status echo (WebGPU path) — not a user event.
        if event_type == "gpu_status":
            if hasattr(plot, "_set_gpu_active"):
                plot._set_gpu_active(bool(msg.get("gpu_active", False)))
            return

        source = None
        if widget_id and hasattr(plot, "_widgets"):
            widget = plot._widgets.get(widget_id)
            if widget is not None:
                widget._update_from_js(msg, event_type)
                source = widget

        if hasattr(plot, "callbacks"):
            event = Event(
                event_type=event_type,
                source=source,
                time_stamp=msg.get("time_stamp", time.perf_counter()),
                modifiers=msg.get("modifiers", []),
                x=msg.get("x"),
                y=msg.get("y"),
                button=msg.get("button"),
                buttons=msg.get("buttons", 0),
                xdata=msg.get("xdata"),
                ydata=msg.get("ydata"),
                ray=msg.get("ray"),
                line_id=msg.get("line_id"),
                dwell_ms=msg.get("dwell_ms"),
                bar_index=msg.get("bar_index"),
                value=msg.get("value"),
                x_label=msg.get("x_label"),
                group_index=msg.get("group_index"),
                dx=msg.get("dx"),
                dy=msg.get("dy"),
                zoom=msg.get("zoom"),
                center_x=msg.get("center_x"),
                center_y=msg.get("center_y"),
                image_width=msg.get("image_width"),
                image_height=msg.get("image_height"),
                display_width=msg.get("display_width"),
                display_height=msg.get("display_height"),
                key=msg.get("key"),
                last_widget_id=msg.get("last_widget_id"),
            )
            plot.callbacks.fire(event)

    # ── figure-level annotation layer ─────────────────────────────────────────
    def _fire_figure_event(self, event_type: str, msg: dict) -> None:
        """Fire the FIGURE-level callback registry with a flat Event.

        Used for figure-background clicks and figure-marker pointer events —
        events that belong to the figure as a whole, not to any one panel.
        The marker id (if any) rides in ``last_widget_id`` so a host can tell
        which annotation moved.
        """
        event = Event(
            event_type=event_type,
            source=self,
            time_stamp=msg.get("time_stamp", time.perf_counter()),
            modifiers=msg.get("modifiers", []),
            x=msg.get("x"),
            y=msg.get("y"),
            button=msg.get("button"),
            buttons=msg.get("buttons", 0),
            xdata=msg.get("xdata"),
            ydata=msg.get("ydata"),
            last_widget_id=msg.get("marker_id"),
        )
        self.callbacks.fire(event)

    def _apply_figure_marker_event(self, msg: dict) -> None:
        """Merge a figure-marker drag's updated FRACTION fields into the stored
        marker list (matched by ``marker_id``) and re-sync the trait.

        The JS side already wrote ``figure_markers_json`` back on mouseup, but
        we converge Python's authoritative ``_figure_markers`` here too so a
        host reading ``fig.figure_markers`` inside its callback sees the new
        position immediately (and the two never drift)."""
        marker_id = msg.get("marker_id")
        if marker_id is None:
            return
        # Fraction fields the JS emits per kind.
        _pos_keys = ("x", "y", "u", "v", "r", "w", "h")
        for m in self._figure_markers:
            if m.get("id") == marker_id:
                for k in _pos_keys:
                    if k in msg:
                        m[k] = msg[k]
                break
        # Re-sync the trait from the authoritative list (source:"python" is not
        # relevant here — figure_markers_json is a plain state trait, not the
        # event bus, so this does not echo back through _dispatch_event).
        self.figure_markers_json = json.dumps(self._figure_markers)

    def set_figure_markers(self, markers: list) -> None:
        """Set the figure-level annotation layer.

        Parameters
        ----------
        markers : list of dict
            Each dict is ``{"id"?, "kind", ...}`` with positions/sizes in
            FIGURE FRACTIONS (0..1, origin top-left).  ``kind`` is one of:

            - ``"text"``   — ``x, y, text``; optional ``color``, ``fontsize``
            - ``"circle"`` — ``x, y, r`` (``r`` as a fraction of
              ``min(fig_width, fig_height)``); optional ``color``, ``linewidth``
            - ``"rect"``   — ``x, y`` (centre), ``w, h``; optional ``color``,
              ``linewidth``
            - ``"arrow"``  — ``x, y`` (tail), ``u, v`` (vector); optional
              ``color``, ``linewidth``

            Any dict missing an ``id`` is assigned a fresh one.

        Raises
        ------
        ValueError
            If a marker has an unrecognised ``kind``.
        """
        out = []
        for m in markers:
            m = dict(m)
            kind = m.get("kind")
            if kind not in _FIGURE_MARKER_KINDS:
                raise ValueError(
                    f"figure marker kind must be one of "
                    f"{sorted(_FIGURE_MARKER_KINDS)}, got {kind!r}")
            if not m.get("id"):
                m["id"] = str(_uuid.uuid4())[:8]
            out.append(m)
        self._figure_markers = out
        self.figure_markers_json = json.dumps(out)

    @property
    def figure_markers(self) -> list:
        """The current figure-level annotation list (list of dicts, fractions).

        Returns a shallow copy so external mutation doesn't desync the trait;
        call :meth:`set_figure_markers` to change it."""
        return [dict(m) for m in self._figure_markers]

    def _push_widget(self, panel_id: str, widget_id: str, fields: dict) -> None:
        """Send a targeted widget-position update to JS (no image data)."""
        payload = {"source": "python", "panel_id": panel_id,
                   "widget_id": widget_id}
        payload.update(fields)
        self.event_json = json.dumps(payload)

    def _push_panel_fields(self, panel_id: str, fields: dict) -> None:
        """Apply a small set of changed *fields* to a panel, then push once.

        The fields are merged into the panel's ``_state`` and the panel is
        pushed via the normal trait channel (authoritative for Jupyter,
        snapshots, and the Pyodide bridge alike).  Inside a :meth:`batch`
        block the push is coalesced, so many such field updates across many
        panels collapse to one serialise + transfer per panel per frame —
        the dominant per-frame cost over a comm boundary.
        """
        plot = self._plots_map.get(panel_id)
        if plot is not None:
            plot._state.update(fields)
        self._push(panel_id)

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
        return repr_html_iframe(self)

    def to_html(self, *, resizable: bool = True) -> str:
        """Return a self-contained HTML page rendering this figure.

        The page inlines the JS renderer and all data — no Jupyter kernel or
        network needed at view time.  Load it in any browser context, e.g.
        an Electron ``BrowserWindow`` or ``<webview>``.  See
        :mod:`anyplotlib.embed` for the full embedding guide (including live
        Python sync via ``FigureBridge``).
        """
        from anyplotlib.embed import to_html
        return to_html(self, resizable=resizable)

    def save_html(self, path, *, resizable: bool = True):
        """Write :meth:`to_html` output to *path*; returns the ``Path``."""
        from anyplotlib.embed import save_html
        return save_html(self, path, resizable=resizable)

    def close(self) -> None:
        """Close the figure.

        Fires a ``"close"`` event on every panel's :attr:`callbacks`, then
        hides the widget by setting its CSS ``display`` to ``"none"``.
        Subsequent calls are no-ops.
        """
        if getattr(self, "_closed", False):
            return
        self._closed = True
        close_event = Event(event_type="close")
        for plot in self._plots_map.values():
            if hasattr(plot, "callbacks"):
                plot.callbacks.fire(close_event)
        try:
            self.layout.display = "none"
        except Exception:
            pass

    def __repr__(self) -> str:
        return (f"Figure({self._nrows}x{self._ncols}, "
                f"panels={len(self._plots_map)}, "
                f"size={self.fig_width}x{self.fig_height})")

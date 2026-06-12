"""
_base_plot.py
=============
Shared base classes and mixins for all plot panel types.
"""

from __future__ import annotations

from contextlib import contextmanager

from anyplotlib.callbacks import _EventMixin


class _BasePlot(_EventMixin):
    """Universal base for Plot1D, Plot2D, PlotBar, and Plot3D.

    Contains methods identical across all four panel types and helper
    utilities used by view-setter and widget-adder methods.

    Subclasses must define:
        _state : dict         — the panel state dict
        _push() -> None       — serialize state and write to parent Figure
    """

    def configure_pointer_settled(self, ms: int, delta: float = 4) -> None:
        """Configure the pointer-settled event threshold (ms and pixel delta)."""
        self._state["pointer_settled_ms"]    = ms
        self._state["pointer_settled_delta"] = delta
        self._push()

    _configure_pointer_settled = configure_pointer_settled

    #: Mini-TeX formatting note shared by all label setters.
    #:
    #: Label strings support a small TeX subset inside ``$...$`` delimiters,
    #: rendered by the JS canvas engine (no MathJax needed):
    #:
    #: * ``$10^{-3}$`` / ``$x^2$``  — superscripts (exponents)
    #: * ``$E_F$`` / ``$k_{B}T$``   — subscripts
    #: * ``$\\alpha$ … $\\Omega$``  — Greek letters
    #: * ``\\times \\cdot \\pm \\degree \\AA \\infty \\propto \\approx``
    #:   ``\\leq \\geq \\neq \\partial \\nabla \\hbar \\rightarrow`` — symbols
    #: * ``$\\mathrm{...}$``        — upright text inside math (letters in
    #:   math mode are italic by default)
    #:
    #: Example: ``plot.set_xlabel(r"$q$ ($\\AA^{-1}$)", fontsize=14)``

    def _set_label(self, key: str, label: str, size_key: str,
                   fontsize: float | None) -> None:
        """Store a label string (TeX subset allowed) and its optional size."""
        self._state[key] = str(label)
        if fontsize is not None:
            self._state[size_key] = float(fontsize)
        self._push()

    def set_title(self, label: str, fontsize: float | None = None) -> None:
        """Set the panel title.

        Parameters
        ----------
        label : str
            Title text.  Supports the mini-TeX subset (``$10^{-3}$``,
            ``$\\alpha$``, …) — see the class notes on label formatting.
        fontsize : float, optional
            Font size in CSS pixels.  Default 11.  On 2-D panels the title
            strip grows to fit larger sizes.  1-D and bar titles render in a
            fixed 12-px strip, so the drawn size is clamped to 11 there.
        """
        self._set_label("title", label, "title_size", fontsize)

    def set_axis_off(self) -> None:
        self._state["axis_visible"] = False
        self._push()

    def set_axis_on(self) -> None:
        self._state["axis_visible"] = True
        self._push()

    @contextmanager
    def _python_view_push(self):
        """Context manager for view setters that must signal _view_from_python.

        Sets the flag on entry, yields for state mutations, then pushes
        and clears the flag on exit.
        """
        self._state["_view_from_python"] = True
        try:
            yield
        finally:
            self._push()
            self._state["_view_from_python"] = False

    def _make_widget_push_fn(self, widget):
        """Return a targeted-push closure for a widget.

        Replaces the repeated _tp / _targeted_push closures in every
        add_*_widget method.
        """
        plot_ref, wid_id = self, widget._id
        def _push():
            if plot_ref._fig is not None:
                fields = {k: v for k, v in widget._data.items()
                          if k not in ("id", "type")}
                plot_ref._fig._push_widget(plot_ref._id, wid_id, fields)
        return _push


class _PanelMixin:
    """Mixin for panels that support interactive widgets and tick control.

    Shared by Plot1D, Plot2D, and PlotBar. Provides _push (with widget
    serialization), widget management, and tick visibility control.

    Subclasses must define:
        _state : dict
        _fig   : object
        _id    : str
        _widgets : dict[str, Widget]
    """

    def _push(self) -> None:
        if self._fig is None:
            return
        self._state["overlay_widgets"] = [w.to_dict() for w in self._widgets.values()]
        self._fig._push(self._id)

    def set_tick_label_size(self, size: float) -> None:
        """Set the font size of the tick (axis number) labels in CSS pixels.

        Applies to both axes of the panel.  Default 10.

        Parameters
        ----------
        size : float
            Tick label font size in pixels.
        """
        self._state["tick_size"] = float(size)
        self._push()

    def set_ticks_visible(self, visible: bool, *, x: bool | None = None,
                          y: bool | None = None) -> None:
        if x is None and y is None:
            self._state["x_ticks_visible"] = bool(visible)
            self._state["y_ticks_visible"] = bool(visible)
        else:
            if x is not None:
                self._state["x_ticks_visible"] = bool(x)
            if y is not None:
                self._state["y_ticks_visible"] = bool(y)
        self._push()

    def get_widget(self, wid):
        """Return the Widget object by ID string or Widget instance."""
        from anyplotlib.widgets import Widget
        if isinstance(wid, Widget):
            wid = wid.id
        try:
            return self._widgets[wid]
        except KeyError:
            raise KeyError(wid)

    def remove_widget(self, wid) -> None:
        """Remove a widget by ID string or Widget instance."""
        from anyplotlib.widgets import Widget
        if isinstance(wid, Widget):
            wid = wid.id
        if wid not in self._widgets:
            raise KeyError(wid)
        del self._widgets[wid]
        self._push()

    def list_widgets(self) -> list:
        """Return a list of all active widget objects on this panel."""
        return list(self._widgets.values())

    def clear_widgets(self) -> None:
        """Remove all interactive overlay widgets from this panel."""
        self._widgets.clear()
        self._push()


class _MarkerMixin:
    """Mixin for panels that support static marker collections.

    Shared by Plot1D and Plot2D.

    Subclasses must define:
        _state : dict
        markers : MarkerRegistry
        _push() -> None
    """

    def _push_markers(self) -> None:
        self._state["markers"] = self.markers.to_wire_list()
        self._push()

    def _add_marker(self, mtype: str, name, **kwargs):
        return self.markers.add(mtype, name, **kwargs)

    def remove_marker(self, marker_type: str, name: str) -> None:
        """Remove a named marker collection by type and name.

        Parameters
        ----------
        marker_type : str
            Collection type, e.g. ``"points"``, ``"vlines"``.
        name : str
            The name used when the collection was created.
        """
        self.markers.remove(marker_type, name)

    def clear_markers(self) -> None:
        """Remove all marker collections from this panel."""
        self.markers.clear()

    def list_markers(self) -> list:
        """Return a summary list of all marker collections on this panel.

        Returns
        -------
        list of dict
            Each dict has keys ``"type"``, ``"name"``, and ``"n"``
            (number of markers in the collection).
        """
        out = []
        for mtype, td in self.markers._types.items():
            for name, g in td.items():
                out.append({"type": mtype, "name": name, "n": g._count()})
        return out

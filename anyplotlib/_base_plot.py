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

    # ------------------------------------------------------------------
    # Floating image keys (see anyplotlib/keys.py)
    # ------------------------------------------------------------------
    def add_key(self, image, *, corner: str = "top-right", anchor=None,
                size: float = 0.22, margin: float = 10.0,
                bgcolor=None, border=None, border_width: float = 1.0,
                radius: float = 4.0, alpha: float = 1.0,
                hover_only: bool = False, visible: bool = True,
                label=None, label_size: float = 10.0, label_color=None,
                labels=None, name=None) -> "KeyOverlay":
        """Pin a floating image key over this panel.

        A key is a small picture that floats in screen space over the plot
        area — it does not pan or zoom with the data.  Use it for a colour
        legend a colorbar cannot express: an inverse pole figure triangle over
        an orientation map, a hue wheel over a polarization field, a phase key
        over a segmentation::

            key = plot.add_key(ipf_triangle, corner="bottom-right", size=0.28)
            wheel = plot.add_key(hue_wheel, corner="top-left",
                                 bgcolor="none", hover_only=True)

        This is the lightweight sibling of :meth:`Figure.add_inset`.  An inset
        is a draggable window with a title bar and its own canvas stack — the
        right tool when the overlay is a live plot.  A key is a static picture
        with no chrome unless you ask for it, so it reads as part of the
        figure rather than as a floating panel.

        Parameters
        ----------
        image : array-like, bytes, or path
            An ``(H, W, 3|4)`` colour array (uint8, or float 0–1), the raw
            bytes of a PNG/JPEG/GIF/WebP, or a path to such a file.  An RGBA
            array is the usual choice: alpha 0 outside the shape lets a
            triangle or a disc sit on the image without a rectangular card
            around it.
        corner : str, optional
            ``"top-right"`` (default), ``"top-left"``, ``"bottom-right"`` or
            ``"bottom-left"``.  Ignored when *anchor* is given.
        anchor : (x_frac, y_frac), optional
            Free placement: the key's centre as a fraction of the plot area,
            from its top-left.  Overrides *corner*.
        size : float, optional
            Width as a fraction of the plot area's **shorter** side, so a key
            keeps its proportions when the panel is resized.  Default 0.22.
            Height follows the image's aspect ratio.
        margin : float, optional
            Gap in CSS px between the key and the plot-area edge, for corner
            placement.  Default 10.
        bgcolor : str, optional
            CSS colour painted behind the image — e.g. ``"rgba(0,0,0,0.45)"``
            for a legible card over busy data.  Default ``None`` (fully
            transparent); ``"none"`` means the same thing.
        border : str, optional
            CSS colour for a hairline around the card.  Default ``None``.
        border_width : float, optional
            Border stroke width in px.  Default 1.
        radius : float, optional
            Corner radius of the card in px.  Default 4.
        alpha : float, optional
            Opacity of the whole key, 0–1.  Default 1.
        hover_only : bool, optional
            Show the key only while the pointer is over the panel.  Default
            ``False``.  Useful for a reading aid you do not want sitting over
            the data all the time.  PNG export renders the panel as though the
            pointer were over it, so a hover-only key **is** included in an
            exported figure — what you save is what you see while reading.
        visible : bool, optional
            Draw the key at all.  Default ``True``.
        label : str, optional
            Caption drawn under the image, mini-TeX enabled like axis labels.
        label_size : float, optional
            Caption size in px.  Default 10.
        label_color : str, optional
            Caption colour.  Default ``None`` (the theme's tick-label colour).
        labels : list, optional
            Text drawn *inside* the key, for annotating the picture itself —
            an IPF triangle's corner indices, a wheel's compass points.  Each
            entry is ``(x, y, text)`` or a dict with those keys plus optional
            ``size`` / ``color`` / ``align``.  ``x`` and ``y`` are fractions of
            the key image, so the text follows the picture when the key is
            resized.  Mini-TeX works here as in any label::

                tri.add_key(ipf, labels=[
                    (0.02, 0.97, "[1 0 0]"),
                    (0.98, 0.97, "[1 1 0]"),
                    (0.98, 0.03, "[1 1 1]"),
                ])
        name : str, optional
            Handle for :meth:`get_key`.  Defaults to the generated id.

        Returns
        -------
        KeyOverlay

        See Also
        --------
        remove_key, list_keys, get_key
        anyplotlib.Figure.add_inset : a full floating axes, for live plots.
        """
        from anyplotlib._utils import _image_to_data_url
        from anyplotlib.keys import KeyOverlay, _validate

        fields = _validate(dict(
            corner=corner, anchor=anchor, size=size, margin=margin,
            bgcolor=bgcolor, border=border, border_width=border_width,
            radius=radius, alpha=alpha, hover_only=hover_only,
            visible=visible, label=label, label_size=label_size,
            label_color=label_color, labels=labels))
        key = KeyOverlay(self, _image_to_data_url(image), name=name, **fields)
        if any(k.name == key.name for k in self._key_map.values()):
            raise ValueError(f"a key named {key.name!r} already exists on this "
                             "panel; pass a different name=")
        self._key_map[key.id] = key
        self._push_keys()
        return key

    @property
    def _key_map(self) -> dict:
        """Lazily-created ``{id: KeyOverlay}`` — panels predate this feature."""
        if getattr(self, "_keys_dict", None) is None:
            self._keys_dict = {}
        return self._keys_dict

    def _push_keys(self) -> None:
        """Re-serialise the key list + image table, then push.

        The pictures ride the geometry channel under ``key_images`` so that
        restyling a key — or a hover toggle — never re-transmits them.
        """
        keys = list(self._key_map.values())
        self._state["keys"] = [k.to_dict() for k in keys]
        self._state["key_images"] = {k.id: k.image_url for k in keys}
        self._push()

    def get_key(self, name):
        """Return the key with this *name* (or id).

        Raises
        ------
        KeyError
            If no key matches.
        """
        for k in self._key_map.values():
            if k.name == name or k.id == name:
                return k
        raise KeyError(f"no key named {name!r}")

    def remove_key(self, key) -> None:
        """Remove a key, by object, name, or id."""
        from anyplotlib.keys import KeyOverlay
        kid = key.id if isinstance(key, KeyOverlay) else self.get_key(key).id
        if kid not in self._key_map:
            raise KeyError(kid)
        del self._key_map[kid]
        self._push_keys()

    def list_keys(self) -> list:
        """Every key on this panel, in creation order."""
        return list(self._key_map.values())

    def clear_keys(self) -> None:
        """Remove every key from this panel."""
        self._key_map.clear()
        self._push_keys()

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

        Also back-links the widget to this plot so :meth:`Widget.remove` can
        find its owner.  Every ``add_*_widget`` routes through here, so this is
        the one place that has to know.
        """
        plot_ref, wid_id = self, widget._id
        widget._plot = self
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

    # ── geometry / coordinate conversion ──────────────────────────────────
    #
    # These mirror the layout constants and letterbox math in figure_esm.js
    # (the PAD_* block near the top, and _imgFitRect).  They are here so that
    # callers doing display-space work — pixel-sized handles, hit-test
    # tolerances, screenshot-driven tests — do not each have to re-derive the
    # renderer's layout in their own code and then drift from it.

    #: Plot-area padding in CSS px: (left, right, top, bottom).
    #: Matches ``PAD_L``/``PAD_R``/``PAD_T``/``PAD_B`` in ``figure_esm.js``.
    PLOT_PADDING = (58, 12, 12, 42)

    def _panel_size(self) -> tuple[float, float]:
        """(panel_width, panel_height) in CSS px, from the figure's layout."""
        import json

        if self._fig is None:
            raise RuntimeError("panel is not attached to a figure")
        try:
            layout = json.loads(self._fig.layout_json)
            spec = next(s for s in layout["panel_specs"] if s["id"] == self._id)
        except (AttributeError, KeyError, StopIteration, ValueError) as exc:
            raise RuntimeError(f"no layout entry for panel {self._id!r}") from exc
        return float(spec["panel_width"]), float(spec["panel_height"])

    def _pad_top(self) -> float:
        """Title-strip height. Mirrors ``_padT`` in figure_esm.js."""
        pad_t = float(self.PLOT_PADDING[2])
        title = self._state.get("title")
        if not title:
            return pad_t
        size = float(self._state.get("title_size") or 11)
        has_tex = "$" in str(title)
        if size <= 11 and not has_tex:
            return pad_t
        import math

        return max(pad_t, math.ceil(size * 1.3) + (4 if has_tex else 2))

    def plot_box(self) -> dict:
        """Return the panel's plot area in CSS pixels.

        Returns
        -------
        dict
            ``{"x", "y", "width", "height"}`` — the drawable rectangle
            relative to the panel's top-left corner.  On a 2-D image panel it
            is the *letterboxed image* rather than the whole padded area,
            because that is what image coordinates actually map onto.

        Raises
        ------
        RuntimeError
            If the panel is not attached to a figure, so it has no layout.

        Notes
        -----
        Computed from the figure's own layout, so it is exact for the sizes
        the renderer was given.  A browser resized without a re-layout will
        disagree.  Zoom and pan are *not* folded in — this is the box, not
        the visible data window; :meth:`data_to_display` accounts for them.
        """
        left, right, top, bottom = self.PLOT_PADDING
        pw, ph = self._panel_size()
        pad_t = self._pad_top()

        # A 2-D panel drops the left/right/bottom gutters when it has no
        # physical axes to label — the image then fills the panel width.
        # 1-D panels always draw axes.  Mirrors `hasPhysAxis` in the JS.
        iw = self._state.get("image_width")
        ih = self._state.get("image_height")
        is_image = bool(iw and ih)
        has_axes = (not is_image) or bool(
            self._state.get("has_axes") or self._state.get("is_mesh")
        )

        x = float(left) if has_axes else 0.0
        y = float(pad_t)
        width = max((pw - left - right) if has_axes else pw, 1.0)
        height = max(ph - pad_t - (bottom if has_axes else 0.0), 1.0)

        # The colorbar strip and its gap come out of the image width.
        if self._state.get("show_colorbar") and not self._state.get("is_rgb"):
            label = self._state.get("colorbar_label")
            label_w = round((self._state.get("colorbar_label_size") or 10) + 8) \
                if label else 0
            pad = self._state.get("colorbar_pad")
            gap = 6.0 if pad is None else max(0.0, float(pad))
            width = max(width - (16 + label_w) - gap, 1.0)

        if is_image:
            # Images are drawn "contain" — see _imgFitRect.
            scale = min(width / float(iw), height / float(ih))
            fit_w, fit_h = float(iw) * scale, float(ih) * scale
            x += (width - fit_w) / 2.0
            y += (height - fit_h) / 2.0
            width, height = fit_w, fit_h

        return {"x": x, "y": y, "width": width, "height": height}

    def _visible_image_window(self) -> tuple[float, float, float, float]:
        """(src_x, src_y, vis_w, vis_h) of the visible image region, in image px.

        Mirrors the zoom/pan window in ``_imgToCanvas2d``.
        """
        iw = float(self._state.get("image_width") or 1)
        ih = float(self._state.get("image_height") or 1)
        zoom = float(self._state.get("zoom") or 1.0)
        cx = float(self._state.get("center_x", 0.5))
        cy = float(self._state.get("center_y", 0.5))
        if zoom < 1.0:
            # Zoomed out: the whole image, drawn smaller and centred. The box
            # shrinks rather than the source window growing.
            return 0.0, 0.0, iw, ih
        vis_w, vis_h = iw / zoom, ih / zoom
        src_x = max(0.0, min(iw - vis_w, cx * iw - vis_w / 2.0))
        src_y = max(0.0, min(ih - vis_h, cy * ih - vis_h / 2.0))
        return src_x, src_y, vis_w, vis_h

    def data_to_display(self, points):
        """Convert data coordinates to CSS pixels within the panel.

        Parameters
        ----------
        points : array-like
            A single ``(x, y)`` pair or an ``(N, 2)`` sequence of them.

            On a 1-D panel these are axis values.  On a 2-D panel they are
            **image-pixel coordinates** — the same space marker ``offsets``
            and widget positions use — where integer *i* means the *centre*
            of pixel *i*, not its leading edge.

        Returns
        -------
        numpy.ndarray
            Same shape as *points*, in panel pixels with the origin at the
            panel's top-left corner and y increasing downwards.  Zoom and pan
            are accounted for.
        """
        import numpy as np

        pts = np.atleast_2d(np.asarray(points, dtype=float))
        if pts.shape[-1] != 2:
            raise ValueError(f"points must have shape (N, 2); got {pts.shape}")
        box = self.plot_box()

        if self._state.get("image_width") and self._state.get("image_height"):
            zoom = float(self._state.get("zoom") or 1.0)
            src_x, src_y, vis_w, vis_h = self._visible_image_window()
            w = box["width"] * (zoom if zoom < 1.0 else 1.0)
            h = box["height"] * (zoom if zoom < 1.0 else 1.0)
            x0 = box["x"] + (box["width"] - w) / 2.0
            y0 = box["y"] + (box["height"] - h) / 2.0
            px = x0 + (pts[:, 0] + 0.5 - src_x) / vis_w * w
            py = y0 + (pts[:, 1] + 0.5 - src_y) / vis_h * h
        else:
            xlo, xhi = self.get_xlim()
            ylo, yhi = self.get_ylim()
            px = box["x"] + (pts[:, 0] - xlo) / ((xhi - xlo) or 1.0) * box["width"]
            # Screen y grows downwards, data y upwards.
            py = box["y"] + (
                1.0 - (pts[:, 1] - ylo) / ((yhi - ylo) or 1.0)
            ) * box["height"]

        out = np.column_stack([px, py])
        return out if np.ndim(points) == 2 else out[0]

    def display_to_data(self, points):
        """Convert CSS pixels within the panel to data coordinates.

        The inverse of :meth:`data_to_display`; same argument shapes and the
        same per-panel-kind coordinate meaning.
        """
        import numpy as np

        pts = np.atleast_2d(np.asarray(points, dtype=float))
        if pts.shape[-1] != 2:
            raise ValueError(f"points must have shape (N, 2); got {pts.shape}")
        box = self.plot_box()

        if self._state.get("image_width") and self._state.get("image_height"):
            zoom = float(self._state.get("zoom") or 1.0)
            src_x, src_y, vis_w, vis_h = self._visible_image_window()
            w = box["width"] * (zoom if zoom < 1.0 else 1.0)
            h = box["height"] * (zoom if zoom < 1.0 else 1.0)
            x0 = box["x"] + (box["width"] - w) / 2.0
            y0 = box["y"] + (box["height"] - h) / 2.0
            dx = (pts[:, 0] - x0) / (w or 1.0) * vis_w + src_x - 0.5
            dy = (pts[:, 1] - y0) / (h or 1.0) * vis_h + src_y - 0.5
        else:
            xlo, xhi = self.get_xlim()
            ylo, yhi = self.get_ylim()
            dx = xlo + (pts[:, 0] - box["x"]) / (box["width"] or 1.0) \
                * ((xhi - xlo) or 1.0)
            dy = ylo + (
                1.0 - (pts[:, 1] - box["y"]) / (box["height"] or 1.0)
            ) * ((yhi - ylo) or 1.0)

        out = np.column_stack([dx, dy])
        return out if np.ndim(points) == 2 else out[0]

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


class _TextHandle:
    """Handle for a single text annotation created by :meth:`add_text`.

    Wraps the underlying single-text :class:`~anyplotlib.markers.MarkerGroup`
    and exposes label-oriented mutators (``set_text`` / ``set_color`` /
    ``remove``) so callers do not need to know it is backed by a texts
    marker collection.
    """

    __slots__ = ("_group",)

    def __init__(self, group):
        self._group = group

    def set_text(self, s: str) -> None:
        """Replace the displayed string."""
        self._group.set(texts=[s])

    def set_color(self, color: str) -> None:
        """Change the text colour."""
        self._group.set(color=color)

    def remove(self) -> None:
        """Remove the annotation from its panel."""
        self._group.remove()

    def __repr__(self) -> str:  # pragma: no cover
        texts = self._group._data.get("texts") or [""]
        return f"_TextHandle(text={texts[0]!r})"


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

    def add_text(self, x, y, s, name=None, *, color="#ff0000",
                 fontsize=12, transform="data", **kwargs) -> "_TextHandle":
        """Add a single text annotation at ``(x, y)``.

        A convenience wrapper over :meth:`add_texts` for the common
        single-label case (e.g. a navigation index or scale-bar label).
        The returned handle exposes ``set_text``, ``set_color`` and
        ``remove`` so callers can mutate the label after creation.

        Parameters
        ----------
        x, y : float
            Anchor position.  Interpreted in the coordinate system named
            by ``transform`` (``"data"``, ``"axes"``, or ``"display"``).
        s : str
            The text to display.
        name : str, optional
            Registry key.  Auto-generated if omitted.
        color : str, optional
            Text colour.  Default ``"#ff0000"``.
        fontsize : int, optional
            Font size in pixels.  Default ``12``.
        transform : str, optional
            Coordinate system for ``(x, y)``.  Default ``"data"``.
        **kwargs : dict
            Forwarded to :meth:`add_texts` (e.g. ``clip_display``).

        Returns
        -------
        _TextHandle
            Handle wrapping the underlying single-text marker group.
        """
        group = self.add_texts(
            offsets=[(x, y)], texts=[s], name=name,
            color=color, fontsize=fontsize, transform=transform, **kwargs,
        )
        return _TextHandle(group)

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

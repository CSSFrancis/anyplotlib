"""
plot2d/_plot2d.py
=================
2-D image panel (imshow).
"""

from __future__ import annotations

import numpy as np
from typing import Callable

from anyplotlib.markers import MarkerRegistry
from anyplotlib.callbacks import CallbackRegistry, _EventMixin
from anyplotlib.widgets import (
    Widget,
    RectangleWidget, CircleWidget, AnnularWidget,
    CrosshairWidget, PolygonWidget, LabelWidget,
)
from anyplotlib._utils import _normalize_image, _build_colormap_lut


class Plot2D(_EventMixin):
    """2-D image plot panel.

    Not an anywidget.  Holds state in ``_state`` dict; every mutation calls
    ``_push()`` which writes to the parent Figure's panel trait.

    The marker API follows matplotlib conventions:
        plot.add_circles(offsets, name="g1", facecolors="#f00", radius=5)
        plot.markers["circles"]["g1"].set(radius=8)
    """

    def __init__(self, data: np.ndarray,
                 x_axis=None, y_axis=None, units: str = "px",
                 cmap: str | None = None,
                 vmin: float | None = None,
                 vmax: float | None = None,
                 origin: str = "upper"):
        self._id:  str = ""       # assigned by Axes._attach
        self._fig: object = None  # assigned by Axes._attach

        _valid_origins = ("upper", "lower")
        if origin not in _valid_origins:
            raise ValueError(
                f"origin must be one of {_valid_origins!r}, got {origin!r}"
            )
        self._origin: str = origin

        data = np.asarray(data)
        if data.ndim == 3:
            data = data[:, :, 0]
        if data.ndim != 2:
            raise ValueError(f"data must be 2-D (H x W), got {data.shape}")

        h, w = data.shape

        # origin='lower' — row 0 at the bottom, matching matplotlib's matrix
        # convention.  Flip the data so our renderer (which always draws row 0
        # at the top) shows the correct orientation, and reverse the y-axis so
        # tick values increase upward.
        if origin == "lower":
            data = np.flipud(data)

        self._data: np.ndarray = data.astype(float)

        x_axis_given = x_axis is not None
        y_axis_given = y_axis is not None
        if x_axis is None:
            x_axis = np.arange(w, dtype=float)
        if y_axis is None:
            y_axis = np.arange(h, dtype=float)
        x_axis = np.asarray(x_axis, dtype=float)
        y_axis = np.asarray(y_axis, dtype=float)

        if origin == "lower":
            y_axis = y_axis[::-1]

        img_u8, raw_vmin, raw_vmax = _normalize_image(data)
        self._raw_u8   = img_u8
        self._raw_vmin = raw_vmin
        self._raw_vmax = raw_vmax

        cmap_name = cmap if cmap is not None else "gray"
        cmap_lut  = _build_colormap_lut(cmap_name)

        # vmin/vmax clip the colormap in data units; default to the full range.
        disp_min = float(vmin) if vmin is not None else raw_vmin
        disp_max = float(vmax) if vmax is not None else raw_vmax

        # Compute physical pixel scale (data-units per pixel) from axis arrays
        scale_x = float(abs(x_axis[-1] - x_axis[0]) / max(w - 1, 1)) if len(x_axis) >= 2 else 1.0
        scale_y = float(abs(y_axis[-1] - y_axis[0]) / max(h - 1, 1)) if len(y_axis) >= 2 else 1.0

        self._state: dict = {
            "kind":              "2d",
            "is_mesh":           False,
            "has_axes":          x_axis_given or y_axis_given,
            "image_b64":         self._encode_bytes(img_u8),
            "image_width":       w,
            "image_height":      h,
            "x_axis":            x_axis.tolist(),
            "y_axis":            y_axis.tolist(),
            "units":             units,
            "scale_x":           scale_x,
            "scale_y":           scale_y,
            "display_min":       disp_min,
            "display_max":       disp_max,
            "raw_min":           raw_vmin,
            "raw_max":           raw_vmax,
            "show_colorbar":     False,
            "log_scale":         False,
            "scale_mode":        "linear",
            "colormap_name":     cmap_name,
            "colormap_data":     cmap_lut,
            "zoom":              1.0,
            "center_x":          0.5,
            "center_y":          0.5,
            "overlay_widgets":   [],
            "markers":           [],
            "pointer_settled_ms":    0,
            "pointer_settled_delta": 4,
            # Transparent mask overlay (set via set_overlay_mask)
            "overlay_mask_b64":   "",
            "overlay_mask_color": "#ff4444",
            "overlay_mask_alpha": 0.4,
            # Set True when Python explicitly changes view; JS uses it to
            # decide whether to preserve the current frontend zoom/pan state.
            "_view_from_python":  False,
            # Axis / annotation labels (rendered by JS in Phase 4)
            "x_label":           "",
            "y_label":           "",
            "title":             "",
            "colorbar_label":    "",
            # Aspect ratio: None means free, float means width/height ratio
            "aspect":            None,
            # Visibility toggles
            "axis_visible":      True,
            "x_ticks_visible":   True,
            "y_ticks_visible":   True,
        }

        self.markers = MarkerRegistry(self._push_markers,
                                      allowed=MarkerRegistry._KNOWN_2D)
        self.callbacks = CallbackRegistry()
        self._widgets: dict[str, Widget] = {}

    def _configure_pointer_settled(self, ms: int, delta: float) -> None:
        self._state["pointer_settled_ms"]    = ms
        self._state["pointer_settled_delta"] = delta
        self._push()

    @staticmethod
    def _encode_bytes(arr: np.ndarray) -> str:
        import base64
        return base64.b64encode(arr.tobytes()).decode("ascii")

    def _push(self) -> None:
        """Serialise _state + markers and write to Figure trait."""
        if self._fig is None:
            return
        self._state["overlay_widgets"] = [w.to_dict() for w in self._widgets.values()]
        self._fig._push(self._id)

    def _push_markers(self) -> None:
        """Called by MarkerRegistry whenever markers change."""
        self._state["markers"] = self.markers.to_wire_list()
        self._push()

    def to_state_dict(self) -> dict:
        """Return a JSON-serialisable copy of the current state."""
        d = dict(self._state)
        d["overlay_widgets"] = [w.to_dict() for w in self._widgets.values()]
        d["markers"] = self.markers.to_wire_list()
        return d

    # ------------------------------------------------------------------
    # Data
    # ------------------------------------------------------------------
    @property
    def data(self) -> np.ndarray:
        """The image data in the original user coordinate system (read-only).

        Returns a float64 copy with ``writeable=False``.  To replace the
        data call :meth:`set_data`.
        """
        arr = np.flipud(self._data).copy() if self._origin == "lower" else self._data.copy()
        arr.flags.writeable = False
        return arr

    def set_data(self, data: np.ndarray,
               x_axis=None, y_axis=None, units: str | None = None) -> None:
        """Replace the image data.

        The ``origin`` supplied at construction is automatically re-applied
        so the new data is displayed with the same orientation.
        """
        data = np.asarray(data)
        if data.ndim == 3:
            data = data[:, :, 0]
        if data.ndim != 2:
            raise ValueError(f"data must be 2-D, got {data.shape}")
        h, w = data.shape

        if self._origin == "lower":
            data = np.flipud(data)

        self._data = data.astype(float)
        img_u8, vmin, vmax = _normalize_image(data)
        self._raw_u8, self._raw_vmin, self._raw_vmax = img_u8, vmin, vmax

        if x_axis is not None:
            self._state["x_axis"] = np.asarray(x_axis, float).tolist()
            self._state["image_width"] = w
            self._state["has_axes"] = True
        if y_axis is not None:
            ya = np.asarray(y_axis, float)
            if self._origin == "lower":
                ya = ya[::-1]
            self._state["y_axis"] = ya.tolist()
            self._state["image_height"] = h
            self._state["has_axes"] = True
        if units is not None:
            self._state["units"] = units

        self._state.update({
            "image_b64":    self._encode_bytes(img_u8),
            "image_width":  w,
            "image_height": h,
            "display_min":  vmin,
            "display_max":  vmax,
            "raw_min":      vmin,
            "raw_max":      vmax,
            "colormap_data": _build_colormap_lut(self._state["colormap_name"]),
        })
        self._push()

    def set_overlay_mask(self, mask: "np.ndarray | None",
                         color: str = "#ff4444",
                         alpha: float = 0.4) -> None:
        """Set (or clear) a transparent boolean mask drawn over the image.

        The mask is composited client-side in the browser at *alpha* opacity
        using *color* for all ``True`` pixels.  Call with ``mask=None`` to
        remove any existing overlay.

        Parameters
        ----------
        mask : ndarray of shape (H, W), bool or uint8, or None
            Boolean array aligned to the image data.  ``True`` / non-zero
            pixels are filled with *color* at transparency *alpha*.
            Pass ``None`` to clear the overlay.
        color : str, optional
            CSS hex colour for the overlay, e.g. ``"#ff4444"``.  Default red.
            Must be in ``#RRGGBB`` format.
        alpha : float, optional
            Opacity in [0, 1].  Default 0.4 (40 % opaque).
        """
        import base64, re
        # Validate color format
        if not re.fullmatch(r'#[0-9a-fA-F]{6}', color):
            raise ValueError(
                f"color must be a CSS hex colour in '#RRGGBB' format, got {color!r}"
            )
        # Clamp alpha to [0, 1]
        alpha = float(alpha)
        if not (0.0 <= alpha <= 1.0):
            raise ValueError(f"alpha must be in [0, 1], got {alpha!r}")
        if mask is None:
            self._state["overlay_mask_b64"]   = ""
            self._state["overlay_mask_color"] = color
            self._state["overlay_mask_alpha"] = alpha
        else:
            arr = np.asarray(mask)
            if arr.shape != (self._state["image_height"], self._state["image_width"]):
                raise ValueError(
                    f"mask shape {arr.shape} does not match image "
                    f"({self._state['image_height']} x {self._state['image_width']})"
                )
            # For origin='lower' the image data was flipped; flip mask to match.
            if self._origin == "lower":
                arr = np.flipud(arr)
            # Convert to uint8: True/non-zero → 255, False/zero → 0
            u8 = (np.asarray(arr, dtype=bool).view(np.uint8) * 255).astype(np.uint8)
            self._state["overlay_mask_b64"]   = base64.b64encode(u8.tobytes()).decode("ascii")
            self._state["overlay_mask_color"] = color
            self._state["overlay_mask_alpha"] = alpha
        self._push()

    # ------------------------------------------------------------------
    # Display settings
    # ------------------------------------------------------------------
    def set_colormap(self, name: str) -> None:
        self._state["colormap_name"] = name
        self._state["colormap_data"] = _build_colormap_lut(name)
        self._push()

    def set_clim(self, vmin=None, vmax=None) -> None:
        if vmin is not None:
            self._state["display_min"] = float(vmin)
        if vmax is not None:
            self._state["display_max"] = float(vmax)
        self._push()

    def set_scale_mode(self, mode: str) -> None:
        valid = ("linear", "log", "symlog")
        if mode not in valid:
            raise ValueError(f"mode must be one of {valid}")
        self._state["scale_mode"] = mode
        self._push()

    @property
    def colormap_name(self) -> str:
        return self._state["colormap_name"]

    @colormap_name.setter
    def colormap_name(self, name: str) -> None:
        self.set_colormap(name)

    def set_xlabel(self, label: str) -> None:
        self._state["x_label"] = str(label)
        self._push()

    def set_ylabel(self, label: str) -> None:
        self._state["y_label"] = str(label)
        self._push()

    def set_title(self, label: str) -> None:
        self._state["title"] = str(label)
        self._push()

    def set_xlim(self, xmin: float, xmax: float) -> None:
        self.set_view(x0=xmin, x1=xmax)

    def set_ylim(self, ymin: float, ymax: float) -> None:
        self.set_view(y0=ymin, y1=ymax)

    def get_ylim(self) -> tuple:
        yarr = np.asarray(self._state["y_axis"])
        return (float(yarr.min()), float(yarr.max()))

    def get_xbound(self) -> tuple:
        xarr = np.asarray(self._state["x_axis"])
        return (float(xarr.min()), float(xarr.max()))

    def set_extent(self, x_axis, y_axis) -> None:
        x_axis = np.asarray(x_axis, dtype=float)
        y_axis = np.asarray(y_axis, dtype=float)
        w = self._state["image_width"]
        h = self._state["image_height"]
        scale_x = float(abs(x_axis[-1] - x_axis[0]) / max(w - 1, 1)) if len(x_axis) >= 2 else 1.0
        scale_y = float(abs(y_axis[-1] - y_axis[0]) / max(h - 1, 1)) if len(y_axis) >= 2 else 1.0
        self._state["x_axis"]  = x_axis.tolist()
        self._state["y_axis"]  = y_axis.tolist()
        self._state["scale_x"] = scale_x
        self._state["scale_y"] = scale_y
        self._push()

    def set_colorbar_label(self, label: str) -> None:
        self._state["colorbar_label"] = str(label)
        self._push()

    def set_colorbar_visible(self, visible: bool) -> None:
        self._state["show_colorbar"] = bool(visible)
        self._push()

    def set_aspect(self, ratio) -> None:
        if ratio == "equal":
            ratio = 1.0
        self._state["aspect"] = float(ratio) if ratio is not None else None
        self._push()

    def set_axis_off(self) -> None:
        self._state["axis_visible"] = False
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

    # ------------------------------------------------------------------
    # Overlay Widgets
    # ------------------------------------------------------------------
    def add_widget(self, kind: str, color: str = "#00e5ff", **kwargs) -> Widget:
        kind = kind.lower()
        valid = ("circle", "rectangle", "annular", "polygon", "label", "crosshair")
        if kind not in valid:
            raise ValueError(f"kind must be one of {valid}")
        iw, ih = self._state["image_width"], self._state["image_height"]

        def _f(k, default): return float(kwargs.get(k, default))
        def _i(k, default): return int(kwargs.get(k, default))

        if kind == "circle":
            widget = CircleWidget(lambda: None,
                                  cx=_f("cx", iw / 2), cy=_f("cy", ih / 2),
                                  r=_f("r", iw * 0.1), color=color)
        elif kind == "rectangle":
            widget = RectangleWidget(lambda: None,
                                     x=_f("x", iw * 0.25), y=_f("y", ih * 0.25),
                                     w=_f("w", iw * 0.5), h=_f("h", ih * 0.5),
                                     color=color)
        elif kind == "annular":
            r_outer = _f("r_outer", iw * 0.2)
            r_inner = _f("r_inner", iw * 0.1)
            widget = AnnularWidget(lambda: None,
                                   cx=_f("cx", iw / 2), cy=_f("cy", ih / 2),
                                   r_outer=r_outer, r_inner=r_inner, color=color)
        elif kind == "polygon":
            raw = kwargs.get("vertices", [[iw * .25, ih * .25], [iw * .75, ih * .25],
                                          [iw * .75, ih * .75], [iw * .25, ih * .75]])
            widget = PolygonWidget(lambda: None, vertices=raw, color=color)
        elif kind == "crosshair":
            widget = CrosshairWidget(lambda: None,
                                     cx=_f("cx", iw / 2), cy=_f("cy", ih / 2),
                                     color=color)
        else:  # label
            widget = LabelWidget(lambda: None,
                                 x=_f("x", iw * 0.1), y=_f("y", ih * 0.1),
                                 text=str(kwargs.get("text", "Label")),
                                 fontsize=_i("fontsize", 14), color=color)

        # Replace the temporary push_fn with a targeted one now that
        # we have both the widget's _id and the plot's _id.
        plot_ref = self
        wid_id   = widget._id
        def _targeted_push():
            if plot_ref._fig is not None:
                fields = {k: v for k, v in widget._data.items()
                          if k not in ("id", "type")}
                plot_ref._fig._push_widget(plot_ref._id, wid_id, fields)
        widget._push_fn = _targeted_push

        self._widgets[widget.id] = widget
        self._push()       # full panel push once so JS knows about the widget
        return widget

    def get_widget(self, wid) -> Widget:
        """Return the Widget object by ID string or Widget instance."""
        if isinstance(wid, Widget):
            wid = wid.id
        try:
            return self._widgets[wid]
        except KeyError:
            raise KeyError(wid)

    def remove_widget(self, wid) -> None:
        """Remove a widget by ID string or Widget instance."""
        if isinstance(wid, Widget):
            wid = wid.id
        if wid not in self._widgets:
            raise KeyError(wid)
        del self._widgets[wid]
        self._push()

    def list_widgets(self) -> list:
        return list(self._widgets.values())

    def clear_widgets(self) -> None:
        self._widgets.clear()
        self._push()

    # ------------------------------------------------------------------
    # View control
    # ------------------------------------------------------------------
    def set_view(self,
                 x0: float | None = None, x1: float | None = None,
                 y0: float | None = None, y1: float | None = None) -> None:
        """Set the viewport to a data-space rectangle.

        Parameters
        ----------
        x0, x1 : float, optional
            Horizontal data-space range to show.  If omitted the full
            x-extent is used for zoom calculation.
        y0, y1 : float, optional
            Vertical data-space range to show.  If omitted the full
            y-extent is used for zoom calculation.

        Translates the requested rectangle into the ``zoom`` / ``center_x``
        / ``center_y`` state values used by the 2-D JS renderer.
        """
        xarr = np.asarray(self._state["x_axis"])
        yarr = np.asarray(self._state["y_axis"])
        if len(xarr) < 2 or len(yarr) < 2:
            return

        xmin, xmax = float(xarr[0]), float(xarr[-1])
        ymin, ymax = float(yarr[0]), float(yarr[-1])
        x_span = xmax - xmin or 1.0
        y_span = ymax - ymin or 1.0

        zoom_candidates = []

        if x0 is not None and x1 is not None:
            fx0 = max(0.0, min(1.0, (float(x0) - xmin) / x_span))
            fx1 = max(0.0, min(1.0, (float(x1) - xmin) / x_span))
            if fx1 > fx0:
                self._state["center_x"] = (fx0 + fx1) / 2.0
                zoom_candidates.append(1.0 / (fx1 - fx0))

        if y0 is not None and y1 is not None:
            fy0 = max(0.0, min(1.0, (float(y0) - ymin) / y_span))
            fy1 = max(0.0, min(1.0, (float(y1) - ymin) / y_span))
            if fy1 > fy0:
                self._state["center_y"] = (fy0 + fy1) / 2.0
                zoom_candidates.append(1.0 / (fy1 - fy0))

        if zoom_candidates:
            self._state["zoom"] = min(zoom_candidates)
        self._state["_view_from_python"] = True
        self._push()
        self._state["_view_from_python"] = False

    def reset_view(self) -> None:
        """Reset pan and zoom to show the full image."""
        self._state["zoom"]     = 1.0
        self._state["center_x"] = 0.5
        self._state["center_y"] = 0.5
        self._state["_view_from_python"] = True
        self._push()
        self._state["_view_from_python"] = False

    # ------------------------------------------------------------------
    # Marker API  (matplotlib-style kwargs → MarkerRegistry)
    # ------------------------------------------------------------------
    def _add_marker(self, mtype: str, name: str | None, **kwargs) -> "MarkerGroup":  # noqa: F821
        return self.markers.add(mtype, name, **kwargs)

    def add_circles(self, offsets, name=None, *, radius=5,
                    facecolors=None, edgecolors="#ff0000",
                    linewidths=1.5, alpha=0.3,
                    hover_edgecolors=None, hover_facecolors=None,
                    labels=None, label=None,
                    transform: str = "data") -> "MarkerGroup":  # noqa: F821
        """Add circle markers at (x, y) positions in data coordinates."""
        return self._add_marker("circles", name, offsets=offsets, radius=radius,
                                facecolors=facecolors, edgecolors=edgecolors,
                                linewidths=linewidths, alpha=alpha,
                                hover_edgecolors=hover_edgecolors,
                                hover_facecolors=hover_facecolors,
                                labels=labels, label=label,
                                transform=transform)

    def add_points(self, offsets, name=None, *, sizes=5,
                   color="#ff0000", facecolors=None,
                   linewidths=1.5, alpha=0.3,
                   hover_edgecolors=None, hover_facecolors=None,
                   labels=None, label=None,
                   transform: str = "data") -> "MarkerGroup":  # noqa: F821
        """Add point markers at (x, y) positions in data coordinates."""
        return self._add_marker("circles", name, offsets=offsets, radius=sizes,
                                edgecolors=color, facecolors=facecolors,
                                linewidths=linewidths, alpha=alpha,
                                hover_edgecolors=hover_edgecolors,
                                hover_facecolors=hover_facecolors,
                                labels=labels, label=label,
                                transform=transform)

    def add_hlines(self, y_values, name=None, *,
                   color="#ff0000", linewidths=1.5,
                   hover_edgecolors=None,
                   labels=None, label=None,
                   transform: str = "data") -> "MarkerGroup":  # noqa: F821
        """Add static horizontal lines at the given y positions."""
        return self._add_marker("hlines", name, offsets=y_values,
                                color=color, linewidths=linewidths,
                                hover_edgecolors=hover_edgecolors,
                                labels=labels, label=label,
                                transform=transform)

    def add_vlines(self, x_values, name=None, *,
                   color="#ff0000", linewidths=1.5,
                   hover_edgecolors=None,
                   labels=None, label=None,
                   transform: str = "data") -> "MarkerGroup":  # noqa: F821
        """Add static vertical lines at the given x positions."""
        return self._add_marker("vlines", name, offsets=x_values,
                                color=color, linewidths=linewidths,
                                hover_edgecolors=hover_edgecolors,
                                labels=labels, label=label,
                                transform=transform)

    def add_arrows(self, offsets, U, V, name=None, *,
                   edgecolors="#ff0000", linewidths=1.5,
                   hover_edgecolors=None,
                   labels=None, label=None,
                   transform: str = "data") -> "MarkerGroup":  # noqa: F821
        return self._add_marker("arrows", name, offsets=offsets, U=U, V=V,
                                edgecolors=edgecolors, linewidths=linewidths,
                                hover_edgecolors=hover_edgecolors,
                                labels=labels, label=label,
                                transform=transform)

    def add_ellipses(self, offsets, widths, heights, name=None, *,
                     angles=0, facecolors=None, edgecolors="#ff0000",
                     linewidths=1.5, alpha=0.3,
                     hover_edgecolors=None, hover_facecolors=None,
                     labels=None, label=None,
                     transform: str = "data") -> "MarkerGroup":  # noqa: F821
        return self._add_marker("ellipses", name, offsets=offsets,
                                widths=widths, heights=heights, angles=angles,
                                facecolors=facecolors, edgecolors=edgecolors,
                                linewidths=linewidths, alpha=alpha,
                                hover_edgecolors=hover_edgecolors,
                                hover_facecolors=hover_facecolors,
                                labels=labels, label=label,
                                transform=transform)

    def add_lines(self, segments, name=None, *,
                  edgecolors="#ff0000", linewidths=1.5,
                  hover_edgecolors=None,
                  labels=None, label=None,
                  transform: str = "data") -> "MarkerGroup":  # noqa: F821
        return self._add_marker("lines", name, segments=segments,
                                edgecolors=edgecolors, linewidths=linewidths,
                                hover_edgecolors=hover_edgecolors,
                                labels=labels, label=label,
                                transform=transform)

    def add_rectangles(self, offsets, widths, heights, name=None, *,
                       angles=0, facecolors=None, edgecolors="#ff0000",
                       linewidths=1.5, alpha=0.3,
                       hover_edgecolors=None, hover_facecolors=None,
                       labels=None, label=None,
                       transform: str = "data") -> "MarkerGroup":  # noqa: F821
        return self._add_marker("rectangles", name, offsets=offsets,
                                widths=widths, heights=heights, angles=angles,
                                facecolors=facecolors, edgecolors=edgecolors,
                                linewidths=linewidths, alpha=alpha,
                                hover_edgecolors=hover_edgecolors,
                                hover_facecolors=hover_facecolors,
                                labels=labels, label=label,
                                transform=transform)

    def add_squares(self, offsets, widths, name=None, *,
                    angles=0, facecolors=None, edgecolors="#ff0000",
                    linewidths=1.5, alpha=0.3,
                    hover_edgecolors=None, hover_facecolors=None,
                    labels=None, label=None,
                    transform: str = "data") -> "MarkerGroup":  # noqa: F821
        return self._add_marker("squares", name, offsets=offsets,
                                widths=widths, angles=angles,
                                facecolors=facecolors, edgecolors=edgecolors,
                                linewidths=linewidths, alpha=alpha,
                                hover_edgecolors=hover_edgecolors,
                                hover_facecolors=hover_facecolors,
                                labels=labels, label=label,
                                transform=transform)

    def add_polygons(self, vertices_list, name=None, *,
                     facecolors=None, edgecolors="#ff0000",
                     linewidths=1.5, alpha=0.3,
                     hover_edgecolors=None, hover_facecolors=None,
                     labels=None, label=None,
                     transform: str = "data") -> "MarkerGroup":  # noqa: F821
        return self._add_marker("polygons", name, vertices_list=vertices_list,
                                facecolors=facecolors, edgecolors=edgecolors,
                                linewidths=linewidths, alpha=alpha,
                                hover_edgecolors=hover_edgecolors,
                                hover_facecolors=hover_facecolors,
                                labels=labels, label=label,
                                transform=transform)

    def add_texts(self, offsets, texts, name=None, *,
                  color="#ff0000", fontsize=12,
                  hover_edgecolors=None,
                  labels=None, label=None,
                  transform: str = "data") -> "MarkerGroup":  # noqa: F821
        return self._add_marker("texts", name, offsets=offsets, texts=texts,
                                color=color, fontsize=fontsize,
                                hover_edgecolors=hover_edgecolors,
                                labels=labels, label=label,
                                transform=transform)

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

    def __repr__(self) -> str:
        w = self._state.get("image_width", "?")
        h = self._state.get("image_height", "?")
        cmap = self._state.get("colormap_name", "?")
        return f"Plot2D({w}×{h}, cmap={cmap!r})"

"""
plot2d/_plot2d.py
=================
2-D image panel (imshow).
"""

from __future__ import annotations

import logging
import os
import numpy as np
from typing import Callable

# Tile-mode diagnostics. WARNING level so it reaches stderr / the SpyDE Log panel
# without turning on DEBUG. Grep the app log for "[TILEDBG]".
_TLOG = logging.getLogger("anyplotlib.tile")

# Set APL_TILE_DEBUG=1 to log each tiled zoom/pan decision (region fetched) to the
# backend logger — reads to the terminal so a snap/inverted-pan can be diagnosed
# without the browser console. Off by default (zero cost).
_TILE_DEBUG = os.environ.get("APL_TILE_DEBUG") == "1"

from anyplotlib._base_plot import _BasePlot, _PanelMixin, _MarkerMixin
from anyplotlib.markers import MarkerRegistry
from anyplotlib.callbacks import CallbackRegistry
from anyplotlib.widgets import (
    Widget,
    RectangleWidget, CircleWidget, AnnularWidget,
    CrosshairWidget, PolygonWidget, LabelWidget, ArrowWidget,
)
from anyplotlib._utils import _normalize_image, _build_colormap_lut, _to_rgba_u8


def _binary_transport_active() -> bool:
    """True when the Electron binary pixel transport is enabled.

    Reads ``APL_BINARY_TRANSPORT`` from the ENVIRONMENT fresh each call (not a
    cached module global) so it tracks the live setting — and so a test that
    toggles the env var is honoured without a stale reloaded-module flag leaking
    across tests. Only SpyDE / the Electron host sets it; every other host
    (Jupyter / Pyodide / standalone / ``save_html``) leaves it unset → base64."""
    import os
    return os.environ.get("APL_BINARY_TRANSPORT") == "1"


class Plot2D(_BasePlot, _PanelMixin, _MarkerMixin):
    """2-D image plot panel.

    Not an anywidget.  Holds state in ``_state`` dict; every mutation calls
    ``_push()`` which writes to the parent Figure's panel trait.

    The marker API follows matplotlib conventions:
        plot.add_circles(offsets, name="g1", facecolors="#f00", radius=5)
        plot.markers["circles"]["g1"].set(radius=8)
    """

    #: Heavy state keys routed to the geometry channel (see Figure._push).
    #: ``colormap_data`` is large and only changes on set_colormap. ``detail_b64``
    #: (the zoom detail tile) MUST be here: it's a large pixel blob, and only geom-
    #: channel keys are eligible for the PLOTBIN binary route in _route_change — if it
    #: rode the light view trait instead, its "\x00bin:" token would never be resolved
    #: to bytes and the crisp zoom tile would never render (only the overview shows).
    #:
    #: NB ``_GEOM_KEYS`` is a *property* (not a plain frozenset) because image LAYERS
    #: add DYNAMIC pixel keys ``layer_<id>_b64`` — one per active layer — that must
    #: also ride the geom channel (dedup-cached + PLOTBIN-eligible), exactly like the
    #: base image. The property returns the fixed base set UNION the current layer
    #: pixel keys, so ``Figure._push`` splits every layer's pixels off the light view
    #: trait and the binary route recognises them. The consumers only ever iterate the
    #: returned set, so a set-typed property is a drop-in for the old frozenset.
    _BASE_GEOM_KEYS = frozenset({"image_b64", "colormap_data", "overlay_mask_b64",
                                 "detail_b64"})

    @property
    def _GEOM_KEYS(self) -> frozenset:
        layer_keys = self._layer_pixel_keys()
        if not layer_keys:
            return self._BASE_GEOM_KEYS
        return self._BASE_GEOM_KEYS | layer_keys

    @staticmethod
    def _layer_pixel_key(layer_id: str) -> str:
        """The top-level state / geom key holding one layer's raw pixel bytes."""
        return f"layer_{layer_id}_b64"

    def _layer_pixel_keys(self) -> frozenset:
        """The pixel geom keys for every currently-attached layer."""
        return frozenset(
            self._layer_pixel_key(lyr["id"])
            for lyr in self._state.get("layers", []))

    # Logical image bigger than this (either side) uses the tile backend under
    # tile="auto": it sends a downsampled OVERVIEW as the base + streams a hi-res
    # detail tile of the visible region on zoom/pan, instead of the whole frame.
    TILE_THRESHOLD = 1024
    OVERVIEW_MAX = 1024        # initial overview edge (refined to panel px on first view)
    VIEW_OVERFETCH = 2.0       # sample 2× the visible area (a full extra viewport of
                               # padding) so casual zoom-out/pan stays on the crisp tile
                               # and the overview only shows past that padded FOV
    VIEW_ZOOM_MIN = 1.05       # below this the overview base is enough (no tile)
    RANGE_SAMPLE_MAX = 2048    # subsample edge for the tile display-range probe (native
                               # pixels → true extremes, so a zoom tile doesn't blow out)

    def __init__(self, data,
                 x_axis=None, y_axis=None, units: str = "px",
                 cmap: str | None = None,
                 vmin: float | None = None,
                 vmax: float | None = None,
                 origin: str = "upper",
                 gpu: "str | bool" = "auto",
                 tile: "str | bool" = "auto",
                 integration_method: str = "mean",
                 overview_method: str = "mean",
                 tile_backend=None):
        self._id:  str = ""       # assigned by Axes._attach
        self._fig: object = None  # assigned by Axes._attach

        _valid_origins = ("upper", "lower")
        if origin not in _valid_origins:
            raise ValueError(
                f"origin must be one of {_valid_origins!r}, got {origin!r}"
            )
        self._origin: str = origin

        # ── Tile backend resolution ──────────────────────────────────────────────
        # A backend OWNS the source + sampling; a bare ndarray is wrapped. Decide
        # tile mode from the LOGICAL shape (so we never materialise a huge array just
        # to measure it). When tiled, `data` below becomes a downsampled OVERVIEW and
        # the logical full size is remembered for the coordinate system.
        from anyplotlib.plot2d._tile_backend import as_tile_backend, TileBackend
        self._integration_method = integration_method
        # Sampling method used for the always-visible base OVERVIEW texture.
        # Defaults to "mean" so sparse images are integration-consistent between
        # overview and detail tiles — a "subsample" overview would show very
        # different intensities on a sparse image compared to a "mean" detail
        # tile, producing a visible shift on zoom-in.  Pass
        # overview_method="subsample" to restore the old fast path when a full-
        # frame area-mean is too expensive (e.g. 16 MP+ frames on every scrub).
        self._overview_method: str = overview_method
        self._tile_backend = None
        self._detail_pending = None   # (id) latest requested tile — latest-wins
        src = tile_backend if tile_backend is not None else data
        is_backend = isinstance(src, TileBackend) and not isinstance(src, np.ndarray)
        if is_backend:
            logical_h, logical_w = src.full_shape
        else:
            _arr = np.asarray(src)
            logical_h, logical_w = _arr.shape[:2] if _arr.ndim >= 2 else (0, 0)
        _rgb_src = (not is_backend) and np.asarray(src).ndim == 3
        tile_on = (not _rgb_src) and (
            tile is True or (tile == "auto" and max(logical_h, logical_w) > self.TILE_THRESHOLD))

        # Remember the tile PREFERENCE so a later set_data can auto-enable tiling when
        # a large frame arrives on a plot that started small (the live-navigator case:
        # imshow a tiny placeholder, then set_data the real 4k frames). tile=False
        # stays off forever; "auto"/True honour the threshold per frame.
        self._tile_pref = tile
        self._tile_on = tile_on
        self._logical_w = logical_w
        self._logical_h = logical_h
        if tile_on:
            self._tile_backend = as_tile_backend(
                src, origin=origin) if not is_backend else src
            # Base texture = a downsampled OVERVIEW (row 0 at top, already oriented);
            # the logical full size drives image_width/height + the coordinate system.
            data = self._make_overview(self._tile_backend)
            # The overview is already display-oriented; don't let the origin='lower'
            # flip below double-flip it (the y_axis still reverses for correct ticks).
            self._overview_pre_oriented = True
        else:
            self._overview_pre_oriented = False

        data = np.asarray(data)
        # (H, W, 3|4) arrays render as true-colour RGB(A); anything else 2-D.
        self._is_rgb: bool = data.ndim == 3 and data.shape[2] in (3, 4)
        if data.ndim == 3 and not self._is_rgb:
            raise ValueError(
                f"3-D image data must have 3 (RGB) or 4 (RGBA) channels, "
                f"got shape {data.shape}")
        if data.ndim not in (2, 3):
            raise ValueError(f"data must be 2-D (H x W) or (H x W x 3|4), "
                             f"got {data.shape}")

        h, w = data.shape[:2]
        # In tile mode `data` is the overview; the LOGICAL size drives the axes/extent.
        axis_w = self._logical_w if self._tile_on else w
        axis_h = self._logical_h if self._tile_on else h

        # origin='lower' — row 0 at the bottom, matching matplotlib's matrix
        # convention.  Flip the data so our renderer (which always draws row 0
        # at the top) shows the correct orientation, and reverse the y-axis so
        # tick values increase upward. (A tile overview is already oriented.)
        if origin == "lower" and not self._overview_pre_oriented:
            data = np.flipud(data)

        self._data: np.ndarray = data.astype(float)

        x_axis_given = x_axis is not None
        y_axis_given = y_axis is not None
        if x_axis is None:
            x_axis = np.arange(axis_w, dtype=float)
        if y_axis is None:
            y_axis = np.arange(axis_h, dtype=float)
        x_axis = np.asarray(x_axis, dtype=float)
        y_axis = np.asarray(y_axis, dtype=float)

        if origin == "lower":
            y_axis = y_axis[::-1]

        # Tile mode with no explicit clim: derive the display range from the FULL-RES
        # data (a native-pixel subsample), NOT the averaged overview. The overview's
        # min/max are pulled toward the mean, so quantising a near-native zoom DETAIL
        # tile over that narrow range clips the true extremes → the region goes white
        # on zoom-in. Using the full-res range keeps base + detail on one honest range.
        tile_clim = None
        if (self._tile_on and not self._is_rgb
                and vmin is None and vmax is None):
            tile_clim = self._backend_display_range(self._tile_backend)

        if self._is_rgb:
            # True-colour path: bytes go to JS as RGBA; no LUT applies.
            img_u8 = _to_rgba_u8(data)
            raw_vmin, raw_vmax = 0.0, 255.0
        else:
            # Quantise the overview base over the full-res range (tile_clim) so its
            # codes line up with the detail tile's; falls back to the overview's own
            # min/max when the probe couldn't run.
            img_u8, raw_vmin, raw_vmax = _normalize_image(data, clim=tile_clim)
        self._raw_u8   = img_u8
        self._raw_vmin = raw_vmin
        self._raw_vmax = raw_vmax

        cmap_name = cmap if cmap is not None else "gray"
        cmap_lut  = _build_colormap_lut(cmap_name)

        # vmin/vmax clip the colormap in data units; default to the full range.
        disp_min = float(vmin) if vmin is not None else raw_vmin
        disp_max = float(vmax) if vmax is not None else raw_vmax

        # Compute physical pixel scale (data-units per pixel) from axis arrays over
        # the LOGICAL image size (the axes span the full image, not the overview).
        scale_x = float(abs(x_axis[-1] - x_axis[0]) / max(axis_w - 1, 1)) if len(x_axis) >= 2 else 1.0
        scale_y = float(abs(y_axis[-1] - y_axis[0]) / max(axis_h - 1, 1)) if len(y_axis) >= 2 else 1.0

        # WebGPU image path: "auto" (GPU above ~1 Mpx), True (force attempt),
        # False/"off" (never). Maps to the JS gpu_mode gate.
        _gpu_mode = ("always" if gpu is True
                     else "off" if gpu in (False, "off")
                     else "auto")

        self._state: dict = {
            "kind":              "2d",
            "is_mesh":           False,
            "is_rgb":            self._is_rgb,
            "gpu_mode":          _gpu_mode,
            "gpu_active":        False,
            "has_axes":          x_axis_given or y_axis_given,
            "image_b64":         self._encode_bytes(img_u8),
            # LOGICAL full-image size (zoom math + detail_region are in these px). In
            # tile mode the base texture (image_b64) is a smaller OVERVIEW whose real
            # pixel dims are base_width/height (0 → base == image size).
            "image_width":       axis_w,
            "image_height":      axis_h,
            "base_width":        (w if self._tile_on else 0),
            "base_height":       (h if self._tile_on else 0),
            "tile_enabled":      self._tile_on,
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
            "scale_mode":        "linear",
            "colormap_name":     cmap_name,
            "colormap_data":     cmap_lut,
            "zoom":              1.0,
            "center_x":          0.5,
            "center_y":          0.5,
            # Detail tile: a HIGHER-RES texture for a logical sub-region of the
            # image, sampled by the shader when the current zoom window is inside
            # detail_region — so a zoom-in shows true native pixels for the visible
            # area WITHOUT transferring the whole full-res frame. Set via set_detail;
            # "" / [] clears it (revert to the base texture). See set_detail.
            "detail_b64":        "",
            "detail_region":     [],   # [x0, x1, y0, y1] image-pixel rect of the base
            "detail_width":      0,
            "detail_height":     0,
            "detail_seq":        0,    # bumped per set_detail so the renderer re-uploads
                                       # a re-sampled tile even at the same size/region
            "overlay_widgets":   [],
            "markers":           [],
            # Image LAYERS (see add_layer): each entry is a small metadata dict
            # {id, cmap, clim_min, clim_max, alpha, visible, width, height, image_b64}
            # drawn bottom-up OVER the base image. The heavy pixel bytes for a layer
            # ride the DYNAMIC geom key layer_<id>_b64 (see _GEOM_KEYS); image_b64 in
            # the entry is the base64 / "\x00bin:" TOKEN mirror the JS reads.
            "layers":            [],
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
        # Tile mode: anyplotlib itself reacts to view_changed (zoom/pan) → sample a
        # hi-res detail tile of the visible region from the backend. The consumer
        # does nothing; it can still add its OWN view_changed handler (they coexist).
        if self._tile_on:
            self.callbacks.connect("view_changed", self._on_view_changed_internal)
        self._widgets: dict[str, Widget] = {}
        # Set True once the JS side reports the WebGPU image path activated for
        # this panel (via the gpu_status event → _set_gpu_active). Reflects the
        # actual render path, not just the requested gpu_mode.
        self._gpu_active: bool = False

        # Image layers (see add_layer). ``_layers`` holds the Layer handles in
        # z-order; ``_layer_raw`` caches each layer's display-oriented raw frame
        # (keyed by layer id) so a clim change can re-quantise without the caller
        # re-supplying data — the layer analogue of ``self._data`` + ``set_clim``.
        self._layers: list = []
        self._layer_raw: dict = {}

    @property
    def gpu_active(self) -> bool:
        """True when this image is being rendered by the WebGPU path (reported by
        JS after the device resolves and the panel flips to GPU). ``False`` on the
        Canvas2D path (small image, gpu=False, no GPU, or a GPU failure/fallback)."""
        return self._gpu_active

    def _set_gpu_active(self, active: bool) -> None:
        """Internal: called from the Figure's gpu_status event dispatch."""
        self._gpu_active = bool(active)
        # Keep the state echo in sync for save_html snapshots / introspection.
        self._state["gpu_active"] = self._gpu_active

    # ── Tile mode ──────────────────────────────────────────────────────────────

    def _make_overview(self, backend) -> np.ndarray:
        """Downsampled overview of the WHOLE image for the base texture — fit to
        ~OVERVIEW_MAX px on the long edge (refined to the real panel size on the
        first view_changed). Row 0 at top (display orientation).

        Uses ``self._overview_method`` (default ``"mean"``) so the base overview is
        integration-consistent with detail tiles — important for sparse images where a
        ``"subsample"`` overview shows very different intensities from a ``"mean"``
        detail tile, producing a visible shift on zoom-in.  Pass
        ``overview_method="subsample"`` to ``imshow``/``enable_tile`` when a full-frame
        area-mean is too expensive (e.g. 16 MP+ frames scrubbed on every tick)."""
        h, w = backend.full_shape
        scale = max(1.0, max(h, w) / float(self.OVERVIEW_MAX))
        ov_w = max(1, int(round(w / scale)))
        ov_h = max(1, int(round(h / scale)))
        ov = backend.sample(0, w, 0, h, ov_w, ov_h, self._overview_method)
        if backend.origin == "lower":
            ov = np.flipud(ov)   # normalise to row-0-top for the base texture
        return np.asarray(ov)

    def _backend_display_range(self, backend):
        """A display (vmin, vmax) for tile mode derived from the FULL-RES data, NOT
        the overview. The overview is a box-MEAN downsample, so its min/max are pulled
        toward the mean → a NARROWER range than the native pixels. Quantising the base
        over that narrow range is fine (the base is itself averaged), but when a zoom
        samples a near-native DETAIL tile and quantises it over the same narrow range,
        the true extremes clip to black/white — the region visibly BLOWS OUT (goes
        white) on zoom-in. Deriving the range from a SUBSAMPLE (native pixels, no
        averaging) of the full image keeps the extremes, so base and detail share one
        honest range and the contrast is stable from zoomed-out to zoomed-in.

        Returns (vmin, vmax) or None if it can't be computed (caller falls back to the
        overview range). Subsample is capped to ~RANGE_SAMPLE_MAX px/edge so this stays
        cheap even on an 8k+ frame."""
        try:
            h, w = backend.full_shape
            n = self.RANGE_SAMPLE_MAX
            sw = min(w, n); sh = min(h, n)
            samp = backend.sample(0, w, 0, h, sw, sh, "subsample")
            samp = np.asarray(samp)
            finite = samp[np.isfinite(samp)]
            if finite.size == 0:
                return None
            vmin = float(finite.min()); vmax = float(finite.max())
            if vmax <= vmin:
                return None
            return vmin, vmax
        except Exception:
            return None

    def _visible_region(self, zoom, cx, cy):
        """The visible LOGICAL image-pixel rect for the current zoom/center,
        expanded by VIEW_OVERFETCH (clamped) so a small pan stays inside the tile."""
        iw, ih = self._logical_w, self._logical_h
        vis_w = iw / max(zoom, 1e-9)
        vis_h = ih / max(zoom, 1e-9)
        # over-fetch around the visible window
        ex_w = min(iw, vis_w * self.VIEW_OVERFETCH)
        ex_h = min(ih, vis_h * self.VIEW_OVERFETCH)
        x0 = int(max(0, min(iw - ex_w, cx * iw - ex_w / 2)))
        y0 = int(max(0, min(ih - ex_h, cy * ih - ex_h / 2)))
        x1 = int(min(iw, x0 + int(round(ex_w))))
        y1 = int(min(ih, y0 + int(round(ex_h))))
        return x0, x1, y0, y1

    def enable_tile(self, backend=None, integration_method: str = "mean",
                    overview_method: str | None = None) -> None:
        """Turn tile mode ON (or reconfigure it) AFTER construction — for a consumer
        whose large frame isn't known at ``imshow`` time (e.g. a live navigator whose
        signal frame arrives later and changes). Registers the internal view→tile loop
        (once), sets the logical size from the backend, and paints the overview base.
        Call ``update_tile_source(new_frame)`` on each subsequent data change.

        ``backend``: a TileBackend (or an ndarray, wrapped). ``None`` keeps the
        current backend (just re-enable / change method).

        ``overview_method``: sampling method for the base overview texture
        (``"mean"|"subsample"|"max"``).  ``None`` keeps the current setting
        (default ``"mean"`` from construction).  Use ``"subsample"`` to restore the
        old fast nearest-neighbour path when a full-frame area-mean is too expensive."""
        if self._state.get("layers"):
            raise RuntimeError(
                "enable_tile is not supported on a plot with image layers — tile "
                "mode streams detail tiles of a single image and cannot composite "
                "independent layers. Remove all layers first (remove_layer), or "
                "keep the plot untiled.")
        from anyplotlib.plot2d._tile_backend import as_tile_backend
        if backend is not None:
            self._tile_backend = as_tile_backend(backend, origin=self._origin)
        if self._tile_backend is None:
            _TLOG.warning("[TILEDBG] enable_tile ABORT: no backend")
            return
        self._integration_method = integration_method
        # Only overwrite when caller explicitly passes a value so that internal
        # re-enables (_set_data_tiled, _enable_tile_from_frame) which omit this
        # arg preserve whatever the user set at construction / last enable_tile.
        if overview_method is not None:
            self._overview_method = overview_method
        h, w = self._tile_backend.full_shape
        self._logical_w, self._logical_h = int(w), int(h)
        self._state["image_width"] = int(w)
        self._state["image_height"] = int(h)
        self._state["tile_enabled"] = True
        # Fixed QUANTISATION band for the tile bytes: the overview + detail tiles are
        # quantised to uint8 over raw_min/raw_max (the full-res data range), NOT the
        # display window. That lets a CONTRAST change re-window purely in the LUT
        # (raw_min/raw_max fixed, display_min/display_max move) with NO pixel re-encode
        # or re-transfer — set_clim just moves the display window (see set_clim). Set
        # once from the full-res range; keep any existing band on a re-enable.
        if (self._state.get("raw_min") is None
                or not (self._state.get("raw_max", 0) > self._state.get("raw_min", 0))):
            rng = self._backend_display_range(self._tile_backend)
            if rng is not None:
                self._state["raw_min"], self._state["raw_max"] = rng
        _was_on = self._tile_on
        if not self._tile_on:
            self._tile_on = True
            self.callbacks.connect("view_changed", self._on_view_changed_internal)
        _TLOG.debug(
            "[TILEDBG] enable_tile logical=%s was_on=%s method=%s overview_method=%s "
            "display=(%s,%s) → will build overview",
            (h, w), _was_on, integration_method, self._overview_method,
            self._state.get("display_min"), self._state.get("display_max"))
        # Paint the overview base + refresh any active tile from the (new) backend.
        self.update_tile_source()

    def _disable_tile(self) -> None:
        """Leave tile mode (a consumer sent tile=False). Disconnect the internal
        view→tile handler, drop the backend, and clear the tile state fields so a
        following plain set_data sets image_width to the real frame size with
        base_width=0 and no stale detail tile."""
        if self._tile_on:
            try:
                self.callbacks.disconnect_fn(self._on_view_changed_internal,
                                             "view_changed")
            except Exception:
                pass
        self._tile_on = False
        self._tile_backend = None
        self._state["tile_enabled"] = False
        self._state["base_width"] = 0
        self._state["base_height"] = 0
        self._state.update({"detail_b64": "", "detail_region": [],
                            "detail_width": 0, "detail_height": 0})
        _TLOG.debug("[TILEDBG] _disable_tile: tile mode OFF (forced plain)")

    def update_tile_source(self, array=None) -> None:
        """The backing DATA changed (e.g. a movie navigator advanced a frame) — keep
        the current zoom/subselection but refresh the pixels. Re-samples the overview
        base AND (if a detail tile is currently shown) the SAME detail region from the
        new data, so a live source updates in place without a view change.

        ``array``: swap the numpy backend's source first (convenience for the common
        ndarray case). For a custom backend that already mutated its own source, call
        ``update_tile_source()`` with no argument to just re-sample."""
        if not self._tile_on or self._tile_backend is None:
            _TLOG.debug("[TILEDBG] update_tile_source SKIP: tile_on=%s backend=%s",
                          self._tile_on, self._tile_backend is not None)
            return
        if array is not None:
            setter = getattr(self._tile_backend, "set_array", None)
            if setter is not None:
                setter(array)
        reg = self._state.get("detail_region") or []
        has_detail = len(reg) == 4
        # Refresh the overview base ONLY when no detail tile is shown (zoomed out) —
        # when zoomed in, the overview isn't visible, so re-pushing it every frame is
        # wasted work + a texture swap that can flicker. The skipped overview is
        # marked STALE and refreshed once on the next view settle (see
        # _on_view_changed_internal) so a zoom-out after a zoomed-in scrub never
        # shows the pre-scrub frame.
        if not has_detail:
            self._refresh_overview()
            self._push()
            return
        # Zoomed in: re-sample only the CURRENT detail tile from the new data.
        try:
            x0, x1, y0, y1 = reg
            out_h = self._state.get("detail_height") or (y1 - y0)
            out_w = self._state.get("detail_width") or (x1 - x0)
            tile = self._tile_backend.sample(
                x0, x1, y0, y1, out_w, out_h, self._integration_method)
            if self._tile_backend.origin == "lower":
                tile = np.flipud(tile)
            # The base overview now shows OLD data (only the tile was refreshed).
            # Any zoom-out / partial-cover pan would reveal it — refresh once on
            # the next view settle.
            self._overview_stale = True
            self.set_detail(np.ascontiguousarray(tile), x0, x1, y0, y1)
            _TLOG.debug(
                "[TILEDBG] update_tile_source DETAIL-path (zoomed in): region=%s "
                "resampled tile=%s from new frame (overview marked stale)",
                reg, (out_h, out_w))
        except Exception as e:
            _TLOG.warning("[TILEDBG] detail refresh FAILED: %s", e)
            self._push()

    def _refresh_overview(self) -> None:
        """Re-sample the overview base from the backend into the state (image_b64 +
        base_width/height) and clear the staleness flag. Does NOT push — callers
        bundle it with their own push so the fresh base rides the same frame as the
        detail/clear that exposed it."""
        try:
            ov = self._make_overview(self._tile_backend)
            oh, ow = ov.shape
            img_u8, _vmin, _vmax = self._normalize_for_base(ov)
            self._state["image_b64"] = self._encode_pixels("image_b64", img_u8)
            self._state["base_width"] = int(ow)
            self._state["base_height"] = int(oh)
            self._overview_stale = False
            _TLOG.debug(
                "[TILEDBG] overview refresh: overview=%s u8[min=%d max=%d] "
                "display=(%s,%s) base_wh=(%d,%d) image_wh=(%s,%s)", (oh, ow),
                int(img_u8.min()), int(img_u8.max()),
                self._state.get("display_min"), self._state.get("display_max"),
                ow, oh, self._state.get("image_width"),
                self._state.get("image_height"))
        except Exception as e:
            _TLOG.warning("[TILEDBG] overview refresh FAILED: %s", e)

    def _tile_quant_clim(self):
        """The FIXED quantisation band (raw_min/raw_max) the tile bytes are encoded
        over, so a contrast change re-windows in the LUT without re-encoding pixels.
        Falls back to the display window if no band is set."""
        lo, hi = self._state.get("raw_min"), self._state.get("raw_max")
        if lo is None or hi is None or not (hi > lo):
            lo, hi = self._state.get("display_min"), self._state.get("display_max")
        if lo is None or hi is None or not (hi > lo):
            return None
        return (lo, hi)

    def _normalize_for_base(self, arr):
        """Quantise a base/overview array to uint8 over the fixed raw_min/raw_max band
        (NOT the display window) so contrast re-windows via the LUT alone."""
        return _normalize_image(arr, clim=self._tile_quant_clim())

    def _on_view_changed_internal(self, event) -> None:
        """Zoom/pan settled → sample a hi-res detail tile of the (over-fetched)
        visible region from the backend and upload it. Zoomed out → clear the tile
        (the overview base is enough). The consumer never wires this up."""
        if not self._tile_on or self._tile_backend is None:
            _TLOG.debug("[TILEDBG] view_changed IGNORED: tile_on=%s backend=%s",
                          self._tile_on, self._tile_backend is not None)
            return
        try:
            zoom = float(getattr(event, "zoom", 1.0) or 1.0)
            # A zoomed-in scrub refreshed only the detail tile (update_tile_source),
            # leaving the base overview on the pre-scrub frame. Any view where the
            # base can peek out (zoom-out below; the margin around a partial tile
            # here) must therefore re-sample it ONCE on settle — bundled into the
            # same push as the detail/clear so the fresh base lands atomically.
            stale = getattr(self, "_overview_stale", False)
            if zoom < self.VIEW_ZOOM_MIN:
                _TLOG.debug(
                    "[TILEDBG] view_changed zoom=%.3f < MIN=%.2f → CLEAR detail "
                    "(show overview base only%s)", zoom, self.VIEW_ZOOM_MIN,
                    ", refresh stale overview" if stale else "")
                if stale:
                    self._refresh_overview()
                had_detail = bool(self._state.get("detail_b64"))
                self.set_detail(None)          # pushes iff a tile was set
                if stale and not had_detail:
                    self._push()               # fresh overview still must ship
                return
            if stale:
                self._refresh_overview()       # rides the set_detail push below
            cx = float(getattr(event, "center_x", 0.5) or 0.5)
            cy = float(getattr(event, "center_y", 0.5) or 0.5)
            # Panel device px (JS carries it): the tile is ALWAYS output at the panel
            # resolution (matched to the region's aspect), NOT min(region, panel). Why:
            # the tile fills the same on-screen fit-rect regardless of zoom, so its
            # displayed texel density must be CONSTANT — clamping the output to the
            # (shrinking) region on a deep zoom made every frame a different-res
            # texture stretched over the panel, so the image visibly SNAPPED as the
            # scale jumped. A region SMALLER than the panel is upsampled from real
            # native pixels (crisp, nearest); a bigger one is area-meaned down.
            dw = int(getattr(event, "display_width", 0) or 0) or self.OVERVIEW_MAX
            dh = int(getattr(event, "display_height", 0) or 0) or self.OVERVIEW_MAX
            x0, x1, y0, y1 = self._visible_region(zoom, cx, cy)
            rw, rh = x1 - x0, y1 - y0
            if rw < 2 or rh < 2:
                return
            # Fit the panel box (dw×dh) to the region's aspect so the tile isn't
            # distorted (the fit-rect on screen already has the region's aspect).
            aspect = rw / rh
            if aspect >= dw / dh:
                out_w, out_h = dw, max(1, int(round(dw / aspect)))
            else:
                out_h, out_w = dh, max(1, int(round(dh * aspect)))
            b = self._tile_backend
            # DIAGNOSTIC: the raw native region straight from the backend, BEFORE
            # sampling — its shape + distinct-value count tells us whether the backend
            # actually holds native pixels. If region is 82×82 but the raw crop has
            # only ~100 distinct values, the backend source is a downsample (bug).
            _raw = np.asarray(b._a[y0:y1, x0:x1]) if hasattr(b, "_a") else None
            tile = self._tile_backend.sample(
                x0, x1, y0, y1, out_w, out_h, self._integration_method)
            if b.origin == "lower":
                tile = np.flipud(tile)
            self.set_detail(np.ascontiguousarray(tile), x0, x1, y0, y1)
            _bshape = b.full_shape if hasattr(b, "full_shape") else "?"
            _rawinfo = ("raw_crop=%s distinct=%d" % (
                _raw.shape, int(np.unique(_raw).size))) if _raw is not None else "raw=?"
            _tileinfo = "tile_distinct=%d" % int(np.unique(np.asarray(tile)).size)
            _TLOG.debug(
                "[TILEDBG] view_changed FETCH zoom=%.2f region=[x %d:%d y %d:%d] "
                "(%dx%d logical) BACKEND_shape=%s %s → tile=%dx%d %s "
                "u8[min=%d max=%d]",
                zoom, x0, x1, y0, y1, rw, rh, _bshape, _rawinfo, out_w, out_h,
                _tileinfo, int(np.asarray(tile).min()), int(np.asarray(tile).max()))
        except Exception as e:
            _TLOG.warning("[TILEDBG] view_changed tile update FAILED: %s", e)

    @staticmethod
    def _encode_bytes(arr: np.ndarray) -> str:
        import base64
        return base64.b64encode(arr.tobytes()).decode("ascii")

    def _encode_pixels(self, key: str, arr: np.ndarray) -> str:
        """Return the value to store under a pixel geom key (e.g. ``image_b64``).

        Fast path (Electron BINARY transport active + attached to a Figure):
        stash the RAW uint8 bytes on the Figure's ``_raw_pixels`` side-table and
        return only a tiny change-token string. ``_electron._route_change`` then
        ships those bytes directly as a PLOTBIN frame — skipping the ~20 ms
        base64 encode here, the megabyte ``json.dumps`` in ``Figure._push``, and
        the ~17 ms base64 decode that the old binary path paid in
        ``_route_change`` (it re-decoded the string we had just encoded).

        Fallback (Jupyter / Pyodide / standalone / ``save_html``, or no Figure):
        base64-encode into the geom JSON exactly as before — those hosts have no
        binary channel, so the pixels must ride in the trait string.

        The returned token must CHANGE whenever the pixels change, because
        ``Figure._push`` re-sends the geom channel only when its dict differs
        from the last one sent (``_geom_last``). The token is a cheap CONTENT
        checksum (adler32, ~2 ms on a 4 MP frame) of the raw bytes, so it also
        preserves the "unchanged frame → skip re-send" optimisation exactly like
        the old base64-string comparison did (identical pixels → identical
        token → ``_push`` skips), while costing a fraction of a base64 encode.
        """
        fig = getattr(self, "_fig", None)
        store = getattr(fig, "_raw_pixels", None) if fig is not None else None
        if store is not None and _binary_transport_active():
            import zlib
            raw = arr.tobytes()
            store[(self._id, key)] = raw
            # Content token: same bytes → same token (skip); changed → re-send.
            return f"\x00bin:{zlib.adler32(raw) & 0xFFFFFFFF}"
        # No binary channel — pixels must travel as base64 in the geom JSON.
        return self._encode_bytes(arr)

    def to_state_dict(self) -> dict:
        """Return a JSON-serialisable copy of the current state.

        On the binary-transport path ``_state["image_b64"]`` may hold a tiny
        ``"\\x00bin:<checksum>"`` change-token instead of a base64 string — the
        real pixels ride the PLOTBIN channel (``_electron._route_change`` reads
        them from the Figure's ``_raw_pixels`` side-table). The token is the
        correct WIRE representation and is passed through untouched here so the
        hot ``Figure._push`` path does NOT re-encode base64 every frame.

        A COLD consumer with no binary channel (``save_html`` / standalone /
        Jupyter) must instead materialise real base64; it calls
        :meth:`resolve_pixel_tokens` on the returned dict (``Figure._push`` does
        this for the standalone trait when binary transport is off)."""
        d = dict(self._state)
        d["overlay_widgets"] = [w.to_dict() for w in self._widgets.values()]
        d["markers"] = self.markers.to_wire_list()
        return d

    def resolve_pixel_tokens(self, d: dict) -> dict:
        """Replace any ``"\\x00bin:…"`` pixel change-token in *d* with the real
        base64 (materialised from the Figure's ``_raw_pixels`` side-table), in
        place, and return *d*. Used by the COLD paths (save_html / standalone)
        that have no PLOTBIN channel and need the pixels inline. A no-op for a
        normal base64 string. See :meth:`to_state_dict`.

        Also materialises every LAYER's pixels: each layer has a top-level geom
        key ``layer_<id>_b64`` AND a mirror ``image_b64`` field inside its
        ``layers`` entry — both are resolved so a ``save_html`` snapshot of a
        layered plot is self-contained."""
        import base64
        fig = getattr(self, "_fig", None)
        raw_tbl = getattr(fig, "_raw_pixels", None)

        def _resolve(store_key: str, val):
            if not (isinstance(val, str) and val.startswith("\x00bin:")):
                return val
            raw = raw_tbl.get((self._id, store_key)) if raw_tbl is not None else None
            return base64.b64encode(raw).decode("ascii") if raw else ""

        for key in ("image_b64", "overlay_mask_b64"):
            if d.get(key) is not None:
                d[key] = _resolve(key, d.get(key))
        # Layer pixels: top-level layer_<id>_b64 key + the mirror in the entry.
        # ``d`` is a SHALLOW copy of ``_state`` (to_state_dict), so ``d["layers"]``
        # shares the entry dicts with the live state. Rebuild the list with COPIED
        # entries before rewriting ``image_b64`` so materialising base64 for a cold
        # snapshot never mutates a live "\x00bin:" token back into base64 (which
        # would corrupt the binary-transport dedup on the next push).
        layers = d.get("layers")
        if layers:
            new_layers = []
            for lyr in layers:
                lid = lyr.get("id")
                if lid is None:
                    new_layers.append(lyr)
                    continue
                pk = self._layer_pixel_key(lid)
                resolved = _resolve(pk, d.get(pk, lyr.get("image_b64")))
                if pk in d:
                    d[pk] = resolved
                new_layers.append({**lyr, "image_b64": resolved})
            d["layers"] = new_layers
        return d

    # ------------------------------------------------------------------
    # Data
    # ------------------------------------------------------------------
    @property
    def data(self) -> np.ndarray:
        """The image data in the original user coordinate system (read-only).

        Returns a float64 copy with ``writeable=False``.  To replace the
        data call :meth:`set_data`.

        The float64 cast happens HERE, lazily, not in ``set_data`` — a scrub
        pushes a new frame every tick but rarely reads ``.data`` back, and a
        full float64 copy of a 4k frame is ~12 ms. ``set_data`` keeps the
        frame in its source dtype (``self._data``); we cast + copy only on the
        (rare) read.
        """
        src = np.flipud(self._data) if self._origin == "lower" else self._data
        arr = np.asarray(src, dtype=float).copy()   # cast + independent copy
        arr.flags.writeable = False
        return arr

    def set_data(self, data: np.ndarray,
               x_axis=None, y_axis=None, units: str | None = None,
               clim: tuple | None = None, tile: "str | bool | None" = None) -> None:
        """Replace the image data.

        The ``origin`` supplied at construction is automatically re-applied
        so the new data is displayed with the same orientation.

        ``tile`` — per-call override of the tile decision (default ``None`` uses the
        plot's construction preference). ``False`` forces a PLAIN full-frame push even
        for a large frame (the caller manages its own decimation); ``True`` forces tile
        mode. A live consumer that only wants tiling on some frames (e.g. only when its
        GPU is active, sending the NATIVE frame then, but a pre-decimated frame
        otherwise) passes ``tile=False`` on the decimated frames so they don't get
        auto-tiled at the wrong logical size.

        ``clim`` — optional ``(vmin, vmax)`` display range applied in the SAME
        push as the new data.  Without it the caller must follow with a separate
        ``set_clim``, which pushes a SECOND time: the first push shows the image
        stretched over its full data range (wrong contrast) and the second
        corrects it, producing a one-frame flash on every update.  Passing
        ``clim`` here makes data + contrast a single atomic frame (no flash).

        Raises
        ------
        ValueError
            If ``data`` has an invalid shape/ndim, or if this plot has image
            layers (:meth:`add_layer`) and ``data``'s ``(H, W)`` differs from
            the current image shape.  A layer keeps the size it had when it
            was added/last updated, so a shape-changing base update would
            silently stretch stale-sized layer pixels over the new image.
            Remove all layers (``remove_layer``) before changing the base
            image's shape, then re-add them at the new size.
        """
        data = np.asarray(data)
        is_rgb = data.ndim == 3 and data.shape[2] in (3, 4)
        if data.ndim == 3 and not is_rgb:
            raise ValueError(
                f"3-D image data must have 3 (RGB) or 4 (RGBA) channels, "
                f"got shape {data.shape}")
        if data.ndim not in (2, 3):
            raise ValueError(f"data must be 2-D or (H x W x 3|4), got {data.shape}")
        h, w = data.shape[:2]

        # A shape-changing set_data on a plot with image layers would silently
        # corrupt the display: each layer keeps the (h, w) it had at add_layer /
        # its last Layer.set_data time (see _encode_layer_pixels), but JS fits
        # every layer's bitmap into the BASE image's CURRENT fit-rect
        # (_drawLayers2d → _imgFitRect(iw, ih, ...) uses the new image_width/
        # image_height) — so a stale-sized layer would be stretched over the new
        # base image instead of erroring. Mirrors the tile-mode guard above:
        # refuse instead of corrupting, and tell the caller how to proceed.
        if self._state.get("layers"):
            old_h = self._state.get("image_height")
            old_w = self._state.get("image_width")
            if (old_h, old_w) != (h, w):
                raise ValueError(
                    f"set_data: new frame shape ({h}, {w}) does not match the "
                    f"current image shape ({old_h}, {old_w}) while this plot has "
                    f"image layers — remove all layers (remove_layer) before "
                    f"changing the base image shape, then re-add them at the "
                    f"new size.")

        # ── Tile mode: a live consumer (e.g. a movie navigator) calls set_data with
        # each new frame. Route it through the tile pipeline instead of clobbering the
        # tile state. Writing the plain base frame here would corrupt tiling: it sets
        # image_width to THIS frame's width while base_width still names the OLD
        # overview (so JS misreads the base texture — the "shrinks to overview size"
        # bug), and it clears the active detail tile (so a zoom-in snaps back to the
        # blurry overview until the next view_changed re-fetches — the flash). The
        # tile path swaps the backend source + re-samples the overview/detail in place,
        # keeping image_width, base_width, zoom/center, and the detail region intact.
        # RGB frames don't tile — fall through to the plain path.
        # Per-call `tile` override wins; else the construction preference decides.
        eff_pref = self._tile_pref if tile is None else tile
        # Layers + tiling are mutually exclusive (a layer can't be tiled against
        # the same streamed view). A plot with layers ALWAYS takes the plain path:
        # honour an explicit tile=True by refusing, and never auto-enable.
        _has_layers = bool(self._state.get("layers"))
        if _has_layers and tile is True:
            raise RuntimeError(
                "set_data(tile=True) is not supported on a plot with image layers "
                "— remove all layers (remove_layer) before enabling tile mode.")
        want_tile = (not is_rgb) and (not _has_layers) and (
            eff_pref is True
            or (eff_pref == "auto" and max(h, w) > self.TILE_THRESHOLD))
        # tile=False FORCES the plain path even on an already-tiled plot (the caller is
        # sending a pre-decimated frame it wants shown as-is) → tear tiling down first.
        force_plain = (tile is False)
        _TLOG.debug(
            "[TILEDBG] set_data ROUTE frame=%s dtype=%s clim=%s  is_rgb=%s "
            "tile_arg=%r eff_pref=%r want_tile=%s tile_on=%s backend=%s force_plain=%s "
            "THRESH=%s → %s",
            (h, w), data.dtype, clim, is_rgb, tile, eff_pref, want_tile,
            self._tile_on, self._tile_backend is not None, force_plain,
            self.TILE_THRESHOLD,
            "PLAIN(forced)" if force_plain
            else "TILED-SWAP" if (self._tile_on and self._tile_backend is not None
                                  and not is_rgb)
            else "AUTO-ENABLE" if (want_tile and not self._tile_on)
            else "PLAIN")
        if force_plain and self._tile_on:
            # Leaving tile mode: drop the internal view handler + backend so the plain
            # push below sets image_width to the real frame size with base_width=0.
            self._disable_tile()
        elif self._tile_on and self._tile_backend is not None and not is_rgb:
            self._set_data_tiled(data, clim)
            return
        # A large scalar frame arriving on a plot that started small (tiny placeholder
        # → real 4k frames): auto-ENABLE tiling now, exactly like imshow(huge) would,
        # so the consumer just calls set_data and never hand-rolls a backend. This is
        # the seam the SpyDE movie viewer uses.
        elif want_tile and not self._tile_on:
            self._enable_tile_from_frame(data, clim)
            return

        if self._origin == "lower":
            data = np.flipud(data)

        # Keep the frame in its SOURCE dtype (no float64 copy on the hot path);
        # the `.data` property casts to float lazily on the rare read-back.
        # np.array(copy=True) so a later caller mutation can't alias our frame
        # (the old `.astype(float)` also copied) — cheap vs float64 (same-dtype).
        self._data = np.array(data, copy=True)
        self._is_rgb = is_rgb
        self._state["is_rgb"] = is_rgb
        # Parse the caller's display range up front so quantisation can spend all
        # 256 codes on it (clipping a hot pixel / zero beam) instead of stretching
        # them across the raw min/max — see _normalize_image.
        parsed_clim = None
        if clim is not None and not is_rgb:
            try:
                parsed_clim = (float(clim[0]), float(clim[1]))
                if not (parsed_clim[1] > parsed_clim[0]):
                    parsed_clim = None   # degenerate range → fall back to raw min/max
            except (TypeError, ValueError, IndexError):
                parsed_clim = None
        if is_rgb:
            img_u8, vmin, vmax = _to_rgba_u8(data), 0.0, 255.0
        else:
            img_u8, vmin, vmax = _normalize_image(data, clim=parsed_clim)
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

        # Display range for the SAME push (no flash). When a valid clim was used,
        # the codes were quantised over it, so raw_min/raw_max already ARE the clim
        # and the display window is that same range (identity, t = code/255). Only a
        # degenerate/absent clim leaves the display range at the raw min/max.
        disp_min, disp_max = vmin, vmax
        fields = {
            "image_b64":    self._encode_pixels("image_b64", img_u8),
            "image_width":  w,
            "image_height": h,
            "display_min":  disp_min,
            "display_max":  disp_max,
            "raw_min":      vmin,
            "raw_max":      vmax,
        }
        # A new base frame invalidates any detail tile of the OLD frame — clear it
        # so the shader doesn't sample a stale hi-res crop over the new image.
        if self._state.get("detail_b64"):
            fields.update({"detail_b64": "", "detail_region": [],
                           "detail_width": 0, "detail_height": 0})
        # RGB images never use the colormap LUT — skip the (costly) rebuild and
        # leave the existing entry untouched.  Only recompute for scalar data.
        if not is_rgb:
            fields["colormap_data"] = _build_colormap_lut(self._state["colormap_name"])
        self._state.update(fields)
        self._push()

    def _set_data_tiled(self, data: np.ndarray, clim: tuple | None) -> None:
        """set_data for a plot already in tile mode: swap the tile source + refresh
        the overview/detail from it (via update_tile_source) instead of pushing a
        plain base frame. Applies ``clim`` first so the re-sampled overview/detail
        quantise over the new display range in the SAME push. Keeps the logical
        image_width/height, base_width/height, the active detail region, and the
        frontend zoom/center — a live frame update, not a view reset.

        The new frame may differ in shape from the current tile source (e.g. a signal
        whose signal axes changed); update_tile_source → enable_tile re-derives the
        logical size + overview, so image_width/height stay correct for the new frame.
        """
        # Apply the display range up front (if given + valid) so the overview and any
        # detail tile re-sampled below quantise over it — otherwise the tile path uses
        # the stale display_min/display_max and the contrast lags a frame.
        if clim is not None:
            try:
                vmin, vmax = float(clim[0]), float(clim[1])
                if vmax > vmin:
                    self._state["display_min"] = vmin
                    self._state["display_max"] = vmax
            except (TypeError, ValueError, IndexError):
                pass
        # If the frame's shape changed, re-enable tiling so image_width/height and the
        # overview are re-derived for the new logical size; otherwise just swap + re-
        # sample in place (the common live-navigator case: same-size frames).
        from anyplotlib.plot2d._tile_backend import as_tile_backend
        h, w = data.shape[:2]
        same_shape = (int(w) == int(self._logical_w)
                      and int(h) == int(self._logical_h))
        # ascontiguousarray is a no-op (returns the SAME array) when already C-
        # contiguous — the common movie-frame case — so this is free. It replaces the
        # old np.array(copy=True) which unconditionally copied all 16 MP every frame
        # (~4.5 ms) just to stash self._data for a rare .data read-back. The backend
        # holds the frame now; expose it lazily for read-back below.
        arr = np.ascontiguousarray(data)
        self._data = arr           # reference, not a copy — read-back reads the frame
        setter = getattr(self._tile_backend, "set_array", None)
        _TLOG.debug(
            "[TILEDBG] _set_data_tiled frame=%s logical=(%s,%s) same_shape=%s "
            "has_set_array=%s display=(%s,%s) → %s", (h, w),
            self._logical_h, self._logical_w, same_shape, setter is not None,
            self._state.get("display_min"), self._state.get("display_max"),
            "swap+update_tile_source" if (same_shape and setter is not None)
            else "rebuild+enable_tile")
        if same_shape and setter is not None:
            setter(arr)
            self.update_tile_source()
        else:
            # Shape changed (or a custom backend without set_array): rebuild the
            # backend around the new frame and re-enable, preserving zoom/center.
            self._tile_backend = as_tile_backend(arr, origin=self._origin)
            self.enable_tile(self._tile_backend, self._integration_method)

    def _enable_tile_from_frame(self, data: np.ndarray, clim: tuple | None) -> None:
        """First large frame on a not-yet-tiled plot → turn tile mode ON around it,
        exactly like ``imshow(huge)``: wrap the frame in a NumpyTileBackend, set the
        display range (the caller's ``clim`` if given, else the FULL-RES range so a
        zoom detail tile doesn't blow out — see _backend_display_range), then
        enable_tile (which pushes the overview base). This is the seam a live consumer
        uses: imshow a small placeholder, then set_data the real frames; no need to
        hand-roll a backend or call enable_tile directly."""
        from anyplotlib.plot2d._tile_backend import as_tile_backend
        self._data = np.array(data, copy=True)
        arr = np.ascontiguousarray(data)
        self._tile_backend = as_tile_backend(arr, origin=self._origin)
        # Display range: caller's clim wins; else derive from the full-res frame.
        rng = None
        if clim is not None:
            try:
                lo, hi = float(clim[0]), float(clim[1])
                if hi > lo:
                    rng = (lo, hi)
            except (TypeError, ValueError, IndexError):
                rng = None
        _clim_src = "caller-clim" if rng is not None else None
        if rng is None:
            rng = self._backend_display_range(self._tile_backend)
            _clim_src = "full-res-probe"
        if rng is not None:
            self._state["display_min"], self._state["display_max"] = rng
        else:
            _clim_src = "NONE(kept-stale)"
        _TLOG.debug(
            "[TILEDBG] _enable_tile_from_frame frame=%s dtype=%s data[min=%.4g "
            "max=%.4g] → display=(%s,%s) via %s", data.shape, data.dtype,
            float(np.nanmin(data)) if data.size else 0.0,
            float(np.nanmax(data)) if data.size else 0.0,
            self._state.get("display_min"), self._state.get("display_max"),
            _clim_src)
        self.enable_tile(self._tile_backend, self._integration_method)

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
    # Image layers (multi-image overlay)
    # ------------------------------------------------------------------
    @property
    def layers(self) -> list:
        """The list of :class:`~anyplotlib.plot2d._layer.Layer` handles, in
        z-order (index 0 drawn first, above the base image)."""
        return list(self._layers)

    def _norm_clim(self, clim):
        """Parse a ``(vmin, vmax)`` clim → ``(lo, hi)`` floats, or ``(None, None)``
        for auto. A degenerate (non-increasing) range falls back to auto."""
        if clim is None:
            return (None, None)
        try:
            lo, hi = float(clim[0]), float(clim[1])
        except (TypeError, ValueError, IndexError):
            return (None, None)
        if not (hi > lo):
            return (None, None)
        return (lo, hi)

    def _encode_layer_pixels(self, layer_id: str, frame: np.ndarray, clim):
        """Quantise a 2-D layer frame → uint8, store the bytes under the layer's
        geom key (base64 or PLOTBIN token via _encode_pixels), and return
        ``(token, height, width, vmin, vmax)``.

        Requires ``frame.shape == (image_height, image_width)`` — raises
        ``ValueError`` otherwise (a layer must line up pixel-for-pixel with the
        base image, since it shares the base's image→screen transform)."""
        arr = np.asarray(frame)
        ih = self._state["image_height"]
        iw = self._state["image_width"]
        if arr.ndim != 2:
            raise ValueError(
                f"layer data must be 2-D (H x W), got shape {arr.shape}")
        if arr.shape != (ih, iw):
            raise ValueError(
                f"layer data shape {arr.shape} does not match the base image "
                f"({ih} x {iw}); a layer must be the same size as the base image")
        # origin='lower' flips the base data for display; flip layers to match so
        # they line up with the base pixels.
        if self._origin == "lower":
            arr = np.flipud(arr)
        lo, hi = self._norm_clim(clim)
        parsed = (lo, hi) if lo is not None else None
        img_u8, vmin, vmax = _normalize_image(arr, clim=parsed)
        pk = self._layer_pixel_key(layer_id)
        token = self._encode_pixels(pk, np.ascontiguousarray(img_u8))
        # Cache the (display-oriented) raw frame so a later clim change can
        # re-quantise without the caller re-supplying data (mirrors self._data
        # for the base image + set_clim).
        self._layer_raw[layer_id] = arr
        return token, int(arr.shape[0]), int(arr.shape[1]), vmin, vmax

    def add_layer(self, data, *, cmap: str = "magma", alpha: float = 0.5,
                  clim=None, visible: bool = True):
        """Add an image LAYER drawn over the base image.

        Each layer has its OWN colormap, display range (``clim``), and opacity
        (``alpha``), and is composited on top of the base image (and previously
        added layers) with the SAME zoom/pan transform, so it tracks the base
        exactly.  This is the multi-image overlay primitive; for a single-colour
        boolean mask use :meth:`set_overlay_mask` instead.

        Parameters
        ----------
        data : ndarray, shape (H, W)
            2-D scalar array, the same size as the base image.  Normalised to
            uint8 via ``clim`` → LUT exactly like the base image.  A shape
            mismatch raises ``ValueError``.
        cmap : str, optional
            Colormap name (default ``"magma"``).
        alpha : float, optional
            Opacity in [0, 1] (default ``0.5``).
        clim : (vmin, vmax) or None, optional
            Display range; ``None`` (default) auto-scales to the data min/max.
        visible : bool, optional
            Whether the layer is drawn (default ``True``).

        Returns
        -------
        Layer
            A handle with ``.set(...)`` / ``.set_data(frame)`` / ``.remove()``.

        Raises
        ------
        RuntimeError
            If the plot is in TILE mode — layers are incompatible with tiling
            (a layer would have to be tiled independently against the same view).
            Load the plot with ``tile=False`` to use layers.
        ValueError
            If ``data`` is not 2-D or does not match the base image size.
        """
        if self._tile_on:
            raise RuntimeError(
                "add_layer is not supported in tile mode — a tiled plot streams "
                "detail tiles of a single image and cannot composite independent "
                "layers. Create the plot with tile=False to use layers.")
        from anyplotlib.plot2d._layer import Layer, _next_layer_id
        alpha = float(alpha)
        if not (0.0 <= alpha <= 1.0):
            raise ValueError(f"alpha must be in [0, 1], got {alpha!r}")
        layer_id = _next_layer_id()
        token, h, w, vmin, vmax = self._encode_layer_pixels(layer_id, data, clim)
        entry = {
            "id":       layer_id,
            "cmap":     cmap,
            "clim_min": vmin,
            "clim_max": vmax,
            "alpha":    alpha,
            "visible":  bool(visible),
            "width":    w,
            "height":   h,
            # The layer's colormap LUT (256 [r,g,b]); the JS composites via this.
            "colormap_data": _build_colormap_lut(cmap),
            # Mirror of the pixel token so the JS reads bytes for this layer even
            # when it only sees the light `layers` list (the heavy bytes ride the
            # geom key layer_<id>_b64, spliced into the panel state by the binary /
            # geom machinery under the same key).
            "image_b64": token,
        }
        # Also stash the pixels as a TOP-LEVEL geom key so Figure._push splits it
        # onto the geom channel (dedup-cached) and the binary route ships it.
        self._state[self._layer_pixel_key(layer_id)] = token
        self._state.setdefault("layers", []).append(entry)
        layer = Layer(self, layer_id)
        self._layers.append(layer)
        self._push()
        return layer

    def _layer_entry(self, layer_id: str) -> dict:
        for lyr in self._state.get("layers", []):
            if lyr.get("id") == layer_id:
                return lyr
        raise ValueError(f"no layer {layer_id!r} on this plot")

    def _layer_set(self, layer_id: str, *, cmap=None, alpha=None, clim=None,
                   visible=None) -> None:
        entry = self._layer_entry(layer_id)
        if cmap is not None:
            entry["cmap"] = cmap
            entry["colormap_data"] = _build_colormap_lut(cmap)
        if alpha is not None:
            a = float(alpha)
            if not (0.0 <= a <= 1.0):
                raise ValueError(f"alpha must be in [0, 1], got {alpha!r}")
            entry["alpha"] = a
        if visible is not None:
            entry["visible"] = bool(visible)
        # clim=None means "leave unchanged" (no-op) — the historical behaviour,
        # kept as-is. clim="auto" is the sentinel to explicitly RESET to auto
        # (recompute from the layer's current data min/max, like add_layer's
        # clim=None-at-creation path) — see Layer.set / _layer.py docstring.
        if clim is not None:
            # A clim change must RE-QUANTISE the cached frame (like set_clim on the
            # base), because the 8-bit codes are quantised over the old range and
            # can't be re-windowed past it in the LUT alone. We keep the raw frame
            # in _layer_raw for exactly this.
            raw = self._layer_raw.get(layer_id)
            if isinstance(clim, str):
                if clim != "auto":
                    raise ValueError(
                        f"clim must be a (vmin, vmax) tuple or the string "
                        f"'auto', got {clim!r}")
                parsed = None   # None → _normalize_image auto-ranges to data min/max
            else:
                lo, hi = self._norm_clim(clim)
                parsed = (lo, hi) if lo is not None else None
            if raw is not None:
                img_u8, vmin, vmax = _normalize_image(raw, clim=parsed)
                pk = self._layer_pixel_key(layer_id)
                token = self._encode_pixels(pk, np.ascontiguousarray(img_u8))
                entry["clim_min"], entry["clim_max"] = vmin, vmax
                entry["image_b64"] = token
                self._state[pk] = token
            else:
                # No cached frame (unusual) — just record the requested endpoints
                # (auto with no raw frame to compute from leaves them at None).
                entry["clim_min"], entry["clim_max"] = (
                    (None, None) if parsed is None else parsed)
        self._push()

    def _layer_set_data(self, layer_id: str, frame) -> None:
        entry = self._layer_entry(layer_id)
        # Re-quantise over the layer's CURRENT clim so a live frame keeps its
        # contrast window (None endpoints → auto per-frame, matching the base).
        cur_clim = (entry.get("clim_min"), entry.get("clim_max"))
        clim = cur_clim if cur_clim[0] is not None else None
        token, h, w, vmin, vmax = self._encode_layer_pixels(layer_id, frame, clim)
        entry["width"], entry["height"] = w, h
        entry["clim_min"], entry["clim_max"] = vmin, vmax
        entry["image_b64"] = token
        self._state[self._layer_pixel_key(layer_id)] = token
        self._push()

    def remove_layer(self, layer) -> None:
        """Remove *layer* (a :class:`Layer` handle or its id string)."""
        from anyplotlib.plot2d._layer import Layer
        layer_id = layer.id if isinstance(layer, Layer) else str(layer)
        self._state["layers"] = [
            l for l in self._state.get("layers", []) if l.get("id") != layer_id]
        pk = self._layer_pixel_key(layer_id)
        self._state.pop(pk, None)
        self._layer_raw.pop(layer_id, None)
        # Drop the raw-pixel side-table entry so a removed layer's bytes aren't
        # retained (and can't be re-shipped).
        fig = getattr(self, "_fig", None)
        raw_tbl = getattr(fig, "_raw_pixels", None)
        if raw_tbl is not None:
            raw_tbl.pop((self._id, pk), None)
        for h in list(self._layers):
            if h.id == layer_id:
                h._removed = True
                self._layers.remove(h)
        self._push()

    # ------------------------------------------------------------------
    # Display settings
    # ------------------------------------------------------------------
    def set_colormap(self, name: str) -> None:
        self._state["colormap_name"] = name
        self._state["colormap_data"] = _build_colormap_lut(name)
        self._push()

    def set_clim(self, vmin=None, vmax=None) -> None:
        """Set the display range. Because scalar frames are quantised to uint8 over
        their clim (so a hot pixel / zero beam can't crush the signal — see
        _normalize_image), a new range is honoured by RE-QUANTISING from the cached
        raw frame, not merely re-windowing the existing codes (which are saturated
        outside the previous band and so couldn't widen past it). For an RGB frame
        (no scalar quantisation) or when no raw frame is cached, fall back to a pure
        display-window update."""
        new_min = float(vmin) if vmin is not None else self._state.get("display_min")
        new_max = float(vmax) if vmax is not None else self._state.get("display_max")

        # ── TILE MODE: window via the LUT only — do NOT re-quantise/re-push pixels.
        # A tiled plot's base is the OVERVIEW and its pixels stay resident on the GPU;
        # the shader re-windows contrast purely from the 256-entry LUT (rebuilt in JS
        # from display_min/display_max over the fixed raw_min/raw_max band). Re-
        # quantising self._data here would re-encode the FULL 16 MP native frame AND
        # ship it into the overview slot every drag tick — the "retransfers the whole
        # image" lag. So just move the display window (a tiny push). Contrast resolves
        # within the base's original quantisation band, which spans the frame's range.
        if self._tile_on:
            if vmin is not None:
                self._state["display_min"] = float(vmin)
            if vmax is not None:
                self._state["display_max"] = float(vmax)
            self._push()
            return

        raw = getattr(self, "_data", None)
        if (not self._is_rgb and raw is not None
                and new_min is not None and new_max is not None
                and new_max > new_min):
            img_u8, qmin, qmax = _normalize_image(raw, clim=(new_min, new_max))
            self._raw_u8, self._raw_vmin, self._raw_vmax = img_u8, qmin, qmax
            self._state.update({
                "image_b64":   self._encode_pixels("image_b64", img_u8),
                "display_min": qmin,
                "display_max": qmax,
                "raw_min":     qmin,
                "raw_max":     qmax,
            })
            self._push()
            return
        # Fallback: RGB / no cached frame → just move the display window.
        if vmin is not None:
            self._state["display_min"] = float(vmin)
        if vmax is not None:
            self._state["display_max"] = float(vmax)
        self._push()

    def set_detail(self, tile=None, x0=None, x1=None, y0=None, y1=None) -> None:
        """Upload a HIGH-RES detail tile covering the LOGICAL image-pixel rectangle
        ``[x0:x1, y0:y1]`` of the base image (in the SAME orientation as the frame
        passed to ``set_data`` — already ``origin``-applied), so a zoom-in shows true
        native pixels for the visible region WITHOUT transferring the whole full-res
        frame. The shader samples this tile instead of the base whenever the current
        zoom window lies inside ``[x0:x1, y0:y1]``; otherwise it falls back to the
        base texture. ``set_detail(None)`` clears it (revert to base).

        ``tile`` is quantised to uint8 over the SAME display range as the base
        (``display_min``/``display_max``) so its contrast matches seamlessly — a
        zoom crop must look identical to the base, just sharper. Only meaningful for
        scalar (non-RGB) images."""
        if tile is None or self._is_rgb:
            if self._state.get("detail_b64"):
                self._state.update({
                    "detail_b64": "", "detail_region": [],
                    "detail_width": 0, "detail_height": 0,
                })
                self._push()
            return
        tile = np.asarray(tile)
        if tile.ndim != 2:
            raise ValueError(f"detail tile must be 2-D, got {tile.shape}")
        # In tile mode quantise over the FIXED raw_min/raw_max band (so contrast re-
        # windows via the LUT with no re-encode); otherwise (manual set_detail on a
        # non-tiled plot) match the display window as before.
        if self._tile_on:
            clim = self._tile_quant_clim()
        else:
            clim = (self._state.get("display_min"), self._state.get("display_max"))
            if clim[0] is None or clim[1] is None or not (clim[1] > clim[0]):
                clim = None
        img_u8, _vmin, _vmax = _normalize_image(tile, clim=clim)
        th, tw = tile.shape
        # Monotonic sequence so the renderer's dedup key CHANGES on every pushed tile
        # even when length + region are identical (a live movie scrub re-samples the
        # SAME region every frame — without this the JS skips the re-upload and the
        # zoomed-in view freezes on the first frame). See _detailBytes in figure_esm.js.
        self._detail_seq = getattr(self, "_detail_seq", 0) + 1
        self._state.update({
            "detail_b64":    self._encode_pixels("detail_b64", img_u8),
            "detail_region": [int(x0), int(x1), int(y0), int(y1)],
            "detail_width":  int(tw),
            "detail_height": int(th),
            "detail_seq":    self._detail_seq,
        })
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

    def set_xlabel(self, label: str, fontsize: float | None = None) -> None:
        """Set the x-axis label.

        Parameters
        ----------
        label : str
            Label text.  Supports the mini-TeX subset for scientific
            notation, e.g. ``r"$q$ ($\\AA^{-1}$)"`` or ``r"$10^{-3}$ m"``
            — see :class:`~anyplotlib._base_plot._BasePlot` notes.
        fontsize : float, optional
            Font size in CSS pixels.  Default 11.  ``None`` keeps the
            current size.
        """
        self._set_label("x_label", label, "x_label_size", fontsize)

    def set_ylabel(self, label: str, fontsize: float | None = None) -> None:
        """Set the y-axis label.  Same semantics as :meth:`set_xlabel`."""
        self._set_label("y_label", label, "y_label_size", fontsize)

    def set_xlim(self, xmin: float, xmax: float) -> None:
        self.set_view(x0=xmin, x1=xmax)

    def set_ylim(self, ymin: float, ymax: float) -> None:
        self.set_view(y0=ymin, y1=ymax)

    def get_xlim(self) -> tuple:
        xarr = np.asarray(self._state["x_axis"])
        return (float(xarr.min()), float(xarr.max()))

    def get_ylim(self) -> tuple:
        yarr = np.asarray(self._state["y_axis"])
        return (float(yarr.min()), float(yarr.max()))

    def get_xbound(self) -> tuple:
        xarr = np.asarray(self._state["x_axis"])
        return (float(xarr.min()), float(xarr.max()))

    def set_extent(self, x_axis, y_axis, units: str | None = None) -> None:
        """Recalibrate the image axes to the given coordinate arrays.

        Sets ``has_axes`` so the front-end draws physical tick gutters + the
        scale bar — the same gate ``set_data(x_axis=, y_axis=)`` sets. Without
        this a tiled image (which is calibrated ONLY through ``set_extent`` /
        ``enable_tile``, never through ``set_data`` with axis args) would show no
        ticks and no scale bar (the ``has_axes`` gate stayed False). Pass
        ``units`` to update the scale-bar unit label in the same push."""
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
        self._state["has_axes"] = len(x_axis) >= 2 and len(y_axis) >= 2
        if units is not None:
            self._state["units"] = units
        self._push()

    def set_colorbar_label(self, label: str, fontsize: float | None = None) -> None:
        """Set the colorbar label (mini-TeX allowed; default size 10 px)."""
        self._set_label("colorbar_label", label, "colorbar_label_size", fontsize)

    def set_colorbar_visible(self, visible: bool) -> None:
        self._state["show_colorbar"] = bool(visible)
        self._push()

    def set_aspect(self, ratio) -> None:
        if ratio == "equal":
            ratio = 1.0
        self._state["aspect"] = float(ratio) if ratio is not None else None
        self._push()

    # ------------------------------------------------------------------
    # Overlay Widgets
    # ------------------------------------------------------------------
    def add_widget(self, kind: str, color: str = "#00e5ff", **kwargs) -> Widget:
        """Add an overlay widget by kind name.

        Dispatches to the dedicated ``add_<kind>_widget`` method.
        Supported kinds: ``"circle"``, ``"rectangle"``, ``"annular"``,
        ``"polygon"``, ``"crosshair"``, ``"label"``, ``"arrow"``.

        Every kind also accepts ``show_handles`` (default ``True``) to toggle
        the grab-handle dots without changing hit-testing / draggability.
        """
        dispatch = {
            "circle":    self.add_circle_widget,
            "rectangle": self.add_rectangle_widget,
            "annular":   self.add_annular_widget,
            "polygon":   self.add_polygon_widget,
            "crosshair": self.add_crosshair_widget,
            "label":     self.add_label_widget,
            "arrow":     self.add_arrow_widget,
        }
        key = kind.lower()
        if key not in dispatch:
            raise ValueError(f"kind must be one of {tuple(dispatch)}")
        return dispatch[key](color=color, **kwargs)

    def add_circle_widget(self, cx: float | None = None, cy: float | None = None,
                          r: float | None = None, color: str = "#00e5ff",
                          show_handles: bool = True) -> CircleWidget:
        """Add a draggable circle overlay."""
        iw, ih = self._state["image_width"], self._state["image_height"]
        widget = CircleWidget(lambda: None,
                              cx=float(cx) if cx is not None else iw / 2,
                              cy=float(cy) if cy is not None else ih / 2,
                              r=float(r) if r is not None else iw * 0.1,
                              color=color, show_handles=show_handles)
        widget._push_fn = self._make_widget_push_fn(widget)
        self._widgets[widget.id] = widget
        self._push()
        return widget

    def add_rectangle_widget(self, x: float | None = None, y: float | None = None,
                              w: float | None = None, h: float | None = None,
                              color: str = "#00e5ff",
                              show_handles: bool = True) -> RectangleWidget:
        """Add a draggable rectangle overlay."""
        iw, ih = self._state["image_width"], self._state["image_height"]
        widget = RectangleWidget(lambda: None,
                                 x=float(x) if x is not None else iw * 0.25,
                                 y=float(y) if y is not None else ih * 0.25,
                                 w=float(w) if w is not None else iw * 0.5,
                                 h=float(h) if h is not None else ih * 0.5,
                                 color=color, show_handles=show_handles)
        widget._push_fn = self._make_widget_push_fn(widget)
        self._widgets[widget.id] = widget
        self._push()
        return widget

    def add_annular_widget(self, cx: float | None = None, cy: float | None = None,
                           r_outer: float | None = None, r_inner: float | None = None,
                           color: str = "#00e5ff",
                           show_handles: bool = True) -> AnnularWidget:
        """Add a draggable annular (ring) overlay."""
        iw, ih = self._state["image_width"], self._state["image_height"]
        widget = AnnularWidget(lambda: None,
                               cx=float(cx) if cx is not None else iw / 2,
                               cy=float(cy) if cy is not None else ih / 2,
                               r_outer=float(r_outer) if r_outer is not None else iw * 0.2,
                               r_inner=float(r_inner) if r_inner is not None else iw * 0.1,
                               color=color, show_handles=show_handles)
        widget._push_fn = self._make_widget_push_fn(widget)
        self._widgets[widget.id] = widget
        self._push()
        return widget

    def add_polygon_widget(self, vertices=None, color: str = "#00e5ff",
                           show_handles: bool = True) -> PolygonWidget:
        """Add a draggable polygon overlay."""
        iw, ih = self._state["image_width"], self._state["image_height"]
        if vertices is None:
            vertices = [[iw * .25, ih * .25], [iw * .75, ih * .25],
                        [iw * .75, ih * .75], [iw * .25, ih * .75]]
        widget = PolygonWidget(lambda: None, vertices=vertices, color=color,
                               show_handles=show_handles)
        widget._push_fn = self._make_widget_push_fn(widget)
        self._widgets[widget.id] = widget
        self._push()
        return widget

    def add_crosshair_widget(self, cx: float | None = None, cy: float | None = None,
                              color: str = "#00e5ff",
                              show_handles: bool = True) -> CrosshairWidget:
        """Add a draggable crosshair overlay."""
        iw, ih = self._state["image_width"], self._state["image_height"]
        widget = CrosshairWidget(lambda: None,
                                 cx=float(cx) if cx is not None else iw / 2,
                                 cy=float(cy) if cy is not None else ih / 2,
                                 color=color, show_handles=show_handles)
        widget._push_fn = self._make_widget_push_fn(widget)
        self._widgets[widget.id] = widget
        self._push()
        return widget

    def add_label_widget(self, x: float | None = None, y: float | None = None,
                          text: str = "Label", fontsize: int = 14,
                          color: str = "#00e5ff",
                          show_handles: bool = True) -> LabelWidget:
        """Add a draggable text label overlay."""
        iw, ih = self._state["image_width"], self._state["image_height"]
        widget = LabelWidget(lambda: None,
                             x=float(x) if x is not None else iw * 0.1,
                             y=float(y) if y is not None else ih * 0.1,
                             text=str(text), fontsize=int(fontsize), color=color,
                             show_handles=show_handles)
        widget._push_fn = self._make_widget_push_fn(widget)
        self._widgets[widget.id] = widget
        self._push()
        return widget

    def add_arrow_widget(self, x: float | None = None, y: float | None = None,
                         u: float | None = None, v: float | None = None,
                         color: str = "#00e5ff", linewidth: float = 2,
                         show_handles: bool = True) -> ArrowWidget:
        """Add a draggable arrow overlay (tail at ``(x, y)``, head at
        ``(x + u, y + v)``). Defaults place the tail at 25 %, 25 % of the image
        with a vector of 15 % of the image size, mirroring
        :meth:`add_label_widget`'s defaulting."""
        iw, ih = self._state["image_width"], self._state["image_height"]
        widget = ArrowWidget(lambda: None,
                             x=float(x) if x is not None else iw * 0.25,
                             y=float(y) if y is not None else ih * 0.25,
                             u=float(u) if u is not None else iw * 0.15,
                             v=float(v) if v is not None else ih * 0.15,
                             color=color, linewidth=linewidth,
                             show_handles=show_handles)
        widget._push_fn = self._make_widget_push_fn(widget)
        self._widgets[widget.id] = widget
        self._push()
        return widget

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

        with self._python_view_push():
            if zoom_candidates:
                self._state["zoom"] = min(zoom_candidates)

    def reset_view(self) -> None:
        """Reset pan and zoom to show the full image."""
        with self._python_view_push():
            self._state["zoom"]     = 1.0
            self._state["center_x"] = 0.5
            self._state["center_y"] = 0.5

    # ------------------------------------------------------------------
    # Marker API  (matplotlib-style kwargs → MarkerRegistry)
    # ------------------------------------------------------------------
    def add_circles(self, offsets, name=None, *, radius=5,
                    facecolors=None, edgecolors="#ff0000",
                    linewidths=1.5, alpha=0.3,
                    hover_edgecolors=None, hover_facecolors=None,
                    labels=None, label=None,
                    transform: str = "data",
                    clip_display: bool = True) -> "MarkerGroup":  # noqa: F821
        """Add circle markers at (x, y) positions in data coordinates."""
        return self._add_marker("circles", name, offsets=offsets, radius=radius,
                                facecolors=facecolors, edgecolors=edgecolors,
                                linewidths=linewidths, alpha=alpha,
                                hover_edgecolors=hover_edgecolors,
                                hover_facecolors=hover_facecolors,
                                labels=labels, label=label,
                                transform=transform,
                                clip_display=clip_display)

    def add_points(self, offsets, name=None, *, sizes=5,
                   color="#ff0000", facecolors=None,
                   linewidths=1.5, alpha=0.3,
                   hover_edgecolors=None, hover_facecolors=None,
                   labels=None, label=None,
                   transform: str = "data",
                   clip_display: bool = True) -> "MarkerGroup":  # noqa: F821
        """Add point markers at (x, y) positions in data coordinates."""
        return self._add_marker("circles", name, offsets=offsets, radius=sizes,
                                edgecolors=color, facecolors=facecolors,
                                linewidths=linewidths, alpha=alpha,
                                hover_edgecolors=hover_edgecolors,
                                hover_facecolors=hover_facecolors,
                                labels=labels, label=label,
                                transform=transform,
                                clip_display=clip_display)

    def add_hlines(self, y_values, name=None, *,
                   color="#ff0000", linewidths=1.5,
                   hover_edgecolors=None,
                   labels=None, label=None,
                   transform: str = "data",
                   clip_display: bool = True) -> "MarkerGroup":  # noqa: F821
        """Add static horizontal lines at the given y positions."""
        return self._add_marker("hlines", name, offsets=y_values,
                                color=color, linewidths=linewidths,
                                hover_edgecolors=hover_edgecolors,
                                labels=labels, label=label,
                                transform=transform,
                                clip_display=clip_display)

    def add_vlines(self, x_values, name=None, *,
                   color="#ff0000", linewidths=1.5,
                   hover_edgecolors=None,
                   labels=None, label=None,
                   transform: str = "data",
                   clip_display: bool = True) -> "MarkerGroup":  # noqa: F821
        """Add static vertical lines at the given x positions."""
        return self._add_marker("vlines", name, offsets=x_values,
                                color=color, linewidths=linewidths,
                                hover_edgecolors=hover_edgecolors,
                                labels=labels, label=label,
                                transform=transform,
                                clip_display=clip_display)

    def add_arrows(self, offsets, U, V, name=None, *,
                   edgecolors="#ff0000", linewidths=1.5,
                   hover_edgecolors=None,
                   labels=None, label=None,
                   transform: str = "data",
                   clip_display: bool = True) -> "MarkerGroup":  # noqa: F821
        return self._add_marker("arrows", name, offsets=offsets, U=U, V=V,
                                edgecolors=edgecolors, linewidths=linewidths,
                                hover_edgecolors=hover_edgecolors,
                                labels=labels, label=label,
                                transform=transform,
                                clip_display=clip_display)

    def add_ellipses(self, offsets, widths, heights, name=None, *,
                     angles=0, facecolors=None, edgecolors="#ff0000",
                     linewidths=1.5, alpha=0.3,
                     hover_edgecolors=None, hover_facecolors=None,
                     labels=None, label=None,
                     transform: str = "data",
                     clip_display: bool = True) -> "MarkerGroup":  # noqa: F821
        return self._add_marker("ellipses", name, offsets=offsets,
                                widths=widths, heights=heights, angles=angles,
                                facecolors=facecolors, edgecolors=edgecolors,
                                linewidths=linewidths, alpha=alpha,
                                hover_edgecolors=hover_edgecolors,
                                hover_facecolors=hover_facecolors,
                                labels=labels, label=label,
                                transform=transform,
                                clip_display=clip_display)

    def add_lines(self, segments, name=None, *,
                  edgecolors="#ff0000", linewidths=1.5,
                  hover_edgecolors=None,
                  labels=None, label=None,
                  transform: str = "data",
                  clip_display: bool = True) -> "MarkerGroup":  # noqa: F821
        return self._add_marker("lines", name, segments=segments,
                                edgecolors=edgecolors, linewidths=linewidths,
                                hover_edgecolors=hover_edgecolors,
                                labels=labels, label=label,
                                transform=transform,
                                clip_display=clip_display)

    def add_rectangles(self, offsets, widths, heights, name=None, *,
                       angles=0, facecolors=None, edgecolors="#ff0000",
                       linewidths=1.5, alpha=0.3,
                       hover_edgecolors=None, hover_facecolors=None,
                       labels=None, label=None,
                       transform: str = "data",
                       clip_display: bool = True) -> "MarkerGroup":  # noqa: F821
        return self._add_marker("rectangles", name, offsets=offsets,
                                widths=widths, heights=heights, angles=angles,
                                facecolors=facecolors, edgecolors=edgecolors,
                                linewidths=linewidths, alpha=alpha,
                                hover_edgecolors=hover_edgecolors,
                                hover_facecolors=hover_facecolors,
                                labels=labels, label=label,
                                transform=transform,
                                clip_display=clip_display)

    def add_squares(self, offsets, widths, name=None, *,
                    angles=0, facecolors=None, edgecolors="#ff0000",
                    linewidths=1.5, alpha=0.3,
                    hover_edgecolors=None, hover_facecolors=None,
                    labels=None, label=None,
                    transform: str = "data",
                    clip_display: bool = True) -> "MarkerGroup":  # noqa: F821
        return self._add_marker("squares", name, offsets=offsets,
                                widths=widths, angles=angles,
                                facecolors=facecolors, edgecolors=edgecolors,
                                linewidths=linewidths, alpha=alpha,
                                hover_edgecolors=hover_edgecolors,
                                hover_facecolors=hover_facecolors,
                                labels=labels, label=label,
                                transform=transform,
                                clip_display=clip_display)

    def add_polygons(self, vertices_list, name=None, *,
                     facecolors=None, edgecolors="#ff0000",
                     linewidths=1.5, alpha=0.3,
                     hover_edgecolors=None, hover_facecolors=None,
                     labels=None, label=None,
                     transform: str = "data",
                     clip_display: bool = True) -> "MarkerGroup":  # noqa: F821
        return self._add_marker("polygons", name, vertices_list=vertices_list,
                                facecolors=facecolors, edgecolors=edgecolors,
                                linewidths=linewidths, alpha=alpha,
                                hover_edgecolors=hover_edgecolors,
                                hover_facecolors=hover_facecolors,
                                labels=labels, label=label,
                                transform=transform,
                                clip_display=clip_display)

    def add_texts(self, offsets, texts, name=None, *,
                  color="#ff0000", fontsize=12,
                  hover_edgecolors=None,
                  labels=None, label=None,
                  transform: str = "data",
                  clip_display: bool = True) -> "MarkerGroup":  # noqa: F821
        return self._add_marker("texts", name, offsets=offsets, texts=texts,
                                color=color, fontsize=fontsize,
                                hover_edgecolors=hover_edgecolors,
                                labels=labels, label=label,
                                transform=transform,
                                clip_display=clip_display)

    def __repr__(self) -> str:
        w = self._state.get("image_width", "?")
        h = self._state.get("image_height", "?")
        cmap = self._state.get("colormap_name", "?")
        return f"Plot2D({w}×{h}, cmap={cmap!r})"

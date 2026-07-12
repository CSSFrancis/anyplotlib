"""
plot2d/_layer.py
================
Multi-image LAYER handle for :class:`~anyplotlib.plot2d.Plot2D`.

A ``Layer`` is a second (third, …) scalar image drawn OVER the base image in the
same panel, each with its OWN colormap, clim (display range), and alpha.  It is
composited client-side (JS ``draw2d``) with the exact same image→screen
transform as the base image, so zoom/pan track perfectly.  This is distinct from
:meth:`Plot2D.set_overlay_mask`, which is a single-colour boolean mask.

The pixel bytes travel exactly like the base image ``image_b64``: base64 inline
for Jupyter / standalone / ``save_html``, and a raw PLOTBIN frame under the
Electron binary transport (``APL_BINARY_TRANSPORT=1``).  Each layer's pixels ride
a DYNAMIC geometry key ``layer_<id>_b64`` (see ``Plot2D._GEOM_KEYS`` /
``_electron._route_change`` / ``resolve_pixel_tokens``).

A ``Layer`` is a thin handle: it owns no state itself.  All state lives in the
parent plot's ``_state["layers"]`` list (metadata) plus the top-level
``layer_<id>_b64`` pixel key; the handle just forwards mutations to the plot.
"""
from __future__ import annotations

import itertools

_layer_counter = itertools.count(1)


def _next_layer_id() -> str:
    return f"L{next(_layer_counter)}"


class Layer:
    """Handle for one image layer on a :class:`Plot2D`.

    Do not construct directly — use :meth:`Plot2D.add_layer`.  The handle stays
    valid until :meth:`remove` (or :meth:`Plot2D.remove_layer`) is called.

    Attributes are read through the parent plot's state so they always reflect
    the latest ``set``/``set_data``.
    """

    def __init__(self, plot, layer_id: str) -> None:
        self._plot = plot
        self._id = layer_id
        self._removed = False

    # ── identity ──────────────────────────────────────────────────────────────
    @property
    def id(self) -> str:
        return self._id

    def _entry(self) -> dict:
        """Return this layer's metadata dict in the plot state (or raise)."""
        if self._removed:
            raise ValueError(f"layer {self._id!r} has been removed")
        for lyr in self._plot._state.get("layers", []):
            if lyr.get("id") == self._id:
                return lyr
        raise ValueError(f"layer {self._id!r} is no longer attached to its plot")

    # ── read-only views of the current state ──────────────────────────────────
    @property
    def cmap(self) -> str:
        return self._entry().get("cmap", "gray")

    @property
    def alpha(self) -> float:
        return float(self._entry().get("alpha", 1.0))

    @property
    def visible(self) -> bool:
        return bool(self._entry().get("visible", True))

    @property
    def clim(self):
        e = self._entry()
        return (e.get("clim_min"), e.get("clim_max"))

    # ── mutations (forwarded to the plot) ─────────────────────────────────────
    def set(self, *, cmap=None, alpha=None, clim=None, visible=None) -> "Layer":
        """Partial update of this layer's appearance (any subset of fields).

        ``cmap`` — colormap name.  ``alpha`` — opacity in [0, 1].  ``clim`` —
        ``(vmin, vmax)`` display range, or ``None`` to auto (data min/max).
        ``visible`` — draw or hide.  A pixel re-encode happens only when ``clim``
        changes (it re-quantises the cached frame); ``cmap``/``alpha``/``visible``
        are cheap LUT/compositor-only changes.
        """
        self._plot._layer_set(self._id, cmap=cmap, alpha=alpha, clim=clim,
                              visible=visible)
        return self

    def set_data(self, frame) -> "Layer":
        """Replace this layer's image data (the live path — one push, no full
        state rebuild).  ``frame`` must match the base image ``(H, W)``."""
        self._plot._layer_set_data(self._id, frame)
        return self

    def remove(self) -> None:
        """Remove this layer from its plot."""
        if self._removed:
            return
        self._plot.remove_layer(self)

    def __repr__(self) -> str:
        state = "removed" if self._removed else "active"
        return f"Layer(id={self._id!r}, {state})"

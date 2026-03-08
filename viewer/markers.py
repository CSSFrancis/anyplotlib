"""
markers.py
==========

Marker registry for Plot1D and Plot2D panels inside a Figure.

The public API mirrors matplotlib's collection kwargs:

    plot.add_circles(offsets, name="group1",
                     facecolors="#ff0000", edgecolors="#ffffff",
                     radius=5, labels=[...])

    plot.markers["circles"]["group1"].set(offsets=new_offsets, radius=3)

Design
------
* ``MarkerGroup``       – a single named collection of markers (one type).
* ``MarkerTypeDict``    – dict-like for one type; mutations propagate to the plot.
* ``MarkerRegistry``    – top-level two-level dict: registry[type][name].

All state is stored as plain Python dicts; no traitlets here.  The ``_push``
callback is supplied by the parent plot and is responsible for serialising
the full registry into the panel's JSON trait on the Figure widget.

Wire-format translation
-----------------------
The JS renderer uses the same internal field names as the standalone viewers
(``color``, ``fill_color``, ``fill_alpha``, ``sizes``, etc.).  ``MarkerGroup``
stores matplotlib-style names and ``to_wire()`` translates before JSON
serialisation.
"""

from __future__ import annotations

import numpy as np

__all__ = ["MarkerGroup", "MarkerTypeDict", "MarkerRegistry"]

# ---------------------------------------------------------------------------
# Type → wire-format converter registry
# ---------------------------------------------------------------------------

def _broadcast(val, n: int) -> list:
    """Broadcast scalar or sequence to a list of length *n*."""
    arr = np.asarray(val, dtype=float)
    if arr.ndim == 0:
        return np.full(n, float(arr)).tolist()
    if arr.ndim == 1 and len(arr) == n:
        return arr.tolist()
    raise ValueError(f"Expected scalar or length-{n} array, got shape {arr.shape}")


def _offsets_2d(offsets) -> list:
    arr = np.asarray(offsets, dtype=float)
    if arr.ndim == 1 and arr.shape[0] == 2:
        arr = arr[np.newaxis, :]
    if arr.ndim != 2 or arr.shape[1] != 2:
        raise ValueError("offsets must be shape (N, 2)")
    return arr.tolist()


def _offsets_1d(offsets) -> list:
    """Accept (N,), (N,1) or (N,2) — return (N,1) or (N,2) list."""
    arr = np.asarray(offsets, dtype=float)
    if arr.ndim == 0:
        return [[float(arr)]]
    if arr.ndim == 1:
        return arr[:, np.newaxis].tolist()
    if arr.ndim == 2 and arr.shape[1] in (1, 2):
        return arr.tolist()
    raise ValueError("offsets must be 1-D or shape (N,1)/(N,2)")


# ---------------------------------------------------------------------------
# MarkerGroup
# ---------------------------------------------------------------------------

class MarkerGroup:
    """A named collection of markers of one type on one plot.

    Parameters
    ----------
    marker_type : str
        One of the supported marker types (``'circles'``, ``'lines'``, …).
    name : str
        User-facing name (key in the parent :class:`MarkerTypeDict`).
    kwargs : dict
        Initial matplotlib-style kwargs for this group.
    push_fn : callable
        Zero-arg callback that serialises the full registry and pushes it to
        the parent figure trait.
    """

    def __init__(self, marker_type: str, name: str, kwargs: dict, push_fn):
        self._type = marker_type
        self._name = name
        self._data: dict = dict(kwargs)
        self._push_fn = push_fn

    # ------------------------------------------------------------------
    def set(self, **kwargs) -> None:
        """Update one or more properties and push the change to the plot."""
        self._data.update(kwargs)
        self._push_fn()

    def __repr__(self) -> str:  # pragma: no cover
        return f"MarkerGroup(type={self._type!r}, name={self._name!r}, n={self._count()})"

    def _count(self) -> int:
        offs = self._data.get("offsets")
        if offs is None:
            return 0
        try:
            return len(np.asarray(offs))
        except Exception:
            return 0

    # ------------------------------------------------------------------
    # Wire-format serialisation
    # ------------------------------------------------------------------
    def to_wire(self, group_id: str) -> dict:
        """Return a dict in the JS wire format for this marker group."""
        d = self._data
        t = self._type

        # Build the wire dict based on marker type
        if t == "circles":
            offsets = _offsets_2d(d["offsets"])
            n = len(offsets)
            wire: dict = {
                "id":        group_id,
                "name":      self._name,
                "type":      "circles",
                "offsets":   offsets,
                "sizes":     _broadcast(d.get("radius", 5), n),
                "color":     d.get("edgecolors", "#ff0000"),
                "linewidth": float(d.get("linewidths", 1.5)),
            }
            fc = d.get("facecolors")
            if fc is not None:
                wire["fill_color"] = fc
                wire["fill_alpha"] = float(d.get("alpha", 0.3))

        elif t == "arrows":
            offsets = _offsets_2d(d["offsets"])
            n = len(offsets)
            wire = {
                "id":        group_id,
                "name":      self._name,
                "type":      "arrows",
                "offsets":   offsets,
                "U":         _broadcast(d.get("U", 0), n),
                "V":         _broadcast(d.get("V", 0), n),
                "color":     d.get("edgecolors", d.get("color", "#ff0000")),
                "linewidth": float(d.get("linewidths", 1.5)),
            }

        elif t == "ellipses":
            offsets = _offsets_2d(d["offsets"])
            n = len(offsets)
            wire = {
                "id":        group_id,
                "name":      self._name,
                "type":      "ellipses",
                "offsets":   offsets,
                "widths":    _broadcast(d.get("widths", 10), n),
                "heights":   _broadcast(d.get("heights", 10), n),
                "angles":    _broadcast(d.get("angles", 0), n),
                "color":     d.get("edgecolors", d.get("color", "#ff0000")),
                "linewidth": float(d.get("linewidths", 1.5)),
            }
            fc = d.get("facecolors")
            if fc is not None:
                wire["fill_color"] = fc
                wire["fill_alpha"] = float(d.get("alpha", 0.3))

        elif t == "lines":
            segs = np.asarray(d["segments"], dtype=float)
            if segs.ndim == 2 and segs.shape == (2, 2):
                segs = segs[np.newaxis]
            if segs.ndim != 3 or segs.shape[1:] != (2, 2):
                raise ValueError("segments must be shape (N,2,2)")
            wire = {
                "id":        group_id,
                "name":      self._name,
                "type":      "lines",
                "segments":  segs.tolist(),
                "color":     d.get("edgecolors", d.get("color", "#ff0000")),
                "linewidth": float(d.get("linewidths", 1.5)),
            }

        elif t == "rectangles":
            offsets = _offsets_2d(d["offsets"])
            n = len(offsets)
            wire = {
                "id":        group_id,
                "name":      self._name,
                "type":      "rectangles",
                "offsets":   offsets,
                "widths":    _broadcast(d.get("widths", 10), n),
                "heights":   _broadcast(d.get("heights", 10), n),
                "angles":    _broadcast(d.get("angles", 0), n),
                "color":     d.get("edgecolors", d.get("color", "#ff0000")),
                "linewidth": float(d.get("linewidths", 1.5)),
            }
            fc = d.get("facecolors")
            if fc is not None:
                wire["fill_color"] = fc
                wire["fill_alpha"] = float(d.get("alpha", 0.3))

        elif t == "squares":
            offsets = _offsets_2d(d["offsets"])
            n = len(offsets)
            wire = {
                "id":        group_id,
                "name":      self._name,
                "type":      "squares",
                "offsets":   offsets,
                "widths":    _broadcast(d.get("widths", 10), n),
                "angles":    _broadcast(d.get("angles", 0), n),
                "color":     d.get("edgecolors", d.get("color", "#ff0000")),
                "linewidth": float(d.get("linewidths", 1.5)),
            }
            fc = d.get("facecolors")
            if fc is not None:
                wire["fill_color"] = fc
                wire["fill_alpha"] = float(d.get("alpha", 0.3))

        elif t == "polygons":
            vlist = []
            for poly in d.get("vertices_list", []):
                arr = np.asarray(poly, dtype=float)
                if arr.ndim != 2 or arr.shape[1] != 2 or len(arr) < 3:
                    raise ValueError("each polygon must be (N>=3, 2)")
                vlist.append(arr.tolist())
            wire = {
                "id":           group_id,
                "name":         self._name,
                "type":         "polygons",
                "vertices_list": vlist,
                "color":        d.get("edgecolors", d.get("color", "#ff0000")),
                "linewidth":    float(d.get("linewidths", 1.5)),
            }
            fc = d.get("facecolors")
            if fc is not None:
                wire["fill_color"] = fc
                wire["fill_alpha"] = float(d.get("alpha", 0.3))

        elif t == "texts":
            offsets = _offsets_2d(d["offsets"])
            texts = list(d.get("texts", []))
            wire = {
                "id":       group_id,
                "name":     self._name,
                "type":     "texts",
                "offsets":  offsets,
                "texts":    texts,
                "color":    d.get("color", d.get("edgecolors", "#ff0000")),
                "fontsize": int(d.get("fontsize", 12)),
            }

        # ── 1D-only types ───────────────────────────────────────────────────
        elif t == "points":
            offsets = _offsets_1d(d["offsets"])
            n = len(offsets)
            wire = {
                "id":        group_id,
                "name":      self._name,
                "type":      "points",
                "offsets":   offsets,
                "sizes":     _broadcast(d.get("sizes", 5), n),
                "color":     d.get("edgecolors", d.get("color", "#ff0000")),
                "linewidth": float(d.get("linewidths", 1.5)),
            }
            fc = d.get("facecolors")
            if fc is not None:
                wire["fill_color"] = fc
                wire["fill_alpha"] = float(d.get("alpha", 0.3))

        elif t == "vlines":
            offsets = _offsets_1d(d["offsets"])
            wire = {
                "id":        group_id,
                "name":      self._name,
                "type":      "vlines",
                "offsets":   [[row[0]] for row in offsets],
                "color":     d.get("color", d.get("edgecolors", "#ff0000")),
                "linewidth": float(d.get("linewidths", 1.5)),
            }

        elif t == "hlines":
            offsets = _offsets_1d(d["offsets"])
            wire = {
                "id":        group_id,
                "name":      self._name,
                "type":      "hlines",
                "offsets":   [[row[0]] for row in offsets],
                "color":     d.get("color", d.get("edgecolors", "#ff0000")),
                "linewidth": float(d.get("linewidths", 1.5)),
            }

        else:
            raise ValueError(f"Unknown marker type: {t!r}")

        # ── common optional fields ──────────────────────────────────────────
        label = d.get("label")
        if label is not None:
            wire["label"] = str(label)
        labels = d.get("labels")
        if labels is not None:
            wire["labels"] = [str(lb) for lb in labels]

        # ── hover colours (optional) ────────────────────────────────────────
        # Applied to all markers in the group when any one is hovered.
        # Names mirror the base colour kwargs: edgecolors → hover_edgecolors,
        # facecolors → hover_facecolors.  Any CSS colour string is accepted.
        hec = d.get("hover_edgecolors")
        if hec is not None:
            wire["hover_color"] = str(hec)
        hfc = d.get("hover_facecolors")
        if hfc is not None:
            wire["hover_facecolor"] = str(hfc)

        return wire


# ---------------------------------------------------------------------------
# MarkerTypeDict
# ---------------------------------------------------------------------------

class MarkerTypeDict:
    """Dict-like container for all named groups of one marker type.

    Any modification (``__setitem__``, ``__delitem__``) automatically triggers
    the ``_push_fn`` callback so the plot re-renders.
    """

    def __init__(self, marker_type: str, push_fn):
        self._type = marker_type
        self._push_fn = push_fn
        self._groups: dict[str, MarkerGroup] = {}

    # ------------------------------------------------------------------
    # dict-like interface
    def __getitem__(self, name: str) -> MarkerGroup:
        return self._groups[name]

    def __setitem__(self, name: str, group: MarkerGroup) -> None:
        self._groups[name] = group
        self._push_fn()

    def __delitem__(self, name: str) -> None:
        del self._groups[name]
        self._push_fn()

    def __contains__(self, name: object) -> bool:
        return name in self._groups

    def __iter__(self):
        return iter(self._groups)

    def __len__(self) -> int:
        return len(self._groups)

    def __repr__(self) -> str:  # pragma: no cover
        return f"MarkerTypeDict(type={self._type!r}, groups={list(self._groups)})"

    def keys(self):
        return self._groups.keys()

    def values(self):
        return self._groups.values()

    def items(self):
        return self._groups.items()

    def pop(self, name: str, *args):
        result = self._groups.pop(name, *args)
        self._push_fn()
        return result

    # ------------------------------------------------------------------
    def _add(self, name: str, kwargs: dict) -> "MarkerGroup":
        """Internal: create and register a MarkerGroup without double-pushing."""
        g = MarkerGroup(self._type, name, kwargs, self._push_fn)
        self._groups[name] = g
        return g

    def to_wire_list(self) -> list:
        """Serialise all groups to a list of wire-format dicts."""
        out = []
        for gid, g in self._groups.items():
            out.append(g.to_wire(gid))
        return out


# ---------------------------------------------------------------------------
# MarkerRegistry
# ---------------------------------------------------------------------------

class MarkerRegistry:
    """Top-level two-level marker registry for a plot.

    Usage::

        plot.markers["circles"]["group1"].set(offsets=new_offsets)

    ``plot.markers`` is a ``MarkerRegistry``.  Indexing by type returns a
    :class:`MarkerTypeDict` (auto-created on first access).
    """

    # Known marker types — used for validation and auto-naming.
    _KNOWN_2D = frozenset({
        "circles", "arrows", "ellipses", "lines",
        "rectangles", "squares", "polygons", "texts",
    })
    _KNOWN_1D = frozenset({
        "points", "vlines", "hlines", "lines", "rectangles",
        "ellipses", "polygons", "texts",
    })

    def __init__(self, push_fn, allowed: frozenset | None = None):
        """
        Parameters
        ----------
        push_fn :
            Callable that re-serialises the full registry and writes to the
            Figure trait.
        allowed :
            Set of allowed type names.  ``None`` means all known types.
        """
        self._push_fn = push_fn
        self._allowed = allowed
        self._types: dict[str, MarkerTypeDict] = {}

    # ------------------------------------------------------------------
    def __getitem__(self, marker_type: str) -> MarkerTypeDict:
        if marker_type not in self._types:
            self._types[marker_type] = MarkerTypeDict(marker_type, self._push_fn)
        return self._types[marker_type]

    def __contains__(self, marker_type: object) -> bool:
        return marker_type in self._types

    def __iter__(self):
        return iter(self._types)

    def __repr__(self) -> str:  # pragma: no cover
        return f"MarkerRegistry(types={list(self._types)})"

    # ------------------------------------------------------------------
    def _auto_name(self, marker_type: str) -> str:
        """Return the next auto-generated name like ``circles_1``, ``circles_2``…

        Never reuses an existing key (monotonically increasing).
        """
        td = self._types.get(marker_type)
        if td is None or len(td) == 0:
            return f"{marker_type}_1"
        # Find the highest existing integer suffix
        max_n = 0
        for key in td.keys():
            prefix = f"{marker_type}_"
            if key.startswith(prefix):
                try:
                    n = int(key[len(prefix):])
                    if n > max_n:
                        max_n = n
                except ValueError:
                    pass
        return f"{marker_type}_{max_n + 1}"

    def add(self, marker_type: str, name: str | None = None, **kwargs) -> MarkerGroup:
        """Add a marker group, returning the :class:`MarkerGroup`.

        Parameters
        ----------
        marker_type :
            Type string, e.g. ``'circles'``.
        name :
            Group name.  Auto-generated (``'circles_1'`` etc.) if ``None``.
        **kwargs :
            Matplotlib-style kwargs for the group.

        Returns
        -------
        MarkerGroup
        """
        if name is None:
            name = self._auto_name(marker_type)
        td = self[marker_type]          # auto-creates MarkerTypeDict
        g = td._add(name, kwargs)       # create without double push
        self._push_fn()                 # single push after group is ready
        return g

    def remove(self, marker_type: str, name: str) -> None:
        """Remove a named group (triggers a push)."""
        del self[marker_type][name]     # MarkerTypeDict.__delitem__ pushes

    def clear(self) -> None:
        """Remove all markers of all types."""
        self._types.clear()
        self._push_fn()

    def to_wire_list(self) -> list:
        """Flatten the full registry to a list of wire-format dicts."""
        out = []
        for td in self._types.values():
            out.extend(td.to_wire_list())
        return out


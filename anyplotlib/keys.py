"""
keys.py
=======
Floating image *keys* — a colour legend pinned over a panel.

A key is the scale bar's sibling: a small picture that floats in a corner of
the plot area, in screen space, and does not pan or zoom with the data.  It is
what you reach for when the colours in a plot mean something a colorbar cannot
say — an inverse pole figure triangle over an orientation map, a hue wheel
over a polarization vector field, a phase legend over a segmentation.

Deliberately *not* an inset axes.  :meth:`Figure.add_inset` gives you a
draggable window with a title bar, a border and a full canvas stack — the
right thing when the overlay is itself a plot you want to interact with, and
much too heavy when it is a static picture that should read as part of the
figure.  A key has no chrome unless you ask for it, no event wiring, and one
canvas shared by every key on the panel.

See :meth:`anyplotlib._base_plot._BasePlot.add_key`.
"""

from __future__ import annotations

import uuid as _uuid

CORNERS = ("top-left", "top-right", "bottom-left", "bottom-right")


class KeyOverlay:
    """A floating image key pinned to a panel corner.

    Created by :meth:`~anyplotlib.Plot2D.add_key`; not constructed directly.

    Every property is settable through :meth:`set`, which pushes to the
    renderer in one update::

        key = plot.add_key(ipf_triangle, corner="bottom-right")
        key.set(size=0.3, bgcolor="none")
        key.visible = False          # plain attribute assignment also pushes
    """

    #: Fields that live on the light view channel.  The image itself does NOT
    #: appear here — it rides the geometry channel keyed by id, so restyling a
    #: key (or toggling `visible`) never re-transmits the picture.
    _FIELDS = (
        "corner", "anchor", "size", "margin", "bgcolor", "border",
        "border_width", "radius", "alpha", "hover_only", "visible",
        "label", "label_size", "label_color", "labels",
    )

    def __init__(self, plot, image_url: str, *, name=None, **kwargs):
        self._id: str = str(_uuid.uuid4())[:8]
        self._plot = plot
        self._url: str = image_url
        self._name: str = str(name) if name is not None else self._id
        self._data: dict = {"id": self._id}
        self._data.update(kwargs)

    # ── identity ──────────────────────────────────────────────────────

    @property
    def id(self) -> str:
        """Short unique identifier."""
        return self._id

    @property
    def name(self) -> str:
        """Caller-supplied name, or the id when none was given.

        Use it with :meth:`~anyplotlib.Plot2D.get_key`.
        """
        return self._name

    # ── attribute access ──────────────────────────────────────────────

    def __getattr__(self, key: str):
        if key.startswith("_"):
            raise AttributeError(key)
        try:
            return self._data[key]
        except KeyError:
            raise AttributeError(
                f"{type(self).__name__!s} has no property {key!r}") from None

    def __setattr__(self, key: str, value) -> None:
        if key.startswith("_") or key in ("id", "name"):
            object.__setattr__(self, key, value)
        elif key in self._FIELDS:
            self.set(**{key: value})
        else:
            raise AttributeError(
                f"{type(self).__name__!s} has no property {key!r}")

    # ── mutation ──────────────────────────────────────────────────────

    def set(self, **kwargs) -> None:
        """Update one or more properties and push once.

        Accepts any of the constructor's keyword arguments except ``image``
        (use :meth:`set_image` — it travels on a different channel).

        Raises
        ------
        ValueError
            On an unknown property name, or a value the constructor would
            also have rejected.
        """
        unknown = set(kwargs) - set(self._FIELDS)
        if unknown:
            raise ValueError(
                f"unknown key property {sorted(unknown)!r}; "
                f"valid: {sorted(self._FIELDS)!r}")
        self._data.update(_validate(kwargs))
        self._sync()

    def set_image(self, image) -> None:
        """Replace the picture, keeping placement and styling.

        Parameters
        ----------
        image : array-like, bytes, or path
            Same input :meth:`~anyplotlib.Plot2D.add_key` accepts.
        """
        from anyplotlib._utils import _image_to_data_url
        self._url = _image_to_data_url(image)
        self._sync()

    def remove(self) -> None:
        """Remove this key from its panel."""
        if self._plot is not None:
            self._plot.remove_key(self)

    # ── wire format ───────────────────────────────────────────────────

    def to_dict(self) -> dict:
        """The light view-channel payload (no image bytes)."""
        return dict(self._data)

    @property
    def image_url(self) -> str:
        """The ``data:`` URL the renderer decodes."""
        return self._url

    def _sync(self) -> None:
        if self._plot is not None:
            self._plot._push_keys()

    def __repr__(self) -> str:  # pragma: no cover
        where = (f"anchor={self._data['anchor']}"
                 if self._data.get("anchor") else
                 f"corner={self._data.get('corner')!r}")
        return (f"<KeyOverlay {self._name!r} {where} "
                f"size={self._data.get('size')}>")


def _validate(kw: dict) -> dict:
    """Coerce and range-check the subset of key properties present in *kw*."""
    out = dict(kw)

    if "corner" in out and out["corner"] is not None:
        c = str(out["corner"]).lower()
        if c not in CORNERS:
            raise ValueError(
                f"corner must be one of {list(CORNERS)}, got {out['corner']!r}")
        out["corner"] = c

    if out.get("anchor") is not None:
        a = out["anchor"]
        if len(a) != 2:
            raise ValueError(f"anchor must be (x_frac, y_frac), got {a!r}")
        out["anchor"] = [float(a[0]), float(a[1])]

    if "size" in out:
        s = float(out["size"])
        if not 0.0 < s <= 1.0:
            raise ValueError(
                f"size is a fraction of the plot area's shorter side and must "
                f"be in (0, 1], got {s}")
        out["size"] = s

    if "alpha" in out:
        a = float(out["alpha"])
        if not 0.0 <= a <= 1.0:
            raise ValueError(f"alpha must be in [0, 1], got {a}")
        out["alpha"] = a

    for k in ("margin", "border_width", "radius", "label_size"):
        if k in out and out[k] is not None:
            v = float(out[k])
            if v < 0:
                raise ValueError(f"{k} must be >= 0, got {v}")
            out[k] = v

    for k in ("hover_only", "visible"):
        if k in out:
            out[k] = bool(out[k])

    for k in ("bgcolor", "border", "label_color", "label"):
        if k in out and out[k] is not None:
            out[k] = str(out[k])

    if "labels" in out:
        out["labels"] = _coerce_labels(out["labels"])

    return out


def _coerce_labels(labels) -> list:
    """Normalise in-image text annotations to plain JSON-able dicts.

    Accepts ``(x, y, text)`` triples or dicts with the same keys plus optional
    ``size`` / ``color`` / ``align``.  ``x``/``y`` are fractions of the key
    IMAGE box, so they follow the picture when the key is resized — which is
    the point: an IPF triangle's corner labels have to stay on the corners.
    """
    if labels is None:
        return []
    out = []
    for i, item in enumerate(labels):
        if isinstance(item, dict):
            d = dict(item)
        else:
            seq = list(item)
            if len(seq) != 3:
                raise ValueError(
                    f"labels[{i}]: expected (x, y, text) or a dict, got "
                    f"{len(seq)} values")
            d = {"x": seq[0], "y": seq[1], "text": seq[2]}
        missing = {"x", "y", "text"} - set(d)
        if missing:
            raise ValueError(f"labels[{i}] is missing {sorted(missing)!r}")
        unknown = set(d) - {"x", "y", "text", "size", "color", "align"}
        if unknown:
            raise ValueError(
                f"labels[{i}]: unknown key(s) {sorted(unknown)!r}; valid: "
                "x, y, text, size, color, align")
        if d.get("align") not in (None, "left", "center", "right"):
            raise ValueError(
                f"labels[{i}]: align must be 'left', 'center' or 'right', "
                f"got {d['align']!r}")
        entry = {"x": float(d["x"]), "y": float(d["y"]), "text": str(d["text"])}
        if d.get("size") is not None:
            entry["size"] = float(d["size"])
        if d.get("color") is not None:
            entry["color"] = str(d["color"])
        if d.get("align") is not None:
            entry["align"] = d["align"]
        out.append(entry)
    return out

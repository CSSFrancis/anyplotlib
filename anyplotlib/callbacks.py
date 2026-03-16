"""
callbacks.py
============

Two-tier event / callback system for anyplotlib plot objects.

The two tiers map directly to what the JS already provides:

``'change'``  — fires on every animation frame while a drag is in
               progress (~16 ms cadence, coalesced by
               ``requestAnimationFrame``).  Keep callbacks here
               **fast**: update a text readout, move a linked cursor.

``'release'`` — fires exactly **once** when the interaction settles
               (mouseup, scroll end, key press).  Safe for expensive
               work: re-fit a spectrum, recompute an integral,
               re-render a dependent plot.

Both tiers receive the same :class:`Event` object; the ``settled``
boolean tells you which tier fired.

Usage
-----

.. code-block:: python

    import anyplotlib as apl
    import numpy as np

    fig, ax = apl.subplots(1, 1)
    v = ax.imshow(data, axes=[x, y], units="nm")

    # ── specific widget, two tiers ─────────────────────────────────
    wid = v.add_widget("crosshair", cx=64, cy=64)

    @v.on_change(wid)           # fast — every drag frame
    def live(event):
        readout.value = f"({event.cx:.1f}, {event.cy:.1f})"

    @v.on_release(wid)          # slow work — only when drag settles
    def settled(event):
        recompute(event.cx, event.cy)

    # ── any widget on this panel, on release ───────────────────────
    @v.on_release()
    def any_settled(event):
        print(event)

    # ── 1-D vline ──────────────────────────────────────────────────
    v1 = ax1.plot(spectrum, axes=[energy], units="eV")
    wid2 = v1.add_vline_widget(x=284.8)

    @v1.on_release(wid2)
    def peak_selected(event):
        idx = np.searchsorted(energy, event.x)
        print(f"{event.x:.2f} eV  →  I={spectrum[idx]:.4f}")

    # ── disconnect by CID (matplotlib-style) ───────────────────────
    cid = v.on_release(wid)(my_fn)
    v.disconnect(cid)

    # ── single-fire pattern ────────────────────────────────────────
    @v.on_release(wid)
    def once(event):
        do_work(event)
        v.disconnect(once._cid)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


# ---------------------------------------------------------------------------
# Event
# ---------------------------------------------------------------------------

@dataclass
class Event:
    """A single interactive event from the JS frontend.

    Attributes
    ----------
    name : str
        Event category:

        ``'widget_change'``  – 2-D overlay widget dragged / resized.
        ``'vline_change'``   – 1-D vline widget moved.
        ``'hline_change'``   – 1-D hline widget moved.
        ``'range_change'``   – 1-D range widget moved / resized.
        ``'zoom_change'``    – 2-D panel panned / zoomed.
        ``'view_change'``    – 1-D view window panned / zoomed.
        ``'rotate_change'``  – 3-D camera rotated / zoomed.

    panel_id : str
        Internal panel identifier.
    widget_id : str or None
        The ``wid`` from ``add_widget`` / ``add_vline_widget`` etc.,
        or ``None`` for view / zoom / rotate events.
    settled : bool
        ``True`` when the interaction has finished (mouseup / scroll
        end / key press).  ``False`` while a drag is still live.

        Use this to gate expensive work::

            def cb(event):
                update_readout(event.cx)      # always cheap
                if event.settled:
                    recompute(event.cx)       # only when done

    data : dict
        Full updated widget or view-state dict.  All keys are also
        forwarded as top-level attributes::

            event.cx    # same as event.data['cx']
            event.x0    # same as event.data['x0']
            event.zoom  # same as event.data['zoom']
    """

    name:      str
    panel_id:  str
    widget_id: str | None
    settled:   bool
    data:      dict = field(default_factory=dict)

    def __getattr__(self, key: str) -> Any:
        try:
            return self.data[key]
        except KeyError:
            raise AttributeError(
                f"Event has no attribute {key!r}. "
                f"Available data keys: {list(self.data)}"
            ) from None

    def __repr__(self) -> str:
        parts = [
            f"name={self.name!r}",
            f"panel_id={self.panel_id!r}",
            f"settled={self.settled}",
        ]
        if self.widget_id is not None:
            parts.append(f"widget_id={self.widget_id!r}")
        _skip = {"id", "type", "color", "colormap_data",
                 "image_b64", "histogram_data", "colormap_name"}
        shown = 0
        for k, v in self.data.items():
            if k in _skip or shown >= 6:
                continue
            parts.append(
                f"{k}={v:.4g}" if isinstance(v, float) else f"{k}={v!r}"
            )
            shown += 1
        return f"Event({', '.join(parts)})"


# ---------------------------------------------------------------------------
# CallbackRegistry
# ---------------------------------------------------------------------------

class CallbackRegistry:
    """Per-plot callback registry with change / release tiers and CID management.

    Instantiated once per plot object.  Users interact through the
    convenience methods on plot objects:

    * ``plot.on_change(wid)``   – decorator; fires every drag frame.
    * ``plot.on_release(wid)``  – decorator; fires once on settle.
    * ``plot.disconnect(cid)``  – remove a handler by integer CID.

    Matching rules
    --------------
    An entry fires when **all** conditions match:

    * *tier* matches ``event.settled``
      (``'change'`` → ``not settled``, ``'release'`` → ``settled``).
    * *name* is ``None`` (wildcard) **or** equals ``event.name``.
    * *widget_id* is ``None`` (wildcard) **or** equals ``event.widget_id``.
    """

    def __init__(self) -> None:
        self._next_cid: int = 1
        # {cid: (tier, name_or_None, widget_id_or_None, fn)}
        self._entries: dict[int, tuple[str, str | None, str | None, Callable]] = {}

    # ------------------------------------------------------------------
    def connect(self, tier: str, name: str | None,
                widget_id: str | None, fn: Callable) -> int:
        """Register *fn* and return an integer CID.

        Parameters
        ----------
        tier      : ``'change'`` or ``'release'``
        name      : event name to match, or ``None`` for any.
        widget_id : widget id to match, or ``None`` for any.
        fn        : callable ``(event: Event) -> None``.
        """
        if tier not in ("change", "release"):
            raise ValueError("tier must be 'change' or 'release'")
        cid = self._next_cid
        self._next_cid += 1
        self._entries[cid] = (tier, name, widget_id, fn)
        return cid

    def disconnect(self, cid: int) -> None:
        """Remove the handler registered under *cid*.  Silent if not found."""
        self._entries.pop(cid, None)

    def fire(self, event: "Event") -> None:
        """Dispatch *event* to all matching handlers."""
        tier = "release" if event.settled else "change"
        for _cid, (t, n, wid, fn) in list(self._entries.items()):
            if t != tier:
                continue
            if n is not None and n != event.name:
                continue
            if wid is not None and wid != event.widget_id:
                continue
            fn(event)

    def __bool__(self) -> bool:
        return bool(self._entries)


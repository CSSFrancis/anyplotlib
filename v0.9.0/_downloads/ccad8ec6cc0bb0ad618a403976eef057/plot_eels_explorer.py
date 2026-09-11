"""
EELS multi-spectrum explorer.
==============================

Five synthetic EELS spectra (Carbon-rich, Nitride, Oxide, Silicide,
Mixed) stacked vertically on a single axis, each with known
characteristic edges and a power-law background.

**Interaction**

* **Click** a spectrum line — selects it (full opacity; others dim to
  25 %).
* **Dwell 250 ms** — shows eV position and intensity; nearby known
  edges (C K, N K, O K, Ti L) are annotated.
* **Double-click** — places a permanent vertical edge marker on the
  active spectrum.
* **Delete / Backspace** — removes the most recent marker on the
  active spectrum.
* **Tab / Shift+Tab** — cycles the selection forward / backward.
"""
import numpy as np
import anyplotlib as apl


# ── synthetic data ─────────────────────────────────────────────────────────────

ENERGY = np.linspace(50, 650, 1200)

KNOWN_EDGES = {"C K": 284.0, "N K": 401.0, "O K": 532.0, "Ti L": 456.0}

_SPECTRUM_DEFS = [
    {"name": "Carbon-rich",  "color": "#4fc3f7", "edges": [("C K", 284, 0.6)]},
    {"name": "Nitride",      "color": "#aed581", "edges": [("N K", 401, 0.5)]},
    {"name": "Oxide",        "color": "#ff8a65", "edges": [("O K", 532, 0.7)]},
    {"name": "Silicide",     "color": "#ba68c8", "edges": [("Si L", 99, 0.3)]},
    {"name": "Mixed",        "color": "#fff176", "edges": [("C K", 284, 0.2), ("O K", 532, 0.15)]},
]


def _power_law_bg(E, A=1e4, r=3.5):
    return A * E ** (-r)


def _edge_onset(E, edge_ev, amplitude, width=20.0, decay=80.0):
    onset = amplitude * (np.arctan((E - edge_ev) / (width / 6)) / np.pi + 0.5)
    envelope = np.exp(-np.clip(E - edge_ev, 0, None) / decay)
    return onset * envelope


def _make_spectrum(rng, defn, offset_y):
    E = ENERGY
    y = _power_law_bg(E)
    for _, edge_ev, amp_frac in defn["edges"]:
        peak = y.max() * amp_frac
        y += _edge_onset(E, edge_ev, peak)
    y += rng.normal(0, y.max() * 0.005, size=len(E))
    y = np.clip(y, 0, None)
    y = y / y.max()
    return y + offset_y


rng = np.random.default_rng(7)
spectra_y = []
offset = 0.0
for defn in _SPECTRUM_DEFS:
    y = _make_spectrum(rng, defn, offset)
    spectra_y.append(y)
    offset += 1.2 * (y - offset).max()


# ── helpers ────────────────────────────────────────────────────────────────────

def _safe_remove(plot, marker_type: str, name: str) -> None:
    try:
        plot.remove_marker(marker_type, name)
    except KeyError:
        pass


# ── figure ─────────────────────────────────────────────────────────────────────

# spectrum 0 is the primary line; spectra 1-4 are overlay lines
fig, ax = apl.subplots(1, 1, figsize=(800, 500))
plot = ax.plot(spectra_y[0], axes=[ENERGY], color=_SPECTRUM_DEFS[0]["color"], linewidth=2.5)

# overlay_lines[i] is the Line1D handle for spectrum i (None for the primary)
overlay_lines = []
for i in range(1, len(_SPECTRUM_DEFS)):
    defn = _SPECTRUM_DEFS[i]
    line = plot.add_line(spectra_y[i], x_axis=ENERGY, color=defn["color"], linewidth=1.0)
    overlay_lines.append(line)

# spectra index → Line1D (or None for primary)
# lines[0] == None means "primary line", lines[1..] == Line1D handles
line_handles = [None] + overlay_lines  # len == len(_SPECTRUM_DEFS)

active_idx: int = 0
markers_per_spectrum: list[list[str]] = [[] for _ in _SPECTRUM_DEFS]
_marker_counter = [0]

info_label_mg = plot.add_texts(
    offsets=np.array([[ENERGY[600], spectra_y[0][600]]]),
    texts=[""],
    name="info_label",
    color="#00e5ff",
    fontsize=11,
)


# ── selection helpers ───────────────────────────────────────────────────────────

def _set_overlay_line_props(lid: str, linewidth: float, alpha: float) -> None:
    """Directly mutate an overlay line's entry in plot._state and push."""
    for entry in plot._state["extra_lines"]:
        if entry["id"] == lid:
            entry["linewidth"] = float(linewidth)
            entry["alpha"] = float(alpha)
            break
    plot._push()


def _apply_selection(new_idx: int) -> None:
    global active_idx
    active_idx = new_idx
    for i, handle in enumerate(line_handles):
        if i == active_idx:
            lw, alpha = 2.5, 1.0
        else:
            lw, alpha = 1.0, 0.25
        if handle is None:
            # primary line — use Plot1D setters
            plot.set_linewidth(lw)
            plot.set_alpha(alpha)
        else:
            _set_overlay_line_props(handle._lid, lw, alpha)
    print(f"Selected: {_SPECTRUM_DEFS[active_idx]['name']}")


_apply_selection(0)


# ── event handlers ─────────────────────────────────────────────────────────────

def _make_line_handler(idx: int):
    def _handler(event) -> None:
        _apply_selection(idx)
    return _handler


# primary line click handler — line_id is None for the primary
plot.line.add_event_handler(_make_line_handler(0), "pointer_down")

# overlay line click handlers
for i, handle in enumerate(overlay_lines, start=1):
    handle.add_event_handler(_make_line_handler(i), "pointer_down")


def _on_settled(event) -> None:
    if event.xdata is None:
        return
    ev = event.xdata
    intensity = float(np.interp(ev, ENERGY, spectra_y[active_idx]))
    label = f"eV: {ev:.1f}  I: {intensity:.3f}"
    for edge_name, edge_ev in KNOWN_EDGES.items():
        if abs(ev - edge_ev) < 15:
            label += f"\n~ {edge_name}-edge"
    y_pos = intensity + 0.05
    plot.markers["texts"]["info_label"].set(
        offsets=np.array([[ev, y_pos]]),
        texts=[label],
    )


def _on_double_click(event) -> None:
    ev = event.xdata
    _marker_counter[0] += 1
    name = f"edge_{active_idx}_{_marker_counter[0]}"
    plot.add_vlines([ev], name=name)
    markers_per_spectrum[active_idx].append(name)
    print(f"Edge marker placed at {ev:.1f} eV on '{_SPECTRUM_DEFS[active_idx]['name']}'")


def _on_key(event) -> None:
    global active_idx
    if event.key in ("Delete", "Backspace"):
        if not markers_per_spectrum[active_idx]:
            return
        name = markers_per_spectrum[active_idx].pop()
        _safe_remove(plot, "vlines", name)
    elif event.key == "Tab":
        n = len(_SPECTRUM_DEFS)
        if "shift" in event.modifiers:
            new_idx = (active_idx - 1) % n
        else:
            new_idx = (active_idx + 1) % n
        _apply_selection(new_idx)


plot.add_event_handler(_on_settled, "pointer_settled", ms=250)
plot.add_event_handler(_on_double_click, "double_click")
plot.add_event_handler(_on_key, "key_down")

fig.set_help(
    "Click a spectrum: select it\n"
    "Dwell 250 ms: inspect eV + intensity\n"
    "Double-click: place edge marker\n"
    "Delete / Backspace: remove last marker\n"
    "Tab / Shift+Tab: cycle selection"
)

fig  # interactive

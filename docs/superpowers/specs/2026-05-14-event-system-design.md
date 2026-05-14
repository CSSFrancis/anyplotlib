# Event System Redesign

**Date:** 2026-05-14
**Status:** Approved — ready for implementation planning

## Motivation

The existing event system has several inconsistencies identified during a pre-0.1.0 audit:

- `on_click` fires on mouse press (not full click cycle) — misleading name
- `on_release` means "debounced/settled" not "mouse button released" — misleading name
- `on_changed` conflates viewport pan/zoom with widget drag frames
- `phys_x`/`phys_y` are non-standard field names; matplotlib users expect `xdata`/`ydata`
- Modifier keys (ctrl, shift, alt) are not exposed on any event
- No `pointer_up`, `pointer_enter`, `pointer_leave`, `double_click`, `wheel`, or `key_up` events
- `on_key` decorator has asymmetric optional-argument syntax inconsistent with all other decorators
- `on_click` payload differs completely across plot types (coords on Plot1D/2D, bar metadata on PlotBar, no data coords on Plot3D)
- No way to pause or buffer events during batch operations

The redesign aligns with the [pygfx/rendercanvas event system](https://github.com/pygfx/rendercanvas) naming and adds anyplotlib-specific extensions (`pointer_settled`, pause/hold).

---

## Section 1: Event Types

### Pointer events (all plot types)

| Event | Trigger |
|-------|---------|
| `pointer_down` | Mouse/touch pressed — replaces `on_click` |
| `pointer_up` | Mouse/touch physically released — new |
| `pointer_move` | Pointer moved (drag or hover) — replaces `on_changed` |
| `pointer_settled` | Pointer held still for ≥ N ms within ± delta px — replaces `on_release`, gains explicit params |
| `pointer_enter` | Cursor enters the panel — new |
| `pointer_leave` | Cursor leaves the panel — new |
| `double_click` | Double-click / long-tap — new |
| `wheel` | Scroll wheel or pinch — new |

### Key events (all plot types)

| Event | Trigger |
|-------|---------|
| `key_down` | Key pressed while panel focused — replaces `on_key` |
| `key_up` | Key released — new |

### Plot-specific behaviour

`pointer_move` and `pointer_down` on **Plot1D** carry a `line_id` field when the pointer is over a line (`None` otherwise). These are not separate event types — the same event carries extra data. Users check `if event.line_id` to distinguish. This replaces the separate `on_line_hover` and `on_line_click` event types.

---

## Section 2: Event Object Fields

The `Event` dataclass is flattened — all fields are top-level attributes with `None` as the default when a field does not apply. No more `data` dict with attribute proxy.

### Universal fields (every event)

| Field | Type | Description |
|-------|------|-------------|
| `event_type` | `str` | e.g. `"pointer_down"` |
| `source` | `object` | the plot or widget that fired it |
| `time_stamp` | `float` | `perf_counter()` at fire time |
| `modifiers` | `list[str]` | `["ctrl"]`, `["shift"]`, `["alt"]`, `["meta"]` — empty list if none |

### Pointer fields (pointer_down, pointer_up, pointer_move, pointer_settled, pointer_enter, pointer_leave, double_click)

| Field | Type | Present on |
|-------|------|-----------|
| `x` | `int` | all pointer events — pixel x within panel |
| `y` | `int` | all pointer events — pixel y within panel |
| `button` | `int \| None` | `pointer_down`, `pointer_up`, `double_click` only — 0=left, 1=middle, 2=right; `None` on enter/leave/move/settled |
| `buttons` | `int` | all pointer events — bitmask of currently held buttons (useful on `pointer_enter` to detect dragging into panel) |
| `xdata` | `float \| None` | Plot1D, Plot2D, PlotMesh — data-space x coordinate |
| `ydata` | `float \| None` | Plot1D, Plot2D, PlotMesh — data-space y coordinate |
| `ray` | `dict \| None` | Plot3D only — `{"origin": [x,y,z], "direction": [dx,dy,dz]}` |
| `line_id` | `str \| None` | Plot1D only — set when pointer is over a line, `None` otherwise |
| `dwell_ms` | `float \| None` | `pointer_settled` only — actual time the pointer held still |

### PlotBar additional fields on `pointer_down`

| Field | Type | Description |
|-------|------|-------------|
| `bar_index` | `int \| None` | which bar was clicked; `None` if click missed all bars |
| `value` | `float \| None` | bar value |
| `x_label` | `str \| None` | category label |
| `group_index` | `int \| None` | group index for grouped bars; `None` for ungrouped |

PlotBar `pointer_down` also carries `x`, `y`, `xdata`, `ydata` like other plot types, so all fields are available.

### Wheel fields

| Field | Type | Description |
|-------|------|-------------|
| `x`, `y` | `int` | pointer position at time of scroll |
| `dx`, `dy` | `float` | scroll deltas; accumulated across merged frames (matching pygfx) |

### Key fields (key_down, key_up)

| Field | Type | Description |
|-------|------|-------------|
| `key` | `str` | key name e.g. `"q"`, `"Enter"`, `"ArrowLeft"` |
| `x`, `y` | `int` | pointer position at time of keypress |

---

## Section 3: Connection API

The user-facing API on every plot and widget becomes `add_event_handler` / `remove_handler`. The internal `CallbackRegistry` engine (`connect`/`disconnect`/`fire`) is unchanged.

### Functional form

```python
# Single type
cid = plot.add_event_handler(fn, "pointer_down")

# Multiple types in one call
cid = plot.add_event_handler(fn, "pointer_down", "pointer_up")

# Wildcard — receives every event type
cid = plot.add_event_handler(fn, "*")

# pointer_settled with explicit thresholds (defaults: ms=300, delta=4)
# ms/delta are only valid when "pointer_settled" is in the types list — ValueError otherwise
cid = plot.add_event_handler(fn, "pointer_settled", ms=400, delta=5)

# Priority — lower order fires first, default 0
cid = plot.add_event_handler(fn, "pointer_move", order=-1)
```

### Decorator form

```python
@plot.add_event_handler("pointer_down")
def on_press(event):
    print(event.xdata, event.ydata)

@plot.add_event_handler("pointer_down", "pointer_up")
def on_press_release(event):
    print(event.event_type, event.button)

@plot.add_event_handler("pointer_settled", ms=400, delta=5)
def on_settled(event):
    update_spectrum(event.xdata, event.ydata)
```

### Removal

```python
# By CID (returned from add_event_handler)
plot.remove_handler(cid)

# By callback reference + specific types
plot.remove_handler(fn, "pointer_down")

# By callback reference alone — removes from all types it was registered under
plot.remove_handler(fn)
```

### Per-line filtering on Plot1D

Line handles returned by `ax.plot()` and `line.add_line()` expose their own `add_event_handler`. Internally this connects to the plot's `pointer_move`/`pointer_down` and filters by `line_id` — no new mechanism required.

```python
line = ax.plot(data)
overlay = line.add_line(data2)

@line.add_event_handler("pointer_move")
def on_hover(event):
    print(event.xdata, event.line_id)

@overlay.add_event_handler("pointer_down")
def on_pick(event):
    print("picked overlay line")
```

### What disappears

| Old | New |
|-----|-----|
| `@plot.on_click` | `@plot.add_event_handler("pointer_down")` |
| `@plot.on_changed` | `@plot.add_event_handler("pointer_move")` |
| `@plot.on_release` | `@plot.add_event_handler("pointer_settled")` |
| `@plot.on_key` / `@plot.on_key('q')` | `@plot.add_event_handler("key_down")` |
| `@line.on_hover` | `@line.add_event_handler("pointer_move")` |
| `@line.on_click` | `@line.add_event_handler("pointer_down")` |
| `plot.disconnect(cid)` | `plot.remove_handler(cid)` |
| `plot.callbacks.connect("on_click", fn)` | `plot.callbacks.connect("pointer_down", fn)` |

---

## Section 4: Architecture & Data Flow

### JS changes (`figure_esm.js`)

**New events JS must emit:**

| JS DOM event | anyplotlib event | Notes |
|-------------|-----------------|-------|
| `mouseenter` | `pointer_enter` | per panel canvas element |
| `mouseleave` | `pointer_leave` | per panel canvas element |
| `mouseup` | `pointer_up` | previously swallowed after debounce |
| `dblclick` | `double_click` | |
| `wheel` | `wheel` | `dx`/`dy` accumulated across merged frames |
| `keyup` | `key_up` | complement to existing keydown |

**Fields added to all emitted events:**
- `modifiers`: extracted from `ctrlKey`, `shiftKey`, `altKey`, `metaKey`
- `buttons`: from `event.buttons` bitmask (available on all MouseEvents)
- `button`: from `event.button` on press/release events
- `time_stamp`: set in JS before sending

**`pointer_settled` timer logic (per panel):**

```
On pointer_move:
  if panel_state.pointer_settled_ms > 0:
    clearTimeout(settled_timer)
    record settle_start_pos = current_pos
    settled_timer = setTimeout(() => {
      if distance(current_pos, settle_start_pos) <= panel_state.pointer_settled_delta:
        emit pointer_settled { ...pointer fields, dwell_ms: actual_elapsed }
    }, panel_state.pointer_settled_ms)
```

Timer is never created when `pointer_settled_ms == 0`. Cost is zero when no handler is connected.

**Key registration removed:** `registered_keys` state field is eliminated. `key_down`/`key_up` forward all key presses unconditionally (matching pygfx). Per-key filtering moves to Python-side handler wrappers if users want it.

### Python changes

**`_dispatch_event()` field mapping:**

| Old field | New field | Change |
|-----------|-----------|--------|
| `phys_x` | `xdata` | rename |
| `phys_y` | `ydata` | rename |
| `mouse_x` | `x` | rename |
| `mouse_y` | `y` | rename |
| *(absent)* | `button` | new |
| *(absent)* | `buttons` | new |
| *(absent)* | `modifiers` | new |
| *(absent)* | `time_stamp` | new |
| *(absent)* | `ray` | new (Plot3D) |
| *(absent)* | `dx`, `dy` | new (wheel) |
| *(absent)* | `dwell_ms` | new (pointer_settled) |

**`pointer_settled` configuration flow:**

When the first `pointer_settled` handler connects:
```python
plot._state["pointer_settled_ms"] = ms        # configured threshold
plot._state["pointer_settled_delta"] = delta  # configured threshold
plot._push()  # JS activates timer
```
When the last `pointer_settled` handler disconnects:
```python
plot._state["pointer_settled_ms"] = 0  # JS deactivates timer
plot._push()
```

**`CallbackRegistry` additions:**
1. Multi-type registration: `add_event_handler(fn, "a", "b")` registers `fn` under both internally; `remove_handler(fn)` removes from all registered types
2. Order-based priority: handlers stored as `(order, fn)` tuples, sorted on insert
3. Wildcard `"*"`: fires for every event type dispatched
4. `stop_propagation`: existing — `event.stop_propagation = True` in a handler halts remaining handlers

### Pause and Hold

Both are context managers implemented on `CallbackRegistry` and exposed on every plot and widget.

**Pause (suppress):**
```python
with plot.pause_events():               # suppress all types
    update_all_panels()

with plot.pause_events("pointer_move"): # suppress specific types
    do_something()
```

**Hold (buffer + flush):**
```python
with plot.hold_events():                # buffer all types, flush on exit
    do_something()

with plot.hold_events("pointer_settled"): # buffer specific types only
    do_something()
```

**Nesting:** both use a depth counter — pause/hold only fully lifts when the outermost context exits.

**Precedence:** if both are active for the same event type, pause wins — events are dropped, not buffered.

**`CallbackRegistry` internal state:**
- `_pause_types: set[str]` — event types currently suppressed
- `_pause_depth: int` — nesting depth counter
- `_hold_types: set[str]` — event types currently buffered
- `_hold_depth: int` — nesting depth counter
- `_held_events: deque[Event]` — ordered buffer of held events

`fire()` checks pause first (drop), then hold (queue), then dispatch.

---

## Section 5: Testing Plan

### Tier 1 — Pure Python, no browser

**`CallbackRegistry` unit tests:**
- Multi-type registration fires handler for both types
- Wildcard `"*"` receives every event type dispatched
- Lower `order` fires before higher; same order fires in registration order
- `remove_handler` by CID
- `remove_handler` by callback reference + types
- `remove_handler` by callback reference alone removes from all types
- `stop_propagation` halts dispatch mid-handler-list
- `pause_events()`: events dropped, handlers intact after context exit
- `hold_events()`: events queued, fire in order on exit
- Pause inside hold: paused types are dropped (not buffered)
- Nested hold: depth counter lifts only on outermost exit
- `pointer_settled` params set in panel state on first connect, cleared on last disconnect

**`Event` dataclass tests:**
- Universal fields present on every event
- `modifiers` is always a `list`, never `None`
- `time_stamp` is always set
- Plot3D events carry `ray`, not `xdata`/`ydata`
- PlotBar `pointer_down` carries bar metadata and coordinates
- `pointer_settled` carries `dwell_ms ≥` configured threshold
- `pointer_enter`/`pointer_leave` carry `buttons` (bitmask) but `button` is `None`

### Tier 2 — Playwright browser tests

One matrix per plot type (Plot1D, Plot2D, PlotMesh, Plot3D, PlotBar):

| Test | Verified |
|------|---------|
| `pointer_down` | fires on mousedown; correct `x/y`, `button=0`, `buttons=1`, `xdata/ydata` |
| `pointer_up` | fires on mouseup; `button=0`, `buttons=0` |
| `pointer_move` | fires during drag; `xdata/ydata` update correctly |
| `pointer_enter/leave` | fire when mouse crosses panel boundary |
| `double_click` | fires on dblclick; same fields as `pointer_down` |
| `wheel` | fires on scroll; `dx/dy` non-zero |
| `key_down/key_up` | fire on keypress/release; `key` field correct |
| `modifiers` | ctrl+click produces `modifiers=["ctrl"]` |
| `pointer_settled` | fires after configured ms; does NOT fire if pointer moves beyond delta |

**Plot1D-specific:**
- `pointer_move` over a line sets `line_id`; off a line sets `line_id=None`
- `pointer_down` on a line sets `line_id`
- Line handle's `add_event_handler` filters correctly — handler on `line2` does not fire when pointer is over `line1`

**`pointer_settled`-specific:**
- Does not fire when no handler connected (JS timer flag absent from panel state)
- `dwell_ms` on the event is ≥ configured `ms`
- Fires again after pointer moves and re-settles (resets correctly)
- Two panels with different `ms`/`delta` thresholds behave independently

**Pause/Hold integration:**
- `pause_events()` during drag: `pointer_move` does not reach handler
- `hold_events()` during drag: events fire in order on context exit
- Type-specific hold: `hold_events("pointer_settled")` buffers settled but fires `pointer_move` immediately

### Tier 3 — Regression

- `on_click`, `on_changed`, `on_release`, `on_key` raise `AttributeError` (old names removed)
- `event.phys_x`, `event.phys_y` raise `AttributeError` (renamed to `xdata`/`ydata`)
- All `Examples/` files run without error after event handler updates

---

## Summary of Changes

| Area | Change |
|------|--------|
| Event names | 5 renamed, 8 new added |
| Event fields | `phys_x/y` → `xdata/ydata`, `mouse_x/y` → `x/y`; add `modifiers`, `button`, `buttons`, `time_stamp`, `ray`, `dx/dy`, `dwell_ms` |
| Connection API | `add_event_handler` / `remove_handler`; multi-type, wildcard, priority |
| `pointer_settled` | Configurable `ms`/`delta` per panel; zero cost when unused |
| Pause/Hold | Context managers on every plot and widget |
| JS layer | 6 new event types forwarded; `registered_keys` removed; timer for `pointer_settled` |
| Removed | `on_click`, `on_changed`, `on_release`, `on_key`, `on_line_hover`, `on_line_click`, `disconnect()`, `registered_keys` |

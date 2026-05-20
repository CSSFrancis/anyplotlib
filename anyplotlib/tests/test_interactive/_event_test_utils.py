"""Shared helpers for event system Playwright tests."""
from __future__ import annotations

# Layout constants (match figure_esm.js)
PAD_L, PAD_R, PAD_T, PAD_B = 58, 12, 12, 42
GRID_PAD = 8


def _collect_events(page) -> None:
    """Monkey-patch model.set to accumulate all event_json payloads in window._aplAllEvents."""
    page.evaluate("""() => {
        window._aplAllEvents = [];
        const orig = window._aplModel.set.bind(window._aplModel);
        window._aplModel.set = (k, v) => {
            if (k === 'event_json') {
                try { window._aplAllEvents.push(JSON.parse(v)); } catch(_) {}
            }
            return orig(k, v);
        };
    }""")


def _get_events(page, event_type=None) -> list:
    """Return collected events, optionally filtered by event_type."""
    events = page.evaluate("() => window._aplAllEvents")
    if event_type:
        return [e for e in events if e.get("event_type") == event_type]
    return events


def _plot_center_page(fig_w: int = 400, fig_h: int = 300) -> tuple[int, int]:
    """Return page coords for the center of the plot area."""
    cx = GRID_PAD + PAD_L + (fig_w - PAD_L - PAD_R) // 2
    cy = GRID_PAD + PAD_T + (fig_h - PAD_T - PAD_B) // 2
    return cx, cy

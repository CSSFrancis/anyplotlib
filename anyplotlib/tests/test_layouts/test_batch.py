"""Tests for Figure.batch() push coalescing — the linked-view lag fix."""
from __future__ import annotations

import numpy as np
import anyplotlib as apl


def _fig3():
    fig = apl.Figure(figsize=(600, 200))
    gs = apl.GridSpec(1, 3)
    axs = [fig.add_subplot(gs[0, c]) for c in range(3)]
    px = [np.arange(16)] * 2
    plots = [a.imshow(np.zeros((16, 16, 3), dtype=np.uint8), axes=px) for a in axs]
    return fig, plots


def _count_pushes(fig):
    calls = {"n": 0}
    orig = type(fig)._push
    def counting(self, pid):
        # count only real trait writes (batch dirty-marking returns early)
        if not self._batching:
            calls["n"] += 1
        return orig(self, pid)
    type(fig)._push = counting
    return calls, lambda: setattr(type(fig), "_push", orig)


class TestBatch:
    def test_coalesces_multiple_pushes_per_panel(self):
        fig, plots = _fig3()
        calls, restore = _count_pushes(fig)
        try:
            with fig.batch():
                for p in plots:
                    p.set_data(np.ones((16, 16, 3), dtype=np.uint8))
                    p.set_title("x")           # 2nd mutation, same panel
            # 3 panels × 2 mutations each = 6 mutations → 3 pushes
            assert calls["n"] == 3, f"expected 3 coalesced pushes, got {calls['n']}"
        finally:
            restore()

    def test_without_batch_pushes_per_mutation(self):
        fig, plots = _fig3()
        calls, restore = _count_pushes(fig)
        try:
            for p in plots:
                p.set_data(np.ones((16, 16, 3), dtype=np.uint8))
                p.set_title("x")
            assert calls["n"] == 6, f"expected 6 pushes, got {calls['n']}"
        finally:
            restore()

    def test_batch_applies_state(self):
        fig, plots = _fig3()
        with fig.batch():
            plots[0].set_title("hello")
        assert plots[0]._state["title"] == "hello"
        # trait reflects the change after the block
        import json
        st = json.loads(getattr(fig, f"panel_{plots[0]._id}_json"))
        assert st["title"] == "hello"

    def test_nested_batch_is_transparent(self):
        fig, plots = _fig3()
        calls, restore = _count_pushes(fig)
        try:
            with fig.batch():
                with fig.batch():
                    plots[0].set_title("a")
                plots[1].set_title("b")
            assert calls["n"] == 2
        finally:
            restore()

    def test_3d_view_and_highlight_coalesce(self):
        fig = apl.Figure(figsize=(300, 300))
        ax = fig.add_subplot(apl.GridSpec(1, 1)[0, 0])
        v = ax.scatter3d(np.zeros(4), np.zeros(4), np.zeros(4),
                         bounds=((-1, 1),) * 3)
        calls, restore = _count_pushes(fig)
        try:
            with fig.batch():
                v.set_highlight(0.1, 0.2, 0.3)
                v.set_view(azimuth=10, elevation=20)
            assert calls["n"] == 1, f"expected 1 coalesced push, got {calls['n']}"
            assert v._state["highlight"]["x"] == 0.1
            assert v._state["azimuth"] == 10
        finally:
            restore()

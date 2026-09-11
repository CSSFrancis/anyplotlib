"""
A self-contained page inlines its data into a ``<script>`` block, and an HTML
parser ends that block at the first ``</`` in its text without caring that the
sequence sits inside a JavaScript string.  A figure title, an axis label read
from file metadata, or a binding's style string is enough to close the block
early and run whatever follows as markup, and the exported file is a top-level
document someone opens directly.  These tests pin the escaping.
"""
from __future__ import annotations

import json
import pathlib
import tempfile

import numpy as np
import anyplotlib as apl
from anyplotlib._repr_utils import script_json
from anyplotlib.embed import navigated_html

PAYLOAD = "</script><script>window.__injected = 1</script>"


class TestScriptJson:
    def test_no_script_ender_survives(self):
        text = script_json({"title": PAYLOAD, "note": "<!-- hidden -->"})
        assert "</" not in text
        assert "<!--" not in text

    def test_round_trips_through_json_loads(self):
        value = {"title": PAYLOAD, "note": "<!-- hidden -->", "n": [1, 2.5, None]}
        assert json.loads(script_json(value)) == value

    def test_ordinary_values_are_untouched(self):
        assert script_json({"a": 1}) == json.dumps({"a": 1})


def _injecting_page():
    """A figure whose title, labels and one binding style carry the payload."""
    rng = np.random.default_rng(1)
    block = rng.integers(0, 256, size=(4, 4, 8, 8)).astype(np.uint8)
    spots = np.stack([np.full(4 * 4, 3.0, dtype=np.float32),
                      np.full(4 * 4, 4.0, dtype=np.float32)])

    fig, axes = apl.subplots(1, 2, figsize=(520, 260))
    navigator = axes[0].imshow(block.sum(axis=(2, 3)).astype(np.float32), cmap="gray")
    panel = axes[1].imshow(block[0, 0], cmap="gray")
    navigator.add_widget("crosshair", cx=0, cy=0)
    panel.set_title(PAYLOAD)
    panel.set_xlabel(PAYLOAD)

    from anyplotlib.embed import Ragged
    ragged = Ragged(offsets=np.arange(0, 17, dtype=np.int32),
                    columns={"x": spots[0], "y": spots[1]},
                    nav_shape=(4, 4))
    return navigated_html(
        fig, {"cube": block, "spots": ragged},
        [{"panel_id": navigator._id, "role": "navigator"},
         {"panel_id": panel._id, "role": "driven",
          "frame": {"block": "cube", "kind": "image", "levels": [0, 255]},
          "overlays": [{"block": "spots", "kind": "circles",
                        "style": {"radius": 3, "color": "#0f0", "label": PAYLOAD}}]}])


class TestNavigatedPageIsNotInjectable:
    def test_a_payload_in_the_figure_does_not_run(self, _pw_browser, tmp_path):
        html = _injecting_page()
        path = tmp_path / "injected.html"
        path.write_text(html, encoding="utf-8")

        page = _pw_browser.new_page()
        try:
            page.goto(path.as_uri())
            page.wait_for_function("() => window._aplReady === true", timeout=20_000)
            injected = page.evaluate("() => window.__injected")
            canvases = page.evaluate(
                "() => document.querySelectorAll('#apl-host canvas').length")
        finally:
            page.close()
        assert injected is None, "the payload executed"
        assert canvases >= 3, "the figure did not mount"

    def test_a_payload_in_the_title_and_caption_is_shown_as_text(
            self, _pw_browser, tmp_path):
        rng = np.random.default_rng(2)
        block = rng.integers(0, 256, size=(4, 4, 8, 8)).astype(np.uint8)
        fig, axes = apl.subplots(1, 2, figsize=(520, 260))
        navigator = axes[0].imshow(block.sum(axis=(2, 3)).astype(np.float32))
        panel = axes[1].imshow(block[0, 0])
        navigator.add_widget("crosshair", cx=0, cy=0)
        panel.set_title(PAYLOAD)          # the script-block route
        html = navigated_html(
            fig, {"cube": block},
            [{"panel_id": navigator._id, "role": "navigator"},
             {"panel_id": panel._id, "role": "driven",
              "frame": {"block": "cube", "kind": "image"}}],
            title=PAYLOAD, caption=PAYLOAD)
        path = tmp_path / "titled.html"
        path.write_text(html, encoding="utf-8")

        page = _pw_browser.new_page()
        try:
            page.goto(path.as_uri())
            page.wait_for_function("() => window._aplReady === true", timeout=20_000)
            injected = page.evaluate("() => window.__injected")
            shown = page.evaluate(
                "() => [document.querySelector('.apl-title').textContent,"
                "       document.querySelector('.apl-caption').textContent]")
            extra = page.evaluate(
                "() => document.querySelectorAll('script').length")
        finally:
            page.close()
        assert injected is None, "the payload executed"
        assert shown == [PAYLOAD, PAYLOAD], shown
        assert extra == 1, f"{extra} script elements; the page has one"


class TestStandalonePageIsNotInjectable:
    def test_a_panel_title_does_not_close_the_script(self, _pw_browser):
        fig, ax = apl.subplots(1, 1, figsize=(320, 240))
        plot = ax.imshow(np.zeros((8, 8), dtype=np.uint8))
        plot.set_title(PAYLOAD)
        html = fig.to_html()
        assert "</script><script>window.__injected" not in html

        with tempfile.NamedTemporaryFile(suffix=".html", mode="w", encoding="utf-8",
                                         delete=False) as handle:
            handle.write(html)
            path = pathlib.Path(handle.name)
        page = _pw_browser.new_page()
        try:
            page.goto(path.as_uri())
            page.wait_for_timeout(700)
            injected = page.evaluate("() => window.__injected")
            canvases = page.evaluate("() => document.querySelectorAll('canvas').length")
        finally:
            page.close()
            path.unlink(missing_ok=True)
        assert injected is None, "the payload executed"
        assert canvases >= 3, "the figure did not mount"

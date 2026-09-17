"""
A framed figure's "Save PNG…" when the host page saves PNGs itself.

In a frame, "Save PNG…" cannot download (a sandboxed frame makes ``a.click()``
a silent no-op), so it posts the image to the parent and shows an in-figure
preview whose caption points at the browser's "Save image as…". A host with its
own Save dialog — a desktop app, whose webview may have no such menu —
announces ``{type: 'anyplotlib_host', savesPng: true}``; the figure then only
posts the image, and drops the "Save as… (choose folder)" row, since the
host's dialog already chooses the folder.
"""
from __future__ import annotations

import pathlib
import tempfile
from html import escape

import numpy as np
import pytest

import anyplotlib as apl
from anyplotlib._repr_utils import build_standalone_html

_PARENT_PAGE = """<!DOCTYPE html>
<html><head><meta charset="utf-8"/><style>html,body{margin:0;padding:0;}</style></head>
<body>
<iframe id="fig" srcdoc="__SRCDOC__" width="360" height="280" style="border:none;"></iframe>
<script>
window._saved = [];
window.addEventListener('message', (e) => {
  if (e.data && e.data.type === 'anyplotlib_export_png_result' && e.data.requestId === null) {
    window._saved.push({filename: e.data.filename, dataUrl: e.data.dataUrl});
  }
});
window._announceHost = () => document.getElementById('fig').contentWindow.postMessage(
  {type: 'anyplotlib_host', savesPng: true}, '*');
</script>
</body></html>
"""

_MENU_ROWS = """() => Array.from(document.querySelectorAll('[data-apl-menu] *'))
  .filter((element) => element.children.length === 0)
  .map((element) => element.textContent)"""

_OPEN_MENU = """() => document.querySelector(
  '[aria-label="Copy or save this figure"]').click()"""

_CLICK_SAVE_PNG = """() => Array.from(document.querySelectorAll('[data-apl-menu] *'))
  .find((element) => element.textContent === 'Save PNG…').click()"""

_PREVIEW_SHOWN = "() => document.body.innerText.includes('Save image as')"


@pytest.fixture
def framed_figure(_pw_browser):
    """Open a parent page holding a figure in an iframe; yield ``(page, frame)``."""
    fig, ax = apl.subplots(1, 1, figsize=(320, 240))
    ax.imshow(np.random.default_rng(3).random((16, 16)).astype(np.float32))
    parent = _PARENT_PAGE.replace(
        "__SRCDOC__", escape(build_standalone_html(fig, resizable=False), quote=True))
    with tempfile.NamedTemporaryFile(
            suffix=".html", mode="w", encoding="utf-8", delete=False) as handle:
        handle.write(parent)
        path = pathlib.Path(handle.name)
    page = _pw_browser.new_page()
    try:
        page.goto(path.as_uri())
        frame = next(frame for frame in page.frames if frame.parent_frame is not None)
        frame.wait_for_function(
            "() => typeof globalThis.__aplExportPNG === 'function'", timeout=15_000)
        yield page, frame
    finally:
        page.close()
        path.unlink(missing_ok=True)


def _save_png(page, frame):
    """Open the export menu, click "Save PNG…"; return the menu's rows."""
    frame.evaluate(_OPEN_MENU)
    rows = frame.evaluate(_MENU_ROWS)
    frame.evaluate(_CLICK_SAVE_PNG)
    page.wait_for_function("() => window._saved.length > 0", timeout=5_000)
    frame.wait_for_timeout(100)
    return rows


class TestHostSavesPng:
    def test_without_a_host_the_frame_shows_the_preview(self, framed_figure):
        page, frame = framed_figure
        _save_png(page, frame)
        saved = page.evaluate("() => window._saved")
        assert saved[0]["dataUrl"].startswith("data:image/png;base64,")
        assert saved[0]["filename"].endswith(".png")
        assert frame.evaluate(_PREVIEW_SHOWN)

    def test_a_host_that_saves_gets_the_image_and_no_preview(self, framed_figure):
        page, frame = framed_figure
        page.evaluate("() => window._announceHost()")
        frame.wait_for_function("() => globalThis.__aplHostSavesPng === true")
        rows = _save_png(page, frame)
        saved = page.evaluate("() => window._saved")
        assert len(saved) == 1 and saved[0]["dataUrl"].startswith("data:image/png;base64,")
        assert not frame.evaluate(_PREVIEW_SHOWN)
        # The host's own dialog chooses the folder.
        assert not any("choose folder" in (row or "") for row in rows), rows

    def test_only_the_parent_can_announce_itself(self, framed_figure):
        page, frame = framed_figure
        frame.evaluate(
            "() => window.postMessage({type: 'anyplotlib_host', savesPng: true}, '*')")
        frame.wait_for_timeout(100)
        assert frame.evaluate("() => globalThis.__aplHostSavesPng") is None
        _save_png(page, frame)
        assert frame.evaluate(_PREVIEW_SHOWN)

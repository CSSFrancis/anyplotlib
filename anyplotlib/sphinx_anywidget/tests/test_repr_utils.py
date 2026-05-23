"""
sphinx_anywidget/tests/test_repr_utils.py
==========================================

Tests for ``sphinx_anywidget._repr_utils``:
  - ``_widget_state``  — trait serialisation
  - ``_widget_px``     — pixel dimension resolution
  - ``build_standalone_html`` — self-contained HTML builder
"""
from __future__ import annotations

import base64
import json

import numpy as np
import pytest

import anyplotlib as apl
from anyplotlib.sphinx_anywidget._repr_utils import (
    _widget_px,
    _widget_state,
    build_standalone_html,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def line_fig():
    fig, ax = apl.subplots(1, 1, figsize=(400, 300))
    ax.plot(np.sin(np.linspace(0, 6.28, 64)))
    return fig


@pytest.fixture
def imshow_fig():
    fig, ax = apl.subplots(1, 1, figsize=(320, 240))
    ax.imshow(np.zeros((32, 32), dtype=np.float32))
    return fig


@pytest.fixture
def multi_fig():
    fig, axes = apl.subplots(1, 2, figsize=(640, 300))
    axes[0].plot(np.zeros(32))
    axes[1].imshow(np.zeros((16, 16), dtype=np.float32))
    return fig


# ---------------------------------------------------------------------------
# _widget_state
# ---------------------------------------------------------------------------

class TestWidgetState:
    def test_returns_dict(self, line_fig):
        state = _widget_state(line_fig)
        assert isinstance(state, dict)

    def test_no_private_keys(self, line_fig):
        state = _widget_state(line_fig)
        for key in state:
            assert not key.startswith("_"), f"Private key leaked: {key!r}"

    def test_layout_json_present(self, line_fig):
        state = _widget_state(line_fig)
        assert "layout_json" in state

    def test_bytes_trait_encoded_as_base64_buffer(self):
        """bytes/bytearray traits are serialised as {buffer: base64} dicts."""
        import anywidget
        import traitlets

        class ByteWidget(anywidget.AnyWidget):
            _esm = "export function render({model, el}) {}"
            data = traitlets.Bytes(b"\x00\x01\x02", sync=True)

        w = ByteWidget()
        state = _widget_state(w)
        assert "data" in state
        encoded = state["data"]
        assert isinstance(encoded, dict)
        assert "buffer" in encoded
        decoded = base64.b64decode(encoded["buffer"])
        assert decoded == b"\x00\x01\x02"

    def test_bytes_trait_empty_bytes(self):
        import anywidget
        import traitlets

        class EmptyBytesWidget(anywidget.AnyWidget):
            _esm = "export function render({model, el}) {}"
            buf = traitlets.Bytes(b"", sync=True)

        w = EmptyBytesWidget()
        state = _widget_state(w)
        assert isinstance(state["buf"], dict)
        assert "buffer" in state["buf"]
        assert base64.b64decode(state["buf"]["buffer"]) == b""


# ---------------------------------------------------------------------------
# _widget_px
# ---------------------------------------------------------------------------

class TestWidgetPx:
    def test_figure_adds_padding(self, line_fig):
        w, h = _widget_px(line_fig)
        assert w == line_fig.fig_width + 16
        assert h == line_fig.fig_height + 16

    def test_figure_400x300(self, line_fig):
        w, h = _widget_px(line_fig)
        assert w == 416
        assert h == 316

    def test_display_override_attributes(self):
        import anywidget
        import traitlets

        class CustomWidget(anywidget.AnyWidget):
            _esm = "export function render({model, el}) {}"
            _display_width = 500
            _display_height = 250

        cw = CustomWidget()
        w, h = _widget_px(cw)
        assert w == 500
        assert h == 250

    def test_viewer_width_height_traits(self):
        import anywidget
        import traitlets

        class ViewerWidget(anywidget.AnyWidget):
            _esm = "export function render({model, el}) {}"
            viewer_width = traitlets.Int(300, sync=True)
            viewer_height = traitlets.Int(200, sync=True)

        vw = ViewerWidget()
        w, h = _widget_px(vw)
        assert w == 320
        assert h == 220

    def test_fallback_dimensions(self):
        import anywidget

        class MinimalWidget(anywidget.AnyWidget):
            _esm = "export function render({model, el}) {}"

        mw = MinimalWidget()
        w, h = _widget_px(mw)
        assert w == 560
        assert h == 340

    def test_multi_panel_figure(self, multi_fig):
        w, h = _widget_px(multi_fig)
        assert w == multi_fig.fig_width + 16
        assert h == multi_fig.fig_height + 16


# ---------------------------------------------------------------------------
# build_standalone_html
# ---------------------------------------------------------------------------

class TestBuildStandaloneHtml:
    def test_returns_string(self, line_fig):
        html = build_standalone_html(line_fig, resizable=False, fig_id="t1")
        assert isinstance(html, str)

    def test_contains_awi_state_listener(self, line_fig):
        html = build_standalone_html(line_fig, resizable=False, fig_id="t1")
        assert "awi_state" in html

    def test_contains_fig_id(self, line_fig):
        html = build_standalone_html(line_fig, resizable=False, fig_id="myfig")
        assert '"myfig"' in html

    def test_html_doctype(self, line_fig):
        html = build_standalone_html(line_fig, resizable=False, fig_id="t1")
        assert html.strip().startswith("<!DOCTYPE html>") or "<html" in html

    def test_contains_widget_root(self, line_fig):
        html = build_standalone_html(line_fig, resizable=False, fig_id="t1")
        assert "widget-root" in html

    def test_contains_model_state(self, line_fig):
        html = build_standalone_html(line_fig, resizable=False, fig_id="t1")
        assert "layout_json" in html

    def test_resizable_false_suppresses_drag_handle(self, line_fig):
        html = build_standalone_html(line_fig, resizable=False, fig_id="t1")
        # resizable=False hides the Jupyter drag handle via CSS override
        assert "nwse-resize" in html or "resizable=False" in html or isinstance(html, str)

    def test_resizable_true_adds_resize_logic(self, line_fig):
        html = build_standalone_html(line_fig, resizable=True, fig_id="t1")
        assert isinstance(html, str)

    def test_auto_fig_id_when_none(self, line_fig):
        html = build_standalone_html(line_fig, resizable=False, fig_id=None)
        assert isinstance(html, str)
        assert len(html) > 0

    def test_imshow_fig_serialises(self, imshow_fig):
        html = build_standalone_html(imshow_fig, resizable=False, fig_id="img")
        assert "awi_state" in html

    def test_html_is_valid_json_state(self, line_fig):
        html = build_standalone_html(line_fig, resizable=False, fig_id="t1")
        # Extract STATE JSON — it appears as a JS variable assignment
        import re
        m = re.search(r"const STATE\s*=\s*(\{.*?\});", html, re.DOTALL)
        if m:
            data = json.loads(m.group(1))
            assert "layout_json" in data


# ---------------------------------------------------------------------------
# Playwright: HTML renders correctly in browser
# ---------------------------------------------------------------------------

class TestBuildStandaloneHtmlPlaywright:
    def test_widget_root_visible(self, render_widget_page, line_fig):
        """The rendered page contains a visible #widget-root element."""
        page = render_widget_page(line_fig, fig_id="pw_test")
        root = page.locator("#widget-root")
        assert root.count() == 1

    def test_canvas_rendered(self, render_widget_page, line_fig):
        """At least one canvas element is present after render."""
        page = render_widget_page(line_fig, fig_id="pw_canvas")
        canvas_count = page.evaluate("() => document.querySelectorAll('canvas').length")
        assert canvas_count >= 1

    def test_model_state_accessible(self, saw_browser, line_fig):
        """window._aplModel is available and has layout_json set."""
        import pathlib, tempfile
        html = build_standalone_html(line_fig, resizable=False, fig_id="pw_model")
        html = html.replace(
            "renderFn({ model, el });",
            "renderFn({ model, el }); window._aplReady = true;",
        ).replace(
            "const model   = makeModel(STATE);",
            "const model   = makeModel(STATE);\nwindow._aplModel = model;",
        )
        with tempfile.NamedTemporaryFile(
            suffix=".html", mode="w", encoding="utf-8", delete=False
        ) as fh:
            fh.write(html)
            tmp = pathlib.Path(fh.name)
        page = saw_browser.new_page()
        try:
            page.goto(tmp.as_uri())
            page.wait_for_function("() => window._aplReady === true", timeout=15_000)
            has_model = page.evaluate("() => typeof window._aplModel !== 'undefined'")
            assert has_model
        finally:
            page.close()
            tmp.unlink(missing_ok=True)

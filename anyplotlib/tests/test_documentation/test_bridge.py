"""
tests/test_documentation/test_bridge.py
========================================

Browser-based end-to-end tests for the Pyodide live-documentation bridge.

Requires Playwright (skipped automatically when not installed).  Two tiers:

Tier 2 -- **iframe postMessage tests**
    Open a standalone figure HTML as a top-level page, fire ``awi_state``
    postMessages directly, and assert the model updates.
    No Pyodide, no HTTP server.

Tier 3 -- **Full bridge mock-boot tests**
    Build a ``parent.html`` page that includes the real ``anywidget_bridge.js``
    but defines ``window.loadPyodide`` as a lightweight mock.  The mock
    exercises the complete JS boot sequence without downloading Pyodide WASM.
    Pages are served over a local stdlib HTTP server.

No-browser unit tests for ``_push()`` / ``_push_layout()`` live in
``test_push_hook.py``.
"""

from __future__ import annotations

import json
import pathlib
import socket
import threading
from http.server import HTTPServer, SimpleHTTPRequestHandler
from html import escape as _html_escape
from typing import Generator

import numpy as np
import pytest

import anyplotlib as apl
from anyplotlib._repr_utils import build_standalone_html

pytest.importorskip("playwright", reason="playwright not installed")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_BRIDGE_JS = (
    pathlib.Path(__file__).parent.parent.parent
    / "sphinx_anywidget" / "static" / "anywidget_bridge.js"
)

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _capture_fig_state(fig) -> dict:
    """Return {trait_name: json_string} for layout + every panel trait."""
    fig._push_layout()
    for pid in list(fig._plots_map):
        fig._push(pid)
    captured = {"layout_json": fig.layout_json}
    for tname in fig.trait_names():
        if tname.startswith("panel_") and tname.endswith("_json"):
            captured[tname] = getattr(fig, tname)
    return captured


def _patched_iframe_html(fig, fig_id: str) -> str:
    """Return standalone HTML instrumented for Playwright.

    Adds ``window._aplModel`` and ``window._aplReady`` sentinels.
    """
    html = build_standalone_html(fig, resizable=False, fig_id=fig_id)
    html = html.replace(
        "const model   = makeModel(STATE);",
        "const model   = makeModel(STATE);\nwindow._aplModel = model;",
    )
    html = html.replace(
        "renderFn({ model, el });",
        "renderFn({ model, el }); window._aplReady = true;",
    )
    return html


def _rafter(page) -> None:
    page.evaluate("() => new Promise(r => requestAnimationFrame(r))")


def _click_and_wait_boot(page, timeout: int = 15_000) -> None:
    """Click the activate button and wait until data-state reaches 'active'."""
    page.wait_for_function(
        "() => !!document.querySelector('button.awi-activate-btn')",
        timeout=timeout,
    )
    page.click("button.awi-activate-btn")
    page.wait_for_function(
        """() => {
            const btn = document.querySelector('button.awi-activate-btn');
            return btn && btn.dataset.state === 'active';
        }""",
        timeout=timeout,
    )


def _wait_for_iframe_model(page, fig_id: str, panel_id: str,
                            timeout: int = 10_000) -> None:
    """Block until the iframe's model has a non-empty panel JSON."""
    js = (
        "() => {"
        f"  const iframe = document.querySelector('iframe[data-awi-fig=\"{fig_id}\"]');"
        "  if (!iframe || !iframe.contentWindow) return false;"
        "  const mdl = iframe.contentWindow._aplModel;"
        "  if (!mdl) return false;"
        f"  const raw = mdl.get('panel_{panel_id}_json');"
        "  return typeof raw === 'string' && raw.length > 10;"
        "}"
    )
    page.wait_for_function(js, timeout=timeout)


# ---------------------------------------------------------------------------
# HTTP-server fixture  (module-scoped)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def http_server(tmp_path_factory) -> Generator:
    """Serve a temp directory over HTTP; yield (base_url, base_dir)."""
    base_dir = tmp_path_factory.mktemp("bridge_server")

    class _SilentHandler(SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(base_dir), **kw)

        def log_message(self, *_):
            pass

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]

    srv = HTTPServer(("127.0.0.1", port), _SilentHandler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{port}", base_dir
    srv.shutdown()


# ---------------------------------------------------------------------------
# Parent-page builder  (Tier 3)
# ---------------------------------------------------------------------------

def _build_parent_page(
    fig,
    fig_id: str,
    *,
    base_dir: pathlib.Path,
    python_src: str = "",
) -> pathlib.Path:
    """Write a complete mock-Pyodide parent page to *base_dir*."""
    # Iframe HTML + real bridge script
    (base_dir / f"{fig_id}.html").write_text(
        _patched_iframe_html(fig, fig_id), encoding="utf-8"
    )
    (base_dir / "anywidget_bridge.js").write_text(
        _BRIDGE_JS.read_text(encoding="utf-8"), encoding="utf-8"
    )

    # Capture real figure state
    fig_state = _capture_fig_state(fig)
    layout_value = fig_state.get("layout_json", "{}")
    panel_entries = [
        {"key": k, "value": v}
        for k, v in fig_state.items()
        if k.startswith("panel_")
    ]
    fig_w, fig_h = int(fig.fig_width), int(fig.fig_height)
    if not python_src:
        python_src = "# mock example\n"
    data_src_attr = _html_escape(json.dumps(python_src), quote=True)

    # Build mock loadPyodide JS as a list of lines to avoid quoting hell
    mock_lines = [
        "<script>",
        f"window._MOCK_FIG_ID  = {json.dumps(fig_id)};",
        f"window._MOCK_LAYOUT  = {json.dumps(layout_value)};",
        f"window._MOCK_PANELS  = {json.dumps(panel_entries)};",
        "window._APL_BOOT_STEPS = [];",
        "window.loadPyodide = async function() {",
        "  window._APL_BOOT_STEPS.push('loadPyodide');",
        "  return {",
        "    loadPackage: async function(p) {",
        "      window._APL_BOOT_STEPS.push('loadPackage:' + JSON.stringify(p));",
        "    },",
        "    runPythonAsync: async function(src) {",
        "      if (src.includes('micropip') && src.includes('traitlets')) {",
        "        window._APL_BOOT_STEPS.push('micropip_install'); return;",
        "      }",
        "      if (src.includes('_AnyWidget') && src.includes('sys.modules')) {",
        "        window._APL_BOOT_STEPS.push('stub_anywidget');",
        "        window._APL_REGISTRY = {}; return;",
        "      }",
        "      /* _fig_ids BEFORE _patched_init -- bridge step 9 has both */",
        "      if (src.includes('_fig_ids')) {",
        "        window._APL_BOOT_STEPS.push('run_example');",
        "        const fid = window._MOCK_FIG_ID;",
        "        if (window._anywidgetPush) {",
        "          window._anywidgetPush(fid, 'layout_json', window._MOCK_LAYOUT);",
        "          for (const e of window._MOCK_PANELS) {",
        "            window._anywidgetPush(fid, e.key, e.value);",
        "          }",
        "        }",
        "        window._APL_FIGS_PUSHED = true; return;",
        "      }",
        "      if (src.includes('_patched_init') || src.includes('_anywidget_fig_id')) {",
        "        window._APL_BOOT_STEPS.push('install_monkey_patch');",
        "        window._anywidgetPush = function(figId, key, value) {",
        "          const el = document.querySelector('iframe[data-awi-fig=\"' + figId + '\"]');",
        "          if (el && el.contentWindow) {",
        "            el.contentWindow.postMessage({type:'awi_state',key,value}, '*');",
        "          }",
        "        }; return;",
        "      }",
        "      window._APL_BOOT_STEPS.push('runPythonAsync:other');",
        "    }",
        "  };",
        "};",
        "</script>",
    ]
    mock_js = "\n".join(mock_lines)

    parent_html = (
        "<!DOCTYPE html>\n<html><head><meta charset=\"utf-8\"/>\n"
        f"<title>bridge test - {fig_id}</title>\n"
        f"{mock_js}\n"
        "<script src=\"anywidget_bridge.js\"></script>\n"
        "</head>\n"
        "<body style=\"margin:0;padding:24px;background:#1e1e2e;\">\n"
        "<div style=\"display:block;text-align:center;line-height:0;margin:12px 0;\">\n"
        f"  <div id=\"fig-wrap-{fig_id}\" class=\"awi-fig-wrap\" data-awi-fig=\"{fig_id}\"\n"
        f"       style=\"display:inline-block;overflow:hidden;position:relative;\n"
        f"              width:{fig_w}px;height:{fig_h}px;\">\n"
        f"    <iframe src=\"{fig_id}.html\" data-awi-fig=\"{fig_id}\" id=\"iframe-{fig_id}\"\n"
        f"            frameborder=\"0\" scrolling=\"no\"\n"
        f"            style=\"width:{fig_w}px;height:{fig_h}px;border:none;\n"
        "                   overflow:hidden;display:block;\"></iframe>\n"
        f"    <div class=\"awi-badge\" data-awi-badge=\"{fig_id}\">\n"
        f"      <button class=\"awi-badge-icon awi-activate-btn\"\n"
        f"              data-awi-fig=\"{fig_id}\"\n"
        "              title=\"Make interactive\">&#x26A1;</button>\n"
        "    </div>\n"
        "  </div>\n"
        "</div>\n"
        f"<script type=\"text/x-python\" data-fig-id=\"{fig_id}\" data-fig-index=\"0\"\n"
        f"        data-src-file=\"test_e2e\" data-src=\"{data_src_attr}\"></script>\n"
        "</body></html>"
    )

    parent_path = base_dir / f"{fig_id}_parent.html"
    parent_path.write_text(parent_html, encoding="utf-8")
    return parent_path


# =============================================================================
# Tier 2 -- iframe postMessage tests  (browser only, no HTTP server)
# =============================================================================

class TestIframeMessaging:
    """Verify the awi_state postMessage protocol via the standalone iframe.

    The ``interact_page`` fixture opens the figure HTML as a top-level page
    (``window.parent === window``), so outbound awi_event forwarding is
    disabled.  Tests focus on the *inbound* direction: awi_state updates the
    model.
    """

    def _open_fig(self, interact_page):
        fig, ax = apl.subplots(1, 1, figsize=(400, 300))
        ax.plot(np.sin(np.linspace(0, 2 * np.pi, 64)), color="#4fc3f7")
        panel_id = list(fig._plots_map.keys())[0]
        plot = list(fig._plots_map.values())[0]
        page = interact_page(fig)
        return fig, plot, panel_id, page

    def test_awi_state_updates_model_key(self, interact_page):
        """Posting {type:'awi_state', key, value} updates the model."""
        fig, plot, panel_id, page = self._open_fig(interact_page)
        raw = page.evaluate(f"() => window._aplModel.get('panel_{panel_id}_json')")
        assert raw is not None
        curr = json.loads(raw)
        curr["__sentinel__"] = "hello"
        new_json = json.dumps(curr)
        page.evaluate(
            "() => window.postMessage("
            + json.dumps({"type": "awi_state",
                          "key": f"panel_{panel_id}_json",
                          "value": new_json})
            + ", '*')"
        )
        _rafter(page)
        updated = json.loads(
            page.evaluate(f"() => window._aplModel.get('panel_{panel_id}_json')")
        )
        assert updated.get("__sentinel__") == "hello"

    def test_no_echo_in_standalone_mode(self, interact_page):
        """No awi_event is echoed back in standalone mode (FIG_ID is null)."""
        fig, plot, panel_id, page = self._open_fig(interact_page)
        raw = json.loads(
            page.evaluate(f"() => window._aplModel.get('panel_{panel_id}_json')")
        )
        raw["__flag__"] = 1
        new_json = json.dumps(raw)
        page.evaluate(
            "() => {"
            "  window._aplEventsSeen = 0;"
            "  window.addEventListener('message', (e) => {"
            "    if (e.data && e.data.type === 'awi_event') window._aplEventsSeen++;"
            "  });"
            "}"
        )
        page.evaluate(
            "() => window.postMessage("
            + json.dumps({"type": "awi_state",
                          "key": f"panel_{panel_id}_json",
                          "value": new_json})
            + ", '*')"
        )
        _rafter(page)
        assert page.evaluate("() => window._aplEventsSeen") == 0

    def test_awi_state_fires_change_listeners(self, interact_page):
        """Posting awi_state triggers on('change:...') listeners."""
        fig, plot, panel_id, page = self._open_fig(interact_page)
        page.evaluate(
            f"() => {{"
            f"  window._aplChangeCount = 0;"
            f"  window._aplModel.on('change:panel_{panel_id}_json',"
            f"    () => window._aplChangeCount++);"
            f"}}"
        )
        raw = json.loads(
            page.evaluate(f"() => window._aplModel.get('panel_{panel_id}_json')")
        )
        raw["__change__"] = 1
        new_json = json.dumps(raw)
        page.evaluate(
            "() => window.postMessage("
            + json.dumps({"type": "awi_state",
                          "key": f"panel_{panel_id}_json",
                          "value": new_json})
            + ", '*')"
        )
        _rafter(page)
        assert page.evaluate("() => window._aplChangeCount") >= 1

    def test_layout_json_push_updates_model(self, interact_page):
        """layout_json can be updated via awi_state."""
        fig, plot, panel_id, page = self._open_fig(interact_page)
        layout = json.loads(
            page.evaluate("() => window._aplModel.get('layout_json') || '{}'")
        )
        layout["__layout_sentinel__"] = "bridge_test"
        new_json = json.dumps(layout)
        page.evaluate(
            "() => window.postMessage("
            + json.dumps({"type": "awi_state", "key": "layout_json", "value": new_json})
            + ", '*')"
        )
        _rafter(page)
        updated = json.loads(
            page.evaluate("() => window._aplModel.get('layout_json') || '{}'")
        )
        assert updated.get("__layout_sentinel__") == "bridge_test"


# =============================================================================
# Tier 3 -- Full bridge mock-boot tests  (HTTP server + mock Pyodide)
# =============================================================================

class TestFullBridgeBoot:
    """Boot anywidget_bridge.js end-to-end via a mock loadPyodide.

    Each test builds a parent HTML page and serves it from the shared
    ``http_server`` fixture.  All Pyodide network I/O is replaced by the JS
    mock so tests complete in milliseconds.
    """

    def _open(self, browser, base_url, parent_path, timeout=15_000):
        url = f"{base_url}/{parent_path.name}"
        page = browser.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=timeout)
        return page

    def _basic_fig(self):
        fig, ax = apl.subplots(1, 1, figsize=(400, 300))
        ax.plot(np.sin(np.linspace(0, 2 * np.pi, 64)), color="#50fa7b")
        panel_id = list(fig._plots_map.keys())[0]
        return fig, panel_id

    def test_button_appears_when_iframe_present(self, http_server, _pw_browser):
        """The activate button is injected on any page with a data-awi-fig iframe."""
        base_url, base_dir = http_server
        fig, _ = self._basic_fig()
        parent = _build_parent_page(fig, "btn_test_001", base_dir=base_dir)
        page = self._open(_pw_browser, base_url, parent)
        page.wait_for_function(
            "() => !!document.querySelector('button.awi-activate-btn')",
            timeout=5_000,
        )
        tooltip = page.evaluate(
            "() => document.querySelector('button.awi-activate-btn').title"
        )
        assert "interactive" in tooltip.lower()
        page.close()

    def test_boot_completes_all_mock_steps(self, http_server, _pw_browser):
        """Clicking the button runs through all expected mock Pyodide boot steps."""
        base_url, base_dir = http_server
        fig, _ = self._basic_fig()
        parent = _build_parent_page(fig, "boot_test_001", base_dir=base_dir)
        page = self._open(_pw_browser, base_url, parent)
        _click_and_wait_boot(page)
        steps = page.evaluate("() => window._APL_BOOT_STEPS")
        for step in ("loadPyodide", "micropip_install", "stub_anywidget",
                     "install_monkey_patch", "run_example"):
            assert step in steps, f"Step {step!r} missing; got {steps}"
        page.close()

    def test_anywidgetPush_is_function_after_boot(self, http_server, _pw_browser):
        """window._anywidgetPush must be a function after the push-hook step."""
        base_url, base_dir = http_server
        fig, _ = self._basic_fig()
        parent = _build_parent_page(fig, "apush_test_001", base_dir=base_dir)
        page = self._open(_pw_browser, base_url, parent)
        _click_and_wait_boot(page)
        assert page.evaluate(
            "() => typeof window._anywidgetPush === 'function'"
        ), "window._anywidgetPush not installed"
        page.close()

    def test_state_pushed_into_iframe_model(self, http_server, _pw_browser):
        """After boot the iframe's model contains the figure's panel JSON."""
        base_url, base_dir = http_server
        fig, panel_id = self._basic_fig()
        expected = fig._plots_map[panel_id].to_state_dict()
        parent = _build_parent_page(fig, "state_push_001", base_dir=base_dir)
        page = self._open(_pw_browser, base_url, parent)
        _click_and_wait_boot(page)
        _wait_for_iframe_model(page, "state_push_001", panel_id)
        raw = page.evaluate(
            "() => {"
            "  const el = document.querySelector('iframe[data-awi-fig=\"state_push_001\"]');"
            f"  return el && el.contentWindow ? el.contentWindow._aplModel.get('panel_{panel_id}_json') : null;"
            "}"
        )
        assert raw is not None, "panel JSON not delivered to iframe model"
        assert json.loads(raw).get("kind") == expected.get("kind")
        page.close()

    def test_layout_json_pushed_into_iframe(self, http_server, _pw_browser):
        """layout_json is delivered to the iframe model."""
        base_url, base_dir = http_server
        fig, _ = self._basic_fig()
        parent = _build_parent_page(fig, "layout_push_001", base_dir=base_dir)
        page = self._open(_pw_browser, base_url, parent)
        _click_and_wait_boot(page)
        page.wait_for_function(
            "() => {"
            "  const el = document.querySelector('iframe[data-awi-fig=\"layout_push_001\"]');"
            "  if (!el || !el.contentWindow) return false;"
            "  const mdl = el.contentWindow._aplModel;"
            "  if (!mdl) return false;"
            "  const raw = mdl.get('layout_json');"
            "  return typeof raw === 'string' && raw.length > 10;"
            "}",
            timeout=8_000,
        )
        raw = page.evaluate(
            "() => {"
            "  const el = document.querySelector('iframe[data-awi-fig=\"layout_push_001\"]');"
            "  return el.contentWindow._aplModel.get('layout_json');"
            "}"
        )
        assert raw is not None
        assert "panel_specs" in json.loads(raw)
        page.close()

    def test_event_message_forwarded_to_parent(self, http_server, _pw_browser):
        """awi_event messages from the iframe arrive at the parent window."""
        base_url, base_dir = http_server
        fig, panel_id = self._basic_fig()
        parent = _build_parent_page(fig, "event_fwd_001", base_dir=base_dir)
        page = self._open(_pw_browser, base_url, parent)
        _click_and_wait_boot(page)
        page.evaluate(
            "() => {"
            "  window._aplReceivedEvents = [];"
            "  window.addEventListener('message', (e) => {"
            "    if (e.data && e.data.type === 'awi_event')"
            "      window._aplReceivedEvents.push(e.data);"
            "  });"
            "}"
        )
        fake_event = json.dumps({
            "event_type": "on_release", "panel_id": panel_id,
            "widget_id": "w_fake", "x": 42.0,
        })
        page.evaluate(
            "() => window.postMessage("
            + json.dumps({"type": "awi_event",
                          "figId": "event_fwd_001",
                          "data": fake_event})
            + ", '*')"
        )
        _rafter(page)
        events = page.evaluate("() => window._aplReceivedEvents")
        assert len(events) >= 1, "No awi_event reached the parent message bus"
        assert events[0]["figId"] == "event_fwd_001"
        page.close()

    def test_multiple_panels_all_receive_state(self, http_server, _pw_browser):
        """All panels in a multi-panel figure have their state pushed."""
        base_url, base_dir = http_server
        fig, axes = apl.subplots(1, 2, figsize=(700, 300))
        axes[0].plot(np.zeros(32))
        axes[1].plot(np.ones(32) * 0.5)
        panel_ids = list(fig._plots_map.keys())
        assert len(panel_ids) == 2
        parent = _build_parent_page(fig, "multi_panel_001", base_dir=base_dir)
        page = self._open(_pw_browser, base_url, parent)
        _click_and_wait_boot(page)
        for pid in panel_ids:
            _wait_for_iframe_model(page, "multi_panel_001", pid)
        for pid in panel_ids:
            raw = page.evaluate(
                "() => {"
                "  const el = document.querySelector('iframe[data-awi-fig=\"multi_panel_001\"]');"
                f"  return el && el.contentWindow ? el.contentWindow._aplModel.get('panel_{pid}_json') : null;"
                "}"
            )
            assert raw is not None, f"Panel {pid!r} state not pushed"
        page.close()

    def test_button_shows_error_on_boot_failure(self, http_server, _pw_browser):
        """If Pyodide boot fails the button switches to the error state."""
        base_url, base_dir = http_server
        fig, _ = self._basic_fig()
        parent = _build_parent_page(fig, "error_test_001", base_dir=base_dir)
        html = (base_dir / "error_test_001_parent.html").read_text(encoding="utf-8")
        # Patch mock to throw immediately on loadPyodide
        html = html.replace(
            "window.loadPyodide = async function() {",
            "window.loadPyodide = async function() { throw new Error('mock boot failure'); //",
        )
        (base_dir / "error_test_001_parent.html").write_text(html, encoding="utf-8")
        page = self._open(_pw_browser, base_url, parent)
        page.wait_for_function(
            "() => !!document.querySelector('button.awi-activate-btn')",
            timeout=5_000,
        )
        page.click("button.awi-activate-btn")
        page.wait_for_function(
            "() => {"
            "  const btn = document.querySelector('button.awi-activate-btn');"
            "  return btn && btn.dataset.state === 'error';"
            "}",
            timeout=10_000,
        )
        label = page.evaluate(
            "() => document.querySelector('button.awi-activate-btn').title"
        )
        assert "mock boot failure" in label
        page.close()

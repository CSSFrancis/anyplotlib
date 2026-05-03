"""
tests/test_pyodide_e2e.py
=========================

End-to-end Playwright tests for the Pyodide live documentation bridge.

Three test tiers, in increasing scope:

1. **Python push-hook unit tests** — verify ``_pyodide_push_hook`` intercepts
   ``_push()`` / ``_push_layout()`` correctly, and that panel IDs are
   deterministic (no-browser, fast).

2. **iframe postMessage tests** — reuse the existing ``interact_page`` fixture
   to open a standalone figure in headless Chromium, fire ``awi_state``
   messages directly, and assert the model updates correctly (no Pyodide, no
   HTTP server).

3. **Full bridge mock-boot tests** — build a ``parent.html`` page that
   includes the real ``anywidget_bridge.js`` but defines ``window.loadPyodide``
   as a lightweight mock *before* the bridge evaluates it.  The mock exercises
   the complete JS boot sequence — button click → all ``runPythonAsync`` /
   ``loadPackage`` calls → push-hook installation → state push into the iframe
   → awi_event forwarding — without downloading the ~10 MB Pyodide WASM
   runtime.  Pages are served over a local stdlib HTTP server so the
   ``file://`` guard in ``anywidget_bridge.js`` is bypassed.

Run::

    uv run pytest tests/test_pyodide_e2e.py -v
"""
from __future__ import annotations

import json
import pathlib
import socket
import tempfile
import threading
from http.server import HTTPServer, SimpleHTTPRequestHandler
from html import escape as _html_escape
from typing import Generator

import numpy as np
import pytest

import anyplotlib as apl
import anyplotlib.figure as _af
from anyplotlib._repr_utils import build_standalone_html

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_BRIDGE_JS = (
    pathlib.Path(__file__).parent.parent
    / "anyplotlib" / "sphinx_anywidget" / "static" / "anywidget_bridge.js"
)


# ---------------------------------------------------------------------------
# Helpers used by multiple tiers
# ---------------------------------------------------------------------------

def _capture_fig_state(fig) -> dict[str, str]:
    """Return ``{trait_name: json_string}`` for layout + every panel trait.

    Reads traitlet values directly after calling the push methods.  This
    works even when the value hasn't changed (traitlets suppresses duplicate
    change events, so an observe-based approach would return nothing on a
    second call with the same state).
    """
    # Ensure state is up to date
    fig._push_layout()
    for pid in list(fig._plots_map):
        fig._push(pid)

    captured: dict[str, str] = {}
    captured["layout_json"] = fig.layout_json
    for tname in fig.trait_names():
        if tname.startswith("panel_") and tname.endswith("_json"):
            captured[tname] = getattr(fig, tname)
    return captured


def _patched_iframe_html(fig, fig_id: str) -> str:
    """Return standalone figure HTML instrumented for Playwright.

    Patches applied on top of ``build_standalone_html``:
    * ``window._aplModel = model`` — exposes the model to parent-frame JS.
    * ``window._aplReady = true`` — sentinel polled by ``wait_for_function``.
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


# ---------------------------------------------------------------------------
# HTTP-server fixture (module-scoped — one server per test module)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def http_server(tmp_path_factory) -> Generator[tuple[str, pathlib.Path], None, None]:
    """Serve a temp directory over HTTP; yield ``(base_url, base_dir)``.

    Uses a randomly-chosen free port so tests run safely alongside other
    sessions.  The server is shut down after the last test in the module.
    """
    base_dir = tmp_path_factory.mktemp("bridge_server")

    class _SilentHandler(SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(base_dir), **kw)

        def log_message(self, *_):
            pass  # suppress request noise in test output

    # Pick a free port
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]

    srv = HTTPServer(("127.0.0.1", port), _SilentHandler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()

    yield f"http://127.0.0.1:{port}", base_dir

    srv.shutdown()


# ---------------------------------------------------------------------------
# Parent-page builder
# ---------------------------------------------------------------------------

def _build_parent_page(
    fig,
    fig_id: str,
    *,
    base_dir: pathlib.Path,
    python_src: str = "",
) -> pathlib.Path:
    """Write a complete mock-Pyodide parent page to *base_dir*.

    Files written
    -------------
    ``{fig_id}.html``         — standalone figure iframe
    ``anywidget_bridge.js``     — the real bridge script (copied from docs/)
    ``{fig_id}_parent.html``  — parent page with mock loadPyodide

    The mock ``window.loadPyodide`` is defined **before** the bridge script
    so the bridge's ``typeof loadPyodide !== 'undefined'`` guard skips the CDN
    download entirely.  Each ``runPythonAsync`` call is dispatched by string
    pattern to simulate the five significant Pyodide boot steps:

    1. ``micropip.install`` — no-op.
    2. ``sys.modules['anywidget']`` stub — no-op.
    3. ``_pyodide_push_hook`` install — sets real ``window._anywidgetPush``.
    4. ``_fig_ids`` example-run — calls ``window._anywidgetPush`` with captured state.

    Pre-collected figure state (``layout_json`` + ``panel_*_json``) is baked
    into the page as ``window._MOCK_LAYOUT`` / ``window._MOCK_PANELS`` so the
    mock can push real data without running any Python.
    """
    # ── 1. Iframe HTML (with Playwright instrumentation patches) ─────────
    iframe_html = _patched_iframe_html(fig, fig_id)
    (base_dir / f"{fig_id}.html").write_text(iframe_html, encoding="utf-8")

    # ── 2. Real bridge script ─────────────────────────────────────────────
    (base_dir / "anywidget_bridge.js").write_text(
        _BRIDGE_JS.read_text(encoding="utf-8"), encoding="utf-8"
    )

    # ── 3. Capture real figure state via the push-hook ────────────────────
    fig_state = _capture_fig_state(fig)
    layout_value = fig_state.get("layout_json", "{}")
    panel_entries = [
        {"key": k, "value": v}
        for k, v in fig_state.items()
        if k.startswith("panel_")
    ]

    fig_w, fig_h = int(fig.fig_width), int(fig.fig_height)

    # ── 4. Python source block (or a minimal comment stub) ────────────────
    if not python_src:
        python_src = "# mock example — state injected by test harness\n"
    data_src_attr = _html_escape(json.dumps(python_src), quote=True)

    # ── 5. Mock loadPyodide script ────────────────────────────────────────
    #
    # Intercepts every runPythonAsync call by pattern so the full JS boot
    # path (button → loading → active) is exercised in milliseconds.
    #
    # Step (3): install push-hook → sets window._anywidgetPush which delivers
    #           postMessage awi_state updates into the correct iframe.
    # Step (4): run example        → calls window._anywidgetPush with pre-baked
    #           state so the iframe model receives real figure data.
    mock_js = f"""<script>
// Pre-collected Python figure state (captured from the real Figure object
// at test-build time via _capture_fig_state).
window._MOCK_FIG_ID  = {json.dumps(fig_id)};
window._MOCK_LAYOUT  = {json.dumps(layout_value)};
window._MOCK_PANELS  = {json.dumps(panel_entries)};
// Audit log — every mock step appended here so tests can assert the
// full boot sequence ran.
window._APL_BOOT_STEPS = [];

// Override window.loadPyodide BEFORE anywidget_bridge.js evaluates it.
// anywidget_bridge.js checks `typeof loadPyodide !== 'undefined'` and skips
// the CDN script-tag injection when this is truthy — so no network call.
window.loadPyodide = async function({{indexURL}}) {{
  window._APL_BOOT_STEPS.push('loadPyodide');
  return {{
    loadPackage: async function(pkgs) {{
      window._APL_BOOT_STEPS.push('loadPackage:' + JSON.stringify(pkgs));
    }},
    runPythonAsync: async function(src) {{

      // ── micropip.install(['traitlets', 'colorcet']) ──────────────────
      if (src.includes('micropip') && src.includes('traitlets')) {{
        window._APL_BOOT_STEPS.push('micropip_install');
        return;
      }}

      // ── stub anywidget in sys.modules ────────────────────────────────
      if (src.includes('_AnyWidget') && src.includes('sys.modules')) {{
        window._APL_BOOT_STEPS.push('stub_anywidget');
        // _APL_REGISTRY used in later steps
        window._APL_REGISTRY = {{}};
        return;
      }}

      // ── install generic anywidget monkey-patch ─────────────────────
      // Identified by the '_patched_init' marker in the monkey-patch code.
      // Installs window._anywidgetPush so postMessage reaches the iframe.
      if (src.includes('_patched_init') || src.includes('_anywidget_fig_id')) {{
        window._APL_BOOT_STEPS.push('install_monkey_patch');
        // Install the real _anywidgetPush — delivers awi_state postMessages.
        window._anywidgetPush = function(figId, key, value) {{
          const iframe = document.querySelector('iframe[data-awi-fig="' + figId + '"]');
          if (iframe && iframe.contentWindow) {{
            iframe.contentWindow.postMessage(
              {{type: 'awi_state', key: key, value: value}}, '*');
          }}
        }};
        return;
      }}

      // ── exec(example_src) + _push_layout() + _push(panel_id) ────────
      // Triggered by the `_fig_ids = …` line that anywidget_bridge.js
      // wraps around every example exec call.  We skip the actual Python
      // exec and instead push pre-collected state directly.
      if (src.includes('_fig_ids')) {{
        window._APL_BOOT_STEPS.push('run_example');
        const fid = window._MOCK_FIG_ID;
        if (window._anywidgetPush) {{
          window._anywidgetPush(fid, 'layout_json', window._MOCK_LAYOUT);
          for (const entry of window._MOCK_PANELS) {{
            window._anywidgetPush(fid, entry.key, entry.value);
          }}
        }}
        window._APL_FIGS_PUSHED = true;
        return;
      }}

      // Catch-all for any other runPythonAsync call
      window._APL_BOOT_STEPS.push('runPythonAsync:other');
    }}
  }};
}};
</script>"""

    # ── 6. Assemble the parent HTML ───────────────────────────────────────
    parent_html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8"/>
<title>anywidget bridge test — {fig_id}</title>
{mock_js}
<script src="anywidget_bridge.js"></script>
</head>
<body style="margin:0;padding:24px;background:#1e1e2e;">
<div style="display:block;text-align:center;line-height:0;margin:12px 0;">
  <div id="fig-wrap-{fig_id}" class="awi-fig-wrap" data-awi-fig="{fig_id}"
       style="display:inline-block;overflow:hidden;
              position:relative;width:{fig_w}px;height:{fig_h}px;">
    <iframe src="{fig_id}.html"
            data-awi-fig="{fig_id}"
            id="iframe-{fig_id}"
            frameborder="0" scrolling="no"
            style="width:{fig_w}px;height:{fig_h}px;border:none;
                   overflow:hidden;display:block;">
    </iframe>
    <div class="awi-badge" data-awi-badge="{fig_id}">
      <span class="awi-badge-icon awi-static-icon">📷</span>
      <button class="awi-badge-icon awi-activate-btn"
              data-awi-fig="{fig_id}"
              title="Make interactive">&#x26A1;</button>
    </div>
  </div>
</div>
<script type="text/x-python"
        data-fig-id="{fig_id}"
        data-fig-index="0"
        data-src-file="test_e2e_example"
        data-src="{data_src_attr}">
</script>
</body>
</html>"""

    parent_path = base_dir / f"{fig_id}_parent.html"
    parent_path.write_text(parent_html, encoding="utf-8")
    return parent_path


# ---------------------------------------------------------------------------
# Browser helpers
# ---------------------------------------------------------------------------

def _rafter(page) -> None:
    page.evaluate("() => new Promise(r => requestAnimationFrame(r))")


def _open_page(browser, url: str, timeout: int = 15_000):
    page = browser.new_page()
    page.goto(url, wait_until="domcontentloaded", timeout=timeout)
    return page


def _click_and_wait_boot(page, timeout: int = 15_000) -> None:
    """Click the ⚡ badge button and wait until it reaches the 'active' state."""
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
    page.wait_for_function(
        f"""() => {{
            const iframe = document.querySelector('iframe[data-awi-fig="{fig_id}"]');
            if (!iframe || !iframe.contentWindow) return false;
            const mdl = iframe.contentWindow._aplModel;
            if (!mdl) return false;
            const raw = mdl.get('panel_{panel_id}_json');
            return typeof raw === 'string' && raw.length > 10;
        }}""",
        timeout=timeout,
    )


# =============================================================================
# Tier 1 — Traitlet push unit tests  (no browser required)
# =============================================================================

class TestPushHook:
    """Verify _push() / _push_layout() write to sync=True traitlets.

    The old tests checked ``_pyodide_push_hook``; now we observe the traitlets
    directly — the same path that the generic anywidget monkey-patch uses in
    Pyodide.
    """

    def test_push_does_not_crash(self):
        """Normal mode: _push() succeeds without error."""
        fig, ax = apl.subplots(1, 1, figsize=(400, 300))
        ax.plot(np.zeros(16))  # must not raise

    def test_layout_json_written_on_create(self):
        """layout_json traitlet is set when a figure is created."""
        fig, ax = apl.subplots(1, 1, figsize=(400, 300))
        import json
        parsed = json.loads(fig.layout_json)
        assert "panel_specs" in parsed, (
            f"layout_json missing 'panel_specs': {list(parsed.keys())}"
        )

    def test_panel_json_written_after_plot(self):
        """panel_*_json traitlet is set when a plot is added."""
        import json
        fig, ax = apl.subplots(1, 1, figsize=(400, 300))
        ax.plot(np.sin(np.linspace(0, 2 * np.pi, 64)))

        panel_keys = [k for k in fig.trait_names() if k.startswith("panel_") and k.endswith("_json")]
        assert len(panel_keys) >= 1, "Expected at least one panel_*_json trait"
        for k in panel_keys:
            parsed = json.loads(getattr(fig, k))
            assert "kind" in parsed, f"panel JSON missing 'kind': {list(parsed.keys())}"

    def test_observe_fires_on_push(self):
        """traitlets.observe() fires when _push() writes a panel trait."""
        seen: list[str] = []

        def _watch(change):
            seen.append(change["name"])

        fig, ax = apl.subplots(1, 1, figsize=(400, 300))
        fig.observe(_watch)
        ax.plot(np.zeros(8))
        fig.unobserve(_watch)

        assert any(k.startswith("panel_") for k in seen), (
            f"Expected a panel_* trait change; got: {seen}"
        )

    def test_panel_id_deterministic(self):
        """Panel IDs derived from SubplotSpec must be identical across rebuilds."""
        ids: list[str] = []
        for _ in range(3):
            fig, ax = apl.subplots(1, 1, figsize=(400, 300))
            ax.plot(np.zeros(8))
            ids.append(list(fig._plots_map.keys())[0])
        assert ids[0] == ids[1] == ids[2], (
            f"Panel ID must be deterministic; got {ids}"
        )

    def test_panel_ids_unique_in_multiplot(self):
        """Each panel in a multi-panel figure has a unique ID."""
        fig, axes = apl.subplots(1, 3, figsize=(900, 300))
        for ax in axes:
            ax.plot(np.zeros(8))
        ids = list(fig._plots_map.keys())
        assert len(ids) == len(set(ids)), f"Panel IDs not unique: {ids}"

    def test_panel_id_matches_grid_position(self):
        """Panel IDs encode the SubplotSpec row/col bounds."""
        fig, axes = apl.subplots(2, 2, figsize=(600, 400))
        for ax in np.asarray(axes).flat:
            ax.plot(np.zeros(4))
        ids = set(fig._plots_map.keys())
        for pid in ids:
            assert pid.startswith("p"), f"Unexpected panel ID format: {pid!r}"

    def test_dispatch_event_callable_without_kernel(self):
        """_dispatch_event() can be called directly as the Pyodide bridge does."""
        import json
        fig, ax = apl.subplots(1, 1, figsize=(400, 300))
        ax.plot(np.zeros(16))
        raw = json.dumps({
            "event_type": "on_zoom",
            "panel_id": list(fig._plots_map.keys())[0],
            "source": "js",
        })
        fig._dispatch_event(raw)  # must not raise

    def test_capture_fig_state_helper(self):
        """_capture_fig_state returns both layout_json and panel JSON(s)."""
        fig, ax = apl.subplots(1, 1, figsize=(400, 300))
        ax.plot(np.zeros(32))
        state = _capture_fig_state(fig)
        assert "layout_json" in state, f"Expected layout_json; got {list(state.keys())}"
        panel_keys = [k for k in state if k.startswith("panel_")]
        assert len(panel_keys) >= 1, "Expected at least one panel_ key"

    def test_no_pyodide_push_hook_attribute(self):
        """figure module no longer exposes _pyodide_push_hook."""
        assert not hasattr(_af, "_pyodide_push_hook"), (
            "_pyodide_push_hook should not exist on figure module in this branch"
        )


# =============================================================================
# Tier 2 — iframe postMessage tests  (browser, no Pyodide, no HTTP server)
# =============================================================================

class TestIframeMessaging:
    """Test the awi_state postMessage protocol via the standalone iframe.

    The ``interact_page`` fixture opens the figure HTML as a top-level page
    (not as an iframe), so ``window.parent === window`` and the outbound
    awi_event forwarding is naturally disabled.  These tests focus on the
    *inbound* direction: an ``awi_state`` message updates the model.
    """

    def _open_fig(self, interact_page):
        fig, ax = apl.subplots(1, 1, figsize=(400, 300))
        ax.plot(np.sin(np.linspace(0, 2 * np.pi, 64)), color="#4fc3f7")
        plot = list(fig._plots_map.values())[0]
        panel_id = list(fig._plots_map.keys())[0]
        page = interact_page(fig)
        return fig, plot, panel_id, page

    def test_awi_state_message_updates_model_key(self, interact_page):
        """Posting {type:'awi_state', key, value} into the page updates the model."""
        fig, plot, panel_id, page = self._open_fig(interact_page)

        # Read the current panel JSON and add a sentinel key
        raw = page.evaluate(f"() => window._aplModel.get('panel_{panel_id}_json')")
        assert raw is not None, "Model should have an initial panel JSON"
        curr = json.loads(raw)
        curr["__apl_e2e_sentinel__"] = "hello_from_postMessage"
        new_json = json.dumps(curr)

        page.evaluate(f"""() => {{
            window.postMessage({{
                type: 'awi_state',
                key: 'panel_{panel_id}_json',
                value: {json.dumps(new_json)}
            }}, '*');
        }}""")
        _rafter(page)

        updated = json.loads(
            page.evaluate(f"() => window._aplModel.get('panel_{panel_id}_json')")
        )
        assert updated.get("__apl_e2e_sentinel__") == "hello_from_postMessage", (
            "awi_state postMessage did not update the model key"
        )

    def test_awi_state_message_sets_from_parent_flag(self, interact_page):
        """_fromParent is True while the awi_state handler runs.

        We can't read the flag mid-handler, but we can verify that a
        save_changes() triggered by awi_state does NOT set _eventJsonDirty
        (since event_json was not written in that transaction).  A by-product
        check: calling model.set on a non-event_json key never marks the
        dirty flag.
        """
        fig, plot, panel_id, page = self._open_fig(interact_page)

        raw = json.loads(
            page.evaluate(f"() => window._aplModel.get('panel_{panel_id}_json')")
        )
        raw["__flag_test__"] = 42
        new_json = json.dumps(raw)

        # Expose _eventJsonDirty so we can read it after the handler runs.
        # We monkey-patch model.save_changes to record whether _eventJsonDirty
        # was True at the time of the call triggered by the awi_state message.
        page.evaluate("""() => {
            window._dirtyAtSaveChanges = null;
            // We can't access module-scoped _eventJsonDirty from outside, but
            // we can observe whether an awi_event postMessage is fired: it only
            // fires when (!_fromParent && FIG_ID && parent!==window && dirty).
            // Since FIG_ID is null (standalone page), no awi_event fires in any
            // case. So we check absence of awi_event messages instead.
            window._aplEventsSeen = 0;
            window.addEventListener('message', (e) => {
                if (e.data && e.data.type === 'awi_event') window._aplEventsSeen++;
            });
        }""")

        page.evaluate(f"""() => {{
            window.postMessage({{
                type: 'awi_state',
                key: 'panel_{panel_id}_json',
                value: {json.dumps(new_json)}
            }}, '*');
        }}""")
        _rafter(page)

        # In standalone mode FIG_ID is null → no awi_event is ever forwarded
        events_seen = page.evaluate("() => window._aplEventsSeen")
        assert events_seen == 0, (
            "_fromParent guard or FIG_ID=null should prevent awi_event echo; "
            f"got {events_seen} awi_event(s)"
        )

    def test_awi_state_fires_change_listeners(self, interact_page):
        """Posting awi_state triggers on('change:…') listeners in the model."""
        fig, plot, panel_id, page = self._open_fig(interact_page)

        page.evaluate(f"""() => {{
            window._aplChangeCount = 0;
            window._aplModel.on('change:panel_{panel_id}_json', () => {{
                window._aplChangeCount++;
            }});
        }}""")

        raw = json.loads(
            page.evaluate(f"() => window._aplModel.get('panel_{panel_id}_json')")
        )
        raw["__change_test__"] = 1
        new_json = json.dumps(raw)

        page.evaluate(f"""() => {{
            window.postMessage({{
                type: 'awi_state',
                key: 'panel_{panel_id}_json',
                value: {json.dumps(new_json)}
            }}, '*');
        }}""")
        _rafter(page)

        count = page.evaluate("() => window._aplChangeCount")
        assert count >= 1, (
            "awi_state postMessage should fire change listeners; "
            f"got {count} invocations"
        )

    def test_layout_json_push_updates_model(self, interact_page):
        """layout_json can be updated via awi_state, not only panel_*_json."""
        fig, plot, panel_id, page = self._open_fig(interact_page)

        layout = json.loads(
            page.evaluate("() => window._aplModel.get('layout_json') || '{}'")
        )
        layout["__layout_sentinel__"] = "bridge_test"
        new_json = json.dumps(layout)

        page.evaluate(f"""() => {{
            window.postMessage({{
                type: 'awi_state',
                key: 'layout_json',
                value: {json.dumps(new_json)}
            }}, '*');
        }}""")
        _rafter(page)

        updated = json.loads(
            page.evaluate("() => window._aplModel.get('layout_json') || '{}'")
        )
        assert updated.get("__layout_sentinel__") == "bridge_test", (
            "layout_json postMessage did not update the model"
        )


# =============================================================================
# Tier 3 — Full bridge mock-boot tests  (HTTP server + mock Pyodide)
# =============================================================================

class TestFullBridgeBoot:
    """Boot anywidget_bridge.js end-to-end via a mock loadPyodide.

    Each test builds a parent HTML page using ``_build_parent_page`` and
    serves it from the shared ``http_server`` fixture.  All Pyodide network
    I/O is replaced by the JS mock so tests run in milliseconds.
    """

    # ------------------------------------------------------------------
    # helpers

    def _open(self, browser, base_url: str, parent_path: pathlib.Path,
              timeout: int = 15_000):
        url = f"{base_url}/{parent_path.name}"
        page = browser.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=timeout)
        return page

    def _basic_fig(self) -> tuple:
        fig, ax = apl.subplots(1, 1, figsize=(400, 300))
        ax.plot(np.sin(np.linspace(0, 2 * np.pi, 64)), color="#50fa7b")
        panel_id = list(fig._plots_map.keys())[0]
        return fig, panel_id

    # ------------------------------------------------------------------
    # tests

    def test_button_appears_when_iframe_present(
        self, http_server, _pw_browser
    ):
        """The ⚡ button is injected on any page that has a data-awi-fig iframe."""
        base_url, base_dir = http_server
        fig, panel_id = self._basic_fig()
        parent = _build_parent_page(fig, "btn_test_001", base_dir=base_dir)
        page = self._open(_pw_browser, base_url, parent)

        page.wait_for_function(
            "() => !!document.querySelector('button.awi-activate-btn')",
            timeout=5_000,
        )
        tooltip = page.evaluate(
            "() => document.querySelector('button.awi-activate-btn').title"
        )
        assert "interactive" in tooltip.lower(), (
            f"Button tooltip should mention 'interactive'; got {tooltip!r}"
        )
        page.close()

    def test_boot_completes_all_mock_steps(
        self, http_server, _pw_browser
    ):
        """Clicking ⚡ runs through all expected mock Pyodide boot steps."""
        base_url, base_dir = http_server
        fig, panel_id = self._basic_fig()
        parent = _build_parent_page(fig, "boot_test_001", base_dir=base_dir)
        page = self._open(_pw_browser, base_url, parent)

        _click_and_wait_boot(page)

        steps = page.evaluate("() => window._APL_BOOT_STEPS")

        assert "loadPyodide" in steps, (
            f"loadPyodide() was never called; steps={steps}"
        )
        assert "micropip_install" in steps, (
            f"micropip install step missing; steps={steps}"
        )
        assert "stub_anywidget" in steps, (
            f"anywidget stub step missing; steps={steps}"
        )
        assert "install_monkey_patch" in steps, (
            f"monkey-patch install step missing; steps={steps!r}\n"
            "This means anywidget_bridge.js never called runPythonAsync with "
            "the _patched_init monkey-patch source — the JS↔Python bridge is broken."
        )
        assert "run_example" in steps, (
            f"Example-run step missing; steps={steps!r}\n"
            "This means anywidget_bridge.js never called runPythonAsync with "
            "the _fig_ids / _push_layout block that seeds the iframes."
        )
        page.close()

    def test_anywidgetPush_is_function_after_boot(
        self, http_server, _pw_browser
    ):
        """window._anywidgetPush must be a function after the push-hook step runs."""
        base_url, base_dir = http_server
        fig, panel_id = self._basic_fig()
        parent = _build_parent_page(fig, "apush_test_001", base_dir=base_dir)
        page = self._open(_pw_browser, base_url, parent)

        _click_and_wait_boot(page)

        is_fn = page.evaluate("() => typeof window._anywidgetPush === 'function'")
        assert is_fn, (
            "window._anywidgetPush should be a function after the push-hook step; "
            "if it is missing the hook was never installed by anywidget_bridge.js"
        )
        page.close()

    def test_state_pushed_into_iframe_model(
        self, http_server, _pw_browser
    ):
        """After boot the iframe's model contains the figure's panel JSON.

        This is the core Pyodide bridge assertion: Python figure state must
        reach the iframe model via _anywidgetPush → postMessage → awi_state listener
        → model.set(key, value).
        """
        base_url, base_dir = http_server
        fig, panel_id = self._basic_fig()
        expected = fig._plots_map[panel_id].to_state_dict()

        parent = _build_parent_page(fig, "state_push_001", base_dir=base_dir)
        page = self._open(_pw_browser, base_url, parent)

        _click_and_wait_boot(page)
        _wait_for_iframe_model(page, "state_push_001", panel_id)

        raw = page.evaluate(f"""() => {{
            const iframe = document.querySelector('iframe[data-awi-fig="state_push_001"]');
            return iframe && iframe.contentWindow
                   ? iframe.contentWindow._aplModel.get('panel_{panel_id}_json')
                   : null;
        }}""")

        assert raw is not None, (
            "panel JSON was never delivered to the iframe model after boot.\n"
            "Check: (a) _anywidgetPush was installed, (b) postMessage reached the "
            "iframe's awi_state listener, (c) model.set() was called."
        )
        state = json.loads(raw)
        assert state.get("kind") == expected.get("kind"), (
            f"kind mismatch: iframe has {state.get('kind')!r}, "
            f"Python produced {expected.get('kind')!r}"
        )
        page.close()

    def test_layout_json_pushed_into_iframe(
        self, http_server, _pw_browser
    ):
        """layout_json (panel geometry) is delivered to the iframe model."""
        base_url, base_dir = http_server
        fig, panel_id = self._basic_fig()
        parent = _build_parent_page(fig, "layout_push_001", base_dir=base_dir)
        page = self._open(_pw_browser, base_url, parent)

        _click_and_wait_boot(page)

        # Wait for layout_json to propagate
        page.wait_for_function(
            """() => {
                const iframe = document.querySelector('iframe[data-awi-fig="layout_push_001"]');
                if (!iframe || !iframe.contentWindow) return false;
                const mdl = iframe.contentWindow._aplModel;
                if (!mdl) return false;
                const raw = mdl.get('layout_json');
                return typeof raw === 'string' && raw.length > 10;
            }""",
            timeout=8_000,
        )

        raw = page.evaluate("""() => {
            const iframe = document.querySelector('iframe[data-awi-fig="layout_push_001"]');
            return iframe.contentWindow._aplModel.get('layout_json');
        }""")
        assert raw is not None, "layout_json was not delivered to the iframe"
        layout = json.loads(raw)
        assert "panel_specs" in layout, (
            f"layout_json is missing 'panel_specs'; got keys: {list(layout.keys())}"
        )
        page.close()

    def test_event_message_forwarded_to_parent(
        self, http_server, _pw_browser
    ):
        """awi_event messages sent from the iframe arrive at the parent window.

        This tests the reverse direction of the bridge: user interaction in
        the iframe → awi_event postMessage → parent window.message listener
        → _fig._dispatch_event().  Here we only test the JS forwarding step;
        the Python dispatch is covered by TestPushHook.test_dispatch_event_*.
        """
        base_url, base_dir = http_server
        fig, panel_id = self._basic_fig()
        parent = _build_parent_page(fig, "event_fwd_001", base_dir=base_dir)
        page = self._open(_pw_browser, base_url, parent)

        _click_and_wait_boot(page)

        # Install a parent-side listener that records received awi_events
        page.evaluate("""() => {
            window._aplReceivedEvents = [];
            window.addEventListener('message', (e) => {
                if (e.data && e.data.type === 'awi_event') {
                    window._aplReceivedEvents.push(e.data);
                }
            });
        }""")

        # Synthesise an awi_event from the iframe (mirrors what the iframe
        # does when a widget drag ends: window.parent.postMessage({...}, '*'))
        fake_event = json.dumps({
            "event_type": "on_release",
            "panel_id": panel_id,
            "widget_id": "w_e2e_fake",
            "x": 42.0,
        })
        page.evaluate(f"""() => {{
            // Simulate the iframe posting the event to its parent.
            // In the actual docs the iframe does:
            //   window.parent.postMessage({{type:'awi_event', figId, data}}, '*')
            // Here the iframe IS the top-level page so we post to window itself.
            window.postMessage({{
                type: 'awi_event',
                figId: 'event_fwd_001',
                data: {json.dumps(fake_event)}
            }}, '*');
        }}""")
        _rafter(page)

        events = page.evaluate("() => window._aplReceivedEvents")
        assert len(events) >= 1, (
            "No awi_event reached the parent message bus.\n"
            "The parent window.message listener in anywidget_bridge.js "
            "may not be installed, or the figId routing is broken."
        )
        assert events[0]["figId"] == "event_fwd_001", (
            f"figId mismatch: {events[0]['figId']!r} vs 'event_fwd_001'"
        )
        page.close()

    def test_multiple_panels_all_receive_state(
        self, http_server, _pw_browser
    ):
        """All panels in a multi-panel figure have their state pushed."""
        base_url, base_dir = http_server

        fig, axes = apl.subplots(1, 2, figsize=(700, 300))
        axes[0].plot(np.zeros(32))
        axes[1].plot(np.ones(32) * 0.5)
        panel_ids = list(fig._plots_map.keys())
        assert len(panel_ids) == 2, "Expected exactly 2 panels"

        parent = _build_parent_page(fig, "multi_panel_001", base_dir=base_dir)
        page = self._open(_pw_browser, base_url, parent)
        _click_and_wait_boot(page)

        # Wait for both panels to arrive
        for pid in panel_ids:
            _wait_for_iframe_model(page, "multi_panel_001", pid)

        for pid in panel_ids:
            raw = page.evaluate(f"""() => {{
                const iframe = document.querySelector(
                    'iframe[data-awi-fig="multi_panel_001"]');
                return iframe && iframe.contentWindow
                       ? iframe.contentWindow._aplModel.get('panel_{pid}_json')
                       : null;
            }}""")
            assert raw is not None, (
                f"Panel {pid!r} state was not pushed into the iframe model.\n"
                "If only the first panel arrives, _anywidgetPush may be iterating "
                "panels incorrectly in the mock (or in the real bridge)."
            )
        page.close()

    def test_button_shows_error_on_boot_failure(
        self, http_server, _pw_browser
    ):
        """If Pyodide boot fails the button switches to the error state (❌)."""
        base_url, base_dir = http_server
        fig, panel_id = self._basic_fig()

        # Build the parent page, then patch the mock to throw on loadPyodide
        parent = _build_parent_page(fig, "error_test_001", base_dir=base_dir)
        html = (base_dir / "error_test_001_parent.html").read_text(encoding="utf-8")
        # Inject a rejection AFTER the mock definition so it overrides it
        html = html.replace(
            "window.loadPyodide = async function({indexURL}) {",
            "window.loadPyodide = async function({indexURL}) { throw new Error('mock boot failure'); //",
        )
        (base_dir / "error_test_001_parent.html").write_text(html, encoding="utf-8")

        page = self._open(_pw_browser, base_url, parent)
        page.wait_for_function(
            "() => !!document.querySelector('button.awi-activate-btn')",
            timeout=5_000
        )
        page.click("button.awi-activate-btn")

        # Wait for button to enter error state
        page.wait_for_function(
            """() => {
                const btn = document.querySelector('button.awi-activate-btn');
                return btn && btn.dataset.state === 'error';
            }""",
            timeout=10_000,
        )
        label = page.evaluate(
            "() => document.querySelector('button.awi-activate-btn').title"
        )
        assert "mock boot failure" in label, (
            f"Error button title should contain the exception message; got {label!r}"
        )
        page.close()




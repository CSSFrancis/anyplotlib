/**
 * pyodide_bridge.js
 *
 * Adds a single floating "⚡" button to any docs page that contains
 * anyplotlib figure iframes.  Clicking it boots ONE shared Pyodide instance
 * for the entire page, runs each example's Python source exactly once, then
 * wires Python ↔ JS via postMessage so on_change / on_release callbacks fire
 * live in the browser — no server, no Jupyter kernel.
 *
 * Architecture
 * ────────────
 *  Parent page (this script)
 *  ├─ Pyodide WASM runtime (loaded once from CDN on button click)
 *  ├─ anyplotlib wheel built at docs-build time → _static/wheels/
 *  ├─ <script type="text/x-python" data-fig-id="…" data-src-file="…">
 *  │    Full example source (emitted by _sg_html_scraper.py at build time)
 *  └─ <iframe data-apl-fig="…" src="…_static/viewer_widgets/….html">
 *       figure_esm.js renderer + postMessage listener (from _repr_utils.py)
 *
 *  Data flow after activation
 *  ──────────────────────────
 *  Python _push()  → _pyodide_push_hook  → window._aplPush(figId, key, val)
 *                  → iframe.contentWindow.postMessage({type:'apl_state',…})
 *                  → model.set(key,val) + save_changes()  →  JS re-renders
 *
 *  user interaction → iframe save_changes() forwards event_json to parent
 *                   → window 'message' listener → pyodide fig._dispatch_event()
 *                   → Python on_release / on_change callbacks
 *
 *  Wheel URL resolution
 *  ────────────────────
 *  The anyplotlib wheel lives at _static/wheels/anyplotlib-0.0.0-py3-none-any.whl
 *  relative to the docs root.  _DOCS_ROOT is derived from document.currentScript.src
 *  at page-load time so the URL is always version-specific:
 *
 *    dev docs    → https://…/anyplotlib/dev/_static/wheels/anyplotlib-0.0.0….whl
 *    v0.1.0 docs → https://…/anyplotlib/v0.1.0/_static/wheels/anyplotlib-0.0.0….whl
 *
 *  "0.0.0" is a valid PEP 440 sentinel; micropip accepts it for URL installs
 *  and never cross-checks it against PyPI when deps=False is passed.
 */

(function () {
  'use strict';

  const PYODIDE_VERSION = '0.27.5';
  const PYODIDE_CDN = `https://cdn.jsdelivr.net/pyodide/v${PYODIDE_VERSION}/full/`;

  // Capture the docs-root URL from this script's own src attribute.
  // document.currentScript is only valid during synchronous top-level
  // execution — we must capture it here before any async work begins.
  //
  //  Script src:  https://example.com/anyplotlib/v0.1.0/_static/pyodide_bridge.js
  //  _DOCS_ROOT:  https://example.com/anyplotlib/v0.1.0/
  //
  // This makes the wheel URL automatically version-correct for every deployed
  // copy of the docs without any hard-coded version strings.
  const _SCRIPT_SRC = (document.currentScript || {}).src || '';
  const _DOCS_ROOT  = _SCRIPT_SRC.replace(/_static\/pyodide_bridge\.js.*$/, '') || './';

  // ── helpers ──────────────────────────────────────────────────────────────

  /** True when the page has at least one anyplotlib figure iframe. */
  function _hasFigures() {
    return document.querySelector('iframe[data-apl-fig]') !== null;
  }

  /** Deliver a state-update message into the iframe for figId. */
  function _postToIframe(figId, key, value) {
    const iframe = document.querySelector(`iframe[data-apl-fig="${figId}"]`);
    if (iframe && iframe.contentWindow) {
      iframe.contentWindow.postMessage({ type: 'apl_state', key, value }, '*');
    }
  }

  // ── button ────────────────────────────────────────────────────────────────

  function _createButton() {
    const btn = document.createElement('button');
    btn.id = 'apl-pyodide-btn';
    btn.title = 'Activate interactive Python for this page';
    btn.innerHTML =
      '<span class="apl-btn-icon">⚡</span>' +
      '<span class="apl-btn-label"> Click to make interactive</span>';

    Object.assign(btn.style, {
      position:       'fixed',
      bottom:         '24px',
      right:          '24px',
      height:         '40px',
      borderRadius:   '20px',
      border:         'none',
      fontSize:       '14px',
      fontFamily:     'system-ui, sans-serif',
      fontWeight:     '600',
      lineHeight:     '1',
      cursor:         'pointer',
      background:     '#6272a4',
      color:          '#fff',
      zIndex:         '9999',
      boxShadow:      '0 2px 8px rgba(0,0,0,0.35)',
      display:        'flex',
      alignItems:     'center',
      justifyContent: 'center',
      padding:        '0 16px 0 12px',
      whiteSpace:     'nowrap',
      transition:     'background 0.2s, width 0.25s, padding 0.25s, border-radius 0.25s',
    });

    btn.addEventListener('mouseenter', () => {
      if (!btn.dataset.state) btn.style.background = '#8be9fd';
    });
    btn.addEventListener('mouseleave', () => {
      if (!btn.dataset.state) btn.style.background = '#6272a4';
    });

    document.body.appendChild(btn);
    return btn;
  }

  function _setButtonLoading(btn) {
    btn.querySelector('.apl-btn-icon').textContent = '⏳';
    btn.querySelector('.apl-btn-label').style.display = 'none';
    Object.assign(btn.style, {
      width:         '40px',
      padding:       '0',
      borderRadius:  '50%',
      background:    '#bd93f9',
      cursor:        'default',
      pointerEvents: 'none',
    });
  }

  function _setButtonActive(btn) {
    btn.querySelector('.apl-btn-icon').textContent = '✓';
    btn.querySelector('.apl-btn-label').style.display = 'none';
    btn.dataset.state = 'active';
    Object.assign(btn.style, {
      width:         '40px',
      padding:       '0',
      borderRadius:  '50%',
      background:    '#50fa7b',
      color:         '#1e1e2e',
      cursor:        'pointer',
      pointerEvents: 'auto',
      fontSize:      '16px',
    });
    btn.title = 'Python active — click to dismiss';
    btn.addEventListener('click', () => btn.remove());
  }

  function _setButtonError(btn, err) {
    // Python tracebacks have the actual exception on the LAST non-empty line,
    // not the first ("Traceback (most recent call last):" is useless to show).
    const msg   = String(err.message || err);
    const lines = msg.split('\n').map(l => l.trim()).filter(Boolean);
    const displayLine = lines.length > 1 ? lines[lines.length - 1] : (lines[0] || msg);
    btn.querySelector('.apl-btn-icon').textContent = '❌';
    const label = btn.querySelector('.apl-btn-label');
    label.textContent = ' ' + displayLine;
    label.style.display = '';
    Object.assign(btn.style, {
      width:         'auto',
      padding:       '0 16px 0 12px',
      borderRadius:  '20px',
      background:    '#ff5555',
      cursor:        'default',
      pointerEvents: 'none',
    });
    // Full error in tooltip for copy-paste
    btn.title = msg;
  }

  // ── Pyodide bootstrap ─────────────────────────────────────────────────────

  async function _boot(btn) {
    // ── file:// guard ─────────────────────────────────────────────────────
    if (window.location.protocol === 'file:') {
      throw new Error(
        'Serve docs over HTTP — run: python -m http.server -d build/html 8080'
      );
    }

    _setButtonLoading(btn);

    // Re-throw any promise rejection with a step label prepended so the error
    // button shows exactly which phase failed (e.g. "[install traitlets/colorcet]
    // ModuleNotFoundError: …") without the user needing to open DevTools.
    function _step(label, promise) {
      return promise.catch(e => {
        throw new Error('[' + label + '] ' + (e.message || String(e)));
      });
    }

    // 1. Load pyodide.js from CDN
    if (typeof loadPyodide === 'undefined') {
      await _step('load pyodide.js', new Promise((resolve, reject) => {
        const s  = document.createElement('script');
        s.src    = PYODIDE_CDN + 'pyodide.js';
        s.onload = resolve;
        s.onerror = () => reject(new Error('Failed to load pyodide.js from CDN'));
        document.head.appendChild(s);
      }));
    }

    // 2. Initialise Pyodide
    const pyodide = await _step('init pyodide',
      loadPyodide({ indexURL: PYODIDE_CDN }));

    // 3. Install packages
    //
    //  numpy    — pre-built binary in Pyodide's package index.
    //  traitlets, colorcet — pure-Python; fetched from PyPI via micropip.
    //  anyplotlib — wheel from _static/wheels/ (same source tree as the docs).
    //
    //  anyplotlib declares anywidget as a dep; anywidget → psygnal may have
    //  no Pyodide-compatible wheel.  Safe strategy:
    //    a) load numpy + micropip from Pyodide's bundled index (fast),
    //    b) install traitlets + colorcet via micropip in Python (avoids
    //       JS-Array → Python-list coercion when calling the PyProxy),
    //    c) pre-populate sys.modules['anywidget'] with a HasTraits stub so
    //       micropip never tries to fetch it,
    //    d) install the anyplotlib wheel with deps=False.

    // a) Pyodide-bundled packages
    await _step('load numpy',
      pyodide.loadPackage(['micropip', 'numpy']));

    // b) Pure-Python deps — run as Python to avoid JS array coercion issues
    await _step('install traitlets/colorcet',
      pyodide.runPythonAsync(`
import micropip
await micropip.install(['traitlets', 'colorcet'])
`));

    // 4. Stub anywidget BEFORE installing the anyplotlib wheel.
    //    anyplotlib/figure.py imports anywidget inside a try/except and will
    //    pick up this stub as _AnyWidgetBase automatically.
    await _step('stub anywidget',
      pyodide.runPythonAsync(`
import sys, traitlets as _tr

class _AnyWidget(_tr.HasTraits):
    _esm = _tr.Unicode("").tag(sync=False)
    _css = _tr.Unicode("").tag(sync=False)
    def __init__(self, **kw):
        super().__init__(**kw)

class _AnyWidgetMod:
    AnyWidget = _AnyWidget

sys.modules['anywidget'] = _AnyWidgetMod()
_APL_REGISTRY = {}
`));

    // c) Install anyplotlib wheel directly via pyodide.loadPackage(url).
    //    loadPackage accepts wheel URLs and installs them without dependency
    //    resolution, which sidesteps the micropip "Attempted to install wheel
    //    before downloading it" bug that is triggered by deps=False on URL
    //    installs in Pyodide 0.27.x.  anywidget is already in sys.modules so
    //    importing anyplotlib will use our stub.
    const wheelUrl = _DOCS_ROOT + '_static/wheels/anyplotlib-0.0.0-py3-none-any.whl';
    await _step('install anyplotlib wheel', pyodide.loadPackage(wheelUrl));

    // 5. Expose window._aplPush so Python can push state into iframes
    window._aplPush = (figId, key, value) =>
      _postToIframe(String(figId), String(key), String(value));

    // 6. Install the push hook — from now on every Figure._push() /
    //    _push_layout() / _push_widget() call routes through _aplPush
    //    instead of writing to a Jupyter traitlet.
    await _step('install push hook',
      pyodide.runPythonAsync(`
import anyplotlib.figure as _af
import js

def _push_hook(fig, key, value_str):
    fid = getattr(fig, '_pyodide_fig_id', None)
    if fid:
        js.window._aplPush(fid, key, value_str)

_af._pyodide_push_hook = _push_hook
`));

    // 7. Collect text/x-python script blocks, group by src-file so each
    //    example source runs exactly once even if it creates multiple figures.
    const srcGroups = new Map();  // srcFile → { src, pairs: [{figId, figIndex}] }

    for (const script of document.querySelectorAll(
        'script[type="text/x-python"][data-fig-id]')) {
      const srcFile  = script.dataset.srcFile  || '__default__';
      const figId    = script.dataset.figId;
      const figIndex = parseInt(script.dataset.figIndex || '0', 10);
      // Source is JSON-encoded in data-src to keep the <script> tag one line
      // and avoid breaking RST raw:: html directives (see _sg_html_scraper.py).
      let src = '';
      try { src = JSON.parse(script.dataset.src || 'null') || ''; } catch (_) {}

      if (!srcGroups.has(srcFile)) srcGroups.set(srcFile, { src, pairs: [] });
      srcGroups.get(srcFile).pairs.push({ figId, figIndex });
    }

    for (const g of srcGroups.values())
      g.pairs.sort((a, b) => a.figIndex - b.figIndex);

    // 8. Run each example source once, tag created figures in creation order,
    //    then push the current Python state into the matching iframes.
    for (const [srcFile, { src, pairs }] of srcGroups) {
      const figIdList = JSON.stringify(pairs.map(p => p.figId));
      try {
        await pyodide.runPythonAsync(`
import anyplotlib.figure as _af

_CREATED_FIGS = []
_SEEN_IDS     = set()
_orig_init    = _af.Figure.__init__

def _tracked_init(self, *a, **kw):
    _orig_init(self, *a, **kw)
    if id(self) not in _SEEN_IDS:
        _SEEN_IDS.add(id(self))
        _CREATED_FIGS.append(self)

_af.Figure.__init__ = _tracked_init
try:
    exec(${JSON.stringify(src)}, {})
except Exception as _e:
    print(f"[anyplotlib] exec error in ${JSON.stringify(srcFile)}: {_e}")
finally:
    _af.Figure.__init__ = _orig_init

_fig_ids = ${figIdList}
for _i, _fid in enumerate(_fig_ids):
    if _i < len(_CREATED_FIGS):
        _fig = _CREATED_FIGS[_i]
        _fig._pyodide_fig_id = _fid
        _APL_REGISTRY[_fid]  = _fig
        _fig._push_layout()
        for _pid in list(_fig._plots_map):
            _fig._push(_pid)
`);
      } catch (err) {
        console.warn(`[anyplotlib] Pyodide failed for ${srcFile}:`, err);
      }
    }

    // 9. Route interaction events from iframes → Pyodide callbacks
    window.addEventListener('message', async (e) => {
      if (!e.data || e.data.type !== 'apl_event') return;
      const { figId, data } = e.data;
      try {
        await pyodide.runPythonAsync(`
_fig = _APL_REGISTRY.get(${JSON.stringify(figId)})
if _fig is not None:
    _fig._dispatch_event(${JSON.stringify(data)})
`);
      } catch (err) {
        console.warn('[anyplotlib] event dispatch error:', err);
      }
    });

    // 10. Done
    _setButtonActive(btn);
  }

  // ── init ──────────────────────────────────────────────────────────────────

  function _init() {
    if (!_hasFigures()) return;

    const btn = _createButton();
    btn.addEventListener('click', function handler() {
      btn.removeEventListener('click', handler);
      _boot(btn).catch(err => {
        console.error('[anyplotlib] Pyodide boot failed:', err);
        _setButtonError(btn, err);
      });
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', _init);
  } else {
    _init();
  }
})();

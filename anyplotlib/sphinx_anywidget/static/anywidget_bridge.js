/**
 * anywidget_bridge.js
 *
 * Generic Pyodide bridge for anywidget-based interactive documentation.
 *
 * Architecture
 * ────────────
 *  Parent page (this script)
 *  ├─ Per-figure ⚡ badge (in .awi-badge div, rendered by _scraper.py)
 *  ├─ Pyodide WASM runtime (loaded once from CDN on first ⚡ click)
 *  ├─ Package wheel at _static/wheels/{pkg}-0.0.0-py3-none-any.whl
 *  ├─ <script type="text/x-python" data-fig-id="…"> — example source
 *  └─ <iframe data-awi-fig="…" src="…_static/viewer_widgets/….html">
 *       anywidget ESM renderer + postMessage listener
 *
 *  Data flow after activation
 *  ──────────────────────────
 *  Python setattr(widget, key, val)  [any sync=True traitlet]
 *    → traitlets fires observe() on monkey-patched AnyWidget.__init__ observer
 *    → observer calls js.window._anywidgetPush(fig_id, key, val_str)
 *    → iframe.contentWindow.postMessage({type:'awi_state', key, value})
 *    → model.set(key, val) + save_changes()  →  JS re-renders
 *
 *  user interaction  → iframe save_changes() forwards awi_event to parent
 *                    → window 'message' listener  → pyodide dispatch
 *                    → if hasattr(widget, '_dispatch_event'): widget._dispatch_event(data)
 *                    → Python on_release / on_change callbacks
 *
 *  Monkey-patch (installed in Pyodide after anywidget stub is ready)
 *  ─────────────────────────────────────────────────────────────────
 *  _aw.AnyWidget.__init__ is wrapped to add a traitlets.observe(names=All)
 *  observer to every new widget instance.  The observer fires for every trait
 *  change; it filters to sync=True traits and calls _anywidgetPush when
 *  _anywidget_fig_id is set on the instance.  Dynamic traits added via
 *  add_traits() are automatically covered by the All sentinel.
 *
 *  Wheel URL resolution
 *  ────────────────────
 *  The wheel lives at _static/wheels/{pkg}-0.0.0-py3-none-any.whl relative
 *  to the docs root.  _DOCS_ROOT is derived from document.currentScript.src
 *  so the URL is always version-correct for every deployed copy of the docs.
 */

(function () {
  'use strict';

  const PYODIDE_VERSION = '0.27.5';
  const PYODIDE_CDN = `https://cdn.jsdelivr.net/pyodide/v${PYODIDE_VERSION}/full/`;

  // Derives the docs root from this script's own URL so wheel references are
  // always version-specific (dev vs v0.1.0, etc.)
  const _SCRIPT_SRC = (document.currentScript || {}).src || '';
  const _DOCS_ROOT  = _SCRIPT_SRC.replace(/_static\/anywidget_bridge\.js.*$/, '') || './';

  // One shared Pyodide instance for the whole page, resolved once on first boot.
  let _pyodidePromise = null;

  // ── helpers ──────────────────────────────────────────────────────────────

  /** True when the page has at least one interactive anywidget figure. */
  function _hasInteractiveFigures() {
    return document.querySelector('button.awi-activate-btn') !== null;
  }

  /** Deliver a state-update message into the iframe for figId. */
  function _postToIframe(figId, key, value) {
    const iframe = document.querySelector(`iframe[data-awi-fig="${figId}"]`);
    if (iframe && iframe.contentWindow) {
      iframe.contentWindow.postMessage({ type: 'awi_state', key, value }, '*');
    }
  }

  // ── badge state management ────────────────────────────────────────────────

  function _allActivateBtns() {
    return Array.from(document.querySelectorAll('button.awi-activate-btn'));
  }

  function _setBadgesLoading() {
    for (const btn of _allActivateBtns()) {
      btn.textContent = '⏳';
      btn.dataset.state = 'loading';
      btn.title = 'Loading Pyodide…';
    }
  }

  function _setBadgesActive() {
    for (const btn of _allActivateBtns()) {
      btn.textContent = '✓';
      btn.dataset.state = 'active';
      btn.title = 'Python active';
      // Mark the wrapper so CSS can hide the static icon
      const wrap = btn.closest('.awi-fig-wrap');
      if (wrap) wrap.dataset.awiLive = 'true';
    }
  }

  function _setBadgesError(err) {
    const msg    = String(err.message || err);
    const lines  = msg.split('\n').map(l => l.trim()).filter(Boolean);
    const summary = lines.length > 1 ? lines[lines.length - 1] : (lines[0] || msg);
    for (const btn of _allActivateBtns()) {
      btn.textContent  = '❌';
      btn.dataset.state = 'error';
      btn.title        = `Boot failed: ${summary}\n\n${msg}`;
    }
  }

  // ── Pyodide bootstrap ─────────────────────────────────────────────────────

  function _boot() {
    if (_pyodidePromise) return _pyodidePromise;
    _pyodidePromise = _doBoot().catch(err => {
      _pyodidePromise = null;  // allow retry
      throw err;
    });
    return _pyodidePromise;
  }

  async function _doBoot() {
    // ── file:// guard ─────────────────────────────────────────────────────
    if (window.location.protocol === 'file:') {
      throw new Error(
        'Serve docs over HTTP — run: python -m http.server -d build/html 8080'
      );
    }

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
    console.info('[sphinx_anywidget] pyodide.js ready');

    // 2. Initialise Pyodide
    const pyodide = await _step('init pyodide',
      loadPyodide({ indexURL: PYODIDE_CDN }));
    console.info('[sphinx_anywidget] Pyodide initialised');

    // 3. Load micropip + numpy
    await _step('load micropip+numpy',
      pyodide.loadPackage(['micropip', 'numpy']));
    console.info('[sphinx_anywidget] micropip + numpy loaded');

    // 4. Install pure-Python deps
    await _step('install traitlets/colorcet',
      pyodide.runPythonAsync(`
import micropip
await micropip.install(['traitlets', 'colorcet'])
`));
    console.info('[sphinx_anywidget] traitlets + colorcet installed');

    // 5. Stub anywidget in sys.modules
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
_AWI_REGISTRY = {}   # fig_id → widget instance
`));
    console.info('[sphinx_anywidget] anywidget stub installed');

    // 6. Install package wheel
    const wheelUrl = _DOCS_ROOT + '_static/wheels/';
    // Discover wheel name: try the configured package name from the <script>
    // data-package attribute injected by _build_pyodide_wheel, else fall back
    // to scanning data-src-file scripts for a clue.
    const pkgName = _inferPackageName();
    const fullWheelUrl = wheelUrl + pkgName + '-0.0.0-py3-none-any.whl';
    console.info('[sphinx_anywidget] installing wheel from', fullWheelUrl);
    await _step('install wheel', pyodide.loadPackage(fullWheelUrl));
    console.info('[sphinx_anywidget] package wheel installed');

    // 7. Install generic anywidget monkey-patch
    //    Wraps AnyWidget.__init__ so that every new widget instance automatically
    //    gets a traitlets.observe(names=All) callback.  The callback pushes any
    //    sync=True trait change to the matching iframe via window._anywidgetPush.
    //    This works for dynamically-added traits too because traitlets.All
    //    matches all trait names, including ones added after __init__ via add_traits().
    window._anywidgetPush = (figId, key, value) =>
      _postToIframe(String(figId), String(key), String(value));

    await _step('install monkey-patch',
      pyodide.runPythonAsync(`
import anywidget as _aw
import traitlets as _tr
import js

_orig_init = _aw.AnyWidget.__init__

def _patched_init(self, *args, **kw):
    _orig_init(self, *args, **kw)

    # Capture self in a closure so each widget has its own push callback.
    _self = self

    def _push_cb(change):
        fid = getattr(_self, '_anywidget_fig_id', None)
        if fid is None:
            return
        tname = change['name']
        # Only push traits tagged sync=True
        # instance_traits() covers dynamically-added traits from add_traits()
        t = _self.traits().get(tname)
        if t is None or not t.metadata.get('sync'):
            return
        import json as _j
        val = change['new']
        val_str = val if isinstance(val, str) else _j.dumps(val, default=str)
        js.window._anywidgetPush(fid, tname, val_str)

    self.observe(_push_cb, names=_tr.All)

_aw.AnyWidget.__init__ = _patched_init
print('[sphinx_anywidget] anywidget monkey-patch installed')
`));
    console.info('[sphinx_anywidget] monkey-patch installed');

    // 8. Collect text/x-python script blocks, group by src-file so each
    //    example source runs exactly once even with multiple figures.
    const srcGroups = new Map();  // srcFile → { src, pairs: [{figId, figIndex}] }

    for (const script of document.querySelectorAll(
        'script[type="text/x-python"][data-fig-id]')) {
      const srcFile  = script.dataset.srcFile  || '__default__';
      const figId    = script.dataset.figId;
      const figIndex = parseInt(script.dataset.figIndex || '0', 10);
      let src = '';
      try { src = JSON.parse(script.dataset.src || 'null') || ''; } catch (_) {}

      if (!srcGroups.has(srcFile)) srcGroups.set(srcFile, { src, pairs: [] });
      srcGroups.get(srcFile).pairs.push({ figId, figIndex });
    }

    for (const g of srcGroups.values())
      g.pairs.sort((a, b) => a.figIndex - b.figIndex);

    // 9. Run each example source once, assign _anywidget_fig_id in creation
    //    order, then push current state into the matching iframes.
    const _execErrors = [];
    for (const [srcFile, { src, pairs }] of srcGroups) {
      const figIdList = JSON.stringify(pairs.map(p => p.figId));
      console.info(`[sphinx_anywidget] running: ${srcFile} (${pairs.length} figure(s))`);
      const _srcFileRepr = JSON.stringify(srcFile);
      try {
        await pyodide.runPythonAsync(`
import anywidget as _aw
import traitlets as _tr

_SRC_FILE     = ${_srcFileRepr}
_CREATED_WIDS = []
_SEEN_IDS     = set()
_orig_init2   = _aw.AnyWidget.__init__

def _tracked_init(self, *a, **kw):
    _orig_init2(self, *a, **kw)
    if id(self) not in _SEEN_IDS:
        _SEEN_IDS.add(id(self))
        _CREATED_WIDS.append(self)

_aw.AnyWidget.__init__ = _tracked_init
_exec_error = None
try:
    exec(${JSON.stringify(src)}, {"__name__": "__main__"})
except Exception as _e:
    import traceback as _tb
    _exec_error = _tb.format_exc()
    print("[sphinx_anywidget] exec error in " + _SRC_FILE + ":\\n" + _exec_error)
finally:
    _aw.AnyWidget.__init__ = _orig_init2

_fig_ids = ${figIdList}
_wired = 0
for _i, _fid in enumerate(_fig_ids):
    if _i < len(_CREATED_WIDS):
        _w = _CREATED_WIDS[_i]
        _w._anywidget_fig_id = _fid
        _AWI_REGISTRY[_fid]  = _w
        # Push current state into the iframe immediately
        for _tname, _trait in _w.traits().items():
            if _tname.startswith('_') or not _trait.metadata.get('sync'):
                continue
            import json as _jj
            _val = getattr(_w, _tname, None)
            if _val is None:
                continue
            _vs = _val if isinstance(_val, str) else _jj.dumps(_val, default=str)
            import js as _js
            _js.window._anywidgetPush(_fid, _tname, _vs)
        _wired += 1

print("[sphinx_anywidget] wired " + str(_wired) + "/" + str(len(_fig_ids))
      + " widgets for " + _SRC_FILE)
if _exec_error:
    raise RuntimeError("exec failed: " + _exec_error)
`);
      } catch (err) {
        const msg = String(err.message || err);
        console.warn(`[sphinx_anywidget] Pyodide failed for ${srcFile}:`, msg);
        _execErrors.push(`${srcFile}: ${msg.split('\n').filter(Boolean).pop()}`);
      }
    }

    // 10. Route awi_event messages from iframes → Pyodide callbacks
    window.addEventListener('message', async (e) => {
      if (!e.data || e.data.type !== 'awi_event') return;
      const { figId, data } = e.data;
      console.debug('[sphinx_anywidget] awi_event', figId,
                    JSON.parse(data || '{}').event_type);
      const _figIdRepr = JSON.stringify(figId);
      const _dataRepr  = JSON.stringify(data);
      try {
        await pyodide.runPythonAsync(`
_AWI_FIG_ID = ${_figIdRepr}
_widget = _AWI_REGISTRY.get(_AWI_FIG_ID)
if _widget is not None and hasattr(_widget, '_dispatch_event'):
    _widget._dispatch_event(${_dataRepr})
elif _widget is None:
    print("[sphinx_anywidget] no widget for figId=" + repr(_AWI_FIG_ID))
`);
      } catch (err) {
        console.warn('[sphinx_anywidget] event dispatch error:', err);
      }
    });

    if (_execErrors.length > 0) {
      console.warn('[sphinx_anywidget] some examples failed:', _execErrors);
    }

    return pyodide;
  }

  // ── package name inference ────────────────────────────────────────────────

  function _inferPackageName() {
    // 1. Check for a <meta name="anywidget:package"> tag (set by the extension)
    const meta = document.querySelector('meta[name="anywidget:package"]');
    if (meta) return meta.getAttribute('content');
    // 2. Scan script data-src-file stems for a known module name
    //    (heuristic: first segment before "_" often indicates the package)
    const script = document.querySelector('script[type="text/x-python"][data-src-file]');
    if (script) {
      const stem = script.dataset.srcFile || '';
      const pkg  = stem.split('_')[0];
      if (pkg) return pkg;
    }
    // 3. Fallback: derive from the docs root URL last segment
    try {
      const parts = new URL(_DOCS_ROOT).pathname.replace(/\/$/, '').split('/');
      for (let i = parts.length - 1; i >= 0; i--) {
        const s = parts[i];
        if (s && s !== 'dev' && !/^v\d/.test(s)) return s;
      }
    } catch (_) {}
    return 'anyplotlib';
  }

  // ── per-badge click handler ───────────────────────────────────────────────

  function _attachBadgeHandlers() {
    // Use event delegation so badges added by SG after DOMContentLoaded also work.
    document.addEventListener('click', function (e) {
      const btn = e.target.closest('button.awi-activate-btn');
      if (!btn || btn.dataset.state) return;  // already loading/active/error

      // Disable ALL activate buttons and show ⏳ on all of them
      _setBadgesLoading();

      _boot()
        .then(() => _setBadgesActive())
        .catch(err => {
          console.error('[sphinx_anywidget] boot failed:', err);
          _setBadgesError(err);
        });
    });
  }

  // ── init ──────────────────────────────────────────────────────────────────

  function _init() {
    if (!_hasInteractiveFigures()) return;
    _attachBadgeHandlers();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', _init);
  } else {
    _init();
  }
})();


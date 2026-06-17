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

  /** Deliver a state-update message into the iframe for figId.
   *
   * rawValue is always a JSON-encoded string (Python serialises every trait
   * with json.dumps so numeric/boolean/object traits are not type-erased when
   * the iframe receives them).
   */
  function _postToIframe(figId, key, rawValue) {
    const iframe = document.querySelector(`iframe[data-awi-fig="${figId}"]`);
    if (iframe && iframe.contentWindow) {
      // JSON.parse recovers the real JS type (number, bool, array, object …).
      // Plain Python strings are also JSON-encoded (quoted), so they round-trip
      // correctly too.
      let value = rawValue;
      try { value = JSON.parse(rawValue); } catch (_) {}
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
await micropip.install(['traitlets', 'colorcet', 'toolz'])
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

# Pre-compiled interaction-event dispatcher.  The JS message handler calls
# this proxy DIRECTLY per frame instead of pyodide.runPythonAsync(code-string)
# — recompiling a code string every event costs ~1.2 ms in WASM (vs ~0.01 ms
# to call a ready function), which is the dominant per-frame cost of the
# Pyodide interaction path on a drag (30-60 events/sec).
def _awi_dispatch(fig_id, data):
    _w = _AWI_REGISTRY.get(fig_id)
    if _w is not None and hasattr(_w, '_dispatch_event'):
        _w._dispatch_event(data)
`));
    console.info('[sphinx_anywidget] anywidget stub installed');

    // 5.5  Stub traits in sys.modules using traitlets as the backend.
    //  traits (from Enthought) has a C extension (ctraits) so it can't be
    //  installed via micropip in Pyodide.  HyperSpy uses traits for HasTraits,
    //  trait types (CBool, Str, Enum, …) and Undefined — all of which have
    //  close equivalents in traitlets (the IPython fork of traits).  We
    //  install shim modules for traits, traits.api, traits.trait_errors, and
    //  traits.trait_numeric before the HyperSpy wheel is installed so that
    //  micropip's dep-resolution never even sees traits as a requirement.
    await _step('stub traits',
      pyodide.runPythonAsync(`
import sys
import traitlets as _tr

# ── Patch traits-only methods onto traitlets.HasTraits ────────────────
# traits.HasTraits has trait_get() / trait_set() / trait_names() etc.
# that traitlets dropped or renamed.  Patch them in so HyperSpy modules
# that call e.g.  obj.trait_get()  work transparently.
#
# Also patch __init__ to auto-register  _{name}_changed  methods as
# traitlets observers (traits magic that traitlets doesn't replicate).
_orig_HasTraits_init = _tr.HasTraits.__init__

def _patched_HasTraits_init(self, *args, **kwargs):
    # Call the original traitlets init first so that the object is fully
    # initialised before we wire any trait-change observers.  traits wires
    # _{name}_changed observers only after __init__ completes; traitlets
    # would fire them mid-init, so we defer registration to after init.
    _orig_HasTraits_init(self, *args, **kwargs)
    # Now register  _{name}_changed  auto-observers.
    cls = type(self)
    import inspect as _inspect
    for attr_name in dir(cls):
        if not attr_name.endswith('_changed'):
            continue
        inner = attr_name[1:-8]
        if not inner:
            continue
        if inner in cls.class_traits():
            method = getattr(cls, attr_name)
            if callable(method) and not isinstance(method, property):
                try:
                    sig = _inspect.signature(method)
                    # Exclude 'self' from count
                    nparams = len([p for p in sig.parameters.values()
                                   if p.name != 'self'
                                   and p.default is _inspect.Parameter.empty
                                   and p.kind not in (_inspect.Parameter.VAR_POSITIONAL,
                                                      _inspect.Parameter.VAR_KEYWORD)])
                except (ValueError, TypeError):
                    nparams = 3
                def _make_bridge(m, np):
                    def _bridge(change):
                        if np == 0:
                            m(self)
                        elif np == 1:
                            m(self, change['new'])
                        elif np == 2:
                            m(self, change['name'], change['new'])
                        else:
                            m(self, change['name'], change['old'], change['new'])
                    return _bridge
                self.observe(_make_bridge(method, nparams), names=[inner])

_tr.HasTraits.__init__ = _patched_HasTraits_init

def _trait_get(self, *names):
    """Return a dict of trait name → current value (traits API)."""
    if names:
        return {n: getattr(self, n) for n in names if n in self.traits()}
    return {n: getattr(self, n) for n in self.traits()}

def _trait_set(self, trait_change_notify=True, **kw):
    """Set multiple traits at once (traits API).  Silently skip coercion
    failures — traits does auto-coerce (CFloat accepts '7.5') but traitlets
    does not; skip rather than crash for preference loading."""
    for k, v in kw.items():
        if k not in self.traits():
            continue
        # Try the value as-is; if validation fails try common coercions.
        for candidate in (v, _coerce_trait_value(self.traits()[k], v)):
            try:
                setattr(self, k, candidate)
                break
            except Exception:
                pass

def _coerce_trait_value(trait, v):
    """Best-effort coercion of a string config value to the trait's type."""
    import traitlets as _tr2
    if isinstance(v, str):
        if isinstance(trait, _tr2.Bool):
            return v.lower() not in ('false', '0', 'no', '')
        if isinstance(trait, (_tr2.Int,)):
            try: return int(v)
            except: pass
        if isinstance(trait, (_tr2.Float,)):
            try: return float(v)
            except: pass
    return v

def _trait_names(self):
    return list(self.traits().keys())

def _get(self, *names):
    return _trait_get(self, *names)

def _on_trait_change(self, handler, trait_name, remove=False):
    """Register or remove a traits-style observer.

    Handles dotted paths like "_axes.slice" (traits list-item observation):
    watches each item in the list trait for changes to the child attribute,
    and re-wires when the list itself changes.
    """
    import inspect
    try:
        sig = inspect.signature(handler)
        nparams = len([p for p in sig.parameters.values()
                       if p.default is inspect.Parameter.empty
                       and p.kind not in (inspect.Parameter.VAR_POSITIONAL,
                                          inspect.Parameter.VAR_KEYWORD)])
    except (ValueError, TypeError):
        nparams = 3

    def _call_handler(change):
        if nparams == 0:
            handler()
        elif nparams == 1:
            handler(change['new'])
        elif nparams == 2:
            handler(change['name'], change['new'])
        else:
            handler(change['name'], change['old'], change['new'])

    if not hasattr(self, '_oti_bridges'):
        self._oti_bridges = {}
    if not hasattr(self, '_oti_item_bridges'):
        self._oti_item_bridges = {}

    if '.' in trait_name:
        # dotted path: "list_trait.child_attr"
        list_trait, child_attr = trait_name.split('.', 1)

        key = (id(handler), trait_name)
        if remove:
            # unobserve child bridges already registered
            for item_bridge, item in self._oti_item_bridges.pop(key, []):
                try:
                    item.unobserve(item_bridge, names=[child_attr])
                except Exception:
                    pass
            list_bridge = self._oti_bridges.pop(key, None)
            if list_bridge:
                try:
                    self.unobserve(list_bridge, names=[list_trait])
                except Exception:
                    pass
            return

        # Track per-item bridges so we can remove them
        self._oti_item_bridges[key] = []

        def _observe_item(item):
            def _item_bridge(change):
                _call_handler(change)
            _item_bridge.__name__ = getattr(handler, '__name__', 'handler') + '_item'
            item.observe(_item_bridge, names=[child_attr])
            self._oti_item_bridges[key].append((_item_bridge, item))

        # Observe existing items now
        existing = getattr(self, list_trait, None)
        if existing:
            for item in existing:
                if hasattr(item, 'observe'):
                    _observe_item(item)

        # Watch the list for new items being added
        def _list_changed(change):
            new_list = change.get('new', []) or []
            old_list = change.get('old', []) or []
            added = [x for x in new_list if x not in old_list]
            for item in added:
                if hasattr(item, 'observe'):
                    _observe_item(item)
            # Also call handler when list changes (slice assignment etc.)
            _call_handler(change)

        _list_changed.__name__ = getattr(handler, '__name__', 'handler') + '_list'
        self.observe(_list_changed, names=[list_trait])
        self._oti_bridges[key] = _list_changed
    else:
        # simple trait name
        def _bridge(change):
            _call_handler(change)
        _bridge.__name__ = getattr(handler, '__name__', 'handler')
        key = (id(handler), trait_name)
        if not remove:
            self.observe(_bridge, names=[trait_name])
            self._oti_bridges[key] = _bridge
        else:
            bridge = self._oti_bridges.pop(key, None)
            if bridge:
                try:
                    self.unobserve(bridge, names=[trait_name])
                except Exception:
                    pass

if not hasattr(_tr.HasTraits, 'trait_get'):
    _tr.HasTraits.trait_get  = _trait_get
if not hasattr(_tr.HasTraits, 'trait_set'):
    _tr.HasTraits.trait_set  = _trait_set
if not hasattr(_tr.HasTraits, 'trait_names'):
    _tr.HasTraits.trait_names = _trait_names
if not hasattr(_tr.HasTraits, 'get'):
    _tr.HasTraits.get = _get
def _add_trait(self, name, trait_class_or_inst):
    """traits API: add_trait(name, TraitClass) — add a dynamic trait."""
    if isinstance(trait_class_or_inst, type):
        inst = trait_class_or_inst()
    else:
        inst = trait_class_or_inst
    self.add_traits(**{name: inst})

if not hasattr(_tr.HasTraits, 'on_trait_change'):
    _tr.HasTraits.on_trait_change = _on_trait_change
if not hasattr(_tr.HasTraits, 'add_trait'):
    _tr.HasTraits.add_trait = _add_trait

# ── Undefined sentinel (traitlets already has one) ──────────────────
Undefined = _tr.Undefined

# ── TraitError ────────────────────────────────────────────────────────
TraitError = _tr.TraitError

# ── Trait descriptor factory ─────────────────────────────────────────
# traits.Property needs a callable that returns a descriptor. We use a
# simple traitlets.Any with optional validator/observer hooks.
class _Property(_tr.Any):
    def __init__(self, *args, fget=None, fset=None, depends_on=None, **kw):
        super().__init__(None, allow_none=True, **kw)

class _Event(_tr.Any):
    """Fires-and-forgets; observers receive the new value."""
    def __init__(self, *args, **kw):
        super().__init__(None, allow_none=True, **kw)

class _Button(_tr.Any):
    def __init__(self, *args, **kw):
        super().__init__(None, allow_none=True, **kw)

# ── Array placeholder ─────────────────────────────────────────────────
class _Array(_tr.Any):
    def __init__(self, *args, **kw):
        super().__init__(None, allow_none=True, **kw)

# ── Str: traits.Str accepts Undefined as a valid value (used as
#    "not set" sentinel in HyperSpy axes).  Use Any so any value works. ──
class _TraitsStr(_tr.Any):
    def __init__(self, default_value='', **kw):
        kw.setdefault('allow_none', True)
        super().__init__(default_value, **kw)

# ── List: traits.List(SomeClass) means typed list; traitlets.List needs
#    an Instance trait, not a class, as the first arg. ──────────────────
class _TraitsList(_tr.List):
    def __init__(self, trait_or_type=None, value=None, **kw):
        if isinstance(trait_or_type, type):
            # traits API: List(SomeClass) — element type
            trait = _tr.Instance(trait_or_type)
        else:
            trait = trait_or_type
        super().__init__(trait=trait, **kw)

# ── Enum: traitlets.UseEnum needs an actual enum.Enum class;
#    traits.Enum takes *values* instead.  Bridge with a custom class. ──
class _TraitsEnum(_tr.TraitType):
    def __init__(self, values, **kw):
        self._allowed = list(values)
        super().__init__(self._allowed[0] if self._allowed else None, **kw)
    def validate(self, obj, value):
        if value in self._allowed:
            return value
        raise _tr.TraitError(
            f"The value {value!r} is not in {self._allowed!r}"
        )

# ── Range ─────────────────────────────────────────────────────────────
class _Range(_tr.Any):
    def __init__(self, low=None, high=None, value=None, **kw):
        super().__init__(value if value is not None else low, allow_none=True, **kw)

# ── Instance: traits.Instance(SomeClass) allows None by default;
#    traitlets.Instance doesn't.  Wrap to force allow_none=True. ─────────
class _Instance(_tr.Instance):
    def __init__(self, klass=None, args=None, **kw):
        kw.setdefault('allow_none', True)
        super().__init__(klass, args=args, **kw)

# ── WeakRef stub ──────────────────────────────────────────────────────
class _WeakRef(_tr.Any):
    def __init__(self, *a, **kw):
        super().__init__(None, allow_none=True)

# ── Delegate / DelegatesTo / PrototypedFrom stubs ─────────────────────
class _Delegate(_tr.Any):
    def __init__(self, *a, **kw):
        super().__init__(None, allow_none=True)

# ── Type stub ─────────────────────────────────────────────────────────
class _Type(_tr.Type):
    pass

# ── Build traits.api namespace ─────────────────────────────────────────
import types as _types

_traits_api = _types.ModuleType('traits.api')

# Map the most-used traits names onto traitlets equivalents or our shims.
_traits_api.HasTraits        = _tr.HasTraits
_traits_api.HasStrictTraits  = _tr.HasTraits
_traits_api.HasPrivateTraits = _tr.HasTraits
_traits_api.HasRequiredTraits= _tr.HasTraits
_traits_api.Interface        = _tr.HasTraits
_traits_api.Undefined        = Undefined
_traits_api.TraitError       = TraitError
_traits_api.Bool             = _tr.Bool
_traits_api.CBool            = _tr.Bool
_traits_api.BaseBool         = _tr.Bool
_traits_api.BaseCBool        = _tr.Bool
_traits_api.Int              = _tr.Int
_traits_api.CInt             = _tr.Int
_traits_api.BaseInt          = _tr.Int
_traits_api.BaseCInt         = _tr.Int
_traits_api.Float            = _tr.Float
_traits_api.CFloat           = _tr.Float
_traits_api.BaseFloat        = _tr.Float
_traits_api.BaseCFloat       = _tr.Float
_traits_api.Complex          = _tr.Complex
_traits_api.CComplex         = _tr.Complex
_traits_api.BaseComplex      = _tr.Complex
_traits_api.BaseCComplex     = _tr.Complex
_traits_api.Str              = _TraitsStr
_traits_api.CStr             = _TraitsStr
_traits_api.String           = _TraitsStr
_traits_api.BaseStr          = _TraitsStr
_traits_api.BaseCStr         = _TraitsStr
_traits_api.Bytes            = _tr.Bytes
_traits_api.CBytes           = _tr.Bytes
_traits_api.BaseBytes        = _tr.Bytes
_traits_api.Any              = _tr.Any
_traits_api.List             = _TraitsList
_traits_api.CList            = _TraitsList
_traits_api.Set              = _tr.Set
_traits_api.CSet             = _tr.Set
_traits_api.Dict             = _tr.Dict
_traits_api.Tuple            = _tr.Tuple
_traits_api.Instance         = _Instance
_traits_api.BaseInstance     = _Instance
_traits_api.AdaptedTo        = _Instance
_traits_api.AdaptsTo         = _Instance
_traits_api.Type             = _tr.Type
_traits_api.Subclass         = _tr.Type
_traits_api.Enum             = _TraitsEnum
_traits_api.BaseEnum         = _TraitsEnum
_traits_api.Range            = _Range
_traits_api.BaseRange        = _Range
_traits_api.Property         = _Property
_traits_api.Event            = _Event
_traits_api.Button           = _Button
_traits_api.ToolbarButton    = _Button
_traits_api.WeakRef          = _WeakRef
_traits_api.Delegate         = _Delegate
_traits_api.DelegatesTo      = _Delegate
_traits_api.PrototypedFrom   = _Delegate
_traits_api.Callable         = _tr.Callable
_traits_api.BaseCallable     = _tr.Callable
_traits_api.Either           = _tr.Union
_traits_api.Union            = _tr.Union
_traits_api.ReadOnly         = _tr.Any
_traits_api.Disallow         = _tr.Any
_traits_api.Constant         = _tr.Any
_traits_api.PrefixList       = _tr.List
_traits_api.PrefixMap        = _tr.Dict
_traits_api.Map              = _tr.Dict
_traits_api.Expression       = _tr.Any
_traits_api.PythonValue      = _tr.Any
_traits_api.File             = _tr.Unicode
_traits_api.Directory        = _tr.Unicode
_traits_api.BaseFile         = _tr.Unicode
_traits_api.BaseDirectory    = _tr.Unicode
_traits_api.HTML             = _tr.Unicode
_traits_api.Password         = _tr.Unicode
_traits_api.Regex            = _tr.Unicode
_traits_api.Code             = _tr.Unicode
_traits_api.Title            = _tr.Unicode
_traits_api.UUID             = _tr.Unicode
_traits_api.Date             = _tr.Any
_traits_api.Datetime         = _tr.Any
_traits_api.Time             = _tr.Any
_traits_api.Supports         = _tr.Any
_traits_api.Python           = _tr.Any
_traits_api.Module           = _tr.Any
_traits_api.Self             = _tr.Any
_traits_api.This             = _tr.Any
_traits_api.self             = _tr.Any
_traits_api.ValidatedTuple   = _tr.Tuple
_traits_api.Array            = _Array

# observers/decorators
_traits_api.observe          = _tr.observe
_traits_api.on_trait_change  = lambda *a, **kw: (lambda f: f)
_traits_api.cached_property  = property
_traits_api.property_depends_on = lambda *a, **kw: (lambda f: f)
_traits_api.provides         = lambda *a, **kw: (lambda cls: cls)
_traits_api.isinterface      = lambda x: False

# meta classes
_traits_api.MetaHasTraits     = type(_tr.HasTraits)
_traits_api.ABCHasTraits      = _tr.HasTraits
_traits_api.ABCHasStrictTraits= _tr.HasTraits
_traits_api.ABCMetaHasTraits  = type(_tr.HasTraits)
_traits_api.AbstractViewElement = _tr.HasTraits

# misc
_traits_api.Trait            = _tr.Any
_traits_api.Default          = lambda *a, **kw: None
_traits_api.Vetoable         = _tr.HasTraits
_traits_api.VetoableEvent    = _Event

# ── traits.trait_errors module ────────────────────────────────────────
_te = _types.ModuleType('traits.trait_errors')
_te.TraitError             = TraitError
_te.TraitNotificationError = TraitError
_te.DelegationError        = TraitError

# ── traits.trait_numeric module ───────────────────────────────────────
_tn = _types.ModuleType('traits.trait_numeric')
_tn.Array = _Array

# ── traits.etsconfig module ────────────────────────────────────────────
_etc = _types.ModuleType('traits.etsconfig')
_etc_api = _types.ModuleType('traits.etsconfig.api')
class _ETSConfig:
    toolkit = ''
_etc_api.ETSConfig = _ETSConfig()
_etc.api = _etc_api

# ── traits.constants ──────────────────────────────────────────────────
_tc = _types.ModuleType('traits.constants')
_tc.ComparisonMode  = None
_tc.DefaultValue    = None
_tc.TraitKind       = None
_tc.ValidateTrait   = None
_tc.NO_COMPARE      = None
_tc.OBJECT_IDENTITY_COMPARE = None
_tc.RICH_COMPARE    = None

# ── Register all in sys.modules ───────────────────────────────────────
_traits_root = _types.ModuleType('traits')
_traits_root.api         = _traits_api
_traits_root.trait_errors= _te
_traits_root.trait_numeric= _tn
_traits_root.etsconfig   = _etc
_traits_root.constants   = _tc
_traits_root.__version__ = '9999.0.0'

sys.modules['traits']                = _traits_root
sys.modules['traits.api']            = _traits_api
sys.modules['traits.trait_errors']   = _te
sys.modules['traits.trait_numeric']  = _tn
sys.modules['traits.etsconfig']      = _etc
sys.modules['traits.etsconfig.api']  = _etc_api
sys.modules['traits.constants']      = _tc
print('[sphinx_anywidget] traits shim installed')
`));
    console.info('[sphinx_anywidget] traits shim installed');

    // 5.6  Stub rosettasciio (rsciio) in sys.modules.
    //  rosettasciio has one Bruker C extension but otherwise is pure Python.
    //  HyperSpy imports rsciio.utils.{path,rgb} and rsciio.IO_PLUGINS at
    //  module-level.  Provide minimal stubs so HyperSpy starts up cleanly
    //  without needing the real package installed.
    await _step('stub rsciio',
      pyodide.runPythonAsync(`
import sys, types as _types
import numpy as _np

# ── rsciio.utils.path ─────────────────────────────────────────────────
from pathlib import Path as _Path

def _append2pathname(filename, to_append):
    p = _Path(filename)
    return _Path(p.parent, p.stem + to_append + p.suffix)

def _incremental_filename(filename, i=1):
    filename = _Path(filename)
    if filename.is_file():
        nf = _append2pathname(filename, f"-{i}")
        return _incremental_filename(filename, i+1) if nf.is_file() else nf
    return filename

def _ensure_directory(path):
    p = _Path(path)
    p = p.parent if p.is_file() else p
    try: p.mkdir(parents=True, exist_ok=False)
    except FileExistsError: pass

def _overwrite(filename): return True  # no interactive prompts in Pyodide

_rp = _types.ModuleType('rsciio.utils.path')
_rp.append2pathname    = _append2pathname
_rp.incremental_filename = _incremental_filename
_rp.ensure_directory   = _ensure_directory
_rp.overwrite          = _overwrite

# ── rsciio.utils.rgb ──────────────────────────────────────────────────
_RGBA8  = _np.dtype({"names": ["R","G","B","A"], "formats":["u1","u1","u1","u1"]})
_RGB8   = _np.dtype({"names": ["R","G","B"],     "formats":["u1","u1","u1"]})
_RGBA16 = _np.dtype({"names": ["R","G","B","A"], "formats":["u2","u2","u2","u2"]})
_RGB16  = _np.dtype({"names": ["R","G","B"],     "formats":["u2","u2","u2"]})
RGB_DTYPES = {"rgb8": _RGB8, "rgb16": _RGB16, "rgba8": _RGBA8, "rgba16": _RGBA16}

def _is_rgba(a): return a.dtype in (_RGBA8, _RGBA16)
def _is_rgb(a):  return a.dtype in (_RGB8,  _RGB16)
def _is_rgbx(a): return _is_rgb(a) or _is_rgba(a)

def _rgbx2regular_array(data, plot_friendly=False, show_progressbar=True):
    dt = data.dtype
    names = list(dt.names)
    arr = _np.stack([data[n] for n in names], axis=-1)
    if plot_friendly and arr.dtype != _np.uint8:
        arr = arr.astype(float) / _np.iinfo(arr.dtype).max
    return arr

def _regular_array2rgbx(data, **kw):
    n = data.shape[-1]
    names = ["R","G","B","A"][:n]
    dt = _np.dtype({"names": names, "formats": [data.dtype]*n})
    out = _np.empty(data.shape[:-1], dtype=dt)
    for i, nm in enumerate(names):
        out[nm] = data[...,i]
    return out

_rrgb = _types.ModuleType('rsciio.utils.rgb')
_rrgb.RGB_DTYPES           = RGB_DTYPES
_rrgb.is_rgba              = _is_rgba
_rrgb.is_rgb               = _is_rgb
_rrgb.is_rgbx              = _is_rgbx
_rrgb.rgbx2regular_array   = _rgbx2regular_array
_rrgb.regular_array2rgbx   = _regular_array2rgbx

# ── rsciio.utils (parent) ─────────────────────────────────────────────
_ru = _types.ModuleType('rsciio.utils')
_ru.path = _rp
_ru.rgb  = _rrgb

# ── rsciio root ───────────────────────────────────────────────────────
_rsciio = _types.ModuleType('rsciio')
_rsciio.utils      = _ru
_rsciio.IO_PLUGINS = []
_rsciio.__version__ = '9999.0.0'

sys.modules['rsciio']                = _rsciio
sys.modules['rsciio.utils']          = _ru
sys.modules['rsciio.utils.path']     = _rp
sys.modules['rsciio.utils.rgb']      = _rrgb
print('[sphinx_anywidget] rsciio shim installed')

# ── natsort stub ──────────────────────────────────────────────────────
_natsort = _types.ModuleType('natsort')
_natsort.natsorted       = sorted
_natsort.natsort_keygen  = lambda *a, **kw: (lambda x: x)
_natsort.ns              = type('ns', (), {'DEFAULT': 0, 'REAL': 1, 'LOCALE': 2})()
sys.modules['natsort'] = _natsort

# ── prettytable stub ──────────────────────────────────────────────────
_pt = _types.ModuleType('prettytable')
class _PrettyTable:
    def __init__(self, *a, **kw): self._rows = []
    def add_row(self, row): self._rows.append(row)
    def __str__(self): return str(self._rows)
_pt.PrettyTable = _PrettyTable
sys.modules['prettytable'] = _pt

print('[sphinx_anywidget] misc stubs installed')
`));
    console.info('[sphinx_anywidget] rsciio shim installed');

    // 6. Install package wheel via micropip.
    //    anywidget is already stubbed in sys.modules (step 5).  Register it as
    //    a mock package so micropip does not try to download it from PyPI when
    //    it resolves the wheel's declared deps.  numpy/traitlets/colorcet are
    //    properly installed above so micropip will find them and skip them.
    //    We do NOT pass deps=False — that triggers a micropip 0.7.x internal
    //    bug ("attempted to install wheel before downloading it").

    // Collect all _PYODIDE_MOCK_PACKAGES declared by any example on this page
    // so they can be registered as mock packages BEFORE the wheel install.
    // (Dep resolution happens during install, not during exec.)
    const _globalMockPkgs = [];
    for (const s of document.querySelectorAll(
        'script[type="text/x-python"][data-pyodide-mock-packages]')) {
      try {
        const pkgs = JSON.parse(s.dataset.pyodideMockPackages || '[]');
        for (const p of pkgs) if (!_globalMockPkgs.includes(p)) _globalMockPkgs.push(p);
      } catch (_) {}
    }

    const wheelUrl = _DOCS_ROOT + '_static/wheels/';
    // Discover wheel name: try the configured package name from the <script>
    // data-package attribute injected by _build_pyodide_wheel, else fall back
    // to scanning data-src-file scripts for a clue.
    const pkgName = _inferPackageName();
    const fullWheelUrl = wheelUrl + pkgName + '-0.0.0-py3-none-any.whl';
    console.info('[sphinx_anywidget] installing wheel from', fullWheelUrl);
    const _mockList = JSON.stringify(['anywidget', ..._globalMockPkgs]);
    await _step('install wheel', pyodide.runPythonAsync(`
import micropip
# Register anywidget + any page-level mock packages so micropip skips them
# during dep resolution.  Our sys.modules stub takes priority at import time.
for _pkg in ${_mockList}:
    try:
        micropip.add_mock_package(_pkg, "9999.0.0")
    except Exception:
        pass
del _pkg
await micropip.install(${JSON.stringify(fullWheelUrl)})
`));
    console.info('[sphinx_anywidget] package wheel installed');

    // 6.5 Patch BaseDataAxis._update_slice to notify AxesManager
    //  When traits observes "_axes.slice" (dotted path), it calls
    //  AxesManager._on_slice_changed → _update_attributes() each time any
    //  axis's slice changes.  Our traitlets shim handles dotted paths by
    //  registering item-level observers, but those are set up during
    //  AxesManager.__init__ *before* the wheel is installed.  Patching
    //  _update_slice directly is the most reliable alternative: after each
    //  slice assignment the axes_manager (if already set) re-classifies axes.
    await pyodide.runPythonAsync(`
from hyperspy.axes import BaseDataAxis as _BDA, AxesManager as _AM
_orig_update_slice = _BDA._update_slice

def _patched_update_slice(self, value):
    _orig_update_slice(self, value)
    am = getattr(self, 'axes_manager', None)
    if am is not None and hasattr(am, '_update_attributes'):
        am._update_attributes()

_BDA._update_slice = _patched_update_slice
print('[sphinx_anywidget] BaseDataAxis._update_slice patched for traitlets compat')
`).catch(e => console.warn('[DIAG] _update_slice patch failed:', e.message));

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
        # Always JSON-encode so the JS bridge can JSON.parse to recover the
        # correct type — strings, numbers, bools and objects all round-trip.
        val_str = _j.dumps(val, default=str)
        js.window._anywidgetPush(fid, tname, val_str)

    self.observe(_push_cb, names=_tr.All)

_aw.AnyWidget.__init__ = _patched_init
print('[sphinx_anywidget] anywidget monkey-patch installed')
`));
    console.info('[sphinx_anywidget] monkey-patch installed');

    // 8. Collect text/x-python script blocks, group by src-file so each
    //    example source runs exactly once even with multiple figures.
    const srcGroups = new Map();  // srcFile → { src, pairs, packages, mockPackages }

    for (const script of document.querySelectorAll(
        'script[type="text/x-python"][data-fig-id]')) {
      const srcFile  = script.dataset.srcFile  || '__default__';
      const figId    = script.dataset.figId;
      const figIndex = parseInt(script.dataset.figIndex || '0', 10);
      let src = '';
      try { src = JSON.parse(script.dataset.src || 'null') || ''; } catch (_) {}
      let packages = [];
      try { packages = JSON.parse(script.dataset.pyodidePackages || 'null') || []; } catch (_) {}
      let mockPackages = [];
      try { mockPackages = JSON.parse(script.dataset.pyodideMockPackages || 'null') || []; } catch (_) {}

      if (!srcGroups.has(srcFile)) srcGroups.set(srcFile, { src, pairs: [], packages, mockPackages });
      const grp = srcGroups.get(srcFile);
      grp.pairs.push({ figId, figIndex });
      // Merge any packages declared by any script tag for this source file.
      for (const p of packages) if (!grp.packages.includes(p)) grp.packages.push(p);
      for (const p of mockPackages) if (!grp.mockPackages.includes(p)) grp.mockPackages.push(p);
    }

    for (const g of srcGroups.values())
      g.pairs.sort((a, b) => a.figIndex - b.figIndex);

    // 9. Run each example source once, assign _anywidget_fig_id in creation
    //    order, then push current state into the matching iframes.
    const _execErrors = [];
    for (const [srcFile, { src, pairs, packages, mockPackages }] of srcGroups) {
      const figIdList = JSON.stringify(pairs.map(p => p.figId));
      console.info(`[sphinx_anywidget] running: ${srcFile} (${pairs.length} figure(s))`);
      const _srcFileRepr = JSON.stringify(srcFile);

      // Load any extra packages declared by this example (e.g. scipy).
      if (packages.length > 0) {
        console.info(`[sphinx_anywidget] loading extra packages for ${srcFile}:`, packages);
        await _step(`load packages for ${srcFile}`,
          pyodide.loadPackage(packages));
        console.info(`[sphinx_anywidget] extra packages loaded for ${srcFile}`);
      }

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
            # Always JSON-encode (matching the live observer above) so the
            # JS bridge can JSON.parse to recover the correct type.
            _vs = _jj.dumps(_val, default=str)
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

    // 10. Route awi_event messages from iframes → Pyodide callbacks.
    // Call the pre-compiled _awi_dispatch proxy DIRECTLY (no runPythonAsync
    // code-string recompile per frame — that was ~1.2 ms/event in WASM, the
    // dominant per-frame cost of the Pyodide interaction path; the proxy is
    // ~50x faster).  Synchronous call: _dispatch_event itself is sync, and
    // skipping the async wrapper removes a microtask hop per event.
    // The proxy is fetched lazily + cached (robust to any boot-step ordering),
    // with a one-shot runPythonAsync fallback if it isn't available.
    let _awiDispatch = null;
    window.addEventListener('message', (e) => {
      if (!e.data || e.data.type !== 'awi_event') return;
      const { figId, data } = e.data;
      try {
        if (!_awiDispatch) {
          try { _awiDispatch = pyodide.globals.get('_awi_dispatch'); } catch (_) {}
        }
        if (_awiDispatch) {
          _awiDispatch(figId, data);
        } else {
          // Fallback (should not happen): recompiled dispatch.
          pyodide.runPythonAsync(
            `_awi_dispatch(${JSON.stringify(figId)}, ${JSON.stringify(data)})`);
        }
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
    // 0. Authoritative: set by anywidget_config.js (written at build time)
    if (window._anywidgetPackage) return window._anywidgetPackage;
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


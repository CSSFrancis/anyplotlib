// figure_esm.js
// Unified JS renderer for the Figure widget.
// Each panel gets its own three-canvas stack (plot / overlay / markers).
// Panels are drawn independently; only the changed panel's listener fires.

function render({ model, el, onResize }) {
  const dpr = window.devicePixelRatio || 1;

  // ── shared plot-area padding (mirrors 1D drawing constants) ─────────────
  // The image/plot area for BOTH 1D and 2D panels sits at:
  //   x: PAD_L → pw-PAD_R,   y: PAD_T → ph-PAD_B
  // This guarantees pixel-perfect alignment of all panels in a row/column.
  const PAD_L=58, PAD_R=12, PAD_T=12, PAD_B=42;

  // Tile-mode render diagnostics. OFF by default — a console.warn PER ANIMATION
  // FRAME per panel floods the teed renderer console (and the host app's log
  // relay) in normal use. Opt in with globalThis.__apl_tiledbg=true when
  // debugging a render decision ("why is it blurry / white / flashing"): it logs
  // which texture/passes drew, the detail region, and the contrast window.
  if (globalThis.__apl_tiledbg === undefined) globalThis.__apl_tiledbg = false;
  function _tiledbg(tag, msg) {
    if (!globalThis.__apl_tiledbg) return;
    try { console.warn(`[TILEDBG-JS:${tag}] ${msg}`); } catch (_) {}
  }

  // ── theme ────────────────────────────────────────────────────────────────
  function _isDarkBg(node) {
    while (node && node !== document.body) {
      const bg = window.getComputedStyle(node).backgroundColor;
      const m  = bg.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/);
      if (m) {
        const [r,g,b] = [+m[1],+m[2],+m[3]];
        if (!(r===0&&g===0&&b===0&&bg.includes('0)')))
          return (0.299*r + 0.587*g + 0.114*b) < 128;
      }
      node = node.parentElement;
    }
    return window.matchMedia('(prefers-color-scheme: dark)').matches;
  }

  function _makeTheme(dark) {
    return dark ? {
      bg:'#1e1e2e', bgPlot:'#181825', bgCanvas:'#181825',
      border:'#44475a', axisBg:'#1e1e2e',
      axisStroke:'rgba(98,114,164,0.5)', gridStroke:'rgba(98,114,164,0.18)',
      tickStroke:'#6272a4', tickText:'rgba(205,214,244,0.75)',
      unitText:'rgba(98,114,164,0.85)', dark:true,
    } : {
      bg:'#f0f0f0', bgPlot:'#ffffff', bgCanvas:'#ffffff',
      border:'#cccccc', axisBg:'#f0f0f0',
      axisStroke:'rgba(0,0,0,0.35)', gridStroke:'rgba(0,0,0,0.07)',
      tickStroke:'#666666', tickText:'rgba(40,40,40,0.85)',
      unitText:'rgba(100,100,100,0.85)', dark:false,
    };
  }

  let theme = _makeTheme(_isDarkBg(el));
  const _mq = window.matchMedia('(prefers-color-scheme: dark)');
  _mq.addEventListener('change', () => { theme = _makeTheme(_isDarkBg(el)); redrawAll(); });
  new MutationObserver(() => { theme = _makeTheme(_isDarkBg(el)); redrawAll(); })
    .observe(document.documentElement, { attributes:true,
      attributeFilter:['data-jp-theme-name','data-vscode-theme-kind','class'] });

  // ── shared math helpers ──────────────────────────────────────────────────
  function findNice(t) {
    if (t<=0) return 1;
    const mag = Math.pow(10, Math.floor(Math.log10(t)));
    let best=mag, bd=Math.abs(t-mag);
    for (const n of [1,2,2.5,5,10]) { const v=n*mag,d=Math.abs(t-v); if(d<bd){best=v;bd=d;} }
    return best;
  }
  function fmtVal(v) {
    const a=Math.abs(v);
    if(a===0) return '0';
    if(a>=1e4) return v.toExponential(1);
    if(a>=100) return v.toFixed(0);
    // Strip trailing zeros so a "nice" value reads compactly (2.00 → 2,
    // 0.2500 → 0.25) instead of overflowing labels/scale bar with dead digits.
    if(a>=1)   return stripZeros(v.toFixed(2));
    if(a>=1e-2)return stripZeros(v.toFixed(4));
    return v.toExponential(1);
  }
  function stripZeros(s){ return s.indexOf('.')<0 ? s : s.replace(/\.?0+$/,''); }
  function _axisValToFrac(arr,val) {
    if(arr.length<2) return 0;
    const n=arr.length, asc=arr[n-1]>=arr[0];
    if(asc?val<=arr[0]:val>=arr[0]) return 0;
    if(asc?val>=arr[n-1]:val<=arr[n-1]) return 1;
    let lo=0,hi=n-2;
    while(lo<hi){const mid=(lo+hi)>>1;const ok=asc?(arr[mid]<=val&&val<arr[mid+1]):(arr[mid]>=val&&val>arr[mid+1]);if(ok){lo=mid;break;}if(asc?arr[mid+1]<=val:arr[mid+1]>=val)lo=mid+1;else hi=mid;}
    return (lo+(val-arr[lo])/(arr[lo+1]-arr[lo]))/(n-1);
  }
  function _axisFracToVal(arr,frac) {
    if(arr.length<2) return arr.length?arr[0]:0;
    const n=arr.length, pos=Math.max(0,Math.min(1,frac))*(n-1), lo=Math.min(Math.floor(pos),n-2), t=pos-lo;
    return arr[lo]+t*(arr[lo+1]-arr[lo]);
  }
  // Blend a #rrggbb / #rgb colour toward white by `amt` (0=unchanged, 1=white).
  function _brightenColor(hex, amt=0.45) {
    if(!hex||hex[0]!=='#') return hex;
    let r,g,b;
    if(hex.length===4){r=parseInt(hex[1]+hex[1],16);g=parseInt(hex[2]+hex[2],16);b=parseInt(hex[3]+hex[3],16);}
    else{r=parseInt(hex.slice(1,3),16);g=parseInt(hex.slice(3,5),16);b=parseInt(hex.slice(5,7),16);}
    if(isNaN(r)||isNaN(g)||isNaN(b)) return hex;
    r=Math.min(255,Math.round(r+(255-r)*amt));g=Math.min(255,Math.round(g+(255-g)*amt));b=Math.min(255,Math.round(b+(255-b)*amt));
    return `#${r.toString(16).padStart(2,'0')}${g.toString(16).padStart(2,'0')}${b.toString(16).padStart(2,'0')}`;
  }

  // ── b64 array decode helpers ─────────────────────────────────────────────
  // Convert a base-64 string (little-endian raw bytes) to a JS TypedArray.
  // TypedArrays support .length and [i] indexing so they are drop-in
  // replacements for plain arrays in all draw / hit-test functions.
  function _decodeF64(b64) {
    const bin = atob(b64);
    const buf = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) buf[i] = bin.charCodeAt(i);
    return new Float64Array(buf.buffer);
  }
  function _decodeF32(b64) {
    const bin = atob(b64);
    const buf = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) buf[i] = bin.charCodeAt(i);
    return new Float32Array(buf.buffer);
  }
  function _decodeI32(b64) {
    const bin = atob(b64);
    const buf = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) buf[i] = bin.charCodeAt(i);
    return new Int32Array(buf.buffer);
  }

  // ── rich-text (mini-TeX) label engine ───────────────────────────────────
  // Canvas cannot run MathJax, so labels support a small TeX subset that
  // covers scientific axis labels.  Inside $...$ delimiters:
  //   ^{...} / ^x      superscript (exponents)        $10^{-3}$, $x^2$
  //   _{...} / _x      subscript                      $E_F$, $k_{B}T$
  //   \alpha ... \Omega  Greek letters                $\mu m$, $\Delta E$
  //   \times \cdot \pm \degree \AA \infty \propto \approx \leq \geq \neq
  //   \partial \nabla \hbar \rightarrow \leftarrow \sum \int \sqrt \prime
  //   \mathrm{...}     upright (non-italic) text inside math
  // Letters in math mode render italic; text outside $...$ is untouched.
  // \$ renders a literal dollar sign.  Nested scripts are flattened to one
  // level.  Python passes label strings through verbatim — all parsing
  // happens here at draw time.
  const _TEX_SYM = {
    alpha:'α', beta:'β', gamma:'γ', delta:'δ', epsilon:'ε', varepsilon:'ε',
    zeta:'ζ', eta:'η', theta:'θ', vartheta:'ϑ', iota:'ι', kappa:'κ',
    lambda:'λ', mu:'μ', nu:'ν', xi:'ξ', pi:'π', rho:'ρ', sigma:'σ',
    tau:'τ', upsilon:'υ', phi:'φ', varphi:'φ', chi:'χ', psi:'ψ', omega:'ω',
    Gamma:'Γ', Delta:'Δ', Theta:'Θ', Lambda:'Λ', Xi:'Ξ', Pi:'Π',
    Sigma:'Σ', Upsilon:'Υ', Phi:'Φ', Psi:'Ψ', Omega:'Ω',
    times:'×', cdot:'·', pm:'±', mp:'∓', deg:'°', degree:'°', circ:'°',
    AA:'Å', angstrom:'Å', infty:'∞', propto:'∝', approx:'≈', sim:'~',
    le:'≤', leq:'≤', ge:'≥', geq:'≥', ne:'≠', neq:'≠',
    rightarrow:'→', to:'→', leftarrow:'←', leftrightarrow:'↔',
    partial:'∂', nabla:'∇', hbar:'ℏ', ell:'ℓ', prime:'′',
    sqrt:'√', sum:'Σ', int:'∫', langle:'⟨', rangle:'⟩',
  };

  // Parse a label into runs: [{t, lvl, it}] — lvl 0 normal / +1 sup / -1 sub.
  function _texRuns(text) {
    const runs = [];
    const s = String(text);
    const n = s.length;
    let i = 0, math = false;
    let buf = '', bufLvl = 0, bufIt = false;
    const flush = () => { if (buf) { runs.push({ t: buf, lvl: bufLvl, it: bufIt }); buf = ''; } };
    const emit = (t, lvl, it) => {
      if (lvl !== bufLvl || it !== bufIt) { flush(); bufLvl = lvl; bufIt = it; }
      buf += t;
    };
    // Read a {…} group (brace-balanced), a \command, or a single char.
    // Assumes i points just past the ^ / _ that introduced the group.
    function readGroup() {
      if (i < n && s[i] === '{') {
        let depth = 1, g = ''; i++;
        while (i < n) {
          const c = s[i];
          if (c === '{') depth++;
          else if (c === '}') { depth--; if (!depth) { i++; break; } }
          g += c; i++;
        }
        return g;
      }
      if (i < n && s[i] === '\\') {
        let j = i + 1, name = '';
        while (j < n && /[A-Za-z]/.test(s[j])) { name += s[j]; j++; }
        i = j;
        return '\\' + name;
      }
      return i < n ? s[i++] : '';
    }
    while (i < n) {
      const c = s[i];
      if (c === '\\' && s[i + 1] === '$') { emit('$', 0, false); i += 2; continue; }
      if (c === '$') { math = !math; i++; continue; }
      if (!math) { emit(c, 0, false); i++; continue; }
      if (c === '^' || c === '_') {
        i++;
        const lvl = c === '^' ? 1 : -1;
        // Re-parse group content in math mode so \symbols work inside {…};
        // nested scripts collapse to this run's level.
        for (const r of _texRuns('$' + readGroup() + '$')) emit(r.t, lvl, r.it);
        continue;
      }
      if (c === '\\') {
        let j = i + 1, name = '';
        while (j < n && /[A-Za-z]/.test(s[j])) { name += s[j]; j++; }
        if (name === 'mathrm' && s[j] === '{') {
          i = j;
          emit(readGroup(), 0, false);
          continue;
        }
        const sym = _TEX_SYM[name];
        emit(sym !== undefined ? sym : name, 0, false);
        i = j;
        if (s[i] === ' ') i++;   // TeX swallows the space after a command
        continue;
      }
      emit(c, 0, /[A-Za-z]/.test(c));   // math-mode letters are italic
      i++;
    }
    flush();
    return runs;
  }

  // Measure + position runs left-to-right at base size px.
  function _texLayout(ctx, text, px, weight, family) {
    const out = [];
    let xOff = 0;
    for (const r of _texRuns(text)) {
      const size = r.lvl ? Math.max(7, px * 0.68) : px;
      // Offsets are relative to the shared alphabetic baseline: superscripts
      // rise so their top roughly aligns with the base cap height (avoids
      // clipping in the 12-px title strip); subscripts drop below baseline.
      const dy   = r.lvl === 1 ? -px * 0.28 : r.lvl === -1 ? px * 0.16 : 0;
      const font = (r.it ? 'italic ' : '') + (weight ? weight + ' ' : '')
                 + size.toFixed(1) + 'px ' + family;
      ctx.font = font;
      out.push({ t: r.t, x: xOff, dy, font });
      xOff += ctx.measureText(r.t).width;
    }
    return { runs: out, w: xOff };
  }

  // Draw a (possibly TeX-formatted) label.  Respects the caller's fillStyle
  // and textBaseline; alignment is handled internally via opts.align so it
  // stays correct for multi-run TeX strings.
  //   _drawTex(ctx, '$10^{-3}$ counts', x, y, 12, {align:'right', weight:'bold'})
  function _drawTex(ctx, text, x, y, px, opts) {
    const o = opts || {};
    const family = o.family || 'sans-serif';
    const weight = o.weight || '';
    const t = text == null ? '' : String(text);
    if (!t) return;
    ctx.save();
    if (t.indexOf('$') === -1) {          // fast path — no math segments
      ctx.font = (weight ? weight + ' ' : '') + px + 'px ' + family;
      ctx.textAlign = o.align || 'center';
      ctx.fillText(t, x, y);
      ctx.restore();
      return;
    }
    const lay = _texLayout(ctx, t, px, weight, family);
    const align = o.align || 'center';
    let x0 = x;
    if (align === 'center') x0 = x - lay.w / 2;
    else if (align === 'right') x0 = x - lay.w;
    // Draw all runs on one shared alphabetic baseline so sup/sub offsets are
    // consistent across font sizes.  Convert the caller's baseline so TeX
    // text sits at exactly the same height a plain fillText would.
    // TextMetrics.fontBoundingBoxAscent is measured RELATIVE TO the current
    // textBaseline, so the alphabetic-baseline offset is the difference of
    // the ascent measured under each baseline.
    ctx.font = (weight ? weight + ' ' : '') + px + 'px ' + family;
    let yb = y;
    const fmCur = ctx.measureText('Mg');
    if (fmCur.fontBoundingBoxAscent != null) {
      const ascCur = fmCur.fontBoundingBoxAscent;
      ctx.textBaseline = 'alphabetic';
      yb = y + (ctx.measureText('Mg').fontBoundingBoxAscent - ascCur);
    } else {
      const bl = ctx.textBaseline;   // heuristic fallback (old browsers)
      if (bl === 'middle') yb = y + px * 0.30;
      else if (bl === 'top' || bl === 'hanging') yb = y + px * 0.78;
      else if (bl === 'bottom' || bl === 'ideographic') yb = y - px * 0.20;
      ctx.textBaseline = 'alphabetic';
    }
    ctx.textAlign = 'left';
    for (const r of lay.runs) {
      ctx.font = r.font;
      ctx.fillText(r.t, x0 + r.x, yb + r.dy);
    }
    ctx.restore();
  }

  // ── 2D gutter geometry helpers ───────────────────────────────────────────
  // Total width reserved for the colorbar (strip + rotated-label gutter).
  // 0 when the colorbar is hidden.  The image area shrinks by this amount so
  // the strip and its label always fit inside the panel.
  function _cbWidth(st) {
    if (!st || !st.show_colorbar || st.is_rgb) return 0;
    const labelW = st.colorbar_label
      ? Math.round((st.colorbar_label_size || 10) + 8) : 0;
    return 16 + labelW;
  }

  // Height of the title strip.  Stays at PAD_T for default-size plain titles
  // so existing layouts are pixel-identical; grows for title_size > 11 and
  // for TeX titles (superscripts rise above the cap height) so 2D titles are
  // never clipped.  1D/bar use the fixed strip and clamp the drawn size
  // instead (see _titlePx).
  function _padT(st) {
    if (!st || !st.title) return PAD_T;
    const ts = st.title_size || 11;
    const hasTex = String(st.title).indexOf('$') !== -1;
    if (ts <= 11 && !hasTex) return PAD_T;
    return Math.max(PAD_T, Math.ceil(ts * 1.3) + (hasTex ? 4 : 2));
  }

  // Drawn title size for panels with a fixed PAD_T strip (1D / bar): clamp
  // so ascenders, descenders, and TeX superscripts always fit.
  function _titlePx(st) {
    const ts = st.title_size || 11;
    const hasTex = st.title && String(st.title).indexOf('$') !== -1;
    return Math.min(ts, hasTex ? 10 : 11);
  }

  // ── shared constants ──────────────────────────────────────────────────────
  const STATS_DIV_CSS =
    'position:absolute;top:4px;left:4px;padding:4px 7px;' +
    'background:rgba(0,0,0,0.65);color:#e0e0e0;font-size:10px;' +
    'font-family:monospace;border-radius:4px;pointer-events:none;' +
    'white-space:pre;line-height:1.5;z-index:20;display:none;';

  // ── shared helpers ────────────────────────────────────────────────────────

  // Preserve JS-side view state when Python pushes data without requesting a
  // view change (_view_from_python === false).
  function _preserveView(p2, newState) {
    if (!p2.state) return;
    if (p2.kind === '2d' && !newState._view_from_python) {
      newState.zoom     = p2.state.zoom;
      newState.center_x = p2.state.center_x;
      newState.center_y = p2.state.center_y;
    } else if ((p2.kind === '1d' || p2.kind === 'bar') && !newState._view_from_python) {
      newState.view_x0 = p2.state.view_x0;
      newState.view_x1 = p2.state.view_x1;
    } else if (p2.kind === '3d' && !newState._view_from_python) {
      newState.azimuth   = p2.state.azimuth;
      newState.elevation = p2.state.elevation;
      newState.zoom      = p2.state.zoom;
    }
  }

  // Geometry channel: heavy keys (vertices/image/colormap) travel in a
  // separate panel_<id>_geom trait, re-sent only when they change.  The light
  // view payload carries _geom_rev; we cache the decoded geom per panel and
  // splice it into the state before drawing, so view-only updates (highlight,
  // camera, planes) never re-parse or re-transmit geometry.
  function _applyGeom(p2, state) {
    if (state._geom_rev === undefined) return state;   // panel has no geom channel
    // Splice the last-decoded geometry into the view state.  The geom trait
    // is sent before (or with) the first view payload and only re-sent on
    // change, so the cache is the authoritative geometry for every frame;
    // _geom_rev is carried for diagnostics / future invalidation but we
    // always apply the cache when present (never drop geometry on a rev skew).
    if (p2._geomCache) Object.assign(state, p2._geomCache);
    return state;
  }

  // Serialise a panel's VIEW state for the light `panel_<id>_json` trait,
  // EXCLUDING the heavy geometry keys that `_applyGeom` splices in from the
  // cache (`image_b64`, `colormap_data`, `*_b64`, and their binary `*_bytes`
  // companions).  The interaction handlers (wheel/pan/orbit) write the view
  // state back on every mouse tick; without this strip they re-serialise —
  // and re-transmit — the full frame each tick.  For the BINARY path that is
  // `JSON.stringify` of a Uint8Array → a `{"0":..,"1":..}` object with one
  // key per byte (millions of entries), which stalls zoom on large images.
  // Python's `_push` already keeps geometry off this trait; the echo-back
  // listener re-splices geom from `_geomCache`, so dropping it here is safe
  // (the geometry is never actually lost — only kept out of the light path).
  function _viewStateJson(p2) {
    const st = p2.state;
    if (!st) return '{}';
    const geom = p2._geomCache;
    if (!geom) return JSON.stringify(st);
    // Fast path: shallow-clone without the cached geom keys (and their
    // `_bytes` variants).  Object.keys(geom) is exactly what _applyGeom
    // merged in, so this auto-tracks any future geom key with no hardcoded
    // list to drift out of sync with the Python-side _GEOM_KEYS.
    const skip = new Set(Object.keys(geom));
    const view = {};
    for (const k in st) { if (!skip.has(k)) view[k] = st[k]; }
    return JSON.stringify(view);
  }

  // Parse the geom trait into the per-panel cache. PRESERVES any binary pixel
  // bytes (`*_bytes`, delivered on the companion trait) — the slimmed geom JSON
  // carries only the LUT/flags now, and it may arrive AFTER the binary frame, so
  // replacing the cache wholesale would drop the pixels. Re-splice them.
  function _loadGeom(p2, raw, rev) {
    try {
      const prev = p2._geomCache || {};
      const next = JSON.parse(raw || '{}');
      for (const k in prev) {
        if (k.endsWith('_bytes') && next[k] === undefined) next[k] = prev[k];
      }
      p2._geomCache = next;
      p2._geomRev = rev;
    } catch (_) {}
  }

  // Factory: returns a debounced commit function.
  // onCommit is called once per animation frame after the last request.
  function _makeCommitter(onCommit) {
    let pending = false;
    return function() {
      if (pending) return; pending = true;
      requestAnimationFrame(() => { pending = false; onCommit(); });
    };
  }

  // Factory: returns { clear(), arm(mx, my, e, extraFields?) } for the
  // pointer_settled dwell-timer pattern.  extraFields is an optional
  // zero-arg callback that returns extra fields to merge into the event.
  function _makeSettledScheduler(p) {
    let timer = null, startX = 0, startY = 0, startTs = 0;
    return {
      clear() { clearTimeout(timer); timer = null; },
      arm(mx, my, e, extraFields) {
        const ms = p.state?.pointer_settled_ms ?? 0;
        if (ms <= 0) return;
        const delta = p.state?.pointer_settled_delta ?? 4;
        clearTimeout(timer);
        startX = mx; startY = my; startTs = performance.now();
        const mods = _modifiers(e);
        timer = setTimeout(() => {
          if (Math.hypot(p.mouseX - startX, p.mouseY - startY) <= delta) {
            const _now = performance.now();
            _emitEvent(p.id, 'pointer_settled', null, {
              time_stamp: _now / 1000, modifiers: mods,
              button: null, buttons: 0,
              x: Math.round(p.mouseX), y: Math.round(p.mouseY),
              dwell_ms: _now - startTs,
              ...(extraFields ? extraFields() : {}),
            });
          }
        }, ms);
      }
    };
  }

  // ── per-panel frame timing ────────────────────────────────────────────────
  // Called at the entry of every draw function (draw2d / draw1d / draw3d /
  // drawBar).  Records a high-resolution timestamp in a 60-entry rolling
  // buffer on the panel object, then:
  //   • updates window._aplTiming[p.id]  — always, for Playwright readback
  //   • updates p.statsDiv text          — only when display_stats is true
  //
  // Placing the call at the *start* of each draw function means we measure
  // the inter-trigger interval: how often the CPU initiates a render, which
  // is the right metric for both interactive (pan/zoom) and data-push paths.
  const _FRAME_BUF = 60;

  function _recordFrame(p) {
    const now = performance.now();
    p.frameTimes.push(now);
    if (p.frameTimes.length > _FRAME_BUF) p.frameTimes.shift();

    const n = p.frameTimes.length;

    // Always keep the global timing dict fresh so Playwright can read it back
    // at any point via window._aplTiming[panelId].
    if (!window._aplTiming) window._aplTiming = {};

    if (n >= 2) {
      let sum = 0, minDt = Infinity, maxDt = -Infinity;
      for (let i = 1; i < n; i++) {
        const dt = p.frameTimes[i] - p.frameTimes[i - 1];
        sum += dt; if (dt < minDt) minDt = dt; if (dt > maxDt) maxDt = dt;
      }
      const mean_ms = sum / (n - 1);
      const fps     = 1000 * (n - 1) / (now - p.frameTimes[0]);
      window._aplTiming[p.id] = {
        count: n, fps, mean_ms, min_ms: minDt, max_ms: maxDt,
      };

      if (p.statsDiv && model.get('display_stats')) {
        p.statsDiv.style.display = 'block';
        p.statsDiv.textContent   =
          `FPS  ${fps.toFixed(1)}\n` +
          ` dt  ${mean_ms.toFixed(1)} ms\n` +
          `min  ${minDt.toFixed(1)} ms\n` +
          `max  ${maxDt.toFixed(1)} ms`;
      }
    }
  }
  // Static layout styles live in the _css traitlet (.apl-scale-wrap /
  // .apl-outer).  Only the two dynamic properties — transform and
  // marginBottom — are ever written here at runtime.
  const scaleWrap = document.createElement('div');
  scaleWrap.classList.add('apl-scale-wrap');
  el.appendChild(scaleWrap);

  const outerDiv = document.createElement('div');
  outerDiv.classList.add('apl-outer');
  scaleWrap.appendChild(outerDiv);

  const gridDiv = document.createElement('div');
  gridDiv.style.cssText = `display:grid;gap:4px;background:${theme.bg};padding:8px;border-radius:4px;`;
  outerDiv.appendChild(gridDiv);

  // ── Inset overlay container ───────────────────────────────────────────────
  // Covers the grid content area (inside gridDiv's 8 px padding).
  // Individual insetDivs restore pointer-events:all so they capture mouse events.
  const insetsContainer = document.createElement('div');
  insetsContainer.style.cssText =
    'position:absolute;top:8px;left:8px;pointer-events:none;z-index:20;overflow:visible;';
  outerDiv.appendChild(insetsContainer);

  // ── Callout overlay canvas ────────────────────────────────────────────────
  // A figure-level canvas covering the grid content area (inside gridDiv's
  // 8 px padding), used to draw mark_inset-style region indications: a dashed
  // source rectangle on the parent panel + leader lines out to the inset.
  // It spans the whole figure because leaders cross panel boundaries.  Sits
  // ABOVE panel content / insets but BELOW the maximized-inset float (z 45) and
  // the resize handle (z 100); pointer-events:none so it never eats clicks.
  const calloutCanvas = document.createElement('canvas');
  calloutCanvas.style.cssText =
    'position:absolute;top:8px;left:8px;pointer-events:none;z-index:30;';
  outerDiv.appendChild(calloutCanvas);
  const calloutCtx = calloutCanvas.getContext('2d');

  // ── Figure-level annotation overlay canvas ────────────────────────────────
  // Content annotations (text / circle / rect / arrow) positioned in FIGURE
  // FRACTIONS, drawn OVER all panels + insets + callouts.  These are CONTENT
  // (always exported), unlike the hover/selection outlines (DOM chrome, never
  // exported).  pointer-events default OFF so normal panel interaction is
  // untouched; toggled ON only while edit_chrome is active so the markers can
  // be dragged.  Sits above callouts (z 30) but below the resize handle (z 100).
  const figMarkerCanvas = document.createElement('canvas');
  figMarkerCanvas.style.cssText =
    'position:absolute;top:8px;left:8px;pointer-events:none;z-index:35;';
  outerDiv.appendChild(figMarkerCanvas);
  const figMarkerCtx = figMarkerCanvas.getContext('2d');

  // Inset layout constants
  const INSET_TITLE_H = 22;   // px — title bar height
  const INSET_GAP     = 8;    // px — gap between stacked insets in same corner
  const INSET_MARGIN  = 10;   // px — distance from figure edge to first inset

  // Resize handle (figure-level)
  const resizeHandle = document.createElement('div');
  resizeHandle.style.cssText =
    'position:absolute;bottom:2px;right:2px;width:16px;height:16px;cursor:nwse-resize;' +
    'background:linear-gradient(135deg,transparent 50%,#888 50%);border-radius:0 0 4px 0;z-index:100;';
  resizeHandle.title = 'Drag to resize figure';
  outerDiv.appendChild(resizeHandle);

  const sizeLabel = document.createElement('div');
  sizeLabel.style.cssText =
    'position:absolute;bottom:22px;right:22px;padding:7px 14px;background:rgba(0,0,0,0.65);' +
    'color:white;font-size:12px;font-family:monospace;border-radius:5px;display:none;pointer-events:none;z-index:21;';
  outerDiv.appendChild(sizeLabel);

  // ── Help badge (figure-level) ─────────────────────────────────────────────
  // A small '?' button in the top-right corner of the figure.
  //   • Hidden until the mouse enters outerDiv (plot "active").
  //   • Stays visible while the help card is open, even after mouse-leave.
  //   • Rounded square, tucked into the right padding band so it never
  //     overlaps plot content.
  //   • Clicking toggles the help card; click again (or mouse-leave with
  //     card closed) hides the button again.
  const _BTN_BG        = 'rgba(100,100,120,0.72)';
  const _BTN_BG_ACTIVE = 'rgba(75,120,210,0.92)';

  const helpBtn = document.createElement('div');
  helpBtn.style.cssText =
    'position:absolute;top:9px;right:6px;width:20px;height:20px;' +
    'border-radius:4px;background:' + _BTN_BG + ';color:#fff;' +
    'font-size:12px;font-weight:bold;font-family:sans-serif;' +
    'display:none;align-items:center;justify-content:center;' +
    'cursor:pointer;z-index:50;user-select:none;line-height:1;' +
    'box-shadow:0 1px 4px rgba(0,0,0,0.35);';
  helpBtn.textContent = '?';
  helpBtn.title = 'Show help';
  outerDiv.appendChild(helpBtn);

  const helpCard = document.createElement('div');
  helpCard.style.cssText =
    'position:absolute;top:33px;right:6px;padding:10px 14px;' +
    'background:rgba(28,28,38,0.95);color:#e0e0e8;font-size:12px;' +
    'font-family:sans-serif;border-radius:6px;line-height:1.7;' +
    'white-space:pre-wrap;max-width:300px;display:none;z-index:51;' +
    'box-shadow:0 4px 14px rgba(0,0,0,0.55);pointer-events:none;' +
    'border:1px solid rgba(120,120,160,0.3);';
  outerDiv.appendChild(helpCard);

  let _helpExists  = false;   // true when help_text is non-empty
  let _helpHovered = false;   // true while mouse is inside outerDiv
  let _helpOpen    = false;   // true while the card is shown

  function _updateHelp() {
    const txt = model.get('help_text') || '';
    _helpExists          = !!txt;
    helpCard.textContent = txt;
    if (!txt) {
      // Help removed — hide everything immediately.
      helpBtn.style.display    = 'none';
      helpCard.style.display   = 'none';
      helpBtn.style.background = _BTN_BG;
      _helpOpen = false;
    } else if (_helpHovered || _helpOpen) {
      // Already hovered or card open — make badge visible.
      helpBtn.style.display = 'flex';
    }
  }
  _updateHelp();

  outerDiv.addEventListener('mouseenter', () => {
    _helpHovered = true;
    if (_helpExists) helpBtn.style.display = 'flex';
  });

  outerDiv.addEventListener('mouseleave', () => {
    _helpHovered = false;
    // Only hide the button if the card is also closed.
    if (!_helpOpen) helpBtn.style.display = 'none';
  });

  helpBtn.addEventListener('click', (e) => {
    e.stopPropagation();
    _helpOpen = !_helpOpen;
    helpCard.style.display   = _helpOpen ? 'block' : 'none';
    helpBtn.style.background = _helpOpen ? _BTN_BG_ACTIVE : _BTN_BG;
    // If closing the card while the mouse has already left, hide the button too.
    if (!_helpOpen && !_helpHovered) helpBtn.style.display = 'none';
  });

  model.on('change:help_text', _updateHelp);
  const tooltip = document.createElement('div');
  tooltip.style.cssText =
    'position:fixed;padding:5px 9px;font-size:12px;font-family:sans-serif;' +
    'background:rgba(30,30,30,0.92);color:#fff;border-radius:4px;' +
    'pointer-events:none;white-space:pre;display:none;z-index:9999;' +
    'box-shadow:0 2px 6px rgba(0,0,0,0.4);max-width:260px;';
  document.body.appendChild(tooltip);

  function _showTooltip(text,cx,cy) {
    tooltip.textContent=text; tooltip.style.display='block';
    const tw=tooltip.offsetWidth||160, th=tooltip.offsetHeight||28;
    const vw=window.innerWidth, vh=window.innerHeight;  // both used below
    let lx=cx+14, ly=cy-th-8;
    if(lx+tw>vw-8) lx=cx-tw-14;
    if(ly<8) ly=cy+18;
    if(ly+th>vh-8) ly=vh-th-8;
    tooltip.style.left=lx+'px'; tooltip.style.top=ly+'px';
  }

  // ── coordinate helper: undo CSS transform:scale() ───────────────────────
  // _applyScale() shrinks outerDiv with transform:scale(s).  After that,
  // getBoundingClientRect() reports *visual* (CSS-pixel) dimensions, while
  // canvas drawing coordinates live in the *native* (un-scaled) space.
  // Every event handler that does (e.clientX - rect.left) therefore receives
  // a value in [0, nativeW*s] instead of [0, nativeW].
  //
  // _clientPos converts one mouse event back to canvas-pixel space:
  //   sfX = nativeW / rect.width  = 1/s   (1.0 when no scale is active)
  //   mx  = (e.clientX - rect.left) * sfX
  //
  // Usage:
  //   const {mx, my} = _clientPos(e, overlayCanvas, p.pw, p.ph);   // 1D / bar
  //   const {mx, my} = _clientPos(e, overlayCanvas, imgW, imgH);   // 2D
  function _clientPos(e, canvas, nativeW, nativeH) {
    const rect = canvas.getBoundingClientRect();
    const sfX  = rect.width  > 0 ? nativeW / rect.width  : 1;
    const sfY  = rect.height > 0 ? nativeH / rect.height : 1;
    return { mx: (e.clientX - rect.left) * sfX,
             my: (e.clientY - rect.top ) * sfY, sfX, sfY };
  }

  // ── per-panel state maps ──────────────────────────────────────────────────
  const panels = new Map();
  let _suppressLayoutUpdate = false;  // block re-entry during live resize
  let _pixArrivalSeq = 0;  // monotonic binary-pixel-frame arrival counter

  // Binary transport: raw pixel bytes ride a global side-table (`__apl_pixbytes`,
  // keyed `panel_<id>_geom::<pixelKey>`) because the model can't carry a
  // Uint8Array. Splice ANY currently-present bytes for this panel's geom trait
  // into `p2._geomCache` under `<pixelKey>_bytes`, stamping a monotonic arrival
  // sequence so _imageBytes gets a collision-proof cache key. Returns true if
  // any bytes were spliced. Used by BOTH the per-key change listener AND the
  // panel's INITIAL paint — the latter is load-bearing: a first pixel frame that
  // arrived (via the awi_state_binary postMessage handler) BEFORE render()
  // registered the change listener sits in the side-table with nothing to
  // consume it; without this splice the panel stays permanently blank (the
  // initial _loadGeom only parses the slimmed geom JSON, which carries the
  // LUT/flags, NOT the bytes). Idempotent: re-splicing the same buffer keeps the
  // same __aplSeq, so it does not force a spurious re-upload on the normal path.
  function _spliceBinaryBytes(p2, geomTrait) {
    const tbl = globalThis.__apl_pixbytes;
    if (!tbl) return false;
    let spliced = false;
    // Fixed base-image / mask / detail keys PLUS every DYNAMIC layer pixel key
    // (`layer_<id>_b64`) currently present in the side-table for this panel's
    // geom trait — layer keys aren't enumerable ahead of time, so scan by the
    // `<geomTrait>::` prefix. Splices each into the cache as `<pixelKey>_bytes`.
    const prefix = `${geomTrait}::`;
    for (const slot in tbl) {
      if (!slot.startsWith(prefix)) continue;
      const pixelKey = slot.slice(prefix.length);
      const b = tbl[slot];
      if (!b) continue;
      if (b.__aplSeq === undefined) {
        try { b.__aplSeq = ++_pixArrivalSeq; } catch (_) {}
      }
      if (!p2._geomCache) p2._geomCache = {};
      p2._geomCache[pixelKey + '_bytes'] = b;
      spliced = true;
    }
    return spliced;
  }

  // Register the per-pixel-key binary-bytes change listeners for a panel's geom
  // trait. The FIXED base-image / mask / detail keys each get a dedicated
  // listener (their slot fires `change:<slot>` when new bytes arrive). DYNAMIC
  // layer keys (layer_<id>_b64) are NOT enumerable here — their bytes are picked
  // up by the geom-JSON re-splice (the geom trait always re-pushes when layers
  // change) and by _spliceBinaryBytes's prefix scan, so they need no per-slot
  // listener. Shared by _createPanelDOM and _createInsetDOM.
  function _registerBinaryPixelListeners(id, geomTrait) {
    for (const pixelKey of ['image_b64', 'overlay_mask_b64', 'detail_b64']) {
      const slot = `${geomTrait}::${pixelKey}`;
      model.on(`change:${slot}`, () => {
        const p2 = panels.get(id);
        if (!p2) return;
        _spliceBinaryBytes(p2, geomTrait);
        if (p2.state) { _applyGeom(p2, p2.state); _redrawPanel(p2); }
      });
    }
  }

  // ── layout application ───────────────────────────────────────────────────
  function applyLayout() {
    if (_suppressLayoutUpdate) return;
    let layout;
    try { layout = JSON.parse(model.get('layout_json')); } catch(_) { return; }

    const { nrows, ncols, panel_specs } = layout;

    // Build grid tracks directly from panel pixel sizes.
    // Python already guarantees all panels in a row share the same height,
    // and all panels in a col share the same width.
    const colPx = new Array(ncols).fill(0);
    const rowPx = new Array(nrows).fill(0);
    for (const spec of panel_specs) {
      const perCol = Math.round(spec.panel_width  / (spec.col_stop - spec.col_start));
      const perRow = Math.round(spec.panel_height / (spec.row_stop - spec.row_start));
      for (let c = spec.col_start; c < spec.col_stop; c++) colPx[c] = Math.max(colPx[c], perCol);
      for (let r = spec.row_start; r < spec.row_stop; r++) rowPx[r] = Math.max(rowPx[r], perRow);
    }

    gridDiv.style.gridTemplateColumns = colPx.map(px => px + 'px').join(' ');
    gridDiv.style.gridTemplateRows    = rowPx.map(px => px + 'px').join(' ');
    gridDiv.style.width  = '';
    gridDiv.style.height = '';
    const meanColPx = colPx.length ? colPx.reduce((a,b)=>a+b,0)/colPx.length : 0;
    const meanRowPx = rowPx.length ? rowPx.reduce((a,b)=>a+b,0)/rowPx.length : 0;
    // Only override the default gap:4px when the Python caller explicitly set a value.
    if (layout.wspace != null) gridDiv.style.columnGap = (meanColPx ? Math.round(layout.wspace*meanColPx) : 0)+'px';
    if (layout.hspace != null) gridDiv.style.rowGap    = (meanRowPx ? Math.round(layout.hspace*meanRowPx) : 0)+'px';

    const seen = new Set();
    for (const spec of panel_specs) {
      seen.add(spec.id);
      if (!panels.has(spec.id)) {
        _createPanelDOM(spec.id, spec.kind, spec.panel_width, spec.panel_height, spec);
      } else {
        _resizePanelDOM(spec.id, spec.panel_width, spec.panel_height);
      }
    }

    // Handle inset panels
    const insetSpecs = layout.inset_specs || [];
    for (const spec of insetSpecs) {
      seen.add(spec.id);
      const existing = panels.get(spec.id);
      if (!existing) {
        _createInsetDOM(spec);
      } else {
        existing.insetSpec = spec;
      }
    }

    for (const [id, p] of panels) {
      if (!seen.has(id)) {
        // Free GPU resources before dropping the panel (2D image textures +
        // 3D geometry buffers), else they leak on re-layout / panel close.
        try { _gpuDisposeImagePanel(p); _gpuDisposePanel(p); } catch (_) {}
        p.cell.remove(); panels.delete(id);
      }
    }

    // Update insetsContainer size and reposition all insets
    insetsContainer.style.width  = (layout.fig_width  || 640) + 'px';
    insetsContainer.style.height = (layout.fig_height || 480) + 'px';
    if (insetSpecs.length) _applyAllInsetStates(layout);
    // Region indications depend on the browser having laid out the panels +
    // insets (getBoundingClientRect must be real). During the synchronous
    // applyLayout the DOM isn't measured yet, so draw once on the next frame.
    if ((layout.indications || []).length) {
      requestAnimationFrame(() => _drawCallouts());
    } else {
      _drawCallouts();  // clears any stale indication canvas
    }
    // Figure-level annotation layer tracks the figure size (fractions → px) and
    // re-binds per-panel edit-chrome hover handlers for any newly-created cells.
    _drawFigureMarkers();
    _applyPanelChrome();
  }

  // ── _buildCanvasStack ─────────────────────────────────────────────────────
  // Creates the canvas/element stack for one panel kind and appends the
  // top-level wrapper to `outerContainer`.  Returns all canvas/element refs.
  // Used by both _createPanelDOM (cell → gridDiv) and _createInsetDOM
  // (contentDiv → insetDiv).
  function _buildCanvasStack(kind, pw, ph, outerContainer) {
    let plotCanvas, overlayCanvas, markersCanvas, statusBar;
    let xAxisCanvas=null, yAxisCanvas=null, scaleBar=null;
    let cbCanvas=null, cbCtx=null, plotWrap=null, wrapNode=null;
    let titleCanvas=null;
    let stack3dGpuCanvas=null;   // WebGPU geometry canvas (3D only)
    let stack2dGpuCanvas=null;   // WebGPU image canvas (2D large-image path)

    if (kind === '2d') {
      plotWrap = document.createElement('div');
      plotWrap.style.cssText = `position:relative;display:inline-block;vertical-align:top;line-height:0;` +
        `width:${pw}px;height:${ph}px;overflow:visible;flex-shrink:0;`;

      // gpuCanvas (WebGPU image) draws the image raster BELOW plotCanvas (via
      // z-index 0) when GPU mode is active, while plotCanvas keeps drawing all
      // decorations (axes/colorbar/scale-bar/mask/markers) over a now-transparent
      // background. Hidden until/unless the GPU image path activates. It is
      // appended AFTER plotCanvas (below) so DOM order keeps plotCanvas first —
      // callers/tests that grab `querySelector('canvas')` still get the image
      // canvas; z-index (not DOM order) controls the visual stacking.
      var gpu2d = document.createElement('canvas');
      gpu2d.style.cssText =
        `position:absolute;top:0;left:0;display:none;border-radius:2px;z-index:0;`;
      stack2dGpuCanvas = gpu2d;

      plotCanvas = document.createElement('canvas');
      plotCanvas.style.cssText =
        `position:absolute;display:block;border-radius:2px;background:${theme.bgCanvas};z-index:1;`;
      overlayCanvas = document.createElement('canvas');
      overlayCanvas.style.cssText =
        'position:absolute;z-index:5;cursor:default;pointer-events:all;outline:none;touch-action:none;';
      overlayCanvas.tabIndex = 0;
      markersCanvas = document.createElement('canvas');
      markersCanvas.style.cssText = 'position:absolute;pointer-events:none;z-index:6;';
      scaleBar = document.createElement('canvas');
      scaleBar.style.cssText = 'position:absolute;pointer-events:none;display:none;z-index:7;';
      statusBar = document.createElement('div');
      statusBar.style.cssText =
        'position:absolute;padding:7px 14px;background:rgba(0,0,0,0.65);color:white;' +
        'font-size:12px;font-family:monospace;border-radius:5px;pointer-events:none;' +
        'white-space:nowrap;display:none;z-index:9;';
      yAxisCanvas = document.createElement('canvas');
      yAxisCanvas.style.cssText =
        `position:absolute;display:none;background:${theme.axisBg};`;
      xAxisCanvas = document.createElement('canvas');
      xAxisCanvas.style.cssText =
        `position:absolute;display:none;background:${theme.axisBg};`;
      cbCanvas = document.createElement('canvas');
      cbCanvas.style.cssText =
        'position:absolute;display:none;pointer-events:none;border-radius:0 2px 2px 0;';
      cbCtx = cbCanvas.getContext('2d');

      titleCanvas = document.createElement('canvas');
      titleCanvas.style.cssText = `position:absolute;pointer-events:none;z-index:8;background:transparent;display:none;`;

      plotWrap.appendChild(plotCanvas);
      plotWrap.appendChild(gpu2d);      // below plotCanvas via z-index, after in DOM
      plotWrap.appendChild(overlayCanvas);
      plotWrap.appendChild(markersCanvas);
      plotWrap.appendChild(yAxisCanvas);
      plotWrap.appendChild(xAxisCanvas);
      plotWrap.appendChild(cbCanvas);
      plotWrap.appendChild(scaleBar);
      plotWrap.appendChild(statusBar);
      plotWrap.appendChild(titleCanvas);
      outerContainer.appendChild(plotWrap);
      wrapNode = plotWrap;

    } else if (kind === '3d') {
      const wrap3 = document.createElement('div');
      wrap3.style.cssText = 'position:relative;display:inline-block;line-height:0;';
      // gpuCanvas (WebGPU geometry) sits BELOW plotCanvas; plotCanvas draws
      // decorations (axes/labels/sphere/planes/highlight) over a transparent
      // background when GPU mode is active.  Hidden until/unless GPU activates.
      var gpuCanvas = document.createElement('canvas');
      gpuCanvas.style.cssText =
        `position:absolute;top:0;left:0;display:none;border-radius:2px;` +
        `background:${theme.bgPlot};z-index:0;`;
      wrap3.appendChild(gpuCanvas);
      plotCanvas = document.createElement('canvas');
      plotCanvas.style.cssText =
        `position:relative;display:block;border-radius:2px;background:${theme.bgPlot};z-index:1;`;
      wrap3.appendChild(plotCanvas);
      outerContainer.appendChild(wrap3);
      stack3dGpuCanvas = gpuCanvas;
      overlayCanvas = document.createElement('canvas');
      overlayCanvas.style.cssText =
        'position:absolute;top:0;left:0;z-index:5;pointer-events:all;outline:none;touch-action:none;';
      wrap3.appendChild(overlayCanvas);
      markersCanvas = document.createElement('canvas');
      markersCanvas.style.cssText =
        'position:absolute;top:0;left:0;pointer-events:none;z-index:6;display:none;';
      wrap3.appendChild(markersCanvas);
      statusBar = document.createElement('div');
      statusBar.style.cssText =
        'position:absolute;bottom:4px;right:4px;padding:2px 6px;display:none;';
      wrap3.appendChild(statusBar);
      wrapNode = wrap3;

    } else {
      // 1D / bar
      plotCanvas = document.createElement('canvas');
      plotCanvas.tabIndex = 1;
      plotCanvas.style.cssText =
        'outline:none;cursor:crosshair;display:block;border-radius:2px;';
      const wrap = document.createElement('div');
      wrap.style.cssText = 'position:relative;display:inline-block;line-height:0;';
      wrap.appendChild(plotCanvas);
      outerContainer.appendChild(wrap);
      overlayCanvas = document.createElement('canvas');
      overlayCanvas.style.cssText =
        'position:absolute;top:0;left:0;z-index:5;cursor:crosshair;pointer-events:all;touch-action:none;';
      wrap.appendChild(overlayCanvas);
      markersCanvas = document.createElement('canvas');
      markersCanvas.style.cssText =
        'position:absolute;top:0;left:0;pointer-events:none;z-index:6;';
      wrap.appendChild(markersCanvas);
      statusBar = document.createElement('div');
      statusBar.style.cssText =
        'position:absolute;bottom:4px;right:4px;padding:7px 14px;' +
        'background:rgba(0,0,0,0.65);color:white;font-size:12px;font-family:monospace;' +
        'border-radius:5px;pointer-events:none;white-space:nowrap;display:none;z-index:9;';
      wrap.appendChild(statusBar);
      wrapNode = wrap;
    }

    return { plotCanvas, overlayCanvas, markersCanvas, statusBar,
             xAxisCanvas, yAxisCanvas, scaleBar,
             cbCanvas, cbCtx, plotWrap, wrapNode, titleCanvas,
             gpuCanvas: stack3dGpuCanvas || stack2dGpuCanvas };
  }

  function _createPanelDOM(id, kind, pw, ph, spec) {
    const cell = document.createElement('div');
    cell.style.cssText =
      'position:relative;overflow:visible;line-height:0;' +
      'display:flex;justify-content:center;align-items:flex-start;';
    cell.style.gridRow    = `${spec.row_start+1} / ${spec.row_stop+1}`;
    cell.style.gridColumn = `${spec.col_start+1} / ${spec.col_stop+1}`;
    gridDiv.appendChild(cell);

    const stack = _buildCanvasStack(kind, pw, ph, cell);

    const plotCtx = stack.plotCanvas.getContext('2d');
    const ovCtx   = stack.overlayCanvas.getContext('2d');
    const mkCtx   = stack.markersCanvas.getContext('2d');
    const xCtx    = stack.xAxisCanvas ? stack.xAxisCanvas.getContext('2d') : null;
    const yCtx    = stack.yAxisCanvas ? stack.yAxisCanvas.getContext('2d') : null;
    const titleCtx = stack.titleCanvas ? stack.titleCanvas.getContext('2d') : null;

    const blitCache = { bitmap:null, bytesKey:null, lutKey:null, w:0, h:0 };

    const statsDiv = document.createElement('div');
    statsDiv.style.cssText = STATS_DIV_CSS;
    if (stack.wrapNode) stack.wrapNode.appendChild(statsDiv);

    const p = {
      id, kind, cell, pw, ph,
      plotCanvas:    stack.plotCanvas,
      overlayCanvas: stack.overlayCanvas,
      markersCanvas: stack.markersCanvas,
      plotCtx, ovCtx, mkCtx,
      xAxisCanvas:   stack.xAxisCanvas,
      yAxisCanvas:   stack.yAxisCanvas,
      xCtx, yCtx,
      titleCanvas:   stack.titleCanvas || null,
      titleCtx,
      scaleBar:      stack.scaleBar,
      statusBar:     stack.statusBar,
      statsDiv,
      frameTimes: [],
      blitCache,
      ovDrag: null, ovDrag2d: null,
      isPanning: false, panStart: {},
      state: null,
      _hoverSi: -1, _hoverI: -1,
      _hovBar: null,
      lastWidgetId: null,
      mouseX: 0, mouseY: 0,
      cbCanvas:  stack.cbCanvas,
      cbCtx:     stack.cbCtx,
      sbLine:    null,
      sbLabel:   null,
      plotWrap:  stack.plotWrap,
      gpuCanvas: stack.gpuCanvas || null,
      _gpu:      undefined,   // undefined | 'pending' | 'active' | 'unavailable'
    };
    panels.set(id, p);

    _resizePanelDOM(id, pw, ph);
    _attachPanelEvents(p);

    // Geometry channel (only when this panel declared one on the Python side).
    const _geomTrait = `panel_${id}_geom`;
    const _hasGeom = model.get(_geomTrait) !== undefined;
    if (_hasGeom) {
      model.on(`change:${_geomTrait}`, () => {
        const p2 = panels.get(id);
        if (!p2) return;
        const rev = (p2.state && p2.state._geom_rev !== undefined)
          ? p2.state._geom_rev : ((p2._geomRev || 0) + 1);
        _loadGeom(p2, model.get(_geomTrait), rev);
        // Re-splice any binary pixel bytes present for this panel — including
        // DYNAMIC layer keys (layer_<id>_b64) that have no dedicated per-slot
        // listener. The geom JSON always re-pushes when layers change, so this
        // guarantees a layer's bytes are consumed regardless of arrival order.
        _spliceBinaryBytes(p2, _geomTrait);
        if (p2.state) { _applyGeom(p2, p2.state); _redrawPanel(p2); }
      });
      // Binary transport: raw pixel bytes for this panel arrive on a companion
      // trait `panel_<id>_geom::<pixelKey>` (a Uint8Array). Merge them into the
      // geomCache under `<pixelKey>_bytes` so _imageBytes uses them (no atob), and
      // redraw. Fires INDEPENDENTLY of the geom JSON trait (which now carries only
      // the small LUT/flags), so pixels + LUT converge in the cache.
      _registerBinaryPixelListeners(id, _geomTrait);
    }

    model.on(`change:panel_${id}_json`, () => {
      const p2 = panels.get(id);
      if (!p2) return;
      // Skip the echo of our own interaction writes (orbit / plane drags):
      // the state is already current and a second parse+redraw per mouse
      // event doubles the frame cost.
      if (p2._selfWrite) return;
      try {
        const newState = JSON.parse(model.get(`panel_${id}_json`));
        _preserveView(p2, newState);
        _applyGeom(p2, newState);
        p2.state = newState;
      }
      catch(_) { return; }
      p2._hoverSi = -1; p2._hoverI = -1;
      _redrawPanel(p2);
    });

    if (_hasGeom) {
      _loadGeom(p, model.get(_geomTrait), 1);
      // First-paint race fix: consume any binary pixel bytes that already
      // arrived (before this render registered the change listeners above) so
      // the INITIAL paint below shows them instead of leaving the panel blank
      // until an organic second frame. No-op on the normal path (side-table
      // empty until the first frame lands).
      _spliceBinaryBytes(p, _geomTrait);
    }
    try {
      p.state = JSON.parse(model.get(`panel_${id}_json`));
      _applyGeom(p, p.state);
    } catch(_) {}
    _redrawPanel(p);
  }

  // ── _createInsetDOM ───────────────────────────────────────────────────────
  // Builds a floating inset panel:
  //   insetDiv (position:absolute inside insetsContainer)
  //     ├── titleBar  — always visible; click to toggle min/normal
  //     │    ├── titleSpan
  //     │    └── maxBtn (⤢ / ⤡)
  //     └── contentDiv — canvas stack; display:none when minimized
  //          └── _buildCanvasStack(kind, pw, ph)
  function _createInsetDOM(spec) {
    const { id, kind, panel_width: pw, panel_height: ph, title, inset_state } = spec;

    const insetDiv = document.createElement('div');
    insetDiv.style.cssText =
      'position:absolute;pointer-events:all;border-radius:4px;overflow:hidden;' +
      `box-shadow:0 2px 14px rgba(0,0,0,0.55);border:1px solid ${theme.border};z-index:25;background:${theme.bg};`;
    insetsContainer.appendChild(insetDiv);

    // Title bar
    const tbBg = theme.dark ? 'rgba(30,32,46,0.97)' : 'rgba(210,213,224,0.97)';
    const titleBar = document.createElement('div');
    titleBar.style.cssText =
      `display:flex;align-items:center;height:${INSET_TITLE_H}px;` +
      `cursor:pointer;padding:0 5px 0 8px;user-select:none;background:${tbBg};` +
      `border-bottom:1px solid ${theme.border};box-sizing:border-box;flex-shrink:0;`;
    insetDiv.appendChild(titleBar);

    const titleSpan = document.createElement('span');
    titleSpan.style.cssText =
      `flex:1;font-size:11px;font-family:sans-serif;overflow:hidden;` +
      `text-overflow:ellipsis;white-space:nowrap;color:${theme.tickText};`;
    titleSpan.textContent = title || '';
    titleBar.appendChild(titleSpan);


    // Content div — wraps the canvas stack
    const contentDiv = document.createElement('div');
    contentDiv.style.cssText =
      `overflow:hidden;display:${inset_state === 'minimized' ? 'none' : 'block'};`;
    insetDiv.appendChild(contentDiv);

    // Canvas stack inside contentDiv
    const stack = _buildCanvasStack(kind, pw, ph, contentDiv);

    const plotCtx = stack.plotCanvas.getContext('2d');
    const ovCtx   = stack.overlayCanvas.getContext('2d');
    const mkCtx   = stack.markersCanvas.getContext('2d');
    const xCtx    = stack.xAxisCanvas ? stack.xAxisCanvas.getContext('2d') : null;
    const yCtx    = stack.yAxisCanvas ? stack.yAxisCanvas.getContext('2d') : null;

    const blitCache = { bitmap:null, bytesKey:null, lutKey:null, w:0, h:0 };

    const statsDiv = document.createElement('div');
    statsDiv.style.cssText = STATS_DIV_CSS;
    if (stack.wrapNode) stack.wrapNode.appendChild(statsDiv);

    const p = {
      id, kind, pw, ph,
      cell: insetDiv,   // stale-cleanup compatibility (p.cell.remove())
      isInset: true, insetDiv, contentDiv, titleBar,
      insetSpec: spec,
      plotCanvas:    stack.plotCanvas,
      overlayCanvas: stack.overlayCanvas,
      markersCanvas: stack.markersCanvas,
      plotCtx, ovCtx, mkCtx,
      xAxisCanvas:   stack.xAxisCanvas,
      yAxisCanvas:   stack.yAxisCanvas,
      xCtx, yCtx,
      scaleBar:      stack.scaleBar,
      statusBar:     stack.statusBar,
      statsDiv,
      frameTimes: [], blitCache,
      ovDrag: null, ovDrag2d: null,
      isPanning: false, panStart: {},
      state: null,
      _hoverSi: -1, _hoverI: -1,
      _hovBar: null,
      lastWidgetId: null, mouseX: 0, mouseY: 0,
      cbCanvas:  stack.cbCanvas,
      cbCtx:     stack.cbCtx,
      sbLine:    null, sbLabel: null,
      plotWrap:  stack.plotWrap,
    };
    panels.set(id, p);

    _resizePanelDOM(id, pw, ph);
    _attachPanelEvents(p);

    // Title bar click: toggle normal ↔ minimized
    titleBar.addEventListener('click', (e) => {
      const cur = p.insetSpec ? p.insetSpec.inset_state : 'normal';
      _applyButtonState(p, cur === 'minimized' ? 'normal' : 'minimized');
    });


    // Geometry channel (only when this panel declared one on the Python side).
    const _geomTrait = `panel_${id}_geom`;
    const _hasGeom = model.get(_geomTrait) !== undefined;
    if (_hasGeom) {
      model.on(`change:${_geomTrait}`, () => {
        const p2 = panels.get(id);
        if (!p2) return;
        const rev = (p2.state && p2.state._geom_rev !== undefined)
          ? p2.state._geom_rev : ((p2._geomRev || 0) + 1);
        _loadGeom(p2, model.get(_geomTrait), rev);
        // Re-splice binary bytes incl. dynamic layer keys — see _createPanelDOM.
        _spliceBinaryBytes(p2, _geomTrait);
        if (p2.state) { _applyGeom(p2, p2.state); _redrawPanel(p2); }
      });
      // Binary transport: raw pixel bytes for this panel arrive on a companion
      // trait `panel_<id>_geom::<pixelKey>` (a Uint8Array). Merge them into the
      // geomCache under `<pixelKey>_bytes` so _imageBytes uses them (no atob), and
      // redraw. Fires INDEPENDENTLY of the geom JSON trait (which now carries only
      // the small LUT/flags), so pixels + LUT converge in the cache.
      _registerBinaryPixelListeners(id, _geomTrait);
    }

    model.on(`change:panel_${id}_json`, () => {
      const p2 = panels.get(id);
      if (!p2) return;
      // Skip the echo of our own interaction writes (orbit / plane drags):
      // the state is already current and a second parse+redraw per mouse
      // event doubles the frame cost.
      if (p2._selfWrite) return;
      try {
        const newState = JSON.parse(model.get(`panel_${id}_json`));
        _preserveView(p2, newState);
        _applyGeom(p2, newState);
        p2.state = newState;
      }
      catch(_) { return; }
      p2._hoverSi = -1; p2._hoverI = -1;
      _redrawPanel(p2);
    });

    if (_hasGeom) {
      _loadGeom(p, model.get(_geomTrait), 1);
      // First-paint race fix (see _createPanelDOM): splice any binary pixel
      // bytes that arrived before render() registered the listeners above.
      _spliceBinaryBytes(p, _geomTrait);
    }
    try {
      p.state = JSON.parse(model.get(`panel_${id}_json`));
      _applyGeom(p, p.state);
    } catch(_) {}
    _redrawPanel(p);
  }

  // Optimistic local state update + Python notification.
  function _applyButtonState(p, newState) {
    try {
      const layout = JSON.parse(model.get('layout_json'));
      const spec = (layout.inset_specs || []).find(s => s.id === p.id);
      if (spec) {
        spec.inset_state = newState;
        p.insetSpec = spec;
        _applyAllInsetStates(layout);
      }
    } catch(_) {}
    _emitEvent(p.id, 'inset_state_change', null, { new_state: newState });
  }

  // ── _applyAllInsetStates ──────────────────────────────────────────────────
  // Positions every inset for the given layout snapshot.
  // Corner-placed insets are grouped by corner and stacked with INSET_GAP
  // spacing (minimized ones contribute only INSET_TITLE_H to the stack).
  // Anchor-placed insets (spec.anchor != null) float at their anchor fraction.
  // Maximized insets float centred at z-index:45, outside any stack.
  function _applyAllInsetStates(layout) {
    const insetSpecs = layout.inset_specs || [];
    const fw = layout.fig_width  || 640;
    const fh = layout.fig_height || 480;

    insetsContainer.style.width  = fw + 'px';
    insetsContainer.style.height = fh + 'px';

    // Split anchored insets from corner insets. Anchored ones are placed
    // directly at their fraction; corner ones stack per-corner as before.
    const anchored = [];
    const byCorner = {};
    for (const spec of insetSpecs) {
      if (spec.anchor) { anchored.push(spec); continue; }
      (byCorner[spec.corner] = byCorner[spec.corner] || []).push(spec);
    }

    // ── anchor-placed insets ────────────────────────────────────────────────
    for (const spec of anchored) {
      const p = panels.get(spec.id);
      if (!p || !p.isInset) continue;
      const pw = spec.panel_width;
      const ph = spec.panel_height;
      const state = spec.inset_state;
      const stackH = state === 'minimized' ? INSET_TITLE_H : INSET_TITLE_H + ph;

      // Maximized floats centred (same treatment as corner insets below).
      if (state === 'maximized') {
        const mw = Math.round(fw * 0.72), mh = Math.round(fh * 0.72);
        p.insetDiv.style.left = Math.round((fw - mw) / 2) + 'px';
        p.insetDiv.style.top  = Math.round((fh - mh) / 2) + 'px';
        p.insetDiv.style.width  = mw + 'px';
        p.insetDiv.style.height = (INSET_TITLE_H + mh) + 'px';
        p.insetDiv.style.zIndex = '45';
        p.contentDiv.style.display = 'block';
        p.contentDiv.style.height  = mh + 'px';
        if (p.pw !== mw || p.ph !== mh) {
          p.pw = mw; p.ph = mh; _resizePanelDOM(spec.id, mw, mh); _redrawPanel(p);
        }
        continue;
      }

      // Normal / minimized: top-left corner sits at the anchor fraction,
      // clamped so the inset stays inside the figure.
      let left = Math.round(spec.anchor[0] * fw);
      let top  = Math.round(spec.anchor[1] * fh);
      left = Math.max(0, Math.min(left, fw - pw));
      top  = Math.max(0, Math.min(top,  fh - stackH));
      p.insetDiv.style.left   = left + 'px';
      p.insetDiv.style.top    = top  + 'px';
      p.insetDiv.style.width  = pw   + 'px';
      p.insetDiv.style.height = stackH + 'px';
      p.insetDiv.style.zIndex = '25';
      if (state === 'minimized') {
        p.contentDiv.style.display = 'none';
      } else {
        p.contentDiv.style.display = 'block';
        p.contentDiv.style.height  = ph + 'px';
        if (p.pw !== pw || p.ph !== ph) {
          p.pw = pw; p.ph = ph; _resizePanelDOM(spec.id, pw, ph); _redrawPanel(p);
        }
      }
    }

    for (const [corner, group] of Object.entries(byCorner)) {
      const isBottom = corner.startsWith('bottom');
      const isRight  = corner.endsWith('right');
      // Bottom corners: first-added is closest to the corner (stack upward),
      // so reverse for the position loop (offset grows from the corner outward).
      const walk = isBottom ? [...group].reverse() : group;
      let offset = INSET_MARGIN;

      for (const spec of walk) {
        const p = panels.get(spec.id);
        if (!p || !p.isInset) continue;

        const pw    = spec.panel_width;
        const ph    = spec.panel_height;
        const state = spec.inset_state;


        // Normal or minimized: compute position from corner
        const stackH = state === 'minimized' ? INSET_TITLE_H : INSET_TITLE_H + ph;
        const left   = isRight ? fw - pw - INSET_MARGIN : INSET_MARGIN;
        const top    = isBottom ? fh - offset - stackH  : offset;

        p.insetDiv.style.left   = left + 'px';
        p.insetDiv.style.top    = top  + 'px';
        p.insetDiv.style.width  = pw   + 'px';
        p.insetDiv.style.height = stackH + 'px';
        p.insetDiv.style.zIndex = '25';

        if (state === 'minimized') {
          p.contentDiv.style.display = 'none';
        } else {
          p.contentDiv.style.display = 'block';
          p.contentDiv.style.height  = ph + 'px';
          if (p.pw !== pw || p.ph !== ph) {
            p.pw = pw; p.ph = ph;
            _resizePanelDOM(spec.id, pw, ph);
            _redrawPanel(p);
          }
        }

        offset += stackH + INSET_GAP;
      }
    }
    // Inset positions changed → refresh leader lines / rects.  Use the layout's
    // own size (may be a live-resize snapshot ahead of the model).
    _drawCallouts([fw, fh]);
  }

  // ── _drawCallouts ─────────────────────────────────────────────────────────
  // Draw every mark_inset-style region indication onto the figure-level
  // calloutCanvas.  Called after any parent redraw / inset move / resize, so
  // the dashed source rect tracks the parent's zoom+pan (region is mapped
  // through _imgToCanvas2d every draw) and the leaders follow the inset's
  // current DOM rect (leaders hide while the inset is minimized).
  //
  // Coordinate space: everything is mapped into calloutCanvas CSS px via each
  // element's getBoundingClientRect relative to the canvas's own rect — so no
  // layout math is duplicated and the leaders line up across panel boundaries.
  function _drawCallouts(sizeOverride) {
    let layout;
    try { layout = JSON.parse(model.get('layout_json')); } catch (_) { return; }
    const inds = layout.indications || [];

    // Nothing to draw → collapse the overlay to a 0×0 backing store instead of
    // sizing it to the full figure. An empty full-figure transparent canvas
    // would otherwise be the LARGEST canvas in the DOM (it spans the whole
    // figure, wider than any single panel), shadowing the panel content for
    // any consumer/test that samples "the largest canvas". Setting width/height
    // to 0 also clears any prior drawing, so no clearRect is needed here.
    if (!inds.length) {
      if (calloutCanvas.width || calloutCanvas.height) {
        calloutCanvas.width = 0; calloutCanvas.height = 0;
        calloutCanvas.style.width = '0px'; calloutCanvas.style.height = '0px';
      }
      return;
    }

    // Size the canvas to the figure content (fig size + no padding — it is
    // already offset by 8 px like insetsContainer).  During a live figure
    // resize the model hasn't been written yet, so accept an explicit size.
    const fw = sizeOverride ? sizeOverride[0]
             : (Number(model.get('fig_width'))  || layout.fig_width  || 640);
    const fh = sizeOverride ? sizeOverride[1]
             : (Number(model.get('fig_height')) || layout.fig_height || 480);
    if (calloutCanvas.width !== Math.round(fw * dpr) ||
        calloutCanvas.height !== Math.round(fh * dpr)) {
      calloutCanvas.style.width  = fw + 'px';
      calloutCanvas.style.height = fh + 'px';
      calloutCanvas.width  = Math.round(fw * dpr);
      calloutCanvas.height = Math.round(fh * dpr);
    }
    calloutCtx.setTransform(dpr, 0, 0, dpr, 0, 0);
    calloutCtx.clearRect(0, 0, fw, fh);

    const base = calloutCanvas.getBoundingClientRect();

    for (const ind of inds) {
      const parent = panels.get(ind.parent_id);
      const inset  = panels.get(ind.inset_id);
      if (!parent || !parent.state || !inset || !inset.isInset) continue;

      // ── source rectangle in parent-canvas px → figure px ─────────────────
      // Map the region's four data-space corners through the parent's
      // data→canvas transform (tracks zoom/pan), then offset by the parent
      // markers canvas's position relative to the callout canvas.
      const st = parent.state;
      const imgW = parent.imgW || 1, imgH = parent.imgH || 1;
      const [rx, ry, rw, rh] = ind.region;
      const mkRect = (parent.markersCanvas || parent.plotCanvas).getBoundingClientRect();
      const offX = mkRect.left - base.left;
      const offY = mkRect.top  - base.top;
      const toFig = (dx, dy) => {
        const [cx, cy] = _imgToCanvas2d(dx, dy, st, imgW, imgH);
        return [offX + cx, offY + cy];
      };
      const [x0, y0] = toFig(rx,      ry);
      const [x1, y1] = toFig(rx + rw, ry);
      const [x2, y2] = toFig(rx + rw, ry + rh);
      const [x3, y3] = toFig(rx,      ry + rh);
      // Axis-aligned bounds of the (untransformed) rect in figure px.
      const rL = Math.min(x0, x1, x2, x3), rR = Math.max(x0, x1, x2, x3);
      const rT = Math.min(y0, y1, y2, y3), rB = Math.max(y0, y1, y2, y3);

      const color = ind.color || '#ff9800';
      const lw    = ind.linewidth != null ? ind.linewidth : 1.5;
      const dash  = ind.linestyle === 'solid'  ? []
                  : ind.linestyle === 'dotted' ? [2, 3]
                  : [6, 4];  // dashed (default)

      calloutCtx.save();
      calloutCtx.strokeStyle = color;
      calloutCtx.lineWidth   = lw;
      calloutCtx.setLineDash(dash);

      // Dashed source rectangle (drawn as the 4 transformed corners so it
      // stays correct even if a future transform rotates/skews it).  Clipped
      // to the parent's image area so a zoomed-in region that runs off the
      // panel doesn't paint over neighbouring panels (the leaders below are
      // intentionally NOT clipped — they cross panel boundaries).
      calloutCtx.save();
      calloutCtx.beginPath();
      calloutCtx.rect(offX, offY, imgW, imgH);
      calloutCtx.clip();
      calloutCtx.beginPath();
      calloutCtx.moveTo(x0, y0);
      calloutCtx.lineTo(x1, y1);
      calloutCtx.lineTo(x2, y2);
      calloutCtx.lineTo(x3, y3);
      calloutCtx.closePath();
      calloutCtx.stroke();
      calloutCtx.restore();

      // ── leader lines to the inset (skip while minimized) ─────────────────
      const insSpec = (layout.inset_specs || []).find(s => s.id === ind.inset_id);
      const minimized = insSpec && insSpec.inset_state === 'minimized';
      if (!minimized) {
        const iRect = inset.insetDiv.getBoundingClientRect();
        const iL = iRect.left - base.left, iT = iRect.top  - base.top;
        const iR = iL + iRect.width,       iB = iT + iRect.height;

        // Pick which pair of rect corners face the inset (mark_inset loc1/loc2
        // auto): compare the inset's centre to the rect's centre and connect
        // the two corners on the facing side(s).  Deterministic and simple.
        const rcx = (rL + rR) / 2, rcy = (rT + rB) / 2;
        const icx = (iL + iR) / 2, icy = (iT + iB) / 2;
        const dxc = icx - rcx, dyc = icy - rcy;

        // Rect corners (TL, TR, BR, BL) paired with the inset corner nearest
        // to each, so each leader is short and non-crossing.
        const rectCorners = {
          TL: [rL, rT], TR: [rR, rT], BR: [rR, rB], BL: [rL, rB],
        };
        const insCorners = {
          TL: [iL, iT], TR: [iR, iT], BR: [iR, iB], BL: [iL, iB],
        };
        // Choose the two rect corners on the side facing the inset.
        let pair;
        if (Math.abs(dxc) >= Math.abs(dyc)) {
          // Inset predominantly left/right of the rect → connect that vertical edge.
          pair = dxc >= 0 ? [['TR', 'TL'], ['BR', 'BL']]
                          : [['TL', 'TR'], ['BL', 'BR']];
        } else {
          // Inset predominantly above/below → connect that horizontal edge.
          pair = dyc >= 0 ? [['BL', 'TL'], ['BR', 'TR']]
                          : [['TL', 'BL'], ['TR', 'BR']];
        }
        for (const [rc, ic] of pair) {
          const [px, py] = rectCorners[rc];
          const [qx, qy] = insCorners[ic];
          calloutCtx.beginPath();
          calloutCtx.moveTo(px, py);
          calloutCtx.lineTo(qx, qy);
          calloutCtx.stroke();
        }
      }
      calloutCtx.restore();
    }
  }

  // ═══════════════════════════════════════════════════════════════════════════
  // Figure-level annotation layer + edit chrome (Report Builder edit mode)
  // ═══════════════════════════════════════════════════════════════════════════
  const EDIT_ACCENT = '#4b78d2';   // outline / handle accent for edit chrome
  let _figMarkers = [];            // parsed figure_markers_json (fractions)
  let _figMarkerDrag = null;       // active drag: {id, mode, snap, startMX/MY}

  function _editOn() { return !!model.get('edit_chrome'); }

  function _loadFigMarkers() {
    try { _figMarkers = JSON.parse(model.get('figure_markers_json') || '[]') || []; }
    catch (_) { _figMarkers = []; }
    if (!Array.isArray(_figMarkers)) _figMarkers = [];
  }

  // Current figure content size in CSS px (grid content, no padding).
  function _figSizePx() {
    const fw = Number(model.get('fig_width'))  || 640;
    const fh = Number(model.get('fig_height')) || 480;
    return [fw, fh];
  }

  // Fraction (0..1) → figure-content CSS px.
  function _fracToFigPx(fx, fy, fw, fh) { return [fx * fw, fy * fh]; }

  // ── _drawFigureMarkers ────────────────────────────────────────────────────
  // Draw every figure-level annotation onto figMarkerCanvas.  Fraction→px uses
  // the figure content size; circle radius scales with min(fw,fh) so it stays
  // round under a non-square figure.  Handles are drawn only in edit mode.
  function _drawFigureMarkers(sizeOverride, forceNoHandles) {
    const [fw, fh] = sizeOverride || _figSizePx();
    // No markers → collapse the overlay to a 0×0 backing store rather than
    // sizing it to the full figure (same rationale as _drawCallouts: an empty
    // full-figure transparent canvas is the largest canvas in the DOM and
    // shadows panel content for "largest canvas" pixel probes). Zeroing the
    // size also clears any prior drawing.
    if (!_figMarkers.length) {
      if (figMarkerCanvas.width || figMarkerCanvas.height) {
        figMarkerCanvas.width = 0; figMarkerCanvas.height = 0;
        figMarkerCanvas.style.width = '0px'; figMarkerCanvas.style.height = '0px';
      }
      return;
    }
    if (figMarkerCanvas.width !== Math.round(fw * dpr) ||
        figMarkerCanvas.height !== Math.round(fh * dpr)) {
      figMarkerCanvas.style.width  = fw + 'px';
      figMarkerCanvas.style.height = fh + 'px';
      figMarkerCanvas.width  = Math.round(fw * dpr);
      figMarkerCanvas.height = Math.round(fh * dpr);
    }
    figMarkerCtx.setTransform(dpr, 0, 0, dpr, 0, 0);
    figMarkerCtx.clearRect(0, 0, fw, fh);
    const rmin = Math.min(fw, fh);
    const edit = _editOn() && !forceNoHandles;

    for (const m of _figMarkers) {
      const color = m.color || EDIT_ACCENT;
      const lw = m.linewidth != null ? m.linewidth : 2;
      figMarkerCtx.save();
      figMarkerCtx.strokeStyle = color;
      figMarkerCtx.fillStyle   = color;
      figMarkerCtx.lineWidth   = lw;
      if (m.kind === 'text') {
        const [px, py] = _fracToFigPx(m.x, m.y, fw, fh);
        const fs = m.fontsize || 16;
        figMarkerCtx.font = `${fs}px sans-serif`;
        figMarkerCtx.textAlign = 'left';
        figMarkerCtx.textBaseline = 'top';
        figMarkerCtx.fillText(m.text || '', px, py);
        if (edit) _drawHandle2d(figMarkerCtx, px, py, color);
      } else if (m.kind === 'circle') {
        const [px, py] = _fracToFigPx(m.x, m.y, fw, fh);
        const r = (m.r || 0) * rmin;
        figMarkerCtx.beginPath(); figMarkerCtx.arc(px, py, r, 0, Math.PI*2); figMarkerCtx.stroke();
        if (edit) _drawHandle2d(figMarkerCtx, px, py, color);
      } else if (m.kind === 'rect') {
        // x,y = CENTRE; w,h = fractions of figure size.
        const [cx, cy] = _fracToFigPx(m.x, m.y, fw, fh);
        const rw = (m.w || 0) * fw, rh = (m.h || 0) * fh;
        figMarkerCtx.strokeRect(cx - rw/2, cy - rh/2, rw, rh);
        if (edit) _drawHandle2d(figMarkerCtx, cx, cy, color);
      } else if (m.kind === 'arrow') {
        const [tx, ty] = _fracToFigPx(m.x, m.y, fw, fh);
        const [hx, hy] = _fracToFigPx(m.x + (m.u||0), m.y + (m.v||0), fw, fh);
        const ang = Math.atan2(hy-ty, hx-tx), HL = 12;
        figMarkerCtx.beginPath(); figMarkerCtx.moveTo(tx, ty); figMarkerCtx.lineTo(hx, hy); figMarkerCtx.stroke();
        figMarkerCtx.beginPath(); figMarkerCtx.moveTo(hx, hy);
        figMarkerCtx.lineTo(hx-HL*Math.cos(ang-Math.PI/6), hy-HL*Math.sin(ang-Math.PI/6));
        figMarkerCtx.lineTo(hx-HL*Math.cos(ang+Math.PI/6), hy-HL*Math.sin(ang+Math.PI/6));
        figMarkerCtx.closePath(); figMarkerCtx.fill();
        if (edit) { _drawHandle2d(figMarkerCtx, tx, ty, color); _drawHandle2d(figMarkerCtx, hx, hy, color); }
      }
      figMarkerCtx.restore();
    }
  }

  // Mouse (figMarkerCanvas CSS px) for a pointer event.
  function _figMarkerMouse(e) {
    const r = figMarkerCanvas.getBoundingClientRect();
    const sx = r.width  ? figMarkerCanvas.width  / dpr / r.width  : 1;
    const sy = r.height ? figMarkerCanvas.height / dpr / r.height : 1;
    return [(e.clientX - r.left) * sx, (e.clientY - r.top) * sy];
  }

  // Hit-test the figure markers (topmost first). Returns {id, mode} or null.
  function _figMarkerHitTest(mx, my) {
    const [fw, fh] = _figSizePx();
    const rmin = Math.min(fw, fh);
    const HR = 9;
    for (let i = _figMarkers.length - 1; i >= 0; i--) {
      const m = _figMarkers[i];
      if (m.kind === 'arrow') {
        const [tx, ty] = _fracToFigPx(m.x, m.y, fw, fh);
        const [hx, hy] = _fracToFigPx(m.x + (m.u||0), m.y + (m.v||0), fw, fh);
        if (Math.hypot(mx-hx, my-hy) <= HR) return { id: m.id, mode: 'resize_head' };
        if (Math.hypot(mx-tx, my-ty) <= HR) return { id: m.id, mode: 'move' };
        if (_distToSegment2d(mx, my, tx, ty, hx, hy) <= HR) return { id: m.id, mode: 'move' };
      } else if (m.kind === 'circle') {
        const [px, py] = _fracToFigPx(m.x, m.y, fw, fh);
        const r = (m.r || 0) * rmin;
        if (Math.abs(Math.hypot(mx-px, my-py) - r) <= Math.max(HR, r*0.18) ||
            Math.hypot(mx-px, my-py) <= HR) return { id: m.id, mode: 'move' };
      } else if (m.kind === 'rect') {
        const [cx, cy] = _fracToFigPx(m.x, m.y, fw, fh);
        const rw = (m.w||0) * fw, rh = (m.h||0) * fh;
        if (mx >= cx-rw/2-HR && mx <= cx+rw/2+HR && my >= cy-rh/2-HR && my <= cy+rh/2+HR)
          return { id: m.id, mode: 'move' };
      } else if (m.kind === 'text') {
        const [px, py] = _fracToFigPx(m.x, m.y, fw, fh);
        // Approximate text box: measure width, one line tall.
        figMarkerCtx.save();
        figMarkerCtx.font = `${m.fontsize||16}px sans-serif`;
        const tw = figMarkerCtx.measureText(m.text || '').width;
        figMarkerCtx.restore();
        const th = m.fontsize || 16;
        if (mx >= px-HR && mx <= px+tw+HR && my >= py-HR && my <= py+th+HR)
          return { id: m.id, mode: 'move' };
      }
    }
    return null;
  }

  function _figMarkerById(id) { return _figMarkers.find(m => m.id === id) || null; }

  // Persist the current _figMarkers to the model (no event emission).
  function _writeFigMarkers() {
    model.set('figure_markers_json', JSON.stringify(_figMarkers));
    model.save_changes();
  }

  // Apply a drag delta (in figure fractions) to the dragged marker.
  function _doFigMarkerDrag(e) {
    const d = _figMarkerDrag; if (!d) return;
    const [fw, fh] = _figSizePx();
    const [mx, my] = _figMarkerMouse(e);
    const m = _figMarkerById(d.id); if (!m) return;
    const s = d.snap;
    const dfx = (mx - d.startMX) / fw, dfy = (my - d.startMY) / fh;
    if (d.mode === 'move') {
      m.x = s.x + dfx; m.y = s.y + dfy;
    } else if (d.mode === 'resize_head' && m.kind === 'arrow') {
      m.u = (mx / fw) - m.x; m.v = (my / fh) - m.y;
    }
    _drawFigureMarkers();
    e.preventDefault();
  }

  // ── Panel drag-swap (edit mode) ───────────────────────────────────────────
  // A ~16px "⋮⋮" move grip in each panel cell's top-left corner (edit mode
  // only).  Dragging it starts a swap: the source panel dims, the panel under
  // the cursor is highlighted as the drop target, and releasing over a
  // DIFFERENT panel emits a figure-level {panel_swap} event.  anyplotlib does
  // NOT reorder anything itself — the host swaps + rebuilds the layout.  The
  // grip only exists / captures events under edit_chrome; off-edit it is
  // display:none so it never steals a widget drag or a panel selection click.
  const GRIP_PX = 16;
  let _panelSwapDrag = null;   // {sourceId, startX, startY} while dragging

  function _panelAt(clientX, clientY) {
    // Topmost panel cell containing the point (grid cells don't overlap).
    for (const p of panels.values()) {
      const cell = p.cell; if (!cell) continue;
      // Skip insets — swap is grid-panel only.
      if (p.isInset) continue;
      const r = cell.getBoundingClientRect();
      if (clientX >= r.left && clientX <= r.right &&
          clientY >= r.top  && clientY <= r.bottom) return p;
    }
    return null;
  }

  function _clearSwapFeedback() {
    for (const p of panels.values()) {
      if (!p.cell) continue;
      p.cell.style.opacity = '';
      // Restore the panel's normal chrome (selection/hover outline).
    }
    _applyPanelChrome();
  }

  function _ensureGrip(p) {
    if (p.grip || !p.cell) return;
    const g = document.createElement('div');
    g.className = 'apl-panel-grip';
    // Dark-theme dotted-grid affordance; grab cursor; sits above the canvas
    // stack (canvases are z 5) but is display:none unless edit mode is on.
    g.style.cssText =
      `position:absolute;top:2px;left:2px;width:${GRIP_PX}px;height:${GRIP_PX}px;` +
      `z-index:12;cursor:grab;display:none;border-radius:3px;` +
      `align-items:center;justify-content:center;font-size:12px;line-height:1;` +
      `color:${theme.fg||'#cdd6f4'};background:${theme.bg||'#1e1e2e'};` +
      `border:1px solid ${theme.border||'#44475a'};` +
      `box-shadow:0 1px 3px rgba(0,0,0,0.4);user-select:none;`;
    g.textContent = '⠿';  // ⠿ braille dots — a clean "grab" grid glyph
    g.title = 'Drag to swap this panel';
    g.addEventListener('mousedown', (e) => {
      if (!_editOn() || e.button !== 0) return;
      // Grip wins over panel selection / marker grab within its own bounds.
      e.preventDefault(); e.stopPropagation();
      _panelSwapDrag = { sourceId: p.id, startX: e.clientX, startY: e.clientY };
      g.style.cursor = 'grabbing';
      p.cell.style.opacity = '0.4';   // ghost the source
    });
    p.cell.appendChild(g);
    p.grip = g;
  }

  // Global move / up handlers for an in-progress panel swap.
  document.addEventListener('mousemove', (e) => {
    if (!_panelSwapDrag) return;
    const target = _panelAt(e.clientX, e.clientY);
    // Highlight the drop target (not the source) with a solid accent outline.
    for (const p of panels.values()) {
      if (!p.cell || p.isInset) continue;
      if (p.id === _panelSwapDrag.sourceId) continue;
      if (target && p.id === target.id) {
        p.cell.style.outline = `2px solid ${EDIT_ACCENT}`;
        p.cell.style.outlineOffset = '-2px';
      } else {
        // Clear any transient swap highlight (leave the source alone).
        p.cell.style.outline = '';
        p.cell.style.outlineOffset = '';
      }
    }
    e.preventDefault();
  });

  document.addEventListener('mouseup', (e) => {
    if (!_panelSwapDrag) return;
    const d = _panelSwapDrag; _panelSwapDrag = null;
    if (d.sourceId && panels.get(d.sourceId) && panels.get(d.sourceId).grip)
      panels.get(d.sourceId).grip.style.cursor = 'grab';
    const target = _panelAt(e.clientX, e.clientY);
    // Emit ONLY when released over a different, non-inset panel.
    if (target && !target.isInset && target.id !== d.sourceId) {
      _emitEvent('', 'pointer_up', null, {
        panel_swap: true,
        source_panel_id: d.sourceId,
        target_panel_id: target.id,
        ..._pointerFields(e), button: e.button,
      });
    }
    // Released on the source panel / empty space → cancel cleanly (no emit).
    _clearSwapFeedback();
    e.preventDefault();
  });

  // ── Edit chrome: per-panel hover + selection outlines ─────────────────────
  // Purely JS-local DOM styling; never exported.  Hover uses a dashed accent
  // outline via a data-attr-driven inline style; selection a solid one.
  function _applyPanelChrome() {
    const edit = _editOn();
    const sel = model.get('selected_panel') || '';
    for (const p of panels.values()) {
      const cell = p.cell; if (!cell) continue;
      // Move grip: created lazily, shown only in edit mode on grid panels.
      if (!p.isInset) {
        _ensureGrip(p);
        if (p.grip) p.grip.style.display = edit ? 'flex' : 'none';
      }
      // Selection outline (persistent, solid) wins over hover.
      // outline-offset is fully NEGATIVE (−width) so the whole ring is inset
      // INSIDE the cell bounds — otherwise an edge/corner panel's outline is
      // clipped at the figure's right/bottom edge (half the stroke spills out).
      if (edit && p.id === sel) {
        cell.style.outline = `2px solid ${EDIT_ACCENT}`;
        cell.style.outlineOffset = '-2px';
      } else if (!p._editHover || !edit) {
        cell.style.outline = '';
        cell.style.outlineOffset = '';
      }
      // (Re)bind hover handlers exactly once per cell.
      if (!p._editHoverBound) {
        p._editHoverBound = true;
        cell.addEventListener('mouseenter', () => {
          p._editHover = true;
          if (_editOn() && p.id !== (model.get('selected_panel') || '')) {
            cell.style.outline = `2px dashed ${EDIT_ACCENT}`;
            cell.style.outlineOffset = '-2px';
          }
        });
        cell.addEventListener('mouseleave', () => {
          p._editHover = false;
          if (p.id !== (model.get('selected_panel') || '')) {
            cell.style.outline = '';
            cell.style.outlineOffset = '';
          }
        });
      }
    }
  }

  // Edit mode redraws the marker layer (so handles appear/disappear) and the
  // panel chrome.  figMarkerCanvas ALWAYS stays pointer-events:none — a
  // full-figure canvas set to `auto` would sit above every panel's overlay
  // (z 35 > z 5) and swallow all panel interaction.  Instead the outerDiv
  // capture handler below hit-tests markers itself, so a marker is grabbable
  // where it lies and panels stay fully interactive everywhere else.
  function _applyEditMode() {
    _applyPanelChrome();
    _drawFigureMarkers();
  }

  document.addEventListener('mousemove', (e) => {
    if (!_figMarkerDrag) return;
    _doFigMarkerDrag(e);
  });
  document.addEventListener('mouseup', (e) => {
    if (!_figMarkerDrag) return;
    const d = _figMarkerDrag; _figMarkerDrag = null;
    const m = _figMarkerById(d.id);
    // Persist + emit a figure_marker pointer_up carrying the updated FRACTIONS.
    _writeFigMarkers();
    const upd = { figure_marker: true, marker_id: d.id };
    if (m) { for (const k of ['x','y','u','v','r','w','h']) if (m[k] !== undefined) upd[k] = m[k]; }
    _emitEvent('', 'pointer_up', null, { ...upd, ..._pointerFields(e), button: e.button });
    e.preventDefault();
  });

  // ── Edit-mode mousedown capture on outerDiv ───────────────────────────────
  // Runs BEFORE any panel handler (capture phase).  Two jobs, both edit-only:
  //   1. If a figure marker is under the cursor → start a marker drag and
  //      STOP propagation so the panel underneath doesn't also react.
  //   2. Else, if the target is NOT inside any panel cell / inset / chrome →
  //      emit a figure-background pointer_down.
  // A plain click inside a panel does neither (its own path handles it).
  outerDiv.addEventListener('mousedown', (e) => {
    if (!_editOn() || e.button !== 0) return;

    // (0) A panel move-grip owns its own bounds — let its own mousedown handler
    // start the swap; do not marker-grab or background-emit here.
    if (e.target && e.target.classList &&
        e.target.classList.contains('apl-panel-grip')) return;

    const [mx, my] = _figMarkerMouse(e);

    // (1) Marker grab — highest priority, even over a panel underneath.
    const hit = _figMarkerHitTest(mx, my);
    if (hit) {
      const m = _figMarkerById(hit.id);
      _figMarkerDrag = { id: hit.id, mode: hit.mode, snap: {...m},
                         startMX: mx, startMY: my };
      e.preventDefault(); e.stopPropagation();
      return;
    }

    // (2) Background detection.
    const t = e.target;
    for (const p of panels.values()) {
      if (p.cell && p.cell.contains(t)) return;   // inside a panel / inset
    }
    if (t === resizeHandle || (helpBtn && helpBtn.contains(t)) ||
        (helpCard && helpCard.contains(t))) return;
    _emitEvent('', 'pointer_down', null, { figure_background: true, ..._pointerFields(e), button: e.button });
  }, true);

  function _resizePanelDOM(id, pw, ph) {
    const p = panels.get(id);
    if (!p) return;
    p.pw = pw; p.ph = ph;

    function _sz(c, ctx, w, h) {
      c.style.width=w+'px'; c.style.height=h+'px';
      c.width=w*dpr; c.height=h*dpr;
      // ctx is null for a WebGPU canvas (no 2D context to transform).
      if (ctx) ctx.setTransform(dpr,0,0,dpr,0,0);
    }

    if (p.kind === '2d') {
      // ── 2D: all elements absolutely positioned within pw×ph container ──
      // When physical axes are present, reserve PAD gutters for tick labels.
      // When there are no axes (plain imshow) use the full canvas area so
      // no dead space appears on the left / bottom.
      const st = p.state;
      const hasPhysAxis = st && (st.is_mesh || st.has_axes)
                       && st.x_axis && st.x_axis.length >= 2
                       && st.y_axis && st.y_axis.length >= 2;
      // Always reserve the top strip for the title (mirrors 1D behaviour).
      // Left/right/bottom gutters are only used when physical axes are present.
      // The colorbar (strip + label gutter) takes space from the image width
      // so it is never clipped at the panel's right edge.
      const cbW  = _cbWidth(st);
      const padT = _padT(st);
      const imgX = hasPhysAxis ? PAD_L : 0;
      const imgY = padT;
      const imgW = Math.max(1, (hasPhysAxis ? pw - PAD_L - PAD_R : pw)
                               - (cbW ? cbW + 2 : 0));
      let   imgH = Math.max(1, ph - padT - (hasPhysAxis ? PAD_B : 0));
      // Enforce aspect ratio (st.aspect = number or "equal" → 1.0).
      if (st && st.aspect != null) {
        const asp = (st.aspect === 'equal') ? 1.0 : parseFloat(st.aspect);
        if (Number.isFinite(asp) && asp > 0) imgH = Math.max(1, Math.round(imgW / asp));
      }
      // Store on panel so event handlers and draw functions don't recompute.
      // _cbW/_padT let draw2d detect when a state push requires a re-layout.
      p.imgX = imgX; p.imgY = imgY; p.imgW = imgW; p.imgH = imgH;
      p._cbW = cbW;  p._padT = padT;

      // Title canvas: sits in the title strip above the image area
      if (p.titleCanvas && p.titleCtx) {
        p.titleCanvas.style.left    = imgX + 'px';
        p.titleCanvas.style.top     = '0px';
        p.titleCanvas.style.display = 'block';
        p.titleCanvas.style.width   = imgW + 'px';
        p.titleCanvas.style.height  = padT + 'px';
        p.titleCanvas.width  = imgW * dpr;
        p.titleCanvas.height = padT * dpr;
        p.titleCtx.setTransform(dpr, 0, 0, dpr, 0, 0);
      }

      if (p.plotWrap) {
        p.plotWrap.style.width  = pw + 'px';
        p.plotWrap.style.height = ph + 'px';
      }

      // Image canvas at the inner plot area
      p.plotCanvas.style.left = imgX + 'px';
      p.plotCanvas.style.top  = imgY + 'px';
      _sz(p.plotCanvas, p.plotCtx, imgW, imgH);

      // The 2D WebGPU image canvas (if present) sits under plotCanvas and matches
      // the image area exactly. _sz sets CSS size + dpr backing; the WebGPU
      // context reconfigures to this size on the next GPU draw.
      if (p.gpuCanvas) {
        p.gpuCanvas.style.left = imgX + 'px';
        p.gpuCanvas.style.top  = imgY + 'px';
        _sz(p.gpuCanvas, null, imgW, imgH);
      }

      // Overlay and markers match the image canvas exactly
      p.overlayCanvas.style.left = imgX + 'px';
      p.overlayCanvas.style.top  = imgY + 'px';
      _sz(p.overlayCanvas, p.ovCtx, imgW, imgH);
      p.markersCanvas.style.left = imgX + 'px';
      p.markersCanvas.style.top  = imgY + 'px';
      _sz(p.markersCanvas, p.mkCtx, imgW, imgH);

      // Status bar: 4px above bottom of image area, 4px right of left edge
      if (p.statusBar) {
        p.statusBar.style.left   = (imgX + 4) + 'px';
        p.statusBar.style.bottom = (ph - imgY - imgH + 4) + 'px';
        p.statusBar.style.top    = '';
      }

      // Scale bar: 12px above bottom-right of image area
      if (p.scaleBar) {
        p.scaleBar.style.right  = (pw - imgX - imgW + 12) + 'px';
        p.scaleBar.style.bottom = (ph - imgY - imgH + 12) + 'px';
        p.scaleBar.style.left   = '';
        p.scaleBar.style.top    = '';
      }


      // y-axis: left gutter [0, PAD_T]..[PAD_L, ph-PAD_B]
      if (p.yAxisCanvas && p.yCtx) {
        if (hasPhysAxis) {
          p.yAxisCanvas.style.display = 'block';
          p.yAxisCanvas.style.left = '0px';
          p.yAxisCanvas.style.top  = imgY + 'px';
          p.yAxisCanvas.style.width  = PAD_L + 'px';
          p.yAxisCanvas.style.height = imgH + 'px';
          p.yAxisCanvas.width  = PAD_L * dpr;
          p.yAxisCanvas.height = imgH * dpr;
          p.yCtx.setTransform(dpr, 0, 0, dpr, 0, 0);
        } else {
          p.yAxisCanvas.style.display = 'none';
        }
      }

      // x-axis: bottom gutter [PAD_L, ph-PAD_B]..[pw-PAD_R, ph]
      if (p.xAxisCanvas && p.xCtx) {
        if (hasPhysAxis) {
          p.xAxisCanvas.style.display = 'block';
          p.xAxisCanvas.style.left = imgX + 'px';
          p.xAxisCanvas.style.top  = (ph - PAD_B) + 'px';
          p.xAxisCanvas.style.width  = imgW + 'px';
          p.xAxisCanvas.style.height = PAD_B + 'px';
          p.xAxisCanvas.width  = imgW * dpr;
          p.xAxisCanvas.height = PAD_B * dpr;
          p.xCtx.setTransform(dpr, 0, 0, dpr, 0, 0);
        } else {
          p.xAxisCanvas.style.display = 'none';
        }
      }

      // Colorbar: strip + label gutter in the space reserved by _cbWidth
      if (p.cbCanvas && p.cbCtx) {
        if (cbW) {
          p.cbCanvas.style.display = 'block';
          p.cbCanvas.style.left = (imgX + imgW + 2) + 'px';
          p.cbCanvas.style.top  = imgY + 'px';
          _sz(p.cbCanvas, p.cbCtx, cbW, imgH);
        } else {
          p.cbCanvas.style.display = 'none';
        }
      }

    } else if (p.kind === '3d') {
      // ── 3D: full-panel canvases ──
      _sz(p.plotCanvas,    p.plotCtx, pw, ph);
      _sz(p.overlayCanvas, p.ovCtx,   pw, ph);
    } else {
      // ── 1D: canvas is the full pw×ph, padding is drawn internally ──
      _sz(p.plotCanvas,    p.plotCtx,    pw, ph);
      _sz(p.overlayCanvas, p.ovCtx,      pw, ph);
      _sz(p.markersCanvas, p.mkCtx,      pw, ph);
    }
  }

  // ── 2D drawing ───────────────────────────────────────────────────────────

  // Largest rect with the image's natural aspect that fits inside cw×ch,
  // centred.  All 2-D coordinate functions derive from this single rect so
  // draw, hit-test, and coordinate conversion are always consistent.
  // s = uniform scale factor (canvas px per image px).
  function _imgFitRect(iw, ih, cw, ch) {
    const s = Math.min(cw / iw, ch / ih);
    const fw = iw * s, fh = ih * s;
    return { x: (cw - fw) / 2, y: (ch - fh) / 2, w: fw, h: fh, s };
  }

  // On-screen rect occupied by image pixels at the current zoom.
  // zoom>=1: full fit-rect; zoom<1: centred shrunken rect inside the fit-rect.
  function _imgVisibleRect2d(st, pw, ph) {
    const fr = _imgFitRect(st.image_width, st.image_height, pw, ph);
    const z = st.zoom || 1.0;
    if (z >= 1.0) return fr;
    const w = fr.w * z, h = fr.h * z;
    return { x: fr.x + (fr.w - w) / 2, y: fr.y + (fr.h - h) / 2, w, h, s: fr.s * z };
  }

  // Clamp a destination rect and its UV mapping to a clip rect.
  // Returns null when fully outside the clip.
  function _clipRectUv(dx, dy, dw, dh, u0, v0, u1, v1, cx, cy, cw, ch) {
    if (!(dw > 0) || !(dh > 0) || !(cw > 0) || !(ch > 0)) return null;
    const ox0 = dx, oy0 = dy, ox1 = dx + dw, oy1 = dy + dh;
    const nx0 = Math.max(ox0, cx), ny0 = Math.max(oy0, cy);
    const nx1 = Math.min(ox1, cx + cw), ny1 = Math.min(oy1, cy + ch);
    if (nx1 <= nx0 || ny1 <= ny0) return null;
    const tx0 = (nx0 - ox0) / dw, tx1 = (nx1 - ox0) / dw;
    const ty0 = (ny0 - oy0) / dh, ty1 = (ny1 - oy0) / dh;
    const du = u1 - u0, dv = v1 - v0;
    return {
      dx: nx0, dy: ny0, dw: nx1 - nx0, dh: ny1 - ny0,
      u0: u0 + du * tx0, u1: u0 + du * tx1,
      v0: v0 + dv * ty0, v1: v0 + dv * ty1,
    };
  }

  function _buildLut32(st) {
    const dMin=st.display_min, dMax=st.display_max;
    const hMin=st.raw_min!=null?st.raw_min:dMin;
    const hMax=st.raw_max!=null?st.raw_max:dMax;
    const mode=st.scale_mode||'linear';
    const range=hMax-hMin||1;
    const cmapData=st.colormap_data||[];
    let cmapFlat=null;
    if(cmapData.length===256){
      cmapFlat=new Uint8Array(256*4);
      for(let i=0;i<256;i++){cmapFlat[i*4]=cmapData[i][0];cmapFlat[i*4+1]=cmapData[i][1];cmapFlat[i*4+2]=cmapData[i][2];cmapFlat[i*4+3]=255;}
    }
    const lut=new Uint32Array(256);
    const buf=new ArrayBuffer(4); const dv=new DataView(buf); const u32=new Uint32Array(buf);
    for(let raw=0;raw<256;raw++){
      const val=hMin+(raw/255)*range;
      let t;
      if(mode==='log'){const dMC=Math.max(dMin,1e-10),dXC=Math.max(dMax,dMC+1e-10);t=(Math.log10(Math.max(val,1e-10))-Math.log10(dMC))/(Math.log10(dXC)-Math.log10(dMC));}
      else if(mode==='symlog'){const lt=Math.max((dMax-dMin)*0.01,1e-10);const sl=v=>v>=0?(v<=lt?v/lt:1+Math.log10(v/lt)):-(Math.abs(v)<=lt?Math.abs(v)/lt:1+Math.log10(Math.abs(v)/lt));t=(sl(val)-sl(dMin))/((sl(dMax)-sl(dMin))||1);}
      else{t=(val-dMin)/((dMax-dMin)||1);}
      const idx=Math.max(0,Math.min(255,Math.round(t*255)));
      if(cmapFlat){dv.setUint8(0,cmapFlat[idx*4]);dv.setUint8(1,cmapFlat[idx*4+1]);dv.setUint8(2,cmapFlat[idx*4+2]);dv.setUint8(3,255);}
      else{dv.setUint8(0,idx);dv.setUint8(1,idx);dv.setUint8(2,idx);dv.setUint8(3,255);}
      lut[raw]=u32[0];
    }
    return lut;
  }

  function _lutKey(st) {
    return [st.display_min,st.display_max,st.raw_min,st.raw_max,st.scale_mode,st.colormap_name].join('|');
  }

  function _imgToCanvas2d(ix, iy, st, pw, ph) {
    const { x, y, w, h } = _imgFitRect(st.image_width, st.image_height, pw, ph);
    const zoom = st.zoom, cx = st.center_x, cy = st.center_y;
    const iw = st.image_width, ih = st.image_height;
    // +0.5: image coordinate i is the centre of pixel i, which renders at
    // (i + 0.5) * scale in the canvas — not the leading edge (i * scale).
    if (zoom < 1.0) {
      const dstW = w * zoom, dstH = h * zoom;
      const dstX = x + (w - dstW) / 2, dstY = y + (h - dstH) / 2;
      return [dstX + (ix + 0.5) / iw * dstW, dstY + (iy + 0.5) / ih * dstH];
    }
    const visW = iw / zoom, visH = ih / zoom;
    const srcX = Math.max(0, Math.min(iw - visW, cx * iw - visW / 2));
    const srcY = Math.max(0, Math.min(ih - visH, cy * ih - visH / 2));
    return [x + (ix + 0.5 - srcX) / visW * w, y + (iy + 0.5 - srcY) / visH * h];
  }

  // Returns canvas-px per image-px at the current zoom (uniform in x and y).
  function _imgScale2d(st, pw, ph) {
    return _imgFitRect(st.image_width, st.image_height, pw, ph).s * st.zoom;
  }

  // Build (and cache on the panel) the Canvas2D bitmap for the detail tile —
  // LUT-colormapped like the base. Returns null if no tile. Cached by the tile's
  // content key so it rebuilds only when the tile or LUT changes.
  function _detailBitmap(p, st) {
    if (st.is_rgb) return null;
    const d = _detailBytes(st);
    if (!d.bytes || !st.detail_width || !st.detail_height) return null;
    const dw = st.detail_width, dh = st.detail_height;
    const lk = _lutKey(st);
    const cache = (p._detailBlit ||= {});
    if (cache.bitmap && cache.key === d.key && cache.lutKey === lk
        && cache.w === dw && cache.h === dh) return cache.bitmap;
    if (d.bytes.length < dw * dh) return null;
    const imgData = new ImageData(dw, dh);
    const lut = _buildLut32(st);
    const out32 = new Uint32Array(imgData.data.buffer);
    for (let i = 0; i < dw * dh; i++) out32[i] = lut[d.bytes[i]];
    const oc = new OffscreenCanvas(dw, dh);
    oc.getContext('2d').putImageData(imgData, 0, 0);
    cache.bitmap = oc; cache.key = d.key; cache.lutKey = lk;
    cache.w = dw; cache.h = dh;
    return oc;
  }

  // Brief alpha ramp when detail-overlay mode changes (none/partial/full).
  const _DETAIL_BLEND_MS = 90;

  function _detailBlendAlpha(p, mode) {
    const now = performance.now();
    const b = (p._detailBlend ||= { mode: 'none', t0: now });
    if (b.mode !== mode) { b.mode = mode; b.t0 = now; }
    if (mode === 'none') return 0;
    return Math.max(0, Math.min(1, (now - b.t0) / _DETAIL_BLEND_MS));
  }

  // ── Image layers (multi-image overlay) ─────────────────────────────────────
  // Raw single-channel pixel bytes for ONE layer. Prefers the BINARY bytes
  // (`layer_<id>_b64_bytes`, spliced into the geomCache under `<key>_bytes`) over
  // the base64 string in the layer entry's `image_b64`. Returns {bytes, key} where
  // `key` is a cheap identity for the "unchanged → skip rebuild" check.
  function _layerBytes(st, layer) {
    const pk = `layer_${layer.id}_b64`;
    const raw = st[pk + '_bytes'];
    if (raw && (raw instanceof Uint8Array || raw.byteLength !== undefined)) {
      const u8 = raw instanceof Uint8Array ? raw : new Uint8Array(raw);
      let key = layer.image_b64;            // the "\x00bin:<adler>" content token
      if (!key && u8.__aplSeq !== undefined) key = `binseq:${u8.__aplSeq}`;
      if (!key) key = `layerbin:${u8.length}`;
      return { bytes: u8, key };
    }
    const b64 = layer.image_b64 || '';
    if (!b64 || b64.charCodeAt(0) === 0) return { bytes: null, key: '' };  // token, no bytes yet
    try {
      const bin = atob(b64);
      const u8 = new Uint8Array(bin.length);
      for (let i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i);
      return { bytes: u8, key: b64 };
    } catch (_) { return { bytes: null, key: '' }; }
  }

  // Build (and cache on the panel) the LUT-colormapped RGBA OffscreenCanvas for
  // one layer. Cached per layer id by (pixel key, cmap, clim) so a live scrub only
  // rebuilds when the layer's data/appearance actually changes. Returns null when
  // the bytes aren't available or the size is wrong.
  function _layerBitmap(p, st, layer) {
    const d = _layerBytes(st, layer);
    const lw = layer.width || st.image_width;
    const lh = layer.height || st.image_height;
    if (!d.bytes || !lw || !lh || d.bytes.length < lw * lh) return null;
    const cmap = layer.cmap || 'gray';
    const dMin = layer.clim_min, dMax = layer.clim_max;
    const lutKey = [cmap, dMin, dMax].join('|');
    const cache = (p._layerBlit ||= {});
    const c = cache[layer.id];
    if (c && c.key === d.key && c.lutKey === lutKey && c.w === lw && c.h === lh)
      return c.bitmap;
    // Build a 256-entry uint32 LUT from the layer's own colormap + clim. The layer
    // bytes are quantised over [clim_min, clim_max] (Python side), so code i maps
    // linearly through that window; the LUT bakes clim→colour like the base path.
    const cmapData = layer.colormap_data || st.colormap_data || [];
    let cmapFlat = null;
    if (cmapData.length === 256) {
      cmapFlat = new Uint8Array(256 * 4);
      for (let i = 0; i < 256; i++) {
        cmapFlat[i*4] = cmapData[i][0]; cmapFlat[i*4+1] = cmapData[i][1];
        cmapFlat[i*4+2] = cmapData[i][2]; cmapFlat[i*4+3] = 255;
      }
    }
    const lut = new Uint32Array(256);
    const buf = new ArrayBuffer(4); const dv = new DataView(buf);
    const u32 = new Uint32Array(buf);
    for (let raw = 0; raw < 256; raw++) {
      // Bytes are already the normalised index over the layer's clim (Python
      // _normalize_image), so idx == raw — identity into the colormap.
      const idx = raw;
      if (cmapFlat) {
        dv.setUint8(0, cmapFlat[idx*4]); dv.setUint8(1, cmapFlat[idx*4+1]);
        dv.setUint8(2, cmapFlat[idx*4+2]); dv.setUint8(3, 255);
      } else { dv.setUint8(0, idx); dv.setUint8(1, idx); dv.setUint8(2, idx); dv.setUint8(3, 255); }
      lut[raw] = u32[0];
    }
    const imgData = new ImageData(lw, lh);
    const out32 = new Uint32Array(imgData.data.buffer);
    for (let i = 0; i < lw * lh; i++) out32[i] = lut[d.bytes[i]];
    const oc = new OffscreenCanvas(lw, lh);
    oc.getContext('2d').putImageData(imgData, 0, 0);
    cache[layer.id] = { bitmap: oc, key: d.key, lutKey, w: lw, h: lh };
    return oc;
  }

  // Composite every VISIBLE layer over the base image on plotCanvas, bottom-up,
  // using the SAME zoom/pan/fit-rect transform as the base blit (so zoom/pan track
  // exactly) at each layer's own globalAlpha. Layers draw AFTER the base + overlay
  // mask and BEFORE axes/markers/widgets, so they sit under annotations + widgets.
  // Works identically over a WebGPU base (which lives on the gpuCanvas beneath the
  // transparent plotCanvas): the layers just paint onto plotCanvas above it.
  function _drawLayers2d(p, st, imgW, imgH, ctx, iw, ih) {
    const layers = st.layers;
    if (!layers || !layers.length) { if (p._layerBlit) p._layerBlit = {}; return; }
    // Drop cache entries for layers that were removed.
    if (p._layerBlit) {
      const live = new Set(layers.map(l => l.id));
      for (const k in p._layerBlit) if (!live.has(k)) delete p._layerBlit[k];
    }
    const { x, y, w, h } = _imgFitRect(iw, ih, imgW, imgH);
    const z = st.zoom, cx = st.center_x, cy = st.center_y;
    for (const layer of layers) {
      if (layer.visible === false) continue;
      const bmp = _layerBitmap(p, st, layer);
      if (!bmp) continue;
      const alpha = layer.alpha != null ? layer.alpha : 1.0;
      const bw = bmp.width, bh = bmp.height;
      const kx = bw / iw, ky = bh / ih;    // logical→layer-texel scale (==1 here)
      ctx.save();
      ctx.globalAlpha = alpha;
      ctx.imageSmoothingEnabled = false;
      if (z >= 1.0) {
        const visW = iw / z, visH = ih / z;
        const sx = Math.max(0, Math.min(iw - visW, cx * iw - visW / 2));
        const sy = Math.max(0, Math.min(ih - visH, cy * ih - visH / 2));
        ctx.drawImage(bmp, sx * kx, sy * ky, visW * kx, visH * ky, x, y, w, h);
      } else {
        const dw = w * z, dh = h * z;
        ctx.drawImage(bmp, 0, 0, bw, bh, x + (w - dw) / 2, y + (h - dh) / 2, dw, dh);
      }
      ctx.restore();
    }
  }

  function _blit2d(p, bitmap, st, pw, ph, ctx, detailBitmap) {
    const { x, y, w, h } = _imgFitRect(st.image_width, st.image_height, pw, ph);
    const zoom = st.zoom, cx = st.center_x, cy = st.center_y;
    const iw = st.image_width, ih = st.image_height;
    ctx.clearRect(0, 0, pw, ph);
    ctx.fillStyle = theme.bgCanvas;
    ctx.fillRect(0, 0, pw, ph);
    ctx.imageSmoothingEnabled = false;
    // Base pass (overview or full frame) always draws first; detail layers blend over it.
    if (zoom >= 1.0) {
      // Zoomed in: show a portion of the image filling the fit-rect. The visible
      // window is in LOGICAL px; scale it to the bitmap's OWN texels (the base may
      // be a smaller overview: bitmap.width may be < image_width).
      const bw = bitmap.width, bh = bitmap.height;
      const kx = bw / iw, ky = bh / ih;   // logical→bitmap texel scale
      const visW = iw / zoom, visH = ih / zoom;
      const srcX = Math.max(0, Math.min(iw - visW, cx * iw - visW / 2));
      const srcY = Math.max(0, Math.min(ih - visH, cy * ih - visH / 2));
      ctx.drawImage(bitmap, srcX * kx, srcY * ky, visW * kx, visH * ky, x, y, w, h);
    } else {
      // Zoomed out: shrink the fit-rect proportionally, keep it centred. Source is
      // the whole bitmap (overview or full).
      const dstW = w * zoom, dstH = h * zoom;
      ctx.drawImage(bitmap, 0, 0, bitmap.width, bitmap.height,
        x + (w - dstW) / 2, y + (h - dstH) / 2, dstW, dstH);
    }
    const det = detailBitmap ? _detailUV(st) : null;
    const ov = (!det && detailBitmap) ? _detailOverlayRect(st, x, y, w, h) : null;
    const mode = det ? 'full' : (ov ? 'partial' : 'none');
    const alpha = _detailBlendAlpha(p, mode);
    if (mode !== 'none' && alpha < 1 && !p._detailBlendRAF) {
      p._detailBlendRAF = requestAnimationFrame(() => {
        p._detailBlendRAF = 0;
        if (p.state) draw2d(p);
      });
    }
    if (!(alpha > 0) || !detailBitmap) return;

    if (det) {
      const dw = detailBitmap.width, dh = detailBitmap.height;
      const sx = det.u0 * dw, sy = det.v0 * dh;
      const sw = (det.u1 - det.u0) * dw, sh = (det.v1 - det.v0) * dh;
      ctx.save();
      ctx.globalAlpha = alpha;
      ctx.drawImage(detailBitmap, sx, sy, sw, sh, x, y, w, h);
      ctx.restore();
      return;
    }

    const vr = _imgVisibleRect2d(st, pw, ph);
    const cl = _clipRectUv(ov.dx, ov.dy, ov.dw, ov.dh,
      0, 0, 1, 1, vr.x, vr.y, vr.w, vr.h);
    if (!cl) return;
    const dw = detailBitmap.width, dh = detailBitmap.height;
    ctx.save();
    ctx.globalAlpha = alpha;
    ctx.drawImage(detailBitmap,
      cl.u0 * dw, cl.v0 * dh, (cl.u1 - cl.u0) * dw, (cl.v1 - cl.v0) * dh,
      cl.dx, cl.dy, cl.dw, cl.dh);
    ctx.restore();
  }

  function draw2d(p) {
    const st=p.state;
    if(!st) return;
    _recordFrame(p);
    // Re-sync axis/histogram canvas visibility whenever state changes
    _resizePanelDOM(p.id, p.pw, p.ph);
    const {pw,ph,plotCtx:ctx,blitCache} = p;
    // p.imgW/imgH are set by _resizePanelDOM above (full panel when no axes,
    // padded inner area when physical axes are present).
    const imgW = p.imgW || Math.max(1, pw - PAD_L - PAD_R);
    const imgH = p.imgH || Math.max(1, ph - PAD_T - PAD_B);

    // Image bytes: prefer the binary trait (image_bytes, no atob) over base64.
    const _img = _imageBytes(st);
    const b64 = _img.key;                    // cache identity (b64 string or bin token)
    // The base bitmap is built at the OVERVIEW texel size (base_width/height in tile
    // mode; else the full image). _blit2d then draws it over the fit-rect using the
    // LOGICAL image_width/height for the zoom math, so the overview scales to the
    // full extent (lower-res until a detail tile covers the view).
    const iw=st.base_width||st.image_width, ih=st.base_height||st.image_height;

    if(!_img.bytes||iw===0||ih===0){ctx.clearRect(0,0,imgW,imgH);return;}

    const isRgb=!!st.is_rgb;   // bytes are RGBA (4/px) — no LUT applies
    const lk=isRgb?'__rgb__':_lutKey(st);

    // ── WebGPU image path (large scalar images) ─────────────────────────────
    // If the GPU path is active for this panel, draw the image raster on the
    // gpuCanvas (shader-LUT colormap on a texture) and CLEAR the plotCanvas image
    // area so the 2D decorations below (axes/colorbar/scale bar/mask/markers)
    // composite over the GPU image. Any failure reverts to the Canvas2D blit for
    // this frame (and the panel is marked unavailable on hard errors).
    // Test/diagnostic hook: record what the GPU path decided this frame.
    try { (globalThis.__apl_gpu2d ||= {})[p.id] =
      { wanted: _gpuWanted2d(st), gpu: p._gpu, hasImg: !!p._gpuImg,
        iw: st.image_width, ih: st.image_height, active: false }; } catch (_) {}
    let _gpuPainted = false;
    if (_gpuWanted2d(st) && p._gpu === 'active' && p._gpuImg) {
      if (_gpuDraw2dImage(p, st, imgW, imgH)) {
        if (p.gpuCanvas.style.display === 'none') p.gpuCanvas.style.display = 'block';
        // plotCanvas holds only decorations now → transparent, cleared each frame.
        p.plotCanvas.style.background = 'transparent';
        ctx.clearRect(0, 0, imgW, imgH);
        _gpuPainted = true;
        try { globalThis.__apl_gpu2d[p.id].active = true; } catch (_) {}
      } else {
        _tiledbg('path', `panel=${p.id} GPU draw returned FALSE → Canvas2D fallback ` +
          `(tile_enabled=${st.tile_enabled})`);
      }
    } else if (p.gpuCanvas && p.gpuCanvas.style.display !== 'none'
               && (!_gpuWanted2d(st) || p._gpu !== 'active')) {
      // GPU not painting this frame (shrank below threshold, RGB image, a
      // zoom/pan, or device lost) → hide the GPU layer, restore the opaque plot
      // canvas. gpu_active (capability) is echoed only on PERMANENT loss (the
      // device-lost handler); a transient zoom/shrink is reversible so the flag
      // stays as-is rather than flapping per frame.
      p.gpuCanvas.style.display = 'none';
      p.plotCanvas.style.background = theme.bgCanvas;
      try { globalThis.__apl_gpu2d[p.id].active = false; } catch (_) {}
    }

    if (!_gpuPainted) {
    if (globalThis.__apl_tiledbg && st.tile_enabled) {
      const reg = st.detail_region || [];
      const uv = _detailUV(st);
      _tiledbg('canvas', `panel=${p.id} CANVAS2D blit (NOT gpu) ` +
        `zoom=${(st.zoom||1).toFixed(2)} base[${st.base_width}x${st.base_height}] ` +
        `image[${st.image_width}x${st.image_height}] detail_region=[${reg.join(',')}] ` +
        `detailUV=${uv?'COVERS':'partial/none'} hasDetailBmp=${!!_detailBitmap(p, st)}`);
    }
    const needRebuild = b64!==blitCache.bytesKey || lk!==blitCache.lutKey
                     || !blitCache.bitmap || blitCache.w!==iw || blitCache.h!==ih;
    if(!needRebuild && blitCache.bitmap){
      _blit2d(p, blitCache.bitmap, st, imgW, imgH, ctx, _detailBitmap(p, st));
    } else {
      const bytes = _img.bytes;
      if (!bytes) return;
      const imgData=new ImageData(iw,ih);
      if(isRgb){
        imgData.data.set(bytes.subarray(0, iw*ih*4));
      } else {
        const lut=_buildLut32(st);
        const out32=new Uint32Array(imgData.data.buffer);
        for(let i=0;i<iw*ih;i++) out32[i]=lut[bytes[i]];
      }
      const oc=new OffscreenCanvas(iw,ih);
      oc.getContext('2d').putImageData(imgData,0,0);
      blitCache.bitmap=oc; blitCache.bytesKey=b64; blitCache.lutKey=lk;
      blitCache.w=iw; blitCache.h=ih;
      _blit2d(p, oc, st, imgW, imgH, ctx, _detailBitmap(p, st));
    }
    }

    // Kick off async GPU activation if wanted but not yet tried (first frame is
    // always Canvas2D; the device resolves, the panel builds its pipeline, and a
    // redraw flips to GPU). Mirrors the 3D path's async-init contract.
    if (_gpuWanted2d(st) && p.gpuCanvas && p._gpu === undefined) {
      p._gpu = 'pending';
      _gpuDevice().then((device) => {
        // The panel may have been removed while the device promise was pending
        // (guard like the 3D path) — don't init/report/draw on a detached panel.
        if (!device || !panels.has(p.id)) { p._gpu = 'unavailable'; return; }
        try { _gpuInitImagePanel(p, device); p._gpu = 'active'; _reportGpu(p); }
        catch (e) { p._gpu = 'unavailable';
                    console.warn('[anyplotlib] GPU image init failed:', e); }
        _redrawPanel(p);
      });
    }

    // Tile mode: once the panel has a real on-screen size, emit ONE view_changed so
    // the Python tile consumer can size the overview / initial tile to the actual
    // panel px (imgW/imgH are only known after the first layout). Fires immediately
    // (not debounced) so the first crisp tile appears without a user gesture.
    if (st.tile_enabled && !p._didInitialView && p.imgW > 0 && p.imgH > 0) {
      p._didInitialView = true;
      _emitViewChanged(p, true);
    }

    // ── Overlay mask compositing ─────────────────────────────────────────────
    // overlay_mask_b64: base64 uint8 bytes (0|255), same iw×ih as image.
    // Rendered at overlay_mask_alpha on top of the base image without clearing.
    const mob64=st.overlay_mask_b64||'';
    if(!mob64){
      // Mask cleared — release cached bitmap so memory can be reclaimed.
      if(p.maskCache) p.maskCache=null;
    } else {
      const mColor=st.overlay_mask_color||'#ff4444';
      const mAlpha=st.overlay_mask_alpha!=null?st.overlay_mask_alpha:0.4;
      // Compare fields individually to avoid building a large concatenated key
      // on every redraw during pan/zoom (mob64 can be very large).
      if(!p.maskCache||p.maskCache.b64!==mob64||p.maskCache.color!==mColor||p.maskCache.alpha!==mAlpha){
        // Parse hex colour → r,g,b
        let mr=255,mg=68,mb=68;
        if(mColor.startsWith('#')&&mColor.length===7){
          mr=parseInt(mColor.slice(1,3),16);
          mg=parseInt(mColor.slice(3,5),16);
          mb=parseInt(mColor.slice(5,7),16);
        }
        // Binary transport ships the mask bytes on the companion trait (the
        // geom then carries only a "\x00bin:" content token in mob64) — prefer
        // them; atob is the base64-in-JSON fallback.
        let mBytes;
        const mraw=st.overlay_mask_b64_bytes;
        if(mraw&&(mraw instanceof Uint8Array||mraw.byteLength!==undefined)){
          mBytes=mraw instanceof Uint8Array?mraw:new Uint8Array(mraw);
        }else{
          try{const bin=atob(mob64);mBytes=new Uint8Array(bin.length);for(let i=0;i<bin.length;i++)mBytes[i]=bin.charCodeAt(i);}catch(_){mBytes=null;}
        }
        if(mBytes&&mBytes.length===iw*ih){
          const mImg=new ImageData(iw,ih);
          // Write colour where mask=255; transparent where mask=0.
          // Store full-alpha pixel; globalAlpha controls final transparency.
          const buf4=new ArrayBuffer(4);const dv4=new DataView(buf4);const u32m=new Uint32Array(buf4);
          dv4.setUint8(0,mr);dv4.setUint8(1,mg);dv4.setUint8(2,mb);dv4.setUint8(3,255);
          const opaque=u32m[0];
          const out32m=new Uint32Array(mImg.data.buffer);
          for(let i=0;i<mBytes.length;i++)out32m[i]=mBytes[i]?opaque:0;
          const moc=new OffscreenCanvas(iw,ih);
          moc.getContext('2d').putImageData(mImg,0,0);
           p.maskCache={b64:mob64,color:mColor,alpha:mAlpha,bitmap:moc};
        }else{p.maskCache=null;}
      }
      if(p.maskCache&&p.maskCache.bitmap){
        // Blit at the same zoom/pan as the base image (inline, no clearRect).
        const {x:_mx,y:_my,w:_mw,h:_mh}=_imgFitRect(iw,ih,imgW,imgH);
        const _mz=st.zoom,_mcx=st.center_x,_mcy=st.center_y;
        ctx.save();ctx.globalAlpha=mAlpha;ctx.imageSmoothingEnabled=false;
        if(_mz>=1.0){
          const _vw=iw/_mz,_vh=ih/_mz;
          const _sx=Math.max(0,Math.min(iw-_vw,_mcx*iw-_vw/2));
          const _sy=Math.max(0,Math.min(ih-_vh,_mcy*ih-_vh/2));
          ctx.drawImage(p.maskCache.bitmap,_sx,_sy,_vw,_vh,_mx,_my,_mw,_mh);
        }else{
          const _dw=_mw*_mz,_dh=_mh*_mz;
          ctx.drawImage(p.maskCache.bitmap,0,0,iw,ih,_mx+(_mw-_dw)/2,_my+(_mh-_dh)/2,_dw,_dh);
        }
        ctx.restore();
      }
    }
    // ── Image layers ─────────────────────────────────────────────────────────
    // Composited over the base image (+ overlay mask) at each layer's own
    // colormap/clim/alpha, using the same zoom/pan transform, UNDER axes/markers/
    // widgets. For a WebGPU base the layers paint on the transparent plotCanvas
    // that sits above the gpuCanvas. iw/ih == the logical image size here (tiling
    // is forbidden when layers exist, so base_width is 0 and iw == image_width).
    _drawLayers2d(p, st, imgW, imgH, ctx, iw, ih);

    // Axes / scalebar / colorbar
    _drawAxes2d(p);
    drawScaleBar2d(p);
    drawColorbar2d(p);
    drawOverlay2d(p);
    drawMarkers2d(p);
  }

  function drawScaleBar2d(p) {
    const st=p.state; if(!st||!p.scaleBar) return;
    // pcolormesh panels have non-uniform axes: no meaningful single pixel scale
    if(st.is_mesh){p.scaleBar.style.display='none';return;}
    const units=st.units||'px';
    const scaleX=st.scale_x||0;
    if(!scaleX||units==='px'){p.scaleBar.style.display='none';return;}

    const imgW=p.imgW||Math.max(1,p.pw-PAD_L-PAD_R);
    const imgH=p.imgH||Math.max(1,p.ph-PAD_T-PAD_B);

    // Compute bar width in the fit-rect pixel space
    const zoom=st.zoom||1;
    const iw=st.image_width||imgW;
    const fr=_imgFitRect(iw, st.image_height||imgH, imgW, imgH);
    const visDataW=(zoom>=1?iw/zoom:iw)*scaleX;
    const targetDataWidth=visDataW*0.2;
    const niceWidth=findNice(targetDataWidth);
    const barPx=Math.round((niceWidth/visDataW)*fr.w);  // use fit-rect width
    if(barPx<4){p.scaleBar.style.display='none';return;}

    // Layout constants (CSS pixels)
    const fontSize  = 11;
    const lineH     = 3;
    const gap       = 6;   // space between bottom of text and top of line
    const padX      = 8;
    const padTop    = 5;
    const padBot    = 5;

    // Measure text to size the canvas
    const label=`${fmtVal(niceWidth)} ${units}`;
    const cvW=Math.max(barPx, fontSize*label.length*0.6|0) + padX*2;
    const cvH=padTop + fontSize + gap + lineH + padBot;

    const sb=p.scaleBar;
    if(sb.width!==Math.round(cvW*dpr)||sb.height!==Math.round(cvH*dpr)){
      sb.width=Math.round(cvW*dpr);
      sb.height=Math.round(cvH*dpr);
      sb.style.width=cvW+'px';
      sb.style.height=cvH+'px';
    }
    const ctx=sb.getContext('2d');
    ctx.setTransform(dpr,0,0,dpr,0,0);
    ctx.clearRect(0,0,cvW,cvH);

    // Background pill
    ctx.fillStyle='rgba(0,0,0,0.60)';
    const r=5;
    ctx.beginPath();
    ctx.moveTo(r,0);ctx.lineTo(cvW-r,0);ctx.arcTo(cvW,0,cvW,r,r);
    ctx.lineTo(cvW,cvH-r);ctx.arcTo(cvW,cvH,cvW-r,cvH,r);
    ctx.lineTo(r,cvH);ctx.arcTo(0,cvH,0,cvH-r,r);
    ctx.lineTo(0,r);ctx.arcTo(0,0,r,0,r);
    ctx.closePath();ctx.fill();

    // Label (centred over the bar line)
    const lineX=(cvW-barPx)/2;
    const textY=padTop+fontSize;
    ctx.fillStyle='white';
    ctx.font=`bold ${fontSize}px sans-serif`;
    ctx.textAlign='center';
    ctx.textBaseline='alphabetic';
    ctx.fillText(label, cvW/2, textY);

    // Bar line
    const lineY=padTop+fontSize+gap;
    ctx.fillStyle='white';
    ctx.fillRect(lineX, lineY, barPx, lineH);

    // End ticks
    ctx.fillRect(lineX, lineY-3, 2, lineH+3);
    ctx.fillRect(lineX+barPx-2, lineY-3, 2, lineH+3);

    sb.style.display='block';
  }

  function drawColorbar2d(p) {
    const st=p.state; if(!st||!p.cbCanvas||!p.cbCtx) return;
    const vis=(st.show_colorbar&&!st.is_rgb)||false;   // no LUT for RGB images
    p.cbCanvas.style.display = vis ? 'block' : 'none';
    if(!vis) return;

    const cbStripW=16;
    const cbLabel=st.colorbar_label||'';
    const cbW=_cbWidth(st)||cbStripW;
    const imgH=p.imgH||Math.max(1,p.ph-PAD_T-PAD_B);
    const ctx=p.cbCtx;
    ctx.clearRect(0,0,cbW,imgH);

    // Gradient strip
    if(st.colormap_data&&st.colormap_data.length===256){
      for(let py=0;py<imgH;py++){
        const frac=1-py/(imgH-1||1);
        const ci=Math.max(0,Math.min(255,Math.round(frac*255)));
        const [r2,g2,b2]=st.colormap_data[ci];
        ctx.fillStyle=`rgb(${r2},${g2},${b2})`;
        ctx.fillRect(0,py,cbStripW,1);
      }
    } else {
      ctx.fillStyle=theme.dark?'#444':'#ccc';
      ctx.fillRect(0,0,cbStripW,imgH);
    }

    // Border
    ctx.strokeStyle=theme.border||'#888';
    ctx.lineWidth=0.5;
    ctx.strokeRect(0,0,cbStripW,imgH);

    // display_min / display_max tick marks
    const dMin=st.display_min, dMax=st.display_max;
    const hMin=st.raw_min!=null?st.raw_min:dMin;
    const hMax=st.raw_max!=null?st.raw_max:dMax;
    const vRange=(hMax-hMin)||1;
    function _vToY(v){return imgH-1-((v-hMin)/vRange)*(imgH-1);}
    ctx.strokeStyle='rgba(255,255,255,0.85)'; ctx.lineWidth=1.5;
    ctx.beginPath();ctx.moveTo(0,_vToY(dMax));ctx.lineTo(cbStripW,_vToY(dMax));ctx.stroke();
    ctx.beginPath();ctx.moveTo(0,_vToY(dMin));ctx.lineTo(cbStripW,_vToY(dMin));ctx.stroke();

    // Colorbar label (rotated −90°, centred in the label gutter)
    if(cbLabel){
      ctx.save();
      ctx.translate(cbStripW + (cbW - cbStripW) / 2 + 1, imgH/2);
      ctx.rotate(-Math.PI/2);
      ctx.textBaseline='middle';
      ctx.fillStyle=theme.unitText;
      _drawTex(ctx,cbLabel,0,0,st.colorbar_label_size||10,{align:'center'});
      ctx.restore();
    }
  }


  function _drawAxes2d(p) {
    const st=p.state; if(!st) return;
    const {pw,ph} = p;
    const imgW = p.imgW||Math.max(1, pw - PAD_L - PAD_R);
    const imgH = p.imgH||Math.max(1, ph - PAD_T - PAD_B);
    const xArr=st.x_axis||[], yArr=st.y_axis||[];
    const TICK=6;
    const zoom=st.zoom, cx=st.center_x, cy=st.center_y;
    const units=st.units||'px';
    const hasPhysAxis = (st.is_mesh || st.has_axes) && xArr.length>=2 && yArr.length>=2;
    if(st.axis_visible===false){
      if(p.xAxisCanvas) p.xAxisCanvas.style.display='none';
      if(p.yAxisCanvas) p.yAxisCanvas.style.display='none';
    } else if(hasPhysAxis){
      if(st.x_ticks_visible===false&&p.xAxisCanvas) p.xAxisCanvas.style.display='none';
      if(st.y_ticks_visible===false&&p.yAxisCanvas) p.yAxisCanvas.style.display='none';
    }
    const hasX=hasPhysAxis&&st.axis_visible!==false&&st.x_ticks_visible!==false&&p.xCtx&&p.xAxisCanvas&&p.xAxisCanvas.style.display!=='none';
    const hasY=hasPhysAxis&&st.axis_visible!==false&&st.y_ticks_visible!==false&&p.yCtx&&p.yAxisCanvas&&p.yAxisCanvas.style.display!=='none';

    function _visFrac(z,c){
      if(z>=1.0){const h=0.5/z;const cc=Math.max(h,Math.min(1-h,c));return[cc-h,cc+h];}
      return[0,1];
    }
    function _fracToPx(frac, z, center, span) {
      if(z>=1.0){
        const h=0.5/z, cc=Math.max(h,Math.min(1-h,center));
        return (frac-(cc-h))/(2*h)*span;
      }
      return (span-span*z)/2+frac*span*z;
    }

    // ── X axis canvas: imgW × PAD_B, origin at top-left ─────────────────
    // x=0 aligns with the left edge of the image, spans imgW pixels
    if(hasX){
      const aw=imgW, ah=PAD_B;
      p.xCtx.clearRect(0,0,aw,ah);
      p.xCtx.fillStyle=theme.axisBg; p.xCtx.fillRect(0,0,aw,ah);
      p.xCtx.strokeStyle=theme.axisStroke; p.xCtx.lineWidth=1;
      p.xCtx.beginPath(); p.xCtx.moveTo(0,0); p.xCtx.lineTo(aw,0); p.xCtx.stroke();
      const [xF0,xF1]=_visFrac(zoom,cx);
      const xVMin=_axisFracToVal(xArr,xF0), xVMax=_axisFracToVal(xArr,xF1);
      const step=findNice((xVMax-xVMin)/Math.max(3,Math.floor(imgW/60)));
      p.xCtx.strokeStyle=theme.tickStroke;
      p.xCtx.fillStyle=theme.tickText; p.xCtx.font=(st.tick_size||10)+'px sans-serif';
      p.xCtx.textAlign='center'; p.xCtx.textBaseline='top';
      // Generate nice tick values; place each at its true canvas position
      // via binary-search into the axis array (works for both linear and
      // non-linear / pcolormesh edge arrays).
      const xTicks=[];
      for(let v=Math.ceil(xVMin/step)*step; v<=xVMax+step*0.01; v+=step) xTicks.push(v);
      // Clamp first/last label so it doesn't overflow the canvas edges
      const minLabelGap=28; // px — minimum gap between adjacent labels
      let lastPx=-Infinity;
      for(let ti=0;ti<xTicks.length;ti++){
        const v=xTicks[ti];
        const frac=_axisValToFrac(xArr,v);
        const px2=_fracToPx(frac,zoom,cx,imgW);
        if(px2<0||px2>imgW) continue;
        p.xCtx.beginPath(); p.xCtx.moveTo(px2,0); p.xCtx.lineTo(px2,TICK); p.xCtx.stroke();
        // Skip label if too close to the previous one
        if(px2-lastPx>=minLabelGap){
          const txt=fmtVal(v);
          // Nudge edge labels inward so they are never clipped by the canvas
          const hw=p.xCtx.measureText(txt).width/2;
          p.xCtx.fillText(txt, Math.min(Math.max(px2,hw), aw-hw), TICK+2);
          lastPx=px2;
        }
      }
      p.xCtx.textAlign='right'; p.xCtx.textBaseline='bottom';
      p.xCtx.fillStyle=theme.unitText; p.xCtx.font='9px sans-serif';
      p.xCtx.fillText(units, aw-2, ah-1);
      const xlabel=st.x_label||'';
      if(xlabel){p.xCtx.fillStyle=theme.tickText;p.xCtx.textBaseline='bottom';_drawTex(p.xCtx,xlabel,aw/2,ah-2,st.x_label_size||11,{align:'center'});}
    }

    // ── Y axis canvas: PAD_L × imgH, origin at top-left ─────────────────
    // y=0 aligns with the top edge of the image, spans imgH pixels
    if(hasY){
      const aw=PAD_L, ah=imgH;
      p.yCtx.clearRect(0,0,aw,ah);
      p.yCtx.fillStyle=theme.axisBg; p.yCtx.fillRect(0,0,aw,ah);
      p.yCtx.strokeStyle=theme.axisStroke; p.yCtx.lineWidth=1;
      p.yCtx.beginPath(); p.yCtx.moveTo(aw,0); p.yCtx.lineTo(aw,ah); p.yCtx.stroke();
      const [yF0,yF1]=_visFrac(zoom,cy);
      const yVMin=_axisFracToVal(yArr,yF0), yVMax=_axisFracToVal(yArr,yF1);
      const step=findNice((yVMax-yVMin)/Math.max(3,Math.floor(imgH/60)));
      p.yCtx.strokeStyle=theme.tickStroke;
      p.yCtx.fillStyle=theme.tickText; p.yCtx.font=(st.tick_size||10)+'px sans-serif';
      p.yCtx.textAlign='right'; p.yCtx.textBaseline='middle';
      const yTicks=[];
      for(let v=Math.ceil(yVMin/step)*step; v<=yVMax+step*0.01; v+=step) yTicks.push(v);
      const minLabelGapY=14; // px
      let lastPy=-Infinity;
      for(let ti=0;ti<yTicks.length;ti++){
        const v=yTicks[ti];
        const frac=_axisValToFrac(yArr,v);
        const py2=_fracToPx(frac,zoom,cy,imgH);
        if(py2<0||py2>imgH) continue;
        p.yCtx.beginPath(); p.yCtx.moveTo(aw,py2); p.yCtx.lineTo(aw-TICK,py2); p.yCtx.stroke();
        if(py2-lastPy>=minLabelGapY){
          // Nudge edge labels inward so digits are never cut by the canvas
          const vh=(st.tick_size||10)*0.5+1;
          p.yCtx.fillText(fmtVal(v), aw-TICK-2, Math.min(Math.max(py2,vh), ah-vh));
          lastPy=py2;
        }
      }
      // Units label: top-left corner of y-axis gutter
      p.yCtx.textAlign='left'; p.yCtx.textBaseline='top';
      p.yCtx.fillStyle=theme.unitText; p.yCtx.font='9px sans-serif';
      p.yCtx.fillText(units, 2, 1);
      const ylabel=st.y_label||'';
      if(ylabel){
        p.yCtx.save();
        // Keep the rotated label's full height inside the gutter at large sizes
        const ylpx=st.y_label_size||11;
        p.yCtx.translate(Math.max(Math.round(aw*0.15), Math.ceil(ylpx*0.62)+1), ah/2);
        p.yCtx.rotate(-Math.PI/2);
        p.yCtx.textBaseline='middle';
        p.yCtx.fillStyle=theme.tickText;
        _drawTex(p.yCtx,ylabel,0,0,ylpx,{align:'center'});
        p.yCtx.restore();
      }
    }
    const title2d = st.title || '';
    if (p.titleCanvas && p.titleCtx) {
      const tw   = p.imgW || imgW;
      const padT = p._padT || PAD_T;   // strip grows with title_size > 11
      p.titleCtx.clearRect(0, 0, tw, padT);
      if (title2d) {
        // Clamp the drawn size so even the tallest glyphs (caps, descenders,
        // TeX superscripts) fit the strip WITH clear top/bottom margin on
        // every platform.  Font hinting varies — macOS Chromium renders ~1px
        // taller than Windows at the same px — so a strip-tight title was
        // clipped at row 0 on macOS CI.  Reserve ~4px total vertical margin;
        // padT grows for large/TeX titles (see _padT) so this only bites the
        // 12px default strip, capping an 11px title to ~8px — a sub-pixel
        // change well within the visual-regression tolerance.
        const px = Math.min(st.title_size || 11, padT - 4);
        p.titleCtx.fillStyle = theme.tickText;
        p.titleCtx.textBaseline = 'middle';
        _drawTex(p.titleCtx, title2d, tw / 2, padT / 2,
                 px, { align: 'center', weight: 'bold' });
      }
    }
  }

  // opts (optional): { ctx, imgW, imgH, forceNoHandles }
  //   ctx/imgW/imgH default to the panel's own live overlay canvas/dims — pass
  //   an offscreen ctx + matching dims to redraw the SAME widgets elsewhere
  //   (e.g. exportPNG's handle-free export redraw; see _drawOverlay2dNoHandles).
  //   forceNoHandles suppresses the handle dots regardless of each widget's
  //   own show_handles (mirrors _drawFigureMarkers(sizeOverride, forceNoHandles)).
  function drawOverlay2d(p, opts) {
    const st=p.state; if(!st) return;
    const o = opts || {};
    const {pw,ph} = p;
    const ovCtx = o.ctx || p.ovCtx;
    const imgW = o.imgW || p.imgW || Math.max(1,pw-PAD_L-PAD_R);
    const imgH = o.imgH || p.imgH || Math.max(1,ph-PAD_T-PAD_B);
    ovCtx.clearRect(0,0,imgW,imgH);
    const widgets=st.overlay_widgets||[];
    const scale=_imgScale2d(st,imgW,imgH);
    const vr = _imgVisibleRect2d(st, imgW, imgH);
    ovCtx.save();
    ovCtx.beginPath(); ovCtx.rect(vr.x, vr.y, vr.w, vr.h); ovCtx.clip();
    for(const w of widgets){
      if(w.visible === false) continue;
      // Handle dots are drawn unless the widget opts out (show_handles:false),
      // or the caller forces them off entirely (export redraw).
      const _handles = !o.forceNoHandles && w.show_handles !== false;
      ovCtx.save(); ovCtx.strokeStyle=w.color||'#00e5ff'; ovCtx.lineWidth=2;
      if(w.type==='circle'){
        const [ccx,ccy]=_imgToCanvas2d(w.cx,w.cy,st,imgW,imgH);
        ovCtx.beginPath(); ovCtx.arc(ccx,ccy,w.r*scale,0,Math.PI*2); ovCtx.stroke();
        if(_handles){
          // Centre node = move; east-point node = resize radius.
          _drawHandle2d(ovCtx,ccx,ccy,w.color);
          _drawHandle2d(ovCtx,ccx+w.r*scale,ccy,w.color);
        }
      } else if(w.type==='annular'){
        const [ccx,ccy]=_imgToCanvas2d(w.cx,w.cy,st,imgW,imgH);
        ovCtx.beginPath();ovCtx.arc(ccx,ccy,w.r_outer*scale,0,Math.PI*2);ovCtx.stroke();
        ovCtx.beginPath();ovCtx.arc(ccx,ccy,w.r_inner*scale,0,Math.PI*2);ovCtx.stroke();
        if(_handles){
          _drawHandle2d(ovCtx,ccx+w.r_outer*scale,ccy,w.color);
          _drawHandle2d(ovCtx,ccx+w.r_inner*scale,ccy-w.r_inner*scale*0.3,w.color);
        }
      } else if(w.type==='rectangle'){
        const [rx,ry]=_imgToCanvas2d(w.x,w.y,st,imgW,imgH);
        const rw=w.w*scale, rh=w.h*scale;
        ovCtx.strokeRect(rx,ry,rw,rh);
        if(_handles){
          _drawHandle2d(ovCtx,rx,ry,w.color);_drawHandle2d(ovCtx,rx+rw,ry,w.color);
          _drawHandle2d(ovCtx,rx,ry+rh,w.color);_drawHandle2d(ovCtx,rx+rw,ry+rh,w.color);
        }
      } else if(w.type==='crosshair'){
        const [ccx,ccy]=_imgToCanvas2d(w.cx,w.cy,st,imgW,imgH);
        ovCtx.beginPath();ovCtx.moveTo(0,ccy);ovCtx.lineTo(imgW,ccy);ovCtx.stroke();
        ovCtx.beginPath();ovCtx.moveTo(ccx,0);ovCtx.lineTo(ccx,imgH);ovCtx.stroke();
        if(_handles){ovCtx.beginPath();ovCtx.arc(ccx,ccy,4,0,Math.PI*2);ovCtx.fillStyle=w.color||'#00e5ff';ovCtx.fill();}
      } else if(w.type==='polygon'){
        const verts=w.vertices||[];
        if(verts.length>=2){
          ovCtx.beginPath();
          const [px0,py0]=_imgToCanvas2d(verts[0][0],verts[0][1],st,imgW,imgH);
          ovCtx.moveTo(px0,py0);
          for(let k=1;k<verts.length;k++){const[px,py]=_imgToCanvas2d(verts[k][0],verts[k][1],st,imgW,imgH);ovCtx.lineTo(px,py);}
          ovCtx.closePath();ovCtx.stroke();
          if(_handles) for(const v of verts){const[px,py]=_imgToCanvas2d(v[0],v[1],st,imgW,imgH);_drawHandle2d(ovCtx,px,py,w.color);}
        }
      } else if(w.type==='label'){
        const [lx,ly]=_imgToCanvas2d(w.x,w.y,st,imgW,imgH);
        ovCtx.font=`${w.fontsize||14}px sans-serif`;ovCtx.fillStyle=w.color||'#00e5ff';
        ovCtx.textAlign='left';ovCtx.textBaseline='top';ovCtx.fillText(w.text||'',lx,ly);
        if(_handles) _drawHandle2d(ovCtx,lx,ly,w.color);
      } else if(w.type==='arrow'){
        // Shaft from tail (x,y) to head (x+u,y+v), then a filled arrowhead —
        // reusing the head math from the static 'arrows' marker branch.
        const [tx,ty]=_imgToCanvas2d(w.x,w.y,st,imgW,imgH);
        const [hx,hy]=_imgToCanvas2d(w.x+w.u,w.y+w.v,st,imgW,imgH);
        ovCtx.lineWidth=(w.linewidth!=null?w.linewidth:2);
        ovCtx.fillStyle=w.color||'#00e5ff';
        const ang=Math.atan2(hy-ty,hx-tx), HL=10;
        ovCtx.beginPath();ovCtx.moveTo(tx,ty);ovCtx.lineTo(hx,hy);ovCtx.stroke();
        ovCtx.beginPath();ovCtx.moveTo(hx,hy);
        ovCtx.lineTo(hx-HL*Math.cos(ang-Math.PI/6),hy-HL*Math.sin(ang-Math.PI/6));
        ovCtx.lineTo(hx-HL*Math.cos(ang+Math.PI/6),hy-HL*Math.sin(ang+Math.PI/6));
        ovCtx.closePath();ovCtx.fill();
        if(_handles){_drawHandle2d(ovCtx,tx,ty,w.color);_drawHandle2d(ovCtx,hx,hy,w.color);}
      }
      ovCtx.restore();
    }
    ovCtx.restore();
  }

  function _drawHandle2d(ctx,x,y,color){
    ctx.save();ctx.fillStyle='#fff';ctx.strokeStyle=color||'#00e5ff';ctx.lineWidth=1.5;
    ctx.beginPath();ctx.arc(x,y,5,0,Math.PI*2);ctx.fill();ctx.stroke();ctx.restore();
  }

  function drawMarkers2d(p, hoverState) {
    const st=p.state; if(!st) return;
    const {pw,ph,mkCtx} = p;
    const imgW=p.imgW||Math.max(1,pw-PAD_L-PAD_R), imgH=p.imgH||Math.max(1,ph-PAD_T-PAD_B);
    mkCtx.clearRect(0,0,imgW,imgH);
    const sets=st.markers||[];
    if(!sets.length) return;
    const scale=_imgScale2d(st,imgW,imgH);
    const vr = _imgVisibleRect2d(st, imgW, imgH);
    const hsi = hoverState ? hoverState.si : -1;

    for(let si=0;si<sets.length;si++){
      const ms=sets[si];
      const isHov = si===hsi;
      const color = ms.color      || '#ff0000';
      const fc    = ms.fill_color || null;
      const fa    = ms.fill_alpha != null ? ms.fill_alpha : 0.3;
      const lw    = ms.linewidth  != null ? ms.linewidth  : 1.5;
      // Hover colours: only applied when explicitly set — no default fallback.
      // When hovered the whole group switches colour; linewidth bumped by 1.
      const ec  = isHov && ms.hover_color     ? ms.hover_color     : color;
      const fch = isHov && ms.hover_facecolor ? ms.hover_facecolor : fc;
      const dlw = isHov && (ms.hover_color || ms.hover_facecolor) ? lw+1 : lw;
      const type = ms.type || 'circles';

      // Coordinate transform dispatch: "data" (default), "axes", "display".
      // For non-data transforms sizes are in pixels, not scaled by zoom.
      const tfm = ms.transform || 'data';
      const clipSet = tfm !== 'display' || ms.clip_display !== false;
      let _tc;
      if(tfm==='axes'){
        const fr=_imgFitRect(st.image_width,st.image_height,imgW,imgH);
        _tc=(fx,fy)=>[fr.x+fx*fr.w, fr.y+(1-fy)*fr.h];
      } else if(tfm==='display'){
        _tc=(ix,iy)=>[ix,iy];
      } else {
        _tc=(ix,iy)=>_imgToCanvas2d(ix,iy,st,imgW,imgH);
      }
      const scl = tfm==='data' ? scale : 1;

      mkCtx.save();
      if(clipSet){
        mkCtx.beginPath(); mkCtx.rect(vr.x, vr.y, vr.w, vr.h); mkCtx.clip();
      }
      mkCtx.strokeStyle=ec; mkCtx.fillStyle=ec; mkCtx.lineWidth=dlw;

      if(type==='circles'){
        for(let i=0;i<ms.offsets.length;i++){
          const [cx,cy]=_tc(ms.offsets[i][0],ms.offsets[i][1]);
          const r=Math.max(1,(ms.sizes[i]!=null?ms.sizes[i]:ms.sizes[0]||5)*scl);
          mkCtx.beginPath();mkCtx.arc(cx,cy,r,0,Math.PI*2);
          if(fch){mkCtx.save();mkCtx.globalAlpha=fa;mkCtx.fillStyle=fch;mkCtx.fill();mkCtx.restore();}
          mkCtx.stroke();
        }
      } else if(type==='arrows'){
        const HL=8;
        for(let i=0;i<ms.offsets.length;i++){
          const [x1,y1]=_tc(ms.offsets[i][0],ms.offsets[i][1]);
          const u=(ms.U[i]||0)*scl, v=(ms.V[i]||0)*scl;
          const x2=x1+u,y2=y1+v,ang=Math.atan2(y2-y1,x2-x1);
          mkCtx.beginPath();mkCtx.moveTo(x1,y1);mkCtx.lineTo(x2,y2);mkCtx.stroke();
          mkCtx.beginPath();mkCtx.moveTo(x2,y2);
          mkCtx.lineTo(x2-HL*Math.cos(ang-Math.PI/6),y2-HL*Math.sin(ang-Math.PI/6));
          mkCtx.lineTo(x2-HL*Math.cos(ang+Math.PI/6),y2-HL*Math.sin(ang+Math.PI/6));
          mkCtx.closePath();mkCtx.fill();
        }
      } else if(type==='ellipses'){
        for(let i=0;i<ms.offsets.length;i++){
          const [cx,cy]=_tc(ms.offsets[i][0],ms.offsets[i][1]);
          const rw=Math.max(1,(ms.widths[i]||ms.widths[0]||10)*scl/2);
          const rh=Math.max(1,(ms.heights[i]||ms.heights[0]||10)*scl/2);
          const ang=((ms.angles[i]||ms.angles[0]||0)*Math.PI)/180;
          mkCtx.beginPath();mkCtx.ellipse(cx,cy,rw,rh,ang,0,Math.PI*2);
          if(fch){mkCtx.save();mkCtx.globalAlpha=fa;mkCtx.fillStyle=fch;mkCtx.fill();mkCtx.restore();}
          mkCtx.stroke();
        }
      } else if(type==='lines'){
        for(const seg of (ms.segments||[])){
          const [x1,y1]=_tc(seg[0][0],seg[0][1]);
          const [x2,y2]=_tc(seg[1][0],seg[1][1]);
          mkCtx.beginPath();mkCtx.moveTo(x1,y1);mkCtx.lineTo(x2,y2);mkCtx.stroke();
        }
      } else if(type==='rectangles'||type==='squares'){
        const heights=type==='squares'?ms.widths:ms.heights;
        for(let i=0;i<ms.offsets.length;i++){
          const [cx,cy]=_tc(ms.offsets[i][0],ms.offsets[i][1]);
          const rw=(ms.widths[i]||ms.widths[0]||20)*scl;
          const rh=((heights[i]||heights[0]||20))*scl;
          const ang=((ms.angles&&(ms.angles[i]||ms.angles[0])||0)*Math.PI)/180;
          mkCtx.save();mkCtx.translate(cx,cy);mkCtx.rotate(ang);
          if(fch){mkCtx.save();mkCtx.globalAlpha=fa;mkCtx.fillStyle=fch;mkCtx.fillRect(-rw/2,-rh/2,rw,rh);mkCtx.restore();}
          mkCtx.strokeRect(-rw/2,-rh/2,rw,rh);
          mkCtx.restore();
        }
      } else if(type==='polygons'){
        for(let i=0;i<(ms.vertices_list||[]).length;i++){
          const verts=ms.vertices_list[i];
          if(!verts||verts.length<2) continue;
          const [px0,py0]=_tc(verts[0][0],verts[0][1]);
          mkCtx.beginPath();mkCtx.moveTo(px0,py0);
          for(let k=1;k<verts.length;k++){const[px,py]=_tc(verts[k][0],verts[k][1]);mkCtx.lineTo(px,py);}
          mkCtx.closePath();
          if(fch){mkCtx.save();mkCtx.globalAlpha=fa;mkCtx.fillStyle=fch;mkCtx.fill();mkCtx.restore();}
          mkCtx.stroke();
        }
      } else if(type==='texts'){
        const fs=ms.fontsize||12;
        mkCtx.font=`${fs}px sans-serif`;mkCtx.textAlign='left';mkCtx.textBaseline='top';
        for(let i=0;i<ms.offsets.length;i++){
          const [cx,cy]=_tc(ms.offsets[i][0],ms.offsets[i][1]);
          mkCtx.fillText(String(ms.texts[i]||''),cx,cy);
        }
      }
      mkCtx.restore();
    }
  }

  // ── 3D drawing ───────────────────────────────────────────────────────────

  function _rot3(az, el) {
    // Turntable camera (matplotlib azim/elev semantics): azimuth spins the
    // scene about the DATA z-axis, elevation tilts it toward the viewer.
    // Screen axes after rotation: x'→right, y'→depth into screen, z'→up.
    // Unlike the previous Ry·Rx form (which pinned the data x-axis into the
    // screen plane), this view direction reaches ANY point on the sphere —
    // required for rotate-to-face interactions (e.g. the IPF explorer).
    // The camera faces unit vector v when  el = asin(vz),  az = atan2(vx, -vy).
    const azR = az * Math.PI / 180, elR = el * Math.PI / 180;
    const ca = Math.cos(azR), sa = Math.sin(azR);
    const ce = Math.cos(elR), se = Math.sin(elR);
    // R = Tilt_x(el) * Spin_z(az)
    return [
      [ ca,     sa,     0 ],
      [-ce*sa,  ce*ca, -se],
      [-se*sa,  se*ca,  ce],
    ];
  }

  function _applyRot(R, v) {
    return [
      R[0][0]*v[0] + R[0][1]*v[1] + R[0][2]*v[2],
      R[1][0]*v[0] + R[1][1]*v[1] + R[1][2]*v[2],
      R[2][0]*v[0] + R[2][1]*v[1] + R[2][2]*v[2],
    ];
  }

  function _project3(rv, cx, cy, scale) {
    // Weak perspective: x→right, z→up on screen
    return [cx + rv[0] * scale, cy - rv[2] * scale];
  }

  function _colourFromLut(lut, t) {
    // t in [0,1] → CSS colour from 256-entry [[r,g,b],...] lut
    const i = Math.max(0, Math.min(255, Math.round(t * 255)));
    const c = lut[i];
    if (!c) return '#888';
    return `rgb(${c[0]},${c[1]},${c[2]})`;
  }

  // ═══════════════════════════════════════════════════════════════════════
  // WebGPU geometry renderer (progressive enhancement — Phase 1 prototype).
  //
  // Strictly additive: only instanced POINTS move to the GPU, and only when
  // (a) navigator.gpu exists, (b) an adapter+device resolve, and (c) the
  // panel opts in (gpu_mode 'always', or 'auto' above GPU_POINT_THRESHOLD).
  // Every failure — no navigator.gpu, null adapter, device loss — leaves
  // p._gpu === 'unavailable' and the Canvas2D path renders exactly as before.
  //
  // Decorations (axes, labels, sphere, planes, highlight) are NEVER on the
  // GPU; draw3d draws them over a transparent plotCanvas when GPU is active.
  // ═══════════════════════════════════════════════════════════════════════
  const GPU_POINT_THRESHOLD = 20000;
  const GPU_VOXEL_THRESHOLD = 8000;   // cubes cost ~6× a point on canvas
  // A 2-D scalar image goes to the GPU (shader-LUT colormap on a texture) above
  // this many pixels — below it the Canvas2D atob+LUT loop is already instant.
  // ~1 megapixel: a 1024² image and up (a large in-situ movie frame is 16-64 Mpx).
  const GPU_IMAGE_THRESHOLD = 1 << 20;
  let _gpuDevicePromise = null;   // module singleton: Promise<GPUDevice|null>

  function _gpuDevice() {
    if (_gpuDevicePromise) return _gpuDevicePromise;
    _gpuDevicePromise = (async () => {
      try {
        if (!navigator.gpu) return null;
        const adapter = await navigator.gpu.requestAdapter();
        if (!adapter) return null;
        const device = await adapter.requestDevice();
        device.lost.then((info) => {
          // Permanent per-session fallback: any GPU panel reverts to canvas.
          _gpuDevicePromise = Promise.resolve(null);
          for (const p of panels.values()) {
            if (p.kind === '3d' && p._gpu === 'active') {
              p._gpu = 'unavailable';
              if (p.gpuCanvas) p.gpuCanvas.style.display = 'none';
              if (p.plotCanvas) p.plotCanvas.style.background = theme.bgPlot;
              _gpuDisposePanel(p);
              _redrawPanel(p);
            } else if (p.kind === '2d' && p._gpu === 'active') {
              // 2-D image panel: revert to the Canvas2D blit path + free GPU
              // resources, and echo the fallback so plot.gpu_active goes False.
              p._gpu = 'unavailable';
              if (p.gpuCanvas) p.gpuCanvas.style.display = 'none';
              if (p.plotCanvas) p.plotCanvas.style.background = theme.bgCanvas;
              _gpuDisposeImagePanel(p);
              _reportGpu(p);
              _redrawPanel(p);
            }
          }
          console.warn('[anyplotlib] WebGPU device lost — fell back to canvas:',
                       info && info.message);
        });
        return device;
      } catch (e) {
        console.warn('[anyplotlib] WebGPU init failed — using canvas:', e);
        return null;
      }
    })();
    return _gpuDevicePromise;
  }

  // Report GPU activation back to Python via an event (so plot.gpu_active
  // reflects reality).  Fire-and-forget; ignored if no one listens.
  function _reportGpu(p) {
    try {
      _emitEvent(p.id, 'gpu_status', null, { gpu_active: p._gpu === 'active' });
    } catch (_) {}
  }

  // Should this 3-D panel try the GPU path for its current state?
  function _gpuWanted(st) {
    if (typeof navigator === 'undefined' || !navigator.gpu) return false;
    const mode = st.gpu_mode || 'auto';
    if (mode === 'off') return false;
    const geom = st.geom_type;
    if (geom !== 'scatter' && geom !== 'voxels') return false;
    if (mode === 'always') return true;
    const thr = geom === 'voxels' ? GPU_VOXEL_THRESHOLD : GPU_POINT_THRESHOLD;
    return (st.vertices_count || 0) > thr;
  }

  // Should this 2-D image panel take the WebGPU texture path? Scalar (LUT) images
  // only — RGB(A) images stay on Canvas2D (they need no colormap and are rare/
  // small). Gated by megapixels above GPU_IMAGE_THRESHOLD unless gpu_mode forces.
  function _gpuWanted2d(st) {
    if (typeof navigator === 'undefined' || !navigator.gpu) return false;
    const mode = st.gpu_mode || 'auto';
    if (mode === 'off') return false;
    if (st.is_rgb) return false;                 // no LUT → nothing to accelerate
    // Pixels present as base64 (image_b64) OR binary bytes (image_b64_bytes).
    if ((!st.image_b64 && !st.image_b64_bytes)
        || !st.image_width || !st.image_height) return false;
    // ZOOM/PAN is now honoured by the shader (the quad's clip rect + uv sub-region
    // mirror _blit2d, so the GPU image stays registered with the overlays and
    // UPSAMPLES real texels on zoom-in), so we no longer fall back on zoom. See
    // _imageDrawUniform.
    if (mode === 'always') return true;
    return (st.image_width * st.image_height) >= GPU_IMAGE_THRESHOLD;
  }

  const _GPU_POINT_WGSL = `
struct Uniforms {
  mvp      : mat4x4<f32>,   // clip-space transform (orthographic)
  viewport : vec2<f32>,     // panel pixels
  ptSize   : f32,
  _pad     : f32,
};
@group(0) @binding(0) var<uniform> U : Uniforms;

struct VsOut {
  @builtin(position) pos : vec4<f32>,
  @location(0) color     : vec4<f32>,
  @location(1) quad      : vec2<f32>,
};

// Unit quad (two triangles) expanded per instance into a screen-space square.
const QUAD = array<vec2<f32>, 6>(
  vec2(-1.0,-1.0), vec2(1.0,-1.0), vec2(-1.0,1.0),
  vec2(-1.0, 1.0), vec2(1.0,-1.0), vec2( 1.0,1.0));

@vertex
fn vs(@location(0) center : vec3<f32>,
      @location(1) color  : vec4<f32>,
      @builtin(vertex_index) vi : u32) -> VsOut {
  var out : VsOut;
  let clip = U.mvp * vec4<f32>(center, 1.0);
  let q    = QUAD[vi];
  // Offset in NDC by point size (pixels → NDC via viewport).  Orthographic,
  // so clip.w == 1; divide-by-w is implicit and the offset is in NDC units.
  let off  = vec2<f32>(q.x * U.ptSize * 2.0 / U.viewport.x,
                       q.y * U.ptSize * 2.0 / U.viewport.y);
  out.pos   = vec4<f32>(clip.x + off.x, clip.y + off.y, clip.z, 1.0);
  out.color = color;
  out.quad  = q;
  return out;
}

@fragment
fn fs(in : VsOut) -> @location(0) vec4<f32> {
  if (dot(in.quad, in.quad) > 1.0) { discard; }   // round points
  return in.color;
}
`;

  // Voxel cubes: 36 vertices (12 tris) for a unit cube centred at origin,
  // instanced per voxel.  Per-face shading + depth buffer (no sorting).
  // Slice emphasis (voxels on a PlaneWidget) is computed in the vertex shader
  // from up to 4 plane uniforms → dragging a plane is a uniform write, no
  // geometry re-upload.  Opaque mode (Phase 2); translucency is Phase 3.
  const _GPU_VOXEL_WGSL = `
struct Uniforms {
  mvp        : mat4x4<f32>,
  half       : f32,          // half voxel edge, data units
  baseAlpha  : f32,
  sliceAlpha : f32,
  nPlanes    : f32,
  planeAxis  : vec4<f32>,    // axis index 0/1/2 per plane (-1 = unused)
  planePos   : vec4<f32>,    // plane position, data units
  shade      : vec4<f32>,    // x,y,z face shade + pad
};
@group(0) @binding(0) var<uniform> U : Uniforms;

struct VsOut {
  @builtin(position) pos : vec4<f32>,
  @location(0) color     : vec4<f32>,
  @location(1) alpha     : f32,
};

// 36 cube corners (±1) and matching face axis (0=x,1=y,2=z) per triangle.
const CUBE = array<vec3<f32>, 36>(
  // +x
  vec3(1.,-1.,-1.), vec3(1.,1.,-1.), vec3(1.,1.,1.), vec3(1.,-1.,-1.), vec3(1.,1.,1.), vec3(1.,-1.,1.),
  // -x
  vec3(-1.,-1.,-1.), vec3(-1.,1.,1.), vec3(-1.,1.,-1.), vec3(-1.,-1.,-1.), vec3(-1.,-1.,1.), vec3(-1.,1.,1.),
  // +y
  vec3(-1.,1.,-1.), vec3(1.,1.,1.), vec3(1.,1.,-1.), vec3(-1.,1.,-1.), vec3(-1.,1.,1.), vec3(1.,1.,1.),
  // -y
  vec3(-1.,-1.,-1.), vec3(1.,-1.,-1.), vec3(1.,-1.,1.), vec3(-1.,-1.,-1.), vec3(1.,-1.,1.), vec3(-1.,-1.,1.),
  // +z
  vec3(-1.,-1.,1.), vec3(1.,-1.,1.), vec3(1.,1.,1.), vec3(-1.,-1.,1.), vec3(1.,1.,1.), vec3(-1.,1.,1.),
  // -z
  vec3(-1.,-1.,-1.), vec3(1.,1.,-1.), vec3(1.,-1.,-1.), vec3(-1.,-1.,-1.), vec3(-1.,1.,-1.), vec3(1.,1.,-1.));
const FACE_AXIS = array<u32, 12>(0u,0u, 0u,0u, 1u,1u, 1u,1u, 2u,2u, 2u,2u);

@vertex
fn vs(@location(0) center : vec3<f32>,
      @location(1) color  : vec4<f32>,
      @builtin(vertex_index) vi : u32) -> VsOut {
  var out : VsOut;
  let corner = CUBE[vi] * U.half;
  out.pos = U.mvp * vec4<f32>(center + corner, 1.0);
  // Per-face shading
  let fa = FACE_AXIS[vi / 3u];
  var sh = U.shade.x;
  if (fa == 1u) { sh = U.shade.y; }
  if (fa == 2u) { sh = U.shade.z; }
  out.color = vec4<f32>(color.rgb * sh, color.a);
  // Slice emphasis: opaque if the voxel centre lies on any plane.
  var emph = false;
  let np = i32(U.nPlanes);
  for (var i = 0; i < np; i = i + 1) {
    let ax = U.planeAxis[i];
    var cv = center.x;
    if (ax > 1.5) { cv = center.z; } else if (ax > 0.5) { cv = center.y; }
    if (abs(cv - U.planePos[i]) <= U.half * 1.1) { emph = true; }
  }
  out.alpha = select(U.baseAlpha, U.sliceAlpha, emph);
  return out;
}

@fragment
fn fs(in : VsOut) -> @location(0) vec4<f32> {
  return vec4<f32>(in.color.rgb, in.alpha);
}
`;

  // ── 2-D large-image WebGPU path ────────────────────────────────────────────
  // A fullscreen textured quad samples the normalized uint8 image (an R8 texture,
  // the same bytes the Canvas2D path decodes) and maps each pixel through the
  // 256-entry colormap LUT (a 256×1 RGBA texture). This replaces the 64-million-
  // iteration JS atob+LUT loop with one GPU draw.
  //
  // CRITICAL: the LUT is built by _buildLut32, which ALREADY bakes the display
  // window (clim) AND the scale_mode (linear/log/symlog) into a direct
  // "pixel value → final colour" map: lut[raw] = final colour. The Canvas2D path
  // uses it as a plain lookup (out32[i] = lut[bytes[i]]). So the shader must be an
  // IDENTITY lookup — index the LUT by raw/255 and NOTHING else. (A previous
  // version re-applied dmin/dmax in the shader on top of the already-windowed LUT,
  // double-applying the contrast — correct only at full-range clim, wrong for any
  // narrowed window or log/symlog. Do NOT reintroduce a clim uniform here.)
  //
  // The quad is fullscreen with NO zoom/pan: the GPU path is used only when the
  // view is unzoomed/uncentred (see _gpuWanted2d); a zoomed/panned view falls
  // back to Canvas2D so the base image stays registered with the axes/overlays.
  const _GPU_IMAGE_WGSL = `
// rect   = the on-screen quad in CLIP space (x0,y0,x1,y1). For zoom<=1 this is the
//          fit-rect shrunk by zoom (centred); for zoom>=1 it's the full fit-rect.
// uvrect = the texture sub-region to sample (u0,v0,u1,v1), in 0..1. For zoom>=1
//          this is the zoomed-in window of the image (a small region stretched over
//          the fit-rect, nearest sampling UPSAMPLES real texels); for zoom<=1 it's
//          the whole texture (0,0,1,1). Together they reproduce _blit2d's zoom/pan
//          exactly, so the GPU image stays registered with the axes/overlays at any
//          zoom. Outside the rect the clear colour shows as the letterbox bars.
struct U { rect : vec4<f32>, uvrect : vec4<f32>, };
@group(0) @binding(0) var<uniform> u : U;
@group(0) @binding(1) var img  : texture_2d<f32>;
@group(0) @binding(2) var lut  : texture_2d<f32>;
@group(0) @binding(3) var samp : sampler;

struct VsOut {
  @builtin(position) pos : vec4<f32>,
  @location(0) uv        : vec2<f32>,
};

// Unit quad in 0..1; mapped into the clip-space rect + the uv sub-region below.
const Q = array<vec2<f32>, 6>(
  vec2(0.0,0.0), vec2(1.0,0.0), vec2(0.0,1.0),
  vec2(0.0,1.0), vec2(1.0,0.0), vec2(1.0,1.0));

@vertex
fn vs(@builtin(vertex_index) vi : u32) -> VsOut {
  var out : VsOut;
  let q = Q[vi];                              // 0..1 across the drawn quad
  let x = mix(u.rect.x, u.rect.z, q.x);       // lerp into clip-space rect
  let y = mix(u.rect.y, u.rect.w, q.y);
  out.pos = vec4<f32>(x, y, 0.0, 1.0);
  let uu = mix(u.uvrect.x, u.uvrect.z, q.x);
  // q.y=0 is the SCREEN BOTTOM (rect.y is the lower clip edge), which shows
  // the LAST row of the visible window (v1); q.y=1 (screen top) shows the
  // first (v0) — so v interpolates from v1 down to v0 WITHIN the window
  // (imshow: texture row 0 = image top). Do NOT flip with a global (1 - v)
  // after interpolating [v0,v1]: that samples the MIRRORED window
  // [1-v1, 1-v0] — identical only when v0+v1 == 1 (full view / vertically
  // centred), so it survived centred-zoom tests but inverted the pan-y
  // direction and detached the image from markers/overlays on any
  // vertically off-centre view (base AND detail passes).
  let vv = mix(u.uvrect.w, u.uvrect.y, q.y);
  out.uv  = vec2<f32>(uu, vv);
  return out;
}

@fragment
fn fs(in : VsOut) -> @location(0) vec4<f32> {
  // R8 unorm (0..1) = the frame value already normalized to the 0..255 index the
  // LUT is keyed on. Direct identity lookup — the LUT holds the final colour
  // (clim + scale_mode baked in). Nearest sampling on img (no interpolation of
  // raw values); the LUT is sampled at the texel centre.
  let raw = textureSampleLevel(img, samp, in.uv, 0.0).r;   // 0..1 == index/255
  return textureSampleLevel(lut, samp, vec2<f32>(raw, 0.5), 0.0);
}
`;

  function _gpuInitImagePanel(p, device) {
    const fmt = navigator.gpu.getPreferredCanvasFormat();
    const ctx = p.gpuCanvas.getContext('webgpu');
    ctx.configure({ device, format: fmt, alphaMode: 'opaque' });
    const module = device.createShaderModule({ code: _GPU_IMAGE_WGSL });
    const pipeline = device.createRenderPipeline({
      layout: 'auto',
      vertex:   { module, entryPoint: 'vs' },
      fragment: { module, entryPoint: 'fs', targets: [{ format: fmt }] },
      primitive:{ topology: 'triangle-list' },
    });
    // NEAREST on both textures matches the Canvas2D path's imageSmoothingEnabled=
    // false (no interpolation of raw values or between LUT colour entries), so the
    // GPU output is a pixel-faithful match of the reference.
    const samp = device.createSampler({
      magFilter: 'nearest', minFilter: 'nearest', mipmapFilter: 'nearest' });
    // Uniform holds the clip-space quad rect + the texture uv sub-region (two
    // vec4 = 32 B) so the quad matches the fit-rect AND zoom/pan of the Canvas2D
    // path + overlays.
    const uniformBuf = device.createBuffer({
      size: 32, usage: GPUBufferUsage.UNIFORM | GPUBufferUsage.COPY_DST });
    // Second uniform for the DETAIL overlay pass (its own screen rect + uv), so the
    // crisp tile can be stitched OVER the upsampled overview base in one frame
    // (base fills the margin, tile fills the padded FOV — no zoom-out flash).
    const uniformBuf2 = device.createBuffer({
      size: 32, usage: GPUBufferUsage.UNIFORM | GPUBufferUsage.COPY_DST });
    p._gpuImg = { device, ctx, fmt, pipeline, samp, uniformBuf, uniformBuf2,
                  tex: null, texW: 0, texH: 0, lutTex: null, lutKey: null,
                  bytesKey: null, bindGroup: null,
                  // Detail texture slot (kept resident alongside the base).
                  dtex: null, dtexW: 0, dtexH: 0, dbytesKey: null, dbindGroup: null };
  }

  // Raw single-channel pixel bytes for the current image state. Prefers the
  // BINARY bytes `image_b64_bytes` (a Uint8Array spliced into the state from the
  // geomCache by the binary transport — no atob) over `image_b64` (base64, needs
  // decoding). Returns {bytes, key} where `key` is a cheap identity for the
  // "unchanged → skip re-upload" check.
  function _imageBytes(st) {
    const raw = st.image_b64_bytes;
    if (raw && (raw instanceof Uint8Array || raw.byteLength !== undefined)) {
      const u8 = raw instanceof Uint8Array ? raw : new Uint8Array(raw);
      // Cache identity, in preference order:
      //  1. the content token in st.image_b64 ("\x00bin:<adler>", kept in the
      //     slimmed geom by _route_change),
      //  2. the buffer's ARRIVAL sequence (stamped when the binary frame was
      //     spliced in — every received frame is new content),
      //  3. a sampled fingerprint as a last resort. NB sampling is WEAK: it
      //     reads only 4 bytes, so frames differing anywhere else collide and
      //     the "unchanged → skip re-upload" check freezes the display — this
      //     branch must stay a fallback, never the primary key.
      let key = st.image_b64;
      if (!key && u8.__aplSeq !== undefined) key = `binseq:${u8.__aplSeq}`;
      if (!key) {
        const n = u8.length;
        const s0 = u8[0] || 0, s1 = u8[(n >> 2) | 0] || 0;
        const s2 = u8[(n >> 1) | 0] || 0, s3 = u8[n - 1] || 0;
        key = `bin:${n}:${s0},${s1},${s2},${s3}`;
      }
      return { bytes: u8, key };
    }
    const b64 = st.image_b64 || '';
    if (!b64) return { bytes: null, key: '' };
    try {
      const bin = atob(b64);
      const u8 = new Uint8Array(bin.length);
      for (let i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i);
      return { bytes: u8, key: b64 };
    } catch (_) { return { bytes: null, key: '' }; }
  }

  // Detail-tile bytes (binary `detail_b64_bytes` or base64 `detail_b64`), keyed so a
  // new tile re-uploads. Prefix the key with 'detail:' so it never collides with a
  // base-image key of the same length (they share the one GPU texture slot).
  function _detailBytes(st) {
    const raw = st.detail_b64_bytes;
    if (raw && (raw instanceof Uint8Array || raw.byteLength !== undefined)) {
      const u8 = raw instanceof Uint8Array ? raw : new Uint8Array(raw);
      const reg = st.detail_region || [];
      // Key on detail_seq (a monotonic counter bumped by Python's set_detail on EVERY
      // push), NOT just length+region. A live movie scrub while zoomed in re-samples
      // the SAME region every frame → identical length + region, so a length/region
      // key would match every frame and the GPU/Canvas dedup would SKIP the re-upload
      // — the display freezes on the first frame ("won't update when zoomed in").
      // detail_seq guarantees a distinct key per pushed tile.
      const seq = st.detail_seq || 0;
      return { bytes: u8, key: `detail:${seq}:${u8.length}:${reg.join(',')}` };
    }
    const b64 = st.detail_b64 || '';
    if (!b64) return { bytes: null, key: '' };
    try {
      const bin = atob(b64);
      const u8 = new Uint8Array(bin.length);
      for (let i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i);
      return { bytes: u8, key: `detail:${b64}` };
    } catch (_) { return { bytes: null, key: '' }; }
  }

  // Write single-channel R8 bytes into a device texture, (re)creating it if the size
  // changed. Returns the (possibly new) texture, or null if bytes are missing/short.
  function _gpuWriteR8(device, tex, texWH, iw, ih, bytes) {
    if (!bytes) return null;
    if (bytes.length < iw * ih) return null;
    if (!tex || texWH.w !== iw || texWH.h !== ih) {
      if (tex) tex.destroy();
      tex = device.createTexture({
        size: [iw, ih, 1], format: 'r8unorm',
        usage: GPUTextureUsage.TEXTURE_BINDING | GPUTextureUsage.COPY_DST |
               GPUTextureUsage.RENDER_ATTACHMENT });
      texWH.w = iw; texWH.h = ih;
    }
    // bytesPerRow must be a multiple of 256 for writeTexture; R8 = 1 B/px, so pad
    // each row up to the next 256 boundary.
    const bpr = Math.ceil(iw / 256) * 256;
    let src = bytes;
    if (bpr !== iw) {
      src = new Uint8Array(bpr * ih);
      for (let r = 0; r < ih; r++) src.set(bytes.subarray(r * iw, r * iw + iw), r * bpr);
    }
    device.queue.writeTexture(
      { texture: tex }, src, { bytesPerRow: bpr, rowsPerImage: ih }, [iw, ih, 1]);
    return tex;
  }

  // Ensure the shared LUT texture is current for st. Returns false only if it can't
  // be built. Sets g.lutTex; invalidates both bind groups when the LUT changes.
  function _gpuEnsureLut(g, st) {
    const device = g.device;
    const lutKey = _lutKey(st);
    if (lutKey === g.lutKey && g.lutTex) return true;
    const lut = _buildLut32(st);             // Uint32Array(256), 0xAABBGGRR
    const rgba = new Uint8Array(256 * 4);
    for (let i = 0; i < 256; i++) {
      const v = lut[i];
      rgba[i*4]   = v & 0xff;
      rgba[i*4+1] = (v >> 8) & 0xff;
      rgba[i*4+2] = (v >> 16) & 0xff;
      rgba[i*4+3] = 255;
    }
    if (!g.lutTex) {
      g.lutTex = device.createTexture({
        size: [256, 1, 1], format: 'rgba8unorm',
        usage: GPUTextureUsage.TEXTURE_BINDING | GPUTextureUsage.COPY_DST });
    }
    device.queue.writeTexture(
      { texture: g.lutTex }, rgba, { bytesPerRow: 256 * 4, rowsPerImage: 1 },
      [256, 1, 1]);
    g.lutKey = lutKey;
    g.bindGroup = null; g.dbindGroup = null;   // LUT changed → both groups rebuild
    return true;
  }

  // Upload the BASE (overview/full) image bytes + the LUT. Returns false if the base
  // bytes couldn't be decoded (caller falls back to Canvas2D). The detail tile is
  // uploaded separately (_gpuUploadDetail) into its own slot for the overlay pass —
  // base and detail are STITCHED in one frame, not swapped, so a zoom-out shows the
  // crisp padded tile over an upsampled-overview margin (no flash).
  function _gpuUploadImage(p, st) {
    const g = p._gpuImg, device = g.device;
    // The BASE texture is an OVERVIEW in tile mode: its real texel dims are
    // base_width/height (0 → full image_width/height). The shader samples UV as a
    // fraction 0..1 of the texture, so a smaller overview still maps over the full
    // logical extent — lower-res until the detail tile covers the view.
    const iw = st.base_width || st.image_width;
    const ih = st.base_height || st.image_height;
    const img = _imageBytes(st);
    if (img.key !== g.bytesKey || !g.tex || g.texW !== iw || g.texH !== ih) {
      const texWH = { w: g.texW, h: g.texH };
      const tex = _gpuWriteR8(device, g.tex, texWH, iw, ih, img.bytes);
      if (!tex) return false;
      g.tex = tex; g.texW = texWH.w; g.texH = texWH.h;
      g.bytesKey = img.key;
      g.bindGroup = null;   // texture changed → rebuild bind group
    }
    if (!_gpuEnsureLut(g, st)) return false;
    if (!g.bindGroup) {
      g.bindGroup = device.createBindGroup({
        layout: g.pipeline.getBindGroupLayout(0),
        entries: [
          { binding: 0, resource: { buffer: g.uniformBuf } },
          { binding: 1, resource: g.tex.createView() },
          { binding: 2, resource: g.lutTex.createView() },
          { binding: 3, resource: g.samp },
        ],
      });
    }
    return true;
  }

  // Upload the DETAIL tile into its own slot (g.dtex) + build g.dbindGroup bound to
  // uniformBuf2. Returns true if a detail tile is resident & ready to draw, false if
  // there's none (or its bytes couldn't be decoded → skip the overlay pass). Assumes
  // _gpuUploadImage already ran this frame (LUT is current).
  function _gpuUploadDetail(p, st) {
    const g = p._gpuImg, device = g.device;
    const reg = st.detail_region;
    if (!_hasDetail(st) || !reg || reg.length !== 4
        || !st.detail_width || !st.detail_height) return false;
    const iw = st.detail_width, ih = st.detail_height;
    const img = _detailBytes(st);
    if (img.key !== g.dbytesKey || !g.dtex || g.dtexW !== iw || g.dtexH !== ih) {
      const texWH = { w: g.dtexW, h: g.dtexH };
      const tex = _gpuWriteR8(device, g.dtex, texWH, iw, ih, img.bytes);
      if (!tex) return false;
      g.dtex = tex; g.dtexW = texWH.w; g.dtexH = texWH.h;
      g.dbytesKey = img.key;
      g.dbindGroup = null;
    }
    if (!g.dtex) return false;
    if (!g.dbindGroup) {
      g.dbindGroup = device.createBindGroup({
        layout: g.pipeline.getBindGroupLayout(0),
        entries: [
          { binding: 0, resource: { buffer: g.uniformBuf2 } },
          { binding: 1, resource: g.dtex.createView() },
          { binding: 2, resource: g.lutTex.createView() },
          { binding: 3, resource: g.samp },
        ],
      });
    }
    return true;
  }

  // Compute the GPU uniform: the on-screen quad in CLIP space + the texture uv
  // sub-region to sample, honouring zoom/center EXACTLY like the Canvas2D _blit2d
  // (so the GPU image stays registered with the axes/overlays at any zoom, and a
  // zoom-in UPSAMPLES real texels via nearest sampling). Returns 8 floats:
  // [rx0,ry0,rx1,ry1, u0,v0,u1,v1]. imgW/imgH = the gpuCanvas area in CSS px.
  // The visible image-pixel window [srcX, srcX+visW]×[srcY, srcY+visH] for the
  // current zoom/center, in BASE image pixels (zoom>=1). Mirrors _imageDrawUniform.
  function _visibleWindow(st) {
    const iw = st.image_width, ih = st.image_height;
    const zoom = st.zoom || 1.0;
    if (zoom < 1.0) return { srcX: 0, srcY: 0, visW: iw, visH: ih };
    const cx = (st.center_x == null ? 0.5 : st.center_x);
    const cy = (st.center_y == null ? 0.5 : st.center_y);
    const visW = iw / zoom, visH = ih / zoom;
    const srcX = Math.max(0, Math.min(iw - visW, cx * iw - visW / 2));
    const srcY = Math.max(0, Math.min(ih - visH, cy * ih - visH / 2));
    return { srcX, srcY, visW, visH };
  }

  // Is the detail tile active AND does it fully cover the current visible window?
  // If so, return the tile-relative UV of that window (so the shader samples the
  // hi-res tile); otherwise null (sample the base texture). Requires the whole
  // visible window inside detail_region so a zoom-in shows only crisp tile texels.
  // True when a detail tile is present, regardless of transport: base64 path leaves
  // the string in st.detail_b64; the BINARY path strips detail_b64 out of the geom
  // and ships bytes on the companion trait (spliced into st.detail_b64_bytes). Gating
  // on detail_b64 alone made the binary path NEVER show the detail tile — only the
  // blurry overview — because the string is absent under binary transport.
  function _hasDetail(st) {
    if (st.detail_b64) return true;
    const b = st.detail_b64_bytes;
    return !!(b && (b instanceof Uint8Array || b.byteLength !== undefined) && b.length);
  }

  function _detailUV(st) {
    const reg = st.detail_region;
    if (!_hasDetail(st) || !reg || reg.length !== 4) return null;
    const [tx0, tx1, ty0, ty1] = reg;
    const tw = tx1 - tx0, th = ty1 - ty0;
    if (!(tw > 0) || !(th > 0)) return null;
    const w = _visibleWindow(st);
    if (w.srcX < tx0 - 0.5 || w.srcX + w.visW > tx1 + 0.5 ||
        w.srcY < ty0 - 0.5 || w.srcY + w.visH > ty1 + 0.5) return null;
    return {
      u0: (w.srcX - tx0) / tw, u1: (w.srcX + w.visW - tx0) / tw,
      v0: (w.srcY - ty0) / th, v1: (w.srcY + w.visH - ty0) / th,
    };
  }

  // The screen rect (within the fit-rect fx,fy,fw,fh) where the detail tile's
  // logical region maps at the current zoom/center — for compositing the still-
  // valid crisp tile OVER the base when it no longer FULLY covers the view (a
  // zoom-out/pan that outgrew the region). Returns null when: no tile; the tile
  // already fully covers (the _detailUV branch draws it full-screen instead); or
  // the region is entirely off-screen (nothing to overlay). This is what removes
  // the zoom-out flash — the centre stays crisp until the wider tile lands.
  function _detailOverlayRect(st, fx, fy, fw, fh) {
    const reg = st.detail_region;
    if (!_hasDetail(st) || !reg || reg.length !== 4) return null;
    if (_detailUV(st)) return null;                 // fully covered → drawn elsewhere
    const zoom = st.zoom || 1.0;
    // At/below zoom 1 the whole image is visible and the overview base is
    // authoritative — don't float a stale crisp patch over it. The overlay is a
    // zoom-IN / transition aid (it prevents the zoom-OUT flash WHILE still
    // magnified); the live loop clears the tile below VIEW_ZOOM_MIN anyway, so this
    // only additionally guards a manually-set tile at zoom<=1.
    if (zoom <= 1.0) return null;
    const [tx0, tx1, ty0, ty1] = reg;
    if (!(tx1 > tx0) || !(ty1 > ty0)) return null;
    const iw = st.image_width, ih = st.image_height;
    // Logical→screen mapping identical to the zoom>=1 base blit (windowed), so the
    // overlaid tile registers exactly over the base.
    const cx = (st.center_x == null ? 0.5 : st.center_x);
    const cy = (st.center_y == null ? 0.5 : st.center_y);
    const visW = iw / zoom, visH = ih / zoom;
    const srcX = Math.max(0, Math.min(iw - visW, cx * iw - visW / 2));
    const srcY = Math.max(0, Math.min(ih - visH, cy * ih - visH / 2));
    const mapX = (lx) => fx + ((lx - srcX) / visW) * fw;
    const mapY = (ly) => fy + ((ly - srcY) / visH) * fh;
    const dx = mapX(tx0), dx1 = mapX(tx1);
    const dy = mapY(ty0), dy1 = mapY(ty1);
    const dw = dx1 - dx, dh = dy1 - dy;
    if (!(dw > 0.5) || !(dh > 0.5)) return null;
    // Fully outside the fit-rect → nothing to show.
    if (dx1 <= fx || dx >= fx + fw || dy1 <= fy || dy >= fy + fh) return null;
    return { dx, dy, dw, dh };
  }

  // Pack a screen dest rect (px, y-down) + uv sub-region (0..1) into the 8-float
  // clip-space uniform the shader expects. Shared by the base + detail passes.
  function _drawUniform(dx, dy, dw, dh, u0, v0, u1, v1, imgW, imgH) {
    const rx0 = (dx / imgW) * 2 - 1;
    const rx1 = ((dx + dw) / imgW) * 2 - 1;
    const ry0 = 1 - ((dy + dh) / imgH) * 2;   // bottom edge (lower clip y)
    const ry1 = 1 - (dy / imgH) * 2;          // top edge (upper clip y)
    return new Float32Array([rx0, ry0, rx1, ry1, u0, v0, u1, v1]);
  }

  // Uniform for the BASE pass: the overview/full frame over the fit-rect honouring
  // zoom/pan (NOT the detail — that's a separate overlay pass now, so the base
  // always fills the whole view and the crisp tile stitches on top).
  function _imageDrawUniform(st, imgW, imgH) {
    const fr = _imgFitRect(st.image_width, st.image_height, imgW, imgH);
    const iw = st.image_width, ih = st.image_height;
    const zoom = st.zoom || 1.0;
    const cx = (st.center_x == null ? 0.5 : st.center_x);
    const cy = (st.center_y == null ? 0.5 : st.center_y);
    let dx = fr.x, dy = fr.y, dw = fr.w, dh = fr.h;   // dest rect in px
    let u0 = 0, v0 = 0, u1 = 1, v1 = 1;               // full texture
    if (zoom >= 1.0) {
      // Zoomed in: sample a window of the image over the full fit-rect.
      const visW = iw / zoom, visH = ih / zoom;
      const srcX = Math.max(0, Math.min(iw - visW, cx * iw - visW / 2));
      const srcY = Math.max(0, Math.min(ih - visH, cy * ih - visH / 2));
      u0 = srcX / iw; u1 = (srcX + visW) / iw;
      v0 = srcY / ih; v1 = (srcY + visH) / ih;
    } else {
      // Zoomed out: shrink the dest rect proportionally, keep centred.
      dw = fr.w * zoom; dh = fr.h * zoom;
      dx = fr.x + (fr.w - dw) / 2; dy = fr.y + (fr.h - dh) / 2;
    }
    return _drawUniform(dx, dy, dw, dh, u0, v0, u1, v1, imgW, imgH);
  }

  // Uniform for the DETAIL overlay pass. Two cases:
  //  • fully covers (_detailUV): draw the tile over the WHOLE fit-rect, sampling the
  //    tile-relative UV of the visible window (crisp zoom-in) — hides the base.
  //  • partial (_detailOverlayRect): draw the tile at its own screen rect over the
  //    base (crisp centre + overview margin on a zoom-out, no flash).
  // Returns null when there's no detail tile to overlay.
  function _detailDrawUniform(st, imgW, imgH) {
    const fr = _imgFitRect(st.image_width, st.image_height, imgW, imgH);
    const vr = _imgVisibleRect2d(st, imgW, imgH);
    const det = _detailUV(st);
    if (det) {
      return _drawUniform(vr.x, vr.y, vr.w, vr.h,
                          det.u0, det.v0, det.u1, det.v1, imgW, imgH);
    }
    const ov = _detailOverlayRect(st, fr.x, fr.y, fr.w, fr.h);
    if (ov) {
      const cl = _clipRectUv(ov.dx, ov.dy, ov.dw, ov.dh,
        0, 0, 1, 1, vr.x, vr.y, vr.w, vr.h);
      if (!cl) return null;
      return _drawUniform(cl.dx, cl.dy, cl.dw, cl.dh,
        cl.u0, cl.v0, cl.u1, cl.v1, imgW, imgH);
    }
    return null;
  }

  // Draw the image on the GPU canvas. Returns false on any failure so the caller
  // reverts to Canvas2D for this frame. No clim uniform: the LUT already bakes in
  // the display window + scale_mode (see _GPU_IMAGE_WGSL) — the shader is a plain
  // identity lookup.
  function _gpuDraw2dImage(p, st, imgW, imgH) {
    const g = p._gpuImg;
    try {
      if (!_gpuUploadImage(p, st)) { _tiledbg('gpu', 'base upload FAILED → canvas fallback'); return false; }
      const device = g.device;
      // BASE pass: the overview/full frame over the fit-rect, honouring zoom/pan, so
      // it lines up with the Canvas2D blit + overlays. Always drawn — the crisp tile
      // stitches on top, and the base shows through any margin the tile doesn't cover.
      device.queue.writeBuffer(g.uniformBuf, 0, _imageDrawUniform(st, imgW, imgH));
      // DETAIL pass (optional): the hi-res tile over its screen rect (full fit-rect
      // when it covers the view; its own padded-FOV rect on a zoom-out). Prepared
      // BEFORE the encoder so a decode failure just skips the overlay (base still
      // draws) rather than aborting the whole frame to the Canvas2D fallback.
      let drawDetail = false;
      const du = _detailDrawUniform(st, imgW, imgH);
      const _detUpload = du ? _gpuUploadDetail(p, st) : false;
      if (du && _detUpload) {
        device.queue.writeBuffer(g.uniformBuf2, 0, du);
        drawDetail = true;
      }
      if (globalThis.__apl_tiledbg) {
        const reg = st.detail_region || [];
        const uv = _detailUV(st);
        _tiledbg('gpu', `DRAW zoom=${(st.zoom||1).toFixed(2)} ` +
          `center=(${(st.center_x||0.5).toFixed(3)},${(st.center_y||0.5).toFixed(3)}) ` +
          `base[${st.base_width}x${st.base_height}] image[${st.image_width}x${st.image_height}] ` +
          `detail_region=[${reg.join(',')}] detailUV=${uv?'COVERS(full)':'partial/none'} ` +
          `drawDetail=${drawDetail} detUpload=${_detUpload} ` +
          `display=(${st.display_min},${st.display_max})`);
      }
      // Clear to the canvas background so the letterbox bars match the Canvas2D
      // path (which leaves the plotCanvas bg showing outside the fit-rect).
      const bg = _clearRgba(theme.bgCanvas);
      const enc = device.createCommandEncoder();
      const view = g.ctx.getCurrentTexture().createView();
      const pass = enc.beginRenderPass({
        colorAttachments: [{ view, loadOp: 'clear', storeOp: 'store',
          clearValue: bg }] });
      pass.setPipeline(g.pipeline);
      pass.setBindGroup(0, g.bindGroup);
      pass.draw(6);
      if (drawDetail) {
        // Second pass on the SAME target, loadOp:'load' to keep the base underneath.
        pass.end();
        const pass2 = enc.beginRenderPass({
          colorAttachments: [{ view, loadOp: 'load', storeOp: 'store' }] });
        pass2.setPipeline(g.pipeline);
        pass2.setBindGroup(0, g.dbindGroup);
        pass2.draw(6);
        pass2.end();
      } else {
        pass.end();
      }
      device.queue.submit([enc.finish()]);
      return true;
    } catch (e) {
      console.warn('[anyplotlib] GPU image draw failed — canvas fallback:', e);
      return false;
    }
  }

  // '#rrggbb' → {r,g,b,a} floats 0..1 for a WebGPU clearValue.
  function _clearRgba(hex) {
    const h = (hex || '#000000').replace('#', '');
    const n = parseInt(h.length === 3
      ? h.split('').map(c => c + c).join('') : h, 16);
    return { r: ((n >> 16) & 255) / 255, g: ((n >> 8) & 255) / 255,
             b: (n & 255) / 255, a: 1 };
  }

  // Test hook: render an active 2-D image panel into an OFFSCREEN RGBA texture
  // (not the live swapchain, which reads black under automation) and copy it back
  // to CPU. Returns {w,h,px:[[r,g,b],...]} on an NxN sample grid so a test can
  // verify the shader-LUT actually produced the expected colormapped output.
  async function _gpuReadbackImage(panelId, N) {
    N = N || 24;
    const p = panels.get(panelId);
    if (!p || p._gpu !== 'active' || !p._gpuImg) return null;
    const g = p._gpuImg, device = g.device, st = p.state;
    if (!_gpuUploadImage(p, st)) return null;
    // Fill the whole NxN readback target (rect = full clip space) sampling the
    // FULL texture (uv 0..1) so the readback reads the entire image regardless of
    // aspect or the live zoom — the shader is a plain LUT identity lookup (clim
    // baked into LUT), so this reads the true colormapped output.
    device.queue.writeBuffer(g.uniformBuf, 0,
      new Float32Array([-1, -1, 1, 1, 0, 0, 1, 1]));
    // Offscreen target at NxN (a coarse but faithful downscale via the sampler).
    const tex = device.createTexture({
      size: [N, N, 1], format: g.fmt,
      usage: GPUTextureUsage.RENDER_ATTACHMENT | GPUTextureUsage.COPY_SRC });
    const enc = device.createCommandEncoder();
    const pass = enc.beginRenderPass({
      colorAttachments: [{ view: tex.createView(), loadOp: 'clear',
        storeOp: 'store', clearValue: { r: 0, g: 0, b: 0, a: 1 } }] });
    pass.setPipeline(g.pipeline); pass.setBindGroup(0, g.bindGroup); pass.draw(6); pass.end();
    const bpr = Math.ceil(N * 4 / 256) * 256;
    const buf = device.createBuffer({
      size: bpr * N, usage: GPUBufferUsage.COPY_DST | GPUBufferUsage.MAP_READ });
    enc.copyTextureToBuffer({ texture: tex }, { buffer: buf, bytesPerRow: bpr }, [N, N, 1]);
    device.queue.submit([enc.finish()]);
    await buf.mapAsync(GPUMapMode.READ);
    const data = new Uint8Array(buf.getMappedRange()).slice();
    buf.unmap(); buf.destroy(); tex.destroy();
    const isBgra = g.fmt.startsWith('bgra');
    const px = [];
    for (let r = 0; r < N; r++) for (let c = 0; c < N; c++) {
      const o = r * bpr + c * 4;
      px.push(isBgra ? [data[o+2], data[o+1], data[o]]
                     : [data[o], data[o+1], data[o+2]]);
    }
    return { w: N, h: N, px };
  }
  try { globalThis.__apl_gpuReadback = _gpuReadbackImage; } catch (_) {}

  // Test hook: set zoom/center on a 2-D image panel and redraw, so an automated
  // test can verify the GPU path stays active + upsamples when zoomed (mirrors the
  // wheel handler, without a synthetic wheel event).
  try {
    globalThis.__apl_setZoom = function (panelId, zoom, cx, cy) {
      const p = panels.get(panelId);
      if (!p || !p.state) return false;
      p.state.zoom = zoom;
      if (cx != null) p.state.center_x = cx;
      if (cy != null) p.state.center_y = cy;
      const _t0 = performance.now();
      try { draw2d(p); } catch (_) {}
      const _tDraw = performance.now() - _t0;
      // Compare the wheel handler's post-draw serialise: the OLD cost
      // (JSON.stringify of the whole geom-polluted state) vs the NEW cost
      // (_viewStateJson, geom stripped). On the binary path the old cost is a
      // Uint8Array → {"0":..} stringify (millions of keys); the new one is tiny.
      const _t1 = performance.now();
      let _slen = 0;
      try { _slen = JSON.stringify(p.state).length; } catch (_) { _slen = -1; }
      const _tStringify = performance.now() - _t1;
      const _t2 = performance.now();
      let _vlen = 0;
      try { _vlen = _viewStateJson(p).length; } catch (_) { _vlen = -1; }
      const _tView = performance.now() - _t2;
      globalThis.__apl_zoom_dbg = { draw: _tDraw,
        stringify: _tStringify, len: _slen,           // OLD (full state)
        viewStringify: _tView, viewLen: _vlen,        // NEW (geom stripped)
        hasBytes: !!(p.state && p.state.image_b64_bytes),
        b64len: (p.state && p.state.image_b64 && p.state.image_b64.length) || 0 };
      return _tDraw;   // draw2d ms (a zoom-only redraw)
    };
    // Test hook: return the EXACT string the interaction handlers now write to
    // the light `panel_<id>_json` trait (geometry stripped). Lets a test assert
    // the heavy geom keys never leak into the per-tick view write.
    globalThis.__apl_viewStateJson = function (panelId) {
      const p = panels.get(panelId);
      if (!p) return null;
      try { return _viewStateJson(p); } catch (_) { return null; }
    };
    // Test hook: the image-px → canvas-px transform for a 2-D panel at its
    // CURRENT zoom/center (the same _imgToCanvas2d the markers/widgets use),
    // so a test can aim the mouse at a widget/feature under any view.
    globalThis.__apl_imgToCanvas = function (panelId, ix, iy) {
      const p = panels.get(panelId);
      if (!p || !p.state || p.kind !== '2d') return null;
      const imgW = p.imgW || Math.max(1, p.pw - PAD_L - PAD_R);
      const imgH = p.imgH || Math.max(1, p.ph - PAD_T - PAD_B);
      try { return _imgToCanvas2d(ix, iy, p.state, imgW, imgH); }
      catch (_) { return null; }
    };
    // Test hook: pixel-freshness diagnostic for a 2-D panel — which bytes does
    // the state hold vs which bitmap/texture is cached? Distinguishes "stale
    // bytes arrived" from "fresh bytes, stale render cache".
    globalThis.__apl_panelDiag = function (panelId) {
      const p = panels.get(panelId);
      if (!p || !p.state || p.kind !== '2d') return null;
      const st = p.state;
      const img = _imageBytes(st);
      const fp = (u8) => {
        if (!u8) return null;
        const n = u8.length;
        let s = 0;
        for (let i = 0; i < n; i += Math.max(1, n >> 6)) s = (s * 31 + u8[i]) >>> 0;
        return `${n}:${s}`;
      };
      return {
        token: String(st.image_b64 || '').slice(0, 24),
        hasBytes: !!st.image_b64_bytes,
        bytesFp: fp(img.bytes),
        base: [st.base_width, st.base_height],
        logical: [st.image_width, st.image_height],
        detail_region: st.detail_region || [],
        detail_seq: st.detail_seq || 0,
        geomRev: st._geom_rev,
        blitKey: p.blitCache && String(p.blitCache.bytesKey || '').slice(0, 24),
        blitWH: p.blitCache && [p.blitCache.w, p.blitCache.h],
        gpuBytesKey: p._gpuImg && String(p._gpuImg.bytesKey || '').slice(0, 24),
        gpu: p._gpu,
      };
    };
    // Tile debug: __apl_tileDebug(true) then pan/zoom, then __apl_tileDump() to read
    // the ring buffer of detail-tile decisions (detailUV vs FALLBACK->base) + the
    // window/region/uv so we can see exactly where a pan snaps or inverts.
    globalThis.__apl_tileDebug = function (on) { globalThis.__APL_TILE_DEBUG = !!on;
      if (on) globalThis.__apl_tileDbg = []; return globalThis.__APL_TILE_DEBUG; };
    globalThis.__apl_tileDump = function () { return globalThis.__apl_tileDbg || []; };
  } catch (_) {}

  function _gpuInitPanel(p, device, geom) {
    const fmt = navigator.gpu.getPreferredCanvasFormat();
    const ctx = p.gpuCanvas.getContext('webgpu');
    // Opaque canvas: voxel alpha-blending happens inside the render pass over
    // the opaque background clear, so the canvas itself stays opaque.
    ctx.configure({ device, format: fmt, alphaMode: 'opaque' });
    const isVox = geom === 'voxels';
    const module = device.createShaderModule({
      code: isVox ? _GPU_VOXEL_WGSL : _GPU_POINT_WGSL });
    // Voxels with baseAlpha < 1 blend (back-to-front not guaranteed, but the
    // depth buffer + low alpha reads acceptably for a translucent volume;
    // opaque voxels use depth only).
    const blend = {
      color: { srcFactor: 'src-alpha', dstFactor: 'one-minus-src-alpha' },
      alpha: { srcFactor: 'one', dstFactor: 'one-minus-src-alpha' },
    };
    const pipeline = device.createRenderPipeline({
      layout: 'auto',
      vertex: {
        module, entryPoint: 'vs',
        buffers: [
          { arrayStride: 12, stepMode: 'instance',
            attributes: [{ shaderLocation: 0, offset: 0, format: 'float32x3' }] },
          { arrayStride: 4, stepMode: 'instance',
            attributes: [{ shaderLocation: 1, offset: 0, format: 'unorm8x4' }] },
        ],
      },
      fragment: { module, entryPoint: 'fs',
                  targets: [{ format: fmt, blend: isVox ? blend : undefined }] },
      primitive: { topology: 'triangle-list',
                   cullMode: isVox ? 'back' : 'none' },
      depthStencil: { format: 'depth24plus',
                      // Translucent voxels: test depth but don't write it, so
                      // blending isn't order-killed; opaque points write depth.
                      depthWriteEnabled: !isVox, depthCompare: 'less' },
    });
    const uniformBuf = device.createBuffer({
      size: isVox ? 160 : 96,
      usage: GPUBufferUsage.UNIFORM | GPUBufferUsage.COPY_DST });
    const bindGroup = device.createBindGroup({
      layout: pipeline.getBindGroupLayout(0),
      entries: [{ binding: 0, resource: { buffer: uniformBuf } }],
    });
    p._gpuObj = { device, ctx, fmt, pipeline, uniformBuf, bindGroup, geom,
                  posBuf: null, colBuf: null, depthTex: null,
                  count: 0, geomKey: null };
  }

  function _gpuUploadGeometry(p) {
    const g = p._gpuObj, st = p.state, device = g.device;
    // Key on BOTH geometry and colours: the orthoslice explorer recolours
    // voxels via set_point_colors with the vertex set unchanged, so caching
    // on vertices_b64 alone would reuse a stale colour buffer.
    const key = (st.vertices_b64 || '') + '|' + (st.point_colors_b64 || '');
    if (g.geomKey === key && g.posBuf) return;
    g.geomKey = key;
    if (g.posBuf) g.posBuf.destroy();
    if (g.colBuf) g.colBuf.destroy();

    const verts = p._3dVerts || [];   // [[x,y,z],...] decoded by draw3d
    const n = verts.length;
    g.count = n;
    const pos = new Float32Array(n * 3);
    for (let i = 0; i < n; i++) {
      pos[i*3] = verts[i][0]; pos[i*3+1] = verts[i][1]; pos[i*3+2] = verts[i][2];
    }
    g.posBuf = device.createBuffer({
      size: Math.max(16, pos.byteLength),
      usage: GPUBufferUsage.VERTEX | GPUBufferUsage.COPY_DST });
    device.queue.writeBuffer(g.posBuf, 0, pos);

    // Colours: per-point RGBA u8, or replicate the single colour.
    const col = new Uint8Array(n * 4);
    const pc = p._3dPCols;
    if (pc) {
      for (let i = 0; i < n; i++) {
        col[i*4] = pc[i*3]; col[i*4+1] = pc[i*3+1];
        col[i*4+2] = pc[i*3+2]; col[i*4+3] = 255;
      }
    } else {
      const c = st.color || '#4fc3f7';
      const r = parseInt(c.slice(1,3),16), gg = parseInt(c.slice(3,5),16),
            b = parseInt(c.slice(5,7),16);
      for (let i = 0; i < n; i++) {
        col[i*4]=r; col[i*4+1]=gg; col[i*4+2]=b; col[i*4+3]=255;
      }
    }
    g.colBuf = device.createBuffer({
      size: Math.max(16, col.byteLength),
      usage: GPUBufferUsage.VERTEX | GPUBufferUsage.COPY_DST });
    device.queue.writeBuffer(g.colBuf, 0, col);
  }

  // Orthographic clip-space matrix matching the canvas projection EXACTLY.
  // Canvas does:  n = k*v - o  (k=2/maxR; o_i = k*bmin_i + extent_i/maxR),
  //   sx = cx + scale*(r0·n) ;  sy = cy - scale*(r2·n) ;  depth from (r1·n)
  // We want clip = M·[v;1] (WGSL is M × column-vector) producing:
  //   clip.x = NDC.x = 2*sx/pw - 1
  //   clip.y = NDC.y = 1 - 2*sy/ph   (NDC y is up; screen y is down)
  //   clip.z in [0,1], clip.w = 1
  //
  // Substituting n = k*v - o, each clip component is affine in v:
  //   clip.x = (2*scale*k/pw)*(r0·v) + [ -(2*scale/pw)*(r0·o) + (2*cx/pw - 1) ]
  //   clip.y = -(2*scale*k/ph)*(r2·v) + [  (2*scale/ph)*(r2·o) + (1 - 2*cy/ph) ]
  //   clip.z = -0.35*k*(r1·v) + [ 0.35*(r1·o) + 0.5 ]
  //
  // Build the 4 ROWS, then transpose into WGSL's column-major storage.
  function _gpuMatrix(R, scale, cx, cy, pw, ph, bnds, maxR, xr, yr, zr) {
    const r0 = R[0], r1 = R[1], r2 = R[2];
    const k = 2 / maxR;
    const ox = k*bnds.xmin + xr/maxR;
    const oy = k*bnds.ymin + yr/maxR;
    const oz = k*bnds.zmin + zr/maxR;
    const r0o = r0[0]*ox + r0[1]*oy + r0[2]*oz;
    const r1o = r1[0]*ox + r1[1]*oy + r1[2]*oz;
    const r2o = r2[0]*ox + r2[1]*oy + r2[2]*oz;
    const sx = 2*scale*k/pw,  sy = 2*scale*k/ph;
    // Rows of M (M·[vx,vy,vz,1]ᵀ).  For Y: canvas does sy = cy - scale*(r2·n)
    // (screen y down), and NDC.y = 1 - 2*sy/ph flips again — the two
    // negations CANCEL, so rowY's coefficients are +sy*r2, not -sy*r2.
    const rowX = [ sx*r0[0],  sx*r0[1],  sx*r0[2],  -(2*scale/pw)*r0o + (2*cx/pw - 1) ];
    const rowY = [ sy*r2[0],  sy*r2[1],  sy*r2[2],  -(2*scale/ph)*r2o + (1 - 2*cy/ph) ];
    const rowZ = [-0.35*k*r1[0], -0.35*k*r1[1], -0.35*k*r1[2], 0.35*r1o + 0.5 ];
    const rowW = [0, 0, 0, 1];
    // Column-major: column j = [rowX[j], rowY[j], rowZ[j], rowW[j]]
    return new Float32Array([
      rowX[0], rowY[0], rowZ[0], rowW[0],
      rowX[1], rowY[1], rowZ[1], rowW[1],
      rowX[2], rowY[2], rowZ[2], rowW[2],
      rowX[3], rowY[3], rowZ[3], rowW[3],
    ]);
  }

  function _gpuDrawPoints(p, R, scale, cx, cy) {
    const g = p._gpuObj;
    if (!g || !g.count) return;
    const device = g.device, dpr = window.devicePixelRatio || 1;
    const W = Math.max(1, Math.round(p.pw * dpr));
    const H = Math.max(1, Math.round(p.ph * dpr));
    if (p.gpuCanvas.width !== W || p.gpuCanvas.height !== H || !g.depthTex) {
      p.gpuCanvas.width = W; p.gpuCanvas.height = H;
      if (g.depthTex) g.depthTex.destroy();
      g.depthTex = device.createTexture({
        size: [W, H], format: 'depth24plus',
        usage: GPUTextureUsage.RENDER_ATTACHMENT });
    }
    // Uniforms (matrix uses dpr-scaled pixels so points size in CSS px)
    const gm = p._gpuGeom;
    const mvp = _gpuMatrix(R, scale * dpr, cx * dpr, cy * dpr, W, H,
                           gm.bnds, gm.maxR, gm.xr, gm.yr, gm.zr);
    const u = new Float32Array(24);
    u.set(mvp, 0);
    u[16] = W; u[17] = H; u[18] = (p.state.point_size || 4) * dpr;
    device.queue.writeBuffer(g.uniformBuf, 0, u);

    const enc = device.createCommandEncoder();
    const bg = theme.bgPlot;
    const cr = parseInt(bg.slice(1,3),16)/255 || 0.1;
    const cg = parseInt(bg.slice(3,5),16)/255 || 0.1;
    const cb = parseInt(bg.slice(5,7),16)/255 || 0.12;
    const pass = enc.beginRenderPass({
      colorAttachments: [{
        view: g.ctx.getCurrentTexture().createView(),
        clearValue: { r: cr, g: cg, b: cb, a: 1 },
        loadOp: 'clear', storeOp: 'store' }],
      depthStencilAttachment: {
        view: g.depthTex.createView(),
        depthClearValue: 1.0, depthLoadOp: 'clear', depthStoreOp: 'store' },
    });
    pass.setPipeline(g.pipeline);
    pass.setBindGroup(0, g.bindGroup);
    pass.setVertexBuffer(0, g.posBuf);
    pass.setVertexBuffer(1, g.colBuf);
    pass.draw(6, g.count);
    pass.end();
    device.queue.submit([enc.finish()]);
  }

  // Ensure the gpuCanvas + depth texture are sized to the panel (dpr-scaled).
  function _gpuEnsureSize(p) {
    const g = p._gpuObj, device = g.device, dpr = window.devicePixelRatio || 1;
    const W = Math.max(1, Math.round(p.pw * dpr));
    const H = Math.max(1, Math.round(p.ph * dpr));
    if (p.gpuCanvas.width !== W || p.gpuCanvas.height !== H || !g.depthTex) {
      p.gpuCanvas.width = W; p.gpuCanvas.height = H;
      if (g.depthTex) g.depthTex.destroy();
      g.depthTex = device.createTexture({
        size: [W, H], format: 'depth24plus',
        usage: GPUTextureUsage.RENDER_ATTACHMENT });
    }
    return { W, H, dpr };
  }

  function _gpuBeginPass(g, enc) {
    const bg = theme.bgPlot;
    const cr = parseInt(bg.slice(1,3),16)/255 || 0.1;
    const cg = parseInt(bg.slice(3,5),16)/255 || 0.1;
    const cb = parseInt(bg.slice(5,7),16)/255 || 0.12;
    return enc.beginRenderPass({
      colorAttachments: [{
        view: g.ctx.getCurrentTexture().createView(),
        clearValue: { r: cr, g: cg, b: cb, a: 1 },
        loadOp: 'clear', storeOp: 'store' }],
      depthStencilAttachment: {
        view: g.depthTex.createView(),
        depthClearValue: 1.0, depthLoadOp: 'clear', depthStoreOp: 'store' },
    });
  }

  function _gpuDrawVoxels(p, R, scale, cx, cy) {
    const g = p._gpuObj;
    if (!g || !g.count) return;
    const st = p.state, device = g.device;
    const { W, H, dpr } = _gpuEnsureSize(p);
    const gm = p._gpuGeom;
    const mvp = _gpuMatrix(R, scale * dpr, cx * dpr, cy * dpr, W, H,
                           gm.bnds, gm.maxR, gm.xr, gm.yr, gm.zr);
    // Uniform layout (std140-ish): mat4(0..63), half/baseA/sliceA/nPlanes
    // (64..79), planeAxis vec4(80..95), planePos vec4(96..111),
    // shade vec4(112..127).  Buffer is 160 to satisfy 16-byte rounding.
    const u = new Float32Array(40);
    u.set(mvp, 0);
    u[16] = (st.voxel_size || 1) / 2;
    u[17] = st.voxel_alpha != null ? st.voxel_alpha : 0.3;
    u[18] = st.voxel_slice_alpha != null ? st.voxel_slice_alpha : 0.95;
    const AXI = { x: 0, y: 1, z: 2 };
    const planes = (st.overlay_widgets || [])
      .filter(w => w.type === 'plane' && w.visible !== false).slice(0, 4);
    u[19] = planes.length;
    for (let i = 0; i < planes.length; i++) {
      u[20 + i] = AXI[planes[i].axis] ?? 2;   // planeAxis vec4 @ float 20
      u[24 + i] = planes[i].position || 0;     // planePos  vec4 @ float 24
    }
    u[28] = 0.82; u[29] = 0.68; u[30] = 1.0;   // shade x/y/z (match canvas)
    device.queue.writeBuffer(g.uniformBuf, 0, u);

    const enc = device.createCommandEncoder();
    const pass = _gpuBeginPass(g, enc);
    pass.setPipeline(g.pipeline);
    pass.setBindGroup(0, g.bindGroup);
    pass.setVertexBuffer(0, g.posBuf);
    pass.setVertexBuffer(1, g.colBuf);
    pass.draw(36, g.count);
    pass.end();
    device.queue.submit([enc.finish()]);
  }

  function _gpuDisposePanel(p) {
    const g = p._gpuObj;
    if (!g) return;
    try {
      g.posBuf && g.posBuf.destroy();
      g.colBuf && g.colBuf.destroy();
      g.depthTex && g.depthTex.destroy();
      g.uniformBuf && g.uniformBuf.destroy();
    } catch (_) {}
    p._gpuObj = null;
  }

  // Free the 2-D image GPU resources (R8 image texture can be tens of MB). Call on
  // panel removal / figure dispose / device loss so repeatedly opening + closing
  // large-image panels (an in-situ movie viewer) doesn't leak GPU memory.
  function _gpuDisposeImagePanel(p) {
    const g = p._gpuImg;
    if (!g) return;
    try {
      g.tex && g.tex.destroy();
      g.dtex && g.dtex.destroy();
      g.lutTex && g.lutTex.destroy();
      g.uniformBuf && g.uniformBuf.destroy();
      g.uniformBuf2 && g.uniformBuf2.destroy();
    } catch (_) {}
    p._gpuImg = null;
  }

  function draw3d(p, _retry) {
    const st = p.state; if (!st) return;
    if (!_retry) p._gpuFellBack = false;   // per-render re-entry guard reset
    _recordFrame(p);
    const { pw, ph, plotCtx: ctx } = p;

    ctx.clearRect(0, 0, pw, ph);
    ctx.fillStyle = theme.bgPlot;
    ctx.fillRect(0, 0, pw, ph);

    // ── decode + cache b64 geometry (only when state changes) ──────────────
    const vKey = st.vertices_b64 || '';
    const fKey = st.faces_b64    || '';
    const zKey = st.z_values_b64 || '';
    if (p._3dVertsKey !== vKey) {
      p._3dVertsKey = vKey;
      p._voxGen = (p._voxGen || 0) + 1;   // invalidates voxel projection cache
      if (vKey) {
        const vf = _decodeF32(vKey);
        const nv = vf.length / 3;
        const arr = new Array(nv);
        for (let i = 0; i < nv; i++) arr[i] = [vf[i*3], vf[i*3+1], vf[i*3+2]];
        p._3dVerts = arr;
      } else { p._3dVerts = st.vertices || []; }
    }
    if (p._3dFacesKey !== fKey) {
      p._3dFacesKey = fKey;
      if (fKey) {
        const ff = _decodeI32(fKey);
        const nf = ff.length / 3;
        const arr = new Array(nf);
        for (let i = 0; i < nf; i++) arr[i] = [ff[i*3], ff[i*3+1], ff[i*3+2]];
        p._3dFaces = arr;
      } else { p._3dFaces = st.faces || []; }
    }
    if (p._3dZKey !== zKey) {
      p._3dZKey = zKey;
      p._3dZVals = zKey ? _decodeF32(zKey) : (st.z_values || []);
    }
    const verts = p._3dVerts  || [];
    const faces = p._3dFaces  || [];
    const zVals = p._3dZVals  || [];

    const lut      = st.colormap_data || [];
    const geom     = st.geom_type   || 'surface';
    const bnds     = st.data_bounds || {};
    const az       = st.azimuth     || 0;
    const el       = st.elevation   || 30;
    const zoom     = st.zoom        || 1.0;
    const color    = st.color       || '#4fc3f7';
    const ptSize   = st.point_size  || 4;
    const lw       = st.linewidth   || 1.5;

    // Normalise vertices to [-1,1]³
    const xr = (bnds.xmax - bnds.xmin) || 1;
    const yr = (bnds.ymax - bnds.ymin) || 1;
    const zr = (bnds.zmax - bnds.zmin) || 1;
    const maxR = Math.max(xr, yr, zr);
    function norm(v) {
      return [
        2 * (v[0] - bnds.xmin) / maxR - xr / maxR,
        2 * (v[1] - bnds.ymin) / maxR - yr / maxR,
        2 * (v[2] - bnds.zmin) / maxR - zr / maxR,
      ];
    }

    const R = _rot3(az, el);
    const cx = pw / 2, cy = ph / 2;
    const scale = zoom * Math.min(pw, ph) * 0.32;

    // ── WebGPU geometry path (instanced points + voxels) ──────────────────
    // Decide once whether this panel renders geometry on the GPU.  On the
    // first frame that wants it, kick off async device init; until it
    // resolves (or if it fails) the canvas path below runs unchanged.
    // A geom-type change tears down and re-inits the pipeline.
    let gpuActive = false;
    const gpuGeomChanged = p._gpuObj && p._gpuObj.geom !== geom;
    if (gpuGeomChanged) { _gpuDisposePanel(p); p._gpu = undefined; }
    if (p.kind === '3d' && _gpuWanted(st)) {
      if (p._gpu === undefined) {
        p._gpu = 'pending';
        const initGeom = geom;
        _gpuDevice().then((device) => {
          if (!device || !panels.has(p.id)) { p._gpu = 'unavailable'; return; }
          try { _gpuInitPanel(p, device, initGeom); p._gpu = 'active'; }
          catch (e) { console.warn('[anyplotlib] GPU panel init failed:', e);
                      p._gpu = 'unavailable'; }
          _reportGpu(p);
          _redrawPanel(p);
        });
      }
      gpuActive = (p._gpu === 'active' && !!p._gpuObj);
    } else if (p._gpu === 'active') {
      // State no longer wants GPU — revert to canvas.
      p._gpu = undefined; gpuActive = false;
      if (p.gpuCanvas) p.gpuCanvas.style.display = 'none';
      p.plotCanvas.style.background = theme.bgPlot;   // restore opaque bg
      _gpuDisposePanel(p);
    }

    if (gpuActive) {
      // Decode per-instance colours (the canvas block that normally does this
      // is skipped in GPU mode).
      const pcKey = st.point_colors_b64 || '';
      if (p._3dPColKey !== pcKey) {
        p._3dPColKey = pcKey;
        if (pcKey) {
          const bin = atob(pcKey);
          const buf = new Uint8Array(bin.length);
          for (let i = 0; i < bin.length; i++) buf[i] = bin.charCodeAt(i);
          p._3dPCols = buf;
        } else { p._3dPCols = null; }
      }
      // Stash geometry params the GPU matrix needs, upload, draw.
      p._gpuGeom = { bnds, maxR, xr, yr, zr };
      p.gpuCanvas.style.display = 'block';
      p.gpuCanvas.style.width  = pw + 'px';
      p.gpuCanvas.style.height = ph + 'px';
      // plotCanvas becomes a transparent decoration overlay: clear its BITMAP
      // *and* drop its opaque CSS background — otherwise the element keeps
      // painting theme.bgPlot over the gpuCanvas beneath it (z-index 1 vs 0),
      // hiding every GPU-drawn voxel while canvas-drawn planes/highlight still
      // show.  (This is what made large voxel volumes look "empty" with only
      // the plane widgets + highlight visible.)
      p.plotCanvas.style.background = 'transparent';
      ctx.clearRect(0, 0, pw, ph);
      try {
        _gpuUploadGeometry(p);
        if (geom === 'voxels') _gpuDrawVoxels(p, R, scale, cx, cy);
        else                   _gpuDrawPoints(p, R, scale, cx, cy);
      } catch (e) {
        console.warn('[anyplotlib] GPU draw failed — falling back:', e);
        p._gpu = 'unavailable'; gpuActive = false;
        if (p.gpuCanvas) p.gpuCanvas.style.display = 'none';
        p.plotCanvas.style.background = theme.bgPlot;   // restore opaque bg
        _gpuDisposePanel(p);
        // The current frame already cleared plotCanvas and took GPU-only
        // branches (proj == null etc.), so the axes/decorations for THIS frame
        // are half-built.  Rather than limp through, re-render the whole panel
        // once from the top on the canvas path — self-healing without needing
        // a user resize.  (Safari's experimental WebGPU can throw mid-draw or
        // lose the device after working for a while; this recovers cleanly.)
        if (!p._gpuFellBack) {
          p._gpuFellBack = true;
          ctx.fillStyle = theme.bgPlot; ctx.fillRect(0, 0, pw, ph);
          draw3d(p, true);   // re-render once on the canvas path
          return;
        }
        ctx.fillStyle = theme.bgPlot; ctx.fillRect(0, 0, pw, ph);
      }
    }
    p._gpuActiveNow = gpuActive;

    // Pre-project all vertices (voxels use a faster typed-array path inline;
    // skipped entirely when the GPU is drawing the geometry).
    const proj = (geom === 'voxels' || gpuActive) ? null : verts.map(v => {
      const nv = norm(v);
      const rv = _applyRot(R, nv);
      return { s: _project3(rv, cx, cy, scale), d: rv[1] }; // d = depth (into screen)
    });

    // Z-value normalisation for colormap
    const zMin = bnds.zmin, zMax = bnds.zmax, zRange = (zMax - zMin) || 1;

    // ── Reference sphere (set_sphere): shaded silhouette + wireframe ──────
    // Drawn before the geometry so data sits on top; far-side scatter points
    // are dimmed below for a correct depth read.
    const sp = st.sphere;
    const sphereOn = !!(sp && sp.radius > 0);
    if (sphereOn) {
      const cN   = norm([0, 0, 0]);
      const cRot = _applyRot(R, cN);
      const [spx, spy] = _project3(cRot, cx, cy, scale);
      const spr  = (2 * sp.radius / maxR) * scale;
      const col  = sp.color || '#9e9e9e';
      ctx.save();
      // Shaded silhouette disk (light from upper-left)
      const grad = ctx.createRadialGradient(
        spx - spr * 0.35, spy - spr * 0.35, spr * 0.1, spx, spy, spr);
      grad.addColorStop(0, theme.dark ? '#cfd8dc' : '#ffffff');
      grad.addColorStop(1, col);
      ctx.globalAlpha = sp.alpha != null ? sp.alpha : 0.15;
      ctx.fillStyle = grad;
      ctx.beginPath(); ctx.arc(spx, spy, spr, 0, Math.PI * 2); ctx.fill();
      // Silhouette ring
      ctx.globalAlpha = Math.min(1, (sp.alpha != null ? sp.alpha : 0.15) * 3);
      ctx.strokeStyle = col; ctx.lineWidth = 1;
      ctx.beginPath(); ctx.arc(spx, spy, spr, 0, Math.PI * 2); ctx.stroke();
      // Latitude/longitude wireframe, depth-dimmed per segment
      if (sp.wireframe !== false) {
        ctx.lineWidth = 0.7;
        const SEG = 72, r3 = sp.radius;
        const circles = [];
        for (let lat = -60; lat <= 60; lat += 30) {        // parallels
          const cl = Math.cos(lat * Math.PI / 180) * r3;
          const zl = Math.sin(lat * Math.PI / 180) * r3;
          circles.push(t => [cl * Math.cos(t), cl * Math.sin(t), zl]);
        }
        for (let lon = 0; lon < 180; lon += 30) {          // meridians
          const cl = Math.cos(lon * Math.PI / 180), sl = Math.sin(lon * Math.PI / 180);
          circles.push(t => {
            const x3 = Math.cos(t) * r3;
            return [Math.sin(t) * r3 * cl, Math.sin(t) * r3 * sl, x3];
          });
        }
        for (const f of circles) {
          let prev = null;
          for (let i = 0; i <= SEG; i++) {
            const t  = (i / SEG) * Math.PI * 2;
            const rv = _applyRot(R, norm(f(t)));
            const s  = _project3(rv, cx, cy, scale);
            if (prev) {
              ctx.globalAlpha = (rv[1] + prev[2]) / 2 > 0 ? 0.06 : 0.22;
              ctx.strokeStyle = col;
              ctx.beginPath(); ctx.moveTo(prev[0], prev[1]); ctx.lineTo(s[0], s[1]); ctx.stroke();
            }
            prev = [s[0], s[1], rv[1]];
          }
        }
      }
      ctx.restore();
    }

    if (geom === 'surface' && faces.length > 0) {
      // Compute per-face mean depth and mean z for colour
      const faceData = faces.map(f => {
        const d = (proj[f[0]].d + proj[f[1]].d + proj[f[2]].d) / 3;
        const zMean = (zVals[f[0]] + zVals[f[1]] + zVals[f[2]]) / 3;
        return { f, d, zMean };
      });
      // Painter's algorithm: draw back-to-front
      faceData.sort((a, b) => b.d - a.d);

      for (const { f, zMean } of faceData) {
        const t  = (zMean - zMin) / zRange;
        const fc = _colourFromLut(lut, t);
        const [ax2, ay2] = proj[f[0]].s;
        const [bx,  by ] = proj[f[1]].s;
        const [ccx2,ccy2] = proj[f[2]].s;
        ctx.beginPath();
        ctx.moveTo(ax2, ay2); ctx.lineTo(bx, by); ctx.lineTo(ccx2, ccy2);
        ctx.closePath();
        ctx.fillStyle = fc;
        ctx.fill();
        ctx.strokeStyle = 'rgba(0,0,0,0.12)';
        ctx.lineWidth = 0.4;
        ctx.stroke();
      }

    } else if (geom === 'scatter' && !gpuActive) {
      // Optional per-point colours: b64-encoded uint8 RGB triplets
      const pcKey = st.point_colors_b64 || '';
      if (p._3dPColKey !== pcKey) {
        p._3dPColKey = pcKey;
        p._3dPColUniq = null;
        if (pcKey) {
          const bin = atob(pcKey);
          const buf = new Uint8Array(bin.length);
          for (let i = 0; i < bin.length; i++) buf[i] = bin.charCodeAt(i);
          p._3dPCols = buf;
        } else { p._3dPCols = null; }
      }
      const pCols = p._3dPCols;
      // Sort back-to-front so nearer points draw on top
      const order = proj.map((p2, i) => ({ i, d: p2.d })).sort((a, b) => b.d - a.d);
      ctx.save();
      for (const { i } of order) {
        const [sx, sy] = proj[i].s;
        // Dim far-side points when a reference sphere is shown (depth cue)
        ctx.globalAlpha = (sphereOn && proj[i].d > 0) ? 0.25 : 1.0;
        ctx.beginPath();
        ctx.arc(sx, sy, ptSize, 0, Math.PI * 2);
        ctx.fillStyle = pCols
          ? `rgb(${pCols[i*3]},${pCols[i*3+1]},${pCols[i*3+2]})`
          : color;
        ctx.fill();
      }
      ctx.restore();

    } else if (geom === 'voxels' && !gpuActive) {
      // Shaded translucent cubes at the vertex centres.  Voxels lying on a
      // plane widget's slice render at voxel_slice_alpha (more opaque).
      const pcKey = st.point_colors_b64 || '';
      if (p._3dPColKey !== pcKey) {
        p._3dPColKey = pcKey;
        p._3dPColUniq = null;
        if (pcKey) {
          const bin = atob(pcKey);
          const buf = new Uint8Array(bin.length);
          for (let i = 0; i < bin.length; i++) buf[i] = bin.charCodeAt(i);
          p._3dPCols = buf;
        } else { p._3dPCols = null; }
      }
      const pCols  = p._3dPCols;
      const vsz    = st.voxel_size || 1;
      const h      = vsz / 2;
      const baseA  = st.voxel_alpha != null ? st.voxel_alpha : 0.3;
      const sliceA = st.voxel_slice_alpha != null ? st.voxel_slice_alpha : 0.95;
      const planes = (st.overlay_widgets || []).filter(
        w => w.type === 'plane' && w.visible !== false);
      const AXI = { x: 0, y: 1, z: 2 };

      // Orthographic projection + affine normalisation ⇒ the screen offset
      // of a fixed data-space offset is constant, so cube-corner offsets and
      // face visibility are computed ONCE per frame (one projection/voxel).
      const s2 = 2 / maxR;
      const corners = [];
      for (let ci = 0; ci < 8; ci++) {
        const o  = [ci & 1 ? h : -h, ci & 2 ? h : -h, ci & 4 ? h : -h];
        const rv = _applyRot(R, [o[0] * s2, o[1] * s2, o[2] * s2]);
        corners.push([rv[0] * scale, -rv[2] * scale]);
      }
      // Corner bit encoding: bit0 → +x, bit1 → +y, bit2 → +z
      const FACES = [
        { a: 0, n: [ 1, 0, 0], idx: [1, 3, 7, 5] },
        { a: 0, n: [-1, 0, 0], idx: [0, 2, 6, 4] },
        { a: 1, n: [0,  1, 0], idx: [2, 3, 7, 6] },
        { a: 1, n: [0, -1, 0], idx: [0, 1, 5, 4] },
        { a: 2, n: [0, 0,  1], idx: [4, 5, 7, 6] },
        { a: 2, n: [0, 0, -1], idx: [0, 1, 3, 2] },
      ];
      const SHADE = [0.82, 0.68, 1.0];   // x / y / z faces — top brightest
      const visF = [];
      for (const f of FACES) {
        if (_applyRot(R, f.n)[1] < 0) visF.push({ idx: f.idx, shade: SHADE[f.a] });
      }

      // Volumes typically have few label colours (grains, phases), so render
      // each (colour, emphasis) cube ONCE into a sprite and blit per voxel —
      // drawImage is ~10× cheaper than three path fills.  Degenerate
      // many-colour data falls back to direct path drawing.
      if (p._3dPColUniq == null) {
        if (!pCols) { p._3dPColUniq = 1; }
        else {
          const seen = new Set();
          for (let i = 0; i < pCols.length; i += 3) {
            seen.add((pCols[i] << 16) | (pCols[i + 1] << 8) | pCols[i + 2]);
            if (seen.size > 256) break;
          }
          p._3dPColUniq = seen.size;
        }
      }
      const useSprites = p._3dPColUniq <= 256 &&
                         typeof OffscreenCanvas !== 'undefined';

      // Typed-array projection with inlined matrix math: no per-vertex
      // allocations.  Cached per (geometry, view, panel size): redraws that
      // don't move the camera — e.g. plane-widget drags — skip projection
      // and depth-sort entirely and only re-blit.
      const nV = verts.length;
      const projKey = `${p._voxGen || 0}|${az}|${el}|${zoom}|${pw}x${ph}|${vsz}`;
      if (p._voxProjKey !== projKey || p._voxProjN !== nV) {
        p._voxProjKey = projKey;
        p._voxProjN = nV;
        const SXn = new Float32Array(nV);
        const SYn = new Float32Array(nV);
        const DPn = new Float32Array(nV);
        const k2 = 2 / maxR;
        const bx0 = bnds.xmin, by0 = bnds.ymin, bz0 = bnds.zmin;
        const ox2 = xr / maxR, oy2 = yr / maxR, oz2 = zr / maxR;
        const r00 = R[0][0], r01 = R[0][1], r02 = R[0][2];
        const r10 = R[1][0], r11 = R[1][1], r12 = R[1][2];
        const r20 = R[2][0], r21 = R[2][1], r22 = R[2][2];
        for (let i = 0; i < nV; i++) {
          const v  = verts[i];
          const nx = (v[0] - bx0) * k2 - ox2;
          const ny = (v[1] - by0) * k2 - oy2;
          const nz = (v[2] - bz0) * k2 - oz2;
          SXn[i] = cx + (r00 * nx + r01 * ny + r02 * nz) * scale;
          DPn[i] = r10 * nx + r11 * ny + r12 * nz;
          SYn[i] = cy - (r20 * nx + r21 * ny + r22 * nz) * scale;
        }
        p._voxSX = SXn; p._voxSY = SYn; p._voxDP = DPn;
        p._voxOrder = Array.from({ length: nV }, (_, i) => i)
          .sort((a, b) => DPn[b] - DPn[a]);
      }
      const SXa = p._voxSX, SYa = p._voxSY;
      const order = p._voxOrder;
      ctx.save();

      if (useSprites) {
        // Sprite extent = cube bounding box at the current rotation/zoom
        let mnX = 1e9, mnY = 1e9, mxX = -1e9, mxY = -1e9;
        for (const c of corners) {
          if (c[0] < mnX) mnX = c[0]; if (c[0] > mxX) mxX = c[0];
          if (c[1] < mnY) mnY = c[1]; if (c[1] > mxY) mxY = c[1];
        }
        const sw = Math.max(2, Math.ceil(mxX - mnX) + 2);
        const sh = Math.max(2, Math.ceil(mxY - mnY) + 2);
        const ox = -mnX + 1, oy = -mnY + 1;
        const sprKey = `${az}|${el}|${zoom}|${vsz}|${pw}x${ph}`;
        if (p._voxSprKey !== sprKey) {
          p._voxSprKey = sprKey;
          p._voxSprites = new Map();
        }
        const sprites = p._voxSprites;
        const getSprite = (r0, g0, b0, stroked) => {
          const k = ((r0 << 16) | (g0 << 8) | b0) * 2 + (stroked ? 1 : 0);
          let s = sprites.get(k);
          if (s) return s;
          s = new OffscreenCanvas(sw, sh);
          const sc = s.getContext('2d');
          sc.lineWidth = 0.5;
          sc.strokeStyle = 'rgba(0,0,0,0.35)';
          for (const f of visF) {
            sc.fillStyle =
              `rgb(${(r0 * f.shade) | 0},${(g0 * f.shade) | 0},${(b0 * f.shade) | 0})`;
            sc.beginPath();
            sc.moveTo(ox + corners[f.idx[0]][0], oy + corners[f.idx[0]][1]);
            for (let k2 = 1; k2 < 4; k2++) {
              sc.lineTo(ox + corners[f.idx[k2]][0], oy + corners[f.idx[k2]][1]);
            }
            sc.closePath();
            sc.fill();
            if (stroked) sc.stroke();   // crisp edges on the selected slice
          }
          sprites.set(k, s);
          return s;
        };
        for (let oi = 0; oi < nV; oi++) {
          const i = order[oi];
          const v = verts[i];
          let emph = false;
          for (const pl of planes) {
            if (Math.abs(v[AXI[pl.axis] ?? 2] - (pl.position || 0)) <= vsz * 0.55) {
              emph = true; break;
            }
          }
          ctx.globalAlpha = emph ? sliceA : baseA;
          const r0 = pCols ? pCols[i * 3]     : 79;
          const g0 = pCols ? pCols[i * 3 + 1] : 195;
          const b0 = pCols ? pCols[i * 3 + 2] : 247;
          // Integer-snapped blit: subpixel drawImage triggers resampling,
          // which dominates frame time in software rasterisers.
          ctx.drawImage(getSprite(r0, g0, b0, emph),
                        (SXa[i] - ox + 0.5) | 0, (SYa[i] - oy + 0.5) | 0);
        }
      } else {
        // Direct path drawing (many unique colours / no OffscreenCanvas)
        ctx.lineWidth = 0.5;
        ctx.strokeStyle = 'rgba(0,0,0,0.35)';
        for (let oi = 0; oi < nV; oi++) {
          const i = order[oi];
          const vx2 = SXa[i], vy2 = SYa[i];
          const v = verts[i];
          let emph = false;
          for (const pl of planes) {
            if (Math.abs(v[AXI[pl.axis] ?? 2] - (pl.position || 0)) <= vsz * 0.55) {
              emph = true; break;
            }
          }
          ctx.globalAlpha = emph ? sliceA : baseA;
          const r0 = pCols ? pCols[i * 3]     : 79;
          const g0 = pCols ? pCols[i * 3 + 1] : 195;
          const b0 = pCols ? pCols[i * 3 + 2] : 247;
          for (const f of visF) {
            ctx.fillStyle =
              `rgb(${(r0 * f.shade) | 0},${(g0 * f.shade) | 0},${(b0 * f.shade) | 0})`;
            ctx.beginPath();
            ctx.moveTo(vx2 + corners[f.idx[0]][0], vy2 + corners[f.idx[0]][1]);
            for (let k = 1; k < 4; k++) {
              ctx.lineTo(vx2 + corners[f.idx[k]][0], vy2 + corners[f.idx[k]][1]);
            }
            ctx.closePath();
            ctx.fill();
            if (emph) ctx.stroke();
          }
        }
      }
      ctx.restore();

    } else if (geom === 'line') {
      ctx.beginPath();
      ctx.strokeStyle = color;
      ctx.lineWidth   = lw;
      ctx.lineJoin    = 'round';
      for (let i = 0; i < proj.length; i++) {
        const [sx, sy] = proj[i].s;
        if (i === 0) ctx.moveTo(sx, sy); else ctx.lineTo(sx, sy);
      }
      ctx.stroke();
      // Draw point markers at each vertex
      ctx.fillStyle = color;
      for (const { s } of proj) {
        ctx.beginPath(); ctx.arc(s[0], s[1], lw + 1, 0, Math.PI * 2); ctx.fill();
      }
    }

    // ── Plane widgets: translucent draggable slice selectors ──────────────
    // Drawn over the geometry; screen-space quads + the axis screen
    // direction are cached on the panel for mousedown hit-testing and drag.
    p._3dPlanes = [];
    const planeWs = (st.overlay_widgets || []).filter(
      w => w.type === 'plane' && w.visible !== false);
    if (planeWs.length) {
      const AXI = { x: 0, y: 1, z: 2 };
      const lo = [bnds.xmin, bnds.ymin, bnds.zmin];
      const hi = [bnds.xmax, bnds.ymax, bnds.zmax];
      ctx.save();
      for (const w of planeWs) {
        const a   = AXI[w.axis] ?? 2;
        const u   = (a + 1) % 3, vA = (a + 2) % 3;
        const pos = Math.max(lo[a], Math.min(hi[a], w.position || 0));
        const mk  = (uu, vv) => {
          const c = [0, 0, 0]; c[a] = pos; c[u] = uu; c[vA] = vv; return c;
        };
        const cs  = [mk(lo[u], lo[vA]), mk(hi[u], lo[vA]),
                     mk(hi[u], hi[vA]), mk(lo[u], hi[vA])];
        const scr = cs.map(c => _project3(_applyRot(R, norm(c)), cx, cy, scale));
        // Screen direction of +1 data unit along the plane's axis (for drag)
        const c0 = [0, 0, 0];
        c0[a] = pos; c0[u] = (lo[u] + hi[u]) / 2; c0[vA] = (lo[vA] + hi[vA]) / 2;
        const c1 = c0.slice(); c1[a] = pos + 1;
        const s0 = _project3(_applyRot(R, norm(c0)), cx, cy, scale);
        const s1 = _project3(_applyRot(R, norm(c1)), cx, cy, scale);
        const col = w.color || '#00e5ff';
        const al  = w.alpha != null ? w.alpha : 0.12;
        ctx.globalAlpha = al;
        ctx.fillStyle = col;
        ctx.beginPath();
        ctx.moveTo(scr[0][0], scr[0][1]);
        for (let k = 1; k < 4; k++) ctx.lineTo(scr[k][0], scr[k][1]);
        ctx.closePath(); ctx.fill();
        ctx.globalAlpha = Math.min(1, al * 5);
        ctx.lineWidth = 1.5; ctx.strokeStyle = col; ctx.stroke();
        p._3dPlanes.push({ id: w.id, corners: scr,
                           dir: [s1[0] - s0[0], s1[1] - s0[1]],
                           lo: lo[a], hi: hi[a] });
      }
      ctx.restore();
    }

    // ── Draw axes ────────────────────────────────────────────────────────────
    const axisVerts = [
      [-1,0,0],[1,0,0],[0,-1,0],[0,1,0],[0,0,-1],[0,0,1]
    ];
    const ap = axisVerts.map(v => _project3(_applyRot(R, v), cx, cy, scale));

    const axDefs = [
      { i0:0, i1:1, label: st.x_label||'x', col:'#e06c75', size: st.x_label_size||11 },
      { i0:2, i1:3, label: st.y_label||'y', col:'#98c379', size: st.y_label_size||11 },
      { i0:4, i1:5, label: st.z_label||'z', col:'#61afef', size: st.z_label_size||11 },
    ];
    for (const { i0, i1, label, col, size } of axDefs) {
      ctx.beginPath();
      ctx.moveTo(ap[i0][0], ap[i0][1]);
      ctx.lineTo(ap[i1][0], ap[i1][1]);
      ctx.strokeStyle = col;
      ctx.lineWidth   = 1.5;
      ctx.setLineDash([4, 3]);
      ctx.stroke();
      ctx.setLineDash([]);
      // Positive-end label
      ctx.fillStyle   = col;
      ctx.textBaseline = 'middle';
      _drawTex(ctx, label, ap[i1][0], ap[i1][1], size,
               { align: 'center', weight: 'bold' });
    }

    // ── Tick marks on each axis (5 evenly spaced) ─────────────────────────
    ctx.font = '9px sans-serif';
    ctx.fillStyle = theme.tickText;
    const NTICK = 5;
    const axisData = [
      { lo: bnds.xmin, hi: bnds.xmax, baseN: [0,0,0], dir: [1/maxR*2,0,0] },
      { lo: bnds.ymin, hi: bnds.ymax, baseN: [0,0,0], dir: [0,1/maxR*2,0] },
      { lo: bnds.zmin, hi: bnds.zmax, baseN: [0,0,0], dir: [0,0,1/maxR*2] },
    ];
    const axisColours = ['#e06c75','#98c379','#61afef'];
    for (let ai = 0; ai < 3; ai++) {
      const { lo, hi } = axisData[ai];
      const range = hi - lo || 1;
      const step  = findNice(range / NTICK);
      ctx.fillStyle   = axisColours[ai];
      ctx.strokeStyle = axisColours[ai];
      ctx.lineWidth   = 0.8;
      for (let tv = Math.ceil(lo / step) * step; tv <= hi + step * 0.01; tv += step) {
        const t = (tv - lo) / range; // 0..1
        // Normalised position on the axis
        let nv;
        if (ai === 0) nv = [2*t*xr/maxR - xr/maxR, -yr/maxR, -zr/maxR];
        else if(ai===1) nv = [-xr/maxR, 2*t*yr/maxR - yr/maxR, -zr/maxR];
        else            nv = [-xr/maxR, -yr/maxR, 2*t*zr/maxR - zr/maxR];
        const [tx, ty] = _project3(_applyRot(R, nv), cx, cy, scale);
        // Small tick cross
        ctx.beginPath();
        ctx.arc(tx, ty, 1.5, 0, Math.PI * 2);
        ctx.fill();
        // Label (only every other tick to avoid crowding)
        ctx.textAlign = 'left';
        ctx.textBaseline = 'bottom';
        ctx.fillText(fmtVal(tv), tx + 3, ty - 1);
      }
    }

    // ── Highlight point (drawn last, always on top) ───────────────────────
    // st.highlight = {x, y, z, color, size} in data coordinates.  A filled
    // dot with a contrasting ring; semi-transparent when on the far side of
    // the data (depth cue).
    const hl = st.highlight;
    if (hl && hl.x != null) {
      const rv = _applyRot(R, norm([hl.x, hl.y, hl.z]));
      const [hx, hy] = _project3(rv, cx, cy, scale);
      const far = rv[1] > 0;
      const sz  = hl.size || 7;
      ctx.save();
      ctx.globalAlpha = far ? 0.45 : 1.0;
      ctx.beginPath();
      ctx.arc(hx, hy, sz, 0, Math.PI * 2);
      ctx.fillStyle = hl.color || '#ff1744';
      ctx.fill();
      ctx.lineWidth = 2;
      ctx.strokeStyle = theme.dark ? '#ffffff' : '#1a1a1a';
      ctx.stroke();
      // Outer ring for visibility against same-coloured points
      ctx.beginPath();
      ctx.arc(hx, hy, sz + 3.5, 0, Math.PI * 2);
      ctx.lineWidth = 1.2;
      ctx.strokeStyle = hl.color || '#ff1744';
      ctx.stroke();
      ctx.restore();
    }
  }

  // ── event emission helper (module-scope: accessible to all attach fns) ──
  // eventType: any pointer_* or key_* event type string
  function _emitEvent(panelId, eventType, widgetId, extraData) {
    const payload = Object.assign(
      { source: 'js', panel_id: panelId, event_type: eventType,
        widget_id: widgetId || null },
      extraData || {}
    );
    model.set('event_json', JSON.stringify(payload));
    model.save_changes();
  }

  // Debounced 'view_changed' event: fires to Python after zoom/pan SETTLES (~90 ms
  // idle) with the current view rect, so a viewport-LOD consumer can fetch a hi-res
  // detail tile for exactly the visible region (see Plot2D.set_detail). Debounced so
  // a fast wheel/drag doesn't flood Python — only the final resting view is sent.
  const _viewChangeTimers = {};
  function _emitViewChanged(p, immediate) {
    const st = p.state; if (!st) return;
    const send = () => {
      _viewChangeTimers[p.id] = null;
      const s = p.state; if (!s) return;
      const dpr = window.devicePixelRatio || 1;
      _emitEvent(p.id, 'view_changed', null, {
        zoom: s.zoom, center_x: s.center_x, center_y: s.center_y,
        image_width: s.image_width, image_height: s.image_height,
        // Panel device px → the tile consumer sizes the tile to what fits on screen.
        display_width: Math.round((p.imgW || 0) * dpr),
        display_height: Math.round((p.imgH || 0) * dpr),
      });
    };
    if (_viewChangeTimers[p.id]) clearTimeout(_viewChangeTimers[p.id]);
    if (immediate) { send(); return; }
    _viewChangeTimers[p.id] = setTimeout(send, 90);
  }

  function _modifiers(e) {
    const mods = [];
    if (e.ctrlKey)  mods.push("ctrl");
    if (e.shiftKey) mods.push("shift");
    if (e.altKey)   mods.push("alt");
    if (e.metaKey)  mods.push("meta");
    return mods;
  }

  function _pointerFields(e) {
    return {
      time_stamp: performance.now() / 1000,
      modifiers:  _modifiers(e),
      button:     null,
      buttons:    e.buttons ?? 0,
    };
  }

  function _attachEvents3d(p) {
    const { overlayCanvas } = p;
    let dragStart = null;
    let planeDrag = null;   // active plane-widget drag, or null
    const _scheduleCommit = _makeCommitter(() => model.save_changes());
    const settled = _makeSettledScheduler(p);

    // Write our (already-applied) interaction state without triggering the
    // panel listener echo — see the _selfWrite guard in _createPanelDOM.
    function _writeState() {
      p._selfWrite = true;
      try { model.set(`panel_${p.id}_json`, _viewStateJson(p)); }
      finally { p._selfWrite = false; }
    }

    // Point-in-quad test against the screen-space planes cached by draw3d.
    function _hitPlane(mx, my) {
      const list = p._3dPlanes || [];
      for (let i = list.length - 1; i >= 0; i--) {
        const c = list[i].corners;
        let inside = false;
        for (let k = 0, j = 3; k < 4; j = k++) {
          if (((c[k][1] > my) !== (c[j][1] > my)) &&
              (mx < (c[j][0] - c[k][0]) * (my - c[k][1]) /
                    (c[j][1] - c[k][1]) + c[k][0])) {
            inside = !inside;
          }
        }
        if (inside) return list[i];
      }
      return null;
    }

    overlayCanvas.addEventListener('mousedown', (e) => {
      if (e.button !== 0) return;
      const {mx:_d3mx, my:_d3my} = _clientPos(e, overlayCanvas, p.pw, p.ph);
      // Plane-widget drag takes precedence over orbiting.
      // Cache only the widget ID — p.state is replaced on every model echo,
      // so object references into overlay_widgets go stale mid-drag.
      const hit = _hitPlane(_d3mx, _d3my);
      if (hit) {
        const ws = (p.state.overlay_widgets || []).find(w => w.id === hit.id);
        if (ws) {
          planeDrag = { id: hit.id, dir: hit.dir, lo: hit.lo, hi: hit.hi,
                        mx: _d3mx, my: _d3my, start: ws.position || 0 };
          overlayCanvas.style.cursor = 'move';
          return;
        }
      }
      dragStart = { mx: _d3mx, my: _d3my,
                    az: p.state.azimuth, el: p.state.elevation };
      overlayCanvas.style.cursor = 'grabbing';
      // Do NOT call e.preventDefault() — suppresses click → dblclick cascade.
    });
    document.addEventListener('mousemove', (e) => {
      if (planeDrag) {
        const {mx, my} = _clientPos(e, overlayCanvas, p.pw, p.ph);
        const d   = planeDrag.dir;
        const len2 = d[0] * d[0] + d[1] * d[1] || 1;
        const delta = ((mx - planeDrag.mx) * d[0] + (my - planeDrag.my) * d[1]) / len2;
        // Re-resolve the widget in the CURRENT state (replaced on model echo)
        const ws = (p.state.overlay_widgets || []).find(w => w.id === planeDrag.id);
        if (ws) {
          ws.position = Math.max(planeDrag.lo,
            Math.min(planeDrag.hi, planeDrag.start + delta));
          draw3d(p);
          // Write fresh state BEFORE emitting so the listener echo re-parses
          // the updated widgets (mirrors the orbit-drag pattern).
          _writeState();
          _emitEvent(p.id, 'pointer_move', planeDrag.id,
            { axis: ws.axis, position: ws.position, ..._pointerFields(e) });
        }
        e.preventDefault();
        return;
      }
      if (!dragStart) return;
      const {mx:_d3mx2, my:_d3my2} = _clientPos(e, overlayCanvas, p.pw, p.ph);
      const dx = _d3mx2 - dragStart.mx;
      const dy = _d3my2 - dragStart.my;
      p.state.azimuth   = dragStart.az + dx * 0.5;
      p.state.elevation = Math.max(-89, Math.min(89, dragStart.el - dy * 0.5));
      draw3d(p);
      _writeState();
      _emitEvent(p.id, 'pointer_move', null,
        { azimuth: p.state.azimuth, elevation: p.state.elevation, zoom: p.state.zoom,
          ..._pointerFields(e) });
      e.preventDefault();
    });
    document.addEventListener('mouseup', (e) => {
      settled.clear();
      if (planeDrag) {
        const wid = planeDrag.id;
        planeDrag = null;
        overlayCanvas.style.cursor = 'grab';
        _writeState();
        const ws = (p.state.overlay_widgets || []).find(w => w.id === wid);
        _emitEvent(p.id, 'pointer_up', wid,
          { axis: ws ? ws.axis : null, position: ws ? ws.position : null,
            ..._pointerFields(e), button: e.button });
        _scheduleCommit();
        return;
      }
      if (!dragStart) return;
      dragStart = null;
      overlayCanvas.style.cursor = 'grab';
      _writeState();
      _emitEvent(p.id, 'pointer_up', null,
        { azimuth: p.state.azimuth, elevation: p.state.elevation, zoom: p.state.zoom,
          ..._pointerFields(e), button: e.button });
      _scheduleCommit();
    });

    overlayCanvas.addEventListener('wheel', (e) => {
      e.preventDefault();
      p.state.zoom = Math.max(0.1, Math.min(10, p.state.zoom * (e.deltaY > 0 ? 0.9 : 1.1)));
      draw3d(p);
      _writeState();
      _emitEvent(p.id, 'wheel', null, {
        time_stamp: performance.now() / 1000,
        modifiers: _modifiers(e),
        x: p.mouseX ?? 0, y: p.mouseY ?? 0,
        dx: e.deltaX, dy: e.deltaY,
      });
      _emitEvent(p.id, 'pointer_move', null,
        { azimuth: p.state.azimuth, elevation: p.state.elevation, zoom: p.state.zoom,
          ..._pointerFields(e) });
      _scheduleCommit();
    }, { passive: false });

    overlayCanvas.addEventListener('mousemove', (e) => {
      const {mx, my} = _clientPos(e, overlayCanvas, p.pw, p.ph);
      p.mouseX = mx;
      p.mouseY = my;
      settled.arm(mx, my, e);
    });

    // Keyboard shortcuts
    // Built-in: r=reset view. All keys are forwarded to Python unconditionally.
    overlayCanvas.addEventListener('keydown', (e) => {
      const st = p.state; if (!st) return;
      _emitEvent(p.id, 'key_down', null, {
        time_stamp: performance.now() / 1000,
        modifiers: _modifiers(e),
        key: e.key,
        last_widget_id: p.lastWidgetId || null,
        x: p.mouseX ?? 0, y: p.mouseY ?? 0,
      });
      if (e.key.toLowerCase() === 'r') {
        p.state.azimuth = -60; p.state.elevation = 30; p.state.zoom = 1;
        draw3d(p);
        _writeState();
        model.save_changes();
        e.stopPropagation(); e.preventDefault();
      }
    });
    overlayCanvas.tabIndex = 0;
    overlayCanvas.style.outline = 'none';
    overlayCanvas.style.cursor  = 'grab';
    overlayCanvas.addEventListener('mouseenter', (e) => {
      overlayCanvas.focus();
      _emitEvent(p.id, 'pointer_enter', null, {..._pointerFields(e), x: e.offsetX, y: e.offsetY});
    });
    overlayCanvas.addEventListener('mouseleave', (e) => {
      settled.clear();
      _emitEvent(p.id, 'pointer_leave', null, {..._pointerFields(e), x: e.offsetX, y: e.offsetY});
    });
    overlayCanvas.addEventListener('keyup', (e) => {
      _emitEvent(p.id, 'key_up', null, {
        time_stamp: performance.now() / 1000,
        modifiers: _modifiers(e),
        key: e.key,
        x: p.mouseX ?? 0, y: p.mouseY ?? 0,
      });
    });
    overlayCanvas.addEventListener('dblclick', (e) => {
      const {mx, my} = _clientPos(e, overlayCanvas, p.pw, p.ph);
      _emitEvent(p.id, 'double_click', null, {..._pointerFields(e), button: e.button, x: mx, y: my});
    });
  }

  // ── 1D drawing ───────────────────────────────────────────────────────────

  // Panel rect for a 1-D / coordinate (PlotXY) axis. When state.aspect==='equal'
  // we apply matplotlib's apply_aspect(): shrink + centre the box so one data
  // unit spans equal pixels on x and y (an IPF triangle etc. must not stretch).
  // Baked in here so EVERY consumer (draw1d / markers / overlay / hit-test) uses
  // the identical box — matplotlib's transData derives from the adjusted axes box.
  function _plotRect1d(p){
    const pw=p.pw, ph=p.ph, st=p.state;
    const r={x:PAD_L,y:PAD_T,w:Math.max(1,pw-PAD_L-PAD_R),h:Math.max(1,ph-PAD_T-PAD_B)};
    if(!st || st.aspect!=='equal') return r;
    const xArr=p._1dXArr || (st.x_axis_b64 ? _decodeF64(st.x_axis_b64) : (st.x_axis||[]));
    const x0=st.view_x0||0, x1=st.view_x1||1;
    let xspan=1;
    if(xArr && xArr.length>=2) xspan=Math.abs(_axisFracToVal(xArr,x1)-_axisFracToVal(xArr,x0))||1;
    let dMin=st.data_min, dMax=st.data_max;
    if(st.y_range && st.y_range.length===2){ dMin=st.y_range[0]; dMax=st.y_range[1]; }
    const yspan=Math.abs((dMax!=null?dMax:1)-(dMin!=null?dMin:0))||1;
    const s=Math.min(r.w/xspan, r.h/yspan);
    const nw=s*xspan, nh=s*yspan;
    return {x:r.x+(r.w-nw)/2, y:r.y+(r.h-nh)/2, w:nw, h:nh};
  }

  // _xToFrac1d / _fracToX1d are identical to _axisValToFrac / _axisFracToVal
  // (defined at the top of this file) — callers use those shared functions.
  function _fracToPx1d(frac,x0,x1,r){return r.x+((frac-x0)/((x1-x0)||1))*r.w;}
  function _valToPy1d(val,dMin,dMax,r){return r.y+r.h-((val-dMin)/((dMax-dMin)||1))*r.h;}

  function draw1d(p) {
    const st=p.state; if(!st) return;
    _recordFrame(p);
    const {pw,ph,plotCtx:ctx} = p;
    const r=_plotRect1d(p);

    // ── decode + cache b64 arrays (keyed by b64 string; free on re-render) ──
    const xKey = st.x_axis_b64 || '';
    const dKey = st.data_b64   || '';
    if (p._1dXKey !== xKey) {
      p._1dXKey  = xKey;
      p._1dXArr  = xKey ? _decodeF64(xKey) : (st.x_axis || []);
    }
    if (p._1dDKey !== dKey) {
      p._1dDKey  = dKey;
      p._1dDArr  = dKey ? _decodeF64(dKey)  : (st.data   || []);
    }
    const xArr = p._1dXArr;   // Float64Array (or plain array fallback)
    const yData = p._1dDArr;  // Float64Array (or plain array fallback)

    const x0=st.view_x0||0, x1=st.view_x1||1;
    let dMin=st.data_min, dMax=st.data_max;
    if (st.y_range && st.y_range.length === 2) { dMin = st.y_range[0]; dMax = st.y_range[1]; }
    // Cache the linear y bounds so the dblclick handler inverts event y → data y
    // using exactly what was drawn (for a PlotXY coordinate axis the y range is
    // y_range, not the hidden zero-curve's data_min/max).
    p._1dDMin=dMin; p._1dDMax=dMax;
    const units=st.units||'', yUnits=st.y_units||'';

    const isLog = st.yscale === 'log';
    const _logEps = 1e-300;
    const effDMin = isLog ? Math.log10(Math.max(_logEps, dMin)) : dMin;
    const effDMax = isLog ? Math.log10(Math.max(_logEps, dMax)) : dMax;
    function _toPlotY(v) {
      return _valToPy1d(isLog ? Math.log10(Math.max(_logEps, v)) : v, effDMin, effDMax, r);
    }

    ctx.clearRect(0,0,pw,ph);
    ctx.fillStyle=theme.bg; ctx.fillRect(0,0,pw,ph);
    ctx.fillStyle=theme.bgPlot; ctx.fillRect(r.x,r.y,r.w,r.h);

    // Grid
    ctx.strokeStyle=theme.gridStroke; ctx.lineWidth=1;
    if(xArr.length>=2){
      const xVMin=_axisFracToVal(xArr,x0), xVMax=_axisFracToVal(xArr,x1);
      const xStep=findNice((xVMax-xVMin)/Math.max(2,Math.floor(r.w/70)));
      for(let v=Math.ceil(xVMin/xStep)*xStep;v<=xVMax+xStep*0.01;v+=xStep){
        const px=_fracToPx1d(_axisValToFrac(xArr,v),x0,x1,r);
        if(px<r.x||px>r.x+r.w) continue;
        ctx.beginPath();ctx.moveTo(px,r.y);ctx.lineTo(px,r.y+r.h);ctx.stroke();
      }
    }
    const yRange=(effDMax-effDMin)||1;
    const yStep=findNice(yRange/Math.max(2,Math.floor(r.h/40)));
    if(isLog){
      const lo=Math.floor(effDMin), hi=Math.ceil(effDMax);
      for(let e=lo;e<=hi;e++){
        const py=_toPlotY(Math.pow(10,e));
        if(py<r.y||py>r.y+r.h) continue;
        ctx.beginPath();ctx.moveTo(r.x,py);ctx.lineTo(r.x+r.w,py);ctx.stroke();
      }
    } else {
      for(let v=Math.ceil(dMin/yStep)*yStep;v<=dMax+yStep*0.01;v+=yStep){
        const py=_valToPy1d(v,dMin,dMax,r);
        if(py<r.y||py>r.y+r.h) continue;
        ctx.beginPath();ctx.moveTo(r.x,py);ctx.lineTo(r.x+r.w,py);ctx.stroke();
      }
    }

    // Spans
    for(const sp of (st.spans||[])){
      ctx.fillStyle=sp.color||(theme.dark?'rgba(255,255,100,0.15)':'rgba(200,160,0,0.15)');
      if(sp.axis==='x'){
        const px0=_fracToPx1d(_axisValToFrac(xArr,sp.v0),x0,x1,r);
        const px1b=_fracToPx1d(_axisValToFrac(xArr,sp.v1),x0,x1,r);
        ctx.fillRect(px0,r.y,px1b-px0,r.h);
      } else {
        const py0=_toPlotY(sp.v1), py1=_toPlotY(sp.v0);
        ctx.fillRect(r.x,py0,r.w,py1-py0);
      }
    }

    // Clip
    ctx.save(); ctx.beginPath(); ctx.rect(r.x,r.y,r.w,r.h); ctx.clip();

    // Linestyle → canvas dash pattern
    const _LINESTYLE_DASH = {
      'solid':   [],
      'dashed':  [6, 3],
      'dotted':  [2, 3],
      'dashdot': [6, 3, 2, 3],
    };

    // Draw a single marker symbol centred at (px, py) with half-size ms.
    // The caller is responsible for beginPath() before and fill()/stroke() after.
    function _drawMarkerSymbol(mctx, marker, px, py, ms) {
      switch (marker) {
        case 'o':
          mctx.arc(px, py, ms, 0, Math.PI * 2);
          break;
        case 's':
          mctx.rect(px - ms, py - ms, ms * 2, ms * 2);
          break;
        case '^':
          mctx.moveTo(px, py - ms);
          mctx.lineTo(px + ms, py + ms);
          mctx.lineTo(px - ms, py + ms);
          mctx.closePath();
          break;
        case 'v':
          mctx.moveTo(px, py + ms);
          mctx.lineTo(px + ms, py - ms);
          mctx.lineTo(px - ms, py - ms);
          mctx.closePath();
          break;
        case 'D':
          mctx.moveTo(px, py - ms);
          mctx.lineTo(px + ms, py);
          mctx.lineTo(px, py + ms);
          mctx.lineTo(px - ms, py);
          mctx.closePath();
          break;
        case '+':
          mctx.moveTo(px - ms, py); mctx.lineTo(px + ms, py);
          mctx.moveTo(px, py - ms); mctx.lineTo(px, py + ms);
          break;
        case 'x':
          mctx.moveTo(px - ms, py - ms); mctx.lineTo(px + ms, py + ms);
          mctx.moveTo(px + ms, py - ms); mctx.lineTo(px - ms, py + ms);
          break;
        default:
          mctx.arc(px, py, ms, 0, Math.PI * 2);
      }
    }

    // Stroke-only markers (no meaningful fill area)
    const _MARKER_STROKE_ONLY = new Set(['+', 'x']);

    function _drawLine(yData, lineXArr, color, lw, linestyle, alpha, marker, markersize) {
      if (!yData || !yData.length) return;
      const n = yData.length;
      const isStepMid = linestyle === 'step-mid';
      const dash = isStepMid ? [] : (_LINESTYLE_DASH[linestyle || 'solid'] || []);
      const eff_alpha = (alpha != null && alpha < 1.0) ? alpha : 1.0;
      const ms = Math.max(1, markersize || 4);
      const doMarker = marker && marker !== 'none';

      // Pre-compute pixel positions
      const allPx = new Array(n), allPy = new Array(n);
      for (let i = 0; i < n; i++) {
        const xFrac = lineXArr.length >= 2
          ? (lineXArr[i] - lineXArr[0]) / ((lineXArr[lineXArr.length - 1] - lineXArr[0]) || 1)
          : i / ((n - 1) || 1);
        allPx[i] = _fracToPx1d(xFrac, x0, x1, r);
        allPy[i] = _toPlotY(yData[i]);
      }

      ctx.save();
      if (eff_alpha < 1.0) ctx.globalAlpha = eff_alpha;
      ctx.setLineDash(dash);
      ctx.beginPath();
      ctx.strokeStyle = color; ctx.lineWidth = lw; ctx.lineJoin = 'round';

      if (isStepMid && n >= 2) {
        ctx.moveTo(allPx[0], allPy[0]);
        for (let i = 0; i < n - 1; i++) {
          const midX = (allPx[i] + allPx[i + 1]) / 2;
          ctx.lineTo(midX, allPy[i]);
          ctx.lineTo(midX, allPy[i + 1]);
        }
        ctx.lineTo(allPx[n - 1], allPy[n - 1]);
      } else {
        for (let i = 0; i < n; i++) {
          if (i === 0) ctx.moveTo(allPx[i], allPy[i]);
          else ctx.lineTo(allPx[i], allPy[i]);
        }
      }
      ctx.stroke();
      ctx.setLineDash([]);

      const pts = doMarker ? allPx.map((px, i) => [px, allPy[i]]) : null;

      // Per-point marker symbols
      if (doMarker && pts && pts.length) {
        ctx.strokeStyle = color;
        ctx.fillStyle   = color;
        ctx.lineWidth   = Math.max(1, lw * 0.8);
        const strokeOnly = _MARKER_STROKE_ONLY.has(marker);
        for (const [px, py] of pts) {
          ctx.beginPath();
          _drawMarkerSymbol(ctx, marker, px, py, ms);
          if (!strokeOnly) ctx.fill();
          ctx.stroke();
        }
      }

      ctx.restore();
    }

    _drawLine(yData, xArr,
      st.line_color || '#4fc3f7', st.line_linewidth || 1.5,
      st.line_linestyle || 'solid',
      st.line_alpha != null ? st.line_alpha : 1.0,
      st.line_marker || 'none', st.line_markersize || 4);
    for (const ex of (st.extra_lines || [])) {
      const exY = ex.data_b64   ? _decodeF64(ex.data_b64)   : (ex.data   || []);
      const exX = ex.x_axis_b64 ? _decodeF64(ex.x_axis_b64) : (ex.x_axis ? ex.x_axis : xArr);
      _drawLine(exY, exX,
        ex.color || (theme.dark ? '#fff' : '#333'), ex.linewidth || 1.5,
        ex.linestyle || 'solid',
        ex.alpha != null ? ex.alpha : 1.0,
        ex.marker || 'none', ex.markersize || 4);
    }
    // ── hovered-line highlight: redraw on top with brightened colour + thicker stroke ──
    const _hovId = p._lineHoverId;
    if (_hovId !== undefined && _hovId !== '__none__') {
      if (_hovId === null) {
        _drawLine(yData, xArr,
          _brightenColor(st.line_color||'#4fc3f7'), (st.line_linewidth||1.5)+1,
          st.line_linestyle||'solid', st.line_alpha!=null?st.line_alpha:1.0,
          st.line_marker||'none', st.line_markersize||4);
      } else {
        for (const ex of (st.extra_lines||[])) {
          if (ex.id === _hovId) {
            const exY = ex.data_b64 ? _decodeF64(ex.data_b64) : (ex.data||[]);
            const exX = ex.x_axis_b64 ? _decodeF64(ex.x_axis_b64) : (ex.x_axis?ex.x_axis:xArr);
            _drawLine(exY, exX,
              _brightenColor(ex.color||(theme.dark?'#fff':'#333')), (ex.linewidth||1.5)+1,
              ex.linestyle||'solid', ex.alpha!=null?ex.alpha:1.0,
              ex.marker||'none', ex.markersize||4);
            break;
          }
        }
      }
    }
    ctx.restore();

    const axisVis1d=st.axis_visible!==false;
    const xTicksVis1d=st.x_ticks_visible!==false;
    const yTicksVis1d=st.y_ticks_visible!==false;

    // Axes
    ctx.strokeStyle=theme.axisStroke; ctx.lineWidth=1;
    ctx.beginPath();ctx.moveTo(r.x,r.y+r.h);ctx.lineTo(r.x+r.w,r.y+r.h);ctx.stroke();
    ctx.beginPath();ctx.moveTo(r.x,r.y);ctx.lineTo(r.x,r.y+r.h);ctx.stroke();

    if(axisVis1d&&xTicksVis1d){
      ctx.fillStyle=theme.tickText; ctx.font=(st.tick_size||10)+'px monospace';
      if(xArr.length>=2){
        const xVMin=_axisFracToVal(xArr,x0), xVMax=_axisFracToVal(xArr,x1);
        const xStep=findNice((xVMax-xVMin)/Math.max(2,Math.floor(r.w/70)));
        ctx.textAlign='center'; ctx.textBaseline='top';
        for(let v=Math.ceil(xVMin/xStep)*xStep;v<=xVMax+xStep*0.01;v+=xStep){
          const px=_fracToPx1d(_axisValToFrac(xArr,v),x0,x1,r);
          if(px<r.x||px>r.x+r.w) continue;
          ctx.strokeStyle=theme.axisStroke;ctx.beginPath();ctx.moveTo(px,r.y+r.h);ctx.lineTo(px,r.y+r.h+5);ctx.stroke();
          const xtTxt=fmtVal(v);
          const xtHw=ctx.measureText(xtTxt).width/2;
          ctx.fillStyle=theme.tickText;
          ctx.fillText(xtTxt, Math.min(Math.max(px,xtHw), pw-xtHw), r.y+r.h+7);
        }
        if(units&&units!=='px'){ctx.textBaseline='top';ctx.fillStyle=theme.unitText;_drawTex(ctx,units,r.x+r.w,r.y+r.h+24,st.x_label_size||9,{align:'right',family:'monospace'});}
      }
    }
    if(axisVis1d&&yTicksVis1d){
      ctx.font=(st.tick_size||10)+'px monospace';ctx.textAlign='right';ctx.textBaseline='middle';
      const tickRX=r.x-8;
      if(isLog){
        const lo=Math.floor(effDMin), hi=Math.ceil(effDMax);
        for(let e=lo;e<=hi;e++){
          const v=Math.pow(10,e);
          const py=_toPlotY(v);
          if(py<r.y||py>r.y+r.h) continue;
          ctx.strokeStyle=theme.axisStroke;ctx.beginPath();ctx.moveTo(r.x,py);ctx.lineTo(r.x-5,py);ctx.stroke();
          ctx.fillStyle=theme.tickText;_drawTex(ctx,'$10^{'+e+'}$',tickRX,py,st.tick_size||10,{align:'right',family:'monospace'});
        }
      } else {
        let maxTW=0;
        for(let v=Math.ceil(dMin/yStep)*yStep;v<=dMax+yStep*0.01;v+=yStep){const tw=ctx.measureText(fmtVal(v)).width;if(tw>maxTW)maxTW=tw;}
        for(let v=Math.ceil(dMin/yStep)*yStep;v<=dMax+yStep*0.01;v+=yStep){
          const py=_valToPy1d(v,dMin,dMax,r);
          if(py<r.y||py>r.y+r.h) continue;
          ctx.strokeStyle=theme.axisStroke;ctx.beginPath();ctx.moveTo(r.x,py);ctx.lineTo(r.x-5,py);ctx.stroke();
          ctx.fillStyle=theme.tickText;ctx.fillText(fmtVal(v),tickRX,py);
        }
      }
      if(yUnits){
        ctx.save();
        // Centre the rotated label in the left gutter (x = 0..r.x).
        // Using a fixed x of PAD_L*0.28 keeps it clear of the tick numbers
        // regardless of how wide those numbers are.
        const ylpx1d = st.y_label_size||9;
        const lcx = Math.max(Math.round(PAD_L * 0.28), Math.ceil(ylpx1d*0.62)+1);
        ctx.translate(lcx, r.y+r.h/2); ctx.rotate(-Math.PI/2);
        ctx.textBaseline='middle';
        ctx.fillStyle=theme.unitText;
        _drawTex(ctx, yUnits, 0, 0, ylpx1d, {align:'center',family:'monospace'});
        ctx.restore();
      }
    }

    // Legend
    const labels=[];
    if(st.line_label) labels.push({
      color: st.line_color||'#4fc3f7', text: st.line_label,
      linestyle: st.line_linestyle||'solid',
      marker: st.line_marker||'none', ms: st.line_markersize||4,
    });
    for(const ex of (st.extra_lines||[])) if(ex.label) labels.push({
      color: ex.color||(theme.dark?'#fff':'#333'), text: ex.label,
      linestyle: ex.linestyle||'solid',
      marker: ex.marker||'none', ms: ex.markersize||4,
    });
    if(labels.length){
      ctx.font='10px monospace'; let ly=r.y+6;
      for(const lb of labels){
        const ldash=_LINESTYLE_DASH[lb.linestyle||'solid']||[];
        ctx.strokeStyle=lb.color; ctx.lineWidth=2;
        ctx.setLineDash(ldash);
        ctx.beginPath(); ctx.moveTo(r.x+8,ly+5); ctx.lineTo(r.x+24,ly+5); ctx.stroke();
        ctx.setLineDash([]);
        if(lb.marker && lb.marker!=='none'){
          ctx.strokeStyle=lb.color; ctx.fillStyle=lb.color; ctx.lineWidth=1.5;
          ctx.beginPath(); _drawMarkerSymbol(ctx,lb.marker,r.x+16,ly+5,Math.min(lb.ms||4,4)); ctx.fill(); ctx.stroke();
        }
        ctx.fillStyle=theme.tickText;ctx.textAlign='left';ctx.textBaseline='top';ctx.fillText(lb.text,r.x+28,ly);ly+=16;
      }
    }

    const title1d=st.title||'';
    if(title1d){
      ctx.fillStyle=theme.tickText;
      ctx.textBaseline='middle';
      // 1D titles live in the fixed PAD_T strip; clamp the drawn size so
      // ascenders/descenders never clip (the 2D title strip grows instead).
      _drawTex(ctx, title1d, r.x+r.w/2, PAD_T/2, _titlePx(st),
               {align:'center', weight:'bold'});
    }

    drawOverlay1d(p);
    drawMarkers1d(p);
  }

  function drawOverlay1d(p) {
    const st=p.state; if(!st) return;
    const {pw,ph,ovCtx} = p;
    const r=_plotRect1d(p);
    const xArr = p._1dXArr || (st.x_axis_b64 ? _decodeF64(st.x_axis_b64) : (st.x_axis||[]));
    const x0=st.view_x0||0, x1=st.view_x1||1;
    const dMin=st.data_min, dMax=st.data_max;
    ovCtx.clearRect(0,0,pw,ph);
    const widgets=st.overlay_widgets||[];
    if(!widgets.length) return;

    for(const w of widgets){
      if(w.visible === false) continue;
      const color=w.color||'#00e5ff';
      ovCtx.save();ovCtx.strokeStyle=color;ovCtx.lineWidth=2;
      if(w.type==='vline'){
        const px=_fracToPx1d(_axisValToFrac(xArr,w.x),x0,x1,r);
        ovCtx.setLineDash([5,3]);ovCtx.beginPath();ovCtx.moveTo(px,r.y);ovCtx.lineTo(px,r.y+r.h);ovCtx.stroke();ovCtx.setLineDash([]);
        _ovHandle1d(ovCtx,px,r.y+7,color);
      } else if(w.type==='hline'){
        const py=_valToPy1d(w.y,dMin,dMax,r);
        ovCtx.setLineDash([5,3]);ovCtx.beginPath();ovCtx.moveTo(r.x,py);ovCtx.lineTo(r.x+r.w,py);ovCtx.stroke();ovCtx.setLineDash([]);
        _ovHandle1d(ovCtx,r.x+r.w-7,py,color);
      } else if(w.type==='range'){
        const px0=_fracToPx1d(_axisValToFrac(xArr,w.x0),x0,x1,r);
        const px1b=_fracToPx1d(_axisValToFrac(xArr,w.x1),x0,x1,r);
        if(w.style==='fwhm'){
          // FWHM style: o-------o  two handles joined by a dashed horizontal line
          const pyHalf=_valToPy1d(w.y||0,dMin,dMax,r);
          ovCtx.setLineDash([5,4]);
          ovCtx.beginPath();ovCtx.moveTo(px0,pyHalf);ovCtx.lineTo(px1b,pyHalf);ovCtx.stroke();
          ovCtx.setLineDash([]);
          _ovHandle1d(ovCtx,px0,pyHalf,color);
          _ovHandle1d(ovCtx,px1b,pyHalf,color);
        } else {
          // band style (default)
          const left=Math.min(px0,px1b), right=Math.max(px0,px1b);
          ovCtx.save();ovCtx.globalAlpha=0.15;ovCtx.fillStyle=color;ovCtx.fillRect(left,r.y,right-left,r.h);ovCtx.restore();
          ovCtx.setLineDash([5,3]);
          ovCtx.beginPath();ovCtx.moveTo(px0,r.y);ovCtx.lineTo(px0,r.y+r.h);ovCtx.stroke();
          ovCtx.beginPath();ovCtx.moveTo(px1b,r.y);ovCtx.lineTo(px1b,r.y+r.h);ovCtx.stroke();
          ovCtx.setLineDash([]);
          _ovHandle1d(ovCtx,px0,r.y+7,color);_ovHandle1d(ovCtx,px1b,r.y+7,color);
        }
      } else if(w.type==='point'){
        const px=_fracToPx1d(_axisValToFrac(xArr,w.x),x0,x1,r);
        const py=_valToPy1d(w.y,dMin,dMax,r);
        // Dashed crosshair guide lines (skipped when show_crosshair is false)
        if(w.show_crosshair!==false){
          ovCtx.save();ovCtx.beginPath();ovCtx.rect(r.x,r.y,r.w,r.h);ovCtx.clip();
          ovCtx.setLineDash([4,3]);
          ovCtx.beginPath();ovCtx.moveTo(px,r.y);ovCtx.lineTo(px,r.y+r.h);ovCtx.stroke();
          ovCtx.beginPath();ovCtx.moveTo(r.x,py);ovCtx.lineTo(r.x+r.w,py);ovCtx.stroke();
          ovCtx.setLineDash([]);
          ovCtx.restore();
        }
        // Draw the draggable handle (larger than _ovHandle1d for easy grab)
        ovCtx.save();ovCtx.fillStyle=color;ovCtx.strokeStyle='rgba(0,0,0,0.5)';ovCtx.lineWidth=1.5;
        ovCtx.beginPath();ovCtx.arc(px,py,7,0,Math.PI*2);ovCtx.fill();ovCtx.stroke();
        ovCtx.restore();
      }
      ovCtx.restore();
    }
  }

  function _ovHandle1d(ctx,x,y,color){
    ctx.save();ctx.fillStyle=color;ctx.strokeStyle='rgba(0,0,0,0.45)';ctx.lineWidth=1.5;
    ctx.beginPath();ctx.arc(x,y,5,0,Math.PI*2);ctx.fill();ctx.stroke();ctx.restore();
  }

  function drawMarkers1d(p, hoverState) {
    const st=p.state; if(!st) return;
    const {pw,ph,mkCtx} = p;
    const r=_plotRect1d(p);
    // Use cached decoded arrays from draw1d; fall back to inline decode if needed.
    const xArr = p._1dXArr || (st.x_axis_b64 ? _decodeF64(st.x_axis_b64) : (st.x_axis||[]));
    const yData = p._1dDArr || (st.data_b64 ? _decodeF64(st.data_b64) : (st.data||[]));
    const x0=st.view_x0||0, x1=st.view_x1||1;
    let dMin=st.data_min, dMax=st.data_max;
    if (st.y_range && st.y_range.length === 2) { dMin = st.y_range[0]; dMax = st.y_range[1]; }
    mkCtx.clearRect(0,0,pw,ph);
    const sets=st.markers||[];
    if(!sets.length) return;
    const hsi = hoverState ? hoverState.si : -1;

    mkCtx.save();mkCtx.beginPath();mkCtx.rect(r.x,r.y,r.w,r.h);mkCtx.clip();

    function _offToCanvas(off){
      const xFrac=xArr.length>=2?_axisValToFrac(xArr,off[0]):(off[0]/((xArr.length-1)||1));
      const px=_fracToPx1d(xFrac,x0,x1,r);
      let py;
      if(off.length>=2&&off[1]!=null){py=_valToPy1d(off[1],dMin,dMax,r);}
      else if(yData.length>1){const idx=Math.max(0,Math.min(yData.length-1,Math.round(xFrac*(yData.length-1))));py=_valToPy1d(yData[idx],dMin,dMax,r);}
      else{py=_valToPy1d(0,dMin,dMax,r);}
      return[px,py];
    }
    function _xPx(v){return _fracToPx1d(xArr.length>=2?_axisValToFrac(xArr,v):0,x0,x1,r);}
    function _yPx(v){return _valToPy1d(v,dMin,dMax,r);}

    for(let si=0;si<sets.length;si++){
      const ms=sets[si];
      const isHov=si===hsi;
      const color=ms.color||'#ff0000', lw=ms.linewidth!=null?ms.linewidth:1.5;
      const type=ms.type||'points';
      const fc=ms.fill_color||null, fa=ms.fill_alpha!=null?ms.fill_alpha:0.3;
      // Hover colours: only applied when explicitly set — no default fallback.
      const ec  = isHov && ms.hover_color     ? ms.hover_color     : color;
      const fch = isHov && ms.hover_facecolor ? ms.hover_facecolor : fc;
      const dlw = isHov && (ms.hover_color || ms.hover_facecolor) ? lw+1 : lw;

      // Coordinate transform: "axes" and "display" map 2-D offsets to panel
      // space independently of data values; vlines/hlines stay in data coords.
      const tfm = ms.transform || 'data';
      let _tc2d;
      if(tfm==='axes'){
        _tc2d=(fx,fy)=>[r.x+fx*r.w, r.y+(1-fy)*r.h];
      } else if(tfm==='display'){
        _tc2d=(ix,iy)=>[ix,iy];
      } else {
        _tc2d=(off0,off1)=>_offToCanvas([off0,off1]);
      }

      mkCtx.save();mkCtx.strokeStyle=ec;mkCtx.fillStyle=ec;mkCtx.lineWidth=dlw;

      // Optional clip path (matplotlib set_clip_path): a data-coord polygon the
      // group is clipped to — e.g. a pcolormesh mesh clipped to a curved
      // fundamental-sector boundary so edge cells don't stick out. Scoped to this
      // set's save()/restore().
      if(ms.clip_path && ms.clip_path.length>=3){
        const _cp0= tfm==='data' ? _offToCanvas(ms.clip_path[0]) : _tc2d(ms.clip_path[0][0],ms.clip_path[0][1]);
        mkCtx.beginPath();mkCtx.moveTo(_cp0[0],_cp0[1]);
        for(let k=1;k<ms.clip_path.length;k++){
          const _cp= tfm==='data' ? _offToCanvas(ms.clip_path[k]) : _tc2d(ms.clip_path[k][0],ms.clip_path[k][1]);
          mkCtx.lineTo(_cp[0],_cp[1]);
        }
        mkCtx.closePath();mkCtx.clip();
      }

      if(type==='points'){
        // Per-point face/edge colours (matplotlib scatter c=[...]): fill_color
        // and/or color may be arrays parallel to offsets.
        const _fcArr = Array.isArray(fch) ? fch : null;
        const _ecArr = Array.isArray(ec)  ? ec  : null;
        for(let i=0;i<ms.offsets.length;i++){
          const [px,py]= tfm==='data' ? _offToCanvas(ms.offsets[i]) : _tc2d(ms.offsets[i][0],ms.offsets[i][1]!=null?ms.offsets[i][1]:0);
          const sz=Math.max(1,ms.sizes[i]!=null?ms.sizes[i]:ms.sizes[0]||5);
          mkCtx.beginPath();mkCtx.arc(px,py,sz,0,Math.PI*2);
          const _fc=_fcArr?_fcArr[i%_fcArr.length]:fch;
          if(_fc){mkCtx.save();mkCtx.globalAlpha=fa;mkCtx.fillStyle=_fc;mkCtx.fill();mkCtx.restore();}
          if(_ecArr) mkCtx.strokeStyle=_ecArr[i%_ecArr.length];
          mkCtx.stroke();
        }
      } else if(type==='vlines'){
        for(let i=0;i<ms.offsets.length;i++){
          const px=_xPx(ms.offsets[i][0]);
          mkCtx.beginPath();mkCtx.moveTo(px,r.y);mkCtx.lineTo(px,r.y+r.h);mkCtx.stroke();
        }
      } else if(type==='hlines'){
        for(let i=0;i<ms.offsets.length;i++){
          const py=_yPx(ms.offsets[i][0]);
          mkCtx.beginPath();mkCtx.moveTo(r.x,py);mkCtx.lineTo(r.x+r.w,py);mkCtx.stroke();
        }
      } else if(type==='lines'){
        for(const seg of (ms.segments||[])){
          const [x1c,y1c]= tfm==='data' ? _offToCanvas(seg[0]) : _tc2d(seg[0][0],seg[0][1]);
          const [x2c,y2c]= tfm==='data' ? _offToCanvas(seg[1]) : _tc2d(seg[1][0],seg[1][1]);
          mkCtx.beginPath();mkCtx.moveTo(x1c,y1c);mkCtx.lineTo(x2c,y2c);mkCtx.stroke();
        }
      } else if(type==='ellipses'){
        for(let i=0;i<ms.offsets.length;i++){
          const off=ms.offsets[i];
          const [cx,cy]= tfm==='data' ? _offToCanvas(off) : _tc2d(off[0],off[1]!=null?off[1]:0);
          const wd=ms.widths[i]!=null?ms.widths[i]:(ms.widths[0]||10);
          const hd=ms.heights[i]!=null?ms.heights[i]:(ms.heights[0]||10);
          const rw=Math.max(1, tfm==='data' ? Math.abs(_xPx(off[0]+wd/2)-_xPx(off[0]-wd/2))/2 : wd/2);
          const rh=Math.max(1, tfm==='data' ? Math.abs(_yPx((off[1]||0)-hd/2)-_yPx((off[1]||0)+hd/2))/2 : hd/2);
          const ang=((ms.angles&&(ms.angles[i]!=null?ms.angles[i]:ms.angles[0])||0)*Math.PI)/180;
          mkCtx.beginPath();mkCtx.ellipse(cx,cy,rw,rh,ang,0,Math.PI*2);
          if(fch){mkCtx.save();mkCtx.globalAlpha=fa;mkCtx.fillStyle=fch;mkCtx.fill();mkCtx.restore();}
          mkCtx.stroke();
        }
      } else if(type==='rectangles'||type==='squares'){
        const heights=type==='squares'?ms.widths:ms.heights;
        for(let i=0;i<ms.offsets.length;i++){
          const off=ms.offsets[i];
          const [cx,cy]= tfm==='data' ? _offToCanvas(off) : _tc2d(off[0],off[1]!=null?off[1]:0);
          const wd=ms.widths[i]!=null?ms.widths[i]:(ms.widths[0]||10);
          const hd=heights[i]!=null?heights[i]:(heights[0]||10);
          const rw=Math.max(1, tfm==='data' ? Math.abs(_xPx(off[0]+wd/2)-_xPx(off[0]-wd/2)) : wd);
          const rh=Math.max(1, tfm==='data' ? Math.abs(_yPx((off[1]||0)-hd/2)-_yPx((off[1]||0)+hd/2)) : hd);
          const ang=((ms.angles&&(ms.angles[i]!=null?ms.angles[i]:ms.angles[0])||0)*Math.PI)/180;
          mkCtx.save();mkCtx.translate(cx,cy);mkCtx.rotate(ang);
          if(fch){mkCtx.save();mkCtx.globalAlpha=fa;mkCtx.fillStyle=fch;mkCtx.fillRect(-rw/2,-rh/2,rw,rh);mkCtx.restore();}
          mkCtx.strokeRect(-rw/2,-rh/2,rw,rh);
          mkCtx.restore();
        }
      } else if(type==='polygons'){
        // Per-polygon face/edge colours (matplotlib PathCollection / pcolormesh):
        // fill_color and/or color may be arrays parallel to vertices_list.
        const _fcArr = Array.isArray(fch) ? fch : null;
        const _ecArr = Array.isArray(ec)  ? ec  : null;
        for(let i=0;i<(ms.vertices_list||[]).length;i++){
          const verts=ms.vertices_list[i];
          if(!verts||verts.length<2) continue;
          const [px0,py0]= tfm==='data' ? _offToCanvas(verts[0]) : _tc2d(verts[0][0],verts[0][1]);
          mkCtx.beginPath();mkCtx.moveTo(px0,py0);
          for(let k=1;k<verts.length;k++){
            const[px,py]= tfm==='data' ? _offToCanvas(verts[k]) : _tc2d(verts[k][0],verts[k][1]);
            mkCtx.lineTo(px,py);
          }
          mkCtx.closePath();
          const _fc=_fcArr?_fcArr[i%_fcArr.length]:fch;
          if(_fc){mkCtx.save();mkCtx.globalAlpha=fa;mkCtx.fillStyle=_fc;mkCtx.fill();mkCtx.restore();}
          if(_ecArr) mkCtx.strokeStyle=_ecArr[i%_ecArr.length];
          mkCtx.stroke();
        }
      } else if(type==='raster'){
        // A single RGBA image stretched across data-coord `extent`. Heavy bytes
        // ride the geom channel (st.raster_geom[id]); fall back to inline. The
        // decoded OffscreenCanvas is cached on the set so view-only redraws blit
        // without re-decoding. The clip block above already scoped any sector.
        const rg = (st.raster_geom && st.raster_geom[ms.id]) || ms;
        const b64 = rg.image_b64 || '';
        const iw = rg.image_width|0, ih = rg.image_height|0;
        if(b64 && iw>0 && ih>0){
          if(ms._rasterKey!==b64 || !ms._rasterBmp){
            try{
              const bin=atob(b64);
              const bytes=new Uint8ClampedArray(bin.length);
              for(let i=0;i<bin.length;i++) bytes[i]=bin.charCodeAt(i);
              const imgData=new ImageData(bytes, iw, ih);
              const oc=new OffscreenCanvas(iw,ih);
              oc.getContext('2d').putImageData(imgData,0,0);
              ms._rasterBmp=oc; ms._rasterKey=b64;
            }catch(_){ ms._rasterBmp=null; }
          }
          const ext=ms.extent||[0,1,0,1];
          const [ax2,ay2]= tfm==='data' ? _offToCanvas([ext[0],ext[2]]) : _tc2d(ext[0],ext[2]);
          const [bx2,by2]= tfm==='data' ? _offToCanvas([ext[1],ext[3]]) : _tc2d(ext[1],ext[3]);
          if(ms._rasterBmp){
            mkCtx.save();
            // Nearest-neighbour by default (crisp cells); smoothing bilinearly
            // interpolates for a smooth heat field (ms.smooth === true).
            mkCtx.imageSmoothingEnabled = ms.smooth === true;
            if(ms.smooth === true) mkCtx.imageSmoothingQuality = 'high';
            mkCtx.drawImage(ms._rasterBmp, 0,0,iw,ih,
              Math.min(ax2,bx2), Math.min(ay2,by2),
              Math.abs(bx2-ax2), Math.abs(by2-ay2));
            mkCtx.restore();
          }
        }
      } else if(type==='arrows'){
        const HL=8;
        for(let i=0;i<ms.offsets.length;i++){
          const off=ms.offsets[i];
          const [x1a,y1a]= tfm==='data' ? _offToCanvas(off) : _tc2d(off[0],off[1]!=null?off[1]:0);
          const u=ms.U[i]||0, v=ms.V[i]||0;
          const x2a= tfm==='data' ? _xPx(off[0]+u) : x1a+u;
          const y2a= tfm==='data' ? _yPx((off[1]||0)+v) : y1a+v;
          const ang=Math.atan2(y2a-y1a,x2a-x1a);
          mkCtx.beginPath();mkCtx.moveTo(x1a,y1a);mkCtx.lineTo(x2a,y2a);mkCtx.stroke();
          mkCtx.beginPath();mkCtx.moveTo(x2a,y2a);
          mkCtx.lineTo(x2a-HL*Math.cos(ang-Math.PI/6),y2a-HL*Math.sin(ang-Math.PI/6));
          mkCtx.lineTo(x2a-HL*Math.cos(ang+Math.PI/6),y2a-HL*Math.sin(ang+Math.PI/6));
          mkCtx.closePath();mkCtx.fill();
        }
      } else if(type==='texts'){
        const fs=ms.fontsize||12;
        mkCtx.font=`${fs}px sans-serif`;mkCtx.textAlign='left';mkCtx.textBaseline='top';
        for(let i=0;i<ms.offsets.length;i++){
          const [px,py]= tfm==='data' ? _offToCanvas(ms.offsets[i]) : _tc2d(ms.offsets[i][0],ms.offsets[i][1]!=null?ms.offsets[i][1]:0);
          mkCtx.fillText(String((ms.texts&&ms.texts[i])||''),px,py);
        }
      }
      mkCtx.restore();
    }
    mkCtx.restore();
  }

  // Returns {lineId, canvasPx, canvasPy, x, y} for the line closest to (mx,my),
  // or null if nothing is within HIT px.
  // lineId: null = primary line, string = extra-line id.
  function _lineHitTest1d(mx, my, p) {
    const st = p.state; if (!st) return null;
    const r = _plotRect1d(p);
    if (mx < r.x || mx > r.x+r.w || my < r.y || my > r.y+r.h) return null;
    const xArr = p._1dXArr || (st.x_axis_b64 ? _decodeF64(st.x_axis_b64) : (st.x_axis||[]));
    const x0 = st.view_x0||0, x1 = st.view_x1||1;
    const dMin = st.data_min, dMax = st.data_max;
    const HIT = 6;

    function _nearestOnLine(yData, lineXArr, lineId) {
      if (!yData || yData.length < 2) return null;
      const n = yData.length;
      const span = lineXArr.length >= 2 ? (lineXArr[lineXArr.length-1] - lineXArr[0]) || 1 : (n-1)||1;
      let bestDist = HIT + 1, bx = null, by = null;
      for (let i = 0; i < n - 1; i++) {
        const f0 = lineXArr.length >= 2 ? (lineXArr[i]   - lineXArr[0]) / span : i   / ((n-1)||1);
        const f1 = lineXArr.length >= 2 ? (lineXArr[i+1] - lineXArr[0]) / span : (i+1) / ((n-1)||1);
        const px0 = _fracToPx1d(f0, x0, x1, r), py0 = _valToPy1d(yData[i],   dMin, dMax, r);
        const px1 = _fracToPx1d(f1, x0, x1, r), py1 = _valToPy1d(yData[i+1], dMin, dMax, r);
        const dx = px1-px0, dy = py1-py0, lenSq = dx*dx+dy*dy;
        const t  = lenSq > 0 ? Math.max(0, Math.min(1, ((mx-px0)*dx+(my-py0)*dy)/lenSq)) : 0;
        const nx = px0+t*dx, ny = py0+t*dy;
        const d  = Math.hypot(mx-nx, my-ny);
        if (d < bestDist) { bestDist = d; bx = nx; by = ny; }
      }
      if (bx === null) return null;
      // Convert canvas best-point back to data coords
      const frac = _canvasXToFrac1d(bx, x0, x1, r);
      const physX = lineXArr.length >= 2 ? _axisFracToVal(lineXArr, frac) : frac;
      const physY = dMin + (r.y + r.h - by) / (r.h||1) * (dMax - dMin);
      return { lineId, canvasPx: bx, canvasPy: by, x: physX, y: physY };
    }

    // Check extra lines first (drawn on top), then primary
    for (let i = (st.extra_lines||[]).length - 1; i >= 0; i--) {
      const ex = st.extra_lines[i];
      const exY = ex.data_b64   ? _decodeF64(ex.data_b64)   : (ex.data   || []);
      const exX = ex.x_axis_b64 ? _decodeF64(ex.x_axis_b64) : (ex.x_axis ? ex.x_axis : xArr);
      const hit = _nearestOnLine(exY, exX, ex.id);
      if (hit) return hit;
    }
    const primY = p._1dDArr || (st.data_b64 ? _decodeF64(st.data_b64) : (st.data||[]));
    return _nearestOnLine(primY, xArr, null);
  }

  // ── marker hit-test helpers ────────────────────────────────────────────────
  const MARKER_HIT = 8;

  // Returns {si, i, collectionLabel, markerLabel} or null.
  // si/i identify the set/marker for hover; labels are for tooltips (null if unset).
  function _markerHitTest2d(mx, my, st, pw, ph) {
    const sets = st.markers || [];
    const scale = _imgScale2d(st, pw, ph);
    const vr = _imgVisibleRect2d(st, pw, ph);
    for (let si = sets.length-1; si >= 0; si--) {
      const ms = sets[si];
      const type = ms.type || 'circles';
      const tfm = ms.transform || 'data';
      const clipSet = tfm !== 'display' || ms.clip_display !== false;
      if (clipSet && (mx < vr.x || mx > vr.x + vr.w || my < vr.y || my > vr.y + vr.h)) {
        continue;
      }
      const collLabel = ms.label != null ? String(ms.label) : null;
      const perLabels = Array.isArray(ms.labels) ? ms.labels : null;
      let _tc;
      if(tfm==='axes'){
        const fr=_imgFitRect(st.image_width,st.image_height,pw,ph);
        _tc=(fx,fy)=>[fr.x+fx*fr.w, fr.y+(1-fy)*fr.h];
      } else if(tfm==='display'){
        _tc=(ix,iy)=>[ix,iy];
      } else {
        _tc=(ix,iy)=>_imgToCanvas2d(ix,iy,st,pw,ph);
      }
      const scl = tfm==='data' ? scale : 1;
      if (type === 'circles') {
        for (let i=0;i<(ms.offsets||[]).length;i++) {
          const [cx,cy]=_tc(ms.offsets[i][0],ms.offsets[i][1]);
          const r=Math.max(1,(ms.sizes[i]!=null?ms.sizes[i]:ms.sizes[0]||5)*scl);
          if(Math.sqrt((mx-cx)**2+(my-cy)**2)<=r+MARKER_HIT)
            return{si,i,collectionLabel:collLabel,markerLabel:perLabels?String(perLabels[i]??''):null};
        }
      } else if (type === 'ellipses') {
        for (let i=0;i<(ms.offsets||[]).length;i++) {
          const [cx,cy]=_tc(ms.offsets[i][0],ms.offsets[i][1]);
          const rw=(ms.widths[i]||ms.widths[0]||10)*scl/2+MARKER_HIT;
          const rh=(ms.heights[i]||ms.heights[0]||10)*scl/2+MARKER_HIT;
          const dx=(mx-cx)/Math.max(1,rw), dy=(my-cy)/Math.max(1,rh);
          if(dx*dx+dy*dy<=1.0)
            return{si,i,collectionLabel:collLabel,markerLabel:perLabels?String(perLabels[i]??''):null};
        }
      } else if (type === 'rectangles' || type === 'squares') {
        const heights = type==='squares' ? ms.widths : ms.heights;
        for (let i=0;i<(ms.offsets||[]).length;i++) {
          const [cx,cy]=_tc(ms.offsets[i][0],ms.offsets[i][1]);
          const hw=(ms.widths[i]||ms.widths[0]||20)*scl/2+MARKER_HIT;
          const hh=((heights[i]||heights[0]||20))*scl/2+MARKER_HIT;
          if(Math.abs(mx-cx)<=hw&&Math.abs(my-cy)<=hh)
            return{si,i,collectionLabel:collLabel,markerLabel:perLabels?String(perLabels[i]??''):null};
        }
      } else if (type === 'arrows') {
        for (let i=0;i<(ms.offsets||[]).length;i++) {
          const [x1,y1]=_tc(ms.offsets[i][0],ms.offsets[i][1]);
          const mx2=x1+(ms.U[i]||0)*scl/2, my2=y1+(ms.V[i]||0)*scl/2;
          if(Math.sqrt((mx-mx2)**2+(my-my2)**2)<=MARKER_HIT*2)
            return{si,i,collectionLabel:collLabel,markerLabel:perLabels?String(perLabels[i]??''):null};
        }
      } else if (type === 'lines') {
        for (let i=0;i<(ms.segments||[]).length;i++) {
          const seg=ms.segments[i];
          const [x1,y1]=_tc(seg[0][0],seg[0][1]);
          const [x2,y2]=_tc(seg[1][0],seg[1][1]);
          const dx=x2-x1,dy=y2-y1,len2=dx*dx+dy*dy;
          const t=len2>0?Math.max(0,Math.min(1,((mx-x1)*dx+(my-y1)*dy)/len2)):0;
          if(Math.sqrt((mx-(x1+t*dx))**2+(my-(y1+t*dy))**2)<=MARKER_HIT)
            return{si,i,collectionLabel:collLabel,markerLabel:perLabels?String(perLabels[i]??''):null};
        }
      } else if (type === 'polygons') {
        for (let i=0;i<(ms.vertices_list||[]).length;i++) {
          const verts=ms.vertices_list[i]; if(!verts||!verts.length) continue;
          const [cx,cy]=_tc(verts[0][0],verts[0][1]);
          if(Math.sqrt((mx-cx)**2+(my-cy)**2)<=MARKER_HIT*1.5)
            return{si,i,collectionLabel:collLabel,markerLabel:perLabels?String(perLabels[i]??''):null};
        }
      } else if (type === 'texts') {
        for (let i=0;i<(ms.offsets||[]).length;i++) {
          const [cx,cy]=_tc(ms.offsets[i][0],ms.offsets[i][1]);
          if(Math.sqrt((mx-cx)**2+(my-cy)**2)<=MARKER_HIT*1.5)
            return{si,i,collectionLabel:collLabel,markerLabel:perLabels?String(perLabels[i]??''):null};
        }
      }
    }
    return null;
  }

  function _markerHitTest1d(mx, my, p) {
    const st=p.state; if(!st) return null;
    const r=_plotRect1d(p);
    // Use cached decoded array from draw1d; fall back to inline decode if needed.
    const xArr = p._1dXArr || (st.x_axis_b64 ? _decodeF64(st.x_axis_b64) : (st.x_axis||[]));
    const x0=st.view_x0||0, x1=st.view_x1||1;
    const dMin=st.data_min, dMax=st.data_max;
    const sets=st.markers||[];
    for(let si=sets.length-1;si>=0;si--){
      const ms=sets[si];
      const collLabel=ms.label!=null?String(ms.label):null;
      const perLabels=Array.isArray(ms.labels)?ms.labels:null;
      if(ms.type==='points'){
        for(let i=0;i<(ms.offsets||[]).length;i++){
          const frac=xArr.length>=2?_axisValToFrac(xArr,ms.offsets[i][0]):0;
          const px=_fracToPx1d(frac,x0,x1,r);
          const sz=Math.max(1,ms.sizes[i]!=null?ms.sizes[i]:ms.sizes[0]||5);
          if(Math.sqrt((mx-px)**2+(my-r.y-r.h/2)**2)<=sz+MARKER_HIT)
            return{si,i,collectionLabel:collLabel,markerLabel:perLabels?String(perLabels[i]??''):null};
        }
      } else if(ms.type==='vlines'){
        for(let i=0;i<(ms.offsets||[]).length;i++){
          const px=_fracToPx1d(xArr.length>=2?_axisValToFrac(xArr,ms.offsets[i][0]):0,x0,x1,r);
          if(Math.abs(mx-px)<=MARKER_HIT&&my>=r.y&&my<=r.y+r.h)
            return{si,i,collectionLabel:collLabel,markerLabel:perLabels?String(perLabels[i]??''):null};
        }
      } else if(ms.type==='hlines'){
        for(let i=0;i<(ms.offsets||[]).length;i++){
          const py=_valToPy1d(ms.offsets[i][0],dMin,dMax,r);
          if(Math.abs(my-py)<=MARKER_HIT&&mx>=r.x&&mx<=r.x+r.w)
            return{si,i,collectionLabel:collLabel,markerLabel:perLabels?String(perLabels[i]??''):null};
        }
      } else if(ms.type==='lines'){
        for(let i=0;i<(ms.segments||[]).length;i++){
          const seg=ms.segments[i];
          const xf1=xArr.length>=2?_axisValToFrac(xArr,seg[0][0]):0;
          const xf2=xArr.length>=2?_axisValToFrac(xArr,seg[1][0]):0;
          const x1c=_fracToPx1d(xf1,x0,x1,r),y1c=_valToPy1d(seg[0][1],dMin,dMax,r);
          const x2c=_fracToPx1d(xf2,x0,x1,r),y2c=_valToPy1d(seg[1][1],dMin,dMax,r);
          const dx=x2c-x1c,dy=y2c-y1c,len2=dx*dx+dy*dy;
          const t=len2>0?Math.max(0,Math.min(1,((mx-x1c)*dx+(my-y1c)*dy)/len2)):0;
          if(Math.sqrt((mx-(x1c+t*dx))**2+(my-(y1c+t*dy))**2)<=MARKER_HIT)
            return{si,i,collectionLabel:collLabel,markerLabel:perLabels?String(perLabels[i]??''):null};
        }
      }
    }
    return null;
  }

  // ── touch input bridge ────────────────────────────────────────────────────
  // Touch devices (iPad / iPhone) emit touch* events, not mouse* — but every
  // panel handler is written against mouse events.  Rather than rewrite ~20
  // handlers per kind, we translate touch gestures into the synthetic mouse /
  // wheel events those handlers already understand, attached once per panel:
  //
  //   1 finger  drag   → mousedown / mousemove / mouseup  (pan, orbit, drag a
  //                       widget / ROI / marker / plane — whatever's under it)
  //   2 fingers pinch  → wheel (zoom), centred on the gesture midpoint
  //   double-tap       → dblclick → the panel's double_click event (picking /
  //                       app callbacks), exactly as a mouse double-click
  //
  // A synthetic event carries exactly the fields the handlers read:
  // clientX/Y, button, buttons, the modifier flags (always false for touch),
  // and a no-op preventDefault.  document-level mousemove/up listeners in the
  // handlers receive the synthetic move/up too, so drags that start on the
  // canvas and continue off it work just like a mouse.
  // Dispatch a real MouseEvent so it reaches every listener (including the
  // document-level mousemove/mouseup the handlers use for off-canvas drags).
  // Native MouseEvent carries clientX/Y, button, buttons and false modifiers —
  // exactly what _clientPos / _pointerFields / _modifiers read.
  function _dispatchMouse(target, type, clientX, clientY) {
    target.dispatchEvent(new MouseEvent(type, {
      clientX, clientY, button: 0,
      buttons: type === 'mouseup' ? 0 : 1,
      bubbles: true, cancelable: true, view: window,
    }));
  }

  // Dispatch a real WheelEvent (pinch → zoom).  dir = -1 zoom in, +1 zoom out
  // (matches the handlers' deltaY sign convention).
  function _dispatchWheel(target, clientX, clientY, dir) {
    target.dispatchEvent(new WheelEvent('wheel', {
      clientX, clientY, deltaY: dir * 100, deltaX: 0,
      bubbles: true, cancelable: true, view: window,
    }));
  }

  function _attachTouch(p) {
    const oc = p.overlayCanvas;
    if (!oc || oc._touchBridged) return;
    oc._touchBridged = true;

    let mode = null;            // null | 'drag' | 'pinch'
    let pinchStartDist = 0;
    let lastTapTime = 0, lastTapX = 0, lastTapY = 0;

    const dist = (t0, t1) =>
      Math.hypot(t0.clientX - t1.clientX, t0.clientY - t1.clientY);
    const mid = (t0, t1) => ({
      x: (t0.clientX + t1.clientX) / 2, y: (t0.clientY + t1.clientY) / 2 });

    oc.addEventListener('touchstart', (e) => {
      if (e.touches.length === 1) {
        mode = 'drag';
        const t = e.touches[0];
        _dispatchMouse(oc, 'mousedown', t.clientX, t.clientY);
        e.preventDefault();
      } else if (e.touches.length === 2) {
        // Switching into a pinch — end any single-finger drag cleanly first.
        if (mode === 'drag') {
          const t = e.touches[0];
          _dispatchMouse(document, 'mouseup', t.clientX, t.clientY);
        }
        mode = 'pinch';
        pinchStartDist = dist(e.touches[0], e.touches[1]);
        e.preventDefault();
      }
    }, { passive: false });

    oc.addEventListener('touchmove', (e) => {
      if (mode === 'drag' && e.touches.length >= 1) {
        const t = e.touches[0];
        _dispatchMouse(document, 'mousemove', t.clientX, t.clientY);
        e.preventDefault();
      } else if (mode === 'pinch' && e.touches.length >= 2) {
        const d = dist(e.touches[0], e.touches[1]);
        const m = mid(e.touches[0], e.touches[1]);
        // Quantise into wheel steps; spread (d>start) zooms IN (deltaY<0).
        const ratio = d / (pinchStartDist || d);
        if (Math.abs(ratio - 1) > 0.02) {
          // Update mouse position so wheel-zoom anchors at the pinch centre.
          const { mx, my } = _clientPos({ clientX: m.x, clientY: m.y },
                                        oc, p.pw, p.ph);
          p.mouseX = mx; p.mouseY = my;
          _dispatchWheel(oc, m.x, m.y, ratio > 1 ? -1 : 1);
          pinchStartDist = d;   // incremental — each move is one small step
        }
        e.preventDefault();
      }
    }, { passive: false });

    const endTouch = (e) => {
      if (mode === 'drag') {
        const t = (e.changedTouches && e.changedTouches[0]) || { clientX: 0, clientY: 0 };
        _dispatchMouse(document, 'mouseup', t.clientX, t.clientY);
        // Double-tap detection (only for a tap, not a drag-release): a quick
        // second tap near the first fires dblclick → reset view.
        const now = performance.now();
        if (now - lastTapTime < 300 &&
            Math.hypot(t.clientX - lastTapX, t.clientY - lastTapY) < 30) {
          _dispatchMouse(oc, 'dblclick', t.clientX, t.clientY);
          lastTapTime = 0;
        } else {
          lastTapTime = now; lastTapX = t.clientX; lastTapY = t.clientY;
        }
      }
      // If fingers remain (pinch→1 finger), restart a drag from the survivor.
      if (e.touches && e.touches.length === 1) {
        mode = 'drag';
        const t = e.touches[0];
        _dispatchMouse(oc, 'mousedown', t.clientX, t.clientY);
      } else if (!e.touches || e.touches.length === 0) {
        mode = null;
      }
      if (e.cancelable) e.preventDefault();
    };
    oc.addEventListener('touchend', endTouch, { passive: false });
    oc.addEventListener('touchcancel', endTouch, { passive: false });
  }

  // ── panel-level event handlers ───────────────────────────────────────────
  function _attachPanelEvents(p) {
    if (p.kind === '2d')  _attachEvents2d(p);
    else if (p.kind === '3d')  _attachEvents3d(p);
    else if (p.kind === 'bar') _attachEventsBar(p);
    else                       _attachEvents1d(p);
    _attachTouch(p);   // touch bridge — translates gestures to mouse/wheel
  }

  function _canvasToImg2d(px, py, st, pw, ph) {
    const { x, y, w, h } = _imgFitRect(st.image_width, st.image_height, pw, ph);
    const zoom = st.zoom, cx = st.center_x, cy = st.center_y;
    const iw = st.image_width, ih = st.image_height;
    if (zoom < 1.0) {
      // Zoom-out path: inverse of the centred-shrink in _blit2d.
      const dstW = w * zoom, dstH = h * zoom;
      const dstX = x + (w - dstW) / 2, dstY = y + (h - dstH) / 2;
      return [(px - dstX) / dstW * iw, (py - dstY) / dstH * ih];
    }
    const visW = iw / zoom, visH = ih / zoom;
    const srcX = Math.max(0, Math.min(iw - visW, cx * iw - visW / 2));
    const srcY = Math.max(0, Math.min(ih - visH, cy * ih - visH / 2));
    return [srcX + (px - x) / w * visW, srcY + (py - y) / h * visH];
  }

  function _attachEvents2d(p) {
    const { overlayCanvas } = p;
    let localOnly = false;
    const _scheduleCommit = _makeCommitter(() => {
      localOnly = true; model.save_changes(); setTimeout(() => { localOnly = false; }, 200);
    });
    const settled = _makeSettledScheduler(p);

    // Wheel zoom — anchored on the image point under the cursor
    overlayCanvas.addEventListener('wheel',(e)=>{
      e.preventDefault();
      const st=p.state; if(!st) return;
      const imgW=p.imgW||Math.max(1,p.pw-PAD_L-PAD_R), imgH=p.imgH||Math.max(1,p.ph-PAD_T-PAD_B);
      const newZ=Math.max(0.75,Math.min(100,st.zoom*(e.deltaY>0?0.9:1.1)));
      if(!st.tile_enabled){
        // NON-tiled image: anchor the zoom on the cursor (the image point under the
        // cursor stays put) — there's no detail-tile fetch to disagree with it.
        const {mx,my}=_clientPos(e,overlayCanvas,imgW,imgH);
        const [anchorX,anchorY]=_canvasToImg2d(mx,my,st,imgW,imgH);
        st.zoom=newZ;
        const iw=st.image_width, ih=st.image_height;
        const fr=_imgFitRect(iw,ih,imgW,imgH);
        const newVisW=iw/newZ, newVisH=ih/newZ;
        const newSrcX=anchorX-(mx-fr.x)/fr.w*newVisW;
        const newSrcY=anchorY-(my-fr.y)/fr.h*newVisH;
        st.center_x=Math.max(0,Math.min(1,(newSrcX+newVisW/2)/iw));
        st.center_y=Math.max(0,Math.min(1,(newSrcY+newVisH/2)/ih));
      } else {
        // TILE mode: zoom about the CURRENT CENTER, not the cursor. Cursor-anchored
        // zoom looked right DURING the wheel (base blit re-anchored to the cursor),
        // but when the debounced detail-tile fetch landed it re-derived the visible
        // window from center_x/center_y — a different anchor — so the image visibly
        // JUMPED. Center-zoom makes the base blit + detail tile agree at every zoom.
        st.zoom=newZ;
      }
      draw2d(p);
      _propagateZoom2d(p);
      model.set(`panel_${p.id}_json`, _viewStateJson(p));
      _emitViewChanged(p);   // debounced → fetch a hi-res detail tile on zoom settle
      _scheduleCommit();
    },{passive:false});

    // Pan + widget drag
    let panStart={};
    overlayCanvas.addEventListener('mousedown',(e)=>{
      if(e.button!==0) return;
      const st=p.state; if(!st) return;
      overlayCanvas.focus();
      const imgW=p.imgW||Math.max(1,p.pw-PAD_L-PAD_R), imgH=p.imgH||Math.max(1,p.ph-PAD_T-PAD_B);
      const {mx,my}=_clientPos(e,overlayCanvas,imgW,imgH);
      const hit=_ovHitTest2d(mx, my, p);
      if(hit){
        p.ovDrag2d=hit;
        p.lastWidgetId=(st.overlay_widgets||[])[hit.idx]?.id||null;
        overlayCanvas.style.cursor='move';
        e.preventDefault(); return;
      }
      // Store pan start in canvas-pixel coords so the drag delta is also
      // in canvas-pixel space and matches fr.w/fr.h (both canvas-pixel).
      panStart={mx,my,cx:st.center_x,cy:st.center_y};
      // Track potential click: distance + time guards distinguish click from pan.
      p.clickCandidate={mx,my,t:Date.now(),shiftKey:e.shiftKey};
      p.isPanning=true; overlayCanvas.style.cursor='grabbing';
      // Do NOT call e.preventDefault() here: Chrome suppresses the click event
      // when mousedown is cancelled, which in turn prevents dblclick from firing.
      // Panning's preventDefault lives in the mousemove handler (prevents scroll).
    });
    document.addEventListener('mousemove',(e)=>{
      if(p.ovDrag2d){
        _doDrag2d(e,p);
        const _dw=(p.state.overlay_widgets||[])[p.ovDrag2d.idx]||{};
        _emitEvent(p.id,'pointer_move',_dw.id||null,{..._dw,..._pointerFields(e)});
        return;
      }
      if(!p.isPanning) return;
      const st=p.state; if(!st) return;
      const imgW=p.imgW||Math.max(1,p.pw-PAD_L-PAD_R), imgH=p.imgH||Math.max(1,p.ph-PAD_T-PAD_B);
      const fr=_imgFitRect(st.image_width,st.image_height,imgW,imgH);
      const z=st.zoom;
      const {mx:cmx,my:cmy}=_clientPos(e,overlayCanvas,imgW,imgH);
      // Invalidate click candidate once the cursor has clearly moved (>4 px).
      if(p.clickCandidate){const _dx=cmx-p.clickCandidate.mx,_dy=cmy-p.clickCandidate.my;if(_dx*_dx+_dy*_dy>16)p.clickCandidate=null;}
      localOnly=true;
      st.center_x=Math.max(0,Math.min(1,panStart.cx-(cmx-panStart.mx)/fr.w/z));
      st.center_y=Math.max(0,Math.min(1,panStart.cy-(cmy-panStart.my)/fr.h/z));
      draw2d(p);
      _propagateZoom2d(p);
      model.set(`panel_${p.id}_json`, _viewStateJson(p));
      _scheduleCommit(); e.preventDefault();
    });
    document.addEventListener('mouseup',(e)=>{
      settled.clear();
      if(p.ovDrag2d){
        const _idx=p.ovDrag2d.idx;
        const _dw=(p.state.overlay_widgets||[])[_idx]||{};
        const _did=_dw.id||null;
        p.ovDrag2d=null; overlayCanvas.style.cursor='default';
        model.set(`panel_${p.id}_json`, _viewStateJson(p));
        _emitEvent(p.id,'pointer_up',_did,{..._dw,..._pointerFields(e),button:e.button});
        return;
      }
      if(!p.isPanning) return;
      p.isPanning=false; overlayCanvas.style.cursor='default';
      const st=p.state; if(!st) return;
      const imgW=p.imgW||Math.max(1,p.pw-PAD_L-PAD_R), imgH=p.imgH||Math.max(1,p.ph-PAD_T-PAD_B);
      const fr=_imgFitRect(st.image_width,st.image_height,imgW,imgH);
      const {mx:cmx,my:cmy}=_clientPos(e,overlayCanvas,imgW,imgH);
      // ── Click detection: short-duration + small-movement mousedown/up ────────
      // Criteria: candidate still alive (not cleared by mousemove) AND ≤300 ms.
      // We also re-check final distance as a safety net for document-level moves
      // that didn't fire our mousemove guard (e.g. rapid trackpad flicks).
      if(p.clickCandidate){
        const _cc=p.clickCandidate; p.clickCandidate=null;
        const _dx=cmx-_cc.mx, _dy=cmy-_cc.my;
        const _dist2=_dx*_dx+_dy*_dy;
        const _dt=Date.now()-_cc.t;
        if(_dist2<=25&&_dt<=350){
          // Genuine click — skip pan-settle, emit pointer_down with image coords.
          const [imgX,imgY]=_canvasToImg2d(_cc.mx,_cc.my,st,imgW,imgH);
          const xArr=st.x_axis||[], yArr=st.y_axis||[];
          const _iw=st.image_width||1, _ih=st.image_height||1;
          const physX=xArr.length>=2?_axisFracToVal(xArr,imgX/_iw):imgX;
          const physY=yArr.length>=2?_axisFracToVal(yArr,imgY/_ih):imgY;
          _emitEvent(p.id,'pointer_down',null,{
            img_x:imgX, img_y:imgY,
            xdata:physX, ydata:physY,
            x:_cc.mx, y:_cc.my,
            ..._pointerFields(e),
            button:e.button,
          });
          // _emitEvent already calls model.save_changes() — no duplicate needed.
          return;
        }
      }
      // ── Normal pan settle ───────────────────────────────────────────────────
      st.center_x=Math.max(0,Math.min(1,panStart.cx-(cmx-panStart.mx)/fr.w/st.zoom));
      st.center_y=Math.max(0,Math.min(1,panStart.cy-(cmy-panStart.my)/fr.h/st.zoom));
      model.set(`panel_${p.id}_json`, _viewStateJson(p));
      _emitEvent(p.id,'pointer_up',null,{center_x:st.center_x,center_y:st.center_y,zoom:st.zoom,..._pointerFields(e),button:e.button});
      _emitViewChanged(p);   // pan settled → refresh the detail tile for the new view
      model.save_changes();
    });

    // Status bar + tooltip + widget hover cursor
    overlayCanvas.addEventListener('mousemove',(e)=>{
      const imgW=p.imgW||Math.max(1,p.pw-PAD_L-PAD_R), imgH=p.imgH||Math.max(1,p.ph-PAD_T-PAD_B);
      const {mx,my}=_clientPos(e,overlayCanvas,imgW,imgH);
      p.mouseX=mx; p.mouseY=my;
      if(p.ovDrag2d) return; // handled by document mousemove
      const st=p.state; if(!st) return;

      // Update cursor based on widget hit
      const whit=_ovHitTest2d(mx, my, p);
      if(whit){
        const m=whit.mode;
        overlayCanvas.style.cursor = m==='move' ? 'move'
          : (m==='resize_br'||m==='resize_tl') ? 'nwse-resize'
          : (m==='resize_bl'||m==='resize_tr') ? 'nesw-resize'
          : (m==='resize_r'||m==='resize_ir')  ? 'ew-resize'
          : (m==='resize_head'||m==='resize_tail') ? 'crosshair'
          : m.startsWith('vertex_')            ? 'crosshair'
          : 'move';
      } else if(!p.isPanning){
        overlayCanvas.style.cursor='default';
      }

      const [ix,iy]=_canvasToImg2d(mx,my,st,imgW,imgH);
      if(ix>=0&&ix<st.image_width&&iy>=0&&iy<st.image_height){
        const xArr=st.x_axis||[], yArr=st.y_axis||[];
        const iw=st.image_width, ih=st.image_height;
        // For both imshow (centre arrays) and pcolormesh (edge arrays),
        // ix/iw maps the pixel fraction into the axis array via binary search.
        const physX=xArr.length>=2?_axisFracToVal(xArr,ix/iw):ix;
        const physY=yArr.length>=2?_axisFracToVal(yArr,iy/ih):iy;
        const units=st.units||'px';
        const showPhys=xArr.length>=2||yArr.length>=2;
        p.statusBar.textContent = showPhys
          ? `x:${fmtVal(physX)} y:${fmtVal(physY)}${units?' '+units:''}  [${Math.floor(ix)}, ${Math.floor(iy)}]`
          : `x:${Math.floor(ix)}  y:${Math.floor(iy)}`;
        p.statusBar.style.display='block';
        const mhit=_markerHitTest2d(mx,my,st,imgW,imgH);
        const newSi=mhit?mhit.si:-1;
        if(newSi!==p._hoverSi){
          p._hoverSi=newSi; p._hoverI=mhit?mhit.i:-1;
          drawMarkers2d(p, mhit?{si:newSi}:null);
        }
        if(mhit&&(mhit.collectionLabel||mhit.markerLabel)){const parts=[];if(mhit.collectionLabel)parts.push(mhit.collectionLabel);if(mhit.markerLabel)parts.push(mhit.markerLabel);_showTooltip(parts.join('\n'),e.clientX,e.clientY);settled.clear();return;}
        tooltip.style.display='none';
      } else { p.statusBar.style.display='none'; tooltip.style.display='none';
        if(p._hoverSi!==-1){p._hoverSi=-1;p._hoverI=-1;drawMarkers2d(p,null);}
      }
      settled.arm(mx, my, e, () => {
        const st2 = p.state; if (!st2) return {};
        const imgW2 = p.imgW || Math.max(1, p.pw - PAD_L - PAD_R);
        const imgH2 = p.imgH || Math.max(1, p.ph - PAD_T - PAD_B);
        const [sImgX, sImgY] = _canvasToImg2d(p.mouseX, p.mouseY, st2, imgW2, imgH2);
        const sXArr = st2.x_axis || [], sYArr = st2.y_axis || [];
        const _siw = st2.image_width || 1, _sih = st2.image_height || 1;
        return {
          img_x:  sImgX, img_y:  sImgY,
          xdata:  sXArr.length >= 2 ? _axisFracToVal(sXArr, sImgX / _siw) : sImgX,
          ydata:  sYArr.length >= 2 ? _axisFracToVal(sYArr, sImgY / _sih) : sImgY,
        };
      });
    });
    overlayCanvas.addEventListener('mouseleave',(e)=>{
      settled.clear();
      _emitEvent(p.id,'pointer_leave',null,{..._pointerFields(e),x:e.offsetX,y:e.offsetY});
      p.statusBar.style.display='none';tooltip.style.display='none';
      if(p._hoverSi!==-1){p._hoverSi=-1;p._hoverI=-1;drawMarkers2d(p,null);}
    });
    overlayCanvas.addEventListener('dblclick',(e)=>{
      const st=p.state; if(!st) return;
      const imgW=p.imgW||Math.max(1,p.pw-PAD_L-PAD_R), imgH=p.imgH||Math.max(1,p.ph-PAD_T-PAD_B);
      const {mx,my}=_clientPos(e,overlayCanvas,imgW,imgH);
      const [imgX,imgY]=_canvasToImg2d(mx,my,st,imgW,imgH);
      const xArr=st.x_axis||[], yArr=st.y_axis||[];
      const _iw=st.image_width||1, _ih=st.image_height||1;
      const physX=xArr.length>=2?_axisFracToVal(xArr,imgX/_iw):imgX;
      const physY=yArr.length>=2?_axisFracToVal(yArr,imgY/_ih):imgY;
      _emitEvent(p.id,'double_click',null,{..._pointerFields(e),button:e.button,x:mx,y:my,img_x:imgX,img_y:imgY,xdata:physX,ydata:physY});
    });
    overlayCanvas.addEventListener('wheel',(e)=>{
      _emitEvent(p.id,'wheel',null,{
        time_stamp:performance.now()/1000,
        modifiers:_modifiers(e),
        x:p.mouseX??0, y:p.mouseY??0,
        dx:e.deltaX, dy:e.deltaY,
      });
    },{passive:true});

    // Keyboard shortcuts
    // Built-ins: r=reset zoom, c=colorbar toggle, l=log scale, s=symlog scale.
    // All keys are forwarded to Python unconditionally.
    overlayCanvas.addEventListener('keydown',(e)=>{
      const st=p.state; if(!st) return;
      const imgW=p.imgW||Math.max(1,p.pw-PAD_L-PAD_R), imgH=p.imgH||Math.max(1,p.ph-PAD_T-PAD_B);
      const [imgX,imgY]=_canvasToImg2d(p.mouseX,p.mouseY,st,imgW,imgH);
      const xArr=st.x_axis||[], yArr=st.y_axis||[];
      const iw=st.image_width||1, ih=st.image_height||1;
      const physX=xArr.length>=2?_axisFracToVal(xArr,imgX/iw):imgX;
      const physY=yArr.length>=2?_axisFracToVal(yArr,imgY/ih):imgY;
      _emitEvent(p.id,'key_down',null,{
        time_stamp:performance.now()/1000,
        modifiers:_modifiers(e),
        key:e.key,
        last_widget_id:p.lastWidgetId||null,
        x:p.mouseX ?? 0, y:p.mouseY ?? 0,
        img_x:imgX, img_y:imgY,
        xdata:physX, ydata:physY,
      });
      const key=e.key.toLowerCase();
      if(key==='r'){
        st.zoom=1; st.center_x=0.5; st.center_y=0.5;
        draw2d(p); model.set(`panel_${p.id}_json`,_viewStateJson(p)); model.save_changes();
        e.stopPropagation(); e.preventDefault();
      } else if(key==='c'){
        st.show_colorbar=!st.show_colorbar;
        draw2d(p);
        model.set(`panel_${p.id}_json`,_viewStateJson(p)); model.save_changes();
        e.stopPropagation(); e.preventDefault();
      } else if(key==='l'){
        st.scale_mode=st.scale_mode==='log'?'linear':'log';
        draw2d(p); model.set(`panel_${p.id}_json`,_viewStateJson(p)); model.save_changes();
        e.stopPropagation(); e.preventDefault();
      } else if(key==='s'){
        st.scale_mode=st.scale_mode==='symlog'?'linear':'symlog';
        draw2d(p); model.set(`panel_${p.id}_json`,_viewStateJson(p)); model.save_changes();
        e.stopPropagation(); e.preventDefault();
      }
    });
    overlayCanvas.addEventListener('keyup',(e)=>{
      _emitEvent(p.id,'key_up',null,{
        time_stamp:performance.now()/1000,
        modifiers:_modifiers(e),
        key:e.key,
        x:p.mouseX??0, y:p.mouseY??0,
      });
    });
    overlayCanvas.addEventListener('mouseenter',(e)=>{
      overlayCanvas.focus();
      _emitEvent(p.id,'pointer_enter',null,{..._pointerFields(e),x:e.offsetX,y:e.offsetY});
    });
  }

  function _attachEvents1d(p) {
    const { overlayCanvas } = p;
    let localOnly = false;
    const _scheduleCommit = _makeCommitter(() => {
      localOnly = true; model.save_changes(); setTimeout(() => { localOnly = false; }, 200);
    });
    const settled = _makeSettledScheduler(p);

    // Wheel zoom
    overlayCanvas.addEventListener('wheel',(e)=>{
      e.preventDefault();
      const st=p.state; if(!st) return;
      const r=_plotRect1d(p);
      const {mx}=_clientPos(e,overlayCanvas,p.pw,p.ph);
      const frac=_canvasXToFrac1d(mx,st.view_x0,st.view_x1,r);
      const x0=st.view_x0, x1=st.view_x1, span=x1-x0;
      const factor=e.deltaY>0?1.15:0.87;
      let ns=Math.min(1,span*factor);
      let nx0=frac-(frac-x0)*(ns/span), nx1=nx0+ns;
      if(nx0<0){nx0=0;nx1=ns;}if(nx1>1){nx1=1;nx0=1-ns;}
      st.view_x0=nx0;st.view_x1=nx1;
      draw1d(p);
      _propagateView1d(p);
      model.set(`panel_${p.id}_json`,_viewStateJson(p));
      _scheduleCommit();
    },{passive:false});

    // Pan
    let panStart={};
    overlayCanvas.addEventListener('mousedown',(e)=>{
      if(e.button!==0) return;
      const st=p.state; if(!st) return;
      // Store raw client coords for the drag-vs-click threshold (visual pixels
      // are fine for that comparison — both endpoints use the same space).
      p._mousedownX=e.clientX; p._mousedownY=e.clientY;
      const {mx:_emx,my:_emy}=_clientPos(e,overlayCanvas,p.pw,p.ph);
      const hit=_ovHitTest1d(_emx, _emy, p);
      if(hit){p.ovDrag=hit;p.lastWidgetId=(p.state.overlay_widgets||[])[hit.idx]?.id||null;overlayCanvas.style.cursor=(hit.mode==='edge0'||hit.mode==='edge1')?'ew-resize':'move';e.preventDefault();return;}
      // Store pan start in canvas-px so pan delta in mousemove is canvas-px.
      panStart={mx:_emx,x0:st.view_x0,x1:st.view_x1};
      p.isPanning=true;overlayCanvas.style.cursor='grabbing';
      // Do NOT call e.preventDefault() — see 2D note: suppresses click → dblclick.
    });
    document.addEventListener('mousemove',(e)=>{
      if(p.ovDrag){
        _doDrag1d(e,p);
        const _dw=(p.state.overlay_widgets||[])[p.ovDrag.idx]||{};
        _emitEvent(p.id,'pointer_move',_dw.id||null,{..._dw,..._pointerFields(e)});
        return;
      }
      if(!p.isPanning) return;
      const st=p.state; if(!st) return;
      const r=_plotRect1d(p);
      const {mx:cmx}=_clientPos(e,overlayCanvas,p.pw,p.ph);
      const dx=(cmx-panStart.mx)/(r.w||1);
      const span=panStart.x1-panStart.x0;
      let nx0=panStart.x0-dx*span, nx1=panStart.x1-dx*span;
      if(nx0<0){nx0=0;nx1=span;}if(nx1>1){nx1=1;nx0=1-span;}
      st.view_x0=nx0;st.view_x1=nx1;
      draw1d(p);_propagateView1d(p);
      model.set(`panel_${p.id}_json`,_viewStateJson(p));_scheduleCommit();e.preventDefault();
    });
    document.addEventListener('mouseup',(e)=>{
      settled.clear();
      const wasWidgetDragging=!!p.ovDrag;   // capture BEFORE clearing
      const wasDragging=wasWidgetDragging||!!p.isPanning;
      if(p.ovDrag){
        const _idx=p.ovDrag.idx;
        const _dw=(p.state.overlay_widgets||[])[_idx]||{};
        const _did=_dw.id||null;
        p.ovDrag=null; overlayCanvas.style.cursor='crosshair';
        model.set(`panel_${p.id}_json`,_viewStateJson(p));
        _emitEvent(p.id,'pointer_up',_did,{..._dw,..._pointerFields(e),button:e.button});
      }
      if(p.isPanning){
        p.isPanning=false; overlayCanvas.style.cursor='crosshair';
        const st=p.state;
        if(st) _emitEvent(p.id,'pointer_up',null,{view_x0:st.view_x0,view_x1:st.view_x1,..._pointerFields(e),button:e.button});
      }
      // Line click: fire when no widget was being dragged and mouse barely moved.
      // NOTE: p.isPanning is always set true on mousedown (pan start), so we
      // deliberately only block on wasWidgetDragging here — the distance
      // threshold below already excludes real pan gestures.
      if(!wasWidgetDragging && p._mousedownX!=null){
        const mdx=e.clientX-p._mousedownX, mdy=e.clientY-p._mousedownY;
        if(Math.hypot(mdx,mdy)<5){
          const {mx,my}=_clientPos(e,overlayCanvas,p.pw,p.ph);
          const lhit=_lineHitTest1d(mx,my,p);
          if(lhit) _emitEvent(p.id,'pointer_down',null,{line_id:lhit.lineId,x:lhit.x,y:lhit.y,..._pointerFields(e),button:e.button});
        }
      }
      p._mousedownX=null;
    });

    // Keyboard shortcuts
    // Built-in: r=reset view. All keys are forwarded to Python unconditionally.
    overlayCanvas.addEventListener('keydown',(e)=>{
      const st=p.state; if(!st) return;
      const r=_plotRect1d(p);
      const xArr = p._1dXArr || (st.x_axis_b64 ? _decodeF64(st.x_axis_b64) : (st.x_axis||[]));
      const frac=_canvasXToFrac1d(p.mouseX,st.view_x0,st.view_x1,r);
      const physX=xArr.length>=2?_axisFracToVal(xArr,frac):frac;
      _emitEvent(p.id,'key_down',null,{
        time_stamp:performance.now()/1000,
        modifiers:_modifiers(e),
        key:e.key,
        last_widget_id:p.lastWidgetId||null,
        x:p.mouseX ?? 0, y:p.mouseY ?? 0,
        xdata:physX,
      });
      if(e.key.toLowerCase()==='r'){st.view_x0=0;st.view_x1=1;draw1d(p);model.set(`panel_${p.id}_json`,_viewStateJson(p));model.save_changes();e.stopPropagation();e.preventDefault();}
    });
    overlayCanvas.addEventListener('keyup',(e)=>{
      _emitEvent(p.id,'key_up',null,{
        time_stamp:performance.now()/1000,
        modifiers:_modifiers(e),
        key:e.key,
        x:p.mouseX??0, y:p.mouseY??0,
      });
    });
    overlayCanvas.tabIndex=0;overlayCanvas.style.outline='none';
    overlayCanvas.addEventListener('mouseenter',(e)=>{
      overlayCanvas.focus();
      _emitEvent(p.id,'pointer_enter',null,{..._pointerFields(e),x:e.offsetX,y:e.offsetY});
    });
    overlayCanvas.addEventListener('mousemove',(e)=>{
      const st=p.state;if(!st)return;
      const {mx,my}=_clientPos(e,overlayCanvas,p.pw,p.ph);
      p.mouseX=mx; p.mouseY=my;
      const r=_plotRect1d(p);
      if(mx<r.x||mx>r.x+r.w||my<r.y||my>r.y+r.h){
        p.statusBar.style.display='none';tooltip.style.display='none';
        if(p._hoverSi!==-1){p._hoverSi=-1;p._hoverI=-1;drawMarkers1d(p,null);}
        settled.clear();
        return;
      }
      const xArr = p._1dXArr || (st.x_axis_b64 ? _decodeF64(st.x_axis_b64) : (st.x_axis||[]));
      const frac=_canvasXToFrac1d(mx,st.view_x0,st.view_x1,r);
      const phys=xArr.length>=2?_axisFracToVal(xArr,frac):frac;
      p.statusBar.textContent=`x:${fmtVal(phys)}`;p.statusBar.style.display='block';
      const mhit=_markerHitTest1d(mx,my,p);
      const newSi=mhit?mhit.si:-1;
      if(newSi!==p._hoverSi){
        p._hoverSi=newSi; p._hoverI=mhit?mhit.i:-1;
        drawMarkers1d(p, mhit?{si:newSi}:null);
      }
      if(mhit&&(mhit.collectionLabel||mhit.markerLabel)){const parts=[];if(mhit.collectionLabel)parts.push(mhit.collectionLabel);if(mhit.markerLabel)parts.push(mhit.markerLabel);_showTooltip(parts.join('\n'),e.clientX,e.clientY);return;}
      tooltip.style.display='none';
      // Line hover — only when no widget is being dragged
      if(!p.ovDrag){
        const lhit=_lineHitTest1d(mx,my,p);
        const newLid=lhit?lhit.lineId:'__none__';
        if(newLid!==p._lineHoverId){
          p._lineHoverId=newLid;
          draw1d(p);  // redraw so hovered line is brightened
          drawOverlay1d(p);
          overlayCanvas.style.cursor=lhit?'pointer':'crosshair';
          if(lhit){
            p.ovCtx.save();p.ovCtx.fillStyle='rgba(255,255,255,0.9)';
            p.ovCtx.strokeStyle='rgba(0,0,0,0.5)';p.ovCtx.lineWidth=1.5;
            p.ovCtx.beginPath();p.ovCtx.arc(lhit.canvasPx,lhit.canvasPy,4,0,Math.PI*2);
            p.ovCtx.fill();p.ovCtx.stroke();p.ovCtx.restore();
          }
        }
        if(lhit) _emitEvent(p.id,'pointer_move',null,{line_id:lhit.lineId,x:lhit.x,y:lhit.y,..._pointerFields(e)});
      }
      settled.arm(mx, my, e);
    });
    overlayCanvas.addEventListener('mouseleave',(e)=>{
      settled.clear();
      _emitEvent(p.id,'pointer_leave',null,{..._pointerFields(e),x:e.offsetX,y:e.offsetY});
      p.statusBar.style.display='none';tooltip.style.display='none';
      if(p._hoverSi!==-1){p._hoverSi=-1;p._hoverI=-1;drawMarkers1d(p,null);}
      if(p._lineHoverId!=='__none__'){p._lineHoverId='__none__';draw1d(p);drawOverlay1d(p);overlayCanvas.style.cursor='crosshair';}
    });
    overlayCanvas.addEventListener('dblclick',(e)=>{
      const {mx,my}=_clientPos(e,overlayCanvas,p.pw,p.ph);
      const st=p.state;
      let xdata=null, ydata=null;
      if(st){
        const r=_plotRect1d(p);
        const xArr=p._1dXArr||(st.x_axis_b64?_decodeF64(st.x_axis_b64):(st.x_axis||[]));
        const frac=_canvasXToFrac1d(mx,st.view_x0,st.view_x1,r);
        xdata=xArr.length>=2?_axisFracToVal(xArr,frac):frac;
        // ydata: invert the linear y transform. Prefer the bounds draw1d cached
        // (exactly what was rendered) — for a coordinate axis (PlotXY) data_min
        // may be the zero-curve's range, so y_range / the cache is authoritative.
        let dMin=(p._1dDMin!=null?p._1dDMin:st.data_min), dMax=(p._1dDMax!=null?p._1dDMax:st.data_max);
        if(dMin==null && st.y_range && st.y_range.length===2){ dMin=st.y_range[0]; dMax=st.y_range[1]; }
        if(dMin!=null && dMax!=null) ydata=dMin+((r.y+r.h-my)/(r.h||1))*(dMax-dMin);
      }
      _emitEvent(p.id,'double_click',null,{..._pointerFields(e),button:e.button,x:mx,y:my,xdata,ydata});
    });
    overlayCanvas.addEventListener('wheel',(e)=>{
      _emitEvent(p.id,'wheel',null,{
        time_stamp:performance.now()/1000,
        modifiers:_modifiers(e),
        x:p.mouseX??0, y:p.mouseY??0,
        dx:e.deltaX, dy:e.deltaY,
      });
    },{passive:true});
  }

  // ── 2D overlay widget hit-test & drag ────────────────────────────────────
  // Returns {idx, mode, snapW, ...} describing which widget and handle was hit.
  // mode values:
  //   'move'       – drag the whole widget body
  //   'resize_r'   – circle/annular outer-radius handle (right)
  //   'resize_ir'  – annular inner-radius handle
  //   'resize_br'  – rectangle bottom-right corner
  //   'resize_bl'  – rectangle bottom-left corner
  //   'resize_tr'  – rectangle top-right corner
  //   'resize_tl'  – rectangle top-left corner
  //   'vertex_N'   – polygon vertex N
  function _ovHitTest2d(mx, my, p) {
    const st = p.state; if (!st) return null;
    const imgW = p.imgW||Math.max(1, p.pw - PAD_L - PAD_R);
    const imgH = p.imgH||Math.max(1, p.ph - PAD_T - PAD_B);
    const widgets = st.overlay_widgets || [];
    const scale   = _imgScale2d(st, imgW, imgH);
    const HR = 9; // handle grab radius (px)

    // iterate top-to-bottom (last drawn = topmost)
    for (let i = widgets.length - 1; i >= 0; i--) {
      const w = widgets[i];
      if(w.visible === false) continue;
      if (w.type === 'circle') {
        const [ccx, ccy] = _imgToCanvas2d(w.cx, w.cy, st, imgW, imgH);
        const cr = w.r * scale;
        // outer radius handle
        if (Math.hypot(mx - (ccx + cr), my - ccy) <= HR)
          return { idx:i, mode:'resize_r', snapW:{...w}, startMX:mx, startMY:my };
        // body (inside ring ± tolerance)
        if (Math.abs(Math.hypot(mx-ccx, my-ccy) - cr) <= Math.max(HR, cr*0.18) ||
            Math.hypot(mx-ccx, my-ccy) <= HR)
          return { idx:i, mode:'move', snapW:{...w}, startMX:mx, startMY:my };

      } else if (w.type === 'annular') {
        const [ccx, ccy] = _imgToCanvas2d(w.cx, w.cy, st, imgW, imgH);
        const ro = w.r_outer * scale, ri = w.r_inner * scale;
        // inner-radius handle (above centre, inside inner ring)
        if (Math.hypot(mx - (ccx + ri), my - (ccy - ri * 0.3)) <= HR)
          return { idx:i, mode:'resize_ir', snapW:{...w}, startMX:mx, startMY:my };
        // outer-radius handle
        if (Math.hypot(mx - (ccx + ro), my - ccy) <= HR)
          return { idx:i, mode:'resize_r', snapW:{...w}, startMX:mx, startMY:my };
        // body (annular band)
        const d = Math.hypot(mx - ccx, my - ccy);
        if (d >= ri - HR && d <= ro + HR)
          return { idx:i, mode:'move', snapW:{...w}, startMX:mx, startMY:my };

      } else if (w.type === 'rectangle') {
        const [rx, ry] = _imgToCanvas2d(w.x, w.y, st, imgW, imgH);
        const rw = w.w * scale, rh = w.h * scale;
        if (Math.hypot(mx-(rx+rw), my-(ry+rh)) <= HR) return { idx:i, mode:'resize_br', snapW:{...w}, startMX:mx, startMY:my };
        if (Math.hypot(mx-rx,      my-(ry+rh)) <= HR) return { idx:i, mode:'resize_bl', snapW:{...w}, startMX:mx, startMY:my };
        if (Math.hypot(mx-(rx+rw), my-ry)      <= HR) return { idx:i, mode:'resize_tr', snapW:{...w}, startMX:mx, startMY:my };
        if (Math.hypot(mx-rx,      my-ry)      <= HR) return { idx:i, mode:'resize_tl', snapW:{...w}, startMX:mx, startMY:my };
        if (mx >= rx-HR && mx <= rx+rw+HR && my >= ry-HR && my <= ry+rh+HR)
          return { idx:i, mode:'move', snapW:{...w}, startMX:mx, startMY:my };

      } else if (w.type === 'crosshair') {
        const [ccx, ccy] = _imgToCanvas2d(w.cx, w.cy, st, imgW, imgH);
        if (Math.hypot(mx-ccx, my-ccy) <= HR + 4)
          return { idx:i, mode:'move', snapW:{...w}, startMX:mx, startMY:my };

      } else if (w.type === 'polygon') {
        const verts = w.vertices || [];
        for (let k = 0; k < verts.length; k++) {
          const [px, py] = _imgToCanvas2d(verts[k][0], verts[k][1], st, imgW, imgH);
          if (Math.hypot(mx-px, my-py) <= HR)
            return { idx:i, mode:`vertex_${k}`, snapW:{...w, vertices: verts.map(v=>[...v])}, startMX:mx, startMY:my };
        }
        // hit inside polygon → move whole polygon
        if (_pointInPolygon2d(mx, my, verts, st, imgW, imgH))
          return { idx:i, mode:'move', snapW:{...w, vertices: verts.map(v=>[...v])}, startMX:mx, startMY:my };

      } else if (w.type === 'label') {
        const [lx, ly] = _imgToCanvas2d(w.x, w.y, st, imgW, imgH);
        if (Math.hypot(mx-lx, my-ly) <= HR + 6)
          return { idx:i, mode:'move', snapW:{...w}, startMX:mx, startMY:my };

      } else if (w.type === 'arrow') {
        const [tx, ty] = _imgToCanvas2d(w.x, w.y, st, imgW, imgH);
        const [hx, hy] = _imgToCanvas2d(w.x + w.u, w.y + w.v, st, imgW, imgH);
        // head handle → re-aim the arrow (head moves, tail fixed)
        if (Math.hypot(mx-hx, my-hy) <= HR)
          return { idx:i, mode:'resize_head', snapW:{...w}, startMX:mx, startMY:my };
        // tail handle → reshape (tail moves, HEAD stays anchored)
        if (Math.hypot(mx-tx, my-ty) <= HR)
          return { idx:i, mode:'resize_tail', snapW:{...w}, startMX:mx, startMY:my };
        // near the shaft → move whole arrow
        if (_distToSegment2d(mx, my, tx, ty, hx, hy) <= HR)
          return { idx:i, mode:'move', snapW:{...w}, startMX:mx, startMY:my };
      }
    }
    return null;
  }

  // Perpendicular distance from point (px,py) to the segment (ax,ay)-(bx,by).
  function _distToSegment2d(px, py, ax, ay, bx, by) {
    const dx = bx - ax, dy = by - ay;
    const len2 = dx*dx + dy*dy;
    if (len2 === 0) return Math.hypot(px-ax, py-ay);
    let t = ((px-ax)*dx + (py-ay)*dy) / len2;
    t = Math.max(0, Math.min(1, t));
    return Math.hypot(px - (ax + t*dx), py - (ay + t*dy));
  }

  function _pointInPolygon2d(mx, my, verts, st, imgW, imgH) {
    let inside = false;
    const cverts = verts.map(v => _imgToCanvas2d(v[0], v[1], st, imgW, imgH));
    for (let i = 0, j = cverts.length-1; i < cverts.length; j = i++) {
      const [xi,yi] = cverts[i], [xj,yj] = cverts[j];
      if (((yi>my)!==(yj>my)) && (mx < (xj-xi)*(my-yi)/(yj-yi)+xi)) inside = !inside;
    }
    return inside;
  }

  function _doDrag2d(e, p) {
    const st = p.state; if (!st) return;
    const imgW = p.imgW||Math.max(1, p.pw - PAD_L - PAD_R);
    const imgH = p.imgH||Math.max(1, p.ph - PAD_T - PAD_B);
    const {mx, my} = _clientPos(e, p.overlayCanvas, imgW, imgH);
    const d     = p.ovDrag2d;
    const s     = d.snapW;
    const w     = st.overlay_widgets[d.idx];
    const scale = _imgScale2d(st, imgW, imgH);

    // Convert current mouse to image coords
    const [imgMX, imgMY] = _canvasToImg2d(mx, my, st, imgW, imgH);
    // delta in image pixels from drag-start
    const [imgSX, imgSY] = _canvasToImg2d(d.startMX, d.startMY, st, imgW, imgH);
    const dix = imgMX - imgSX, diy = imgMY - imgSY;

    if (w.type === 'circle') {
      if (d.mode === 'move') {
        w.cx = s.cx + dix; w.cy = s.cy + diy;
      } else if (d.mode === 'resize_r') {
        // distance from centre in image-px
        const [ccx, ccy] = _imgToCanvas2d(s.cx, s.cy, st, imgW, imgH);
        w.r = Math.max(1, Math.hypot(mx-ccx, my-ccy) / scale);
      }
    } else if (w.type === 'annular') {
      if (d.mode === 'move') {
        w.cx = s.cx + dix; w.cy = s.cy + diy;
      } else if (d.mode === 'resize_r') {
        const [ccx, ccy] = _imgToCanvas2d(s.cx, s.cy, st, imgW, imgH);
        const newR = Math.max(s.r_inner + 1, Math.hypot(mx-ccx, my-ccy) / scale);
        w.r_outer = newR;
      } else if (d.mode === 'resize_ir') {
        const [ccx, ccy] = _imgToCanvas2d(s.cx, s.cy, st, imgW, imgH);
        const newR = Math.max(1, Math.min(s.r_outer - 1, Math.hypot(mx-ccx, my-ccy) / scale));
        w.r_inner = newR;
      }
    } else if (w.type === 'rectangle') {
      if (d.mode === 'move') {
        w.x = s.x + dix; w.y = s.y + diy;
      } else if (d.mode === 'resize_br') {
        w.w = Math.max(1, s.w + dix); w.h = Math.max(1, s.h + diy);
      } else if (d.mode === 'resize_bl') {
        const newW = Math.max(1, s.w - dix);
        w.x = s.x + (s.w - newW); w.w = newW;
        w.h = Math.max(1, s.h + diy);
      } else if (d.mode === 'resize_tr') {
        w.w = Math.max(1, s.w + dix);
        const newH = Math.max(1, s.h - diy);
        w.y = s.y + (s.h - newH); w.h = newH;
      } else if (d.mode === 'resize_tl') {
        const newW = Math.max(1, s.w - dix);
        w.x = s.x + (s.w - newW); w.w = newW;
        const newH = Math.max(1, s.h - diy);
        w.y = s.y + (s.h - newH); w.h = newH;
      }
    } else if (w.type === 'crosshair') {
      w.cx = s.cx + dix; w.cy = s.cy + diy;
    } else if (w.type === 'polygon') {
      if (d.mode === 'move') {
        w.vertices = s.vertices.map(v => [v[0]+dix, v[1]+diy]);
      } else if (d.mode.startsWith('vertex_')) {
        const k = parseInt(d.mode.slice(7));
        w.vertices = s.vertices.map((v,j) => j===k ? [imgMX, imgMY] : [...v]);
      }
    } else if (w.type === 'label') {
      w.x = s.x + dix; w.y = s.y + diy;
    } else if (w.type === 'arrow') {
      if (d.mode === 'move') {
        w.x = s.x + dix; w.y = s.y + diy;
      } else if (d.mode === 'resize_head') {
        // head follows the cursor → u,v = imgMouse − tail (tail fixed)
        w.u = imgMX - s.x; w.v = imgMY - s.y;
      } else if (d.mode === 'resize_tail') {
        // tail follows the cursor, HEAD stays anchored: the fixed head is
        // (s.x + s.u, s.y + s.v).  x,y = tail; u,v = head − tail so the head
        // point is invariant under the drag.
        w.x = s.x + dix; w.y = s.y + diy;
        w.u = s.u - dix; w.v = s.v - diy;
      }
    }

    drawOverlay2d(p);
    model.set(`panel_${p.id}_json`, _viewStateJson(p));
    model.save_changes();
    e.preventDefault();
  }

  function _canvasXToFrac1d(px,x0,x1,r){return x0+((px-r.x)/(r.w||1))*(x1-x0);}

  function _ovHitTest1d(mx,my,p){
    const st=p.state;if(!st)return null;
    const r=_plotRect1d(p);
    const xArr = p._1dXArr || (st.x_axis_b64 ? _decodeF64(st.x_axis_b64) : (st.x_axis||[]));
    const x0=st.view_x0||0,x1=st.view_x1||1;
    const widgets=st.overlay_widgets||[];
    const HR=7;
    // First pass: point widgets have highest drag priority so that a point
    // handle sitting inside a range band is always reachable.
    for(let i=widgets.length-1;i>=0;i--){
      const w=widgets[i];
      if(w.visible===false) continue;
      if(w.type==='point'){
        const px=_fracToPx1d(_axisValToFrac(xArr,w.x),x0,x1,r);
        const py=_valToPy1d(w.y,st.data_min,st.data_max,r);
        if(Math.hypot(mx-px,my-py)<=HR+4)
          return{idx:i,mode:'move',wtype:'point',startMX:mx,startMY:my,snapW:{...w}};
      }
    }
    // Second pass: everything else
    for(let i=widgets.length-1;i>=0;i--){
      const w=widgets[i];
      if(w.visible===false) continue;
      if(w.type==='vline'){
        const px=_fracToPx1d(_axisValToFrac(xArr,w.x),x0,x1,r);
        if(Math.sqrt((mx-px)**2+(my-(r.y+7))**2)<=HR||Math.abs(mx-px)<=5)
          return{idx:i,mode:'move',wtype:'vline',startMX:mx,snapW:{...w}};
      } else if(w.type==='hline'){
        const py=_valToPy1d(w.y,st.data_min,st.data_max,r);
        if(Math.abs(my-py)<=5) return{idx:i,mode:'move',wtype:'hline',startMY:my,snapW:{...w}};
      } else if(w.type==='range'){
        const px0=_fracToPx1d(_axisValToFrac(xArr,w.x0),x0,x1,r);
        const px1b=_fracToPx1d(_axisValToFrac(xArr,w.x1),x0,x1,r);
        if(w.style==='fwhm'){
          // FWHM style: hit-test the two circular handles
          const pyHalf=_valToPy1d(w.y||0,st.data_min,st.data_max,r);
          if(Math.hypot(mx-px0,my-pyHalf)<=HR+5)
            return{idx:i,mode:'edge0',wtype:'range',startMX:mx,snapW:{...w}};
          if(Math.hypot(mx-px1b,my-pyHalf)<=HR+5)
            return{idx:i,mode:'edge1',wtype:'range',startMX:mx,snapW:{...w}};
        } else {
          if(Math.abs(mx-px0)<=HR+5) return{idx:i,mode:'edge0',wtype:'range',startMX:mx,snapW:{...w}};
          if(Math.abs(mx-px1b)<=HR+5) return{idx:i,mode:'edge1',wtype:'range',startMX:mx,snapW:{...w}};
          const left=Math.min(px0,px1b),right=Math.max(px0,px1b);
          if(mx>=left&&mx<=right&&my>=r.y&&my<=r.y+r.h) return{idx:i,mode:'move',wtype:'range',startMX:mx,snapW:{...w}};
        }
      }
    }
    return null;
  }

  function _doDrag1d(e,p){
    const st=p.state;if(!st)return;
    const r=_plotRect1d(p);
    const {mx,my:py}=_clientPos(e,p.overlayCanvas,p.pw,p.ph);
    const xArr = p._1dXArr || (st.x_axis_b64 ? _decodeF64(st.x_axis_b64) : (st.x_axis||[]));
    const x0=st.view_x0||0,x1=st.view_x1||1;
    const xUnit=xArr.length>=2?_axisFracToVal(xArr,_canvasXToFrac1d(mx,x0,x1,r)):_canvasXToFrac1d(mx,x0,x1,r);
    const widgets=st.overlay_widgets;
    const d=p.ovDrag, s=d.snapW, w=widgets[d.idx];
    if(w.type==='vline'){w.x=xUnit;}
    else if(w.type==='hline'){w.y=st.data_max-((py-r.y)/(r.h||1))*(st.data_max-st.data_min);}
    else if(w.type==='range'){
      if(d.mode==='edge0') w.x0=xUnit;
      else if(d.mode==='edge1') w.x1=xUnit;
      else {
        const snapPx=_fracToPx1d(xArr.length>=2?_axisValToFrac(xArr,s.x0):0,x0,x1,r);
        const dxUnit=xArr.length>=2?_axisFracToVal(xArr,_canvasXToFrac1d(snapPx+(mx-d.startMX),x0,x1,r))-s.x0:(mx-d.startMX)/(r.w||1);
        w.x0=s.x0+dxUnit;w.x1=s.x1+dxUnit;
      }
    } else if(w.type==='point'){
      // Clamp to plot rectangle
      const clampX=Math.max(r.x,Math.min(r.x+r.w,mx));
      const clampY=Math.max(r.y,Math.min(r.y+r.h,py));
      w.x=xArr.length>=2?_axisFracToVal(xArr,_canvasXToFrac1d(clampX,x0,x1,r)):_canvasXToFrac1d(clampX,x0,x1,r);
      w.y=st.data_max-((clampY-r.y)/(r.h||1))*(st.data_max-st.data_min);
    }
    drawOverlay1d(p);
    model.set(`panel_${p.id}_json`,_viewStateJson(p));model.save_changes();
    e.preventDefault();
  }

  // ── shared-axis propagation ───────────────────────────────────────────────
  function _getShareGroups() {
    try { return JSON.parse(model.get('layout_json')).share_groups||{}; } catch(_){ return {}; }
  }

  function _propagateZoom2d(srcPanel) {
    const sg=_getShareGroups();
    const srcId=srcPanel.id, st=srcPanel.state;
    for(const [axis,groups] of Object.entries(sg)){
      for(const group of groups){
        if(!group.includes(srcId)) continue;
        for(const pid of group){
          if(pid===srcId) continue;
          const tp=panels.get(pid); if(!tp||!tp.state) continue;
          if(axis==='x'||axis==='both'){tp.state.zoom=st.zoom;tp.state.center_x=st.center_x;}
          if(axis==='y'||axis==='both'){tp.state.center_y=st.center_y;}
          _redrawPanel(tp);
          model.set(`panel_${pid}_json`,_viewStateJson(tp));
        }
      }
    }
  }

  function _propagateView1d(srcPanel) {
    const sg=_getShareGroups();
    const srcId=srcPanel.id, st=srcPanel.state;
    for(const [axis,groups] of Object.entries(sg)){
      if(axis!=='x'&&axis!=='both') continue;
      for(const group of groups){
        if(!group.includes(srcId)) continue;
        for(const pid of group){
          if(pid===srcId) continue;
          const tp=panels.get(pid); if(!tp||!tp.state) continue;
          tp.state.view_x0=st.view_x0; tp.state.view_x1=st.view_x1;
          _redrawPanel(tp);
          model.set(`panel_${pid}_json`,_viewStateJson(tp));
        }
      }
    }
  }

  // ── figure-level resize ───────────────────────────────────────────────────
  let isResizing = false;
  let resizeStart = {};
  let _cachedLayout = null;   // layout parsed once at mousedown — avoids per-frame JSON.parse
  let _rafPending = false;    // rAF throttle flag
  let _pendingNfw = 0, _pendingNfh = 0;

  resizeHandle.addEventListener('mousedown', (e) => {
    isResizing = true;
    _suppressLayoutUpdate = true;
    const fw = model.get('fig_width'), fh = model.get('fig_height');
    // Capture the current CSS scale so drag deltas (in visual/page pixels) can
    // be converted back to native figure pixels.  offsetWidth is pre-transform.
    const _oRect = outerDiv.getBoundingClientRect();
    const _sfFig = (_oRect.width > 0) ? outerDiv.offsetWidth / _oRect.width : 1;
    resizeStart = { mx: e.clientX, my: e.clientY, fw, fh, sfFig: _sfFig };
    // Cache the layout once so mousemove never needs to parse JSON
    try { _cachedLayout = JSON.parse(model.get('layout_json')); } catch(_) { _cachedLayout = null; }
    sizeLabel.style.display = 'block';
    e.preventDefault();
  });

  // Low-level resize: only moves DOM geometry, no pixel drawing.
  // This is cheap enough to call every rAF (~16 ms).
  function _applyFigResizeDOM(nfw, nfh) {
    const layout = _cachedLayout;
    if (!layout) return;
    const { nrows, ncols, width_ratios, height_ratios, panel_specs } = layout;
    const wsum = width_ratios.reduce((a,b)=>a+b,0);
    const hsum = height_ratios.reduce((a,b)=>a+b,0);

    const col_px = width_ratios.map(w => nfw * w / wsum);
    const row_px = height_ratios.map(h => nfh * h / hsum);


    // Resize canvases (CSS size only — no pixel content redrawn)
    const colPx = new Array(ncols).fill(0);
    const rowPx = new Array(nrows).fill(0);
    for (const spec of panel_specs) {
      const p = panels.get(spec.id); if (!p) continue;
      let cw=0, ch=0;
      for(let c=spec.col_start;c<spec.col_stop;c++) cw+=col_px[c];
      for(let r=spec.row_start;r<spec.row_stop;r++) ch+=row_px[r];
      cw = Math.max(64, Math.round(cw));
      ch = Math.max(64, Math.round(ch));
      p.pw = cw; p.ph = ch;

      // Resize only CSS dimensions — don't touch canvas.width/height yet
      // (that clears the pixel buffer and forces a redraw)
      _resizePanelCSS(spec.id, cw, ch);

      const perC=Math.round(cw/(spec.col_stop-spec.col_start));
      const perR=Math.round(ch/(spec.row_stop-spec.row_start));
      for(let c=spec.col_start;c<spec.col_stop;c++) colPx[c]=Math.max(colPx[c],perC);
      for(let r=spec.row_start;r<spec.row_stop;r++) rowPx[r]=Math.max(rowPx[r],perR);
    }

    gridDiv.style.gridTemplateColumns = colPx.map(px=>px+'px').join(' ');
    gridDiv.style.gridTemplateRows    = rowPx.map(px=>px+'px').join(' ');
    gridDiv.style.width  = '';
    gridDiv.style.height = '';

    // CSS-only reposition of insets (no canvas redraw during live drag)
    insetsContainer.style.width  = nfw + 'px';
    insetsContainer.style.height = nfh + 'px';
    const insetSpecs = layout.inset_specs || [];
    for (const spec of insetSpecs) {
      const pi = panels.get(spec.id);
      if (!pi || !pi.isInset) continue;
      const pw = Math.max(64, Math.round(nfw * spec.w_frac));
      const ph = Math.max(64, Math.round(nfh * spec.h_frac));
      pi.pw = pw; pi.ph = ph;
      // Reuse _applyAllInsetStates logic inline (CSS only) by temporarily
      // patching spec dimensions and calling the function with a fake layout.
      spec.panel_width  = pw;
      spec.panel_height = ph;
    }
    if (insetSpecs.length) {
      _applyAllInsetStates({ ...layout, fig_width: nfw, fig_height: nfh });
    }
  }

  // CSS-only resize: move/size elements without clearing canvas buffers.
  // The canvas still renders its old content scaled by CSS — which looks
  // slightly blurry but is instantaneous. A full redraw follows on mouseup.
  function _resizePanelCSS(id, pw, ph) {
    const p = panels.get(id); if (!p) return;

    function _szCSS(c, w, h) {
      c.style.width  = w + 'px';
      c.style.height = h + 'px';
      // Do NOT set c.width / c.height — that would clear the canvas buffer
    }

    if (p.kind === '2d') {
      const st = p.state;
      const hasPhysAxis = st && (st.is_mesh || st.has_axes)
                       && st.x_axis && st.x_axis.length >= 2
                       && st.y_axis && st.y_axis.length >= 2;
      const cbW  = _cbWidth(st);
      const padT = _padT(st);
      const imgX = hasPhysAxis ? PAD_L : 0;
      const imgY = hasPhysAxis ? padT : 0;
      const imgW = Math.max(1, (hasPhysAxis ? pw - PAD_L - PAD_R : pw)
                               - (cbW ? cbW + 2 : 0));
      const imgH = hasPhysAxis ? Math.max(1, ph - padT - PAD_B) : ph;
      // Update stored dims so event handlers stay consistent during CSS resize
      p.imgX = imgX; p.imgY = imgY; p.imgW = imgW; p.imgH = imgH;

      if (p.plotWrap) { p.plotWrap.style.width=pw+'px'; p.plotWrap.style.height=ph+'px'; }

      _szCSS(p.plotCanvas,    imgW, imgH);
      _szCSS(p.overlayCanvas, imgW, imgH);
      _szCSS(p.markersCanvas, imgW, imgH);

      p.plotCanvas.style.left    = imgX+'px'; p.plotCanvas.style.top    = imgY+'px';
      p.overlayCanvas.style.left = imgX+'px'; p.overlayCanvas.style.top = imgY+'px';
      p.markersCanvas.style.left = imgX+'px'; p.markersCanvas.style.top = imgY+'px';

      if (p.statusBar) { p.statusBar.style.left=(imgX+4)+'px'; p.statusBar.style.bottom=(ph-imgY-imgH+4)+'px'; }
      if (p.scaleBar)  { p.scaleBar.style.right=(pw-imgX-imgW+12)+'px'; p.scaleBar.style.bottom=(ph-imgY-imgH+12)+'px'; }

      // Axis canvases: just reposition, size handled on full redraw
      if (p.yAxisCanvas && p.yAxisCanvas.style.display !== 'none') {
        p.yAxisCanvas.style.left = '0px'; p.yAxisCanvas.style.top = imgY+'px';
        _szCSS(p.yAxisCanvas, PAD_L, imgH);
      }
      if (p.xAxisCanvas && p.xAxisCanvas.style.display !== 'none') {
        p.xAxisCanvas.style.left = imgX+'px'; p.xAxisCanvas.style.top = (ph-PAD_B)+'px';
        _szCSS(p.xAxisCanvas, imgW, PAD_B);
      }
      if (p.cbCanvas && p.cbCanvas.style.display !== 'none') {
        p.cbCanvas.style.left = (imgX + imgW + 2) + 'px'; p.cbCanvas.style.top = imgY + 'px';
        _szCSS(p.cbCanvas, cbW || 16, imgH);
      }
    } else if (p.kind === '3d') {
      _szCSS(p.plotCanvas,    pw, ph);
      _szCSS(p.overlayCanvas, pw, ph);
    } else {
      _szCSS(p.plotCanvas,    pw, ph);
      _szCSS(p.overlayCanvas, pw, ph);
      _szCSS(p.markersCanvas, pw, ph);
    }
  }

  // Full resize: update canvas pixel buffers and redraw content.
  function _applyFigResize(nfw, nfh) {
    _applyFigResizeDOM(nfw, nfh);
    for (const p of panels.values()) {
      _resizePanelDOM(p.id, p.pw, p.ph);
      _redrawPanel(p);
    }
    _drawFigureMarkers([nfw, nfh]);
  }

  document.addEventListener('mousemove', (e) => {
    if (!isResizing) return;
    const sf = resizeStart.sfFig || 1;
    _pendingNfw = Math.max(200, resizeStart.fw + (e.clientX - resizeStart.mx) * sf);
    _pendingNfh = Math.max(100, resizeStart.fh + (e.clientY - resizeStart.my) * sf);
    sizeLabel.textContent = `${Math.round(_pendingNfw)}×${Math.round(_pendingNfh)}`;

    // Throttle to one DOM update per animation frame
    if (!_rafPending) {
      _rafPending = true;
      requestAnimationFrame(() => {
        _rafPending = false;
        if (!isResizing) return;
        _applyFigResizeDOM(_pendingNfw, _pendingNfh);
        // Track the figure-marker overlay to the live drag size.
        _drawFigureMarkers([_pendingNfw, _pendingNfh]);
      });
    }
    e.preventDefault();
  });

  document.addEventListener('mouseup', (e) => {
    if (!isResizing) return;
    isResizing = false;
    _rafPending = false;
    sizeLabel.style.display = 'none';
    const sf = resizeStart.sfFig || 1;
    const nfw = Math.max(200, resizeStart.fw + (e.clientX - resizeStart.mx) * sf);
    const nfh = Math.max(100, resizeStart.fh + (e.clientY - resizeStart.my) * sf);

    // Full redraw at final size
    _applyFigResize(nfw, nfh);

    // Patch layout_json so the model listener won't revert sizes
    try {
      const layout = JSON.parse(model.get('layout_json'));
      layout.fig_width  = Math.round(nfw);
      layout.fig_height = Math.round(nfh);
      for (const spec of layout.panel_specs) {
        const p = panels.get(spec.id);
        if (p) { spec.panel_width = p.pw; spec.panel_height = p.ph; }
      }
      for (const spec of (layout.inset_specs || [])) {
        const pi = panels.get(spec.id);
        if (pi) { spec.panel_width = pi.pw; spec.panel_height = pi.ph; }
      }
      model.set('layout_json', JSON.stringify(layout));
    } catch(_) {}

    _suppressLayoutUpdate = false;
    model.set('fig_width',  Math.round(nfw));
    model.set('fig_height', Math.round(nfh));
    model.save_changes();
    e.preventDefault();
  });


  // ── bar chart ─────────────────────────────────────────────────────────────
  // Shared geometry helper used by both drawBar and _attachEventsBar.
  // Returns per-slot/bar pixel sizes, coordinate mappers, and group helpers.
  function _barGeom(st, r) {
    const values   = st.values   || [];
    const n        = values.length || 1;
    const groups   = st.groups   || 1;
    const orient   = st.orient   || 'v';
    const bwFrac   = st.bar_width !== undefined ? st.bar_width : 0.8;
    const baseline = st.baseline !== undefined  ? st.baseline  : 0;
    let dMin = st.data_min, dMax = st.data_max;
    if (st.y_range && st.y_range.length === 2) { dMin = st.y_range[0]; dMax = st.y_range[1]; }
    const logScale = !!st.log_scale;
    const LC       = 1e-10; // log clamp

    // Value at category i, group g — supports 2-D [[g0,g1,...], ...] and
    // legacy 1-D [v0, v1, ...].
    function getVal(i, g) {
      const row = values[i];
      if (Array.isArray(row)) return row[g] !== undefined ? row[g] : 0;
      return (g === 0) ? (row !== undefined ? +row : 0) : 0;
    }

    // Pixel coordinate along the VALUE axis.
    function _valToPy(v) {
      if (logScale) {
        const lv   = Math.log10(Math.max(LC, v));
        const lMin = Math.log10(Math.max(LC, dMin));
        const lMax = Math.log10(Math.max(LC, dMax));
        return r.y + r.h - ((lv - lMin) / ((lMax - lMin) || 1)) * r.h;
      }
      return r.y + r.h - ((v - dMin) / ((dMax - dMin) || 1)) * r.h;
    }
    function _valToX(v) {
      if (logScale) {
        const lv   = Math.log10(Math.max(LC, v));
        const lMin = Math.log10(Math.max(LC, dMin));
        const lMax = Math.log10(Math.max(LC, dMax));
        return r.x + ((lv - lMin) / ((lMax - lMin) || 1)) * r.w;
      }
      return r.x + ((v - dMin) / ((dMax - dMin) || 1)) * r.w;
    }

    if (orient === 'h') {
      const slotPx     = r.h / n;
      const barPx      = (slotPx * bwFrac) / groups;
      function xToPx(v) { return _valToX(v); }
      function yToPx(i) { return r.y + (i + 0.5) * slotPx; }
      function groupOffsetPx(g) { return (g - (groups - 1) / 2) * barPx; }
      const bv = logScale ? Math.max(LC, baseline) : baseline;
      const basePx = Math.max(r.x, Math.min(r.x + r.w, xToPx(bv)));
      return { n, groups, orient, slotPx, barPx, dMin, dMax, baseline,
               basePx, xToPx, yToPx, groupOffsetPx, logScale, getVal, LC };
    } else {
      const slotPx     = r.w / n;
      const barPx      = (slotPx * bwFrac) / groups;
      function xToPx(i) { return r.x + (i + 0.5) * slotPx; }
      function yToPx(v) { return _valToPy(v); }
      function groupOffsetPx(g) { return (g - (groups - 1) / 2) * barPx; }
      const bv = logScale ? Math.max(LC, baseline) : baseline;
      const basePx = Math.max(r.y, Math.min(r.y + r.h, yToPx(bv)));
      return { n, groups, orient, slotPx, barPx, dMin, dMax, baseline,
               basePx, xToPx, yToPx, groupOffsetPx, logScale, getVal, LC };
    }
  }

  function drawBar(p) {
    const st = p.state; if (!st) return;
    _recordFrame(p);
    const { pw, ph, plotCtx: ctx } = p;
    const r = _plotRect1d(p);

    ctx.clearRect(0, 0, pw, ph);
    ctx.fillStyle = theme.bg;     ctx.fillRect(0, 0, pw, ph);
    ctx.fillStyle = theme.bgPlot; ctx.fillRect(r.x, r.y, r.w, r.h);

    const values      = st.values      || [];
    const xCenters    = st.x_centers   || values.map((_, i) => i);
    const xLabels     = st.x_labels    || [];
    const barColor    = st.bar_color   || '#4fc3f7';
    const barColors   = st.bar_colors  || [];
    const groupColors = st.group_colors || [];
    const groupLabels = st.group_labels || [];
    const orient      = st.orient || 'v';
    let dMin = st.data_min, dMax = st.data_max;
    if (st.y_range && st.y_range.length === 2) { dMin = st.y_range[0]; dMax = st.y_range[1]; }
    const logScale    = !!st.log_scale;
    const axisVis     = st.axis_visible !== false;
    const xTicksVis   = st.x_ticks_visible !== false;
    const yTicksVis   = st.y_ticks_visible !== false;

    if (!values.length) return;

    const g = _barGeom(st, r);
    const LC = g.LC;

    // ── log tick helper ───────────────────────────────────────────────────
    function _fmtLogTick(v) {
      const exp = Math.round(Math.log10(v));
      if (Math.abs(v - Math.pow(10, exp)) < v * 1e-6) {
        if (exp === 0) return '1';
        if (exp === 1) return '10';
        return `$10^{${exp}}$`;   // rendered as a true superscript by _drawTex
      }
      return fmtVal(v);
    }

    // ── grid lines (along value axis) ─────────────────────────────────────
    ctx.strokeStyle = theme.gridStroke; ctx.lineWidth = 1;

    if (logScale) {
      const lMin = Math.log10(Math.max(LC, dMin));
      const lMax = Math.log10(Math.max(LC, dMax));
      // minor grid — 2,3,5 × decade, semi-transparent
      ctx.globalAlpha = 0.3;
      for (let exp = Math.floor(lMin); exp < Math.ceil(lMax); exp++) {
        for (const m of [2, 3, 5]) {
          const v = m * Math.pow(10, exp);
          if (v < dMin || v > dMax) continue;
          if (orient === 'h') {
            const px = g.xToPx(v);
            if (px < r.x || px > r.x + r.w) continue;
            ctx.beginPath(); ctx.moveTo(px, r.y); ctx.lineTo(px, r.y + r.h); ctx.stroke();
          } else {
            const py = g.yToPx(v);
            if (py < r.y || py > r.y + r.h) continue;
            ctx.beginPath(); ctx.moveTo(r.x, py); ctx.lineTo(r.x + r.w, py); ctx.stroke();
          }
        }
      }
      ctx.globalAlpha = 1.0;
      // major grid — decades, full opacity
      for (let exp = Math.floor(lMin); exp <= Math.ceil(lMax); exp++) {
        const v = Math.pow(10, exp);
        if (v < dMin || v > dMax) continue;
        if (orient === 'h') {
          const px = g.xToPx(v);
          if (px < r.x || px > r.x + r.w) continue;
          ctx.beginPath(); ctx.moveTo(px, r.y); ctx.lineTo(px, r.y + r.h); ctx.stroke();
        } else {
          const py = g.yToPx(v);
          if (py < r.y || py > r.y + r.h) continue;
          ctx.beginPath(); ctx.moveTo(r.x, py); ctx.lineTo(r.x + r.w, py); ctx.stroke();
        }
      }
    } else {
      const valRange = (dMax - dMin) || 1;
      const valStep  = findNice(valRange / Math.max(2, Math.floor((orient==='h' ? r.w : r.h) / 40)));
      if (orient === 'h') {
        for (let v = Math.ceil(dMin/valStep)*valStep; v <= dMax+valStep*0.01; v += valStep) {
          const px = g.xToPx(v);
          if (px < r.x || px > r.x + r.w) continue;
          ctx.beginPath(); ctx.moveTo(px, r.y); ctx.lineTo(px, r.y + r.h); ctx.stroke();
        }
      } else {
        for (let v = Math.ceil(dMin/valStep)*valStep; v <= dMax+valStep*0.01; v += valStep) {
          const py = g.yToPx(v);
          if (py < r.y || py > r.y + r.h) continue;
          ctx.beginPath(); ctx.moveTo(r.x, py); ctx.lineTo(r.x + r.w, py); ctx.stroke();
        }
      }
    }

    // ── bars ──────────────────────────────────────────────────────────────
    ctx.save(); ctx.beginPath(); ctx.rect(r.x, r.y, r.w, r.h); ctx.clip();

    for (let i = 0; i < g.n; i++) {
      for (let gi = 0; gi < g.groups; gi++) {
        const val   = g.getVal(i, gi);
        const color = groupColors[gi] || barColors[i] || barColor;
        const isHov = p._hovBar !== null &&
                      p._hovBar.slot === i && p._hovBar.group === gi;
        const dv    = logScale ? Math.max(LC, val) : val;

        if (orient === 'h') {
          const cy    = g.yToPx(i) + g.groupOffsetPx(gi);
          const valPx = g.xToPx(dv);
          const bLeft = Math.min(valPx, g.basePx);
          const bW    = Math.max(1, Math.abs(valPx - g.basePx));
          ctx.fillStyle = color;
          ctx.fillRect(bLeft, cy - g.barPx / 2, bW, g.barPx);
          if (isHov) {
            ctx.save(); ctx.fillStyle = 'rgba(255,255,255,0.22)';
            ctx.fillRect(bLeft, cy - g.barPx / 2, bW, g.barPx); ctx.restore();
          }
          ctx.strokeStyle = theme.dark ? 'rgba(0,0,0,0.25)' : 'rgba(0,0,0,0.09)';
          ctx.lineWidth = 0.5;
          ctx.strokeRect(bLeft, cy - g.barPx / 2, bW, g.barPx);
        } else {
          const cx    = g.xToPx(i) + g.groupOffsetPx(gi);
          const valPy = g.yToPx(dv);
          const bTop  = Math.min(valPy, g.basePx);
          const bH    = Math.max(1, Math.abs(valPy - g.basePx));
          ctx.fillStyle = color;
          ctx.fillRect(cx - g.barPx / 2, bTop, g.barPx, bH);
          if (isHov) {
            ctx.save(); ctx.fillStyle = 'rgba(255,255,255,0.22)';
            ctx.fillRect(cx - g.barPx / 2, bTop, g.barPx, bH); ctx.restore();
          }
          ctx.strokeStyle = theme.dark ? 'rgba(0,0,0,0.25)' : 'rgba(0,0,0,0.09)';
          ctx.lineWidth = 0.5;
          ctx.strokeRect(cx - g.barPx / 2, bTop, g.barPx, bH);
        }
      }
    }
    ctx.restore();

    // ── value annotations ─────────────────────────────────────────────────
    if (st.show_values) {
      ctx.font = '9px monospace'; ctx.fillStyle = theme.tickText;
      for (let i = 0; i < g.n; i++) {
        for (let gi = 0; gi < g.groups; gi++) {
          const val = g.getVal(i, gi);
          const dv  = logScale ? Math.max(LC, val) : val;
          if (orient === 'h') {
            const cy    = g.yToPx(i) + g.groupOffsetPx(gi);
            const valPx = g.xToPx(dv);
            const above = val >= g.baseline;
            ctx.textAlign    = above ? 'left' : 'right';
            ctx.textBaseline = 'middle';
            ctx.fillText(fmtVal(val), valPx + (above ? 3 : -3), cy);
          } else {
            const cx    = g.xToPx(i) + g.groupOffsetPx(gi);
            const valPy = g.yToPx(dv);
            const above = val >= g.baseline;
            ctx.textAlign    = 'center';
            ctx.textBaseline = above ? 'bottom' : 'top';
            ctx.fillText(fmtVal(val), cx, valPy + (above ? -2 : 2));
          }
        }
      }
    }

    // ── axis borders ──────────────────────────────────────────────────────
    if (axisVis) {
    ctx.strokeStyle = theme.axisStroke; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(r.x, r.y + r.h); ctx.lineTo(r.x + r.w, r.y + r.h); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(r.x, r.y);         ctx.lineTo(r.x, r.y + r.h);       ctx.stroke();

    // Explicit baseline (only for linear scale)
    if (!logScale) {
      if (orient === 'h') {
        if (g.basePx > r.x && g.basePx < r.x + r.w) {
          ctx.strokeStyle = theme.axisStroke; ctx.lineWidth = 1.5;
          ctx.beginPath(); ctx.moveTo(g.basePx, r.y); ctx.lineTo(g.basePx, r.y + r.h); ctx.stroke();
        }
      } else {
        if (g.basePx > r.y && g.basePx < r.y + r.h) {
          ctx.strokeStyle = theme.axisStroke; ctx.lineWidth = 1.5;
          ctx.beginPath(); ctx.moveTo(r.x, g.basePx); ctx.lineTo(r.x + r.w, g.basePx); ctx.stroke();
        }
      }
    } // end axisVis (baseline)
    } // end axisVis (borders)

    // ── tick labels ───────────────────────────────────────────────────────
    if (axisVis) {
      ctx.font = (st.tick_size||10) + 'px monospace'; ctx.fillStyle = theme.tickText;

      if (orient === 'h') {
        // Value axis → X ticks at bottom
        if (xTicksVis) {
          ctx.textAlign = 'center'; ctx.textBaseline = 'top';
          if (logScale) {
            const lMin = Math.log10(Math.max(LC, dMin));
            const lMax = Math.log10(Math.max(LC, dMax));
            for (let exp = Math.floor(lMin); exp <= Math.ceil(lMax); exp++) {
              const v = Math.pow(10, exp);
              if (v < dMin || v > dMax) continue;
              const px = g.xToPx(v);
              if (px < r.x || px > r.x + r.w) continue;
              ctx.strokeStyle = theme.axisStroke;
              ctx.beginPath(); ctx.moveTo(px, r.y + r.h); ctx.lineTo(px, r.y + r.h + 4); ctx.stroke();
              ctx.fillStyle = theme.tickText;
              _drawTex(ctx, _fmtLogTick(v), px, r.y + r.h + 7,
                       st.tick_size||10, {align:'center', family:'monospace'});
            }
          } else {
            const valRange = (dMax - dMin) || 1;
            const valStep  = findNice(valRange / Math.max(2, Math.floor(r.w / 40)));
            for (let v = Math.ceil(dMin/valStep)*valStep; v <= dMax+valStep*0.01; v += valStep) {
              const px = g.xToPx(v);
              if (px < r.x || px > r.x + r.w) continue;
              ctx.strokeStyle = theme.axisStroke;
              ctx.beginPath(); ctx.moveTo(px, r.y + r.h); ctx.lineTo(px, r.y + r.h + 4); ctx.stroke();
              ctx.fillStyle = theme.tickText;
              ctx.fillText(fmtVal(v), px, r.y + r.h + 7);
            }
          }
          if (st.y_units) {
            ctx.textAlign='right'; ctx.textBaseline='top'; ctx.font='9px monospace';
            ctx.fillStyle=theme.unitText;
            ctx.fillText(st.y_units, r.x + r.w, r.y + r.h + 24);
            ctx.font='10px monospace';
          }
        }
        // Category axis → Y labels on left
        if (yTicksVis) {
          ctx.textAlign = 'right'; ctx.textBaseline = 'middle';
          const maxCatLabels = Math.max(1, Math.floor(r.h / 14));
          const catStep = Math.max(1, Math.ceil(g.n / maxCatLabels));
          for (let i = 0; i < g.n; i += catStep) {
            const cy    = g.yToPx(i);
            const label = xLabels[i] !== undefined ? String(xLabels[i]) : fmtVal(xCenters[i]);
            ctx.strokeStyle = theme.axisStroke;
            ctx.beginPath(); ctx.moveTo(r.x, cy); ctx.lineTo(r.x - 4, cy); ctx.stroke();
            ctx.fillStyle = theme.tickText;
            ctx.fillText(label, r.x - 7, cy);
          }
          if (st.units) {
            ctx.save();
            ctx.translate(Math.round(PAD_L * 0.28), r.y + r.h / 2); ctx.rotate(-Math.PI/2);
            ctx.textAlign='center'; ctx.textBaseline='middle';
            ctx.fillStyle=theme.unitText; ctx.font='9px monospace';
            ctx.fillText(st.units, 0, 0);
            ctx.restore();
          }
        }
      } else {
        // Category axis → X ticks at bottom
        if (xTicksVis) {
          ctx.textAlign = 'center'; ctx.textBaseline = 'top';
          const maxCatLabels = Math.max(1, Math.floor(r.w / 42));
          const catStep = Math.max(1, Math.ceil(g.n / maxCatLabels));
          for (let i = 0; i < g.n; i += catStep) {
            const cx    = g.xToPx(i);
            const label = xLabels[i] !== undefined ? String(xLabels[i]) : fmtVal(xCenters[i]);
            ctx.strokeStyle = theme.axisStroke;
            ctx.beginPath(); ctx.moveTo(cx, r.y + r.h); ctx.lineTo(cx, r.y + r.h + 4); ctx.stroke();
            ctx.fillStyle = theme.tickText;
            const catHw = ctx.measureText(label).width / 2;
            ctx.fillText(label, Math.min(Math.max(cx, catHw), p.pw - catHw), r.y + r.h + 7);
          }
          if (st.units && st.units !== 'px') {
            ctx.textAlign='right'; ctx.textBaseline='top'; ctx.font='9px monospace';
            ctx.fillStyle=theme.unitText;
            ctx.fillText(st.units, r.x + r.w, r.y + r.h + 24);
            ctx.font='10px monospace';
          }
        }
        // Value axis → Y ticks on left
        if (yTicksVis) {
          ctx.textAlign = 'right'; ctx.textBaseline = 'middle';
          if (logScale) {
            const lMin = Math.log10(Math.max(LC, dMin));
            const lMax = Math.log10(Math.max(LC, dMax));
            for (let exp = Math.floor(lMin); exp <= Math.ceil(lMax); exp++) {
              const v = Math.pow(10, exp);
              if (v < dMin || v > dMax) continue;
              const py = g.yToPx(v);
              if (py < r.y || py > r.y + r.h) continue;
              ctx.strokeStyle = theme.axisStroke;
              ctx.beginPath(); ctx.moveTo(r.x, py); ctx.lineTo(r.x - 5, py); ctx.stroke();
              ctx.fillStyle = theme.tickText;
              _drawTex(ctx, _fmtLogTick(v), r.x - 8, py,
                       st.tick_size||10, {align:'right', family:'monospace'});
            }
          } else {
            const valRange = (dMax - dMin) || 1;
            const valStep  = findNice(valRange / Math.max(2, Math.floor(r.h / 40)));
            for (let v = Math.ceil(dMin/valStep)*valStep; v <= dMax+valStep*0.01; v += valStep) {
              const py = g.yToPx(v);
              if (py < r.y || py > r.y + r.h) continue;
              ctx.strokeStyle = theme.axisStroke;
              ctx.beginPath(); ctx.moveTo(r.x, py); ctx.lineTo(r.x - 5, py); ctx.stroke();
              ctx.fillStyle = theme.tickText;
              ctx.fillText(fmtVal(v), r.x - 8, py);
            }
          }
          if (st.y_units) {
            ctx.save();
            ctx.translate(Math.round(PAD_L * 0.28), r.y + r.h / 2); ctx.rotate(-Math.PI/2);
            ctx.textAlign='center'; ctx.textBaseline='middle';
            ctx.fillStyle=theme.unitText; ctx.font='9px monospace';
            ctx.fillText(st.y_units, 0, 0);
            ctx.restore();
          }
        }
      }
    } // end axisVis

    // ── group legend (only when group_labels are provided) ────────────────
    if (g.groups > 1 && groupLabels.length > 0) {
      ctx.font = '9px monospace';
      const swatchW = 12, swatchH = 10, pad = 4, rowH = 15;
      let legendMaxW = 0;
      for (let gi = 0; gi < Math.min(g.groups, groupLabels.length); gi++) {
        legendMaxW = Math.max(legendMaxW, ctx.measureText(String(groupLabels[gi])).width);
      }
      const legendW = swatchW + pad + legendMaxW + 6;
      const nRows   = Math.min(g.groups, groupLabels.length);
      const legendH = nRows * rowH + 4;
      const lx = r.x + r.w - legendW - 4;
      const ly = r.y + 4;
      ctx.fillStyle = theme.dark ? 'rgba(0,0,0,0.45)' : 'rgba(255,255,255,0.75)';
      ctx.fillRect(lx, ly, legendW, legendH);
      ctx.strokeStyle = theme.axisStroke; ctx.lineWidth = 0.5;
      ctx.strokeRect(lx, ly, legendW, legendH);
      for (let gi = 0; gi < nRows; gi++) {
        const label = String(groupLabels[gi]);
        const ey    = ly + 2 + gi * rowH;
        ctx.fillStyle = groupColors[gi] || barColor;
        ctx.fillRect(lx + 3, ey + (rowH - swatchH) / 2, swatchW, swatchH);
        ctx.fillStyle = theme.tickText;
        ctx.textAlign = 'left'; ctx.textBaseline = 'middle';
        ctx.fillText(label, lx + 3 + swatchW + pad, ey + rowH / 2);
      }
    }

    // ── title ─────────────────────────────────────────────────────────────
    const titleBar = st.title || '';
    if (titleBar) {
      ctx.fillStyle = theme.tickText;
      ctx.textBaseline = 'middle';
      // Fixed PAD_T strip — clamp drawn size like 1D (2D strips grow instead).
      _drawTex(ctx, titleBar, r.x + r.w / 2, PAD_T / 2, _titlePx(st),
               { align: 'center', weight: 'bold' });
    }

    // ── axis labels ───────────────────────────────────────────────────────
    const xLabelBar = st.x_label || '';
    const yLabelBar = st.y_label || '';
    if (xLabelBar) {
      ctx.fillStyle = theme.tickText; ctx.textBaseline = 'top';
      _drawTex(ctx, xLabelBar, r.x + r.w / 2, r.y + r.h + 26,
               st.x_label_size || 10, { align: 'center' });
    }
    if (yLabelBar) {
      ctx.save();
      const ylpxBar = st.y_label_size || 10;
      ctx.translate(Math.max(Math.round(PAD_L * 0.1), Math.ceil(ylpxBar*0.62)+1),
                    r.y + r.h / 2);
      ctx.rotate(-Math.PI / 2);
      ctx.fillStyle = theme.tickText; ctx.textBaseline = 'middle';
      _drawTex(ctx, yLabelBar, 0, 0, ylpxBar, { align: 'center' });
      ctx.restore();
    }

    // Overlay widgets (vlines, hlines) drawn on overlay canvas
    drawOverlay1d(p);
  }

  function _attachEventsBar(p) {
    const { overlayCanvas } = p;

    // Returns {slot, group} for the bar at canvas (mx,my), or null if none.
    function _barHit(mx, my) {
      const st = p.state;
      if (!st || !st.values || !st.values.length) return null;
      const r  = _plotRect1d(p);
      if (mx < r.x || mx > r.x + r.w || my < r.y || my > r.y + r.h) return null;
      const g  = _barGeom(st, r);
      const LC = g.LC;
      for (let i = 0; i < g.n; i++) {
        for (let gi = 0; gi < g.groups; gi++) {
          const val = g.getVal(i, gi);
          const dv  = g.logScale ? Math.max(LC, val) : val;
          if (g.orient === 'h') {
            const cy    = g.yToPx(i) + g.groupOffsetPx(gi);
            const valPx = g.xToPx(dv);
            const left  = Math.min(valPx, g.basePx);
            const bW    = Math.max(1, Math.abs(valPx - g.basePx));
            if (Math.abs(my - cy) <= g.barPx / 2 && mx >= left && mx <= left + bW)
              return { slot: i, group: gi };
          } else {
            const cx    = g.xToPx(i) + g.groupOffsetPx(gi);
            const valPy = g.yToPx(dv);
            const top   = Math.min(valPy, g.basePx);
            const bH    = Math.max(1, Math.abs(valPy - g.basePx));
            if (Math.abs(mx - cx) <= g.barPx / 2 && my >= top && my <= top + bH)
              return { slot: i, group: gi };
          }
        }
      }
      return null;
    }

    // Widget drag support
    const _scheduleCommit = _makeCommitter(() => model.save_changes());
    const settled = _makeSettledScheduler(p);

    overlayCanvas.addEventListener('mousedown', (e) => {
      if (e.button !== 0) return;
      const {mx:_bmx, my:_bmy} = _clientPos(e, overlayCanvas, p.pw, p.ph);
      const hit = _ovHitTest1d(_bmx, _bmy, p);
      if (hit) {
        p.ovDrag = hit;
        p.lastWidgetId = (p.state.overlay_widgets || [])[hit.idx]?.id || null;
        overlayCanvas.style.cursor = 'ew-resize';
        e.preventDefault();
      }
    });

    document.addEventListener('mousemove', (e) => {
      if (!p.ovDrag) return;
      _doDrag1d(e, p);
      const _dw = (p.state.overlay_widgets || [])[p.ovDrag.idx] || {};
      _emitEvent(p.id, 'pointer_move', _dw.id || null, {..._dw, ..._pointerFields(e)});
    });

    document.addEventListener('mouseup', (e) => {
      settled.clear();
      if (!p.ovDrag) return;
      const _idx = p.ovDrag.idx;
      const _dw  = (p.state.overlay_widgets || [])[_idx] || {};
      const _did = _dw.id || null;
      p.ovDrag = null;
      overlayCanvas.style.cursor = 'default';
      model.set(`panel_${p.id}_json`, _viewStateJson(p));
      _emitEvent(p.id, 'pointer_up', _did, {..._dw, ..._pointerFields(e), button: e.button});
      _scheduleCommit();
    });

    overlayCanvas.addEventListener('mousemove', (e) => {
      const {mx, my} = _clientPos(e, overlayCanvas, p.pw, p.ph);
      p.mouseX = mx; p.mouseY = my;
      if (p.ovDrag) return;
      const st = p.state; if (!st) return;

      // Overlay widget cursor hint
      const whit = _ovHitTest1d(mx, my, p);
      if (whit) {
        overlayCanvas.style.cursor = 'ew-resize';
        tooltip.style.display = 'none';
        if (p._hovBar !== null) { p._hovBar = null; drawBar(p); }
        return;
      }

      const hit = _barHit(mx, my);
      const prev = p._hovBar;
      const same = hit !== null && prev !== null &&
                   prev.slot === hit.slot && prev.group === hit.group;
      if (!same) { p._hovBar = hit; drawBar(p); }

      if (hit !== null) {
        const { slot: idx, group: gi } = hit;
        const label = (st.x_labels||[])[idx] !== undefined
          ? String(st.x_labels[idx])
          : fmtVal((st.x_centers||[])[idx] ?? idx);
        const gLabel = (st.group_labels||[])[gi];
        const gm  = _barGeom(st, _plotRect1d(p));
        const val = gm.getVal(idx, gi);
        const tip = (st.groups > 1 && gLabel)
          ? `${gLabel} | ${label}: ${fmtVal(val)}`
          : `${label}: ${fmtVal(val)}`;
        _showTooltip(tip, e.clientX, e.clientY);
        overlayCanvas.style.cursor = 'pointer';
      } else {
        tooltip.style.display = 'none';
        overlayCanvas.style.cursor = 'default';
      }
      settled.arm(mx, my, e);
    });

    overlayCanvas.addEventListener('mouseleave', (e) => {
      settled.clear();
      _emitEvent(p.id, 'pointer_leave', null, {..._pointerFields(e), x: e.offsetX, y: e.offsetY});
      if (p._hovBar !== null) { p._hovBar = null; drawBar(p); }
      tooltip.style.display = 'none';
    });

    overlayCanvas.addEventListener('mousedown', (e) => {
      if (p.ovDrag) return;
      const st = p.state; if (!st) return;
      const {mx:_cmx, my:_cmy} = _clientPos(e, overlayCanvas, p.pw, p.ph);
      const hit = _barHit(_cmx, _cmy);
      const _baseFields = {..._pointerFields(e), button: e.button, x: _cmx, y: _cmy};
      if (hit === null) {
        _emitEvent(p.id, 'pointer_down', null, {
          bar_index:   null,
          group_index: null,
          value:       null,
          x_label:     null,
          ..._baseFields,
        });
        return;
      }
      const { slot: idx, group: gi } = hit;
      const gm  = _barGeom(st, _plotRect1d(p));
      const val = gm.getVal(idx, gi);
      _emitEvent(p.id, 'pointer_down', null, {
        bar_index:   idx,
        group_index: gi,
        value:       val,
        group_value: val,
        x_center:    (st.x_centers||[])[idx] ?? idx,
        x_label:     (st.x_labels||[])[idx] !== undefined
                       ? String(st.x_labels[idx]) : null,
        ..._baseFields,
      });
    });

    // Keyboard: all keys forwarded to Python unconditionally; no built-in bar shortcuts.
    overlayCanvas.addEventListener('keydown', (e) => {
      const st = p.state; if (!st) return;
      _emitEvent(p.id, 'key_down', null, {
        time_stamp: performance.now() / 1000,
        modifiers: _modifiers(e),
        key: e.key,
        last_widget_id: p.lastWidgetId || null,
        x: p.mouseX ?? 0, y: p.mouseY ?? 0,
      });
    });
    overlayCanvas.addEventListener('keyup', (e) => {
      _emitEvent(p.id, 'key_up', null, {
        time_stamp: performance.now() / 1000,
        modifiers: _modifiers(e),
        key: e.key,
        x: p.mouseX ?? 0, y: p.mouseY ?? 0,
      });
    });
    overlayCanvas.tabIndex = 0;
    overlayCanvas.style.outline = 'none';
    overlayCanvas.addEventListener('mouseenter', (e) => {
      overlayCanvas.focus();
      _emitEvent(p.id, 'pointer_enter', null, {..._pointerFields(e), x: e.offsetX, y: e.offsetY});
    });
    overlayCanvas.addEventListener('dblclick', (e) => {
      const {mx, my} = _clientPos(e, overlayCanvas, p.pw, p.ph);
      _emitEvent(p.id, 'double_click', null, {..._pointerFields(e), button: e.button, x: mx, y: my, xdata: null});
    });
    overlayCanvas.addEventListener('wheel', (e) => {
      _emitEvent(p.id, 'wheel', null, {
        time_stamp: performance.now() / 1000,
        modifiers: _modifiers(e),
        x: p.mouseX ?? 0, y: p.mouseY ?? 0,
        dx: e.deltaX, dy: e.deltaY,
      });
    }, { passive: true });
  }

  // ── generic redraw ────────────────────────────────────────────────────────
  function _redrawPanel(p) {
    if(!p.state) return;
    if(p.kind==='2d')      draw2d(p);
    else if(p.kind==='3d') draw3d(p);
    else if(p.kind==='bar') drawBar(p);
    else                   draw1d(p);
    // Region indications track the parent's zoom/pan: any panel redraw
    // refreshes ALL callouts (cheap no-op when there are none). Redrawing all
    // (not just this panel's) keeps rect + leaders consistent when a parent
    // and its inset live in different panels.
    _drawCallouts();
  }

  function redrawAll() {
    for(const p of panels.values()) _redrawPanel(p);
    _drawCallouts();
  }

  // ── PNG export ────────────────────────────────────────────────────────────
  // Composite the WHOLE figure (all panels, insets, background) onto one
  // offscreen canvas and return a PNG data URL.  Used by handle.exportPNG()
  // and the standalone-HTML postMessage export protocol.
  //
  //   opts.scale          extra multiplier on top of devicePixelRatio (1)
  //   opts.includeWidgets include the interactive overlay canvas (false)
  //
  // The composite is positioned by each element's on-screen bounding box
  // relative to the figure background (`gridDiv`), so multi-panel grids and
  // corner insets export as one correctly-arranged image without re-deriving
  // any layout math.  Elements are drawn in DOM/z-order per panel: gpuCanvas
  // (beneath) → plotCanvas → [overlayCanvas] → markersCanvas → axis canvases →
  // colorbar → scale bar → title.  Status bars and other hover chrome are
  // excluded.
  function exportPNG(opts) {
    const o = opts || {};
    const scale = (o.scale != null && o.scale > 0) ? o.scale : 1;
    const includeWidgets = !!o.includeWidgets;
    const outScale = (window.devicePixelRatio || 1) * scale;

    // WebGPU hazard: a WebGPU canvas's drawing buffer is only valid right after
    // its render pass.  Force a synchronous re-render of every active-GPU 2-D
    // panel FIRST, then composite in the SAME task — so drawImage(gpuCanvas)
    // reads freshly-rendered pixels instead of a blank/cleared buffer.
    for (const p of panels.values()) {
      if (p.kind === '2d' && p._gpu === 'active' && p._gpuImg
          && p.gpuCanvas && p.gpuCanvas.style.display !== 'none') {
        try { draw2d(p); } catch (_) {}
      }
    }

    // The figure background element (grid) defines the ORIGIN for every
    // relative rect.  Its top-left is the figure's top-left; the grid tracks are
    // fixed-px and left-anchored, so panel canvases sit at the correct offset
    // even if the grid container itself stretches wider than the figure (it can
    // in a bare mount() page with no .apl-outer inline-block CSS constraining
    // it).  So take the ORIGIN from the DOM but the EXTENT from the true figure
    // size — fig_width/height (the grid content) + the 8 px gridDiv padding on
    // each side — rather than the possibly-stretched gridDiv width.
    const rootRect = gridDiv.getBoundingClientRect();
    const GRID_PAD = 8;   // gridDiv padding (see the gridDiv cssText)
    const figW = Number(model.get('fig_width'))  || 0;
    const figH = Number(model.get('fig_height')) || 0;
    // Fall back to the measured content box if the model lacks sizes.
    const contentW = figW ? figW + 2 * GRID_PAD : rootRect.width;
    const contentH = figH ? figH + 2 * GRID_PAD : rootRect.height;
    const W = Math.max(1, Math.round(contentW * outScale));
    const H = Math.max(1, Math.round(contentH * outScale));

    const out = document.createElement('canvas');
    out.width = W; out.height = H;
    const octx = out.getContext('2d');
    if (!octx) return Promise.reject(new Error('exportPNG: 2D context unavailable'));
    octx.imageSmoothingEnabled = false;

    // Figure background first (matches the on-screen gridDiv background).
    octx.fillStyle = theme.bg;
    octx.fillRect(0, 0, W, H);

    // Draw one element scaled into the output at its position relative to root.
    // Skips hidden (display:none) or zero-area elements; catches per-element
    // draw failures (a tainted / uninitialised canvas) so one bad layer never
    // aborts the whole export.
    //
    // Coordinates are SNAPPED to output pixels: dx/dy round the element's
    // top-left, and dw/dh are derived from the ROUNDED right/bottom edges
    // (not by rounding width/height directly). Two adjacent elements that
    // share a boundary (e.g. neighbouring grid panels) therefore round to the
    // exact same output-pixel edge on both sides, instead of each picking up
    // an independent +/-1 px from its own width/height rounding — which is
    // what caused 1 px seams / overlaps at fractional scale (e.g. scale:1.25).
    // `rectElm` (defaults to `elm`) supplies the on-screen position/visibility
    // — used to blit an offscreen scratch canvas (no DOM rect of its own) at
    // the position of the live element it stands in for (see
    // _drawPanelWidgetsNoHandles below).
    const _drawEl = (elm, rectElm) => {
      if (!elm) return;
      const re = rectElm || elm;
      const cs = window.getComputedStyle(re);
      if (cs.display === 'none' || cs.visibility === 'hidden') return;
      // A canvas with 0×0 backing store has nothing to blit.
      if (elm.width === 0 || elm.height === 0) return;
      const r = re.getBoundingClientRect();
      if (r.width === 0 || r.height === 0) return;
      const left   = (r.left   - rootRect.left) * outScale;
      const top    = (r.top    - rootRect.top)  * outScale;
      const right  = (r.right  - rootRect.left) * outScale;
      const bottom = (r.bottom - rootRect.top)  * outScale;
      const dx = Math.round(left);
      const dy = Math.round(top);
      const dw = Math.round(right)  - dx;
      const dh = Math.round(bottom) - dy;
      if (dw <= 0 || dh <= 0) return;
      try { octx.drawImage(elm, dx, dy, dw, dh); } catch (_) {}
    };

    // Widget handle/node dots are edit-mode chrome (like figure-marker handles
    // — see _drawFigureMarkers(null, true) below), not exported content.  For
    // includeWidgets:true, redraw the panel's widgets onto a scratch canvas
    // (same backing size + DPR transform as the live overlayCanvas) with
    // handles forced off, and blit THAT (positioned via the live
    // overlayCanvas's own on-screen rect) instead of the live p.overlayCanvas
    // — so the on-screen canvas (and any handles currently visible on it) is
    // never touched, no flicker.
    const _drawPanelWidgetsNoHandles = (p) => {
      if (!p.overlayCanvas || !p.ovCtx) return null;
      const oc = p.overlayCanvas;
      if (oc.width === 0 || oc.height === 0) return null;
      const scratch = document.createElement('canvas');
      scratch.width = oc.width; scratch.height = oc.height;
      const sctx = scratch.getContext('2d');
      if (!sctx) return null;
      sctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      try {
        drawOverlay2d(p, { ctx: sctx, imgW: p.imgW, imgH: p.imgH, forceNoHandles: true });
      } catch (_) { return null; }
      return scratch;
    };

    // Per-panel canvas stack, in visual z-order (see _buildCanvasStack).
    const _drawPanel = (p) => {
      _drawEl(p.gpuCanvas);      // z 0 — GPU image raster (beneath)
      _drawEl(p.plotCanvas);     // z 1 — image blit + inline decorations
      _drawEl(p.yAxisCanvas);    // physical axis gutters (no explicit z)
      _drawEl(p.xAxisCanvas);
      _drawEl(p.cbCanvas);       // colorbar strip + label
      if (includeWidgets) {      // z 5 — interactive widgets, handles suppressed
        const scratch = _drawPanelWidgetsNoHandles(p);
        if (scratch) _drawEl(scratch, p.overlayCanvas); else _drawEl(p.overlayCanvas);
      }
      _drawEl(p.markersCanvas);  // z 6 — static marker groups
      _drawEl(p.scaleBar);       // z 7 — physical scale bar
      _drawEl(p.titleCanvas);    // z 8 — 2-D title strip
      // (statusBar / statsDiv are hover chrome — intentionally excluded.)
    };

    // Inset title bars are plain DOM (titleSpan text node), not a canvas, so
    // _drawEl (which only blits drawImage-able elements) never captures them.
    // Draw the title text directly onto the output canvas, positioned at the
    // titleBar's on-screen rect, approximating the CSS declared in
    // _createInsetDOM (11px sans-serif, theme.tickText colour, left-padded).
    const _drawInsetTitle = (p) => {
      if (!p.isInset || !p.titleBar || !p.insetSpec) return;
      const title = p.insetSpec.title;
      if (!title) return;
      const cs = window.getComputedStyle(p.titleBar);
      if (cs.display === 'none' || cs.visibility === 'hidden') return;
      const r = p.titleBar.getBoundingClientRect();
      if (r.width === 0 || r.height === 0) return;
      const left = (r.left - rootRect.left) * outScale;
      const top  = (r.top  - rootRect.top)  * outScale;
      octx.save();
      octx.fillStyle = theme.tickText;
      octx.textBaseline = 'middle';
      octx.textAlign = 'left';
      // 8px left padding matches titleBar's `padding:0 5px 0 8px`.
      _drawTex(octx, title, left + 8 * outScale, top + r.height * outScale / 2,
               11 * outScale, { align: 'left' });
      octx.restore();
    };

    // Grid panels first, then insets on top (insets sit above grid content).
    for (const p of panels.values()) if (!p.isInset) _drawPanel(p);
    for (const p of panels.values()) if (p.isInset)  { _drawPanel(p); _drawInsetTitle(p); }

    // Callout indications (dashed source rects + leader lines) sit above panel
    // content and insets — composite them last so they overlay everything.
    // Force a fresh draw first so the canvas reflects the current view.
    try { _drawCallouts(); } catch (_) {}
    _drawEl(calloutCanvas);

    // Figure-level annotation layer is CONTENT — always composited (handles
    // suppressed for export). Hover/selection outlines are DOM styles and are
    // never on a canvas, so they are inherently excluded.
    try { _drawFigureMarkers(null, true); } catch (_) {}
    _drawEl(figMarkerCanvas);
    // Restore the on-screen draw (handles visible again if in edit mode).
    try { _drawFigureMarkers(); } catch (_) {}

    let dataUrl;
    try {
      dataUrl = out.toDataURL('image/png');
    } catch (e) {
      return Promise.reject(new Error('exportPNG: toDataURL failed — ' + e));
    }
    return Promise.resolve({ dataUrl, width: W, height: H });
  }

  // ── cell-aware CSS scaling ────────────────────────────────────────────────
  // When the notebook cell (or any container) is narrower than the figure's
  // native size, apply CSS transform:scale() to outerDiv so it shrinks
  // proportionally without re-rendering canvases or writing to the model.
  // Full canvas resolution is preserved; CSS transforms correctly route
  // pointer events so all interactive features (drag, zoom, pan) keep working.
  // Also called after layout/resize changes so the scale stays in sync.
  //
  // Prerequisite: .apl-outer must carry `min-width: max-content` (set in the
  // _css traitlet).  Without it, the inline-block shrinks to match its
  // constrained parent and outerDiv.offsetWidth == cellW, giving s = 1 always.
  function _applyScale() {
    const cellW = el.getBoundingClientRect().width;
    if (!cellW) return;
    // offsetWidth is the pre-transform layout width — unaffected by any
    // currently applied transform AND pinned ≥ content width by
    // min-width:max-content, so it always reflects the true native figure size.
    const nativeW = outerDiv.offsetWidth;
    const nativeH = outerDiv.offsetHeight;
    if (!nativeW) return;
    const s = Math.min(1.0, cellW / nativeW);
    // transform-origin:top left (set in _css) means scale(s) shrinks the
    // figure from the top-left corner.  With width:100% on scaleWrap the
    // scaled figure (nativeW*s ≤ cellW) always fits — no overflow, no
    // clipping, no cross-browser layout-box vs visual-box discrepancies.
    outerDiv.style.transform = s < 1 ? `scale(${s})` : '';
    // transform:scale does not affect layout — outerDiv still occupies
    // nativeH px in the flow even when visually shorter.  A negative
    // marginBottom compensates exactly, pulling subsequent content up by
    // the difference without ever touching scaleWrap's own dimensions.
    // This eliminates any ResizeObserver feedback loop.
    outerDiv.style.marginBottom = (s < 1 && nativeH)
      ? Math.round(nativeH * (s - 1)) + 'px'
      : '';
  }

  if (typeof ResizeObserver !== 'undefined') {
    let _lastCellW = 0;
    let _lastRoW = 0, _lastRoH = 0;
    let _roTimer = null;
    new ResizeObserver(entries => {
      const cr = entries[0].contentRect;
      const cellW = cr.width, cellH = cr.height;
      // (1) Jupyter fit-to-cell down-scale — width-only to avoid a feedback
      // loop (our own scaleWrap height updates would re-trigger the observer).
      if (cellW !== _lastCellW) {
        _lastCellW = cellW;
        requestAnimationFrame(_applyScale);
      }
      // (2) Container-resize hook for an embedding host (SpyDE): fire onResize
      // with the new root-container CSS px so the host can drive a real
      // relayout (e.g. handle.resize(w,h) → fig_width/height → applyLayout).
      // Debounced (rAF-coalesced trailing) so a drag-resize fires once on
      // settle, not per-frame.  Fires on width OR height change; the host owns
      // whether to scale, relayout, or ignore.
      if (typeof onResize === 'function' &&
          (Math.round(cellW) !== _lastRoW || Math.round(cellH) !== _lastRoH)) {
        _lastRoW = Math.round(cellW); _lastRoH = Math.round(cellH);
        if (_roTimer) cancelAnimationFrame(_roTimer);
        _roTimer = requestAnimationFrame(() => {
          _roTimer = null;
          try { onResize({ width: _lastRoW, height: _lastRoH }); } catch (_) {}
        });
      }
    }).observe(el);
    requestAnimationFrame(_applyScale);
  }

  // ── model listeners ───────────────────────────────────────────────────────
  model.on('change:layout_json', () => { applyLayout(); redrawAll(); requestAnimationFrame(_applyScale); });
  model.on('change:fig_width change:fig_height', () => { applyLayout(); redrawAll(); requestAnimationFrame(_applyScale); });

  // Toggle the per-panel stats overlay when display_stats changes.
  // Hiding is immediate; showing waits for the next natural redraw to
  // populate the overlay text — but we also call redrawAll() here so the
  // stats appear instantly without having to interact with the figure first.
  model.on('change:display_stats', () => {
    const show = model.get('display_stats');
    for (const p of panels.values()) {
      if (!show && p.statsDiv) {
        p.statsDiv.style.display = 'none';
      }
    }
    if (show) redrawAll();
  });

  // Python→JS targeted widget update (source:"python" in event_json).
  // Applies changed fields directly to the widget in overlay_widgets and
  // redraws the panel — no image re-decode, no Python echo.
  model.on('change:event_json', () => {
    try {
      const msg = JSON.parse(model.get('event_json') || '{}');
      if (!msg || msg.source !== 'python') return;
      const p = panels.get(msg.panel_id);
      if (!p || !p.state) return;
      const ws = p.state.overlay_widgets || [];
      const wi = ws.findIndex(w => w.id === msg.widget_id);
      if (wi < 0) return;
      // Apply every field from the message except protocol keys
      const skip = new Set(['source', 'panel_id', 'widget_id']);
      for (const [k, v] of Object.entries(msg)) {
        if (!skip.has(k)) ws[wi][k] = v;
      }
      _redrawPanel(p);
    } catch(_) {}
  });

  // ── edit-chrome / figure-marker listeners ─────────────────────────────────
  model.on('change:edit_chrome',    () => { _applyEditMode(); });
  model.on('change:selected_panel', () => { _applyPanelChrome(); });
  model.on('change:figure_markers_json', () => { _loadFigMarkers(); _drawFigureMarkers(); });

  // ── initial render ────────────────────────────────────────────────────────
  _loadFigMarkers();
  applyLayout();
  _applyEditMode();

  // Internal API surface returned to mount().  anywidget ignores render()'s
  // return value; mount() captures it so its handle can reach the closure's
  // panel map + drawing helpers (exportPNG, dispose) that are otherwise
  // inaccessible from module scope.
  return {
    panels,
    exportPNG,
    calloutCanvas,      // figure-level region-indication overlay
    _drawCallouts,      // force a callout redraw (tests / external layout sync)
    figMarkerCanvas,    // figure-level annotation overlay (content, exported)
    _drawFigureMarkers, // force a figure-marker redraw (tests / external sync)
    _gpuDisposeImagePanel,
    _gpuDisposePanel,
  };
}

export default { render };

// ═══════════════════════════════════════════════════════════════════════════
// Embedding API — use anyplotlib WITHOUT Jupyter or the anywidget runtime.
//
// For Electron apps, MDI sub-windows, or any plain web page:
//
//   import apl, { mount } from './figure_esm.js';
//
//   const handle = mount(document.getElementById('plot'), state, {
//     onEvent: (ev) => console.log(ev.event_type, ev.xdata, ev.ydata),
//   });
//   handle.setPanelState(panelId, newPanelState);   // live data update
//   handle.resize(800, 500);
//   handle.dispose();
//
// `state` is the serialised figure state produced by the Python side:
// `anyplotlib.embed.figure_state(fig)` — a plain JSON dict of
// {layout_json, fig_width, fig_height, event_json, panel_<id>_json, ...}.
//
// For a live Python backend (e.g. an Electron app with a Python sidecar over
// WebSocket/stdio), pair `mount(..., {onSync})` with
// `anyplotlib.embed.FigureBridge` on the Python side:
//   JS → Python:  onSync(key, value)            → bridge.receive(key, value)
//   Python → JS:  FigureBridge(fig, send=...)   → handle.applyUpdate(key, value)
// ═══════════════════════════════════════════════════════════════════════════

// Minimal stand-in for the anywidget model: get/set/save_changes/on/off.
// set() fires per-key listeners synchronously (matching anywidget semantics);
// save_changes() flushes dirty keys to the optional outbound sync handler.
export function createLocalModel(initialState) {
  const _data   = Object.assign({}, initialState || {});
  const _cbs    = {};
  const _anyCbs = [];
  const _dirty  = new Set();
  let _onSync   = null;

  return {
    get(key) { return _data[key]; },
    set(key, val) {
      _data[key] = val;
      _dirty.add(key);
      const ev = 'change:' + key;
      if (_cbs[ev]) for (const cb of [..._cbs[ev]]) { try { cb({ new: val }); } catch (_) {} }
      for (const cb of [..._anyCbs]) { try { cb(); } catch (_) {} }
    },
    save_changes() {
      const keys = [..._dirty];
      _dirty.clear();
      if (_onSync) {
        for (const k of keys) { try { _onSync(k, _data[k]); } catch (_) {} }
      }
    },
    on(event, cb) {
      if (event === 'change') { _anyCbs.push(cb); return; }
      (_cbs[event] = _cbs[event] || []).push(cb);
    },
    off(event, cb) {
      if (!event) { for (const k in _cbs) _cbs[k] = []; _anyCbs.length = 0; return; }
      if (_cbs[event]) _cbs[event] = _cbs[event].filter((c) => c !== cb);
    },
    // Apply an update that originated OUTSIDE this view (e.g. from a Python
    // bridge): listeners fire so the figure re-renders, but the key is not
    // marked dirty, so it is never echoed back through onSync.
    applyRemote(key, val) {
      this.set(key, val);
      _dirty.delete(key);
    },
    _setSyncHandler(fn) { _onSync = fn; },
    get model() { return this; },
  };
}

// Mount a figure into *el* and return a control handle.
//   opts.onEvent(ev)        — parsed interaction events (pointer/key/wheel …)
//   opts.onSync(key, value) — raw outbound model writes, for a Python bridge
//   opts.onResize({width,height}) — fired (debounced) when the ROOT CONTAINER
//                             el resizes, so the host can relayout the figure
//                             to its new box (e.g. call handle.resize(w,h)).
export function mount(el, state, opts) {
  // Diagnostic marker: proves THIS (WebGPU-2D) build of figure_esm.js is loaded.
  try { globalThis.__apl_build = 'webgpu-2d'; } catch (_) {}
  const o = opts || {};
  const model = createLocalModel(state);
  if (o.onSync) model._setSyncHandler(o.onSync);
  if (o.onEvent) {
    model.on('change:event_json', () => {
      try {
        const ev = JSON.parse(model.get('event_json') || '{}');
        if (ev && ev.event_type && ev.source !== 'python') o.onEvent(ev);
      } catch (_) {}
    });
  }
  // Capture render()'s internal API so the handle can reach the closure's
  // panel map + drawing helpers (exportPNG / GPU dispose).  opts.onResize (if
  // given) is fired with {width,height} when the ROOT CONTAINER resizes, so an
  // embedding host can relayout the figure to its new box.
  const api = render({ model, el, onResize: o.onResize }) || {};
  return {
    model,
    api,               // internal render() API (panels, calloutCanvas, _drawCallouts, …)
    get(key) { return model.get(key); },
    set(key, value) { model.set(key, value); model.save_changes(); },
    // Replace one panel's full state (object or pre-serialised JSON string).
    setPanelState(panelId, panelState) {
      const v = typeof panelState === 'string' ? panelState : JSON.stringify(panelState);
      this.set('panel_' + panelId + '_json', v);
    },
    // Inbound update from a Python bridge — renders without echoing to onSync.
    applyUpdate(key, value) { model.applyRemote(key, value); },
    resize(width, height) {
      model.set('fig_width', Math.round(width));
      model.set('fig_height', Math.round(height));
      model.save_changes();
    },
    // Composite the whole figure to a PNG data URL.
    //   opts.scale (1)               extra multiplier over devicePixelRatio
    //   opts.includeWidgets (false)  include the interactive widget overlay
    // Resolves to {dataUrl, width, height}; rejects with a useful message.
    exportPNG(opts) {
      if (typeof api.exportPNG !== 'function') {
        return Promise.reject(new Error('exportPNG unavailable (render() returned no API)'));
      }
      try { return api.exportPNG(opts); }
      catch (e) { return Promise.reject(e); }
    },
    // Remove the figure's DOM.  (Window-level listeners registered by the
    // renderer are inert once the DOM is gone; for complete cleanup, discard
    // the containing element or iframe.)
    dispose() {
      // Free GPU resources for every panel before tearing down the DOM.
      try { if (api.panels) for (const p of api.panels.values()) {
        api._gpuDisposeImagePanel(p); api._gpuDisposePanel(p);
      } } catch (_) {}
      model.off(); el.replaceChildren();
    },
  };
}







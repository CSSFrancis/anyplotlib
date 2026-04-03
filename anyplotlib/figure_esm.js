// figure_esm.js
// Unified JS renderer for the Figure widget.
// Each panel gets its own three-canvas stack (plot / overlay / markers).
// Panels are drawn independently; only the changed panel's listener fires.

function render({ model, el }) {
  const dpr = window.devicePixelRatio || 1;

  // ── shared plot-area padding (mirrors 1D drawing constants) ─────────────
  // The image/plot area for BOTH 1D and 2D panels sits at:
  //   x: PAD_L → pw-PAD_R,   y: PAD_T → ph-PAD_B
  // This guarantees pixel-perfect alignment of all panels in a row/column.
  const PAD_L=58, PAD_R=12, PAD_T=12, PAD_B=42;

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
    if(a>=1)   return v.toFixed(2);
    if(a>=1e-2)return v.toFixed(4);
    return v.toExponential(1);
  }
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

  // Resize handle (figure-level)
  const resizeHandle = document.createElement('div');
  resizeHandle.style.cssText =
    'position:absolute;bottom:2px;right:2px;width:16px;height:16px;cursor:nwse-resize;' +
    'background:linear-gradient(135deg,transparent 50%,#888 50%);border-radius:0 0 4px 0;z-index:100;';
  resizeHandle.title = 'Drag to resize figure';
  outerDiv.appendChild(resizeHandle);

  const sizeLabel = document.createElement('div');
  sizeLabel.style.cssText =
    'position:absolute;bottom:22px;right:22px;padding:3px 7px;background:rgba(0,0,0,0.7);' +
    'color:white;font-size:11px;border-radius:4px;display:none;pointer-events:none;z-index:21;';
  outerDiv.appendChild(sizeLabel);

  // Tooltip (shared across all panels)
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

    const seen = new Set();
    for (const spec of panel_specs) {
      seen.add(spec.id);
      if (!panels.has(spec.id)) {
        _createPanelDOM(spec.id, spec.kind, spec.panel_width, spec.panel_height, spec);
      } else {
        _resizePanelDOM(spec.id, spec.panel_width, spec.panel_height);
      }
    }
    for (const [id, p] of panels) {
      if (!seen.has(id)) { p.cell.remove(); panels.delete(id); }
    }
  }

  function _createPanelDOM(id, kind, pw, ph, spec) {
    const cell = document.createElement('div');
    cell.style.cssText = 'position:relative;overflow:visible;line-height:0;display:flex;justify-content:center;align-items:flex-start;';
    cell.style.gridRow    = `${spec.row_start+1} / ${spec.row_stop+1}`;
    cell.style.gridColumn = `${spec.col_start+1} / ${spec.col_stop+1}`;
    gridDiv.appendChild(cell);

    let plotCanvas, overlayCanvas, markersCanvas, statusBar;
    let xAxisCanvas=null, yAxisCanvas=null, scaleBar=null;
    let _p2d = null;   // extra 2D DOM refs, null for 1D panels
    let _wrapNode = null;  // container to which statsDiv is appended

    if (kind === '2d') {
      // ── 2D branch ──────────────────────────────────────────────────────────
      // The outer container is exactly pw×ph — same as the 1D canvas.
      // Inside it everything is absolutely positioned to mirror 1D's _plotRect1d:
      //   image area : [PAD_L, PAD_T] → [pw-PAD_R, ph-PAD_B]
      //   y-axis     : [0, PAD_T]     → [PAD_L,    ph-PAD_B]
      //   x-axis     : [PAD_L, ph-PAD_B] → [pw-PAD_R, ph]
      // This makes the bottom-left corner of the image/plot areas line up exactly.

      const plotWrap = document.createElement('div');
      plotWrap.style.cssText = `position:relative;display:inline-block;line-height:0;` +
        `width:${pw}px;height:${ph}px;overflow:visible;flex-shrink:0;`;

      // Image canvas — positioned at the inner plot area
      plotCanvas = document.createElement('canvas');
      plotCanvas.style.cssText = `position:absolute;display:block;border-radius:2px;background:${theme.bgCanvas};`;

      // Overlay + marker canvases (same size as plotCanvas, stacked on top)
      overlayCanvas = document.createElement('canvas');
      overlayCanvas.style.cssText = 'position:absolute;z-index:5;cursor:default;pointer-events:all;outline:none;';
      overlayCanvas.tabIndex = 0;
      markersCanvas = document.createElement('canvas');
      markersCanvas.style.cssText = 'position:absolute;pointer-events:none;z-index:6;';

      // Scale bar: single canvas drawn on demand
      scaleBar = document.createElement('canvas');
      scaleBar.style.cssText =
        'position:absolute;pointer-events:none;display:none;z-index:7;';
      const sbLine  = null;   // unused — drawing handled by canvas
      const sbLabel = null;   // unused — drawing handled by canvas
      plotWrap.appendChild(scaleBar);

      // Status bar: absolute, bottom-left of image area
      statusBar = document.createElement('div');
      statusBar.style.cssText =
        'position:absolute;padding:2px 6px;' +
        'background:rgba(0,0,0,0.55);color:white;font-size:10px;font-family:monospace;' +
        'border-radius:4px;pointer-events:none;white-space:nowrap;display:none;z-index:9;';

      // y-axis canvas: left gutter [0, PAD_T]..[PAD_L, ph-PAD_B]
      yAxisCanvas = document.createElement('canvas');
      yAxisCanvas.style.cssText = `position:absolute;display:none;background:${theme.axisBg};`;

      // x-axis canvas: bottom gutter [PAD_L, ph-PAD_B]..[pw-PAD_R, ph]
      xAxisCanvas = document.createElement('canvas');
      xAxisCanvas.style.cssText = `position:absolute;display:none;background:${theme.axisBg};`;

      // Colorbar canvas: narrow strip (16 px) to the right of the image area
      const cbCanvas = document.createElement('canvas');
      cbCanvas.style.cssText = 'position:absolute;display:none;pointer-events:none;border-radius:0 2px 2px 0;';

      plotWrap.appendChild(plotCanvas);
      plotWrap.appendChild(overlayCanvas);
      plotWrap.appendChild(markersCanvas);
      plotWrap.appendChild(yAxisCanvas);
      plotWrap.appendChild(xAxisCanvas);
      plotWrap.appendChild(cbCanvas);
      plotWrap.appendChild(statusBar);
      cell.appendChild(plotWrap);

      const cbCtx = cbCanvas.getContext('2d');
      _p2d = { cbCanvas, cbCtx, plotWrap };
      _wrapNode = plotWrap;

    } else if (kind === '3d') {
      // ── 3D branch: one full-panel plotCanvas + overlayCanvas on top ───────
      plotCanvas = document.createElement('canvas');
      plotCanvas.style.cssText = `display:block;border-radius:2px;background:${theme.bgPlot};`;

      const wrap3 = document.createElement('div');
      wrap3.style.cssText = 'position:relative;display:inline-block;line-height:0;';
      wrap3.appendChild(plotCanvas);
      cell.appendChild(wrap3);

      overlayCanvas = document.createElement('canvas');
      overlayCanvas.style.cssText = 'position:absolute;top:0;left:0;z-index:5;pointer-events:all;outline:none;';
      wrap3.appendChild(overlayCanvas);

      markersCanvas = document.createElement('canvas');
      markersCanvas.style.cssText = 'position:absolute;top:0;left:0;pointer-events:none;z-index:6;display:none;';
      wrap3.appendChild(markersCanvas);

      statusBar = document.createElement('div');
      statusBar.style.cssText =
        'position:absolute;bottom:4px;right:4px;padding:2px 6px;display:none;';
      wrap3.appendChild(statusBar);
      _wrapNode = wrap3;
      plotCanvas = document.createElement('canvas');
      plotCanvas.tabIndex = 1;
      plotCanvas.style.cssText = 'outline:none;cursor:crosshair;display:block;border-radius:2px;';

      // wrap gives us a positioned container for the absolute canvases + status bar
      const wrap = document.createElement('div');
      wrap.style.cssText = 'position:relative;display:inline-block;line-height:0;';
      wrap.appendChild(plotCanvas);
      cell.appendChild(wrap);

      overlayCanvas = document.createElement('canvas');
      overlayCanvas.style.cssText = 'position:absolute;top:0;left:0;z-index:5;cursor:crosshair;pointer-events:all;';
      wrap.appendChild(overlayCanvas);
      markersCanvas = document.createElement('canvas');
      markersCanvas.style.cssText = 'position:absolute;top:0;left:0;pointer-events:none;z-index:6;';
      wrap.appendChild(markersCanvas);

      // Status bar overlays the 1D plot area
      statusBar = document.createElement('div');
      statusBar.style.cssText =
        'position:absolute;bottom:4px;right:4px;padding:2px 6px;' +
        'background:rgba(0,0,0,0.55);color:white;font-size:10px;font-family:monospace;' +
        'border-radius:4px;pointer-events:none;white-space:nowrap;display:none;z-index:9;';
      wrap.appendChild(statusBar);
      _wrapNode = wrap;
    }

    const plotCtx    = plotCanvas.getContext('2d');
    const ovCtx      = overlayCanvas.getContext('2d');
    const mkCtx      = markersCanvas.getContext('2d');
    const xCtx       = xAxisCanvas ? xAxisCanvas.getContext('2d') : null;
    const yCtx       = yAxisCanvas ? yAxisCanvas.getContext('2d') : null;

    const blitCache  = { bitmap:null, bytesKey:null, lutKey:null, w:0, h:0 };

    // ── stats overlay (top-left of panel) ────────────────────────────────
    // Positioned absolutely inside the panel's wrap container so it floats
    // over the plot area.  Visibility is toggled by the display_stats traitlet.
    const statsDiv = document.createElement('div');
    statsDiv.style.cssText =
      'position:absolute;top:4px;left:4px;padding:4px 7px;' +
      'background:rgba(0,0,0,0.65);color:#e0e0e0;font-size:10px;' +
      'font-family:monospace;border-radius:4px;pointer-events:none;' +
      'white-space:pre;line-height:1.5;z-index:20;display:none;';
    if (_wrapNode) _wrapNode.appendChild(statsDiv);

    const p = {
      id, kind, cell, pw, ph,
      plotCanvas, overlayCanvas, markersCanvas,
      plotCtx, ovCtx, mkCtx,
      xAxisCanvas, yAxisCanvas, xCtx, yCtx,
      scaleBar, statusBar,
      statsDiv,        // ← per-panel FPS overlay element
      frameTimes: [],  // ← rolling 60-entry timestamp buffer (performance.now())
      blitCache,
      ovDrag: null,
      isPanning: false, panStart: {},
      state: null,
      _hoverSi: -1, _hoverI: -1,   // index of hovered marker group / marker (-1 = none)
      _hovBar:  -1,                 // index of hovered bar (-1 = none)
      lastWidgetId: null,           // id of the last clicked/dragged widget (for on_key Delete etc.)
      mouseX: 0, mouseY: 0,        // last known canvas-relative cursor position
      // 2D extras (null for non-2D panels)
      cbCanvas:    _p2d ? _p2d.cbCanvas    : null,
      cbCtx:       _p2d ? _p2d.cbCtx       : null,
      sbLine:      null,
      sbLabel:     null,
      plotWrap:    _p2d ? _p2d.plotWrap    : null,
    };
    panels.set(id, p);

    _resizePanelDOM(id, pw, ph);
    _attachPanelEvents(p);

    // Listen for this panel's trait changes
    model.on(`change:panel_${id}_json`, () => {
      const p2 = panels.get(id);
      if (!p2) return;
      try { p2.state = JSON.parse(model.get(`panel_${id}_json`)); }
      catch(_) { return; }
      p2._hoverSi = -1; p2._hoverI = -1;
      _redrawPanel(p2);
    });

    // Initial draw
    try { p.state = JSON.parse(model.get(`panel_${id}_json`)); } catch(_) {}
    _redrawPanel(p);
  }

  function _resizePanelDOM(id, pw, ph) {
    const p = panels.get(id);
    if (!p) return;
    p.pw = pw; p.ph = ph;

    function _sz(c, ctx, w, h) {
      c.style.width=w+'px'; c.style.height=h+'px';
      c.width=w*dpr; c.height=h*dpr;
      ctx.setTransform(dpr,0,0,dpr,0,0);
    }

    if (p.kind === '2d') {
      // ── 2D: all elements absolutely positioned within pw×ph container ──
      // The image/plot area mirrors 1D's _plotRect1d:
      //   x: PAD_L → pw-PAD_R,  y: PAD_T → ph-PAD_B
      const imgX = PAD_L, imgY = PAD_T;
      const imgW = Math.max(1, pw - PAD_L - PAD_R);
      const imgH = Math.max(1, ph - PAD_T - PAD_B);

      if (p.plotWrap) {
        p.plotWrap.style.width  = pw + 'px';
        p.plotWrap.style.height = ph + 'px';
      }

      // Image canvas at the inner plot area
      p.plotCanvas.style.left = imgX + 'px';
      p.plotCanvas.style.top  = imgY + 'px';
      _sz(p.plotCanvas, p.plotCtx, imgW, imgH);

      // Overlay and markers match the image canvas exactly
      p.overlayCanvas.style.left = imgX + 'px';
      p.overlayCanvas.style.top  = imgY + 'px';
      _sz(p.overlayCanvas, p.ovCtx, imgW, imgH);
      p.markersCanvas.style.left = imgX + 'px';
      p.markersCanvas.style.top  = imgY + 'px';
      _sz(p.markersCanvas, p.mkCtx, imgW, imgH);

      // Status bar: bottom-left of image area
      if (p.statusBar) {
        p.statusBar.style.left   = (imgX + 4) + 'px';
        p.statusBar.style.bottom = (PAD_B + 4) + 'px';
        p.statusBar.style.top    = '';
      }

      // Scale bar: bottom-right of image area
      if (p.scaleBar) {
        p.scaleBar.style.right  = (PAD_R + 12) + 'px';
        p.scaleBar.style.bottom = (PAD_B + 12) + 'px';
        p.scaleBar.style.left   = '';
        p.scaleBar.style.top    = '';
      }

      const st = p.state;
      // Show axis canvases only when the user explicitly provided coordinate
      // arrays (has_axes), or for pcolormesh panels (is_mesh, always has edges).
      const hasPhysAxis = st && (st.is_mesh || st.has_axes)
                       && st.x_axis && st.x_axis.length >= 2
                       && st.y_axis && st.y_axis.length >= 2;

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

      // Colorbar: narrow strip to the right of the image area
      if (p.cbCanvas && p.cbCtx) {
        const cbW = 16;
        const vis = st && st.show_colorbar;
        if (vis) {
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
    if (zoom < 1.0) {
      // Zoom-out path: full image drawn centred inside a scaled-down fit-rect
      // (mirrors the zoom<1 branch in _blit2d exactly).
      const dstW = w * zoom, dstH = h * zoom;
      const dstX = x + (w - dstW) / 2, dstY = y + (h - dstH) / 2;
      return [dstX + (ix / iw) * dstW, dstY + (iy / ih) * dstH];
    }
    const visW = iw / zoom, visH = ih / zoom;
    const srcX = Math.max(0, Math.min(iw - visW, cx * iw - visW / 2));
    const srcY = Math.max(0, Math.min(ih - visH, cy * ih - visH / 2));
    return [x + (ix - srcX) / visW * w, y + (iy - srcY) / visH * h];
  }

  // Returns canvas-px per image-px at the current zoom (uniform in x and y).
  function _imgScale2d(st, pw, ph) {
    return _imgFitRect(st.image_width, st.image_height, pw, ph).s * st.zoom;
  }

  function _blit2d(bitmap, st, pw, ph, ctx) {
    const { x, y, w, h } = _imgFitRect(st.image_width, st.image_height, pw, ph);
    const zoom = st.zoom, cx = st.center_x, cy = st.center_y;
    const iw = st.image_width, ih = st.image_height;
    ctx.clearRect(0, 0, pw, ph);
    ctx.fillStyle = theme.bgCanvas;
    ctx.fillRect(0, 0, pw, ph);
    ctx.imageSmoothingEnabled = false;
    if (zoom >= 1.0) {
      // Zoomed in: show a portion of the image filling the fit-rect.
      const visW = iw / zoom, visH = ih / zoom;
      const srcX = Math.max(0, Math.min(iw - visW, cx * iw - visW / 2));
      const srcY = Math.max(0, Math.min(ih - visH, cy * ih - visH / 2));
      ctx.drawImage(bitmap, srcX, srcY, visW, visH, x, y, w, h);
    } else {
      // Zoomed out: shrink the fit-rect proportionally, keep it centred.
      const dstW = w * zoom, dstH = h * zoom;
      ctx.drawImage(bitmap, 0, 0, iw, ih,
        x + (w - dstW) / 2, y + (h - dstH) / 2, dstW, dstH);
    }
  }

  function draw2d(p) {
    const st=p.state;
    if(!st) return;
    _recordFrame(p);
    // Re-sync axis/histogram canvas visibility whenever state changes
    _resizePanelDOM(p.id, p.pw, p.ph);
    const {pw,ph,plotCtx:ctx,blitCache} = p;
    // The image canvas occupies the inner plot area, mirroring 1D's _plotRect1d
    const imgW = Math.max(1, pw - PAD_L - PAD_R);
    const imgH = Math.max(1, ph - PAD_T - PAD_B);

    // Decode base64 image bytes
    const b64=st.image_b64||'';
    const iw=st.image_width, ih=st.image_height;

    if(!b64||iw===0||ih===0){ctx.clearRect(0,0,imgW,imgH);return;}

    let bytes;
    try {
      const bin=atob(b64);
      bytes=new Uint8Array(bin.length);
      for(let i=0;i<bin.length;i++) bytes[i]=bin.charCodeAt(i);
    } catch(_){return;}

    const lk=_lutKey(st);
    const needRebuild = bytes!==blitCache.bytesKey || lk!==blitCache.lutKey
                     || !blitCache.bitmap || blitCache.w!==iw || blitCache.h!==ih;
    if(!needRebuild && blitCache.bitmap){
      _blit2d(blitCache.bitmap, st, imgW, imgH, ctx);
    } else {
      const lut=_buildLut32(st);
      const imgData=new ImageData(iw,ih);
      const out32=new Uint32Array(imgData.data.buffer);
      for(let i=0;i<iw*ih;i++) out32[i]=lut[bytes[i]];
      const oc=new OffscreenCanvas(iw,ih);
      oc.getContext('2d').putImageData(imgData,0,0);
      blitCache.bitmap=oc; blitCache.bytesKey=bytes; blitCache.lutKey=lk;
      blitCache.w=iw; blitCache.h=ih;
      _blit2d(oc, st, imgW, imgH, ctx);
    }
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

    const imgW=Math.max(1,p.pw-PAD_L-PAD_R);
    const imgH=Math.max(1,p.ph-PAD_T-PAD_B);

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
    const vis=st.show_colorbar||false;
    p.cbCanvas.style.display = vis ? 'block' : 'none';
    if(!vis) return;

    const cbW=16;
    const imgH=Math.max(1,p.ph-PAD_T-PAD_B);
    const ctx=p.cbCtx;
    ctx.clearRect(0,0,cbW,imgH);

    // Gradient strip
    if(st.colormap_data&&st.colormap_data.length===256){
      for(let py=0;py<imgH;py++){
        const frac=1-py/(imgH-1||1);
        const ci=Math.max(0,Math.min(255,Math.round(frac*255)));
        const [r2,g2,b2]=st.colormap_data[ci];
        ctx.fillStyle=`rgb(${r2},${g2},${b2})`;
        ctx.fillRect(0,py,cbW,1);
      }
    } else {
      ctx.fillStyle=theme.dark?'#444':'#ccc';
      ctx.fillRect(0,0,cbW,imgH);
    }

    // Border
    ctx.strokeStyle=theme.border||'#888';
    ctx.lineWidth=0.5;
    ctx.strokeRect(0,0,cbW,imgH);

    // display_min / display_max tick marks
    const dMin=st.display_min, dMax=st.display_max;
    const hMin=st.raw_min!=null?st.raw_min:dMin;
    const hMax=st.raw_max!=null?st.raw_max:dMax;
    const vRange=(hMax-hMin)||1;
    function _vToY(v){return imgH-1-((v-hMin)/vRange)*(imgH-1);}
    ctx.strokeStyle='rgba(255,255,255,0.85)'; ctx.lineWidth=1.5;
    ctx.beginPath();ctx.moveTo(0,_vToY(dMax));ctx.lineTo(cbW,_vToY(dMax));ctx.stroke();
    ctx.beginPath();ctx.moveTo(0,_vToY(dMin));ctx.lineTo(cbW,_vToY(dMin));ctx.stroke();
  }


  function _drawAxes2d(p) {
    const st=p.state; if(!st) return;
    const {pw,ph} = p;
    const imgW = Math.max(1, pw - PAD_L - PAD_R);
    const imgH = Math.max(1, ph - PAD_T - PAD_B);
    const xArr=st.x_axis||[], yArr=st.y_axis||[];
    const TICK=6;
    const zoom=st.zoom, cx=st.center_x, cy=st.center_y;
    const units=st.units||'px';
    const hasPhysAxis = (st.is_mesh || st.has_axes) && xArr.length>=2 && yArr.length>=2;
    const hasX = hasPhysAxis && p.xCtx && p.xAxisCanvas && p.xAxisCanvas.style.display!=='none';
    const hasY = hasPhysAxis && p.yCtx && p.yAxisCanvas && p.yAxisCanvas.style.display!=='none';

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
      p.xCtx.fillStyle=theme.tickText; p.xCtx.font='10px sans-serif';
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
          p.xCtx.fillText(fmtVal(v), px2, TICK+2);
          lastPx=px2;
        }
      }
      p.xCtx.textAlign='right'; p.xCtx.textBaseline='bottom';
      p.xCtx.fillStyle=theme.unitText; p.xCtx.font='9px sans-serif';
      p.xCtx.fillText(units, aw-2, ah-1);
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
      p.yCtx.fillStyle=theme.tickText; p.yCtx.font='10px sans-serif';
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
          p.yCtx.fillText(fmtVal(v), aw-TICK-2, py2);
          lastPy=py2;
        }
      }
      // Units label: top-left corner of y-axis gutter
      p.yCtx.textAlign='left'; p.yCtx.textBaseline='top';
      p.yCtx.fillStyle=theme.unitText; p.yCtx.font='9px sans-serif';
      p.yCtx.fillText(units, 2, 1);
    }
  }

  function drawOverlay2d(p) {
    const st=p.state; if(!st) return;
    const {pw,ph,ovCtx} = p;
    const imgW=Math.max(1,pw-PAD_L-PAD_R), imgH=Math.max(1,ph-PAD_T-PAD_B);
    ovCtx.clearRect(0,0,imgW,imgH);
    const widgets=st.overlay_widgets||[];
    const scale=_imgScale2d(st,imgW,imgH);
    for(const w of widgets){
      ovCtx.save(); ovCtx.strokeStyle=w.color||'#00e5ff'; ovCtx.lineWidth=2;
      if(w.type==='circle'){
        const [ccx,ccy]=_imgToCanvas2d(w.cx,w.cy,st,imgW,imgH);
        ovCtx.beginPath(); ovCtx.arc(ccx,ccy,w.r*scale,0,Math.PI*2); ovCtx.stroke();
        _drawHandle2d(ovCtx,ccx+w.r*scale,ccy,w.color);
      } else if(w.type==='annular'){
        const [ccx,ccy]=_imgToCanvas2d(w.cx,w.cy,st,imgW,imgH);
        ovCtx.beginPath();ovCtx.arc(ccx,ccy,w.r_outer*scale,0,Math.PI*2);ovCtx.stroke();
        ovCtx.beginPath();ovCtx.arc(ccx,ccy,w.r_inner*scale,0,Math.PI*2);ovCtx.stroke();
        _drawHandle2d(ovCtx,ccx+w.r_outer*scale,ccy,w.color);
        _drawHandle2d(ovCtx,ccx+w.r_inner*scale,ccy-w.r_inner*scale*0.3,w.color);
      } else if(w.type==='rectangle'){
        const [rx,ry]=_imgToCanvas2d(w.x,w.y,st,imgW,imgH);
        const rw=w.w*scale, rh=w.h*scale;
        ovCtx.strokeRect(rx,ry,rw,rh);
        _drawHandle2d(ovCtx,rx,ry,w.color);_drawHandle2d(ovCtx,rx+rw,ry,w.color);
        _drawHandle2d(ovCtx,rx,ry+rh,w.color);_drawHandle2d(ovCtx,rx+rw,ry+rh,w.color);
      } else if(w.type==='crosshair'){
        const [ccx,ccy]=_imgToCanvas2d(w.cx,w.cy,st,imgW,imgH);
        ovCtx.beginPath();ovCtx.moveTo(0,ccy);ovCtx.lineTo(imgW,ccy);ovCtx.stroke();
        ovCtx.beginPath();ovCtx.moveTo(ccx,0);ovCtx.lineTo(ccx,imgH);ovCtx.stroke();
        ovCtx.beginPath();ovCtx.arc(ccx,ccy,4,0,Math.PI*2);ovCtx.fillStyle=w.color||'#00e5ff';ovCtx.fill();
      } else if(w.type==='polygon'){
        const verts=w.vertices||[];
        if(verts.length>=2){
          ovCtx.beginPath();
          const [px0,py0]=_imgToCanvas2d(verts[0][0],verts[0][1],st,imgW,imgH);
          ovCtx.moveTo(px0,py0);
          for(let k=1;k<verts.length;k++){const[px,py]=_imgToCanvas2d(verts[k][0],verts[k][1],st,imgW,imgH);ovCtx.lineTo(px,py);}
          ovCtx.closePath();ovCtx.stroke();
          for(const v of verts){const[px,py]=_imgToCanvas2d(v[0],v[1],st,imgW,imgH);_drawHandle2d(ovCtx,px,py,w.color);}
        }
      } else if(w.type==='label'){
        const [lx,ly]=_imgToCanvas2d(w.x,w.y,st,imgW,imgH);
        ovCtx.font=`${w.fontsize||14}px sans-serif`;ovCtx.fillStyle=w.color||'#00e5ff';
        ovCtx.textAlign='left';ovCtx.textBaseline='top';ovCtx.fillText(w.text||'',lx,ly);
        _drawHandle2d(ovCtx,lx,ly,w.color);
      }
      ovCtx.restore();
    }
  }

  function _drawHandle2d(ctx,x,y,color){
    ctx.save();ctx.fillStyle='#fff';ctx.strokeStyle=color||'#00e5ff';ctx.lineWidth=1.5;
    ctx.beginPath();ctx.arc(x,y,5,0,Math.PI*2);ctx.fill();ctx.stroke();ctx.restore();
  }

  function drawMarkers2d(p, hoverState) {
    const st=p.state; if(!st) return;
    const {pw,ph,mkCtx} = p;
    const imgW=Math.max(1,pw-PAD_L-PAD_R), imgH=Math.max(1,ph-PAD_T-PAD_B);
    mkCtx.clearRect(0,0,imgW,imgH);
    const sets=st.markers||[];
    if(!sets.length) return;
    const scale=_imgScale2d(st,imgW,imgH);
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
      mkCtx.save();
      mkCtx.strokeStyle=ec; mkCtx.fillStyle=ec; mkCtx.lineWidth=dlw;

      if(type==='circles'){
        for(let i=0;i<ms.offsets.length;i++){
          const [cx,cy]=_imgToCanvas2d(ms.offsets[i][0],ms.offsets[i][1],st,imgW,imgH);
          const r=Math.max(1,(ms.sizes[i]!=null?ms.sizes[i]:ms.sizes[0]||5)*scale);
          mkCtx.beginPath();mkCtx.arc(cx,cy,r,0,Math.PI*2);
          if(fch){mkCtx.save();mkCtx.globalAlpha=fa;mkCtx.fillStyle=fch;mkCtx.fill();mkCtx.restore();}
          mkCtx.stroke();
        }
      } else if(type==='arrows'){
        const HL=8;
        for(let i=0;i<ms.offsets.length;i++){
          const [x1,y1]=_imgToCanvas2d(ms.offsets[i][0],ms.offsets[i][1],st,imgW,imgH);
          const u=(ms.U[i]||0)*scale, v=(ms.V[i]||0)*scale;
          const x2=x1+u,y2=y1+v,ang=Math.atan2(y2-y1,x2-x1);
          mkCtx.beginPath();mkCtx.moveTo(x1,y1);mkCtx.lineTo(x2,y2);mkCtx.stroke();
          mkCtx.beginPath();mkCtx.moveTo(x2,y2);
          mkCtx.lineTo(x2-HL*Math.cos(ang-Math.PI/6),y2-HL*Math.sin(ang-Math.PI/6));
          mkCtx.lineTo(x2-HL*Math.cos(ang+Math.PI/6),y2-HL*Math.sin(ang+Math.PI/6));
          mkCtx.closePath();mkCtx.fill();
        }
      } else if(type==='ellipses'){
        for(let i=0;i<ms.offsets.length;i++){
          const [cx,cy]=_imgToCanvas2d(ms.offsets[i][0],ms.offsets[i][1],st,imgW,imgH);
          const rw=Math.max(1,(ms.widths[i]||ms.widths[0]||10)*scale/2);
          const rh=Math.max(1,(ms.heights[i]||ms.heights[0]||10)*scale/2);
          const ang=((ms.angles[i]||ms.angles[0]||0)*Math.PI)/180;
          mkCtx.beginPath();mkCtx.ellipse(cx,cy,rw,rh,ang,0,Math.PI*2);
          if(fch){mkCtx.save();mkCtx.globalAlpha=fa;mkCtx.fillStyle=fch;mkCtx.fill();mkCtx.restore();}
          mkCtx.stroke();
        }
      } else if(type==='lines'){
        for(const seg of (ms.segments||[])){
          const [x1,y1]=_imgToCanvas2d(seg[0][0],seg[0][1],st,imgW,imgH);
          const [x2,y2]=_imgToCanvas2d(seg[1][0],seg[1][1],st,imgW,imgH);
          mkCtx.beginPath();mkCtx.moveTo(x1,y1);mkCtx.lineTo(x2,y2);mkCtx.stroke();
        }
      } else if(type==='rectangles'||type==='squares'){
        const heights=type==='squares'?ms.widths:ms.heights;
        for(let i=0;i<ms.offsets.length;i++){
          const [cx,cy]=_imgToCanvas2d(ms.offsets[i][0],ms.offsets[i][1],st,imgW,imgH);
          const rw=(ms.widths[i]||ms.widths[0]||20)*scale;
          const rh=((heights[i]||heights[0]||20))*scale;
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
          const [px0,py0]=_imgToCanvas2d(verts[0][0],verts[0][1],st,imgW,imgH);
          mkCtx.beginPath();mkCtx.moveTo(px0,py0);
          for(let k=1;k<verts.length;k++){const[px,py]=_imgToCanvas2d(verts[k][0],verts[k][1],st,imgW,imgH);mkCtx.lineTo(px,py);}
          mkCtx.closePath();
          if(fch){mkCtx.save();mkCtx.globalAlpha=fa;mkCtx.fillStyle=fch;mkCtx.fill();mkCtx.restore();}
          mkCtx.stroke();
        }
      } else if(type==='texts'){
        const fs=ms.fontsize||12;
        mkCtx.font=`${fs}px sans-serif`;mkCtx.textAlign='left';mkCtx.textBaseline='top';
        for(let i=0;i<ms.offsets.length;i++){
          const [cx,cy]=_imgToCanvas2d(ms.offsets[i][0],ms.offsets[i][1],st,imgW,imgH);
          mkCtx.fillText(String(ms.texts[i]||''),cx,cy);
        }
      }
      mkCtx.restore();
    }
  }

  // ── 3D drawing ───────────────────────────────────────────────────────────

  function _rot3(az, el) {
    // Rotation matrix: Ry(az) * Rx(-el)  (azimuth around world-Y, elevation around screen-X)
    const azR = az * Math.PI / 180, elR = el * Math.PI / 180;
    const ca = Math.cos(azR), sa = Math.sin(azR);
    const ce = Math.cos(elR), se = Math.sin(elR);
    // R = Ry(az) * Rx(-el):
    return [
      [ ca,      sa*se,   sa*ce],
      [ 0,       ce,     -se   ],
      [-sa,      ca*se,   ca*ce],
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

  function draw3d(p) {
    const st = p.state; if (!st) return;
    _recordFrame(p);
    const { pw, ph, plotCtx: ctx } = p;

    ctx.clearRect(0, 0, pw, ph);
    ctx.fillStyle = theme.bgPlot;
    ctx.fillRect(0, 0, pw, ph);

    const verts    = st.vertices    || [];
    const faces    = st.faces       || [];
    const zVals    = st.z_values    || [];
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

    // Pre-project all vertices
    const proj = verts.map(v => {
      const nv = norm(v);
      const rv = _applyRot(R, nv);
      return { s: _project3(rv, cx, cy, scale), d: rv[1] }; // d = depth (into screen)
    });

    // Z-value normalisation for colormap
    const zMin = bnds.zmin, zMax = bnds.zmax, zRange = (zMax - zMin) || 1;

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

    } else if (geom === 'scatter') {
      // Sort back-to-front so nearer points draw on top
      const order = proj.map((p2, i) => ({ i, d: p2.d })).sort((a, b) => b.d - a.d);
      for (const { i } of order) {
        const [sx, sy] = proj[i].s;
        ctx.beginPath();
        ctx.arc(sx, sy, ptSize, 0, Math.PI * 2);
        ctx.fillStyle = color;
        ctx.fill();
      }

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

    // ── Draw axes ────────────────────────────────────────────────────────────
    const axisVerts = [
      [-1,0,0],[1,0,0],[0,-1,0],[0,1,0],[0,0,-1],[0,0,1]
    ];
    const ap = axisVerts.map(v => _project3(_applyRot(R, v), cx, cy, scale));

    const axDefs = [
      { i0:0, i1:1, label: st.x_label||'x', col:'#e06c75' },
      { i0:2, i1:3, label: st.y_label||'y', col:'#98c379' },
      { i0:4, i1:5, label: st.z_label||'z', col:'#61afef' },
    ];
    for (const { i0, i1, label, col } of axDefs) {
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
      ctx.font        = 'bold 11px sans-serif';
      ctx.textAlign   = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText(label, ap[i1][0], ap[i1][1]);
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
  }

  // ── event emission helper (module-scope: accessible to all attach fns) ──
  // eventType: 'on_changed' | 'on_release' | 'on_click'
  function _emitEvent(panelId, eventType, widgetId, extraData) {
    const payload = Object.assign(
      { source: 'js', panel_id: panelId, event_type: eventType,
        widget_id: widgetId || null },
      extraData || {}
    );
    model.set('event_json', JSON.stringify(payload));
    model.save_changes();
  }

  function _attachEvents3d(p) {
    const { overlayCanvas } = p;
    let dragStart = null;
    let commitPending = false;
    function _scheduleCommit() {
      if (commitPending) return; commitPending = true;
      requestAnimationFrame(() => {
        commitPending = false;
        model.save_changes();
      });
    }


    overlayCanvas.addEventListener('mousedown', (e) => {
      if (e.button !== 0) return;
      const {mx:_d3mx, my:_d3my} = _clientPos(e, overlayCanvas, p.pw, p.ph);
      dragStart = { mx: _d3mx, my: _d3my,
                    az: p.state.azimuth, el: p.state.elevation };
      overlayCanvas.style.cursor = 'grabbing';
      e.preventDefault();
    });
    document.addEventListener('mousemove', (e) => {
      if (!dragStart) return;
      const {mx:_d3mx2, my:_d3my2} = _clientPos(e, overlayCanvas, p.pw, p.ph);
      const dx = _d3mx2 - dragStart.mx;
      const dy = _d3my2 - dragStart.my;
      p.state.azimuth   = dragStart.az + dx * 0.5;
      p.state.elevation = Math.max(-89, Math.min(89, dragStart.el - dy * 0.5));
      draw3d(p);
      model.set(`panel_${p.id}_json`, JSON.stringify(p.state));
      _emitEvent(p.id, 'on_changed', null,
        { azimuth: p.state.azimuth, elevation: p.state.elevation, zoom: p.state.zoom });
      e.preventDefault();
    });
    document.addEventListener('mouseup', () => {
      if (!dragStart) return;
      dragStart = null;
      overlayCanvas.style.cursor = 'grab';
      model.set(`panel_${p.id}_json`, JSON.stringify(p.state));
      _emitEvent(p.id, 'on_release', null,
        { azimuth: p.state.azimuth, elevation: p.state.elevation, zoom: p.state.zoom });
      _scheduleCommit();
    });

    overlayCanvas.addEventListener('wheel', (e) => {
      e.preventDefault();
      p.state.zoom = Math.max(0.1, Math.min(10, p.state.zoom * (e.deltaY > 0 ? 0.9 : 1.1)));
      draw3d(p);
      model.set(`panel_${p.id}_json`, JSON.stringify(p.state));
      _emitEvent(p.id, 'on_changed', null,
        { azimuth: p.state.azimuth, elevation: p.state.elevation, zoom: p.state.zoom });
      _scheduleCommit();
    }, { passive: false });

    overlayCanvas.addEventListener('mousemove', (e) => {
      const {mx, my} = _clientPos(e, overlayCanvas, p.pw, p.ph);
      p.mouseX = mx;
      p.mouseY = my;
    });

    // Keyboard shortcuts
    // Built-in: r=reset view. Registered keys are forwarded to Python first.
    overlayCanvas.addEventListener('keydown', (e) => {
      const st = p.state; if (!st) return;
      const regKeys = st.registered_keys || [];
      if (regKeys.includes(e.key) || regKeys.includes('*')) {
        _emitEvent(p.id, 'on_key', null, {
          key: e.key,
          last_widget_id: p.lastWidgetId || null,
          mouse_x: p.mouseX, mouse_y: p.mouseY,
        });
        e.stopPropagation(); e.preventDefault(); return;
      }
      if (e.key.toLowerCase() === 'r') {
        p.state.azimuth = -60; p.state.elevation = 30; p.state.zoom = 1;
        draw3d(p);
        model.set(`panel_${p.id}_json`, JSON.stringify(p.state));
        model.save_changes();
        e.stopPropagation(); e.preventDefault();
      }
    });
    overlayCanvas.tabIndex = 0;
    overlayCanvas.style.outline = 'none';
    overlayCanvas.style.cursor  = 'grab';
    overlayCanvas.addEventListener('mouseenter', () => overlayCanvas.focus());
  }

  // ── 1D drawing ───────────────────────────────────────────────────────────

  function _plotRect1d(pw,ph){return{x:PAD_L,y:PAD_T,w:Math.max(1,pw-PAD_L-PAD_R),h:Math.max(1,ph-PAD_T-PAD_B)};}

  function _xToFrac1d(xArr,val){
    if(xArr.length<2) return 0;
    const n=xArr.length, asc=xArr[n-1]>=xArr[0];
    if(asc?val<=xArr[0]:val>=xArr[0]) return 0;
    if(asc?val>=xArr[n-1]:val<=xArr[n-1]) return 1;
    let lo=0,hi=n-2;
    while(lo<hi){const mid=(lo+hi)>>1;const ok=asc?(xArr[mid]<=val&&val<xArr[mid+1]):(xArr[mid]>=val&&val>xArr[mid+1]);if(ok){lo=mid;break;}if(asc?xArr[mid+1]<=val:xArr[mid+1]>=val)lo=mid+1;else hi=mid;}
    return(lo+(val-xArr[lo])/(xArr[lo+1]-xArr[lo]))/(n-1);
  }
  function _fracToX1d(xArr,frac){
    if(xArr.length<2) return xArr.length?xArr[0]:0;
    const n=xArr.length,pos=Math.max(0,Math.min(1,frac))*(n-1),lo=Math.min(Math.floor(pos),n-2),t=pos-lo;
    return xArr[lo]+t*(xArr[lo+1]-xArr[lo]);
  }
  function _fracToPx1d(frac,x0,x1,r){return r.x+((frac-x0)/((x1-x0)||1))*r.w;}
  function _valToPy1d(val,dMin,dMax,r){return r.y+r.h-((val-dMin)/((dMax-dMin)||1))*r.h;}

  function draw1d(p) {
    const st=p.state; if(!st) return;
    _recordFrame(p);
    const {pw,ph,plotCtx:ctx} = p;
    const r=_plotRect1d(pw,ph);
    const xArr=st.x_axis||[], x0=st.view_x0||0, x1=st.view_x1||1;
    const dMin=st.data_min, dMax=st.data_max;
    const units=st.units||'', yUnits=st.y_units||'';

    ctx.clearRect(0,0,pw,ph);
    ctx.fillStyle=theme.bg; ctx.fillRect(0,0,pw,ph);
    ctx.fillStyle=theme.bgPlot; ctx.fillRect(r.x,r.y,r.w,r.h);

    // Grid
    ctx.strokeStyle=theme.gridStroke; ctx.lineWidth=1;
    if(xArr.length>=2){
      const xVMin=_fracToX1d(xArr,x0), xVMax=_fracToX1d(xArr,x1);
      const xStep=findNice((xVMax-xVMin)/Math.max(2,Math.floor(r.w/70)));
      for(let v=Math.ceil(xVMin/xStep)*xStep;v<=xVMax+xStep*0.01;v+=xStep){
        const px=_fracToPx1d(_xToFrac1d(xArr,v),x0,x1,r);
        if(px<r.x||px>r.x+r.w) continue;
        ctx.beginPath();ctx.moveTo(px,r.y);ctx.lineTo(px,r.y+r.h);ctx.stroke();
      }
    }
    const yRange=(dMax-dMin)||1;
    const yStep=findNice(yRange/Math.max(2,Math.floor(r.h/40)));
    for(let v=Math.ceil(dMin/yStep)*yStep;v<=dMax+yStep*0.01;v+=yStep){
      const py=_valToPy1d(v,dMin,dMax,r);
      if(py<r.y||py>r.y+r.h) continue;
      ctx.beginPath();ctx.moveTo(r.x,py);ctx.lineTo(r.x+r.w,py);ctx.stroke();
    }

    // Spans
    for(const sp of (st.spans||[])){
      ctx.fillStyle=sp.color||(theme.dark?'rgba(255,255,100,0.15)':'rgba(200,160,0,0.15)');
      if(sp.axis==='x'){
        const px0=_fracToPx1d(_xToFrac1d(xArr,sp.v0),x0,x1,r);
        const px1b=_fracToPx1d(_xToFrac1d(xArr,sp.v1),x0,x1,r);
        ctx.fillRect(px0,r.y,px1b-px0,r.h);
      } else {
        const py0=_valToPy1d(sp.v1,dMin,dMax,r), py1=_valToPy1d(sp.v0,dMin,dMax,r);
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
      const dash = _LINESTYLE_DASH[linestyle || 'solid'] || [];
      const eff_alpha = (alpha != null && alpha < 1.0) ? alpha : 1.0;
      const ms = Math.max(1, markersize || 4);
      const doMarker = marker && marker !== 'none';

      ctx.save();
      if (eff_alpha < 1.0) ctx.globalAlpha = eff_alpha;
      ctx.setLineDash(dash);
      ctx.beginPath();
      ctx.strokeStyle = color; ctx.lineWidth = lw; ctx.lineJoin = 'round';

      const pts = doMarker ? [] : null;
      let first = true;
      for (let i = 0; i < n; i++) {
        const xFrac = lineXArr.length >= 2
          ? (lineXArr[i] - lineXArr[0]) / ((lineXArr[lineXArr.length - 1] - lineXArr[0]) || 1)
          : i / ((n - 1) || 1);
        const px = _fracToPx1d(xFrac, x0, x1, r);
        const py = _valToPy1d(yData[i], dMin, dMax, r);
        if (first) { ctx.moveTo(px, py); first = false; } else { ctx.lineTo(px, py); }
        if (pts) pts.push([px, py]);
      }
      ctx.stroke();
      ctx.setLineDash([]);

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

    _drawLine(st.data, xArr,
      st.line_color || '#4fc3f7', st.line_linewidth || 1.5,
      st.line_linestyle || 'solid',
      st.line_alpha != null ? st.line_alpha : 1.0,
      st.line_marker || 'none', st.line_markersize || 4);
    for (const ex of (st.extra_lines || [])) {
      _drawLine(ex.data || [], ex.x_axis || xArr,
        ex.color || (theme.dark ? '#fff' : '#333'), ex.linewidth || 1.5,
        ex.linestyle || 'solid',
        ex.alpha != null ? ex.alpha : 1.0,
        ex.marker || 'none', ex.markersize || 4);
    }
    ctx.restore();

    // Axes
    ctx.strokeStyle=theme.axisStroke; ctx.lineWidth=1;
    ctx.beginPath();ctx.moveTo(r.x,r.y+r.h);ctx.lineTo(r.x+r.w,r.y+r.h);ctx.stroke();
    ctx.beginPath();ctx.moveTo(r.x,r.y);ctx.lineTo(r.x,r.y+r.h);ctx.stroke();

    ctx.fillStyle=theme.tickText; ctx.font='10px monospace';
    if(xArr.length>=2){
      const xVMin=_fracToX1d(xArr,x0), xVMax=_fracToX1d(xArr,x1);
      const xStep=findNice((xVMax-xVMin)/Math.max(2,Math.floor(r.w/70)));
      ctx.textAlign='center'; ctx.textBaseline='top';
      for(let v=Math.ceil(xVMin/xStep)*xStep;v<=xVMax+xStep*0.01;v+=xStep){
        const px=_fracToPx1d(_xToFrac1d(xArr,v),x0,x1,r);
        if(px<r.x||px>r.x+r.w) continue;
        ctx.strokeStyle=theme.axisStroke;ctx.beginPath();ctx.moveTo(px,r.y+r.h);ctx.lineTo(px,r.y+r.h+5);ctx.stroke();
        ctx.fillStyle=theme.tickText;ctx.fillText(fmtVal(v),px,r.y+r.h+7);
      }
      if(units&&units!=='px'){ctx.textAlign='right';ctx.textBaseline='top';ctx.fillStyle=theme.unitText;ctx.font='9px monospace';ctx.fillText(units,r.x+r.w,r.y+r.h+24);ctx.font='10px monospace';}
    }
    ctx.font='10px monospace';ctx.textAlign='right';ctx.textBaseline='middle';
    let maxTW=0;
    for(let v=Math.ceil(dMin/yStep)*yStep;v<=dMax+yStep*0.01;v+=yStep){const tw=ctx.measureText(fmtVal(v)).width;if(tw>maxTW)maxTW=tw;}
    const tickRX=r.x-8;
    for(let v=Math.ceil(dMin/yStep)*yStep;v<=dMax+yStep*0.01;v+=yStep){
      const py=_valToPy1d(v,dMin,dMax,r);
      if(py<r.y||py>r.y+r.h) continue;
      ctx.strokeStyle=theme.axisStroke;ctx.beginPath();ctx.moveTo(r.x,py);ctx.lineTo(r.x-5,py);ctx.stroke();
      ctx.fillStyle=theme.tickText;ctx.fillText(fmtVal(v),tickRX,py);
    }
    if(yUnits){
      ctx.save();
      // Centre the rotated label in the left gutter (x = 0..r.x).
      // Using a fixed x of PAD_L*0.28 keeps it clear of the tick numbers
      // regardless of how wide those numbers are.
      const lcx = Math.round(PAD_L * 0.28);
      ctx.translate(lcx, r.y+r.h/2); ctx.rotate(-Math.PI/2);
      ctx.textAlign='center'; ctx.textBaseline='middle';
      ctx.fillStyle=theme.unitText; ctx.font='9px monospace';
      ctx.fillText(yUnits, 0, 0);
      ctx.restore();
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

    drawOverlay1d(p);
    drawMarkers1d(p);
  }

  function drawOverlay1d(p) {
    const st=p.state; if(!st) return;
    const {pw,ph,ovCtx} = p;
    const r=_plotRect1d(pw,ph);
    const xArr=st.x_axis||[], x0=st.view_x0||0, x1=st.view_x1||1;
    const dMin=st.data_min, dMax=st.data_max;
    ovCtx.clearRect(0,0,pw,ph);
    const widgets=st.overlay_widgets||[];
    if(!widgets.length) return;

    for(const w of widgets){
      const color=w.color||'#00e5ff';
      ovCtx.save();ovCtx.strokeStyle=color;ovCtx.lineWidth=2;
      if(w.type==='vline'){
        const px=_fracToPx1d(_xToFrac1d(xArr,w.x),x0,x1,r);
        ovCtx.setLineDash([5,3]);ovCtx.beginPath();ovCtx.moveTo(px,r.y);ovCtx.lineTo(px,r.y+r.h);ovCtx.stroke();ovCtx.setLineDash([]);
        _ovHandle1d(ovCtx,px,r.y+7,color);
      } else if(w.type==='hline'){
        const py=_valToPy1d(w.y,dMin,dMax,r);
        ovCtx.setLineDash([5,3]);ovCtx.beginPath();ovCtx.moveTo(r.x,py);ovCtx.lineTo(r.x+r.w,py);ovCtx.stroke();ovCtx.setLineDash([]);
        _ovHandle1d(ovCtx,r.x+r.w-7,py,color);
      } else if(w.type==='range'){
        const px0=_fracToPx1d(_xToFrac1d(xArr,w.x0),x0,x1,r);
        const px1b=_fracToPx1d(_xToFrac1d(xArr,w.x1),x0,x1,r);
        const left=Math.min(px0,px1b), right=Math.max(px0,px1b);
        ovCtx.save();ovCtx.globalAlpha=0.15;ovCtx.fillStyle=color;ovCtx.fillRect(left,r.y,right-left,r.h);ovCtx.restore();
        ovCtx.setLineDash([5,3]);
        ovCtx.beginPath();ovCtx.moveTo(px0,r.y);ovCtx.lineTo(px0,r.y+r.h);ovCtx.stroke();
        ovCtx.beginPath();ovCtx.moveTo(px1b,r.y);ovCtx.lineTo(px1b,r.y+r.h);ovCtx.stroke();
        ovCtx.setLineDash([]);
        _ovHandle1d(ovCtx,px0,r.y+7,color);_ovHandle1d(ovCtx,px1b,r.y+7,color);
      } else if(w.type==='point'){
        const px=_fracToPx1d(_xToFrac1d(xArr,w.x),x0,x1,r);
        const py=_valToPy1d(w.y,dMin,dMax,r);
        // Clip dashed crosshair guides to the plot rectangle
        ovCtx.save();ovCtx.beginPath();ovCtx.rect(r.x,r.y,r.w,r.h);ovCtx.clip();
        ovCtx.setLineDash([4,3]);
        ovCtx.beginPath();ovCtx.moveTo(px,r.y);ovCtx.lineTo(px,r.y+r.h);ovCtx.stroke();
        ovCtx.beginPath();ovCtx.moveTo(r.x,py);ovCtx.lineTo(r.x+r.w,py);ovCtx.stroke();
        ovCtx.setLineDash([]);
        ovCtx.restore();
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
    const r=_plotRect1d(pw,ph);
    const xArr=st.x_axis||[], x0=st.view_x0||0, x1=st.view_x1||1;
    const dMin=st.data_min, dMax=st.data_max;
    const yData=st.data||[];
    mkCtx.clearRect(0,0,pw,ph);
    const sets=st.markers||[];
    if(!sets.length) return;
    const hsi = hoverState ? hoverState.si : -1;

    mkCtx.save();mkCtx.beginPath();mkCtx.rect(r.x,r.y,r.w,r.h);mkCtx.clip();

    function _offToCanvas(off){
      const xFrac=xArr.length>=2?_xToFrac1d(xArr,off[0]):(off[0]/((xArr.length-1)||1));
      const px=_fracToPx1d(xFrac,x0,x1,r);
      let py;
      if(off.length>=2&&off[1]!=null){py=_valToPy1d(off[1],dMin,dMax,r);}
      else if(yData.length>1){const idx=Math.max(0,Math.min(yData.length-1,Math.round(xFrac*(yData.length-1))));py=_valToPy1d(yData[idx],dMin,dMax,r);}
      else{py=_valToPy1d(0,dMin,dMax,r);}
      return[px,py];
    }
    function _xPx(v){return _fracToPx1d(xArr.length>=2?_xToFrac1d(xArr,v):0,x0,x1,r);}
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
      mkCtx.save();mkCtx.strokeStyle=ec;mkCtx.fillStyle=ec;mkCtx.lineWidth=dlw;

      if(type==='points'){
        for(let i=0;i<ms.offsets.length;i++){
          const [px,py]=_offToCanvas(ms.offsets[i]);
          const sz=Math.max(1,ms.sizes[i]!=null?ms.sizes[i]:ms.sizes[0]||5);
          mkCtx.beginPath();mkCtx.arc(px,py,sz,0,Math.PI*2);
          if(fch){mkCtx.save();mkCtx.globalAlpha=fa;mkCtx.fillStyle=fch;mkCtx.fill();mkCtx.restore();}
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
          const [x1c,y1c]=_offToCanvas(seg[0]), [x2c,y2c]=_offToCanvas(seg[1]);
          mkCtx.beginPath();mkCtx.moveTo(x1c,y1c);mkCtx.lineTo(x2c,y2c);mkCtx.stroke();
        }
      } else if(type==='texts'){
        const fs=ms.fontsize||12;
        mkCtx.font=`${fs}px sans-serif`;mkCtx.textAlign='left';mkCtx.textBaseline='top';
        for(let i=0;i<ms.offsets.length;i++){
          const [px,py]=_offToCanvas(ms.offsets[i]);
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
    const r = _plotRect1d(p.pw, p.ph);
    if (mx < r.x || mx > r.x+r.w || my < r.y || my > r.y+r.h) return null;
    const xArr = st.x_axis||[], x0 = st.view_x0||0, x1 = st.view_x1||1;
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
      const physX = lineXArr.length >= 2 ? _fracToX1d(lineXArr, frac) : frac;
      const physY = dMin + (r.y + r.h - by) / (r.h||1) * (dMax - dMin);
      return { lineId, canvasPx: bx, canvasPy: by, x: physX, y: physY };
    }

    // Check extra lines first (drawn on top), then primary
    for (let i = (st.extra_lines||[]).length - 1; i >= 0; i--) {
      const ex = st.extra_lines[i];
      const hit = _nearestOnLine(ex.data, ex.x_axis || xArr, ex.id);
      if (hit) return hit;
    }
    return _nearestOnLine(st.data, xArr, null);
  }

  // ── marker hit-test helpers ────────────────────────────────────────────────
  const MARKER_HIT = 8;

  // Returns {si, i, collectionLabel, markerLabel} or null.
  // si/i identify the set/marker for hover; labels are for tooltips (null if unset).
  function _markerHitTest2d(mx, my, st, pw, ph) {
    const sets = st.markers || [];
    const scale = _imgScale2d(st, pw, ph);
    for (let si = sets.length-1; si >= 0; si--) {
      const ms = sets[si];
      const type = ms.type || 'circles';
      const collLabel = ms.label != null ? String(ms.label) : null;
      const perLabels = Array.isArray(ms.labels) ? ms.labels : null;
      if (type === 'circles') {
        for (let i=0;i<(ms.offsets||[]).length;i++) {
          const [cx,cy]=_imgToCanvas2d(ms.offsets[i][0],ms.offsets[i][1],st,pw,ph);
          const r=Math.max(1,(ms.sizes[i]!=null?ms.sizes[i]:ms.sizes[0]||5)*scale);
          if(Math.sqrt((mx-cx)**2+(my-cy)**2)<=r+MARKER_HIT)
            return{si,i,collectionLabel:collLabel,markerLabel:perLabels?String(perLabels[i]??''):null};
        }
      } else if (type === 'ellipses') {
        for (let i=0;i<(ms.offsets||[]).length;i++) {
          const [cx,cy]=_imgToCanvas2d(ms.offsets[i][0],ms.offsets[i][1],st,pw,ph);
          const rw=(ms.widths[i]||ms.widths[0]||10)*scale/2+MARKER_HIT;
          const rh=(ms.heights[i]||ms.heights[0]||10)*scale/2+MARKER_HIT;
          const dx=(mx-cx)/Math.max(1,rw), dy=(my-cy)/Math.max(1,rh);
          if(dx*dx+dy*dy<=1.0)
            return{si,i,collectionLabel:collLabel,markerLabel:perLabels?String(perLabels[i]??''):null};
        }
      } else if (type === 'rectangles' || type === 'squares') {
        const heights = type==='squares' ? ms.widths : ms.heights;
        for (let i=0;i<(ms.offsets||[]).length;i++) {
          const [cx,cy]=_imgToCanvas2d(ms.offsets[i][0],ms.offsets[i][1],st,pw,ph);
          const hw=(ms.widths[i]||ms.widths[0]||20)*scale/2+MARKER_HIT;
          const hh=((heights[i]||heights[0]||20))*scale/2+MARKER_HIT;
          if(Math.abs(mx-cx)<=hw&&Math.abs(my-cy)<=hh)
            return{si,i,collectionLabel:collLabel,markerLabel:perLabels?String(perLabels[i]??''):null};
        }
      } else if (type === 'arrows') {
        for (let i=0;i<(ms.offsets||[]).length;i++) {
          const [x1,y1]=_imgToCanvas2d(ms.offsets[i][0],ms.offsets[i][1],st,pw,ph);
          const mx2=x1+(ms.U[i]||0)*scale/2, my2=y1+(ms.V[i]||0)*scale/2;
          if(Math.sqrt((mx-mx2)**2+(my-my2)**2)<=MARKER_HIT*2)
            return{si,i,collectionLabel:collLabel,markerLabel:perLabels?String(perLabels[i]??''):null};
        }
      } else if (type === 'lines') {
        for (let i=0;i<(ms.segments||[]).length;i++) {
          const seg=ms.segments[i];
          const [x1,y1]=_imgToCanvas2d(seg[0][0],seg[0][1],st,pw,ph);
          const [x2,y2]=_imgToCanvas2d(seg[1][0],seg[1][1],st,pw,ph);
          const dx=x2-x1,dy=y2-y1,len2=dx*dx+dy*dy;
          const t=len2>0?Math.max(0,Math.min(1,((mx-x1)*dx+(my-y1)*dy)/len2)):0;
          if(Math.sqrt((mx-(x1+t*dx))**2+(my-(y1+t*dy))**2)<=MARKER_HIT)
            return{si,i,collectionLabel:collLabel,markerLabel:perLabels?String(perLabels[i]??''):null};
        }
      } else if (type === 'polygons') {
        for (let i=0;i<(ms.vertices_list||[]).length;i++) {
          const verts=ms.vertices_list[i]; if(!verts||!verts.length) continue;
          const [cx,cy]=_imgToCanvas2d(verts[0][0],verts[0][1],st,pw,ph);
          if(Math.sqrt((mx-cx)**2+(my-cy)**2)<=MARKER_HIT*1.5)
            return{si,i,collectionLabel:collLabel,markerLabel:perLabels?String(perLabels[i]??''):null};
        }
      } else if (type === 'texts') {
        for (let i=0;i<(ms.offsets||[]).length;i++) {
          const [cx,cy]=_imgToCanvas2d(ms.offsets[i][0],ms.offsets[i][1],st,pw,ph);
          if(Math.sqrt((mx-cx)**2+(my-cy)**2)<=MARKER_HIT*1.5)
            return{si,i,collectionLabel:collLabel,markerLabel:perLabels?String(perLabels[i]??''):null};
        }
      }
    }
    return null;
  }

  function _markerHitTest1d(mx, my, p) {
    const st=p.state; if(!st) return null;
    const r=_plotRect1d(p.pw,p.ph);
    const xArr=st.x_axis||[], x0=st.view_x0||0, x1=st.view_x1||1;
    const dMin=st.data_min, dMax=st.data_max;
    const sets=st.markers||[];
    for(let si=sets.length-1;si>=0;si--){
      const ms=sets[si];
      const collLabel=ms.label!=null?String(ms.label):null;
      const perLabels=Array.isArray(ms.labels)?ms.labels:null;
      if(ms.type==='points'){
        for(let i=0;i<(ms.offsets||[]).length;i++){
          const frac=xArr.length>=2?_xToFrac1d(xArr,ms.offsets[i][0]):0;
          const px=_fracToPx1d(frac,x0,x1,r);
          const sz=Math.max(1,ms.sizes[i]!=null?ms.sizes[i]:ms.sizes[0]||5);
          if(Math.sqrt((mx-px)**2+(my-r.y-r.h/2)**2)<=sz+MARKER_HIT)
            return{si,i,collectionLabel:collLabel,markerLabel:perLabels?String(perLabels[i]??''):null};
        }
      } else if(ms.type==='vlines'){
        for(let i=0;i<(ms.offsets||[]).length;i++){
          const px=_fracToPx1d(xArr.length>=2?_xToFrac1d(xArr,ms.offsets[i][0]):0,x0,x1,r);
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
          const xf1=xArr.length>=2?_xToFrac1d(xArr,seg[0][0]):0;
          const xf2=xArr.length>=2?_xToFrac1d(xArr,seg[1][0]):0;
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

  // ── panel-level event handlers ───────────────────────────────────────────
  function _attachPanelEvents(p) {
    if (p.kind === '2d')  _attachEvents2d(p);
    else if (p.kind === '3d')  _attachEvents3d(p);
    else if (p.kind === 'bar') _attachEventsBar(p);
    else                       _attachEvents1d(p);
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
    let localOnly=false, commitPending=false;
    function _scheduleCommit(){
      if(commitPending) return; commitPending=true;
      requestAnimationFrame(()=>{commitPending=false;localOnly=true;model.save_changes();setTimeout(()=>{localOnly=false;},200);});
    }

    // Wheel zoom — anchored on the image point under the cursor
    overlayCanvas.addEventListener('wheel',(e)=>{
      e.preventDefault();
      const st=p.state; if(!st) return;
      const imgW=Math.max(1,p.pw-PAD_L-PAD_R), imgH=Math.max(1,p.ph-PAD_T-PAD_B);
      const {mx,my}=_clientPos(e,overlayCanvas,imgW,imgH);
      // Image point under cursor before zoom change
      const [anchorX,anchorY]=_canvasToImg2d(mx,my,st,imgW,imgH);
      const curZ=st.zoom, newZ=Math.max(0.75,Math.min(100,curZ*(e.deltaY>0?0.9:1.1)));
      st.zoom=newZ;
      // Reposition center so the same image point stays under the cursor
      const iw=st.image_width, ih=st.image_height;
      const fr=_imgFitRect(iw,ih,imgW,imgH);
      const newVisW=iw/newZ, newVisH=ih/newZ;
      const newSrcX=anchorX-(mx-fr.x)/fr.w*newVisW;
      const newSrcY=anchorY-(my-fr.y)/fr.h*newVisH;
      st.center_x=Math.max(0,Math.min(1,(newSrcX+newVisW/2)/iw));
      st.center_y=Math.max(0,Math.min(1,(newSrcY+newVisH/2)/ih));
      draw2d(p);
      _propagateZoom2d(p);
      model.set(`panel_${p.id}_json`, JSON.stringify(p.state));
      _scheduleCommit();
    },{passive:false});

    // Pan + widget drag
    let panStart={};
    overlayCanvas.addEventListener('mousedown',(e)=>{
      if(e.button!==0) return;
      const st=p.state; if(!st) return;
      overlayCanvas.focus();
      const imgW=Math.max(1,p.pw-PAD_L-PAD_R), imgH=Math.max(1,p.ph-PAD_T-PAD_B);
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
      p.isPanning=true; overlayCanvas.style.cursor='grabbing'; e.preventDefault();
    });
    document.addEventListener('mousemove',(e)=>{
      if(p.ovDrag2d){
        _doDrag2d(e,p);
        const _dw=(p.state.overlay_widgets||[])[p.ovDrag2d.idx]||{};
        _emitEvent(p.id,'on_changed',_dw.id||null,_dw);
        return;
      }
      if(!p.isPanning) return;
      const st=p.state; if(!st) return;
      const imgW=Math.max(1,p.pw-PAD_L-PAD_R), imgH=Math.max(1,p.ph-PAD_T-PAD_B);
      const fr=_imgFitRect(st.image_width,st.image_height,imgW,imgH);
      const z=st.zoom;
      const {mx:cmx,my:cmy}=_clientPos(e,overlayCanvas,imgW,imgH);
      localOnly=true;
      st.center_x=Math.max(0,Math.min(1,panStart.cx-(cmx-panStart.mx)/fr.w/z));
      st.center_y=Math.max(0,Math.min(1,panStart.cy-(cmy-panStart.my)/fr.h/z));
      draw2d(p);
      _propagateZoom2d(p);
      model.set(`panel_${p.id}_json`, JSON.stringify(p.state));
      _scheduleCommit(); e.preventDefault();
    });
    document.addEventListener('mouseup',(e)=>{
      if(p.ovDrag2d){
        const _idx=p.ovDrag2d.idx;
        const _dw=(p.state.overlay_widgets||[])[_idx]||{};
        const _did=_dw.id||null;
        p.ovDrag2d=null; overlayCanvas.style.cursor='default';
        model.set(`panel_${p.id}_json`, JSON.stringify(p.state));
        _emitEvent(p.id,'on_release',_did,_dw);
        return;
      }
      if(!p.isPanning) return;
      p.isPanning=false; overlayCanvas.style.cursor='default';
      const st=p.state; if(!st) return;
      const imgW=Math.max(1,p.pw-PAD_L-PAD_R), imgH=Math.max(1,p.ph-PAD_T-PAD_B);
      const fr=_imgFitRect(st.image_width,st.image_height,imgW,imgH);
      const {mx:cmx,my:cmy}=_clientPos(e,overlayCanvas,imgW,imgH);
      st.center_x=Math.max(0,Math.min(1,panStart.cx-(cmx-panStart.mx)/fr.w/st.zoom));
      st.center_y=Math.max(0,Math.min(1,panStart.cy-(cmy-panStart.my)/fr.h/st.zoom));
      model.set(`panel_${p.id}_json`, JSON.stringify(p.state));
      _emitEvent(p.id,'on_release',null,{center_x:st.center_x,center_y:st.center_y,zoom:st.zoom});
      model.save_changes();
    });

    // Status bar + tooltip + widget hover cursor
    overlayCanvas.addEventListener('mousemove',(e)=>{
      const imgW=Math.max(1,p.pw-PAD_L-PAD_R), imgH=Math.max(1,p.ph-PAD_T-PAD_B);
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
        if(mhit&&(mhit.collectionLabel||mhit.markerLabel)){const parts=[];if(mhit.collectionLabel)parts.push(mhit.collectionLabel);if(mhit.markerLabel)parts.push(mhit.markerLabel);_showTooltip(parts.join('\n'),e.clientX,e.clientY);return;}
        tooltip.style.display='none';
      } else { p.statusBar.style.display='none'; tooltip.style.display='none';
        if(p._hoverSi!==-1){p._hoverSi=-1;p._hoverI=-1;drawMarkers2d(p,null);}
      }
    });
    overlayCanvas.addEventListener('mouseleave',()=>{p.statusBar.style.display='none';tooltip.style.display='none';
      if(p._hoverSi!==-1){p._hoverSi=-1;p._hoverI=-1;drawMarkers2d(p,null);}
    });

    // Keyboard shortcuts
    // Built-ins: r=reset zoom, c=colorbar toggle, l=log scale, s=symlog scale.
    // Any key listed in st.registered_keys (or '*' for all keys) is forwarded
    // to Python via on_key and suppresses the matching built-in.
    overlayCanvas.addEventListener('keydown',(e)=>{
      const st=p.state; if(!st) return;
      const regKeys=st.registered_keys||[];
      if(regKeys.includes(e.key)||regKeys.includes('*')){
        const imgW=Math.max(1,p.pw-PAD_L-PAD_R), imgH=Math.max(1,p.ph-PAD_T-PAD_B);
        const [imgX,imgY]=_canvasToImg2d(p.mouseX,p.mouseY,st,imgW,imgH);
        const xArr=st.x_axis||[], yArr=st.y_axis||[];
        const iw=st.image_width||1, ih=st.image_height||1;
        const physX=xArr.length>=2?_axisFracToVal(xArr,imgX/iw):imgX;
        const physY=yArr.length>=2?_axisFracToVal(yArr,imgY/ih):imgY;
        _emitEvent(p.id,'on_key',null,{
          key:e.key,
          last_widget_id:p.lastWidgetId||null,
          mouse_x:p.mouseX, mouse_y:p.mouseY,
          img_x:imgX, img_y:imgY,
          phys_x:physX, phys_y:physY,
        });
        e.stopPropagation(); e.preventDefault(); return;
      }
      const key=e.key.toLowerCase();
      if(key==='r'){
        st.zoom=1; st.center_x=0.5; st.center_y=0.5;
        draw2d(p); model.set(`panel_${p.id}_json`,JSON.stringify(st)); model.save_changes();
        e.stopPropagation(); e.preventDefault();
      } else if(key==='c'){
        st.show_colorbar=!st.show_colorbar;
        draw2d(p);
        model.set(`panel_${p.id}_json`,JSON.stringify(st)); model.save_changes();
        e.stopPropagation(); e.preventDefault();
      } else if(key==='l'){
        st.scale_mode=st.scale_mode==='log'?'linear':'log';
        draw2d(p); model.set(`panel_${p.id}_json`,JSON.stringify(st)); model.save_changes();
        e.stopPropagation(); e.preventDefault();
      } else if(key==='s'){
        st.scale_mode=st.scale_mode==='symlog'?'linear':'symlog';
        draw2d(p); model.set(`panel_${p.id}_json`,JSON.stringify(st)); model.save_changes();
        e.stopPropagation(); e.preventDefault();
      }
    });
    overlayCanvas.addEventListener('mouseenter',()=>overlayCanvas.focus());
  }

  function _attachEvents1d(p) {
    const { overlayCanvas } = p;
    let localOnly=false, commitPending=false;
    function _scheduleCommit(){
      if(commitPending) return; commitPending=true;
      requestAnimationFrame(()=>{commitPending=false;localOnly=true;model.save_changes();setTimeout(()=>{localOnly=false;},200);});
    }

    // Wheel zoom
    overlayCanvas.addEventListener('wheel',(e)=>{
      e.preventDefault();
      const st=p.state; if(!st) return;
      const r=_plotRect1d(p.pw,p.ph);
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
      model.set(`panel_${p.id}_json`,JSON.stringify(st));
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
      p.isPanning=true;overlayCanvas.style.cursor='grabbing';e.preventDefault();
    });
    document.addEventListener('mousemove',(e)=>{
      if(p.ovDrag){
        _doDrag1d(e,p);
        const _dw=(p.state.overlay_widgets||[])[p.ovDrag.idx]||{};
        _emitEvent(p.id,'on_changed',_dw.id||null,_dw);
        return;
      }
      if(!p.isPanning) return;
      const st=p.state; if(!st) return;
      const r=_plotRect1d(p.pw,p.ph);
      const {mx:cmx}=_clientPos(e,overlayCanvas,p.pw,p.ph);
      const dx=(cmx-panStart.mx)/(r.w||1);
      const span=panStart.x1-panStart.x0;
      let nx0=panStart.x0-dx*span, nx1=panStart.x1-dx*span;
      if(nx0<0){nx0=0;nx1=span;}if(nx1>1){nx1=1;nx0=1-span;}
      st.view_x0=nx0;st.view_x1=nx1;
      draw1d(p);_propagateView1d(p);
      model.set(`panel_${p.id}_json`,JSON.stringify(st));_scheduleCommit();e.preventDefault();
    });
    document.addEventListener('mouseup',(e)=>{
      const wasDragging=!!p.ovDrag||!!p.isPanning;
      if(p.ovDrag){
        const _idx=p.ovDrag.idx;
        const _dw=(p.state.overlay_widgets||[])[_idx]||{};
        const _did=_dw.id||null;
        p.ovDrag=null; overlayCanvas.style.cursor='crosshair';
        model.set(`panel_${p.id}_json`,JSON.stringify(p.state));
        _emitEvent(p.id,'on_release',_did,_dw);
      }
      if(p.isPanning){
        p.isPanning=false; overlayCanvas.style.cursor='crosshair';
        const st=p.state;
        if(st) _emitEvent(p.id,'on_release',null,{view_x0:st.view_x0,view_x1:st.view_x1});
      }
      // Line click: only when no drag/pan occurred and mouse barely moved
      if(!wasDragging && p._mousedownX!=null){
        const mdx=e.clientX-p._mousedownX, mdy=e.clientY-p._mousedownY;
        if(Math.hypot(mdx,mdy)<5){
          const {mx,my}=_clientPos(e,overlayCanvas,p.pw,p.ph);
          const lhit=_lineHitTest1d(mx,my,p);
          if(lhit) _emitEvent(p.id,'on_line_click',null,{line_id:lhit.lineId,x:lhit.x,y:lhit.y});
        }
      }
      p._mousedownX=null;
    });

    // Keyboard shortcuts
    // Built-in: r=reset view. Any key in st.registered_keys (or '*') is
    // forwarded to Python via on_key and suppresses the matching built-in.
    overlayCanvas.addEventListener('keydown',(e)=>{
      const st=p.state; if(!st) return;
      const regKeys=st.registered_keys||[];
      if(regKeys.includes(e.key)||regKeys.includes('*')){
        const r=_plotRect1d(p.pw,p.ph);
        const xArr=st.x_axis||[];
        const frac=_canvasXToFrac1d(p.mouseX,st.view_x0,st.view_x1,r);
        const physX=xArr.length>=2?_fracToX1d(xArr,frac):frac;
        _emitEvent(p.id,'on_key',null,{
          key:e.key,
          last_widget_id:p.lastWidgetId||null,
          mouse_x:p.mouseX, mouse_y:p.mouseY,
          phys_x:physX,
        });
        e.stopPropagation(); e.preventDefault(); return;
      }
      if(e.key.toLowerCase()==='r'){st.view_x0=0;st.view_x1=1;draw1d(p);model.set(`panel_${p.id}_json`,JSON.stringify(st));model.save_changes();e.stopPropagation();e.preventDefault();}
    });
    overlayCanvas.tabIndex=0;overlayCanvas.style.outline='none';
    overlayCanvas.addEventListener('mouseenter',()=>overlayCanvas.focus());
    overlayCanvas.addEventListener('mousemove',(e)=>{
      const st=p.state;if(!st)return;
      const {mx,my}=_clientPos(e,overlayCanvas,p.pw,p.ph);
      p.mouseX=mx; p.mouseY=my;
      const r=_plotRect1d(p.pw,p.ph);
      if(mx<r.x||mx>r.x+r.w||my<r.y||my>r.y+r.h){
        p.statusBar.style.display='none';tooltip.style.display='none';
        if(p._hoverSi!==-1){p._hoverSi=-1;p._hoverI=-1;drawMarkers1d(p,null);}
        return;
      }
      const xArr=st.x_axis||[];
      const frac=_canvasXToFrac1d(mx,st.view_x0,st.view_x1,r);
      const phys=xArr.length>=2?_fracToX1d(xArr,frac):frac;
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
          drawOverlay1d(p);
          if(lhit){
            p.ovCtx.save();p.ovCtx.fillStyle='rgba(255,255,255,0.9)';
            p.ovCtx.strokeStyle='rgba(0,0,0,0.5)';p.ovCtx.lineWidth=1.5;
            p.ovCtx.beginPath();p.ovCtx.arc(lhit.canvasPx,lhit.canvasPy,4,0,Math.PI*2);
            p.ovCtx.fill();p.ovCtx.stroke();p.ovCtx.restore();
          }
        }
        if(lhit) _emitEvent(p.id,'on_line_hover',null,{line_id:lhit.lineId,x:lhit.x,y:lhit.y});
      }
    });
    overlayCanvas.addEventListener('mouseleave',()=>{p.statusBar.style.display='none';tooltip.style.display='none';
      if(p._hoverSi!==-1){p._hoverSi=-1;p._hoverI=-1;drawMarkers1d(p,null);}
      if(p._lineHoverId!=='__none__'){p._lineHoverId='__none__';drawOverlay1d(p);}
    });
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
    const imgW = Math.max(1, p.pw - PAD_L - PAD_R);
    const imgH = Math.max(1, p.ph - PAD_T - PAD_B);
    const widgets = st.overlay_widgets || [];
    const scale   = _imgScale2d(st, imgW, imgH);
    const HR = 9; // handle grab radius (px)

    // iterate top-to-bottom (last drawn = topmost)
    for (let i = widgets.length - 1; i >= 0; i--) {
      const w = widgets[i];
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
      }
    }
    return null;
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
    const imgW = Math.max(1, p.pw - PAD_L - PAD_R);
    const imgH = Math.max(1, p.ph - PAD_T - PAD_B);
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
    }

    drawOverlay2d(p);
    model.set(`panel_${p.id}_json`, JSON.stringify(st));
    model.save_changes();
    e.preventDefault();
  }

  function _canvasXToFrac1d(px,x0,x1,r){return x0+((px-r.x)/(r.w||1))*(x1-x0);}

  function _ovHitTest1d(mx,my,p){
    const st=p.state;if(!st)return null;
    const r=_plotRect1d(p.pw,p.ph);
    const xArr=st.x_axis||[],x0=st.view_x0||0,x1=st.view_x1||1;
    const widgets=st.overlay_widgets||[];
    const HR=7;
    for(let i=widgets.length-1;i>=0;i--){
      const w=widgets[i];
      if(w.type==='vline'){
        const px=_fracToPx1d(_xToFrac1d(xArr,w.x),x0,x1,r);
        if(Math.sqrt((mx-px)**2+(my-(r.y+7))**2)<=HR||Math.abs(mx-px)<=5)
          return{idx:i,mode:'move',wtype:'vline',startMX:mx,snapW:{...w}};
      } else if(w.type==='hline'){
        const py=_valToPy1d(w.y,st.data_min,st.data_max,r);
        if(Math.abs(my-py)<=5) return{idx:i,mode:'move',wtype:'hline',startMY:my,snapW:{...w}};
      } else if(w.type==='range'){
        const px0=_fracToPx1d(_xToFrac1d(xArr,w.x0),x0,x1,r);
        const px1b=_fracToPx1d(_xToFrac1d(xArr,w.x1),x0,x1,r);
        if(Math.abs(mx-px0)<=HR+5) return{idx:i,mode:'edge0',wtype:'range',startMX:mx,snapW:{...w}};
        if(Math.abs(mx-px1b)<=HR+5) return{idx:i,mode:'edge1',wtype:'range',startMX:mx,snapW:{...w}};
        const left=Math.min(px0,px1b),right=Math.max(px0,px1b);
        if(mx>=left&&mx<=right&&my>=r.y&&my<=r.y+r.h) return{idx:i,mode:'move',wtype:'range',startMX:mx,snapW:{...w}};
      } else if(w.type==='point'){
        const px=_fracToPx1d(_xToFrac1d(xArr,w.x),x0,x1,r);
        const py=_valToPy1d(w.y,st.data_min,st.data_max,r);
        if(Math.hypot(mx-px,my-py)<=HR+4)
          return{idx:i,mode:'move',wtype:'point',startMX:mx,startMY:my,snapW:{...w}};
      }
    }
    return null;
  }

  function _doDrag1d(e,p){
    const st=p.state;if(!st)return;
    const r=_plotRect1d(p.pw,p.ph);
    const {mx,my:py}=_clientPos(e,p.overlayCanvas,p.pw,p.ph);
    const xArr=st.x_axis||[],x0=st.view_x0||0,x1=st.view_x1||1;
    const xUnit=xArr.length>=2?_fracToX1d(xArr,_canvasXToFrac1d(mx,x0,x1,r)):_canvasXToFrac1d(mx,x0,x1,r);
    const widgets=st.overlay_widgets;
    const d=p.ovDrag, s=d.snapW, w=widgets[d.idx];
    if(w.type==='vline'){w.x=xUnit;}
    else if(w.type==='hline'){w.y=st.data_max-((py-r.y)/(r.h||1))*(st.data_max-st.data_min);}
    else if(w.type==='range'){
      if(d.mode==='edge0') w.x0=xUnit;
      else if(d.mode==='edge1') w.x1=xUnit;
      else {
        const snapPx=_fracToPx1d(xArr.length>=2?_xToFrac1d(xArr,s.x0):0,x0,x1,r);
        const dxUnit=xArr.length>=2?_fracToX1d(xArr,_canvasXToFrac1d(snapPx+(mx-d.startMX),x0,x1,r))-s.x0:(mx-d.startMX)/(r.w||1);
        w.x0=s.x0+dxUnit;w.x1=s.x1+dxUnit;
      }
    } else if(w.type==='point'){
      // Clamp to plot rectangle
      const clampX=Math.max(r.x,Math.min(r.x+r.w,mx));
      const clampY=Math.max(r.y,Math.min(r.y+r.h,py));
      w.x=xArr.length>=2?_fracToX1d(xArr,_canvasXToFrac1d(clampX,x0,x1,r)):_canvasXToFrac1d(clampX,x0,x1,r);
      w.y=st.data_max-((clampY-r.y)/(r.h||1))*(st.data_max-st.data_min);
    }
    drawOverlay1d(p);
    model.set(`panel_${p.id}_json`,JSON.stringify(st));model.save_changes();
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
          model.set(`panel_${pid}_json`,JSON.stringify(tp.state));
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
          model.set(`panel_${pid}_json`,JSON.stringify(tp.state));
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
      const imgX = PAD_L, imgY = PAD_T;
      const imgW = Math.max(1, pw - PAD_L - PAD_R);
      const imgH = Math.max(1, ph - PAD_T - PAD_B);

      if (p.plotWrap) { p.plotWrap.style.width=pw+'px'; p.plotWrap.style.height=ph+'px'; }

      _szCSS(p.plotCanvas,    imgW, imgH);
      _szCSS(p.overlayCanvas, imgW, imgH);
      _szCSS(p.markersCanvas, imgW, imgH);

      p.plotCanvas.style.left    = imgX+'px'; p.plotCanvas.style.top    = imgY+'px';
      p.overlayCanvas.style.left = imgX+'px'; p.overlayCanvas.style.top = imgY+'px';
      p.markersCanvas.style.left = imgX+'px'; p.markersCanvas.style.top = imgY+'px';

      if (p.statusBar) { p.statusBar.style.left=(imgX+4)+'px'; p.statusBar.style.bottom=(PAD_B+4)+'px'; }
      if (p.scaleBar)  { p.scaleBar.style.right=(PAD_R+12)+'px'; p.scaleBar.style.bottom=(PAD_B+12)+'px'; }

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
        _szCSS(p.cbCanvas, 16, imgH);
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
  // Returns the per-slot pixel width, per-bar pixel width, and coordinate
  // mappers for the current panel state.
  function _barGeom(st, r) {
    const values   = st.values   || [];
    const n        = values.length || 1;
    const orient   = st.orient   || 'v';
    const bwFrac   = st.bar_width !== undefined ? st.bar_width : 0.7;
    const baseline = st.baseline !== undefined  ? st.baseline  : 0;
    const dMin     = st.data_min, dMax = st.data_max;

    if (orient === 'h') {
      // Horizontal: categories on Y, values on X
      const slotPx = r.h / n;
      const barPx  = slotPx * bwFrac;
      // xToPx maps a value to an x pixel (value axis = horizontal)
      function xToPx(v) { return r.x + ((v - dMin) / ((dMax - dMin) || 1)) * r.w; }
      // yToPx maps a bar index to the centre of its slot (category axis = vertical)
      function yToPx(i) { return r.y + (i + 0.5) * slotPx; }
      const basePx = Math.max(r.x, Math.min(r.x + r.w, xToPx(baseline)));
      return { n, orient, slotPx, barPx, dMin, dMax, baseline, basePx, xToPx, yToPx };
    } else {
      // Vertical: categories on X, values on Y
      const slotPx = r.w / n;
      const barPx  = slotPx * bwFrac;
      function xToPx(i) { return r.x + (i + 0.5) * slotPx; }
      function yToPx(v) { return r.y + r.h - ((v - dMin) / ((dMax - dMin) || 1)) * r.h; }
      const basePx = Math.max(r.y, Math.min(r.y + r.h, yToPx(baseline)));
      return { n, orient, slotPx, barPx, dMin, dMax, baseline, basePx, xToPx, yToPx };
    }
  }

  function drawBar(p) {
    const st = p.state; if (!st) return;
    _recordFrame(p);
    const { pw, ph, plotCtx: ctx } = p;
    const r = _plotRect1d(pw, ph);

    ctx.clearRect(0, 0, pw, ph);
    ctx.fillStyle = theme.bg;     ctx.fillRect(0, 0, pw, ph);
    ctx.fillStyle = theme.bgPlot; ctx.fillRect(r.x, r.y, r.w, r.h);

    const values    = st.values    || [];
    const xCenters  = st.x_centers || values.map((_, i) => i);
    const xLabels   = st.x_labels  || [];
    const barColor  = st.bar_color  || '#4fc3f7';
    const barColors = st.bar_colors || [];
    const orient    = st.orient || 'v';
    const dMin      = st.data_min, dMax = st.data_max;

    if (!values.length) return;

    const g = _barGeom(st, r);

    // ── grid lines (along value axis) ─────────────────────────────────────
    ctx.strokeStyle = theme.gridStroke; ctx.lineWidth = 1;
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

    // ── bars ──────────────────────────────────────────────────────────────
    ctx.save(); ctx.beginPath(); ctx.rect(r.x, r.y, r.w, r.h); ctx.clip();

    for (let i = 0; i < g.n; i++) {
      const color = barColors[i] || barColor;
      const isHov = (p._hovBar === i);

      if (orient === 'h') {
        const cy      = g.yToPx(i);
        const valPx   = g.xToPx(values[i]);
        const barLeft = Math.min(valPx, g.basePx);
        const barW    = Math.max(1, Math.abs(valPx - g.basePx));
        ctx.fillStyle = color;
        ctx.fillRect(barLeft, cy - g.barPx / 2, barW, g.barPx);
        if (isHov) {
          ctx.save(); ctx.fillStyle = 'rgba(255,255,255,0.22)';
          ctx.fillRect(barLeft, cy - g.barPx / 2, barW, g.barPx);
          ctx.restore();
        }
        ctx.strokeStyle = theme.dark ? 'rgba(0,0,0,0.25)' : 'rgba(0,0,0,0.09)';
        ctx.lineWidth = 0.5;
        ctx.strokeRect(barLeft, cy - g.barPx / 2, barW, g.barPx);
      } else {
        const cx     = g.xToPx(i);
        const valPy  = g.yToPx(values[i]);
        const barTop = Math.min(valPy, g.basePx);
        const barH   = Math.max(1, Math.abs(valPy - g.basePx));
        ctx.fillStyle = color;
        ctx.fillRect(cx - g.barPx / 2, barTop, g.barPx, barH);
        if (isHov) {
          ctx.save(); ctx.fillStyle = 'rgba(255,255,255,0.22)';
          ctx.fillRect(cx - g.barPx / 2, barTop, g.barPx, barH);
          ctx.restore();
        }
        ctx.strokeStyle = theme.dark ? 'rgba(0,0,0,0.25)' : 'rgba(0,0,0,0.09)';
        ctx.lineWidth = 0.5;
        ctx.strokeRect(cx - g.barPx / 2, barTop, g.barPx, barH);
      }
    }
    ctx.restore();

    // ── value annotations ─────────────────────────────────────────────────
    if (st.show_values) {
      ctx.font = '9px monospace'; ctx.fillStyle = theme.tickText;
      for (let i = 0; i < g.n; i++) {
        if (orient === 'h') {
          const cy    = g.yToPx(i);
          const valPx = g.xToPx(values[i]);
          const above = values[i] >= g.baseline;
          ctx.textAlign    = above ? 'left' : 'right';
          ctx.textBaseline = 'middle';
          ctx.fillText(fmtVal(values[i]), valPx + (above ? 3 : -3), cy);
        } else {
          const cx    = g.xToPx(i);
          const valPy = g.yToPx(values[i]);
          const above = values[i] >= g.baseline;
          ctx.textAlign    = 'center';
          ctx.textBaseline = above ? 'bottom' : 'top';
          ctx.fillText(fmtVal(values[i]), cx, valPy + (above ? -2 : 2));
        }
      }
    }

    // ── axis borders ──────────────────────────────────────────────────────
    ctx.strokeStyle = theme.axisStroke; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(r.x, r.y + r.h); ctx.lineTo(r.x + r.w, r.y + r.h); ctx.stroke();
    ctx.beginPath(); ctx.moveTo(r.x, r.y);         ctx.lineTo(r.x, r.y + r.h);       ctx.stroke();

    // Explicit baseline when it isn't at the plot edge
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

    // ── tick labels ───────────────────────────────────────────────────────
    ctx.font = '10px monospace'; ctx.fillStyle = theme.tickText;

    if (orient === 'h') {
      // Value axis → X ticks at bottom
      ctx.textAlign = 'center'; ctx.textBaseline = 'top';
      for (let v = Math.ceil(dMin/valStep)*valStep; v <= dMax+valStep*0.01; v += valStep) {
        const px = g.xToPx(v);
        if (px < r.x || px > r.x + r.w) continue;
        ctx.strokeStyle = theme.axisStroke;
        ctx.beginPath(); ctx.moveTo(px, r.y + r.h); ctx.lineTo(px, r.y + r.h + 4); ctx.stroke();
        ctx.fillStyle = theme.tickText;
        ctx.fillText(fmtVal(v), px, r.y + r.h + 7);
      }
      // Category axis → Y labels on left
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
      // Units
      if (st.y_units) {
        ctx.textAlign='right'; ctx.textBaseline='top'; ctx.font='9px monospace';
        ctx.fillStyle=theme.unitText;
        ctx.fillText(st.y_units, r.x + r.w, r.y + r.h + 24);
        ctx.font='10px monospace';
      }
      if (st.units) {
        ctx.save();
        ctx.translate(Math.round(PAD_L * 0.28), r.y + r.h / 2); ctx.rotate(-Math.PI/2);
        ctx.textAlign='center'; ctx.textBaseline='middle';
        ctx.fillStyle=theme.unitText; ctx.font='9px monospace';
        ctx.fillText(st.units, 0, 0);
        ctx.restore();
      }
    } else {
      // Category axis → X ticks at bottom
      ctx.textAlign = 'center'; ctx.textBaseline = 'top';
      const maxCatLabels = Math.max(1, Math.floor(r.w / 42));
      const catStep = Math.max(1, Math.ceil(g.n / maxCatLabels));
      for (let i = 0; i < g.n; i += catStep) {
        const cx    = g.xToPx(i);
        const label = xLabels[i] !== undefined ? String(xLabels[i]) : fmtVal(xCenters[i]);
        ctx.strokeStyle = theme.axisStroke;
        ctx.beginPath(); ctx.moveTo(cx, r.y + r.h); ctx.lineTo(cx, r.y + r.h + 4); ctx.stroke();
        ctx.fillStyle = theme.tickText;
        ctx.fillText(label, cx, r.y + r.h + 7);
      }
      if (st.units && st.units !== 'px') {
        ctx.textAlign='right'; ctx.textBaseline='top'; ctx.font='9px monospace';
        ctx.fillStyle=theme.unitText;
        ctx.fillText(st.units, r.x + r.w, r.y + r.h + 24);
        ctx.font='10px monospace';
      }
      // Value axis → Y ticks on left
      ctx.textAlign = 'right'; ctx.textBaseline = 'middle';
      for (let v = Math.ceil(dMin/valStep)*valStep; v <= dMax+valStep*0.01; v += valStep) {
        const py = g.yToPx(v);
        if (py < r.y || py > r.y + r.h) continue;
        ctx.strokeStyle = theme.axisStroke;
        ctx.beginPath(); ctx.moveTo(r.x, py); ctx.lineTo(r.x - 5, py); ctx.stroke();
        ctx.fillStyle = theme.tickText;
        ctx.fillText(fmtVal(v), r.x - 8, py);
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

    // Overlay widgets (vlines, hlines) drawn on the overlay canvas
    drawOverlay1d(p);
  }

  function _attachEventsBar(p) {
    const { overlayCanvas } = p;

    // Return the bar index at canvas position (mx, my), or -1 if none.
    function _barHit(mx, my) {
      const st = p.state; if (!st || !st.values.length) return -1;
      const r  = _plotRect1d(p.pw, p.ph);
      if (mx < r.x || mx > r.x + r.w || my < r.y || my > r.y + r.h) return -1;
      const g = _barGeom(st, r);
      for (let i = 0; i < g.n; i++) {
        if (g.orient === 'h') {
          const cy    = g.yToPx(i);
          const valPx = g.xToPx(st.values[i]);
          const left  = Math.min(valPx, g.basePx);
          const barW  = Math.max(1, Math.abs(valPx - g.basePx));
          if (Math.abs(my - cy) <= g.barPx / 2 && mx >= left && mx <= left + barW) return i;
        } else {
          const cx    = g.xToPx(i);
          const valPy = g.yToPx(st.values[i]);
          const top   = Math.min(valPy, g.basePx);
          const barH  = Math.max(1, Math.abs(valPy - g.basePx));
          if (Math.abs(mx - cx) <= g.barPx / 2 && my >= top && my <= top + barH) return i;
        }
      }
      return -1;
    }

    // Widget drag support
    let commitPending = false;
    function _scheduleCommit() {
      if (commitPending) return; commitPending = true;
      requestAnimationFrame(() => { commitPending = false; model.save_changes(); });
    }

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
      _emitEvent(p.id, 'on_changed', _dw.id || null, _dw);
    });

    document.addEventListener('mouseup', (e) => {
      if (!p.ovDrag) return;
      const _idx = p.ovDrag.idx;
      const _dw  = (p.state.overlay_widgets || [])[_idx] || {};
      const _did = _dw.id || null;
      p.ovDrag = null;
      overlayCanvas.style.cursor = 'default';
      model.set(`panel_${p.id}_json`, JSON.stringify(p.state));
      _emitEvent(p.id, 'on_release', _did, _dw);
      _scheduleCommit();
    });

    overlayCanvas.addEventListener('mousemove', (e) => {
      const {mx, my} = _clientPos(e, overlayCanvas, p.pw, p.ph);
      p.mouseX = mx; p.mouseY = my;
      if (p.ovDrag) return;  // handled by document mousemove during drag
      const st = p.state; if (!st) return;

      // Overlay widget cursor hint
      const whit = _ovHitTest1d(mx, my, p);
      if (whit) {
        overlayCanvas.style.cursor = 'ew-resize';
        tooltip.style.display = 'none';
        if (p._hovBar !== -1) { p._hovBar = -1; drawBar(p); }
        return;
      }

      const idx = _barHit(mx, my);
      if (idx !== p._hovBar) {
        p._hovBar = idx;
        drawBar(p);
      }
      if (idx >= 0) {
        const label = (st.x_labels||[])[idx] !== undefined
          ? String(st.x_labels[idx])
          : fmtVal((st.x_centers||[])[idx] ?? idx);
        _showTooltip(`${label}: ${fmtVal(st.values[idx])}`, e.clientX, e.clientY);
        overlayCanvas.style.cursor = 'pointer';
      } else {
        tooltip.style.display = 'none';
        overlayCanvas.style.cursor = 'default';
      }
    });

    overlayCanvas.addEventListener('mouseleave', () => {
      if (p._hovBar !== -1) { p._hovBar = -1; drawBar(p); }
      tooltip.style.display = 'none';
    });

    overlayCanvas.addEventListener('click', (e) => {
      if (p.ovDrag) return;
      const st = p.state; if (!st) return;
      const {mx:_cmx, my:_cmy} = _clientPos(e, overlayCanvas, p.pw, p.ph);
      const idx  = _barHit(_cmx, _cmy);
      if (idx < 0) return;
      _emitEvent(p.id, 'on_click', null, {
        bar_index: idx,
        value:     st.values[idx],
        x_center:  (st.x_centers||[])[idx] ?? idx,
        x_label:   (st.x_labels||[])[idx]  !== undefined
                     ? String(st.x_labels[idx]) : null,
      });
    });

    // Keyboard: registered_keys forwarded to Python; no built-in bar shortcuts.
    overlayCanvas.addEventListener('keydown', (e) => {
      const st = p.state; if (!st) return;
      const regKeys = st.registered_keys || [];
      if (regKeys.includes(e.key) || regKeys.includes('*')) {
        _emitEvent(p.id, 'on_key', null, {
          key: e.key,
          last_widget_id: p.lastWidgetId || null,
          mouse_x: p.mouseX, mouse_y: p.mouseY,
        });
        e.stopPropagation(); e.preventDefault();
      }
    });
    overlayCanvas.tabIndex = 0;
    overlayCanvas.style.outline = 'none';
    overlayCanvas.addEventListener('mouseenter', () => overlayCanvas.focus());
  }

  // ── generic redraw ────────────────────────────────────────────────────────
  function _redrawPanel(p) {
    if(!p.state) return;
    if(p.kind==='2d')      draw2d(p);
    else if(p.kind==='3d') draw3d(p);
    else if(p.kind==='bar') drawBar(p);
    else                   draw1d(p);
  }

  function redrawAll() {
    for(const p of panels.values()) _redrawPanel(p);
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
    new ResizeObserver(entries => {
      // React only to width changes to avoid a feedback loop: our own
      // scaleWrap height updates would otherwise re-trigger the observer.
      const cellW = entries[0].contentRect.width;
      if (cellW === _lastCellW) return;
      _lastCellW = cellW;
      requestAnimationFrame(_applyScale);
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

  // ── initial render ────────────────────────────────────────────────────────
  applyLayout();
}

export default { render };







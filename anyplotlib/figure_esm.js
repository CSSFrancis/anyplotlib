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

  // ── outer DOM ────────────────────────────────────────────────────────────
  const outerDiv = document.createElement('div');
  outerDiv.style.cssText = 'position:relative;display:inline-block;user-select:none;';
  el.appendChild(outerDiv);

  const gridDiv = document.createElement('div');
  gridDiv.style.cssText = `display:grid;gap:4px;background:${theme.bg};padding:8px;border-radius:4px;`;
  outerDiv.appendChild(gridDiv);

  // Resize handle (figure-level)
  const resizeHandle = document.createElement('div');
  resizeHandle.style.cssText =
    'position:absolute;bottom:2px;right:2px;width:16px;height:16px;cursor:nwse-resize;' +
    'background:linear-gradient(135deg,transparent 50%,#888 50%);border-radius:0 0 4px 0;z-index:20;';
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
    cell.style.cssText = 'position:relative;overflow:visible;line-height:0;';
    cell.style.gridRow    = `${spec.row_start+1} / ${spec.row_stop+1}`;
    cell.style.gridColumn = `${spec.col_start+1} / ${spec.col_stop+1}`;
    gridDiv.appendChild(cell);

    let plotCanvas, overlayCanvas, markersCanvas, statusBar;
    let xAxisCanvas=null, yAxisCanvas=null, scaleBar=null;
    let _p2d = null;   // extra 2D DOM refs, null for 1D panels

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

      // Histogram canvas: to the right of the image area, same height
      const histCanvas = document.createElement('canvas');
      histCanvas.style.cssText = 'position:absolute;display:none;cursor:ns-resize;';
      const histWidth = 80;

      plotWrap.appendChild(plotCanvas);
      plotWrap.appendChild(overlayCanvas);
      plotWrap.appendChild(markersCanvas);
      plotWrap.appendChild(yAxisCanvas);
      plotWrap.appendChild(xAxisCanvas);
      plotWrap.appendChild(histCanvas);
      plotWrap.appendChild(statusBar);
      cell.appendChild(plotWrap);

      const histCtx = histCanvas.getContext('2d');
      _p2d = { histCanvas, histCtx, histWidth, sbLine, sbLabel, plotWrap };

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

    } else {
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
    }

    const plotCtx    = plotCanvas.getContext('2d');
    const ovCtx      = overlayCanvas.getContext('2d');
    const mkCtx      = markersCanvas.getContext('2d');
    const xCtx       = xAxisCanvas ? xAxisCanvas.getContext('2d') : null;
    const yCtx       = yAxisCanvas ? yAxisCanvas.getContext('2d') : null;

    const blitCache  = { bitmap:null, bytesKey:null, lutKey:null, w:0, h:0 };

    const p = {
      id, kind, cell, pw, ph,
      plotCanvas, overlayCanvas, markersCanvas,
      plotCtx, ovCtx, mkCtx,
      xAxisCanvas, yAxisCanvas, xCtx, yCtx,
      scaleBar, statusBar,
      blitCache,
      ovDrag: null,
      isPanning: false, panStart: {},
      state: null,
      _hoverSi: -1, _hoverI: -1,   // index of hovered marker group / marker (-1 = none)
      // 2D extras (null for 1D panels)
      histCanvas:  _p2d ? _p2d.histCanvas  : null,
      histCtx:     _p2d ? _p2d.histCtx     : null,
      histWidth:   _p2d ? _p2d.histWidth   : 0,
      sbLine:      _p2d ? _p2d.sbLine      : null,
      sbLabel:     _p2d ? _p2d.sbLabel     : null,
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

      // Histogram: right of image area
      if (p.histCanvas && p.histCtx) {
        const hw = p.histWidth || 80;
        const vis = st && st.histogram_visible;
        if (vis) {
          p.histCanvas.style.display = 'block';
          p.histCanvas.style.left = (imgX + imgW) + 'px';
          p.histCanvas.style.top  = imgY + 'px';
          _sz(p.histCanvas, p.histCtx, hw, imgH);
        } else {
          p.histCanvas.style.display = 'none';
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
  function _buildLut32(st) {
    const dMin=st.display_min, dMax=st.display_max;
    const hMin=st.hist_min,    hMax=st.hist_max;
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
    return [st.display_min,st.display_max,st.hist_min,st.hist_max,st.scale_mode,st.colormap_name].join('|');
  }

  function _imgToCanvas2d(ix, iy, st, pw, ph) {
    const zoom=st.zoom, cx=st.center_x, cy=st.center_y;
    const iw=st.image_width, ih=st.image_height;
    if(zoom>=1.0){
      const visW=iw/zoom, visH=ih/zoom;
      const srcX=Math.max(0,Math.min(iw-visW,cx*iw-visW/2));
      const srcY=Math.max(0,Math.min(ih-visH,cy*ih-visH/2));
      return [(ix-srcX)/visW*pw, (iy-srcY)/visH*ph];
    } else {
      const dstW=pw*zoom, dstH=ph*zoom;
      return [(pw-dstW)/2+(ix/iw)*dstW, (ph-dstH)/2+(iy/ih)*dstH];
    }
  }

  function _imgScale2d(st, pw) {
    const zoom=st.zoom, iw=st.image_width;
    return zoom>=1.0 ? pw/(iw/zoom) : pw*zoom/iw;
  }

  function draw2d(p) {
    const st=p.state;
    if(!st) return;
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
    // Axes / scalebar
    _drawAxes2d(p);
    drawScaleBar2d(p);
    drawHistogram2d(p);
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

    // Compute bar width accounting for current zoom
    const zoom=st.zoom||1;
    const iw=st.image_width||imgW;
    const visDataW=(zoom>=1?iw/zoom:iw)*scaleX;
    const targetDataWidth=visDataW*0.2;
    const niceWidth=findNice(targetDataWidth);
    const barPx=Math.round((niceWidth/visDataW)*imgW);
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

  function drawHistogram2d(p) {
    const st=p.state; if(!st||!p.histCanvas||!p.histCtx) return;
    const vis=st.histogram_visible||false;
    p.histCanvas.style.display = vis ? 'block' : 'none';
    if(!vis) return;

    const hw=p.histWidth||80;
    const ph=Math.max(1,p.ph-PAD_T-PAD_B);  // histogram height = image area height
    const hctx=p.histCtx;
    hctx.clearRect(0,0,hw,ph);
    hctx.fillStyle=theme.axisBg; hctx.fillRect(0,0,hw,ph);

    const histData=st.histogram_data||{bins:[],counts:[]};
    const bins=histData.bins||[], counts=histData.counts||[];
    if(!bins.length||!counts.length){return;}

    const hMin=st.hist_min||0, hMax=st.hist_max||1;
    const maxC=Math.max(...counts)||1;

    // Draw histogram bars
    const barAreaX=18, barAreaW=hw-barAreaX-2;
    const dMin=st.display_min, dMax=st.display_max;

    function _dataToY(v){return ph-2-((v-hMin)/(hMax-hMin||1))*(ph-4);}

    // Bars
    hctx.fillStyle=theme.dark?'rgba(150,150,200,0.55)':'rgba(80,80,160,0.55)';
    for(let i=0;i<counts.length;i++){
      const y0=_dataToY(bins[i]);
      const y1=i+1<bins.length?_dataToY(bins[i+1]):_dataToY(hMax);
      const bh=Math.abs(y0-y1)||1;
      const bw=Math.max(1,(counts[i]/maxC)*barAreaW);
      hctx.fillRect(barAreaX, Math.min(y0,y1), bw, bh);
    }

    // display_min / display_max lines
    const yDMax=_dataToY(dMax), yDMin=_dataToY(dMin);
    hctx.save();
    hctx.strokeStyle='#ffffff'; hctx.lineWidth=2; hctx.setLineDash([4,3]);
    hctx.beginPath();hctx.moveTo(barAreaX,yDMax);hctx.lineTo(hw,yDMax);hctx.stroke();
    hctx.strokeStyle='#aaaaff';
    hctx.beginPath();hctx.moveTo(barAreaX,yDMin);hctx.lineTo(hw,yDMin);hctx.stroke();
    hctx.setLineDash([]);hctx.restore();

    // Labels
    hctx.fillStyle=theme.tickText; hctx.font='9px monospace'; hctx.textAlign='right';
    hctx.fillText(fmtVal(hMax),hw-1,12);
    hctx.fillText(fmtVal(hMin),hw-1,ph-3);

    // Scale mode badge
    const mode=st.scale_mode||'linear';
    if(mode!=='linear'){
      hctx.save();hctx.font='bold 9px monospace';hctx.fillStyle='rgba(255,180,0,0.9)';
      hctx.textAlign='right';hctx.fillText(mode.toUpperCase(),hw-1,ph-14);hctx.restore();
    }

    // Colorbar strip on the left
    const cbW=barAreaX-2;
    if(st.colormap_data&&st.colormap_data.length===256){
      for(let py2=2;py2<ph-2;py2++){
        const frac=1-(py2-2)/(ph-4);
        const ci=Math.max(0,Math.min(255,Math.round(frac*255)));
        const [r2,g2,b2]=st.colormap_data[ci];
        hctx.fillStyle=`rgb(${r2},${g2},${b2})`;
        hctx.fillRect(0,py2,cbW,1);
      }
    }

    // Drag for display_min/max
    p.histCanvas._hMin=hMin; p.histCanvas._hMax=hMax;
    p.histCanvas._ph=ph; p.histCanvas._dMin=dMin; p.histCanvas._dMax=dMax;
    p.histCanvas._dataToY=_dataToY;
  }

  function _blit2d(bitmap, st, pw, ph, ctx) {
    const zoom=st.zoom, cx=st.center_x, cy=st.center_y;
    const iw=st.image_width, ih=st.image_height;
    ctx.clearRect(0,0,pw,ph);
    ctx.imageSmoothingEnabled=false;
    if(zoom>=1.0){
      const visW=iw/zoom, visH=ih/zoom;
      const srcX=Math.max(0,Math.min(iw-visW,cx*iw-visW/2));
      const srcY=Math.max(0,Math.min(ih-visH,cy*ih-visH/2));
      ctx.drawImage(bitmap,srcX,srcY,visW,visH,0,0,pw,ph);
    } else {
      const dstW=pw*zoom, dstH=ph*zoom;
      ctx.fillStyle=theme.bgCanvas; ctx.fillRect(0,0,pw,ph);
      ctx.drawImage(bitmap,0,0,iw,ih,(pw-dstW)/2,(ph-dstH)/2,dstW,dstH);
    }
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
      let lastPy=Infinity;
      for(let ti=0;ti<yTicks.length;ti++){
        const v=yTicks[ti];
        const frac=_axisValToFrac(yArr,v);
        const py2=_fracToPx(frac,zoom,cy,imgH);
        if(py2<0||py2>imgH) continue;
        p.yCtx.beginPath(); p.yCtx.moveTo(aw,py2); p.yCtx.lineTo(aw-TICK,py2); p.yCtx.stroke();
        if(lastPy-py2>=minLabelGapY){
          p.yCtx.fillText(fmtVal(v), aw-TICK-2, py2);
          lastPy=py2;
        }
      }
    }
  }

  function drawOverlay2d(p) {
    const st=p.state; if(!st) return;
    const {pw,ph,ovCtx} = p;
    const imgW=Math.max(1,pw-PAD_L-PAD_R), imgH=Math.max(1,ph-PAD_T-PAD_B);
    ovCtx.clearRect(0,0,imgW,imgH);
    const widgets=st.overlay_widgets||[];
    const scale=_imgScale2d(st,imgW);
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
    const scale=_imgScale2d(st,imgW);
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

  // ── event emission helper ───────────────────────────────────────────
  function _emitEvent(panelId, name, widgetId, settled, extraData) {
    const payload = Object.assign(
      { panel_id: panelId, name: name, widget_id: widgetId || null, settled: !!settled },
      extraData || {}
    );
    model.set('event_json', JSON.stringify(payload));
    model.save_changes();
  }

    overlayCanvas.addEventListener('mousedown', (e) => {
      if (e.button !== 0) return;
      dragStart = { mx: e.clientX, my: e.clientY,
                    az: p.state.azimuth, el: p.state.elevation };
      overlayCanvas.style.cursor = 'grabbing';
      e.preventDefault();
    });
    document.addEventListener('mousemove', (e) => {
      if (!dragStart) return;
      const dx = e.clientX - dragStart.mx;
      const dy = e.clientY - dragStart.my;
      p.state.azimuth   = dragStart.az + dx * 0.5;
      p.state.elevation = Math.max(-89, Math.min(89, dragStart.el - dy * 0.5));
      draw3d(p);
      model.set(`panel_${p.id}_json`, JSON.stringify(p.state));
      _emitEvent(p.id, 'rotate_change', null, false,
        { azimuth: p.state.azimuth, elevation: p.state.elevation, zoom: p.state.zoom });
      e.preventDefault();
    });
    document.addEventListener('mouseup', () => {
      if (!dragStart) return;
      dragStart = null;
      overlayCanvas.style.cursor = 'grab';
      model.set(`panel_${p.id}_json`, JSON.stringify(p.state));
      _emitEvent(p.id, 'rotate_change', null, true,
        { azimuth: p.state.azimuth, elevation: p.state.elevation, zoom: p.state.zoom });
      _scheduleCommit();
    });

    overlayCanvas.addEventListener('wheel', (e) => {
      e.preventDefault();
      p.state.zoom = Math.max(0.1, Math.min(10, p.state.zoom * (e.deltaY > 0 ? 0.9 : 1.1)));
      draw3d(p);
      model.set(`panel_${p.id}_json`, JSON.stringify(p.state));
      _emitEvent(p.id, 'zoom_change', null, false,
        { azimuth: p.state.azimuth, elevation: p.state.elevation, zoom: p.state.zoom });
      _scheduleCommit();
    }, { passive: false });

    overlayCanvas.addEventListener('keydown', (e) => {
      if (e.key.toLowerCase() === 'r') {
        p.state.azimuth = -60; p.state.elevation = 30; p.state.zoom = 1;
        draw3d(p);
        model.set(`panel_${p.id}_json`, JSON.stringify(p.state));
        model.save_changes();
        e.preventDefault();
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

    function _drawLine(yData,lineXArr,color,lw){
      if(!yData||!yData.length) return;
      const n=yData.length;
      ctx.beginPath();ctx.strokeStyle=color;ctx.lineWidth=lw;ctx.lineJoin='round';
      let first=true;
      for(let i=0;i<n;i++){
        const xFrac=lineXArr.length>=2?(lineXArr[i]-lineXArr[0])/((lineXArr[lineXArr.length-1]-lineXArr[0])||1):i/((n-1)||1);
        const px=_fracToPx1d(xFrac,x0,x1,r), py=_valToPy1d(yData[i],dMin,dMax,r);
        if(first){ctx.moveTo(px,py);first=false;}else{ctx.lineTo(px,py);}
      }
      ctx.stroke();
    }

    _drawLine(st.data,xArr,st.line_color||'#4fc3f7',st.line_linewidth||1.5);
    for(const ex of (st.extra_lines||[])){
      _drawLine(ex.data||[],ex.x_axis||xArr,ex.color||(theme.dark?'#fff':'#333'),ex.linewidth||1.5);
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
    if(st.line_label) labels.push({color:st.line_color||'#4fc3f7',text:st.line_label});
    for(const ex of (st.extra_lines||[])) if(ex.label) labels.push({color:ex.color||(theme.dark?'#fff':'#333'),text:ex.label});
    if(labels.length){
      ctx.font='10px monospace'; let ly=r.y+6;
      for(const lb of labels){
        ctx.strokeStyle=lb.color;ctx.lineWidth=2;ctx.beginPath();ctx.moveTo(r.x+8,ly+5);ctx.lineTo(r.x+24,ly+5);ctx.stroke();
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

  // ── marker hit-test helpers ────────────────────────────────────────────────
  const MARKER_HIT = 8;

  // Returns {si, i, collectionLabel, markerLabel} or null.
  // si/i identify the set/marker for hover; labels are for tooltips (null if unset).
  function _markerHitTest2d(mx, my, st, pw, ph) {
    const sets = st.markers || [];
    const scale = _imgScale2d(st, pw);
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
    if (p.kind === '2d') _attachEvents2d(p);
    else if (p.kind === '3d') _attachEvents3d(p);
    else                 _attachEvents1d(p);
  }

  function _canvasToImg2d(px,py,st,pw,ph){
    const zoom=st.zoom,cx=st.center_x,cy=st.center_y,iw=st.image_width,ih=st.image_height;
    if(zoom>=1.0){const visW=iw/zoom,visH=ih/zoom;const srcX=Math.max(0,Math.min(iw-visW,cx*iw-visW/2));const srcY=Math.max(0,Math.min(ih-visH,cy*ih-visH/2));return[srcX+(px/pw)*visW,srcY+(py/ph)*visH];}
    const dstW=pw*zoom,dstH=ph*zoom;return[((px-(pw-dstW)/2)/dstW)*iw,((py-(ph-dstH)/2)/dstH)*ih];
  }

  function _attachEvents2d(p) {
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
      const rect=overlayCanvas.getBoundingClientRect();
      const mx=(e.clientX-rect.left)/rect.width, my=(e.clientY-rect.top)/rect.height;
      const curZ=st.zoom, newZ=Math.max(0.75,Math.min(100,curZ*(e.deltaY>0?0.9:1.1)));
      const ratio=curZ/newZ;
      st.zoom=newZ;
      st.center_x=Math.max(0,Math.min(1,st.center_x+(mx-0.5)*(1-ratio)/newZ));
      st.center_y=Math.max(0,Math.min(1,st.center_y+(my-0.5)*(1-ratio)/newZ));
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
      const rect=overlayCanvas.getBoundingClientRect();
      const mx=e.clientX-rect.left, my=e.clientY-rect.top;
      const hit=_ovHitTest2d(mx, my, p);
      if(hit){
        p.ovDrag2d=hit;
        overlayCanvas.style.cursor='move';
        e.preventDefault(); return;
      }
      panStart={mx:e.clientX,my:e.clientY,cx:st.center_x,cy:st.center_y};
      p.isPanning=true; overlayCanvas.style.cursor='grabbing'; e.preventDefault();
    });
    document.addEventListener('mousemove',(e)=>{
      if(p.ovDrag2d){
        _doDrag2d(e,p);
        const _dw=(p.state.overlay_widgets||[]).find(w=>w.id===p.ovDrag2d.id)||{};
        _emitEvent(p.id,(_dw.type||'widget')+'_change',p.ovDrag2d.id,false,_dw);
        return;
      }
      if(!p.isPanning) return;
      const st=p.state; if(!st) return;
      const rect=overlayCanvas.getBoundingClientRect();
      const z=st.zoom;
      localOnly=true;
      st.center_x=Math.max(0,Math.min(1,panStart.cx-(e.clientX-panStart.mx)/rect.width/z));
      st.center_y=Math.max(0,Math.min(1,panStart.cy-(e.clientY-panStart.my)/rect.height/z));
      draw2d(p);
      _propagateZoom2d(p);
      model.set(`panel_${p.id}_json`, JSON.stringify(p.state));
      _scheduleCommit(); e.preventDefault();
    });
    document.addEventListener('mouseup',(e)=>{
      if(p.ovDrag2d){
        const _did=p.ovDrag2d.id;
        const _dw=(p.state.overlay_widgets||[]).find(w=>w.id===_did)||{};
        p.ovDrag2d=null; overlayCanvas.style.cursor='default';
        _emitEvent(p.id,(_dw.type||'widget')+'_change',_did,true,_dw);
        return;
      }
      if(!p.isPanning) return;
      p.isPanning=false; overlayCanvas.style.cursor='default';
      const st=p.state; if(!st) return;
      const rect=overlayCanvas.getBoundingClientRect();
      st.center_x=Math.max(0,Math.min(1,panStart.cx-(e.clientX-panStart.mx)/rect.width/st.zoom));
      st.center_y=Math.max(0,Math.min(1,panStart.cy-(e.clientY-panStart.my)/rect.height/st.zoom));
      model.set(`panel_${p.id}_json`, JSON.stringify(p.state));
      _emitEvent(p.id,'zoom_change',null,true,{center_x:st.center_x,center_y:st.center_y,zoom:st.zoom});
      model.save_changes();
    });

    // Status bar + tooltip + widget hover cursor
    overlayCanvas.addEventListener('mousemove',(e)=>{
      if(p.ovDrag2d) return; // handled by document mousemove
      const st=p.state; if(!st) return;
      const rect=overlayCanvas.getBoundingClientRect();
      const mx=e.clientX-rect.left, my=e.clientY-rect.top;

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

      const imgW=Math.max(1,p.pw-PAD_L-PAD_R), imgH=Math.max(1,p.ph-PAD_T-PAD_B);
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
    overlayCanvas.addEventListener('keydown',(e)=>{
      const st=p.state; if(!st) return;
      const key=e.key.toLowerCase();
      if(key==='r'){
        st.zoom=1; st.center_x=0.5; st.center_y=0.5;
        draw2d(p); model.set(`panel_${p.id}_json`,JSON.stringify(st)); model.save_changes();
        e.preventDefault();
      } else if(key==='h'){
        st.histogram_visible=!st.histogram_visible;
        draw2d(p);
        model.set(`panel_${p.id}_json`,JSON.stringify(st)); model.save_changes();
        e.preventDefault();
      } else if(key==='c'){
        st.show_colorbar=!st.show_colorbar;
        draw2d(p);
        model.set(`panel_${p.id}_json`,JSON.stringify(st)); model.save_changes();
        e.preventDefault();
      } else if(key==='l'){
        st.scale_mode=st.scale_mode==='log'?'linear':'log';
        draw2d(p); model.set(`panel_${p.id}_json`,JSON.stringify(st)); model.save_changes();
        e.preventDefault();
      } else if(key==='s'){
        st.scale_mode=st.scale_mode==='symlog'?'linear':'symlog';
        draw2d(p); model.set(`panel_${p.id}_json`,JSON.stringify(st)); model.save_changes();
        e.preventDefault();
      }
    });
    overlayCanvas.addEventListener('mouseenter',()=>overlayCanvas.focus());

    // Histogram drag (display_min / display_max lines)
    if(p.histCanvas){
      const HTOL=6;
      let histDrag=null;
      p.histCanvas.addEventListener('mousedown',(e)=>{
        const st2=p.state; if(!st2) return;
        const rect=p.histCanvas.getBoundingClientRect();
        const my2=e.clientY-rect.top, ph2=rect.height;
        const yMax=ph2-2-((st2.display_max-st2.hist_min)/((st2.hist_max-st2.hist_min)||1))*(ph2-4);
        const yMin=ph2-2-((st2.display_min-st2.hist_min)/((st2.hist_max-st2.hist_min)||1))*(ph2-4);
        if(Math.abs(my2-yMax)<=HTOL){histDrag='max'; e.preventDefault();}
        else if(Math.abs(my2-yMin)<=HTOL){histDrag='min'; e.preventDefault();}
      });
      document.addEventListener('mousemove',(e)=>{
        if(!histDrag) return;
        const st2=p.state; if(!st2) return;
        const rect=p.histCanvas.getBoundingClientRect();
        const my2=Math.max(0,Math.min(rect.height,e.clientY-rect.top));
        const frac=1-(my2-2)/(rect.height-4);
        let val=st2.hist_min+frac*(st2.hist_max-st2.hist_min);
        val=Math.max(st2.hist_min,Math.min(st2.hist_max,val));
        if(histDrag==='max'&&val>st2.display_min){st2.display_max=val;}
        else if(histDrag==='min'&&val<st2.display_max){st2.display_min=val;}
        draw2d(p);
        model.set(`panel_${p.id}_json`,JSON.stringify(st2));
        _scheduleCommit();
        e.preventDefault();
      });
      document.addEventListener('mouseup',()=>{ histDrag=null; });
    }
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
      const mx=e.clientX-overlayCanvas.getBoundingClientRect().left;
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
      const hit=_ovHitTest1d(e.clientX-overlayCanvas.getBoundingClientRect().left, e.clientY-overlayCanvas.getBoundingClientRect().top, p);
      if(hit){p.ovDrag=hit;overlayCanvas.style.cursor=(hit.mode==='edge0'||hit.mode==='edge1')?'ew-resize':'move';e.preventDefault();return;}
      panStart={mx:e.clientX,x0:st.view_x0,x1:st.view_x1};
      p.isPanning=true;overlayCanvas.style.cursor='grabbing';e.preventDefault();
    });
    document.addEventListener('mousemove',(e)=>{
      if(p.ovDrag){
        _doDrag1d(e,p);
        const _dw=(p.state.overlay_widgets||[]).find(w=>w.id===p.ovDrag.id)||{};
        _emitEvent(p.id,(_dw.type||'widget')+'_change',p.ovDrag.id,false,_dw);
        return;
      }
      if(!p.isPanning) return;
      const st=p.state; if(!st) return;
      const r=_plotRect1d(p.pw,p.ph);
      const dx=(e.clientX-panStart.mx)/(r.w||1);
      const span=panStart.x1-panStart.x0;
      let nx0=panStart.x0-dx*span, nx1=panStart.x1-dx*span;
      if(nx0<0){nx0=0;nx1=span;}if(nx1>1){nx1=1;nx0=1-span;}
      st.view_x0=nx0;st.view_x1=nx1;
      draw1d(p);_propagateView1d(p);
      model.set(`panel_${p.id}_json`,JSON.stringify(st));_scheduleCommit();e.preventDefault();
    });
    document.addEventListener('mouseup',(e)=>{
      if(p.ovDrag){
        const _did=p.ovDrag.id;
        const _dw=(p.state.overlay_widgets||[]).find(w=>w.id===_did)||{};
        p.ovDrag=null; overlayCanvas.style.cursor='crosshair';
        _emitEvent(p.id,(_dw.type||'widget')+'_change',_did,true,_dw);
      }
      if(p.isPanning){
        p.isPanning=false; overlayCanvas.style.cursor='crosshair';
        const st=p.state;
        if(st) _emitEvent(p.id,'view_change',null,true,{view_x0:st.view_x0,view_x1:st.view_x1});
      }
    });

    overlayCanvas.addEventListener('keydown',(e)=>{
      if(e.key.toLowerCase()==='r'){const st=p.state;if(!st)return;st.view_x0=0;st.view_x1=1;draw1d(p);model.set(`panel_${p.id}_json`,JSON.stringify(st));model.save_changes();e.preventDefault();}
    });
    overlayCanvas.tabIndex=0;overlayCanvas.style.outline='none';
    overlayCanvas.addEventListener('mouseenter',()=>overlayCanvas.focus());
    overlayCanvas.addEventListener('mousemove',(e)=>{
      const st=p.state;if(!st)return;
      const rect=overlayCanvas.getBoundingClientRect();
      const mx=e.clientX-rect.left,my=e.clientY-rect.top;
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
    });
    overlayCanvas.addEventListener('mouseleave',()=>{p.statusBar.style.display='none';tooltip.style.display='none';
      if(p._hoverSi!==-1){p._hoverSi=-1;p._hoverI=-1;drawMarkers1d(p,null);}
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
    const scale   = _imgScale2d(st, imgW);
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
    const rect  = p.overlayCanvas.getBoundingClientRect();
    const mx    = e.clientX - rect.left;
    const my    = e.clientY - rect.top;
    const d     = p.ovDrag2d;
    const s     = d.snapW;
    const w     = st.overlay_widgets[d.idx];
    const scale = _imgScale2d(st, imgW);

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
      }
    }
    return null;
  }

  function _doDrag1d(e,p){
    const st=p.state;if(!st)return;
    const r=_plotRect1d(p.pw,p.ph);
    const rect=p.overlayCanvas.getBoundingClientRect();
    const mx=e.clientX-rect.left;
    const xArr=st.x_axis||[],x0=st.view_x0||0,x1=st.view_x1||1;
    const xUnit=xArr.length>=2?_fracToX1d(xArr,_canvasXToFrac1d(mx,x0,x1,r)):_canvasXToFrac1d(mx,x0,x1,r);
    const widgets=st.overlay_widgets;
    const d=p.ovDrag, s=d.snapW, w=widgets[d.idx];
    if(w.type==='vline'){w.x=xUnit;}
    else if(w.type==='hline'){const py=e.clientY-rect.top;w.y=st.data_max-((py-r.y)/(r.h||1))*(st.data_max-st.data_min);}
    else if(w.type==='range'){
      if(d.mode==='edge0') w.x0=xUnit;
      else if(d.mode==='edge1') w.x1=xUnit;
      else {
        const snapPx=_fracToPx1d(xArr.length>=2?_xToFrac1d(xArr,s.x0):0,x0,x1,r);
        const dxUnit=xArr.length>=2?_fracToX1d(xArr,_canvasXToFrac1d(snapPx+(mx-d.startMX),x0,x1,r))-s.x0:(mx-d.startMX)/(r.w||1);
        w.x0=s.x0+dxUnit;w.x1=s.x1+dxUnit;
      }
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
    resizeStart = { mx: e.clientX, my: e.clientY, fw, fh };
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

    // Aspect-lock 2D panels
    for (let pass = 0; pass < 4; pass++) {
      for (const spec of panel_specs) {
        const p = panels.get(spec.id);
        if (!p || p.kind !== '2d' || !p.state) continue;
        const iw = p.state.image_width||1, ih = p.state.image_height||1;
        if (iw<=0||ih<=0) continue;
        const ar = iw/ih;
        let cw=0, ch=0;
        for(let c=spec.col_start;c<spec.col_stop;c++) cw+=col_px[c];
        for(let r=spec.row_start;r<spec.row_stop;r++) ch+=row_px[r];
        if (ch===0) continue;
        if (cw/ch > ar) {
          const new_cw=ch*ar, span=Math.max(1,spec.col_stop-spec.col_start);
          for(let c=spec.col_start;c<spec.col_stop;c++) col_px[c]=new_cw/span;
        } else {
          const new_ch=cw/ar, span=Math.max(1,spec.row_stop-spec.row_start);
          for(let r=spec.row_start;r<spec.row_stop;r++) row_px[r]=new_ch/span;
        }
      }
    }

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
      if (p.histCanvas && p.histCanvas.style.display !== 'none') {
        p.histCanvas.style.left = (imgX+imgW)+'px'; p.histCanvas.style.top = imgY+'px';
        _szCSS(p.histCanvas, p.histWidth||80, imgH);
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
    _pendingNfw = Math.max(200, resizeStart.fw + (e.clientX - resizeStart.mx));
    _pendingNfh = Math.max(100, resizeStart.fh + (e.clientY - resizeStart.my));
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
    const nfw = Math.max(200, resizeStart.fw + (e.clientX - resizeStart.mx));
    const nfh = Math.max(100, resizeStart.fh + (e.clientY - resizeStart.my));

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


  // ── generic redraw ────────────────────────────────────────────────────────
  function _redrawPanel(p) {
    if(!p.state) return;
    if(p.kind==='2d')      draw2d(p);
    else if(p.kind==='3d') draw3d(p);
    else                   draw1d(p);
  }

  function redrawAll() {
    for(const p of panels.values()) _redrawPanel(p);
  }

  // ── cell-aware layout: redraw when the notebook cell changes size ─────────
  // We observe `el` (the anywidget mount point) directly. The notebook sets
  // its width; we never write to it, so there is no feedback loop.
  // Only triggers when the cell is narrower than the current widget — we
  // never upscale beyond the stored fig_width / fig_height.
  if (typeof ResizeObserver !== 'undefined') {
    let _roTimer = null;
    let _roActive = false;            // prevent re-entry
    let _lastCellW = 0;

    const _ro = new ResizeObserver(entries => {
      if (_roActive || isResizing || _suppressLayoutUpdate) return;
      const cellW = entries[0].contentRect.width;
      if (!cellW || cellW === _lastCellW) return;
      _lastCellW = cellW;

      // Measure the widget's natural width (what it would like to be)
      const gridW = gridDiv.scrollWidth || gridDiv.getBoundingClientRect().width;
      if (!gridW || cellW >= gridW - 2) return;  // fits — nothing to do

      clearTimeout(_roTimer);
      _roTimer = setTimeout(() => {
        if (_roActive || isResizing || _suppressLayoutUpdate) return;

        // Re-read the cell width inside the timeout (may have changed)
        const availW = el.getBoundingClientRect().width;
        if (!availW) return;

        let layout;
        try { layout = JSON.parse(model.get('layout_json')); } catch(_) { return; }

        const curW = layout.fig_width || model.get('fig_width');
        const curH = layout.fig_height || model.get('fig_height');
        if (!curW || availW >= curW) return;   // already fits

        const scale = availW / curW;
        const nfw = Math.max(200, Math.round(curW * scale));
        const nfh = Math.max(100, Math.round(curH * scale));

        _roActive = true;
        _suppressLayoutUpdate = true;
        _cachedLayout = layout;        // reuse cached layout for the resize
        _applyFigResize(nfw, nfh);

        // Persist the new size into the model so it survives kernel restarts
        try {
          layout.fig_width  = nfw;
          layout.fig_height = nfh;
          for (const spec of layout.panel_specs) {
            const p = panels.get(spec.id);
            if (p) { spec.panel_width = p.pw; spec.panel_height = p.ph; }
          }
          model.set('layout_json', JSON.stringify(layout));
        } catch(_) {}
        _suppressLayoutUpdate = false;
        model.set('fig_width',  nfw);
        model.set('fig_height', nfh);
        model.save_changes();

        _roActive = false;
      }, 150);
    });

    _ro.observe(el);
  }

  // ── model listeners ───────────────────────────────────────────────────────
  model.on('change:layout_json', () => { applyLayout(); redrawAll(); });
  model.on('change:fig_width change:fig_height', () => { applyLayout(); redrawAll(); });

  // ── initial render ────────────────────────────────────────────────────────
  applyLayout();
}

export default { render };







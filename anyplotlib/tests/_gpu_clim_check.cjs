/**
 * _gpu_clim_check.cjs — verify the GPU shader honors a NARROWED clim correctly
 * (regression guard for the "clim applied twice" critical bug). Runs in real
 * Electron (WebGPU on the GPU). Loads a standalone anyplotlib page with a known
 * ramp image + a narrow vmin/vmax, reads back the GPU output via
 * __apl_gpuReadback, and compares to the expected windowed-colormap values passed
 * in as argv[3] (a JSON grid computed in numpy with the SAME clim).
 *
 * Prints  CLIM_RESULT {meanDiff, maxDiff, gpuActive}  and exits 0 iff GPU matches.
 */
const { app, BrowserWindow } = require('electron')
app.commandLine.appendSwitch('enable-unsafe-webgpu')

const htmlPath = process.argv[2]
const expected = JSON.parse(process.argv[3])   // [[r,g,b], ...] length N*N, row-major
const panelId = process.argv[4]
const N = Math.round(Math.sqrt(expected.length))

app.whenReady().then(async () => {
  const win = new BrowserWindow({ width: 900, height: 900, show: false,
    webPreferences: { offscreen: false, webSecurity: false } })
  try {
    await win.loadFile(htmlPath)
    // Wait for mount + async GPU device + activation + a paint.
    await new Promise(r => setTimeout(r, 3500))
    const res = await win.webContents.executeJavaScript(`(async () => {
      const g = globalThis.__apl_gpu2d || {};
      const pid = ${JSON.stringify(panelId)} || Object.keys(g)[0];
      const active = !!(g[pid] && g[pid].active);
      let px = null;
      if (typeof globalThis.__apl_gpuReadback === 'function' && pid)
        px = await globalThis.__apl_gpuReadback(pid, ${N});
      return { active, px: px && px.px };
    })()`, true)
    if (!res.px) { console.log('CLIM_RESULT', JSON.stringify({ err: 'no readback', ...res })); app.exit(1); return }
    let sum = 0, maxd = 0, n = Math.min(res.px.length, expected.length)
    for (let i = 0; i < n; i++)
      for (let c = 0; c < 3; c++) {
        const d = Math.abs(res.px[i][c] - expected[i][c]); sum += d
        if (d > maxd) maxd = d
      }
    const meanDiff = sum / (n * 3)
    console.log('CLIM_RESULT', JSON.stringify({
      gpuActive: res.active, meanDiff: +meanDiff.toFixed(2), maxDiff: maxd, n }))
    // Small tolerance for the NxN downscale sampling + nearest-rounding.
    app.exit(res.active && meanDiff < 8 ? 0 : 2)
  } catch (e) {
    console.log('CLIM_RESULT', JSON.stringify({ err: String(e).slice(0, 80) }))
    app.exit(1)
  } finally { try { win.destroy() } catch (_) {} }
})

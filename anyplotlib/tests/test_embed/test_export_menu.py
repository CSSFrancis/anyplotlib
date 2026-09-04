"""Right-click menu, Ctrl+C and the export-action registry.

The menu binds on ``outerDiv`` rather than per ``overlayCanvas``, which covers
only the image area — the axis gutters, colorbar and title strip are not under
it.  The regression that matters for Ctrl+C is that the 2-D panel's bare-``c``
colorbar shortcut used to fire on it too.

The clipboard and the download anchor are stubbed via ``add_init_script`` so the
assertions need no browser permissions and no download directory.
"""
from __future__ import annotations

import numpy as np

import anyplotlib as apl

IMG = 32
FIGW, FIGH = 360, 300

# Records clipboard writes and download-anchor clicks instead of performing
# them, and guarantees ClipboardItem exists so the feature detection passes.
_STUB = """
window.__aplCopies = [];
window.__aplDownloads = [];
// Always override: Chromium ships a real ClipboardItem whose payload is not
// readable synchronously, so the stub has to own the constructor to record it.
window.ClipboardItem = function (items) { this.items = items; };
Object.defineProperty(navigator, 'clipboard', {
  configurable: true,
  value: {
    write: (items) => {
      const it = items && items[0];
      const blob = it && (it.items ? it.items['image/png'] : null);
      window.__aplCopies.push({
        type: blob ? blob.type : null,
        size: blob ? blob.size : 0,
      });
      return Promise.resolve();
    },
  },
});
const _click = HTMLAnchorElement.prototype.click;
HTMLAnchorElement.prototype.click = function () {
  if (this.download) {
    window.__aplDownloads.push({download: this.download, href: this.href});
    return;
  }
  return _click.apply(this, arguments);
};
"""


def _fig(tile=False, n=IMG):
    fig, ax = apl.subplots(1, 1, figsize=(FIGW, FIGH))
    data = np.tile(np.arange(256, dtype=np.uint8)[:n], (n, 1))
    plot = ax.imshow(data, cmap="viridis", vmin=0, vmax=255, tile=tile)
    return fig, plot


def _panel_center(page, plot_id):
    return page.evaluate(
        """(pid) => {
             const p = window._handle.api.panels.get(pid);
             const el = p.plotWrap || p.plotCanvas.parentElement;
             const r = el.getBoundingClientRect();
             return {x: r.left + r.width / 2, y: r.top + r.height / 2};
           }""", plot_id)


def _open_menu(page, plot_id):
    c = _panel_center(page, plot_id)
    page.mouse.click(c["x"], c["y"], button="right")
    page.wait_for_function("() => globalThis.__apl_menuItems() !== null", timeout=5000)
    return page.evaluate("() => globalThis.__apl_menuItems()")


def _labels(items):
    return [i["text"] for i in items]


# ══════════════════════════════════════════════════════════════════════════════
# Context menu structure and dismissal
# ══════════════════════════════════════════════════════════════════════════════

class TestContextMenu:
    def test_right_click_opens_panel_then_figure_entries(self, mount_page):
        fig, plot = _fig()
        page = mount_page(fig)
        items = _open_menu(page, plot._id)
        text = "\n".join(_labels(items))

        assert "This panel" in text, text
        assert "Whole figure" in text, text
        assert "Copy image" in text and "Save PNG…" in text, text
        assert "Save at native resolution…" in text, text
        assert text.index("This panel") < text.index("Whole figure"), (
            "figure entries must come after the clicked panel's")

    def test_export_badge_opens_the_menu_without_a_right_click(self, mount_page):
        """Hosts (JupyterLab, PyCharm, VS Code) swallow `contextmenu` before the
        page sees it, so the menu must also open from an ordinary left click."""
        fig, plot = _fig()
        page = mount_page(fig)

        badge = page.locator("div[title='Copy or save this figure']")
        c = _panel_center(page, plot._id)
        page.mouse.move(c["x"], c["y"])
        assert badge.evaluate("e => getComputedStyle(e).display") != "none", \
            "badge should appear on hover"

        badge.click()
        page.wait_for_function("() => globalThis.__apl_menuItems() !== null",
                               timeout=5000)
        text = "\n".join(_labels(page.evaluate("() => globalThis.__apl_menuItems()")))
        # Hovering the panel focuses its overlay, so the menu is panel-scoped.
        assert "This panel" in text and "Whole figure" in text, text

    def test_badge_never_appears_in_a_screenshot(self, take_screenshot):
        """Hover chrome must stay out of rendered images: the same screenshot
        path feeds the visual baselines and the docs gallery thumbnails.  The
        badge is revealed by real pointer movement, not by ``mouseenter``, which
        a browser may synthesise for a stationary cursor when the layout shifts
        under it."""
        fig, ax = apl.subplots(1, 1, figsize=(320, 260))
        ax.imshow(np.zeros((32, 32), dtype=np.float32), cmap="gray", tile=False)
        arr = take_screenshot(fig)

        # Badge fill is rgba(100,100,120,0.72); it sits in the top-right corner.
        corner = arr[0:40, -60:, :3].astype(int)
        d = np.abs(corner - np.array([100, 100, 120])).max(axis=-1)
        hits = int((d <= 30).sum())
        assert hits == 0, (
            f"{hits} badge-coloured pixels in the top-right corner — hover "
            "chrome leaked into the screenshot")

    def test_export_badge_works_when_contextmenu_is_swallowed(self, mount_page):
        """Simulate a host that eats contextmenu in the capture phase."""
        fig, plot = _fig()
        page = mount_page(fig)
        page.evaluate(
            """() => document.addEventListener('contextmenu', (e) => {
                 e.preventDefault(); e.stopImmediatePropagation();
               }, true)""")

        c = _panel_center(page, plot._id)
        page.mouse.click(c["x"], c["y"], button="right")
        assert page.evaluate("() => globalThis.__apl_menuItems()") is None, \
            "test premise broken: the stub did not swallow the event"

        page.mouse.move(c["x"], c["y"])
        page.locator("div[title='Copy or save this figure']").click()
        page.wait_for_function("() => globalThis.__apl_menuItems() !== null",
                               timeout=5000)

    def test_right_click_on_the_axis_gutter_still_finds_the_panel(self, mount_page):
        """The overlay canvas covers only the image area — a gutter click has to
        resolve to the panel too, which is why the listener is on outerDiv."""
        fig, ax = apl.subplots(1, 1, figsize=(FIGW, FIGH))
        n = IMG
        plot = ax.imshow(np.tile(np.arange(256, dtype=np.uint8)[:n], (n, 1)),
                         cmap="viridis", axes=[np.arange(n) * 2.0,
                                               np.arange(n) * 2.0],
                         units="nm", tile=False)
        page = mount_page(fig)
        # A few px inside the panel's left edge = the y-axis gutter.
        spot = page.evaluate(
            """(pid) => {
                 const p = window._handle.api.panels.get(pid);
                 const el = p.plotWrap || p.plotCanvas.parentElement;
                 const r = el.getBoundingClientRect();
                 return {x: r.left + 4, y: r.top + r.height / 2};
               }""", plot._id)
        page.mouse.click(spot["x"], spot["y"], button="right")
        page.wait_for_function("() => globalThis.__apl_menuItems() !== null",
                               timeout=5000)
        text = "\n".join(_labels(page.evaluate("() => globalThis.__apl_menuItems()")))
        assert "This panel" in text, (
            "a right-click on the axis gutter did not resolve to the panel")

    def test_menu_appears_at_the_click_point(self, mount_page):
        """The menu is absolutely positioned inside outerDiv, which only gets
        ``position: relative`` from Figure._css — a stylesheet a bare mount()
        page does not have.  Without an inline fallback it would anchor to some
        other ancestor and land nowhere near the cursor."""
        fig, plot = _fig()
        page = mount_page(fig)
        # Push the figure away from the page origin: with outerDiv left static
        # the menu's containing block is the viewport rather than the figure, so
        # it lands offset by exactly this much. At (0, 0) both cases coincide
        # and the test would pass either way.
        page.evaluate(
            "() => { const o = document.getElementById('outer');"
            " o.style.marginLeft = '140px'; o.style.marginTop = '120px'; }")
        page.evaluate("() => new Promise(r => requestAnimationFrame(r))")

        c = _panel_center(page, plot._id)
        page.mouse.click(c["x"], c["y"], button="right")
        page.wait_for_function("() => globalThis.__apl_menuItems() !== null",
                               timeout=5000)

        box = page.evaluate(
            """() => {
                 const m = document.querySelector('[data-apl-menu]');
                 const r = m.getBoundingClientRect();
                 return {left: r.left, top: r.top};
               }""")
        assert abs(box["left"] - c["x"]) < 40, (
            f"menu left {box['left']:.0f} is far from the click x {c['x']:.0f}")
        assert abs(box["top"] - c["y"]) < 40, (
            f"menu top {box['top']:.0f} is far from the click y {c['y']:.0f}")

    def test_escape_and_outside_click_dismiss(self, mount_page):
        fig, plot = _fig()
        page = mount_page(fig)

        _open_menu(page, plot._id)
        page.keyboard.press("Escape")
        assert page.evaluate("() => globalThis.__apl_menuItems()") is None, \
            "Escape did not close the menu"

        _open_menu(page, plot._id)
        page.mouse.click(3, 3)
        assert page.evaluate("() => globalThis.__apl_menuItems()") is None, \
            "an outside click did not close the menu"

    def test_native_entry_disabled_on_a_tiled_panel(self, mount_page):
        fig, plot = _fig(tile=True, n=1200)
        page = mount_page(fig)
        items = _open_menu(page, plot._id)
        native = [i for i in items if "native resolution" in i["text"]]
        assert native, _labels(items)
        assert native[0]["disabled"], (
            "native export must be disabled for a tiled panel — the browser "
            "only holds an overview")

    def test_native_entry_enabled_on_a_small_panel(self, mount_page):
        fig, plot = _fig(tile=False)
        page = mount_page(fig)
        items = _open_menu(page, plot._id)
        native = [i for i in items if "native resolution" in i["text"]]
        assert native and not native[0]["disabled"], _labels(items)

    def test_theme_choice_is_sticky(self, mount_page):
        fig, plot = _fig()
        page = mount_page(fig)
        _open_menu(page, plot._id)
        assert page.evaluate("() => globalThis.__apl_menuTheme()") == "current"

        page.evaluate(
            """() => [...document.querySelectorAll('[data-apl-theme-opt]')]
                     .find(e => e.getAttribute('data-apl-theme-opt') === 'dark')
                     .click()""")
        assert page.evaluate("() => globalThis.__apl_menuTheme()") == "dark"

        page.keyboard.press("Escape")
        _open_menu(page, plot._id)
        assert page.evaluate("() => globalThis.__apl_menuTheme()") == "dark", \
            "the theme choice must persist across menu openings"


# ══════════════════════════════════════════════════════════════════════════════
# Clipboard + download
# ══════════════════════════════════════════════════════════════════════════════

class TestCopyAndDownload:
    def test_ctrl_c_copies_and_does_not_toggle_the_colorbar(self, mount_page):
        """Regression: the 2-D keydown handler matched ``key === 'c'`` with no
        modifier guard, so Ctrl+C toggled the colorbar instead of copying."""
        fig, plot = _fig()
        page = mount_page(fig)
        page.add_init_script(_STUB)
        page.reload()
        page.wait_for_function("() => window._aplReady === true", timeout=15_000)

        c = _panel_center(page, plot._id)
        page.mouse.move(c["x"], c["y"])            # mouseenter focuses the overlay
        before = page.evaluate(
            "(pid) => JSON.parse(globalThis.__apl_viewStateJson(pid)).show_colorbar",
            plot._id)

        page.keyboard.press("Control+c")
        page.wait_for_function("() => window.__aplCopies.length > 0", timeout=5000)

        after = page.evaluate(
            "(pid) => JSON.parse(globalThis.__apl_viewStateJson(pid)).show_colorbar",
            plot._id)
        assert after == before, (
            "Ctrl+C toggled the colorbar — the modifier guard is missing")
        copy = page.evaluate("() => window.__aplCopies[0]")
        assert copy["type"] == "image/png" and copy["size"] > 0, copy
        assert "copied to clipboard" in page.evaluate(
            "() => globalThis.__apl_toastText().text")

    def test_bare_c_still_toggles_the_colorbar(self, mount_page):
        fig, plot = _fig()
        page = mount_page(fig)
        c = _panel_center(page, plot._id)
        page.mouse.move(c["x"], c["y"])
        before = page.evaluate(
            "(pid) => JSON.parse(globalThis.__apl_viewStateJson(pid)).show_colorbar",
            plot._id)
        page.keyboard.press("c")
        after = page.evaluate(
            "(pid) => JSON.parse(globalThis.__apl_viewStateJson(pid)).show_colorbar",
            plot._id)
        assert after != before, "bare 'c' no longer toggles the colorbar"

    def _save_via_menu(self, page, plot, label="Save PNG…"):
        _open_menu(page, plot._id)
        page.evaluate(
            """(lbl) => [...document.querySelectorAll('div')]
                        .find(e => e.textContent === lbl).click()""", label)

    def test_save_uses_the_system_dialog_when_one_is_available(self, mount_page):
        """A real Save dialog beats dropping the file in ~/Downloads, so
        showSaveFilePicker is tried first where the browser offers it."""
        fig, plot = _fig()
        page = mount_page(fig)
        page.add_init_script(_STUB + """
          window.__aplPicked = null;
          window.showSaveFilePicker = async (opts) => {
            window.__aplPicked = opts;
            return {
              name: opts.suggestedName,
              createWritable: async () => ({
                write: async (b) => { window.__aplWrote = b.size; },
                close: async () => {},
              }),
            };
          };
        """)
        page.reload()
        page.wait_for_function("() => window._aplReady === true", timeout=15_000)

        self._save_via_menu(page, plot, "Save as… (choose folder)")
        page.wait_for_function("() => window.__aplPicked !== null", timeout=5000)

        opts = page.evaluate("() => window.__aplPicked")
        assert opts["suggestedName"].endswith(".png"), opts
        assert opts["types"][0]["accept"]["image/png"] == [".png"], opts
        assert page.evaluate("() => window.__aplWrote") > 0, "nothing was written"
        assert page.evaluate("() => window.__aplDownloads.length") == 0, (
            "fell back to a download even though the picker succeeded")

    def test_a_cancelled_dialog_does_not_also_download(self, mount_page):
        """AbortError after a human-scale delay means the user closed the
        dialog — saving anyway would be the opposite of what they asked."""
        fig, plot = _fig()
        page = mount_page(fig)
        page.add_init_script(_STUB + """
          window.showSaveFilePicker = async () => {
            await new Promise(r => setTimeout(r, 600));   // > PICKER_MIN_MS
            const e = new Error('cancelled'); e.name = 'AbortError'; throw e;
          };
        """)
        page.reload()
        page.wait_for_function("() => window._aplReady === true", timeout=15_000)

        self._save_via_menu(page, plot, "Save as… (choose folder)")
        page.wait_for_timeout(1200)
        assert page.evaluate("() => window.__aplDownloads.length") == 0, (
            "a cancelled Save dialog still wrote a file")

    def test_a_dialog_that_never_opened_falls_through_to_a_download(self, mount_page):
        """Headless browsers and some embedded webviews reject with AbortError
        without ever showing a dialog — indistinguishable by name, so the
        near-instant rejection is what separates them."""
        fig, plot = _fig()
        page = mount_page(fig)
        page.add_init_script(_STUB + """
          window.showSaveFilePicker = async () => {
            const e = new Error('no dialog'); e.name = 'AbortError'; throw e;
          };
        """)
        page.reload()
        page.wait_for_function("() => window._aplReady === true", timeout=15_000)

        self._save_via_menu(page, plot, "Save as… (choose folder)")
        page.wait_for_function("() => window.__aplDownloads.length > 0", timeout=5000)
        assert page.evaluate("() => window.__aplDownloads[0].download").endswith(".png")

    def test_plain_save_never_opens_the_system_dialog(self, mount_page):
        """`showSaveFilePicker` hands the page a persistent writable handle, so
        Chrome prompts for permission to edit files.  That is too much for a
        plain "save this image" — only the explicit "Save as…" pays it."""
        fig, plot = _fig()
        page = mount_page(fig)
        page.add_init_script(_STUB + """
          window.__aplPicked = null;
          window.showSaveFilePicker = async (o) => {
            window.__aplPicked = o;
            throw Object.assign(new Error('x'), {name: 'AbortError'});
          };
        """)
        page.reload()
        page.wait_for_function("() => window._aplReady === true", timeout=15_000)

        self._save_via_menu(page, plot)                      # plain "Save PNG…"
        page.wait_for_function("() => window.__aplDownloads.length > 0", timeout=5000)
        assert page.evaluate("() => window.__aplPicked") is None, (
            "plain Save opened the system dialog and triggered a permission prompt")

    def test_save_entry_downloads_a_png(self, mount_page):
        fig, plot = _fig()
        page = mount_page(fig)
        page.add_init_script(_STUB)
        page.reload()
        page.wait_for_function("() => window._aplReady === true", timeout=15_000)

        _open_menu(page, plot._id)
        page.evaluate(
            """() => [...document.querySelectorAll('div')]
                     .find(e => e.textContent === 'Save PNG…').click()""")
        page.wait_for_function("() => window.__aplDownloads.length > 0", timeout=5000)
        dl = page.evaluate("() => window.__aplDownloads[0]")
        assert dl["download"].endswith(".png"), dl
        assert dl["href"].startswith("blob:"), dl
        assert page.evaluate("() => globalThis.__apl_previewOpen()") is False, (
            "a top-level page should download, not fall back to the preview")


# ══════════════════════════════════════════════════════════════════════════════
# Downstream extensibility
# ══════════════════════════════════════════════════════════════════════════════

class TestRegistry:
    def test_registered_action_appears_and_receives_ctx(self, mount_page):
        fig, plot = _fig()
        page = mount_page(fig)
        page.evaluate(
            """() => {
                 window.__ctx = null;
                 window._handle.registerExportAction({
                   id: 'save-tiff', label: 'Save as TIFF…', group: 'Host',
                   scope: 'panel',
                   handler: (ctx) => {
                     const r = ctx.exportCanvas({source: 'view'});
                     window.__ctx = {
                       panelId: ctx.panelId, kind: ctx.kind,
                       themeName: ctx.themeName, hasState: !!ctx.state,
                       hasModel: !!ctx.model, dark: !!(ctx.theme || {}).dark,
                       figW: ctx.figure.width,
                       canvasW: r.width, canvasH: r.height,
                     };
                     ctx.toast('tiff done');
                   },
                 });
               }""")
        items = _open_menu(page, plot._id)
        assert any("Save as TIFF…" in i["text"] for i in items), _labels(items)

        page.evaluate(
            """() => document.querySelector('[data-apl-action="save-tiff"]').click()""")
        ctx = page.evaluate("() => window.__ctx")
        assert ctx is not None, "the registered handler never ran"
        assert ctx["panelId"] == plot._id
        assert ctx["kind"] == "2d"
        assert ctx["themeName"] == "current"
        assert ctx["hasState"] and ctx["hasModel"]
        assert ctx["figW"] == FIGW
        assert ctx["canvasW"] > 0 and ctx["canvasH"] > 0
        assert page.evaluate("() => globalThis.__apl_toastText().text") == "tiff done"

    def test_figure_scoped_action_is_hidden_on_a_panel_menu(self, mount_page):
        fig, plot = _fig()
        page = mount_page(fig)
        page.evaluate(
            """() => window._handle.registerExportAction({
                 id: 'fig-only', label: 'Figure only…', scope: 'figure',
                 handler: () => {},
               })""")
        items = _open_menu(page, plot._id)
        assert not any("Figure only…" in i["text"] for i in items), _labels(items)

    def test_unregister_removes_the_entry(self, mount_page):
        fig, plot = _fig()
        page = mount_page(fig)
        page.evaluate(
            """() => window._handle.registerExportAction({
                 id: 'tmp', label: 'Temp…', handler: () => {},
               })""")
        assert any("Temp…" in i["text"] for i in _open_menu(page, plot._id))
        page.keyboard.press("Escape")
        page.evaluate("() => window._handle.unregisterExportAction('tmp')")
        assert not any("Temp…" in i["text"] for i in _open_menu(page, plot._id))

    def test_bad_registration_raises(self, mount_page):
        fig, _plot = _fig()
        page = mount_page(fig)
        err = page.evaluate(
            """() => { try { window._handle.registerExportAction({id: 'x'});
                             return null; }
                       catch (e) { return String(e.message || e); } }""")
        assert err and "handler" in err, err

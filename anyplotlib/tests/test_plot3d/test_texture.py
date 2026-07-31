"""
tests/test_plot3d/test_texture.py
=================================

Image textures on 3-D surfaces (``Plot3D.set_texture``) — see
``Examples/PlotTypes/plot_3d_texture.py``.

Covers:
  * the encode path (array / PNG bytes / JPEG bytes / file path → data URL)
  * default parametric UVs and explicit ``uv=``
  * validation (non-surface geometry, wrong UV length, bad image bytes)
  * ``set_data`` regenerating auto UVs and rejecting stale explicit ones
  * the texture riding the geometry channel, not the light view trait
  * Playwright: the texture actually paints, and neighbouring triangles do
    not leave a mesh of background-coloured seams between them
"""
from __future__ import annotations

import base64
import json
import pathlib
import tempfile

import numpy as np
import pytest

import anyplotlib as apl
from anyplotlib._utils import _encode_png
from anyplotlib.embed import esm_path, figure_state
from anyplotlib.tests._png_utils import decode_png


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sphere(ndec=25, nra=49):
    """A closed unit sphere: columns run 0→2π, rows +90°→−90°."""
    ra = np.linspace(0, 2 * np.pi, nra)
    dec = np.linspace(np.pi / 2, -np.pi / 2, ndec)
    RA, DEC = np.meshgrid(ra, dec)
    return (np.cos(DEC) * np.cos(RA), np.cos(DEC) * np.sin(RA), np.sin(DEC))


def _surface(ndec=25, nra=49, **kwargs):
    X, Y, Z = _sphere(ndec, nra)
    fig, ax = apl.subplots(1, 1, figsize=(320, 320))
    return ax.plot_surface(X, Y, Z, bounds=((-1, 1),) * 3, **kwargs)


def _checker(h=64, w=128):
    img = np.zeros((h, w, 3), np.uint8)
    yy, xx = np.mgrid[0:h, 0:w]
    img[((yy // 8) + (xx // 8)) % 2 == 0] = [220, 40, 40]
    img[((yy // 8) + (xx // 8)) % 2 == 1] = [40, 60, 220]
    return img


def _uv(plot) -> np.ndarray:
    return np.frombuffer(
        base64.b64decode(plot._state["texture_uv_b64"]), "<f4").reshape(-1, 2)


# ---------------------------------------------------------------------------
# Encoding the image
# ---------------------------------------------------------------------------

class TestImageInput:
    def test_uint8_array_becomes_a_png_data_url(self):
        s = _surface()
        s.set_texture(_checker())
        assert s._state["texture_url"].startswith("data:image/png;base64,")

    def test_float_array_is_scaled_from_0_1(self):
        s = _surface()
        s.set_texture(np.ones((8, 16, 3), np.float64))
        blob = base64.b64decode(s._state["texture_url"].split(",", 1)[1])
        assert (decode_png(blob)[..., :3] == 255).all()

    def test_rgba_array_keeps_its_alpha(self):
        rgba = np.zeros((8, 16, 4), np.uint8)
        rgba[..., 3] = 128
        s = _surface()
        s.set_texture(rgba)
        blob = base64.b64decode(s._state["texture_url"].split(",", 1)[1])
        assert (decode_png(blob)[..., 3] == 128).all()

    def test_png_bytes_pass_through_unencoded(self):
        png = _encode_png(np.zeros((8, 16, 4), np.uint8))
        s = _surface()
        s.set_texture(png)
        url = s._state["texture_url"]
        assert url == "data:image/png;base64," + base64.b64encode(png).decode()

    def test_jpeg_bytes_keep_their_mime_type(self):
        # Only the magic bytes are inspected — no decode happens in Python.
        s = _surface()
        s.set_texture(b"\xff\xd8\xff\xe0" + b"\x00" * 32)
        assert s._state["texture_url"].startswith("data:image/jpeg;base64,")

    def test_file_path_is_read_and_sniffed(self, tmp_path):
        p = tmp_path / "tex.png"
        p.write_bytes(_encode_png(np.zeros((4, 4, 4), np.uint8)))
        s = _surface()
        s.set_texture(p)
        assert s._state["texture_url"].startswith("data:image/png;base64,")

    def test_existing_data_url_passes_through(self):
        s = _surface()
        s.set_texture("data:image/png;base64,AAAA")
        assert s._state["texture_url"] == "data:image/png;base64,AAAA"

    def test_unrecognised_bytes_raise(self):
        s = _surface()
        with pytest.raises(ValueError, match="PNG/JPEG"):
            s.set_texture(b"not an image at all")

    def test_missing_file_raises(self, tmp_path):
        s = _surface()
        with pytest.raises(FileNotFoundError):
            s.set_texture(tmp_path / "nope.png")


# ---------------------------------------------------------------------------
# Texture coordinates
# ---------------------------------------------------------------------------

class TestUV:
    def test_default_uv_is_the_parametric_grid(self):
        s = _surface(ndec=5, nra=9)
        s.set_texture(_checker())
        uv = _uv(s)
        assert uv.shape == (45, 2)
        # u sweeps 0→1 across each row of columns, v steps 0→1 down the rows
        assert uv[:9, 0] == pytest.approx(np.linspace(0, 1, 9), abs=1e-6)
        assert uv[:9, 1] == pytest.approx(np.zeros(9), abs=1e-6)
        assert uv[-9:, 1] == pytest.approx(np.ones(9), abs=1e-6)

    def test_flip_v_mirrors_the_row_mapping(self):
        s = _surface(ndec=5, nra=9)
        s.set_texture(_checker(), flip_v=True)
        uv = _uv(s)
        assert uv[:9, 1] == pytest.approx(np.ones(9), abs=1e-6)
        assert uv[-9:, 1] == pytest.approx(np.zeros(9), abs=1e-6)

    def test_explicit_uv_pair_in_grid_shape(self):
        s = _surface(ndec=5, nra=9)
        U = np.tile(np.linspace(0, 0.5, 9), (5, 1))
        V = np.tile(np.linspace(0, 0.25, 5)[:, None], (1, 9))
        s.set_texture(_checker(), uv=(U, V))
        uv = _uv(s)
        assert uv[:, 0].max() == pytest.approx(0.5, abs=1e-6)
        assert uv[:, 1].max() == pytest.approx(0.25, abs=1e-6)

    def test_explicit_uv_as_n_by_2_array(self):
        s = _surface(ndec=5, nra=9)
        arr = np.column_stack([np.full(45, 0.3), np.full(45, 0.7)])
        s.set_texture(_checker(), uv=arr)
        uv = _uv(s)
        assert uv[:, 0] == pytest.approx(0.3, abs=1e-6)
        assert uv[:, 1] == pytest.approx(0.7, abs=1e-6)

    def test_wrong_uv_length_raises(self):
        s = _surface(ndec=5, nra=9)
        with pytest.raises(ValueError, match="one per vertex"):
            s.set_texture(_checker(), uv=(np.zeros(10), np.zeros(10)))

    def test_wrong_uv_shape_raises(self):
        s = _surface(ndec=5, nra=9)
        with pytest.raises(ValueError, match=r"\(45, 2\) array"):
            s.set_texture(_checker(), uv=np.zeros((45, 3)))


# ---------------------------------------------------------------------------
# State, options, and lifecycle
# ---------------------------------------------------------------------------

class TestApi:
    def test_defaults(self):
        s = _surface()
        s.set_texture(_checker())
        assert s.has_texture
        assert s._state["texture_alpha"] == 1.0
        assert s._state["texture_shade"] is False
        assert s._state["texture_cull"] is False

    def test_options_are_stored(self):
        s = _surface()
        s.set_texture(_checker(), alpha=0.4, shade=True, cull_backfaces=True)
        assert s._state["texture_alpha"] == pytest.approx(0.4)
        assert s._state["texture_shade"] is True
        assert s._state["texture_cull"] is True

    def test_constructor_kwarg(self):
        s = _surface(texture=_checker())
        assert s.has_texture
        assert len(_uv(s)) == s._state["vertices_count"]

    def test_clear_texture(self):
        s = _surface(texture=_checker())
        s.clear_texture()
        assert not s.has_texture
        assert s._state["texture_url"] == ""
        assert s._state["texture_uv_b64"] == ""

    @pytest.mark.parametrize("bad", [-0.1, 1.5])
    def test_alpha_out_of_range_raises(self, bad):
        s = _surface()
        with pytest.raises(ValueError, match=r"alpha must be in \[0, 1\]"):
            s.set_texture(_checker(), alpha=bad)

    def test_scatter_rejects_textures(self):
        fig, ax = apl.subplots(1, 1)
        sc = ax.scatter3d(np.zeros(4), np.zeros(4), np.zeros(4))
        with pytest.raises(ValueError, match="only supported for surface"):
            sc.set_texture(_checker())

    def test_grid_shape_is_recorded(self):
        s = _surface(ndec=7, nra=11)
        assert (s._state["grid_rows"], s._state["grid_cols"]) == (7, 11)

    def test_non_surface_has_no_grid_shape(self):
        fig, ax = apl.subplots(1, 1)
        sc = ax.scatter3d(np.zeros(4), np.zeros(4), np.zeros(4))
        assert (sc._state["grid_rows"], sc._state["grid_cols"]) == (0, 0)


class TestSetData:
    def test_auto_uv_follows_a_new_grid_shape(self):
        s = _surface(ndec=5, nra=9)
        s.set_texture(_checker())
        X, Y, Z = _sphere(7, 11)
        s.set_data(X, Y, Z)
        assert len(_uv(s)) == 77
        assert s.has_texture

    def test_explicit_uv_survives_a_same_size_update(self):
        s = _surface(ndec=5, nra=9)
        s.set_texture(_checker(), uv=np.full((45, 2), 0.25))
        X, Y, Z = _sphere(5, 9)
        s.set_data(X, Y, Z)
        assert _uv(s)[:, 0] == pytest.approx(0.25, abs=1e-6)

    def test_explicit_uv_rejects_a_shape_change(self):
        s = _surface(ndec=5, nra=9)
        s.set_texture(_checker(), uv=np.full((45, 2), 0.25))
        X, Y, Z = _sphere(7, 11)
        with pytest.raises(ValueError, match="call set_texture again"):
            s.set_data(X, Y, Z)

    def test_untextured_set_data_is_unaffected(self):
        s = _surface(ndec=5, nra=9)
        X, Y, Z = _sphere(7, 11)
        s.set_data(X, Y, Z)
        assert s._state["vertices_count"] == 77

    def test_auto_uv_rebuild_keeps_flip_v(self):
        """A rebuilt auto mapping has to reapply the flip it was built with.

        Without this the UVs come back unflipped and a streaming textured
        surface turns upside-down on its first update.
        """
        s = _surface(ndec=5, nra=9)
        s.set_texture(_checker(), flip_v=True)
        before = _uv(s)[:, 1]
        X, Y, Z = _sphere(5, 9)
        s.set_data(X, Y, Z)
        assert _uv(s)[:, 1] == pytest.approx(before, abs=1e-6)
        # …and still flipped after a grid-shape change.
        X, Y, Z = _sphere(7, 11)
        s.set_data(X, Y, Z)
        uv = _uv(s)
        assert uv[:11, 1] == pytest.approx(np.ones(11), abs=1e-6)
        assert uv[-11:, 1] == pytest.approx(np.zeros(11), abs=1e-6)

    def test_clear_texture_resets_the_flip(self):
        s = _surface(ndec=5, nra=9)
        s.set_texture(_checker(), flip_v=True)
        s.clear_texture()
        s.set_texture(_checker())
        assert _uv(s)[:9, 1] == pytest.approx(np.zeros(9), abs=1e-6)


class TestTransport:
    def test_texture_rides_the_geometry_channel(self):
        s = _surface(texture=_checker())
        fig = s._fig
        view = json.loads(getattr(fig, f"panel_{s._id}_json"))
        geom = json.loads(getattr(fig, f"panel_{s._id}_geom"))
        assert "texture_url" not in view and "texture_uv_b64" not in view
        assert geom["texture_url"].startswith("data:image/png")
        assert geom["texture_uv_b64"]

    def test_view_only_update_does_not_resend_the_texture(self):
        s = _surface(texture=_checker())
        fig = s._fig
        before = getattr(fig, f"panel_{s._id}_geom")
        rev = json.loads(getattr(fig, f"panel_{s._id}_json"))["_geom_rev"]
        s.set_view(azimuth=12)
        s.set_title("moved")
        assert getattr(fig, f"panel_{s._id}_geom") == before
        assert json.loads(getattr(fig, f"panel_{s._id}_json"))["_geom_rev"] == rev


# ---------------------------------------------------------------------------
# Browser rendering
# ---------------------------------------------------------------------------

_MOUNT_PAGE = """<!DOCTYPE html>
<html><head><meta charset="utf-8"/>
<style>html,body{margin:0;padding:0;}</style></head>
<body><div id="host"></div>
<script type="module">
const STATE = __STATE__;
const esmSource = __ESM__;
const blobUrl = URL.createObjectURL(new Blob([esmSource], {type: "text/javascript"}));
import(blobUrl).then(mod => {
  window._api = mod.mount(document.getElementById("host"), STATE, {});
  window._aplReady = true;
}).catch(err => { document.body.textContent = "mount error: " + err; });
</script></body></html>
"""


def _renderer(browser):
    """Build a ``render(fig, panel_id=None) -> (pixels, panel_info)`` closure."""
    pages, paths = [], []

    def _render(fig, panel_id=None):
        html = (_MOUNT_PAGE
                .replace("__STATE__", json.dumps(figure_state(fig)))
                .replace("__ESM__", json.dumps(esm_path().read_text(encoding="utf-8"))))
        with tempfile.NamedTemporaryFile(suffix=".html", mode="w",
                                         encoding="utf-8", delete=False) as fh:
            fh.write(html)
            tmp = pathlib.Path(fh.name)
        paths.append(tmp)
        page = browser.new_page()
        pages.append(page)
        page.goto(tmp.as_uri())
        page.wait_for_function("() => window._aplReady === true", timeout=20_000)
        # The <img> decode is async and schedules its own redraw; on the GPU
        # path the device init adds a second async hop before activation.
        page.wait_for_timeout(1200)
        info = None
        if panel_id is not None:
            info = page.evaluate(
                """(pid) => {
                    const p = window._api.api.panels.get(pid);
                    return p ? { gpu: p._gpu, active: !!p._gpuActiveNow } : null;
                }""", panel_id)
        url = page.evaluate(
            "() => window._api.exportPNG({scale: 1}).then(r => r.dataUrl)")
        px = decode_png(base64.b64decode(url.split(",", 1)[1])).astype(int)
        return (px, info) if panel_id is not None else px

    def _cleanup():
        for p in pages:
            try:
                p.close()
            except Exception:
                pass
        for f in paths:
            f.unlink(missing_ok=True)

    return _render, _cleanup


@pytest.fixture
def render_png(_pw_browser):
    """Mount a figure, wait for the async texture decode, return the pixels.

    The default headless shell has no ``navigator.gpu``, so this always
    exercises the Canvas2D path.
    """
    render, cleanup = _renderer(_pw_browser)
    yield render
    cleanup()


@pytest.fixture
def gpu_render_png(_pw_gpu_browser):
    """Same, in the WebGPU-capable browser (skips without a usable adapter)."""
    render, cleanup = _renderer(_pw_gpu_browser)
    yield render
    cleanup()


def _flat_globe(rgb, **kwargs):
    """A sphere wrapped in one solid colour, filling the panel head-on."""
    X, Y, Z = _sphere(49, 97)
    fig, ax = apl.subplots(1, 1, figsize=(300, 300))
    s = ax.plot_surface(X, Y, Z, bounds=((-1, 1),) * 3,
                        azimuth=0, elevation=0)
    s.set_axis_off()
    tex = np.zeros((128, 256, 3), np.uint8)
    tex[:] = rgb
    s.set_texture(tex, cull_backfaces=True, **kwargs)
    return fig, s


def _drawn_mask(arr, tol=6):
    """Boolean mask of the pixels the sphere actually painted.

    "Not background", derived from the render itself: the figure paints two
    flat colours behind the sphere (the figure margin and the panel's plot
    background), and the projected sphere's radius is only ~0.32 x the panel
    size, so every colour covering a meaningful share of the image OUTSIDE a
    0.45 radius is a background by construction.  Sparse decorations out
    there (axis lines, tick labels) fall under the 5 % share cut.

    This replaces a fixed ``arr[..., :3].sum(2) < 600`` threshold — "darker
    than the lightest background".  That threshold sits EXACTLY on the flat
    (200, 200, 200) texture the shading tests use (200 x 3 == 600), so a
    strict ``<`` classified the whole sphere as background: on Windows and
    Ubuntu a handful of antialiased 199-greys squeaked under and the test
    limped along on 5 % of the disc, on macOS none did and the mask came back
    empty.  Keying on the background colours instead is independent of how
    light or dark the texture happens to be.
    """
    rgb = arr[..., :3]
    h, w = rgb.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w]
    ring = rgb[np.hypot(yy - h / 2, xx - w / 2) > 0.45 * min(h, w)].reshape(-1, 3)
    cols, counts = np.unique(ring, axis=0, return_counts=True)
    mask = np.ones((h, w), bool)
    for bg in cols[counts > 0.05 * len(ring)]:
        mask &= np.abs(rgb - bg).max(2) > tol
    return mask


def _disc(arr, inset=3):
    """Pixels well inside the sphere's silhouette (its own outline excluded)."""
    h, w = arr.shape[:2]
    non_bg = _drawn_mask(arr)
    ys, xs = np.nonzero(non_bg)
    assert len(ys), "nothing was drawn"
    cy, cx = h / 2, w / 2
    rad = np.hypot(ys - cy, xs - cx).max()
    yy, xx = np.mgrid[0:h, 0:w]
    return arr[non_bg & (np.hypot(yy - cy, xx - cx) < rad - inset)][:, :3]


class TestRender:
    def test_texture_colour_reaches_the_canvas(self, render_png):
        fig, _ = _flat_globe((0, 0, 200))
        px = _disc(render_png(fig))
        assert len(px) > 1000
        # Every interior pixel is the texture colour, not a viridis ramp.
        assert px[:, 2].mean() > 150
        assert px[:, 0].mean() < 40

    def test_no_seams_between_neighbouring_triangles(self, render_png):
        """A flat texture must render flat.

        The triangles are deliberately grown so neighbours overlap; without
        that, each covers about half of the pixels along a shared edge and
        the panel background bleeds through as a mesh of hairlines over the
        whole surface.  Assert on that directly: with one uniform colour,
        any interior pixel that is lighter than it is an artifact.
        """
        fig, _ = _flat_globe((20, 24, 46))
        px = _disc(render_png(fig))
        artifacts = (px[:, 0] > 20 + 8).sum()
        assert artifacts / len(px) < 0.01, (
            f"{artifacts}/{len(px)} interior pixels bled through "
            f"(max {px.max(0)}, expected [20 24 46])")

    def test_shade_lights_the_sphere_from_the_upper_left(self, render_png):
        """Diffuse shading must fall off away from the key light.

        The light sits front-and-upper-left in view space, so on a flat grey
        sphere the upper-left of the disc has to come out brighter than the
        lower-right — and both dimmer than the same sphere unshaded.
        """
        means = {}
        for shade in (False, True):
            fig, _ = _flat_globe((200, 200, 200), shade=shade)
            arr = render_png(fig)
            h, w = arr.shape[:2]
            cy, cx = h / 2, w / 2
            yy, xx = np.mgrid[0:h, 0:w]
            r = np.hypot(yy - cy, xx - cx)
            drawn = _drawn_mask(arr)
            inside = drawn & (r < r[drawn].max() - 4)
            ul = inside & (yy < cy) & (xx < cx)
            lr = inside & (yy > cy) & (xx > cx)
            means[shade] = (arr[ul][:, :3].mean(), arr[lr][:, :3].mean())

        assert means[True][0] > means[True][1] + 15, (
            f"shaded upper-left {means[True][0]:.0f} should beat "
            f"lower-right {means[True][1]:.0f}")
        assert means[False][0] == pytest.approx(means[False][1], abs=6), (
            f"unshaded halves should match: {means[False]}")

    def test_clear_texture_falls_back_to_the_colormap(self, render_png):
        fig, s = _flat_globe((0, 0, 200))
        s.clear_texture()
        px = _disc(render_png(fig))
        # viridis over a sphere is green/yellow at the top, purple at the
        # bottom — in any case not the flat blue the texture painted.
        assert px[:, 2].mean() < 150

    def test_untextured_surface_still_renders(self, render_png):
        X, Y, Z = _sphere(25, 49)
        fig, ax = apl.subplots(1, 1, figsize=(300, 300))
        ax.plot_surface(X, Y, Z, bounds=((-1, 1),) * 3)
        assert len(_disc(render_png(fig))) > 500


# ---------------------------------------------------------------------------
# WebGPU path
# ---------------------------------------------------------------------------

def _hemis_texture(h=128, w=256):
    """Left half of the image red, right half blue.

    On a sphere this puts one colour on each hemisphere, so a wrong depth
    direction — showing the FAR side instead of the near one — swaps which
    colour faces the camera and is impossible to miss.
    """
    img = np.zeros((h, w, 3), np.uint8)
    img[:, :w // 2] = [220, 30, 30]
    img[:, w // 2:] = [30, 30, 220]
    return img


def _gpu_globe(gpu, ndec=49, nra=97, tex=None, **kw):
    X, Y, Z = _sphere(ndec, nra)
    fig, ax = apl.subplots(1, 1, figsize=(300, 300))
    s = ax.plot_surface(X, Y, Z, bounds=((-1, 1),) * 3, gpu=gpu)
    s.set_axis_off()
    s.set_view(azimuth=0, elevation=0)
    s.set_texture(_hemis_texture() if tex is None else tex, **kw)
    return fig, s


class TestGpuSurface:
    """A textured surface renders on WebGPU and agrees with Canvas2D."""

    def test_activates_above_the_threshold(self, gpu_render_png):
        fig, s = _gpu_globe("auto")          # 9216 triangles > 2000
        _, info = gpu_render_png(fig, s._id)
        assert info["gpu"] == "active" and info["active"]

    def test_gpu_false_forces_canvas(self, gpu_render_png):
        fig, s = _gpu_globe(False)
        _, info = gpu_render_png(fig, s._id)
        assert not info["active"]

    def test_colormapped_surface_stays_on_canvas(self, gpu_render_png):
        """Only TEXTURED surfaces have a GPU path."""
        X, Y, Z = _sphere(49, 97)
        fig, ax = apl.subplots(1, 1, figsize=(300, 300))
        s = ax.plot_surface(X, Y, Z, bounds=((-1, 1),) * 3, gpu="always")
        _, info = gpu_render_png(fig, s._id)
        assert not info["active"]

    def test_translucent_surface_stays_on_canvas(self, gpu_render_png):
        """alpha < 1 needs the overlap-free Canvas2D composite."""
        fig, s = _gpu_globe("always", alpha=0.5)
        _, info = gpu_render_png(fig, s._id)
        assert not info["active"]

    def test_shows_the_near_hemisphere(self, gpu_render_png):
        """The depth test must keep the NEAREST fragment.

        Regression for an inverted clip-z in ``_gpuMatrix``: with the sign
        flipped the sphere rendered inside-out and the camera saw the far
        hemisphere's texture instead of the near one.
        """
        fig_c, s_c = _gpu_globe(False)
        fig_g, s_g = _gpu_globe("always")
        canvas, _ = gpu_render_png(fig_c, s_c._id)
        gpu, info = gpu_render_png(fig_g, s_g._id)
        assert info["active"]

        def split(arr):
            px = _disc(arr, inset=8)
            return (px[:, 0] > px[:, 2]).mean()   # fraction reading "red"

        assert split(gpu) == pytest.approx(split(canvas), abs=0.08), (
            "GPU and Canvas2D disagree about which hemisphere faces the camera")

    def test_matches_canvas_pixels(self, gpu_render_png):
        """Same geometry, same texture — the two paths must look the same.

        Not pixel-exact: the GPU shades per pixel against an interpolated
        normal and samples through a mip chain, where Canvas2D shades per
        triangle. A small mean difference is expected; a large one means the
        mapping, orientation, or depth handling diverged.
        """
        tex = _checker()
        fig_c, s_c = _gpu_globe(False, tex=tex)
        fig_g, s_g = _gpu_globe("always", tex=tex)
        canvas, _ = gpu_render_png(fig_c, s_c._id)
        gpu, info = gpu_render_png(fig_g, s_g._id)
        assert info["active"]
        assert gpu.shape == canvas.shape
        diff = np.abs(gpu[..., :3] - canvas[..., :3])
        assert diff.mean() < 12, f"mean abs diff {diff.mean():.1f}"

    def test_shading_lights_the_upper_left(self, gpu_render_png):
        flat = np.full((128, 256, 3), 200, np.uint8)
        fig, s = _gpu_globe("always", tex=flat, shade=True)
        arr, info = gpu_render_png(fig, s._id)
        assert info["active"]
        h, w = arr.shape[:2]
        cy, cx = h / 2, w / 2
        yy, xx = np.mgrid[0:h, 0:w]
        r = np.hypot(yy - cy, xx - cx)
        drawn = _drawn_mask(arr)
        inside = drawn & (r < r[drawn].max() - 4)
        ul = arr[inside & (yy < cy) & (xx < cx)][:, :3].mean()
        lr = arr[inside & (yy > cy) & (xx > cx)][:, :3].mean()
        assert ul > lr + 15, f"upper-left {ul:.0f}, lower-right {lr:.0f}"

    def test_live_texture_swap_rebuilds_the_gpu_texture(self, gpu_render_png):
        """set_texture after the first draw must reach the GPU texture."""
        fig, s = _gpu_globe("always", tex=np.full((64, 128, 3), 220, np.uint8))
        s.set_texture(np.zeros((64, 128, 3), np.uint8) + np.array(
            [20, 200, 40], np.uint8))
        arr, info = gpu_render_png(fig, s._id)
        assert info["active"]
        px = _disc(arr).mean(0)
        assert px[1] > px[0] + 40 and px[1] > px[2] + 40, f"got {px}"

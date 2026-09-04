"""Shared page fixtures for the embedding / PNG-export tests.

``mount_page`` drives the *public* ``mount()`` entry point exactly as an
Electron / SpyDE host would, with no anywidget shim in the way.
``scaled_mount_page`` is the same figure inside a container narrower than the
figure, so ``_applyScale``'s ``transform: scale()`` actually engages — the
condition under which export coordinates have to be un-scaled.
"""
from __future__ import annotations

import json
import pathlib
import tempfile

import pytest

from anyplotlib.embed import esm_path, figure_state
from anyplotlib.tests.test_embed._export_utils import MOUNT_PAGE as _MOUNT_PAGE

# Mirrors the `.apl-outer { min-width: max-content }` + transform-origin rules
# that Figure._css installs in a real notebook, and pins the host narrower than
# the figure so _applyScale computes s < 1.
_SCALED_CSS = """
#outer { width: 300px; overflow: hidden; }
.apl-outer { min-width: max-content; transform-origin: top left; }
"""


def _page_factory(browser, extra_css=""):
    pages, paths = [], []

    def _open(fig, device_scale_factor=None):
        html = (_MOUNT_PAGE
                .replace("__STATE__", json.dumps(figure_state(fig)))
                .replace("__ESM__", json.dumps(esm_path().read_text(encoding="utf-8")))
                .replace("__EXTRA_CSS__", extra_css))
        with tempfile.NamedTemporaryFile(
            suffix=".html", mode="w", encoding="utf-8", delete=False
        ) as fh:
            fh.write(html)
            tmp = pathlib.Path(fh.name)
        paths.append(tmp)
        kwargs = {}
        if device_scale_factor is not None:
            kwargs["device_scale_factor"] = device_scale_factor
        page = browser.new_page(**kwargs)
        pages.append(page)
        page.goto(tmp.as_uri())
        page.wait_for_function("() => window._aplReady === true", timeout=15_000)
        page.evaluate(
            "() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))"
        )
        return page

    def _cleanup():
        for p in pages:
            try:
                p.close()
            except Exception:
                pass
        for f in paths:
            f.unlink(missing_ok=True)

    return _open, _cleanup


@pytest.fixture
def mount_page(_pw_browser):
    """Open a figure via the public ``mount()`` API; return the live Page."""
    _open, _cleanup = _page_factory(_pw_browser)
    yield _open
    _cleanup()


@pytest.fixture
def scaled_mount_page(_pw_browser):
    """Same, but in a 300 px host so ``transform: scale(s<1)`` is applied."""
    _open, _cleanup = _page_factory(_pw_browser, extra_css=_SCALED_CSS)
    yield _open
    _cleanup()

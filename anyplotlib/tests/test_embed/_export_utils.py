"""Shared helpers for the PNG-export test modules.

The ``mount_page`` fixture that drives these lives in this package's
``conftest.py``; the pure functions live here so they can be imported by name.
"""
from __future__ import annotations

import base64

import numpy as np

from anyplotlib.tests._png_utils import decode_png

# A bare host page: no CSS constraint, so the figure renders at its native
# size and _applyScale leaves the transform empty. "__EXTRA_CSS__" lets the
# scaled variant inject the .apl-outer rules a real notebook supplies.
MOUNT_PAGE = """<!DOCTYPE html>
<html><head><meta charset="utf-8"/>
<style>html,body{margin:0;padding:0;}__EXTRA_CSS__</style></head>
<body><div id="outer"><div id="host"></div></div>
<script type="module">
const STATE = __STATE__;
const esmSource = __ESM__;
const blobUrl = URL.createObjectURL(new Blob([esmSource], {type: "text/javascript"}));
import(blobUrl).then(mod => {
  window._handle = mod.mount(document.getElementById("host"), STATE, {});
  window._aplReady = true;
}).catch(err => { document.body.textContent = "mount error: " + err; });
</script></body></html>
"""


def export_via_handle(page, opts=None):
    """Call ``window._handle.exportPNG(opts)``; return the result or ``{error}``."""
    return page.evaluate(
        """(opts) => window._handle.exportPNG(opts || {})
                .then(r => ({dataUrl: r.dataUrl, width: r.width, height: r.height}))
                .catch(e => ({error: String(e && e.message || e)}))""",
        opts or {},
    )


def decode_data_url(data_url: str) -> np.ndarray:
    """``data:image/png;base64,...`` → ``(H, W, C)`` uint8 array."""
    assert data_url.startswith("data:image/png;base64,"), (
        f"unexpected data URL prefix: {data_url[:40]!r}"
    )
    raw = base64.b64decode(data_url.split(",", 1)[1])
    return decode_png(raw)


def export_array(page, opts=None) -> np.ndarray:
    """Export and decode in one step, asserting the export did not error."""
    res = export_via_handle(page, opts)
    assert "error" not in res, f"exportPNG({opts!r}) failed: {res.get('error')}"
    return decode_data_url(res["dataUrl"])


def is_nonblank(arr: np.ndarray) -> bool:
    """True when the image is not a single flat colour (has real content)."""
    rgb = arr[..., :3].reshape(-1, 3)
    return int(np.unique(rgb, axis=0).shape[0]) > 1


def closest_color(arr: np.ndarray, rgb, tol: int = 12) -> int:
    """Number of pixels whose RGB is within *tol* of *rgb* on every channel."""
    d = np.abs(arr[..., :3].astype(np.int32) - np.asarray(rgb, dtype=np.int32))
    return int(((d <= tol).all(axis=-1)).sum())

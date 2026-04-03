"""Quick end-to-end test for the Playwright-based scraper thumbnail."""
import sys
sys.path.insert(0, 'docs')
sys.path.insert(0, 'tests')

import numpy as np
import anyplotlib as apl
from _sg_html_scraper import _make_thumbnail_png
from _png_utils import decode_png

tests = []

# 1D line plot
fig, ax = apl.subplots(1, 1, figsize=(400, 250))
ax.plot(np.sin(np.linspace(0, 2 * np.pi, 128)), color='#4fc3f7')
tests.append(("1D line", fig))

# 2D image
fig2, ax2 = apl.subplots(1, 1, figsize=(320, 320))
data = np.linspace(0, 1, 64 * 64, dtype=np.float32).reshape(64, 64)
ax2.imshow(data)
tests.append(("2D imshow", fig2))

# multi-panel
fig3, axes = apl.subplots(1, 2, figsize=(640, 300))
axes[0].plot(np.cos(np.linspace(0, 2 * np.pi, 64)))
axes[1].imshow(np.random.default_rng(0).uniform(0, 1, (32, 32)).astype(np.float32))
tests.append(("multi-panel", fig3))

for name, widget in tests:
    png = _make_thumbnail_png(widget)
    assert png[:4] == b'\x89PNG', f"[{name}] result is not a PNG!"
    arr = decode_png(png)
    r, g, b = arr[0, 0, 0], arr[0, 0, 1], arr[0, 0, 2]
    dark_ok = (b > r) and (b > 30)
    print(f"[{name}]  shape={arr.shape}  top-left RGB=({r},{g},{b})  {'DARK OK' if dark_ok else 'THEME CHECK NEEDED'}")

print("\nAll tests passed.")


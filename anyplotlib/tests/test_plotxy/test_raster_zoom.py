"""
A raster on a coordinate axis survives the view write-back a zoom makes.

The wheel handler writes the panel's view state back through the model, and
the model's change listener redraws the panel from that state after a round
trip through JSON. The decoded raster must not live in that state: a decoded
canvas serialises to ``{}``, which then passed for a cached image, made
``drawImage`` throw, and left the panel blank until the next push from Python.
"""
from __future__ import annotations

import numpy as np

import anyplotlib as apl

GRID_PAD = 8  # gridDiv padding: the canvas's offset from the page origin

_RED_PIXELS = """() => {
  let count = 0
  for (const canvas of document.querySelectorAll('canvas')) {
    const context = canvas.getContext('2d')
    if (!context || !canvas.width || !canvas.height) continue
    const data = context.getImageData(0, 0, canvas.width, canvas.height).data
    for (let i = 0; i < data.length; i += 4) {
      if (data[i + 3] > 128 && data[i] > 150 && data[i + 1] < 80 && data[i + 2] < 80) count++
    }
  }
  return count
}"""

_TWO_FRAMES = "() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))"


def _red_raster_figure():
    fig, ax = apl.subplots(1, 1, figsize=(300, 300))
    coordinates = ax.axes2d(xlim=(0.0, 1.0), ylim=(0.0, 1.0), aspect="equal")
    red = np.zeros((8, 8, 4), dtype=np.uint8)
    red[..., 0] = 255
    red[..., 3] = 255
    coordinates.add_raster(red, extent=(0.0, 1.0, 0.0, 1.0))
    return fig


class TestRasterSurvivesZoom:
    def test_a_wheel_zoom_keeps_the_raster(self, interact_page):
        page = interact_page(_red_raster_figure())
        before = page.evaluate(_RED_PIXELS)
        assert before > 1000, f"the raster was not drawn to begin with ({before} red pixels)"

        page.mouse.move(GRID_PAD + 150, GRID_PAD + 130)
        for _ in range(3):
            page.mouse.wheel(0, -240)
            page.wait_for_timeout(50)
        page.evaluate(_TWO_FRAMES)
        page.wait_for_timeout(100)

        after = page.evaluate(_RED_PIXELS)
        assert after > 1000, f"zooming blanked the raster ({before} red pixels before, {after} after)"

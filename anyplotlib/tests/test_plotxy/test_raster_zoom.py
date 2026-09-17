"""
A raster on a coordinate axis survives the view write-back a zoom makes, and
its decoded image is rebuilt whenever its bytes or its shape change.

The wheel handler writes the panel's view state back through the model, and
the model's change listener redraws the panel from that state after a round
trip through JSON. The decoded raster must not live in that state: a decoded
canvas serialises to ``{}``, which then passed for a cached image, made
``drawImage`` throw, and left the raster — and every marker drawn after it —
blank until the next push from Python.
"""
from __future__ import annotations

import numpy as np

import anyplotlib as apl

GRID_PAD = 8  # gridDiv padding: the canvas's offset from the page origin

RED = (255, 0, 0, 255)
GREEN = (0, 255, 0, 255)

# Where the red and the green pixels are, across every 2-D canvas.
_COLOUR_EXTENTS = """() => {
  const found = {red: {count: 0, minX: Infinity, maxX: -Infinity},
                 green: {count: 0, minX: Infinity, maxX: -Infinity}}
  for (const canvas of document.querySelectorAll('canvas')) {
    const context = canvas.getContext('2d')
    if (!context || !canvas.width || !canvas.height) continue
    const data = context.getImageData(0, 0, canvas.width, canvas.height).data
    for (let i = 0; i < data.length; i += 4) {
      if (data[i + 3] < 128) continue
      const red = data[i], green = data[i + 1], blue = data[i + 2]
      const colour = red > 150 && green < 80 && blue < 80 ? found.red
        : green > 150 && red < 80 && blue < 80 ? found.green : null
      if (!colour) continue
      const x = (i / 4) % canvas.width
      colour.count++
      colour.minX = Math.min(colour.minX, x)
      colour.maxX = Math.max(colour.maxX, x)
    }
  }
  return found
}"""

_TWO_FRAMES = "() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))"


def _coordinate_axis():
    fig, ax = apl.subplots(1, 1, figsize=(300, 300))
    return fig, ax.axes2d(xlim=(0.0, 1.0), ylim=(0.0, 1.0), aspect="equal")


def _wheel_zoom(page):
    page.mouse.move(GRID_PAD + 150, GRID_PAD + 130)
    for _ in range(3):
        page.mouse.wheel(0, -240)
        page.wait_for_timeout(50)
    page.evaluate(_TWO_FRAMES)
    page.wait_for_timeout(100)


class TestRasterSurvivesZoom:
    def test_a_wheel_zoom_keeps_the_raster_and_the_markers_after_it(self, interact_page):
        fig, coordinates = _coordinate_axis()
        coordinates.add_raster(np.tile(np.array(RED, np.uint8), (8, 8, 1)),
                               extent=(0.0, 1.0, 0.0, 1.0))
        # Drawn after the raster, so a raster that throws takes it down too.
        coordinates.scatter([0.5], [0.5], s=10, c="#00ff00", edgecolors="#00ff00")
        page = interact_page(fig)
        before = page.evaluate(_COLOUR_EXTENTS)
        assert before["red"]["count"] > 1000, f"the raster was not drawn to begin with: {before}"
        assert before["green"]["count"] > 20, f"the marker was not drawn to begin with: {before}"

        _wheel_zoom(page)

        after = page.evaluate(_COLOUR_EXTENTS)
        assert after["red"]["count"] > 1000, f"zooming blanked the raster: {before} -> {after}"
        assert after["green"]["count"] > 20, f"zooming blanked the marker: {before} -> {after}"


class TestRasterRedecodes:
    def test_the_same_bytes_in_a_new_shape_are_decoded_again(self, interact_page):
        # Two red pixels then two green ones: as 2×2 the red row sits above the
        # green one; as 4×1 the red half sits left of the green half.
        fig, coordinates = _coordinate_axis()
        square = np.array([[RED, RED], [GREEN, GREEN]], dtype=np.uint8)
        coordinates.add_raster(square, extent=(0.0, 1.0, 0.0, 1.0))
        page = interact_page(fig)
        stacked = page.evaluate(_COLOUR_EXTENTS)
        assert stacked["red"]["maxX"] > stacked["green"]["minX"] + 50, \
            f"the 2x2 raster should put red above green: {stacked}"

        page.evaluate("""(panelId) => {
          const name = 'panel_' + panelId + '_geom'
          const geom = JSON.parse(window._aplModel.get(name))
          for (const id in geom.raster_geom) {
            geom.raster_geom[id].image_width = 4
            geom.raster_geom[id].image_height = 1
          }
          window._aplModel.set(name, JSON.stringify(geom))
        }""", coordinates._id)
        page.evaluate(_TWO_FRAMES)

        side_by_side = page.evaluate(_COLOUR_EXTENTS)
        assert side_by_side["red"]["count"] > 1000 and side_by_side["green"]["count"] > 1000, \
            f"the 4x1 raster lost a colour: {side_by_side}"
        assert side_by_side["red"]["maxX"] <= side_by_side["green"]["minX"] + 2, \
            f"the 4x1 raster was drawn from the stale 2x2 image: {side_by_side}"

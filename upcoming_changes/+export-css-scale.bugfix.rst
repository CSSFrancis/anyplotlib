Fixed PNG export producing a mostly-blank image when the figure is wider than
the notebook cell. In that case the renderer shrinks the figure with a CSS
``transform: scale()``, which makes element rectangles report *visual* pixels
while the export sized its canvas in *native* pixels — so the panels were
composited into the top-left corner and the remainder was filled with the
background colour. Export coordinates are now un-scaled by the live transform.

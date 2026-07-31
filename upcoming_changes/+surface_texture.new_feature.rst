Added :meth:`~anyplotlib.Plot3D.set_texture` for wrapping an image around a 3-D
surface — a globe, a planet, or a star chart on the celestial sphere — with
optional diffuse shading and backface culling.  ``Axes.plot_surface`` gained
``texture=``, ``bounds=``, and ``gpu=`` to match.  Textured surfaces render on
WebGPU when it is available (roughly 9k triangles at 54 ms/frame on Canvas2D
versus 0.4 ms on the GPU), falling back to Canvas2D silently otherwise.
``set_axis_off()`` now also hides a 3-D panel's axis lines, labels, and ticks.

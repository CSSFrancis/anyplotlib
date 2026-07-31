Fixed an inverted depth comparison in the WebGPU 3-D projection: a GPU-rendered
:meth:`~anyplotlib.Axes.scatter3d` cloud drew its far points on top of its near
ones wherever two points overlapped on screen.  Voxel panels were unaffected
(they disable depth writes), and the Canvas2D path was always correct.

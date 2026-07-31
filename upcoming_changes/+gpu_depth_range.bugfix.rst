Fixed WebGPU 3-D geometry being clipped at the corners of a cube-shaped
dataset.  The clip-space depth scale let ``clip.z`` reach 1.09 for a point at
the far corner of the normalised bounds box, outside the ``[0, 1]`` range
WebGPU keeps, so the nearest corner of a dense :meth:`~anyplotlib.Axes.scatter3d`
cloud silently vanished at the default camera angles.  Spherical geometry was
never affected.

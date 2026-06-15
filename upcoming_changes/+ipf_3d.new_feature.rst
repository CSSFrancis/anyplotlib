``imshow`` now renders ``(H, W, 3|4)`` arrays as true-colour RGB(A) images
(previously the extra channels were silently dropped).  ``scatter3d`` gained
per-point ``colors=`` and a ``bounds=`` override for origin-true geometry
(e.g. unit vectors on a sphere), ``Plot3D.set_highlight()`` marks a
single emphasised point, and ``Plot3D.set_sphere()`` draws a shaded,
wireframed reference sphere behind the data (far-side points dimmed).  The 3-D camera is now a proper turntable
(matplotlib ``azim``/``elev`` semantics — azimuth spins about the data
z-axis): the previous camera could not aim at arbitrary directions, which
blocked rotate-to-face interactions.  A new gallery example,
*Inverse Pole Figure (IPF) Explorer*, combines all of these: an IPF-RGB
orientation map whose crosshair rotates a reduced 3-D IPF sphere to face
the selected grain's crystal direction.

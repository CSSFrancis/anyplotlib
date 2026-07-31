**3-D orbit drags have reversed direction.**  Both azimuth and elevation now
move the geometry *with* the cursor instead of away from it, matching
matplotlib's ``mplot3d`` and every other turntable control — dragging right
spins a globe right.  Azimuth and elevation position the *camera*, so adding
the drag delta swept the surface the opposite way, as if you had grabbed its
far side.  Any muscle memory (or scripted pointer drag) built against the old
direction is inverted; panels driven from Python with
:meth:`~anyplotlib.Plot3D.set_view` are unaffected.

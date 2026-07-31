:class:`~anyplotlib.Event` now carries ``azimuth`` and ``elevation`` for 3-D
orbit events. The renderer had always emitted them alongside ``zoom``, but they
were dropped on the way to Python — and since a JS-side drag does not sync back
into ``Plot3D._state``, a handler had no way to react to an orbit at all. See
the new ``Star Globe Explorer`` gallery example, which links a celestial sphere
to a sky map through them.

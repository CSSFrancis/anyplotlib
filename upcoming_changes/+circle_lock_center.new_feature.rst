``Plot2D.add_circle_widget`` gains ``lock_center``: the centre is pinned and
only the radius is draggable. A grab on the ring body is refused at hit-test
time and falls through to the plot's own pan, so the hover cursor never
promises a move and the centre cannot drift. Use it when the centre is fixed by
the data — a ring on a power spectrum is centred on the DC term, and one nudged
off-centre silently corrupts every radius measured from it.

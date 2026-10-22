Marker kwargs now accept a length-1 sequence wherever a scalar is accepted
(``radius=[5]``, ``linewidths=(1.5,)``, ``edgecolors=["#f00"]``), broadcasting
it across the group as matplotlib's property cycling does.

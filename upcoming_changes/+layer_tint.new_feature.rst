Added ``tint=`` to :meth:`~anyplotlib.plot2d.Plot2D.add_layer` and
:meth:`~anyplotlib.plot2d.Layer.set` — a ``#rgb``/``#rrggbb`` hex colour that
renders the layer as a clear→colour intensity ramp (transparent at low
intensity, opaque tint at high, via a 256×4 RGBA LUT) instead of a named
colormap; passing ``cmap=`` reverts a tinted layer to colormap display.

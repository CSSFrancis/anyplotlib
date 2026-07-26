Panels expose their geometry through :meth:`~anyplotlib.Plot1D.plot_box`,
:meth:`~anyplotlib.Plot1D.data_to_display` and
:meth:`~anyplotlib.Plot1D.display_to_data`, so callers working in display space
no longer have to re-derive the renderer's layout constants and letterbox maths
themselves.

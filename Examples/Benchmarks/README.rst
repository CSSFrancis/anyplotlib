Benchmarks
----------

Timing comparisons for the Python-side data-push pipeline in anyplotlib,
matplotlib, Plotly, and Bokeh.  All measurements capture only the
**Python serialisation cost** — the bottleneck in a live Jupyter session
where new data must be encoded and dispatched to the browser on every frame.


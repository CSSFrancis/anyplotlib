Interactive (⚡) documentation figures are much smoother under Pyodide.  Each
user interaction event was dispatched with ``pyodide.runPythonAsync`` on a
freshly-built code string, which recompiles Python source every frame
(~1.2 ms/event in WASM — the dominant per-frame cost on a drag).  The bridge
now calls a pre-compiled dispatcher proxy directly (~50× faster, ~0.02 ms),
so panning, orbiting, and dragging widgets / slice planes in the docs keep up
with the gesture.

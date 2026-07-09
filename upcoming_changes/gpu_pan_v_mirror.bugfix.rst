Fixed the WebGPU 2-D image path sampling a vertically MIRRORED window when the
view was panned off-centre: the shader applied a global ``1 - v`` flip after
interpolating the ``[v0, v1]`` uv window, which sampled ``[1-v1, 1-v0]``
instead — correct only for a full or vertically-centred view. Symptoms: pan-y
moved the image the wrong way on GPU-rendered panels, and markers/widgets
(drawn by the shared Canvas2D overlay transform, which was always correct)
appeared detached from the image features they marked. The base and
detail-tile passes share the shader, so both are fixed. GPU-vs-CPU screenshot
parity tests (zoom, pan, markers, widgets, detail tile) now run on real WebGPU
in headless Chromium (``channel="chromium"`` + ``--enable-unsafe-webgpu``) and
skip on machines with no adapter.

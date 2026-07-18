Fixed ``exportPNG`` compositing WebGPU-rendered 3-D panels (``scatter3d`` /
``voxels``) as blank background rectangles — the 3-D render pass is now
re-rendered synchronously in-task before the canvas readback, exactly like
active-GPU 2-D image panels.

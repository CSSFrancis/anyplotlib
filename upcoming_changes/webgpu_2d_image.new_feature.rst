2-D scalar images can now render on the **GPU via WebGPU** (``imshow(...,
gpu="auto"|True|False)``): the image uploads as an R8 texture and a WGSL fragment
shader applies the colormap LUT + contrast (clim) in one draw, replacing the
per-pixel JavaScript colormap loop. Large images (≳1 megapixel) take the GPU path
automatically; everything below the threshold, RGB images, ``gpu=False``, and any
device without WebGPU keep the identical Canvas2D path. ``plot.gpu_active`` reports
which path ran. Verified on an NVIDIA Pascal GPU.

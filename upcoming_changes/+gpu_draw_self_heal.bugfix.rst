Fixed a 3-D GPU panel breaking — voxels and axes both vanishing after
rendering correctly — when the WebGPU device throws mid-draw or is lost,
as Safari's experimental WebGPU does after working for a while.  The GPU
path makes the decoration ``plotCanvas`` transparent and takes GPU-only
branches, so a mid-draw failure left the frame half-built and only a window
resize (which forces a full redraw) restored it.  The fallback now disposes
the GPU panel, restores the opaque background, and re-renders the whole panel
once on the Canvas2D path in the same frame, so it self-heals without a
resize.

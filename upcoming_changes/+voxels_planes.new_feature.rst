New ``Axes.voxels()`` 3-D geometry renders volumes as shaded translucent
cubes (per-voxel colours, global ``alpha``), and 3-D panels gained their
first interactive widget: ``add_widget("plane", axis=..., position=...)``
adds a draggable :class:`PlaneWidget` slice selector — drag it along its
normal in the browser and ``pointer_move``/``pointer_up`` callbacks fire in
Python.  Voxels lying on a plane render more opaque
(``voxel_slice_alpha``), so selected slices glow inside the volume.  The
voxel grain explorer example now uses all of this: three plane widgets
bidirectionally linked with three orthoslice crosshairs and the 3-D IPF.

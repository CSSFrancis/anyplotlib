Fixed 3-D plane-widget drags snapping back instead of moving smoothly.
``Plot3D.to_state_dict()`` now always serialises the live overlay widgets, so
a view-only push on the same panel (``set_highlight`` / ``set_view``) no
longer re-sends a stale plane position and clobbers an in-progress drag.  The
voxel grain explorer also tracks smooth (float) positions for the highlight
marker so it glides with the planes instead of jumping by whole voxels.

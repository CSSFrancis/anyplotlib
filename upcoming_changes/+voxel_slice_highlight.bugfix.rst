Fixed the 3-D voxel highlight appearing to "float" or land on random voxels
in large grain volumes.  ``Plot3D.set_point_colors`` now accepts ``voxels``
panels (not just ``scatter``), so the orthoslice explorer can re-colour voxels
live.  The voxel grain explorer now renders the voxels that lie *on* the three
slice planes (instead of a sparse random subsample of the whole volume), so the
highlight marker is always anchored on a real cube at the slice intersection.
The on-plane voxel count is ~3·(N/step)² regardless of N, so this stays fast
even for a 256³ volume.

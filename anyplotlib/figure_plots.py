"""
figure_plots.py (compatibility shim)
=====================================
All classes have been moved to dedicated subpackages. Import from those directly:

    from anyplotlib.figure import Figure, GridSpec, SubplotSpec, subplots
    from anyplotlib.axes import Axes, InsetAxes
    from anyplotlib.plot1d import Plot1D, Line1D, PlotBar
    from anyplotlib.plot2d import Plot2D, PlotMesh
    from anyplotlib.plot3d import Plot3D
"""

from anyplotlib.figure._gridspec import GridSpec, SubplotSpec  # noqa: F401
from anyplotlib.axes import Axes, InsetAxes                    # noqa: F401
from anyplotlib.plot1d import Line1D, Plot1D, PlotBar          # noqa: F401
from anyplotlib.plot2d import Plot2D, PlotMesh                 # noqa: F401
from anyplotlib.plot3d import Plot3D                           # noqa: F401
from anyplotlib._utils import (                                # noqa: F401
    _arr_to_b64, _norm_linestyle, _normalize_image,
    _build_colormap_lut, _resample_mesh,
    _LINESTYLE_ALIASES, _CMAP_ALIASES,
)

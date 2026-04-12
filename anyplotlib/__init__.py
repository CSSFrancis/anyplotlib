from anyplotlib.figure import Figure, GridSpec, SubplotSpec, subplots
from anyplotlib.figure_plots import Axes, InsetAxes, Plot1D, Plot2D, PlotMesh, Plot3D, PlotBar
from anyplotlib.callbacks import CallbackRegistry, Event
from anyplotlib.widgets import (
    Widget, RectangleWidget, CircleWidget, AnnularWidget,
    CrosshairWidget, PolygonWidget, LabelWidget,
    VLineWidget, HLineWidget, RangeWidget,
)

# ── Global help flag ──────────────────────────────────────────────────────
# Set to False to suppress help badges on all figures in this session.
# Default True: badges appear whenever a figure has help text set.
show_help: bool = True

__all__ = [
    "Figure", "GridSpec", "SubplotSpec", "subplots",
    "Axes", "InsetAxes", "Plot1D", "Plot2D", "PlotMesh", "Plot3D", "PlotBar",
    "CallbackRegistry", "Event",
    "Widget", "RectangleWidget", "CircleWidget", "AnnularWidget",
    "CrosshairWidget", "PolygonWidget", "LabelWidget",
    "VLineWidget", "HLineWidget", "RangeWidget",
    "show_help",
]

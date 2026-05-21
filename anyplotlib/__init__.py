from anyplotlib.figure import Figure, GridSpec, SubplotSpec, subplots
from anyplotlib.axes import Axes, InsetAxes
from anyplotlib.plot1d import Plot1D, PlotBar
from anyplotlib.plot2d import Plot2D, PlotMesh
from anyplotlib.plot3d import Plot3D
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

_COLOR_CYCLE: list[str] = [
    "#4fc3f7", "#ff7043", "#aed581", "#ffd54f",
    "#ba68c8", "#4db6ac", "#f06292", "#90a4ae",
    "#ffb74d", "#a5d6a7",
]


def get_color_cycle() -> list[str]:
    """Return the default color cycle as a list of CSS hex strings."""
    return list(_COLOR_CYCLE)


__all__ = [
    "Figure", "GridSpec", "SubplotSpec", "subplots",
    "Axes", "InsetAxes", "Plot1D", "Plot2D", "PlotMesh", "Plot3D", "PlotBar",
    "CallbackRegistry", "Event",
    "Widget", "RectangleWidget", "CircleWidget", "AnnularWidget",
    "CrosshairWidget", "PolygonWidget", "LabelWidget",
    "VLineWidget", "HLineWidget", "RangeWidget",
    "show_help", "get_color_cycle",
]

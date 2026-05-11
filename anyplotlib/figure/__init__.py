"""anyplotlib.figure — Figure widget, grid spec, and subplots factory."""

from anyplotlib.figure._figure import Figure
from anyplotlib.figure._gridspec import GridSpec, SubplotSpec
from anyplotlib.figure._subplots import subplots

__all__ = ["Figure", "GridSpec", "SubplotSpec", "subplots"]

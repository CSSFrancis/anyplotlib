:meth:`Figure.close <anyplotlib.Figure.close>` now also closes the
underlying ipywidgets comm (removing the figure's front-end views) and drops
it from ipywidgets' instance registry, so a closed figure that is no longer
referenced — and its plot data — can be garbage collected.  Previously every
figure stayed alive for the life of the process.

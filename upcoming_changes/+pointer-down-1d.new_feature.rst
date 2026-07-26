Clicking a 1-D panel now emits a ``pointer_down`` event carrying the clicked
position as ``xdata``/``ydata``, matching 2-D panels; it previously fired only
when the click landed on a line.  Clicks on a line still report ``line_id``,
so existing line-click handlers are unaffected.

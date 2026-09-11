A self-contained HTML page can now navigate its own data.
``anyplotlib.embed.navigated_html`` writes a figure, the dataset it navigates
and a list of bindings into one file: drag the navigator's crosshair and the
signal panel shows that position's frame, its overlays follow, and a detector
drawn on the signal panel re-maps the navigator.  Data travels as *blocks* —
dense arrays, or ``Ragged`` row-pointer blocks for a variable number of rows
per position — packed by ``pack_blocks`` into one byte string the page decodes
once.

The JS mount handle gained the pieces that make that fast: ``setImage`` pushes
raw pixel bytes straight to the renderer's draw path (a fraction of a
millisecond at 2048², against 129-136 ms through the panel state),
``patchPanel`` merges a partial state, and ``panelIds`` lists the panels.  The
runtime and its readers (``mountNavigated``, ``dense``, ``ragged``,
``maskFromWidget``, ``rasterDisks``, ``robustLevels``, ``toU8``) are exported
from ``figure_esm.js`` for hosts that already own their data.

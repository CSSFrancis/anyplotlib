Modified key presses no longer trigger a plot's single-letter shortcuts. The
panel key handlers matched on the bare letter without checking modifiers, so
``Ctrl+C`` toggled the colorbar instead of copying, and ``Cmd+S`` — JupyterLab's
*save notebook* — silently flipped a 2-D plot's colour scale to symlog. Keys
pressed with ``Ctrl``, ``Cmd`` or ``Alt`` are now left to the host. They are
still reported to Python ``key_down`` callbacks exactly as before, so nothing
that observes the full keystroke changes.

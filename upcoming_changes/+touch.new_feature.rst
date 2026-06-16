Plots are now usable on touch devices (iPad / iPhone) and trackpads.  A touch
bridge in the renderer translates gestures into the existing interaction
handlers, so every panel type and every example becomes touch-capable with no
API change: one-finger drag pans / orbits / moves a widget, ROI, marker or
slice plane (whatever is under the finger); two-finger pinch zooms; and
double-tap fires the panel's ``double_click`` event.  Overlay canvases set
``touch-action: none`` so the browser hands gestures to the plot instead of
scrolling the page.

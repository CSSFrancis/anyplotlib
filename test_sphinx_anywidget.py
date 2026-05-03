"""Quick smoke test for sphinx_anywidget extension."""
from anyplotlib.sphinx_anywidget import AnywidgetScraper, ViewerScraper, setup
from anyplotlib.sphinx_anywidget._scraper import _find_widget, _iframe_html
from anyplotlib.sphinx_anywidget._repr_utils import build_standalone_html, _widget_px
from anyplotlib.sphinx_anywidget._wheel_builder import build_wheel
from anyplotlib.sphinx_anywidget._directive import AnywidgetFigureDirective
print('imports OK')

import numpy as np
import anyplotlib as apl

fig, ax = apl.subplots(1, 1, figsize=(400, 300))
ax.plot(np.sin(np.linspace(0, 6.28, 64)))

html = build_standalone_html(fig, resizable=False, fig_id='tf')
assert 'awi_state' in html, 'Missing awi_state listener'
assert '"tf"' in html, 'Missing fig_id in HTML'

w, h = _widget_px(fig)
assert w == 416, f'Expected 416 got {w}'

b = _iframe_html('t.html', 400, 300, fig_id='a', interactive=True)
assert 'awi-activate-btn' in b, 'Missing activate button'

s = _iframe_html('t.html', 400, 300, fig_id='a', interactive=False)
assert 'awi-activate-btn' not in s, 'Should not have activate btn on static'

import anyplotlib.figure as _af
assert not hasattr(_af, '_pyodide_push_hook'), '_pyodide_push_hook should be gone'

# Test _find_widget
found = _find_widget({'fig': fig, 'x': 42})
assert found is fig, 'Should find Figure'
assert _find_widget({'x': 42}) is None

# Test # Interactive detection
from anyplotlib.sphinx_anywidget._scraper import _INTERACTIVE_RE
assert _INTERACTIVE_RE.search('fig  # Interactive\n'), 'Should match'
assert _INTERACTIVE_RE.search('fig  # interactive'), 'Should match lowercase'
assert not _INTERACTIVE_RE.search('fig  # not a match'), 'Should not match'

print('ALL SMOKE TESTS PASSED')


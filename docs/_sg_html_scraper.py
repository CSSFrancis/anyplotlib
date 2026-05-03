"""
_sg_html_scraper.py — compatibility shim
=========================================

The canonical implementation has moved to
``anyplotlib.sphinx_anywidget._scraper``.

This file is kept so any ``conf.py`` that still does::

    from _sg_html_scraper import ViewerScraper

continues to work without changes.
"""

from anyplotlib.sphinx_anywidget._scraper import (  # noqa: F401
    AnywidgetScraper,
    AnywidgetScraper as ViewerScraper,
)

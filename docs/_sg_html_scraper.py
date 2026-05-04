"""
_sg_html_scraper.py — compatibility shim
=========================================

The canonical implementation has moved to
``anyplotlib.sphinx_anywidget._scraper``.

This file is kept so any ``conf.py`` that still does::

    from _sg_html_scraper import ViewerScraper

continues to work without changes.  All public helpers that existed in the
original module are re-exported here so downstream imports keep working.
"""

from anyplotlib.sphinx_anywidget._scraper import (  # noqa: F401
    AnywidgetScraper,
    AnywidgetScraper as ViewerScraper,
    _make_thumbnail_png,
    _iframe_html,
)

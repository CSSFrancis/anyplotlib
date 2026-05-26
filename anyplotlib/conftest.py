"""
anyplotlib/conftest.py
======================

Package-level pytest fixtures shared by ALL test subdirectories:
  - anyplotlib/tests/
  - anyplotlib/sphinx_anywidget/tests/

Putting ``_pw_browser`` here (rather than in either subdirectory's conftest)
means both test trees share the same Chromium session — only one
``sync_playwright()`` context is ever active per pytest run.
"""
from __future__ import annotations

import pytest


@pytest.fixture(scope="session")
def _pw_browser():
    """Yield a headless Chromium browser for the whole test session."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        yield browser
        browser.close()

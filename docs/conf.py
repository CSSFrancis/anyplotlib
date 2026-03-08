# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

import os
import sys

# Make the viewer package importable from docs/
sys.path.insert(0, os.path.abspath(".."))
# Make docs/ itself importable so _sg_html_scraper can be found.
sys.path.insert(0, os.path.abspath("."))

from _sg_html_scraper import ViewerScraper  # noqa: E402

# -- Project information -----------------------------------------------------
project = "viewer"
copyright = "2026, viewer contributors"
author = "viewer contributors"
release = "0.1.0"

# -- General configuration ---------------------------------------------------
extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.autosummary",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    "sphinx.ext.intersphinx",
    "sphinx_gallery.gen_gallery",
]

autosummary_generate = True

napoleon_google_docstring = False
napoleon_numpy_docstring = True
napoleon_use_param = True
napoleon_use_rtype = True

intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "numpy": ("https://numpy.org/doc/stable", None),
    "matplotlib": ("https://matplotlib.org/stable", None),
}

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

# -- Sphinx Gallery configuration --------------------------------------------
sphinx_gallery_conf = {
    "examples_dirs": "../Examples",
    "gallery_dirs": "auto_examples",
    "filename_pattern": r"/plot_",
    "plot_gallery": True,
    "download_all_examples": True,
    "remove_config_comments": True,
    # ViewerScraper captures _repr_html_() from viewer Widgets and writes
    # them as self-contained iframe HTML files.  The matplotlib scraper
    # handles any plain plt figures in the same example.
    "image_scrapers": (ViewerScraper(), "matplotlib"),
    # Clean module state between examples.
    "reset_modules": ("matplotlib",),
    # capture_repr must be empty — the ViewerScraper handles all display via
    # image_scrapers.  If _repr_html_ is listed here, SG embeds the multi-line
    # srcdoc= attribute as a second raw:: html block which docutils mangles.
    "capture_repr": (),
    # Don't abort on errors — show a placeholder instead.
    "abort_on_example_error": False,
    "expected_failing_examples": [],
    # No notebook magic needed.
    "first_notebook_cell": None,
    "last_notebook_cell": None,
}

# -- Options for HTML output -------------------------------------------------
html_theme = "pydata_sphinx_theme"
html_static_path = ["_static"]

html_theme_options = {
    "github_url": "https://github.com/",
    "logo": {
        "text": "viewer",
    },
    "navbar_end": ["navbar-icon-links"],
    "show_toc_level": 2,
}

# -- autodoc options ---------------------------------------------------------
autodoc_default_options = {
    "members": True,
    "undoc-members": False,
    "show-inheritance": True,
    "member-order": "bysource",
}
autodoc_typehints = "description"


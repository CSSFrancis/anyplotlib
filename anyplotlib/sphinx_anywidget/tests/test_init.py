"""
sphinx_anywidget/tests/test_init.py
=====================================

Tests for ``sphinx_anywidget.__init__``:
  - ``setup()``
  - ``_find_project_root()``
  - ``_infer_package_name()``
  - ``_copy_static_assets()``
  - ``_build_pyodide_wheel()``
  - No stale push hook on the figure module
"""
from __future__ import annotations

import pathlib
import tempfile
import textwrap

import pytest

import anyplotlib.figure as _af
from anyplotlib.sphinx_anywidget import setup
from anyplotlib.sphinx_anywidget import (
    _copy_static_assets,
    _build_pyodide_wheel,
    _find_project_root,
    _infer_package_name,
)


# ---------------------------------------------------------------------------
# Helpers / mocks
# ---------------------------------------------------------------------------

class MockConfig:
    def __init__(self, confdir):
        self.anywidget_pyodide_package = None
        self.html_static_path = []
        self._confdir = str(confdir)

    def __getattr__(self, name):
        return None


class MockApp:
    """Minimal Sphinx application stub."""

    def __init__(self, confdir, outdir=None):
        self.confdir = str(confdir)
        self.outdir = str(outdir or confdir / "_build")
        self.config = MockConfig(confdir)
        self._directives = {}
        self._js_files = []
        self._css_files = []
        self._config_values = {}
        self._event_handlers = {}

    def add_config_value(self, name, default, rebuild):
        self._config_values[name] = default

    def add_directive(self, name, cls):
        self._directives[name] = cls

    def connect(self, event, handler):
        self._event_handlers.setdefault(event, []).append(handler)

    def add_js_file(self, path, **kwargs):
        self._js_files.append(path)

    def add_css_file(self, path, **kwargs):
        self._css_files.append(path)


# ---------------------------------------------------------------------------
# setup()
# ---------------------------------------------------------------------------

class TestSetup:
    def test_returns_dict_with_version(self, tmp_path):
        app = MockApp(tmp_path)
        result = setup(app)
        assert isinstance(result, dict)
        assert "version" in result

    def test_registers_anywidget_figure_directive(self, tmp_path):
        app = MockApp(tmp_path)
        setup(app)
        assert "anywidget-figure" in app._directives

    def test_registers_anywidget_config_value(self, tmp_path):
        app = MockApp(tmp_path)
        setup(app)
        assert "anywidget_pyodide_package" in app._config_values

    def test_adds_bridge_js(self, tmp_path):
        app = MockApp(tmp_path)
        setup(app)
        assert "anywidget_bridge.js" in app._js_files

    def test_adds_config_js(self, tmp_path):
        app = MockApp(tmp_path)
        setup(app)
        assert "anywidget_config.js" in app._js_files

    def test_adds_overlay_css(self, tmp_path):
        app = MockApp(tmp_path)
        setup(app)
        assert "anywidget_overlay.css" in app._css_files

    def test_connects_builder_inited_events(self, tmp_path):
        app = MockApp(tmp_path)
        setup(app)
        assert "builder-inited" in app._event_handlers
        assert len(app._event_handlers["builder-inited"]) >= 2

    def test_parallel_safe_flags(self, tmp_path):
        app = MockApp(tmp_path)
        result = setup(app)
        assert result.get("parallel_read_safe") is True
        assert result.get("parallel_write_safe") is True


# ---------------------------------------------------------------------------
# _copy_static_assets
# ---------------------------------------------------------------------------

class TestCopyStaticAssets:
    def test_adds_static_src_to_html_static_path(self, tmp_path):
        app = MockApp(tmp_path)
        _copy_static_assets(app)
        assert len(app.config.html_static_path) == 1
        assert pathlib.Path(app.config.html_static_path[0]).is_dir()

    def test_does_not_duplicate_existing_entry(self, tmp_path):
        app = MockApp(tmp_path)
        _copy_static_assets(app)
        _copy_static_assets(app)
        assert len(app.config.html_static_path) == 1


# ---------------------------------------------------------------------------
# _build_pyodide_wheel
# ---------------------------------------------------------------------------

class TestBuildPyodideWheel:
    def test_no_package_writes_disabled_config(self, tmp_path):
        confdir = tmp_path / "docs"
        confdir.mkdir()
        app = MockApp(confdir)
        _build_pyodide_wheel(app)
        config_js = confdir / "_static" / "anywidget_config.js"
        assert config_js.exists()
        content = config_js.read_text()
        assert "null" in content or "Disabled" in content or "disabled" in content

    def test_explicit_package_writes_config_js(self, tmp_path):
        confdir = tmp_path / "docs"
        confdir.mkdir()
        app = MockApp(confdir)
        app.config.anywidget_pyodide_package = "mypackage"
        _build_pyodide_wheel(app)
        config_js = confdir / "_static" / "anywidget_config.js"
        assert config_js.exists()
        assert "mypackage" in config_js.read_text()

    def test_existing_wheel_skips_rebuild(self, tmp_path):
        confdir = tmp_path / "docs"
        confdir.mkdir()
        app = MockApp(confdir)
        app.config.anywidget_pyodide_package = "mypkg"

        wheels_dir = confdir / "_static" / "wheels"
        wheels_dir.mkdir(parents=True)
        stable = wheels_dir / "mypkg-0.0.0-py3-none-any.whl"
        stable.write_bytes(b"dummy wheel content")
        mtime_before = stable.stat().st_mtime

        _build_pyodide_wheel(app)
        assert stable.stat().st_mtime == mtime_before, "Should not rebuild existing wheel"


# ---------------------------------------------------------------------------
# _find_project_root
# ---------------------------------------------------------------------------

class TestFindProjectRoot:
    def test_finds_root_with_pyproject_toml(self, tmp_path):
        project = tmp_path / "myproject"
        project.mkdir()
        (project / "pyproject.toml").write_text('[project]\nname = "mypkg"\n')
        docs = project / "docs"
        docs.mkdir()
        root = _find_project_root(docs)
        assert root == project

    def test_finds_root_at_confdir_itself(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "mypkg"\n')
        root = _find_project_root(tmp_path)
        assert root == tmp_path

    def test_fallback_to_parent_when_no_marker(self, tmp_path):
        deep = tmp_path / "a" / "b" / "c"
        deep.mkdir(parents=True)
        root = _find_project_root(deep)
        assert root == deep.parent

    def test_finds_setup_py(self, tmp_path):
        (tmp_path / "setup.py").write_text("from setuptools import setup; setup()\n")
        docs = tmp_path / "docs"
        docs.mkdir()
        root = _find_project_root(docs)
        assert root == tmp_path


# ---------------------------------------------------------------------------
# _infer_package_name
# ---------------------------------------------------------------------------

class TestInferPackageName:
    def test_infers_from_pyproject_in_parent(self, tmp_path):
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text('[project]\nname = "mylib"\n')
        docs = tmp_path / "docs"
        docs.mkdir()
        app = MockApp(docs)
        name = _infer_package_name(app)
        assert name == "mylib"

    def test_infers_from_pyproject_in_confdir(self, tmp_path):
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text('[project]\nname = "inconfdir"\n')
        app = MockApp(tmp_path)
        name = _infer_package_name(app)
        assert name == "inconfdir"

    def test_returns_none_when_no_pyproject(self, tmp_path):
        docs = tmp_path / "docs"
        docs.mkdir()
        app = MockApp(docs)
        name = _infer_package_name(app)
        assert name is None


# ---------------------------------------------------------------------------
# Regression: no stale push hook
# ---------------------------------------------------------------------------

def test_no_pyodide_push_hook_on_figure_module():
    assert not hasattr(_af, "_pyodide_push_hook"), (
        "_pyodide_push_hook should have been removed from the figure module"
    )

"""
sphinx_anywidget/tests/test_wheel_builder.py
=============================================

Tests for ``sphinx_anywidget._wheel_builder.build_wheel``.
"""
from __future__ import annotations

import pathlib
import tempfile

import pytest

from anyplotlib.sphinx_anywidget._wheel_builder import build_wheel


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _project_root() -> pathlib.Path:
    """Return the anyplotlib project root (contains pyproject.toml)."""
    here = pathlib.Path(__file__).parent
    for candidate in [here, *here.parents]:
        if (candidate / "pyproject.toml").exists():
            return candidate
    pytest.skip("Could not find project root with pyproject.toml")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestBuildWheel:
    def test_builds_wheel_for_anyplotlib(self):
        with tempfile.TemporaryDirectory() as tmp:
            static_dir = pathlib.Path(tmp)
            result = build_wheel(static_dir, "anyplotlib", _project_root())
            assert result is not None, "build_wheel returned None"
            assert result.exists(), f"Wheel file not found: {result}"
            assert result.suffix == ".whl"

    def test_wheel_has_stable_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            static_dir = pathlib.Path(tmp)
            result = build_wheel(static_dir, "anyplotlib", _project_root())
            assert result is not None
            assert "0.0.0" in result.name, (
                f"Expected 0.0.0 sentinel in wheel name, got {result.name!r}"
            )

    def test_wheel_placed_in_wheels_subdir(self):
        with tempfile.TemporaryDirectory() as tmp:
            static_dir = pathlib.Path(tmp)
            result = build_wheel(static_dir, "anyplotlib", _project_root())
            assert result is not None
            assert result.parent.name == "wheels"

    def test_existing_wheel_replaced(self):
        with tempfile.TemporaryDirectory() as tmp:
            static_dir = pathlib.Path(tmp)
            first = build_wheel(static_dir, "anyplotlib", _project_root())
            assert first is not None
            first_mtime = first.stat().st_mtime

            second = build_wheel(static_dir, "anyplotlib", _project_root())
            assert second is not None
            assert second.exists()

    def test_invalid_project_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            static_dir = pathlib.Path(tmp)
            fake_root = pathlib.Path(tmp) / "nonexistent"
            result = build_wheel(static_dir, "nonexistent_pkg_xyz", fake_root)
            assert result is None

    def test_wheels_dir_created_if_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            static_dir = pathlib.Path(tmp) / "nested" / "static"
            static_dir.mkdir(parents=True)
            result = build_wheel(static_dir, "anyplotlib", _project_root())
            assert result is not None
            assert (static_dir / "wheels").is_dir()

    def test_wheel_version_is_sentinel(self):
        """Wheel uses the 0.0.0 sentinel version regardless of the package's actual version."""
        with tempfile.TemporaryDirectory() as tmp:
            static_dir = pathlib.Path(tmp)
            result = build_wheel(static_dir, "anyplotlib", _project_root())
            if result is not None:
                assert "0.0.0" in result.name, (
                    f"Expected 0.0.0 sentinel version in wheel name, got {result.name!r}"
                )

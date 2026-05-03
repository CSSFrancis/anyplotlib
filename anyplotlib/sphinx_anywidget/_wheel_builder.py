"""
sphinx_anywidget/_wheel_builder.py
====================================

Builds a project wheel at docs-build time so the Pyodide bridge can install
the exact library version that generated the docs — no PyPI release required.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def build_wheel(
    static_dir: Path,
    package_name: str,
    project_root: Path,
) -> "Path | None":
    """Build a pure-Python wheel into *static_dir/wheels/*.

    The wheel is renamed to ``{package_name}-0.0.0-py3-none-any.whl``.
    ``0.0.0`` is a valid PEP 440 sentinel micropip accepts for URL installs.

    Parameters
    ----------
    static_dir :
        The docs ``_static`` directory; a ``wheels/`` sub-dir is created.
    package_name :
        PyPI / importable name (e.g. ``"anyplotlib"``).
    project_root :
        Directory containing ``pyproject.toml`` / ``setup.py``.

    Returns
    -------
    Path or None
        Path to the written wheel, or *None* on failure.
    """
    wheels_dir = static_dir / "wheels"
    wheels_dir.mkdir(parents=True, exist_ok=True)

    for old in wheels_dir.glob(f"{package_name}*.whl"):
        old.unlink(missing_ok=True)

    result = subprocess.run(
        [
            sys.executable, "-m", "pip", "wheel",
            "--no-deps", "--quiet",
            "--wheel-dir", str(wheels_dir),
            str(project_root),
        ],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        print(
            f"\n[sphinx_anywidget] WARNING: wheel build failed "
            f"for {package_name!r}:\n{result.stderr}"
        )
        return None

    wheels = sorted(wheels_dir.glob(f"{package_name}*.whl"))
    if not wheels:
        print(f"\n[sphinx_anywidget] WARNING: no wheel found for {package_name!r}")
        return None

    stable = wheels_dir / f"{package_name}-0.0.0-py3-none-any.whl"
    stable.unlink(missing_ok=True)
    wheels[-1].rename(stable)
    print(f"[sphinx_anywidget] wheel → {stable}")
    return stable


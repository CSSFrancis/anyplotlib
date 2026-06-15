"""
sphinx_anywidget/_wheel_builder.py
====================================

Builds a project wheel at docs-build time so the Pyodide bridge can install
the exact library version that generated the docs — no PyPI release required.
"""

from __future__ import annotations

import re
import subprocess
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

    # PEP 427 normalises distribution names: hyphens and dots → underscores.
    normalised = re.sub(r"[-.]", "_", package_name)

    stable = wheels_dir / f"{normalised}-0.0.0-py3-none-any.whl"

    # Build into a temporary sub-directory so we never clobber the existing
    # stable wheel until we know the new build actually succeeded.
    import tempfile
    with tempfile.TemporaryDirectory(dir=wheels_dir) as tmp_str:
        tmp_dir = Path(tmp_str)
        result = subprocess.run(
            [
                "uv", "build", "--wheel",
                "--out-dir", str(tmp_dir),
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

        new_wheels = sorted(tmp_dir.glob(f"{normalised}*.whl"))
        if not new_wheels:
            print(f"\n[sphinx_anywidget] WARNING: no wheel found for {package_name!r}")
            return None

        # Build succeeded — now replace the stable wheel atomically.
        stable.unlink(missing_ok=True)
        # Remove any other stale versioned wheels before moving the new one.
        for old in wheels_dir.glob(f"{normalised}*.whl"):
            old.unlink(missing_ok=True)
        new_wheels[-1].rename(stable)
    # ASCII only: Windows consoles (cp1252) can't print '→' during builds
    print(f"[sphinx_anywidget] wheel -> {stable}")
    return stable


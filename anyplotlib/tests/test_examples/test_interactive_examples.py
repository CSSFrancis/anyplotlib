"""Smoke tests: each EM example script must import and execute without error."""
import importlib.util
import pathlib

import pytest

EXAMPLES_DIR = pathlib.Path(__file__).parents[3] / "Examples" / "Interactive"

SCRIPTS = [
    "plot_particle_picker.py",
    "plot_eels_explorer.py",
    "plot_threshold_explorer.py",
    "plot_spectra_roi_inspector.py",
]


def _exec_script(name: str) -> None:
    path = EXAMPLES_DIR / name
    mod_name = f"_smoke_ex_{path.stem}"
    spec = importlib.util.spec_from_file_location(mod_name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)


@pytest.mark.parametrize("script", SCRIPTS)
def test_example_executes(script: str) -> None:
    _exec_script(script)

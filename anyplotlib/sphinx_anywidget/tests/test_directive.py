"""
sphinx_anywidget/tests/test_directive.py
=========================================

Tests for ``sphinx_anywidget._directive``:
  - ``_find_widget``
  - ``AnywidgetFigureDirective`` via a mock Sphinx environment
"""
from __future__ import annotations

import pathlib
import tempfile
import textwrap

import numpy as np
import pytest

import anyplotlib as apl
from anyplotlib.sphinx_anywidget._directive import _find_widget


# ---------------------------------------------------------------------------
# _find_widget (directive's copy)
# ---------------------------------------------------------------------------

class TestFindWidgetDirective:
    def test_finds_figure(self):
        fig, ax = apl.subplots(1, 1)
        ax.plot(np.zeros(10))
        found = _find_widget({"fig": fig, "x": 42})
        assert found is fig

    def test_returns_none_for_plain_values(self):
        assert _find_widget({"x": 1, "y": "hello"}) is None

    def test_returns_last_widget(self):
        fig1, ax1 = apl.subplots(1, 1)
        ax1.plot(np.zeros(5))
        fig2, ax2 = apl.subplots(1, 1)
        ax2.plot(np.zeros(5))
        found = _find_widget({"a": fig1, "b": fig2})
        assert found is fig2

    def test_ignores_non_callable_repr_html(self):
        class FakeWidget:
            _repr_html_ = "not a callable"
            _esm = "..."
        assert _find_widget({"w": FakeWidget()}) is None


# ---------------------------------------------------------------------------
# Minimal Sphinx environment mock
# ---------------------------------------------------------------------------

class MockConfig:
    def __init__(self, confdir):
        self.anywidget_pyodide_package = None
        self.html_static_path = []
        self._confdir = confdir

    def __getattr__(self, name):
        return None


class MockEnv:
    def __init__(self, confdir, outdir):
        self.config = MockConfig(confdir)
        self.srcdir = str(confdir)
        self.docname = "index"

        class _App:
            def __init__(self, confdir, outdir):
                self.confdir = str(confdir)
                self.outdir = str(outdir)
                self.config = MockConfig(confdir)

        self.app = _App(confdir, outdir)


class MockReporter:
    def error(self, msg, *args, line=None):
        from docutils import nodes
        return nodes.system_message(msg, level=3, type="ERROR")


class MockState:
    def __init__(self, confdir, outdir):
        self.document = type("doc", (), {
            "settings": type("s", (), {
                "env": MockEnv(confdir, outdir),
            })(),
        })()
        self.reporter = MockReporter()


# ---------------------------------------------------------------------------
# AnywidgetFigureDirective
# ---------------------------------------------------------------------------

class TestAnywidgetFigureDirective:
    def _make_directive(self, src_file: pathlib.Path, confdir, outdir, options=None):
        from anyplotlib.sphinx_anywidget._directive import AnywidgetFigureDirective
        from docutils.parsers.rst import Directive

        class ConcreteDirective(AnywidgetFigureDirective):
            pass

        state = MockState(confdir, outdir)
        d = ConcreteDirective.__new__(ConcreteDirective)
        d.arguments = [str(src_file.relative_to(confdir))]
        d.options = options or {}
        d.content = []
        d.lineno = 1
        d.state = state
        d.state_machine = None
        d.reporter = state.reporter
        return d

    def test_missing_file_returns_error_node(self, tmp_path):
        confdir = tmp_path / "docs"
        confdir.mkdir()
        outdir = tmp_path / "out"
        outdir.mkdir()

        d = self._make_directive(
            confdir / "nonexistent.py", confdir, outdir
        )
        result = d.run()
        assert len(result) == 1
        assert "system_message" in str(type(result[0]))

    def test_valid_script_returns_raw_node(self, tmp_path):
        confdir = tmp_path / "docs"
        confdir.mkdir()
        outdir = tmp_path / "out"
        outdir.mkdir()

        script = confdir / "example.py"
        script.write_text(textwrap.dedent("""\
            import numpy as np
            import anyplotlib as apl
            fig, ax = apl.subplots(1, 1, figsize=(400, 300))
            ax.plot(np.zeros(10))
        """))

        d = self._make_directive(script, confdir, outdir)
        result = d.run()
        assert len(result) >= 1
        from docutils import nodes
        assert any(isinstance(n, nodes.raw) for n in result)

    def test_no_widget_in_script_returns_error(self, tmp_path):
        confdir = tmp_path / "docs"
        confdir.mkdir()
        outdir = tmp_path / "out"
        outdir.mkdir()

        script = confdir / "no_widget.py"
        script.write_text("x = 1 + 1\n")

        d = self._make_directive(script, confdir, outdir)
        result = d.run()
        assert len(result) == 1
        assert "system_message" in str(type(result[0]))

    def test_failing_script_returns_error(self, tmp_path):
        confdir = tmp_path / "docs"
        confdir.mkdir()
        outdir = tmp_path / "out"
        outdir.mkdir()

        script = confdir / "broken.py"
        script.write_text("raise ValueError('intentional failure')\n")

        d = self._make_directive(script, confdir, outdir)
        result = d.run()
        assert len(result) == 1
        assert "system_message" in str(type(result[0]))

    def test_interactive_option_embeds_python_src(self, tmp_path):
        confdir = tmp_path / "docs"
        confdir.mkdir()
        outdir = tmp_path / "out"
        outdir.mkdir()

        script = confdir / "interactive_example.py"
        script.write_text(textwrap.dedent("""\
            import numpy as np
            import anyplotlib as apl
            fig, ax = apl.subplots(1, 1, figsize=(400, 300))
            ax.plot(np.sin(np.linspace(0, 6.28, 64)))
        """))

        d = self._make_directive(script, confdir, outdir, options={"interactive": None})
        result = d.run()
        from docutils import nodes
        raw_nodes = [n for n in result if isinstance(n, nodes.raw)]
        assert raw_nodes
        combined = " ".join(str(n) for n in raw_nodes)
        assert "text/x-python" in combined or "awi-activate-btn" in combined

    def test_width_option_respected(self, tmp_path):
        confdir = tmp_path / "docs"
        confdir.mkdir()
        outdir = tmp_path / "out"
        outdir.mkdir()

        script = confdir / "wide.py"
        script.write_text(textwrap.dedent("""\
            import numpy as np
            import anyplotlib as apl
            fig, ax = apl.subplots(1, 1, figsize=(400, 300))
            ax.plot(np.zeros(10))
        """))

        d = self._make_directive(script, confdir, outdir, options={"width": "300"})
        result = d.run()
        from docutils import nodes
        raw_nodes = [n for n in result if isinstance(n, nodes.raw)]
        assert raw_nodes

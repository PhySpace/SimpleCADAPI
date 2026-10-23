"""A process that leaves Python callables in C++ global registries must exit cleanly.

The reactive executor registry and the sketch solver backend registry have static storage; they
are destroyed from exit(), after Py_Finalize.  Their destructors used to take the GIL
(PyThreadState_New on a finalized interpreter) and the process died with SIGSEGV (exit 139) at the
very end of a test run.  Each case runs in a fresh interpreter because only the exit matters.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest


def run_script(body: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(body)], capture_output=True, text=True, timeout=120
    )


def test_exit_with_a_python_executor_registered():
    result = run_script(
        """
        import simplecadapi._cpp as c
        c.register_executor("exit_test_op", lambda params, inputs, scalars: [])
        assert "exit_test_op" in c.global_executor_registry().operations()
        """
    )
    assert result.returncode == 0, (result.returncode, result.stderr[-400:])


def test_exit_with_a_python_sketch_backend_registered():
    result = run_script(
        """
        import simplecadapi._cpp as c

        class Backend:
            name = "exit-test"
            version = "0"
            def solve(self, sketch, options):
                raise NotImplementedError

        c.register_sketch_solver_backend(Backend())
        """
    )
    assert result.returncode == 0, (result.returncode, result.stderr[-400:])


def test_exit_with_a_ql_evidence_provider_installed():
    result = run_script(
        """
        import simplecadapi._cpp as c
        c.ql._set_evidence_provider(lambda *args: [])
        """
    )
    assert result.returncode == 0, (result.returncode, result.stderr[-400:])

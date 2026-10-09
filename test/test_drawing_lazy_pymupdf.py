"""pymupdf stays off the package import path; drawing functions name the extra."""

import builtins
import subprocess
import sys

import pytest

from simplecadapi.inspect.drawing._pymupdf import _LazyPymupdf


def test_package_import_does_not_pull_pymupdf() -> None:
    code = (
        "import sys, simplecadapi; "
        "assert 'pymupdf' not in sys.modules, 'pymupdf imported eagerly'"
    )
    subprocess.run([sys.executable, "-c", code], check=True)


def test_missing_pymupdf_names_the_drawing_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    real_import = builtins.__import__

    def poisoned(name, *args, **kwargs):
        if name == "pymupdf":
            raise ImportError(f"No module named '{name}'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", poisoned)
    with pytest.raises(ImportError, match=r"simplecadapi\[drawing\]"):
        _LazyPymupdf().Rect


def test_present_pymupdf_passes_through() -> None:
    assert callable(_LazyPymupdf().open)

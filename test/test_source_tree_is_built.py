"""A checkout is a built source tree only when the compiled module is there; the type stubs do not count.

The checkout carries `src/simplecadapi/_cpp/_native/*.pyi` (a directory).  The validation workers put the checkout's
source on the path of their subprocess only when it is built, because otherwise it shadows the installed wheel with Python
files that have no compiled module: the wheel test job of the 2.2.7 dry run failed that way.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "research" / "build123dftc"))
from b3ftc.validation import _source_tree_is_built  # noqa: E402


def make(tmp_path: Path, *names: str, stubs: bool = False) -> Path:
    cpp = tmp_path / "simplecadapi" / "_cpp"
    cpp.mkdir(parents=True)
    if stubs:
        (cpp / "_native").mkdir()
        (cpp / "_native" / "__init__.pyi").write_text("")
    for name in names:
        (cpp / name).write_bytes(b"")
    return tmp_path


def test_the_type_stub_directory_alone_is_not_a_build(tmp_path) -> None:
    assert not _source_tree_is_built(make(tmp_path, stubs=True))


def test_nothing_is_not_a_build(tmp_path) -> None:
    assert not _source_tree_is_built(make(tmp_path))


@pytest.mark.parametrize("name", ["_native.cpython-312-darwin.so", "_native.cpython-313-x86_64-linux-gnu.so", "_native.cp312-win_amd64.pyd"])
def test_the_compiled_module_is_a_build_with_or_without_stubs(tmp_path, name) -> None:
    assert _source_tree_is_built(make(tmp_path, name, stubs=True))


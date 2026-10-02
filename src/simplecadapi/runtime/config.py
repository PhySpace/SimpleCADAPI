"""The ``[tool.simplecadapi]`` table of a notebook's PEP 723 header.

The table is what makes a marimo notebook a SimpleCAD notebook::

    # /// script
    # dependencies = ["simplecadapi"]
    #
    # [tool.simplecadapi]
    # id = "flange_plate"            # default: the file name without .py
    # revision = "1.0.0"
    # tolerance_profile = "simplecad-default"
    # inputs = ["data/profile.dxf"]  # project files the product reads
    # ///

Without it the notebook runs exactly as marimo would run it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from ..artifacts.canonical import validate_logical_id, validate_revision
from ..build.dependencies import FileInput
from ._marimo import read_pyproject_from_script

_KEYS = frozenset({"id", "revision", "tolerance_profile", "inputs"})


class NotebookConfigError(ValueError):
    """The ``[tool.simplecadapi]`` table is malformed."""


@dataclass(frozen=True)
class NotebookConfig:
    """A SimpleCAD notebook: where it is and what it defines."""

    path: Path
    """The notebook file, resolved."""
    id: str
    """Definition id; the product is the top-level value with this id."""
    revision: str
    tolerance_profile: str
    inputs: tuple[FileInput, ...]
    """Project files (relative to the notebook directory) the product reads."""

    @property
    def directory(self) -> Path:
        return self.path.parent


def read_notebook_config(path: str | Path) -> NotebookConfig | None:
    """Return the config of the notebook at *path*, or ``None`` without one.

    Parsing is cached per file version, so the editor kernel may call this
    for every cell it runs.
    """

    resolved = Path(path).expanduser().resolve()
    try:
        stat = resolved.stat()
    except OSError:
        return None
    return _read_config_version(resolved, stat.st_mtime_ns, stat.st_size)


@lru_cache(maxsize=32)
def _read_config_version(path: Path, _mtime_ns: int, _size: int) -> NotebookConfig | None:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None
    header = read_pyproject_from_script(text) or {}
    tool = header.get("tool")
    table = tool.get("simplecadapi") if isinstance(tool, Mapping) else None
    if table is None:
        return None
    if not isinstance(table, Mapping):
        raise NotebookConfigError(f"{path}: [tool.simplecadapi] must be a table")
    return _parse_table(path, table)


def _parse_table(path: Path, table: Mapping[str, Any]) -> NotebookConfig:
    unknown = sorted(set(table) - _KEYS)
    if unknown:
        raise NotebookConfigError(
            f"{path}: unknown [tool.simplecadapi] keys {unknown}; "
            f"expected some of {sorted(_KEYS)}"
        )
    profile = table.get("tolerance_profile", "simplecad-default")
    if not isinstance(profile, str) or not profile:
        raise NotebookConfigError(f"{path}: tolerance_profile must be a non-empty string")
    inputs = table.get("inputs", [])
    if not isinstance(inputs, list) or not all(isinstance(item, str) for item in inputs):
        raise NotebookConfigError(f"{path}: inputs must be a list of relative paths")
    return NotebookConfig(
        path=path,
        id=validate_logical_id(table.get("id", path.stem), "/tool/simplecadapi/id"),
        revision=validate_revision(
            table.get("revision", "1.0.0"), "/tool/simplecadapi/revision"
        ),
        tolerance_profile=profile,
        inputs=tuple(FileInput(item) for item in inputs),
    )


__all__ = ["NotebookConfig", "NotebookConfigError", "read_notebook_config"]

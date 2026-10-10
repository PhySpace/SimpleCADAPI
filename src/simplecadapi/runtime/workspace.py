"""A workspace: a directory of SimpleCAD notebooks.

There is no manifest and no layout to adopt.  A workspace is any directory
tree; its models are the notebooks whose PEP 723 header carries
``[tool.simplecadapi]`` (:mod:`.config`), wherever they are.  Plain modules,
verification scripts and generated output are not notebooks and are never
listed.  What :func:`scan_workspace` reports is read from the files alone:

* the notebook's id and revision (the header);
* ``kind`` — ``"assembly"`` if a cell builds an assembly or calls
  :func:`~.runner.use`, else ``"part"``;
* ``uses`` — the notebooks it runs with ``use("<literal path>")``, so a
  front end can order and refresh a product's parts;
* the feature tree (:func:`list_features`, the ``# ---- feature: ... ----``
  cell headers of the feature tree convention) and the parameters
  (:func:`~.params.list_parameters`).
"""

from __future__ import annotations

import ast
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ._marimo import parse_notebook
from .cells import cell_keys
from .config import NotebookConfigError, read_notebook_config
from .params import list_parameters

_FEATURE = re.compile(
    r"^#\s*-{2,}\s*feature:\s*(?P<slug>[^\s(]+)\s*(?:\((?P<spec>[^)]*)\))?\s*-*\s*$",
    re.MULTILINE,
)
_SKIPPED = frozenset({"node_modules", "venv", "site-packages", "build", "dist"})
_ASSEMBLY_CALLS = frozenset({"make_assembly_rassembly", "Assembly", "assemble", "use"})


@dataclass(frozen=True)
class FeatureSpec:
    """One ``# ---- feature: <slug> (<role>, ...) ----`` cell header."""

    slug: str
    role: str
    """``build``, ``add``, ``subtract``, ... ``""`` if the header gives none."""
    tags: tuple[tuple[str, str], ...]
    """The ``key=value`` annotations, e.g. ``("profile", "sketch")``."""
    cell: str
    """Key of the cell the header opens."""
    line: int
    """Line of the header within the cell's code, 1-based."""

    def to_dict(self) -> dict[str, Any]:
        return {
            "slug": self.slug,
            "role": self.role,
            "tags": dict(self.tags),
            "cell": self.cell,
            "line": self.line,
        }


@dataclass(frozen=True)
class NotebookEntry:
    path: str
    """Relative to the workspace root, POSIX separators."""
    id: str
    revision: str
    kind: str
    """``"part"`` or ``"assembly"``."""
    uses: tuple[str, ...]
    """Notebooks run with ``use("...")`` in a literal path, workspace-relative."""
    error: str | None = None
    """Why the header could not be read, if it could not."""

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "id": self.id,
            "revision": self.revision,
            "kind": self.kind,
            "uses": list(self.uses),
            "error": self.error,
        }


def scan_workspace(root: str | Path) -> list[NotebookEntry]:
    """Return the SimpleCAD notebooks under *root*, sorted by path."""

    base = Path(root).expanduser().resolve()
    entries: list[NotebookEntry] = []
    for directory, subdirectories, files in os.walk(base):
        subdirectories[:] = sorted(
            name
            for name in subdirectories
            if not name.startswith((".", "_")) and name not in _SKIPPED
        )
        for name in sorted(files):
            if not name.endswith(".py") or name.startswith("_"):
                continue
            path = Path(directory) / name
            entry = _entry(base, path)
            if entry is not None:
                entries.append(entry)
    return sorted(entries, key=lambda entry: entry.path)


def _entry(base: Path, path: Path) -> NotebookEntry | None:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None
    if "tool.simplecadapi" not in text:  # cheap filter before parsing the header
        return None
    relative = path.relative_to(base).as_posix()
    try:
        config = read_notebook_config(path)
    except NotebookConfigError as error:
        return NotebookEntry(relative, path.stem, "", "part", (), error=str(error))
    if config is None:
        return None
    kind, uses = _structure(base, path, text)
    return NotebookEntry(relative, config.id, config.revision, kind, uses)


def _structure(base: Path, path: Path, text: str) -> tuple[str, tuple[str, ...]]:
    try:
        notebook = parse_notebook(text)
    except SyntaxError:
        notebook = None
    codes = [cell.code for cell in notebook.cells] if notebook is not None else []
    assembly = False
    uses: list[str] = []
    for code in codes:
        try:
            tree = ast.parse(code)
        except (SyntaxError, ValueError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = _callee(node.func)
                if name in _ASSEMBLY_CALLS:
                    assembly = True
                if name == "use" and node.args:
                    target = node.args[0]
                    if isinstance(target, ast.Constant) and isinstance(target.value, str):
                        resolved = (path.parent / target.value).resolve()
                        try:
                            uses.append(resolved.relative_to(base).as_posix())
                        except ValueError:
                            pass  # a notebook outside the workspace
    return ("assembly" if assembly else "part"), tuple(dict.fromkeys(uses))


def _callee(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def list_features(path: str | Path) -> list[FeatureSpec]:
    """Return the feature headers of the notebook at *path*, in cell order."""

    try:
        notebook = parse_notebook(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, SyntaxError):
        return []
    if notebook is None:
        return []
    cells = list(notebook.cells)
    keys = cell_keys(cell.code for cell in cells)
    features: list[FeatureSpec] = []
    for cell, key in zip(cells, keys):
        features.extend(features_in_cell(cell.code, key))
    return features


def features_in_cell(code: str, key: str = "") -> list[FeatureSpec]:
    features: list[FeatureSpec] = []
    for match in _FEATURE.finditer(code):
        role = ""
        tags: list[tuple[str, str]] = []
        for part in (match.group("spec") or "").split(","):
            part = part.strip()
            if not part:
                continue
            name, separator, value = part.partition("=")
            if separator:
                tags.append((name.strip(), value.strip()))
            elif not role:
                role = part
        features.append(
            FeatureSpec(
                slug=match.group("slug"),
                role=role,
                tags=tuple(tags),
                cell=key,
                line=code.count("\n", 0, match.start()) + 1,
            )
        )
    return features


def describe_notebook(path: str | Path) -> dict[str, Any]:
    """Features and parameters of one notebook, as plain data."""

    return {
        "features": [feature.to_dict() for feature in list_features(path)],
        "parameters": [spec.to_dict() for spec in list_parameters(path)],
    }


__all__ = [
    "FeatureSpec",
    "NotebookEntry",
    "describe_notebook",
    "features_in_cell",
    "list_features",
    "scan_workspace",
]

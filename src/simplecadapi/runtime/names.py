"""Variable-level dependencies on local modules.

``from lib.dims import A`` depends on what ``A`` is, not on every other name
in ``lib/dims.py``.  :func:`definition_digest` digests the definition of one
top-level name together with every definition it reads, in its own module and
through ``from m import x`` into other local modules.  Comments and
formatting do not count: the digest is over the syntax tree.

It answers only what it can prove.  A module with a statement that can do
more than define a name (a call, a loop, a conditional import, an augmented
assignment), a star import, a name defined twice, a plain ``import m`` of a
local module that the definition reads, or a name the module does not
define: the digest is ``None``, and the caller depends on the whole file as
before.  Never stale, at worst coarse.
"""

from __future__ import annotations

import ast
import hashlib
import json
import threading
from dataclasses import dataclass
from pathlib import Path

from .deps import NameDep, _absolute, _loaded_names_of, _module_files, file_digest


@dataclass(frozen=True)
class _Module:
    name: str
    defs: dict[str, ast.stmt]
    """Top-level name -> the statement that defines it."""
    imports: dict[str, tuple[str, str]]
    """Name bound by ``from m import x [as y]`` of a local module -> (m, x)."""
    local_plain: frozenset[str]
    """Names bound by ``import m`` of a local module."""


def definition_digest(root: Path, module: str, name: str) -> str | None:
    """The digest of *name* defined in local *module* under *root*, or ``None``."""

    parsed: dict[str, _Module | None] = {}

    def load(mod: str) -> _Module | None:
        if mod not in parsed:
            parsed[mod] = _parse(root, mod)
        return parsed[mod]

    payload: dict[str, str] = {}
    packages: dict[str, str | None] = {}
    pending = [(module, name)]
    while pending:
        mod, wanted = pending.pop()
        key = f"{mod}:{wanted}"
        if key in payload:
            continue
        info = load(mod)
        if info is None:
            return None
        # Importing the module runs the packages on the way.
        for package, path in _module_files(root, mod)[:-1]:
            packages[f"pkg:{package}"] = file_digest(path)
        if wanted in info.imports:  # a re-export
            payload[key] = f"-> {info.imports[wanted][0]}:{info.imports[wanted][1]}"
            pending.append(info.imports[wanted])
            continue
        statement = info.defs.get(wanted)
        if statement is None:
            return None
        payload[key] = ast.dump(statement, include_attributes=False)
        for read in _loaded_names_of(statement):
            if read in info.local_plain:
                return None
            if read in info.imports or read in info.defs:
                pending.append((mod, read))
    payload.update({key: str(value) for key, value in packages.items()})
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


def _is_local(root: Path, module: str) -> bool:
    """Whether *module* itself (not only a package on the way) is a local file."""

    files = _module_files(root, module)
    return bool(files) and files[-1][0] == module


_parsed: dict[tuple[str, str, str | None], _Module | None] = {}
_parsed_lock = threading.Lock()


def _parse(root: Path, module: str) -> _Module | None:
    """:func:`_analyse`, remembered per file content: the kernel asks for the
    digest of every cell it runs."""

    files = _module_files(root, module)
    if not files or files[-1][0] != module:
        return None
    key = (str(root), module, file_digest(files[-1][1]))
    with _parsed_lock:
        if key in _parsed:
            return _parsed[key]
    result = _analyse(root, module, files[-1][1])
    with _parsed_lock:
        if len(_parsed) > 512:
            _parsed.clear()
        _parsed[key] = result
    return result


def _analyse(root: Path, module: str, path: Path) -> _Module | None:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, SyntaxError, ValueError):
        return None
    package = module if path.name == "__init__.py" else module.rpartition(".")[0]
    defs: dict[str, ast.stmt] = {}
    imports: dict[str, tuple[str, str]] = {}
    plain: set[str] = set()

    def define(name: str, statement: ast.stmt) -> bool:
        if name in defs or name in imports or name in plain:
            return False  # rebound: which value a reader sees depends on order
        defs[name] = statement
        return True

    for statement in tree.body:
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if not define(statement.name, statement):
                return None
        elif isinstance(statement, ast.Assign) and all(
            isinstance(target, ast.Name) for target in statement.targets
        ):
            for target in statement.targets:
                assert isinstance(target, ast.Name)
                if not define(target.id, statement):
                    return None
        elif isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
            if statement.value is not None and not define(statement.target.id, statement):
                return None
        elif isinstance(statement, ast.Import):
            for alias in statement.names:
                if _is_local(root, alias.name):
                    bound = alias.asname or alias.name.split(".")[0]
                    if bound in defs or bound in imports:
                        return None
                    plain.add(bound)
        elif isinstance(statement, ast.ImportFrom):
            base = _absolute(statement.module, statement.level, package)
            if base is None:
                return None
            for alias in statement.names:
                if alias.name == "*":
                    if _is_local(root, base):
                        return None
                    continue
                bound = alias.asname or alias.name
                if bound in defs or bound in imports or bound in plain:
                    return None
                if _is_local(root, f"{base}.{alias.name}"):
                    plain.add(bound)  # a submodule: its content is a whole file
                elif _is_local(root, base):
                    imports[bound] = (base, alias.name)
        elif (
            isinstance(statement, ast.Expr)
            and isinstance(statement.value, ast.Constant)
            and isinstance(statement.value.value, str)
        ):
            continue  # a docstring
        else:
            return None
    return _Module(module, defs, imports, frozenset(plain))


def names_tag(root: Path, names: frozenset[NameDep]) -> tuple[str, frozenset[Path]]:
    """The digest of what *names* are now, and the files to depend on instead
    for those that cannot be digested."""

    parts: dict[str, str] = {}
    files: set[Path] = set()
    for dep in sorted(names, key=lambda item: (item.module, item.name)):
        digest = definition_digest(root, dep.module, dep.name)
        if digest is None:
            files |= dep.fallback
        else:
            parts[f"{dep.module}:{dep.name}"] = digest
    if not parts:
        return "", frozenset(files)
    encoded = json.dumps(parts, sort_keys=True).encode("utf-8")
    return "n" + hashlib.sha256(encoded).hexdigest()[:12], frozenset(files)

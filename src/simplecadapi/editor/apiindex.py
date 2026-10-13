"""The SDK's public API as plain data, for the editor's code completion.

The cell editor completes ``scad.<name>``, and a call's parameters as ``name=`` placeholders, from
this index.  It is read from the live package (``inspect``), so it is always the API of the
version that is running and cannot drift from the code.  Namespaces are the places a notebook
reaches names through: ``scad`` (the package), ``scad.ql`` and ``scad.std.<module>``.
"""

from __future__ import annotations

import functools
import inspect
import types
from typing import Any

import simplecadapi

_KINDS = {
    inspect.Parameter.POSITIONAL_ONLY: "p",
    inspect.Parameter.POSITIONAL_OR_KEYWORD: "",
    inspect.Parameter.KEYWORD_ONLY: "",
    inspect.Parameter.VAR_POSITIONAL: "a",
    inspect.Parameter.VAR_KEYWORD: "w",
}
_DOC_LIMIT = 240
_DEFAULT_LIMIT = 40


def _summary(obj: Any) -> str:
    """The first paragraph of the docstring, on one line."""

    doc = inspect.getdoc(obj) or ""
    first = doc.strip().split("\n\n", 1)[0]
    text = " ".join(first.split())
    return text if len(text) <= _DOC_LIMIT else text[: _DOC_LIMIT - 1].rstrip() + "…"


def _parameters(obj: Any) -> list[dict[str, Any]] | None:
    try:
        signature = inspect.signature(obj)
    except (TypeError, ValueError):
        return None
    rows: list[dict[str, Any]] = []
    for parameter in signature.parameters.values():
        if parameter.name == "self" or parameter.name.startswith("_"):
            continue
        required = parameter.default is inspect.Parameter.empty and parameter.kind in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.KEYWORD_ONLY,
        )
        row: dict[str, Any] = {"n": parameter.name, "r": required, "k": _KINDS[parameter.kind]}
        if parameter.default is not inspect.Parameter.empty and not str(parameter.default).startswith("<"):
            text = repr(parameter.default)
            row["d"] = text if len(text) <= _DEFAULT_LIMIT else text[: _DEFAULT_LIMIT - 1] + "…"
        rows.append(row)
    return rows


def _entry(name: str, obj: Any) -> dict[str, Any] | None:
    if inspect.isclass(obj):
        kind = "c"
    elif inspect.isfunction(obj) or inspect.isbuiltin(obj):
        kind = "f"
    else:
        return None
    parameters = _parameters(obj)
    if parameters is None:
        return None
    return {"n": name, "k": kind, "p": parameters, "d": _summary(obj)}


def _ours(obj: Any) -> bool:
    """Defined by the SDK itself, not a typing helper or another library re-exported."""

    module = getattr(obj, "__module__", "") or ""
    return module == "simplecadapi" or module.startswith("simplecadapi.")


def _entries(module: types.ModuleType, names: list[str] | None = None, *, own: bool = False) -> list[dict[str, Any]]:
    """Entries for the callables of *module*; with *own*, only those defined in that module (not re-exports)."""

    rows = []
    for name in sorted(names if names is not None else dir(module)):
        if name.startswith("_"):
            continue
        obj = getattr(module, name, None)
        if obj is None or isinstance(obj, types.ModuleType) or not _ours(obj):
            continue
        if own and not (getattr(obj, "__module__", "") or "").startswith(module.__name__):
            continue
        row = _entry(name, obj)
        if row is not None:
            rows.append(row)
    return rows


@functools.lru_cache(maxsize=1)
def build_index() -> dict[str, Any]:
    """``{"namespaces": {path: [entry]}, "submodules": {path: [name]}}``.

    An entry is ``{"n": name, "k": "f"|"c", "p": [parameter], "d": summary}``; a parameter is
    ``{"n": name, "r": required, "k": "p"|"a"|"w"|"", "d"?: default}`` (``p`` positional only,
    ``a`` the ``*args`` one, ``w`` the ``**kwargs`` one).
    """

    from simplecadapi import ql, std

    namespaces: dict[str, list[dict[str, Any]]] = {
        "scad": _entries(simplecadapi, list(getattr(simplecadapi, "__all__", dir(simplecadapi)))),
        "scad.ql": _entries(ql, own=True),
    }
    std_modules = sorted(
        name for name in dir(std) if not name.startswith("_") and isinstance(getattr(std, name), types.ModuleType)
    )
    for name in std_modules:
        module = getattr(std, name)
        namespaces[f"scad.std.{name}"] = _entries(module, list(getattr(module, "__all__", dir(module))), own=True)
    submodules = {"scad": ["ql", "std"], "scad.std": std_modules}
    return {"version": getattr(simplecadapi, "__version__", ""), "namespaces": namespaces, "submodules": submodules}

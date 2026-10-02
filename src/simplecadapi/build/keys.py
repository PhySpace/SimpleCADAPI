"""Build identity helpers: generator profile, project root, canonical values."""

from __future__ import annotations

import importlib.metadata
import inspect
import math
import platform
import sys
from dataclasses import fields, is_dataclass
from enum import Enum
from pathlib import Path
from types import CodeType
from typing import Any, Callable, Mapping

from ..artifacts.canonical import ArtifactValidationError, sha256_bytes
from ..params.expr import Const, Expr, Var
from ..recording.source_mapping import resolve_source

SEMANTIC_REGISTRY_VERSION = "simplecad-operations-2.0"


def _qualified_type(value: Any) -> str:
    value_type = type(value)
    return f"{value_type.__module__}.{value_type.__qualname__}"


def _expression_snapshot(value: Const | Var | Expr, path: str, active: set[int]) -> Any:
    if isinstance(value, Const):
        return {
            "kind": "const",
            "value": normalize_build_value(value.value, path + "/value", active),
        }
    if isinstance(value, Var):
        return {
            "kind": "var",
            "name": value.name,
            "default": normalize_build_value(value.default, path + "/default", active),
            "comment": value.comment,
            "tolerance": normalize_build_value(
                value.tolerance, path + "/tolerance", active
            ),
            "unit": normalize_build_value(value.unit, path + "/unit", active),
            "tolerance_unit": normalize_build_value(
                value.tolerance_unit, path + "/tolerance_unit", active
            ),
        }
    marker = id(value)
    if marker in active:
        raise ArtifactValidationError("cycle_invalid", path, "cyclic expression")
    active.add(marker)
    try:
        return {
            "kind": "expr",
            "op": value.op,
            "args": [
                _expression_snapshot(item, f"{path}/args/{index}", active)
                for index, item in enumerate(value.args)
            ],
        }
    finally:
        active.remove(marker)


def normalize_build_value(
    value: Any,
    path: str = "/arguments",
    active: set[int] | None = None,
) -> Any:
    """Normalize one supported builder argument without repr-based fallbacks."""

    active = set() if active is None else active
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, int):
        if abs(value) > 9_007_199_254_740_991:
            raise ArtifactValidationError(
                "number_invalid", path, "integer exceeds JSON safe range"
            )
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ArtifactValidationError(
                "number_invalid", path, "number must be finite"
            )
        return value
    if isinstance(value, bytes):
        return {
            "$type": "bytes",
            "byte_length": len(value),
            "sha256": sha256_bytes(value),
        }
    if isinstance(value, (Const, Var, Expr)):
        return {
            "$type": "expression",
            "value": _expression_snapshot(value, path, active),
        }
    if isinstance(value, Enum):
        return {
            "$type": "enum",
            "class": _qualified_type(value),
            "value": normalize_build_value(value.value, path + "/value", active),
        }
    if callable(value) or inspect.isgenerator(value):
        raise ArtifactValidationError(
            "build_argument_invalid",
            path,
            f"unsupported runtime value: {_qualified_type(value)}",
        )
    value_type = type(value)
    if value_type.__module__.startswith("OCP") or hasattr(value, "wrapped"):
        raise ArtifactValidationError(
            "build_argument_invalid",
            path,
            "OCP and topology runtime handles are forbidden",
        )

    marker = id(value)
    if isinstance(value, (list, tuple, Mapping)) or is_dataclass(value):
        if marker in active:
            raise ArtifactValidationError(
                "cycle_invalid", path, "cyclic builder arguments are forbidden"
            )
        active.add(marker)
        try:
            if isinstance(value, list):
                return {
                    "$type": "list",
                    "items": [
                        normalize_build_value(item, f"{path}/{index}", active)
                        for index, item in enumerate(value)
                    ],
                }
            if isinstance(value, tuple):
                return {
                    "$type": "tuple",
                    "items": [
                        normalize_build_value(item, f"{path}/{index}", active)
                        for index, item in enumerate(value)
                    ],
                }
            if isinstance(value, Mapping):
                normalized: dict[str, Any] = {}
                for key, item in value.items():
                    if not isinstance(key, str):
                        raise ArtifactValidationError(
                            "build_argument_invalid",
                            path,
                            "mapping keys must be strings",
                        )
                    normalized[key] = normalize_build_value(
                        item,
                        f"{path}/{key.replace('~', '~0').replace('/', '~1')}",
                        active,
                    )
                return {"$type": "mapping", "items": normalized}
            return {
                "$type": "dataclass",
                "class": _qualified_type(value),
                "fields": {
                    field.name: normalize_build_value(
                        getattr(value, field.name), f"{path}/{field.name}", active
                    )
                    for field in fields(value)
                    if not field.name.startswith("_")
                },
            }
        finally:
            active.remove(marker)
    raise ArtifactValidationError(
        "build_argument_invalid",
        path,
        f"unsupported canonical value: {_qualified_type(value)}",
    )


def infer_project_root(
    function: Callable[..., Any], explicit: str | Path | None = None
) -> Path:
    """Resolve the anchor directory for a builder (file inputs, source paths).

    Default anchor is the directory containing the builder's source file, so
    a standalone source runs anywhere. An explicit ``project_root`` relocates
    the anchor and must contain the source.
    """

    # A builder defined in a notebook cell compiles under a temporary name;
    # its source file is the notebook.
    code = getattr(function, "__code__", None)
    cell = (
        resolve_source(code.co_filename, code.co_firstlineno)
        if isinstance(code, CodeType)
        else None
    )
    source_name = (
        str(cell.path)
        if cell is not None
        else inspect.getsourcefile(function) or inspect.getfile(function)
    )
    if not source_name or source_name.startswith("<"):
        raise ArtifactValidationError(
            "source_unavailable",
            "/builder/source",
            "builder source file is unavailable",
        )
    source_path = Path(source_name).expanduser().resolve()
    if explicit is not None:
        root = Path(explicit).expanduser().resolve()
        try:
            source_path.relative_to(root)
        except ValueError as exc:
            raise ArtifactValidationError(
                "source_unsafe",
                "/builder/source",
                "builder source is outside project root",
            ) from exc
        return root
    return source_path.parent


def generator_profile() -> Mapping[str, str]:
    def version(distribution: str, fallback: str) -> str:
        try:
            return importlib.metadata.version(distribution)
        except importlib.metadata.PackageNotFoundError:
            return fallback

    return {
        "simplecadapi_version": version("simplecadapi", "0.0.0+local"),
        "ocp_version": version("cadquery-ocp", "0.0.0+unknown"),
        "python_abi": f"cp{sys.version_info.major}{sys.version_info.minor}",
        "platform_tag": f"{platform.system().lower()}-{platform.machine().lower()}",
        "semantic_registry_version": SEMANTIC_REGISTRY_VERSION,
    }


__all__ = [
    "SEMANTIC_REGISTRY_VERSION",
    "generator_profile",
    "infer_project_root",
    "normalize_build_value",
]

"""Canonical encoding, identities, paths, and resource limits for product artifacts."""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from ..errors import SimpleCADMessageError
from ..scene.canonical import canonical_json_bytes, parse_canonical_json, parse_strict_json

ARTIFACT_SCHEMA_VERSION = "2.0"
PART_DEFINITION_PROFILE = "simplecad-part-definition-2"
ASSEMBLY_DEFINITION_PROFILE = "simplecad-assembly-definition-2"
SOLID_EVALUATOR_PROFILE = "ocp-evaluated-solid-1"
TOPOLOGY_SNAPSHOT_PROFILE = "ocp-stable-topology-4"
_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,255}$")
_HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_REVISION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,127}$")


@dataclass(frozen=True, slots=True)
class ArtifactLimits:
    max_json_bytes: int = 16 * 1024 * 1024
    max_blob_bytes: int = 512 * 1024 * 1024
    max_total_bytes: int = 2 * 1024 * 1024 * 1024
    max_connectors: int = 100_000
    max_definitions: int = 25_000
    max_instances: int = 100_000
    max_relations: int = 100_000
    max_nested_depth: int = 128
    max_file_inputs: int = 1_024
    max_file_input_bytes: int = 512 * 1024 * 1024
    max_total_file_input_bytes: int = 2 * 1024 * 1024 * 1024


DEFAULT_ARTIFACT_LIMITS = ArtifactLimits()


class ArtifactValidationError(SimpleCADMessageError):
    """Deterministic artifact validation failure with a typed reason and path."""

    operation = "artifact_validation"

    def __init__(self, reason: str, path: str, message: str) -> None:
        self.reason = str(reason)
        self.path = path if path.startswith("/") else "/" + path
        self.message = str(message)
        super().__init__(f"{self.reason} at {self.path}: {self.message}")
        # super chain overwrites .message with the combined display string;
        # programmatic consumers read the raw message.
        self.message = str(message)


def sha256_bytes(data: bytes | bytearray | memoryview) -> str:
    return "sha256:" + hashlib.sha256(bytes(data)).hexdigest()


def validate_hash(value: Any, path: str) -> str:
    if not isinstance(value, str) or _HASH_RE.fullmatch(value) is None:
        raise ArtifactValidationError("hash_invalid", path, "expected sha256:<64 lowercase hex>")
    return value


def validate_logical_id(value: Any, path: str) -> str:
    if not isinstance(value, str) or _ID_RE.fullmatch(value) is None:
        raise ArtifactValidationError(
            "logical_id_invalid",
            path,
            "must start with a letter and contain only letters, digits, underscore, dash, dot, or colon",
        )
    return value


def validate_revision(value: Any, path: str = "/revision") -> str:
    if not isinstance(value, str) or _REVISION_RE.fullmatch(value) is None:
        raise ArtifactValidationError("revision_invalid", path, "revision is not a valid stable token")
    return value


def validate_relative_path(value: Any, path: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not value and not allow_empty):
        raise ArtifactValidationError("path_invalid", path, "expected a non-empty relative POSIX path")
    try:
        value.encode("ascii")
    except UnicodeEncodeError as exc:
        raise ArtifactValidationError("path_invalid", path, "artifact paths must be ASCII") from exc
    pure = PurePosixPath(value)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise ArtifactValidationError("path_invalid", path, "path must be normalized and project-relative")
    if "\\" in value or pure.as_posix() != value:
        raise ArtifactValidationError("path_invalid", path, "path must use normalized POSIX separators")
    return value


def resolve_project_path(project_root: Path, relative: str, path: str = "/path") -> Path:
    validate_relative_path(relative, path)
    root = project_root.expanduser().resolve()
    candidate = root.joinpath(*PurePosixPath(relative).parts)
    try:
        resolved = candidate.resolve(strict=False)
    except OSError as exc:
        raise ArtifactValidationError("path_invalid", path, str(exc)) from exc
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ArtifactValidationError("file_input_unsafe", path, "path resolves outside project root") from exc
    return resolved


def validate_json_value(value: Any, path: str = "") -> None:
    """Reject cycles, unknown runtime objects, non-finite values, and unsafe integers."""

    active: set[int] = set()

    def visit(item: Any, pointer: str) -> None:
        if item is None or isinstance(item, (str, bool)):
            return
        if isinstance(item, int):
            if abs(item) > 9_007_199_254_740_991:
                raise ArtifactValidationError("number_invalid", pointer, "integer exceeds JSON safe range")
            return
        if isinstance(item, float):
            if not math.isfinite(item):
                raise ArtifactValidationError("number_invalid", pointer, "number must be finite")
            return
        marker = id(item)
        if marker in active:
            raise ArtifactValidationError("cycle_invalid", pointer, "cyclic containers are forbidden")
        if isinstance(item, (list, tuple)):
            active.add(marker)
            try:
                for index, child in enumerate(item):
                    visit(child, f"{pointer}/{index}")
            finally:
                active.remove(marker)
            return
        if isinstance(item, Mapping):
            active.add(marker)
            try:
                for key, child in item.items():
                    if not isinstance(key, str):
                        raise ArtifactValidationError("type_invalid", pointer, "object keys must be strings")
                    visit(child, f"{pointer}/{key}")
            finally:
                active.remove(marker)
            return
        raise ArtifactValidationError(
            "type_invalid", pointer or "/", f"unsupported canonical value: {type(item).__name__}"
        )

    visit(value, path)


def _native_canonical() -> Any:
    """The C++ canonical-JSON walker on the native backend, else None.

    It returns None for any value outside its domain (the Python path below then raises the same
    errors it always did), so the result is byte-identical by construction.
    """

    try:
        import simplecadapi._cpp as native
    except ImportError:  # pragma: no cover - the C++ module is a hard dependency
        return None
    return native if hasattr(native, "canonical_hash") else None


_NATIVE = _native_canonical()


def canonical_bytes(value: Any) -> bytes:
    if _NATIVE is not None:
        fast = _NATIVE.canonical_bytes(value)
        if fast is not None:
            return fast
    validate_json_value(value)
    return canonical_json_bytes(value)


def content_hash(value: Mapping[str, Any], *, omit: tuple[str, ...] = ("content_hash",)) -> str:
    if _NATIVE is not None:
        fast = _NATIVE.canonical_hash(value, omit)
        if fast is not None:
            return fast
    draft = {key: item for key, item in value.items() if key not in omit}
    return sha256_bytes(canonical_bytes(draft))


__all__ = [
    "ARTIFACT_SCHEMA_VERSION",
    "ASSEMBLY_DEFINITION_PROFILE",
    "ArtifactLimits",
    "ArtifactValidationError",
    "DEFAULT_ARTIFACT_LIMITS",
    "PART_DEFINITION_PROFILE",
    "SOLID_EVALUATOR_PROFILE",
    "TOPOLOGY_SNAPSHOT_PROFILE",
    "canonical_bytes",
    "content_hash",
    "parse_canonical_json",
    "parse_strict_json",
    "resolve_project_path",
    "sha256_bytes",
    "validate_hash",
    "validate_json_value",
    "validate_logical_id",
    "validate_relative_path",
    "validate_revision",
]

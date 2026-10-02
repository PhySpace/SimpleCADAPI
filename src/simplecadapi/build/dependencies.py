"""Typed, project-relative file dependencies for reproducible builders."""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .._internal.os_compat import with_binary_flag
from ..artifacts.canonical import (
    DEFAULT_ARTIFACT_LIMITS,
    ArtifactLimits,
    ArtifactValidationError,
    resolve_project_path,
    sha256_bytes,
    validate_relative_path,
)
from ..artifacts.references import FileInputSnapshot


@dataclass(frozen=True, slots=True)
class FileInput:
    """A declared external file whose bytes are recorded in the Part definition."""

    path: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "path",
            validate_relative_path(self.path, "/file_input/path"),
        )


def file_input(path: str) -> FileInput:
    """Declare one project-relative regular file as a builder dependency."""

    return FileInput(path=path)


def read_stable_file(
    path: Path,
    *,
    max_bytes: int,
    error_path: str,
) -> bytes:
    """Read a regular file once and reject observable concurrent mutation."""

    flags = with_binary_flag(os.O_RDONLY)
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except FileNotFoundError as exc:
        raise ArtifactValidationError(
            "file_input_missing", error_path, "file does not exist"
        ) from exc
    except OSError as exc:
        raise ArtifactValidationError(
            "file_input_unreadable", error_path, str(exc)
        ) from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise ArtifactValidationError(
                "file_input_unsafe", error_path, "input must be a regular file"
            )
        if before.st_size > max_bytes:
            raise ArtifactValidationError(
                "resource_limit", error_path, "file exceeds byte limit"
            )
        chunks: list[bytes] = []
        remaining = max_bytes + 1
        while remaining > 0:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)
        if len(payload) > max_bytes:
            raise ArtifactValidationError(
                "resource_limit", error_path, "file exceeds byte limit"
            )
        after = os.fstat(descriptor)
        identity_before = (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
        )
        identity_after = (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        )
        if identity_before != identity_after or len(payload) != after.st_size:
            raise ArtifactValidationError(
                "file_input_changed", error_path, "file changed while being read"
            )
        return payload
    except OSError as exc:
        raise ArtifactValidationError(
            "file_input_unreadable", error_path, str(exc)
        ) from exc
    finally:
        os.close(descriptor)


def snapshot_file_inputs(
    inputs: Iterable[FileInput],
    *,
    project_root: Path,
    limits: ArtifactLimits = DEFAULT_ARTIFACT_LIMITS,
) -> tuple[FileInputSnapshot, ...]:
    """Hash declared files with deterministic ordering and resource limits."""

    declared = tuple(inputs)
    if len(declared) > limits.max_file_inputs:
        raise ArtifactValidationError(
            "resource_limit", "/file_inputs", "file input count exceeds limit"
        )
    if not all(isinstance(item, FileInput) for item in declared):
        raise TypeError("inputs must contain values returned by file_input()")
    paths = [item.path for item in declared]
    if len(paths) != len(set(paths)):
        raise ArtifactValidationError(
            "file_input_invalid", "/file_inputs", "file input paths must be unique"
        )

    snapshots: list[FileInputSnapshot] = []
    total = 0
    for index, item in enumerate(
        sorted(declared, key=lambda value: value.path.encode("utf-8"))
    ):
        resolved = resolve_project_path(
            project_root,
            item.path,
            f"/file_inputs/{index}/path",
        )
        try:
            resolved = resolved.resolve(strict=True)
        except FileNotFoundError as exc:
            raise ArtifactValidationError(
                "file_input_missing",
                f"/file_inputs/{index}/path",
                "file does not exist",
            ) from exc
        try:
            resolved.relative_to(project_root.resolve())
        except ValueError as exc:
            raise ArtifactValidationError(
                "file_input_unsafe",
                f"/file_inputs/{index}/path",
                "path resolves outside project root",
            ) from exc
        payload = read_stable_file(
            resolved,
            max_bytes=limits.max_file_input_bytes,
            error_path=f"/file_inputs/{index}",
        )
        total += len(payload)
        if total > limits.max_total_file_input_bytes:
            raise ArtifactValidationError(
                "resource_limit",
                "/file_inputs",
                "aggregate file input bytes exceed limit",
            )
        snapshots.append(
            FileInputSnapshot(
                path=item.path,
                byte_length=len(payload),
                sha256=sha256_bytes(payload),
            )
        )
    return tuple(snapshots)


__all__ = ["FileInput", "file_input", "read_stable_file", "snapshot_file_inputs"]

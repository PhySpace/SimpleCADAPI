"""Deterministic BRep encoding and exact-solid validation, through the C++ kernel.

The encoding is the kernel's ``canonical_brep_bytes`` (BinTools V4 without triangulation, taken to the
smallest member of the re-encoding orbit); decoding checks the result is one valid solid.
"""

from __future__ import annotations

import hashlib
from typing import Any

import simplecadapi._cpp as _n

from .canonical import ArtifactValidationError


def _sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def write_brep_bytes(value: Any) -> bytes:
    if not isinstance(value, _n.AnyShape):
        raise TypeError("value must be a Solid")
    payload = _n.canonical_brep_bytes(value)
    if not payload:
        raise ArtifactValidationError("brep_invalid", "/body", "BRep writer returned empty bytes")
    return payload


def brep_hash(value: Any) -> str:
    return _sha256(write_brep_bytes(value))


def read_brep_shape(payload: Any) -> Any:
    raw = bytes(payload)
    if not raw:
        raise ArtifactValidationError("brep_invalid", "/body", "BRep bytes are empty")
    try:
        return _n.from_brep(raw, require_valid=True)
    except Exception as exc:  # noqa: BLE001 - the kernel names the failure
        raise ArtifactValidationError("brep_invalid", "/body", str(exc)) from exc


def read_brep_solid(payload: Any) -> Any:
    shape = read_brep_shape(payload)
    if not isinstance(shape, _n.Solid) or len(shape.solids() if hasattr(shape, "solids") else [shape]) != 1:
        raise ArtifactValidationError(
            "solid_cardinality_invalid", "/body", "BRep root must be exactly one Solid"
        )
    return shape


__all__ = ["brep_hash", "read_brep_shape", "read_brep_solid", "write_brep_bytes"]

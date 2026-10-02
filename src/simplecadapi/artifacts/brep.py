"""Deterministic OpenCascade BRep encoding and exact-solid validation."""

from __future__ import annotations

import io
from typing import Any

from OCP.BRep import BRep_Builder
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepTools import BRepTools
from OCP.BinTools import BinTools, BinTools_FormatVersion
from OCP.TopAbs import TopAbs_SOLID
from OCP.TopExp import TopExp
from OCP.TopTools import TopTools_IndexedMapOfShape
from OCP.TopoDS import TopoDS, TopoDS_Shape

from .._internal.shape_pickle import remember_source_bytes, source_bytes
from ..core import Solid
from .canonical import ArtifactValidationError, sha256_bytes

BRepLike = Solid | TopoDS_Shape
_BINTOOLS_PREAMBLE = b"\nOpen CASCADE Topology V"
# Most orbits reach their cycle within two rounds, chamfered sweeps after
# about ten; some never settle (a few near-zero doubles keep drifting), and
# the bound stops those.
_MAX_DECODE_ROUNDS = 32


def _shape(value: BRepLike) -> TopoDS_Shape:
    if isinstance(value, Solid):
        return value.wrapped
    if isinstance(value, TopoDS_Shape):
        return value
    raise TypeError("value must be a Solid or TopoDS_Shape")


def _bintools_bytes(shape: TopoDS_Shape) -> bytes:
    stream = io.BytesIO()
    BinTools.Write_s(
        shape, stream, False, False, BinTools_FormatVersion.BinTools_FormatVersion_VERSION_4
    )
    return stream.getvalue()


def _start_bytes(value: BRepLike) -> bytes:
    if isinstance(value, Solid):
        recorded = source_bytes(value)
        if recorded is not None:
            return recorded
    return _bintools_bytes(_shape(value))


def write_brep_bytes(value: BRepLike) -> bytes:
    # Binary (BinTools V4) stores every double bit-exactly, so the decoded shape
    # is geometrically identical to the written one and every float-derived
    # fingerprint recomputes to the same value. The ASCII writer keeps only 15
    # significant digits, which flips quantized GProp values on BSpline-bounded
    # faces. Meshes are omitted so the bytes do not depend on whether the shape
    # was rendered or tessellated before capture.
    #
    # Reading is not byte-idempotent, though: some zeros come back as -0.0, and
    # on some shapes a few doubles move by an ulp on every read, settling into a
    # cycle of two encodings rather than a fixed point. A shape the notebook
    # cell cache restored has been decoded once more than the one that was
    # built, so writing the first encoding would hash the two differently. Both
    # orbits end in the same cycle, so the canonical bytes are its smallest
    # member.
    #
    # On some shapes the orbit never settles. A wrapper decoded from bytes (a
    # cell-cache pickle or a package blob) remembers them, and the orbit starts
    # there: it is then the built shape's orbit, and a shape that does not
    # settle is written as its first encoding, which both orbits share.
    current = _start_bytes(value)
    if not current:
        raise ArtifactValidationError("brep_invalid", "/body", "BRep writer returned empty bytes")
    seen: list[bytes] = []
    while current not in seen:
        if len(seen) == _MAX_DECODE_ROUNDS:
            return seen[0]
        seen.append(current)
        decoded = TopoDS_Shape()
        BinTools.Read_s(decoded, io.BytesIO(current))
        current = _bintools_bytes(decoded)
    return min(seen[seen.index(current):])


def brep_hash(value: BRepLike) -> str:
    return sha256_bytes(write_brep_bytes(value))


def read_brep_shape(payload: bytes | bytearray | memoryview) -> TopoDS_Shape:
    raw = bytes(payload)
    if not raw:
        raise ArtifactValidationError("brep_invalid", "/body", "BRep bytes are empty")
    shape = TopoDS_Shape()
    try:
        if raw.startswith(_BINTOOLS_PREAMBLE):
            BinTools.Read_s(shape, io.BytesIO(raw))
        else:
            # Legacy ASCII payloads written before the BinTools switch.
            BRepTools.Read_s(shape, io.BytesIO(raw), BRep_Builder())
    except Exception as exc:
        raise ArtifactValidationError("brep_invalid", "/body", str(exc)) from exc
    if shape.IsNull():
        raise ArtifactValidationError("brep_invalid", "/body", "OpenCascade could not read BRep")
    if not BRepCheck_Analyzer(shape).IsValid():
        raise ArtifactValidationError("brep_invalid", "/body", "OpenCascade reports invalid topology")
    return shape


def read_brep_solid(payload: bytes | bytearray | memoryview) -> Solid:
    raw = bytes(payload)
    shape = read_brep_shape(raw)
    solids = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, TopAbs_SOLID, solids)
    if solids.Extent() != 1 or shape.ShapeType() != TopAbs_SOLID:
        raise ArtifactValidationError(
            "solid_cardinality_invalid", "/body", "BRep root must be exactly one Solid"
        )
    try:
        solid = Solid(TopoDS.Solid_s(shape))
    except Exception as exc:
        raise ArtifactValidationError("solid_cardinality_invalid", "/body", str(exc)) from exc
    if raw.startswith(_BINTOOLS_PREAMBLE):
        remember_source_bytes(solid, raw)
    return solid


__all__ = ["brep_hash", "read_brep_shape", "read_brep_solid", "write_brep_bytes"]

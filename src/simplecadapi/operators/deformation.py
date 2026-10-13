"""Recorded scaling and signed offsets for CAD source translation."""
from __future__ import annotations

import math
from typing import Sequence

import numpy as np
from OCP.BRepBuilderAPI import BRepBuilderAPI_Copy, BRepBuilderAPI_GTransform, BRepBuilderAPI_Transform
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepGProp import BRepGProp
from OCP.BRepOffsetAPI import BRepOffsetAPI_MakeThickSolid
from OCP.GeomAbs import GeomAbs_Arc, GeomAbs_Intersection
from OCP.GProp import GProp_GProps
from OCP.TopTools import TopTools_ListOfShape
from OCP.gp import gp_GTrsf, gp_Pnt, gp_Trsf

from ._support import (
    Solid, Face, ShapeSelector, ScalarLike, evaluate_scalar, evaluate_value,
    get_current_cs, solids_of, record_operation_if_active,
    _attach_lineage_from_source, _current_context_metadata,
    _ensure_geo_selection_node_ids, _resolve_selector_or_shapes,
    _serialize_shape_refs,
    _ensure_geo_selection_input_nodes,
)


def _finite_vector(value: Sequence[float], name: str) -> tuple[float, float, float]:
    values = tuple(float(v) for v in evaluate_value(value))
    if len(values) != 3 or not all(math.isfinite(v) for v in values):
        raise ValueError(f"{name} must contain three finite numbers")
    return values


def _finish(source: Solid, wrapped, op: str, params: dict, inputs: list) -> Solid:
    solids = solids_of(wrapped)
    if len(solids) != 1:
        raise ValueError(f"{op} must produce exactly one solid, got {len(solids)}")
    result = Solid(solids[0])
    props = GProp_GProps()
    BRepGProp.VolumePropertiesGK_s(result.wrapped, props, 1e-9, True, True)
    if props.Mass() < 0:
        result.wrapped.Reverse()
    if not BRepCheck_Analyzer(result.wrapped).IsValid():
        raise ValueError(f"{op} produced invalid geometry")
    result._metadata = source._metadata.copy()
    # These builders do not yet provide a complete face-history channel.
    _attach_lineage_from_source(source, result, derivation="continuation", op=op, coverage="partial")
    _ensure_geo_selection_input_nodes(inputs)
    params = {**params, "input_refs": _serialize_shape_refs(inputs)}
    record_operation_if_active(op=op, params=params, outputs=result,
                               input_shapes=inputs, context=_current_context_metadata())
    return result


def scale_rsolid(
    solid: Solid,
    factors: Sequence[float],
    center: Sequence[float] = (0, 0, 0),
) -> Solid:
    """Scale along current coordinate-system axes about an explicit center.

    Every factor must be finite and nonzero. A uniform scale preserves analytic
    geometry; a nonuniform scale converts curves/surfaces where the kernel needs
    it. The input is unchanged and this operation is recorded for graph replay.
    """
    values = _finite_vector(factors, "factors")
    center_value = _finite_vector(center, "center")
    if any(v == 0 for v in values):
        raise ValueError("scale factors must be nonzero")
    cs = get_current_cs()
    global_center = cs.transform_point(np.array(center_value))
    if values[0] == values[1] == values[2]:
        transform = gp_Trsf()
        transform.SetScale(gp_Pnt(*global_center), values[0])
        builder = BRepBuilderAPI_Transform(solid.wrapped, transform, True)
    else:
        basis = np.column_stack([cs.transform_vector(np.eye(3)[i]) for i in range(3)])
        matrix = basis @ np.diag(values) @ basis.T
        translation = global_center - matrix @ global_center
        transform = gp_GTrsf()
        for row in range(3):
            for col in range(3):
                transform.SetValue(row + 1, col + 1, float(matrix[row, col]))
            transform.SetValue(row + 1, 4, float(translation[row]))
        # GTransform's copy flag copies topology, but can retain shared curve
        # geometry from boolean/fillet history. Isolate that geometry first:
        # otherwise OCCT 7.9 can produce invalid p-curves and crash its checker.
        copied = BRepBuilderAPI_Copy(solid.wrapped, True, False).Shape()
        builder = BRepBuilderAPI_GTransform(copied, transform, True)
    builder.Build()
    if not builder.IsDone():
        raise ValueError("kernel could not scale the solid")
    return _finish(solid, builder.Shape(), "make_scale_rsolid",
                   {"factors": factors, "center": center}, [solid])


def transform_rsolid(solid: Solid, matrix: Sequence[Sequence[float]]) -> Solid:
    """Apply a finite nonsingular 4x4 affine matrix in the current frame.

    General affine transformations include shear and reflection. Perspective
    matrices and singular maps cannot define a solid and are rejected.
    """
    values = np.asarray(evaluate_value(matrix), dtype=float)
    if values.shape != (4, 4) or not np.isfinite(values).all():
        raise ValueError("matrix must be a finite 4x4 affine matrix")
    if not np.allclose(values[3], (0, 0, 0, 1), rtol=0, atol=1e-12):
        raise ValueError("perspective transforms cannot define an affine solid")
    if abs(float(np.linalg.det(values[:3, :3]))) < 1e-14:
        raise ValueError("matrix must be nonsingular")
    cs = get_current_cs()
    basis = np.column_stack([cs.transform_vector(np.eye(3)[i]) for i in range(3)])
    origin = cs.transform_point(np.zeros(3))
    linear = basis @ values[:3, :3] @ basis.T
    translation = origin + basis @ values[:3, 3] - linear @ origin
    transform = gp_GTrsf()
    for row in range(3):
        for col in range(3):
            transform.SetValue(row + 1, col + 1, float(linear[row, col]))
        transform.SetValue(row + 1, 4, float(translation[row]))
    copied = BRepBuilderAPI_Copy(solid.wrapped, True, False).Shape()
    builder = BRepBuilderAPI_GTransform(copied, transform, True)
    builder.Build()
    if not builder.IsDone():
        raise ValueError("kernel could not transform the solid")
    return _finish(solid, builder.Shape(), "make_transform_rsolid", {"matrix": matrix}, [solid])


def offset_rsolid(
    solid: Solid,
    amount: ScalarLike,
    openings: Sequence[Face] | ShapeSelector = (),
    *,
    tolerance: float = 1e-4,
    kind: str = "ARC",
) -> Solid:
    """Offset a solid outward (positive) or inward (negative).

    Selected openings form an open shell. Empty openings produce the closed
    offset solid. This is distinct from shell_rsolid's positive inward wall
    thickness, and supports both signs and ARC/INTERSECTION joins explicitly.
    """
    distance = evaluate_scalar(amount)
    if not math.isfinite(distance) or distance == 0:
        raise ValueError("amount must be finite and nonzero")
    if not math.isfinite(tolerance) or tolerance <= 0:
        raise ValueError("tolerance must be finite and positive")
    joins = {"ARC": GeomAbs_Arc, "INTERSECTION": GeomAbs_Intersection}
    if kind not in joins:
        raise ValueError("kind must be ARC or INTERSECTION")
    faces = list(_resolve_selector_or_shapes(solid, openings))
    if any(not isinstance(face, Face) for face in faces):
        raise ValueError("openings must select faces")
    selected_ids = _ensure_geo_selection_node_ids(solid, faces)
    face_list = TopTools_ListOfShape()
    for face in faces:
        face_list.Append(face.wrapped)
    builder = BRepOffsetAPI_MakeThickSolid()
    builder.MakeThickSolidByJoin(solid.wrapped, face_list, distance, tolerance,
                                Intersection=True, RemoveIntEdges=True, Join=joins[kind])
    builder.Build()
    if not builder.IsDone():
        raise ValueError("kernel could not offset the solid")
    params = {"amount": amount, "tolerance": tolerance, "kind": kind,
              "removed_face_count": len(faces), "selected_faces": _serialize_shape_refs(faces)}
    if selected_ids:
        params["selected_face_node_ids"] = selected_ids
    return _finish(solid, builder.Shape(), "make_offset_rsolid", params, [solid, *faces])


def boolean_rsolidlist(
    left: Sequence[Solid],
    right: Sequence[Solid],
    operation: str,
) -> list[Solid]:
    """Apply a set boolean to two body groups, retaining every result solid.

    Members of each group are a geometric set. Unlike single-solid booleans,
    a cut or intersection may return several solids or an empty list.
    Topology lineage is partial; the ordered inputs and all output slots are
    recorded so downstream features can replay the same geometry.
    """
    from ..kernel.ocp_booleans import cut_shapes, common_shapes, fuse_shapes
    from ..kernel.ocp_export import make_compound_always
    lhs, rhs = list(left), list(right)
    if operation not in {"cut", "intersect", "union"}:
        raise ValueError("operation must be cut, intersect or union")
    inputs = [*lhs, *rhs]
    if any(not isinstance(body, Solid) for body in inputs):
        raise TypeError("boolean groups must contain Solid values")
    if any(body.wrapped.IsNull() or not BRepCheck_Analyzer(body.wrapped).IsValid() for body in inputs):
        raise ValueError("boolean groups must contain valid nonempty topology")
    if operation == "union":
        shape = fuse_shapes([body.wrapped for body in inputs]) if inputs else None
    elif not lhs or (operation == "intersect" and not rhs):
        shape = None
    elif operation == "cut":
        shape = cut_shapes(make_compound_always([body.wrapped for body in lhs]),
                           [body.wrapped for body in rhs])
    else:
        shape = common_shapes([make_compound_always([body.wrapped for body in group])
                               for group in (lhs, rhs)])
    if shape is not None and not BRepCheck_Analyzer(shape).IsValid():
        raise ValueError("set boolean produced invalid topology")
    result = [Solid(solid) for solid in solids_of(shape)] if shape is not None else []
    for body in result:
        for source in inputs:
            _attach_lineage_from_source(source, body, derivation="continuation",
                                        op="make_boolean_rsolidlist", coverage="partial")
    _ensure_geo_selection_input_nodes(inputs)
    record_operation_if_active(op="make_boolean_rsolidlist",
        params={"operation": operation, "left_count": len(lhs), "right_count": len(rhs),
                "input_refs": _serialize_shape_refs(inputs)}, outputs=result,
        input_shapes=inputs, context=_current_context_metadata())
    return result


__all__ = ("scale_rsolid", "offset_rsolid", "transform_rsolid", "boolean_rsolidlist")

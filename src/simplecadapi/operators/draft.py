"""Draft selected analytic solid faces around a recorded neutral plane."""
from __future__ import annotations

import math
from typing import Sequence

import numpy as np
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.BRepOffsetAPI import BRepOffsetAPI_DraftAngle
from OCP.GeomAbs import GeomAbs_Plane, GeomAbs_Cylinder, GeomAbs_Cone
from OCP.gp import gp_Dir, gp_Pln, gp_Pnt

from ._support import (
    Face, Solid, ShapeSelector, ScalarLike, evaluate_scalar, get_current_cs,
    _resolve_selector_or_shapes, _ensure_geo_selection_node_ids, _serialize_shape_refs,
)
from .deformation import _finish, _finite_vector


def draft_rsolid(
    solid: Solid,
    faces_to_draft: Sequence[Face] | ShapeSelector,
    angle: ScalarLike,
    plane_origin: Sequence[float] = (0, 0, 0),
    plane_normal: Sequence[float] = (0, 0, 1),
) -> Solid:
    """Draft planar, cylindrical or conical faces by a signed angle in degrees.

    The neutral plane fixes the unchanged section: the selected faces lean
    toward or away from it. Its origin and normal are in current
    coordinate-system coordinates. Face selection is checked against the input
    body and retained as graph inputs for strict replay. The input solid is
    preserved, the output must be one valid solid, and a zero angle records an
    unchanged result. Other surface families are explicitly rejected.

    The operation is recorded as ``make_draft_rsolid``; the body and selected
    faces are ordered inputs, and the angle, neutral plane and face selection
    nodes are parameters, so model JSON replay is strict.

    Args:
        solid: The body to draft.
        faces_to_draft: Faces of ``solid``, or a QL selector that picks them.
        angle: Draft angle in degrees, strictly between -90 and 90.
        plane_origin: A point of the neutral plane.
        plane_normal: Normal of the neutral plane; must be nonzero.

    Returns:
        The drafted solid.

    Raises:
        TypeError: ``solid`` is not a Solid.
        ValueError: Empty selection, a selection that is not made of faces of
            ``solid``, an unsupported surface family, a zero plane normal, or
            a nonfinite or out-of-range angle.

    Examples:
        import simplecadapi as scad
        from simplecadapi import ql
        body = scad.make_box_rsolid(10, 10, 10)
        right = ql.faces().where(ql.prop("geom.normal.x", ">", 0.9)).exactly(1)
        drafted = scad.draft_rsolid(body, right, angle=10)
    """
    if not isinstance(solid, Solid):
        raise TypeError("solid must be a Solid")
    degrees = float(evaluate_scalar(angle))
    if not math.isfinite(degrees) or abs(degrees) >= 90:
        raise ValueError("angle must be finite and strictly between -90 and 90 degrees")
    origin = _finite_vector(plane_origin, "plane_origin")
    normal = _finite_vector(plane_normal, "plane_normal")
    cs = get_current_cs()
    global_origin = cs.transform_point(np.asarray(origin))
    global_normal = cs.transform_vector(np.asarray(normal))
    magnitude = float(np.linalg.norm(global_normal))
    if magnitude <= 1e-14:
        raise ValueError("plane_normal must be nonzero")
    global_normal = global_normal / magnitude
    selected = list(_resolve_selector_or_shapes(solid, faces_to_draft))
    if not selected:
        raise ValueError("draft requires at least one selected face")
    original_faces = solid._iter_faces()
    for face in selected:
        if not isinstance(face, Face):
            raise ValueError("faces_to_draft must select only Face objects")
        if not any(face.wrapped.IsSame(other.wrapped) for other in original_faces):
            raise ValueError("selected draft faces must belong to the input solid")
        if BRepAdaptor_Surface(face.wrapped).GetType() not in {GeomAbs_Plane, GeomAbs_Cylinder, GeomAbs_Cone}:
            raise ValueError("draft supports only planar, cylindrical, and conical faces")
    # Remove repeated references without changing the ordered face selection.
    selected = list({face.topo_id: face for face in selected}.values())
    selected_ids = _ensure_geo_selection_node_ids(solid, selected)
    if degrees == 0:
        shape = solid.wrapped
    else:
        direction = gp_Dir(*global_normal)
        plane = gp_Pln(gp_Pnt(*global_origin), direction)
        builder = BRepOffsetAPI_DraftAngle(solid.wrapped)
        for face in selected:
            builder.Add(face.wrapped, direction, math.radians(degrees), plane, True)
            if not builder.AddDone():
                raise ValueError("kernel could not add the requested draft angle to a selected face")
        builder.Build()
        if not builder.IsDone():
            raise ValueError("kernel could not build the drafted solid")
        shape = builder.Shape()
    params = {"angle": angle, "plane_origin": plane_origin, "plane_normal": plane_normal,
              "selected_face_count": len(selected), "selected_faces": _serialize_shape_refs(selected)}
    if selected_ids:
        params["selected_face_node_ids"] = selected_ids
    return _finish(solid, shape, "make_draft_rsolid", params, [solid, *selected])


__all__ = ("draft_rsolid",)

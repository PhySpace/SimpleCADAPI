"""Face tessellation helpers over the bound OCCT classes."""

from __future__ import annotations

import math
from typing import Iterable, List, Sequence, Tuple

from simplecadapi._cpp.occt.BRep import BRep_Builder, BRep_Tool
from simplecadapi._cpp.occt.BRepCheck import BRepCheck_Analyzer
from simplecadapi._cpp.occt.BRepBuilderAPI import BRepBuilderAPI_Transform
from simplecadapi._cpp.occt.BRepGProp import BRepGProp
from simplecadapi._cpp.occt.GProp import GProp_GProps
from simplecadapi._cpp.occt.BRepMesh import BRepMesh_IncrementalMesh
from simplecadapi._cpp.occt.BRepTools import BRepTools
from simplecadapi._cpp.occt.Poly import Poly_Triangulation
from simplecadapi._cpp.occt.TopAbs import TopAbs_FORWARD, TopAbs_REVERSED
from simplecadapi._cpp.occt.TopLoc import TopLoc_Location
from simplecadapi._cpp.occt.TopoDS import TopoDS, TopoDS_Face, TopoDS_Shell
from simplecadapi._cpp.occt.gp import gp_Pnt

from .ocp_properties import bounding_box
from .ocp_topology import faces_of


def tessellate_face(face: TopoDS_Face, tolerance: float = 0.35, angular_tolerance: float = 0.22):
    vertices, triangles, _corner_normals = tessellate_face_with_normals(
        face,
        tolerance=tolerance,
        angular_tolerance=angular_tolerance,
    )
    return vertices, triangles


def tessellate_face_with_normals(
    face: TopoDS_Face,
    tolerance: float = 0.35,
    angular_tolerance: float = 0.22,
):
    """Return definition-local triangulation and per-corner CAD normals."""

    prepared = _bake_face_location(face)
    BRepTools.Clean_s(prepared, False)
    mesh = BRepMesh_IncrementalMesh(
        prepared,
        float(tolerance),
        False,
        float(angular_tolerance),
        False,
    )
    mesh.Perform()
    loc = TopLoc_Location()
    tri = BRep_Tool.Triangulation_s(prepared, loc, 0)
    if tri is None:
        return [], [], []
    trsf = loc.Transformation()
    vertices = []
    for idx in range(1, tri.NbNodes() + 1):
        p = tri.Node(idx).Transformed(trsf)
        vertices.append((float(p.X()), float(p.Y()), float(p.Z())))
    triangles = []
    corner_normals = []
    reversed_face = face.Orientation() == TopAbs_REVERSED
    for idx in range(1, tri.NbTriangles() + 1):
        a, b, c = tri.Triangle(idx).Get()
        if reversed_face:
            node_indices = (a, c, b)
        else:
            node_indices = (a, b, c)
        triangles.append(tuple(index - 1 for index in node_indices))
        if tri.HasNormals():
            normals = []
            for node_index in node_indices:
                direction = tri.Normal(node_index).Transformed(trsf)
                if reversed_face:
                    direction = direction.Reversed()
                normals.append((float(direction.X()), float(direction.Y()), float(direction.Z())))
            corner_normals.append(tuple(normals))
        else:
            left = vertices[node_indices[1] - 1]
            origin = vertices[node_indices[0] - 1]
            right = vertices[node_indices[2] - 1]
            cross = (
                (left[1] - origin[1]) * (right[2] - origin[2])
                - (left[2] - origin[2]) * (right[1] - origin[1]),
                (left[2] - origin[2]) * (right[0] - origin[0])
                - (left[0] - origin[0]) * (right[2] - origin[2]),
                (left[0] - origin[0]) * (right[1] - origin[1])
                - (left[1] - origin[1]) * (right[0] - origin[0]),
            )
            length = sum(component * component for component in cross) ** 0.5
            normal = tuple(component / length for component in cross) if length > 0.0 else (0.0, 0.0, 0.0)
            corner_normals.append((normal, normal, normal))
    return vertices, triangles, corner_normals


def _bake_face_location(face: TopoDS_Face) -> TopoDS_Face:
    location = face.Location()
    unlocated = face.Located(TopLoc_Location(), False)
    if location.IsIdentity():
        return TopoDS.Face_s(unlocated)
    builder = BRepBuilderAPI_Transform(
        unlocated,
        location.Transformation(),
        True,
        False,
    )
    builder.Build()
    if not builder.IsDone():
        raise ValueError("OCP face location bake failed")
    return TopoDS.Face_s(builder.Shape())

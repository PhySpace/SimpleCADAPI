"""Native, mesh-free BREP snapshot encoding and validation."""

from __future__ import annotations

import io
import math
from typing import Any, Literal

from simplecadapi._cpp.occt.BinTools import BinTools, BinTools_FormatVersion_VERSION_4
from simplecadapi._cpp.occt.BRep import BRep_Tool
from simplecadapi._cpp.occt.BRepAdaptor import BRepAdaptor_Surface
from simplecadapi._cpp.occt.BRepCheck import BRepCheck_Analyzer
from simplecadapi._cpp.occt.BRepGProp import BRepGProp
from simplecadapi._cpp.occt.GProp import GProp_GProps
from simplecadapi._cpp.occt.TopAbs import (
    TopAbs_EDGE,
    TopAbs_FACE,
    TopAbs_SHELL,
    TopAbs_SOLID,
    TopAbs_VERTEX,
)
from simplecadapi._cpp.occt.TopExp import TopExp, TopExp_Explorer
from simplecadapi._cpp.occt.TopLoc import TopLoc_Location
from simplecadapi._cpp.occt.TopoDS import (
    TopoDS,
    TopoDS_Shape,
    TopoDS_Shell,
    TopoDS_Solid,
)
from simplecadapi._cpp.occt.TopTools import TopTools_IndexedMapOfShape

RootKind = Literal["shell", "solid"]


def has_triangulation(shape: TopoDS_Shape) -> bool:
    explorer = TopExp_Explorer(shape, TopAbs_FACE)
    while explorer.More():
        if (
            BRep_Tool.Triangulation_s(
                TopoDS.Face_s(explorer.Current()), TopLoc_Location(), 0
            )
            is not None
        ):
            return True
        explorer.Next()
    return False


def _shape_count(shape: TopoDS_Shape, kind: Any) -> int:
    indexed = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, kind, indexed)
    return int(indexed.Extent())


def _common_descriptor(shape: TopoDS_Shape, root_kind: RootKind) -> dict[str, Any]:
    return {
        "root_shape_type": root_kind,
        "valid": bool(BRepCheck_Analyzer(shape).IsValid()),
        "solid_count": _shape_count(shape, TopAbs_SOLID),
        "shell_count": _shape_count(shape, TopAbs_SHELL),
        "face_count": _shape_count(shape, TopAbs_FACE),
        "edge_count": _shape_count(shape, TopAbs_EDGE),
        "vertex_count": _shape_count(shape, TopAbs_VERTEX),
    }


def shell_descriptor(shell: TopoDS_Shell) -> dict[str, Any]:
    return {
        **_common_descriptor(shell, "shell"),
        "closed": bool(BRep_Tool.IsClosed_s(shell)),
    }


def solid_descriptor(solid: TopoDS_Solid) -> dict[str, Any]:
    properties = GProp_GProps()
    BRepGProp.VolumeProperties_s(solid, properties)
    volume = float(properties.Mass())
    if not math.isfinite(volume) or volume <= 0.0:
        raise ValueError("BREP region must have positive finite solid volume")
    return {**_common_descriptor(solid, "solid"), "volume": volume}


def require_single_valid_shell(shape: TopoDS_Shape) -> TopoDS_Shell:
    shells: list[TopoDS_Shell] = []
    if shape.ShapeType() == TopAbs_SHELL:
        shells.append(TopoDS.Shell_s(shape))
    else:
        explorer = TopExp_Explorer(shape, TopAbs_SHELL)
        while explorer.More():
            shells.append(TopoDS.Shell_s(explorer.Current()))
            explorer.Next()
    if len(shells) != 1:
        raise ValueError(
            f"BREP region must contain exactly one shell, got {len(shells)}"
        )
    shell = shells[0]
    if _shape_count(shape, TopAbs_FACE) != _shape_count(shell, TopAbs_FACE):
        raise ValueError("BREP region contains faces outside its single shell")
    descriptor = shell_descriptor(shell)
    if not descriptor["valid"]:
        raise ValueError("BREP region shell is invalid")
    return shell


def require_single_valid_solid(shape: TopoDS_Shape) -> TopoDS_Solid:
    solids: list[TopoDS_Solid] = []
    if shape.ShapeType() == TopAbs_SOLID:
        solids.append(TopoDS.Solid_s(shape))
    else:
        explorer = TopExp_Explorer(shape, TopAbs_SOLID)
        while explorer.More():
            solids.append(TopoDS.Solid_s(explorer.Current()))
            explorer.Next()
    if len(solids) != 1:
        raise ValueError(
            f"BREP region must contain exactly one solid, got {len(solids)}"
        )
    solid = solids[0]
    if any(
        _shape_count(shape, kind) != _shape_count(solid, kind)
        for kind in (TopAbs_FACE, TopAbs_EDGE, TopAbs_VERTEX)
    ):
        raise ValueError("BREP region contains topology outside its single solid")
    descriptor = solid_descriptor(solid)
    if not descriptor["valid"]:
        raise ValueError("BREP region solid is invalid")
    return solid


def encode_shape(shape: TopoDS_Shape, root_kind: RootKind) -> bytes:
    if root_kind == "solid":
        require_single_valid_solid(shape)
    else:
        require_single_valid_shell(shape)
    stream = io.BytesIO()
    BinTools.Write_s(
        shape,
        stream,
        False,
        False,
        BinTools_FormatVersion_VERSION_4,
    )
    payload = stream.getvalue()
    if not payload:
        raise ValueError("OpenCascade produced an empty BREP snapshot payload")
    return payload


def decode_shape(payload: bytes, root_kind: RootKind) -> TopoDS_Shape:
    if not payload:
        raise ValueError("BREP snapshot payload is empty")
    shape = TopoDS_Shape()
    BinTools.Read_s(shape, io.BytesIO(payload))
    if shape.IsNull():
        raise ValueError("OpenCascade decoded a null BREP snapshot shape")
    expected_type = TopAbs_SOLID if root_kind == "solid" else TopAbs_SHELL
    if shape.ShapeType() != expected_type:
        raise ValueError(
            f"BREP snapshot payload root is not declared {root_kind} topology"
        )
    return (
        require_single_valid_solid(shape)
        if root_kind == "solid"
        else require_single_valid_shell(shape)
    )


def shape_descriptor(shape: TopoDS_Shape, root_kind: RootKind) -> dict[str, Any]:
    return (
        solid_descriptor(require_single_valid_solid(shape))
        if root_kind == "solid"
        else shell_descriptor(require_single_valid_shell(shape))
    )


def face_fingerprints(shape: TopoDS_Shape) -> list[dict[str, Any]]:
    indexed = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, TopAbs_FACE, indexed)
    records = []
    for index in range(1, indexed.Extent() + 1):
        face = TopoDS.Face_s(indexed.FindKey(index))
        properties = GProp_GProps()
        BRepGProp.SurfaceProperties_s(face, properties)
        center = properties.CentreOfMass()
        records.append(
            {
                "surface_type": BRepAdaptor_Surface(face, True).GetType().name,
                "orientation": face.Orientation().name,
                "area": round(abs(float(properties.Mass())), 12),
                "centroid": [
                    round(float(center.X()), 12),
                    round(float(center.Y()), 12),
                    round(float(center.Z()), 12),
                ],
                "edge_count": _shape_count(face, TopAbs_EDGE),
            }
        )
    return records


__all__ = [
    "RootKind",
    "decode_shape",
    "encode_shape",
    "face_fingerprints",
    "has_triangulation",
    "require_single_valid_shell",
    "require_single_valid_solid",
    "shape_descriptor",
    "shell_descriptor",
    "solid_descriptor",
]

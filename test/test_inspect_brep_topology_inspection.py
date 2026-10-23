from __future__ import annotations

import pytest
from simplecadapi._cpp.occt.BRep import BRep_Builder
from simplecadapi._cpp.occt.BRepBuilderAPI import (
    BRepBuilderAPI_MakeEdge,
    BRepBuilderAPI_MakeFace,
    BRepBuilderAPI_MakeVertex,
    BRepBuilderAPI_MakeWire,
)
from simplecadapi._cpp.occt.BRepPrimAPI import BRepPrimAPI_MakeBox
from simplecadapi._cpp.occt.TopAbs import TopAbs_FACE, TopAbs_VERTEX
from simplecadapi._cpp.occt.TopExp import TopExp
from simplecadapi._cpp.occt.TopTools import TopTools_IndexedMapOfShape
from simplecadapi._cpp.occt.TopoDS import TopoDS, TopoDS_Compound, TopoDS_Edge, TopoDS_Shell
from simplecadapi._cpp.occt.gp import gp_Pnt

from simplecadapi.inspect import brep


def _triangle(shared, first, second):
    wire = BRepBuilderAPI_MakeWire()
    wire.Add(shared)
    wire.Add(BRepBuilderAPI_MakeEdge(first, second).Edge())
    wire.Add(BRepBuilderAPI_MakeEdge(second, gp_Pnt(0.0, 0.0, 0.0)).Edge())
    return BRepBuilderAPI_MakeFace(wire.Wire(), True).Face()


def _three_faces_sharing_one_edge():
    start = gp_Pnt(0.0, 0.0, 0.0)
    end = gp_Pnt(1.0, 0.0, 0.0)
    shared = BRepBuilderAPI_MakeEdge(start, end).Edge()
    faces = [
        _triangle(shared, end, gp_Pnt(0.0, 1.0, 0.0)),
        _triangle(shared, end, gp_Pnt(0.0, -1.0, 0.0)),
        _triangle(shared, end, gp_Pnt(0.0, 0.0, 1.0)),
    ]
    compound = TopoDS_Compound()
    builder = BRep_Builder()
    builder.MakeCompound(compound)
    for face in faces:
        builder.Add(compound, face)
    return compound


def _compound(*shapes):
    compound = TopoDS_Compound()
    builder = BRep_Builder()
    builder.MakeCompound(compound)
    for shape in shapes:
        builder.Add(compound, shape)
    return compound


def _orphan_degenerate_edge():
    edge = TopoDS_Edge()
    builder = BRep_Builder()
    builder.MakeEdge(edge)
    builder.Add(edge, BRepBuilderAPI_MakeVertex(gp_Pnt(3.0, 3.0, 3.0)).Vertex())
    builder.Degenerated(edge, True)
    return edge


def test_inspect_topology_distinguishes_validity_from_closed_manifoldness():
    box = brep.inspect_topology_rdescriptor(
        BRepPrimAPI_MakeBox(2.0, 3.0, 4.0).Shape()
    )
    wire = BRepBuilderAPI_MakeWire()
    corners = (
        gp_Pnt(0.0, 0.0, 0.0),
        gp_Pnt(2.0, 0.0, 0.0),
        gp_Pnt(2.0, 1.0, 0.0),
        gp_Pnt(0.0, 1.0, 0.0),
    )
    for start, end in zip(corners, (*corners[1:], corners[0])):
        wire.Add(BRepBuilderAPI_MakeEdge(start, end).Edge())
    face = brep.inspect_topology_rdescriptor(
        BRepBuilderAPI_MakeFace(wire.Wire(), True).Face()
    )

    assert box["valid"] is True
    assert box["closed_manifold"] is True
    assert box["edge_classification_counts"] == {
        "degenerate": 0,
        "free": 0,
        "manifold": 12,
        "non_manifold": 0,
        "orientation_defect": 0,
        "orphan": 0,
        "seam": 0,
    }
    assert box["edge_evidence_counts"] == {"degenerate": 0, "orphan": 0}
    assert box["orphan_vertex_count"] == 0
    assert box["shells"] == [
        {
            "shell_index": 0,
            "closed": True,
            "closure_status": "BRepCheck_NoError",
            "orientation_status": "BRepCheck_NoError",
        }
    ]

    assert face["valid"] is True
    assert face["closed_manifold"] is False
    assert face["edge_classification_counts"]["free"] == 4
    assert face["edge_use_histogram"] == {"1": 4}


def test_inspect_topology_reports_non_manifold_edge_uses():
    report = brep.inspect_topology_rdescriptor(_three_faces_sharing_one_edge())

    assert report["closed_manifold"] is False
    assert report["edge_classification_counts"]["non_manifold"] == 1
    problem = next(
        item
        for item in report["problem_edges"]
        if item["classification"] == "non_manifold"
    )
    assert problem["use_count"] == 3
    assert problem["unique_face_count"] == 3
    assert problem["face_ids"] == ["face:0", "face:1", "face:2"]


def test_inspect_topology_reports_wire_closure_orientations_and_small_faces():
    wire = BRepBuilderAPI_MakeWire()
    corners = (
        gp_Pnt(0.0, 0.0, 0.0),
        gp_Pnt(1.0e-3, 0.0, 0.0),
        gp_Pnt(1.0e-3, 1.0e-3, 0.0),
        gp_Pnt(0.0, 1.0e-3, 0.0),
    )
    for start, end in zip(corners, (*corners[1:], corners[0])):
        wire.Add(BRepBuilderAPI_MakeEdge(start, end).Edge())
    face = BRepBuilderAPI_MakeFace(wire.Wire(), True).Face()

    report = brep.inspect_topology_rdescriptor(
        face, small_face_area_threshold=1.0e-5
    )

    assert report["wire_counts"] == {"closed": 1, "open": 0}
    assert report["face_orientation_counts"] == {"forward": 1}
    assert report["small_face_count"] == 1
    assert report["small_faces"][0]["face_id"] == "face:0"
    assert report["small_faces"][0]["area"] == pytest.approx(1.0e-6)


def test_inspect_topology_keeps_validity_independent_from_closed_manifoldness():
    shape = BRepPrimAPI_MakeBox(1.0, 1.0, 1.0).Shape()
    vertices = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, TopAbs_VERTEX, vertices)
    vertex = TopoDS.Vertex_s(vertices.FindKey(1))
    BRep_Builder().UpdateVertex(vertex, gp_Pnt(0.2, 0.2, 0.2), 1.0e-7)

    report = brep.inspect_topology_rdescriptor(shape)

    assert report["valid"] is False
    assert report["closed_manifold"] is True
    assert report["edge_classification_counts"]["manifold"] == 12


def test_closed_manifold_requires_edge_and_shell_orientation():
    box = BRepPrimAPI_MakeBox(1.0, 1.0, 1.0).Shape()
    faces = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(box, TopAbs_FACE, faces)
    shell = TopoDS_Shell()
    builder = BRep_Builder()
    builder.MakeShell(shell)
    for index in range(1, faces.Extent() + 1):
        face = TopoDS.Face_s(faces.FindKey(index))
        builder.Add(shell, face.Reversed() if index == 1 else face)

    report = brep.inspect_topology_rdescriptor(shell)

    assert report["shells"][0]["closed"] is True
    assert report["shells"][0]["orientation_status"] != "BRepCheck_NoError"
    assert report["edge_classification_counts"]["orientation_defect"] > 0
    assert report["closed_manifold"] is False


@pytest.mark.parametrize(
    ("orphan", "edge_evidence", "orphan_vertex_count"),
    [
        (BRepBuilderAPI_MakeVertex(gp_Pnt(3.0, 3.0, 3.0)).Vertex(), None, 1),
        (_orphan_degenerate_edge(), {"degenerate": 1, "orphan": 1}, 0),
    ],
)
def test_closed_manifold_rejects_mixed_dimensional_orphan_topology(
    orphan, edge_evidence, orphan_vertex_count
):
    report = brep.inspect_topology_rdescriptor(
        _compound(BRepPrimAPI_MakeBox(1.0, 1.0, 1.0).Shape(), orphan)
    )

    assert report["closed_manifold"] is False
    assert report["orphan_vertex_count"] == orphan_vertex_count
    if edge_evidence is not None:
        assert report["edge_evidence_counts"] == edge_evidence
        problem = next(
            item for item in report["problem_edges"] if item["degenerated"]
        )
        assert problem["classification"] == "degenerate"
        assert problem["orphan"] is True

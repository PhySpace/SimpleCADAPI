"""Planar material intersection with explicit topological outer/inner wires."""

from itertools import product

import numpy as np
from simplecadapi._cpp.occt.BRep import BRep_Tool
from simplecadapi._cpp.occt.Bnd import Bnd_Box
from simplecadapi._cpp.occt.BRepBndLib import BRepBndLib
from simplecadapi._cpp.occt.BRepAlgoAPI import BRepAlgoAPI_Common
from simplecadapi._cpp.occt.BRepBuilderAPI import BRepBuilderAPI_MakeFace
from simplecadapi._cpp.occt.BRepCheck import BRepCheck_Analyzer
from simplecadapi._cpp.occt.BRepTools import BRepTools, BRepTools_WireExplorer
from simplecadapi._cpp.occt.TopAbs import TopAbs_FACE, TopAbs_WIRE, TopAbs_EDGE
from simplecadapi._cpp.occt.TopExp import TopExp, TopExp_Explorer
from simplecadapi._cpp.occt.TopoDS import TopoDS
from simplecadapi._cpp.occt.TopTools import TopTools_ListOfShape
from simplecadapi._cpp.occt.gp import gp_Pln, gp_Pnt, gp_Dir

from ..brep.queries import (
    _sample_edge,
    _linear_length,
    _plane_coordinates,
    _polygon_area,
    _sample_length,
)
from ..brep.model import BRepEntityError


def material_section_geometry(source, section, samples_per_edge, tolerance):
    """Return descriptor, matching edge map, faces and hole faces from ONE cut."""
    plane = section["plane"]
    origin = np.asarray(plane["origin"], float)
    x_axis, y_axis = np.asarray(plane["x_direction"]), np.asarray(plane["y_direction"])
    box = Bnd_Box()
    BRepBndLib.Add_s(source, box, False)
    bounds = box.Get()
    span = (
        max(
            np.linalg.norm(np.asarray(p) - origin)
            for p in product(*[(bounds[i], bounds[i + 3]) for i in range(3)])
        )
        + 1.0
    )
    cutter = BRepBuilderAPI_MakeFace(
        gp_Pln(gp_Pnt(*origin), gp_Dir(*plane["normal"])), -span, span, -span, span
    ).Face()
    arguments, tools = TopTools_ListOfShape(), TopTools_ListOfShape()
    arguments.Append(source)
    tools.Append(cutter)
    operation = BRepAlgoAPI_Common()
    operation.SetArguments(arguments)
    operation.SetTools(tools)
    operation.SetFuzzyValue(tolerance)
    operation.SetNonDestructive(True)
    operation.SetUseOBB(True)
    operation.Build()
    if not operation.IsDone():
        raise BRepEntityError("Planar material-face intersection failed")
    result = operation.Shape()
    edges, contours, edge_shapes, faces, holes = [], [], {}, [], []
    max_snap = 0.0
    errors = []
    if not BRepCheck_Analyzer(result).IsValid():
        errors.append("invalid material-face intersection")
    explorer = TopExp_Explorer(result, TopAbs_FACE)
    while explorer.More():
        face = TopoDS.Face_s(explorer.Current())
        face_id = len(faces)
        faces.append(face)
        outer = BRepTools.OuterWire_s(face)
        outer_count = 0
        wire_explorer = TopExp_Explorer(face, TopAbs_WIRE)
        while wire_explorer.More():
            wire = TopoDS.Wire_s(wire_explorer.Current())
            is_outer = wire.IsSame(outer)
            outer_count += int(is_outer)
            if not is_outer:
                holes.append(BRepBuilderAPI_MakeFace(wire, True).Face())
            walk = BRepTools_WireExplorer(wire, face)
            points, indices, length = [], [], 0.0
            closed = bool(BRep_Tool.IsClosed_s(wire))
            walked_edges = 0
            while walk.More():
                edge = TopoDS.Edge_s(walk.Current())
                walked_edges += 1
                samples = _sample_edge(edge, samples_per_edge)
                if len(samples) >= 2:
                    a = list(BRep_Tool.Pnt_s(TopExp.FirstVertex_s(edge, True)).Coord())
                    b = list(BRep_Tool.Pnt_s(TopExp.LastVertex_s(edge, True)).Coord())
                    max_snap = max(
                        max_snap,
                        float(np.linalg.norm(np.asarray(samples[0]) - a)),
                        float(np.linalg.norm(np.asarray(samples[-1]) - b)),
                    )
                    # _sample_edge follows edge orientation; shared BREP vertices
                    # anchor the joints without inventing a closing segment.
                    samples[0], samples[-1] = a, b
                    if (
                        points
                        and np.linalg.norm(np.asarray(points[-1]) - a) > tolerance
                    ):
                        closed = False
                        errors.append(
                            "material wire traversal has a disconnected joint"
                        )
                    edge_id = len(edges)
                    edge_shapes[edge_id] = edge
                    exact = _linear_length(edge)
                    edges.append(
                        {
                            "index": edge_id,
                            "samples_3d": samples,
                            "samples_2d": [
                                _plane_coordinates(p, origin, x_axis, y_axis)
                                for p in samples
                            ],
                            "length_exact": exact,
                            "length_sampled": _sample_length(samples),
                        }
                    )
                    points.extend(samples if not points else samples[1:])
                    indices.append(edge_id)
                    length += exact
                walk.Next()
            all_edges = TopExp_Explorer(wire, TopAbs_EDGE)
            edge_count = 0
            while all_edges.More():
                edge_count += 1
                all_edges.Next()
            if walked_edges != edge_count:
                closed = False
                errors.append("material wire traversal omitted edges")
            if (
                len(points) < 3
                or np.linalg.norm(np.asarray(points[-1]) - points[0]) > tolerance
            ):
                closed = False
            if closed:
                points[-1] = points[0]
            else:
                errors.append("material wire is not closed")
            points_2d = [_plane_coordinates(p, origin, x_axis, y_axis) for p in points]
            contours.append(
                {
                    "index": len(contours),
                    "edge_indices": indices,
                    "closed": closed,
                    "samples_3d": points,
                    "samples_2d": points_2d,
                    "length_exact": length,
                    "length_sampled": _sample_length(points),
                    "area": _polygon_area(points_2d) if closed else None,
                    "role": "material" if is_outer else "hole",
                    "face_index": face_id,
                    "ring_method": "brep_outer_wire",
                    "nesting_depth": 0 if is_outer else 1,
                }
            )
            wire_explorer.Next()
        if outer_count != 1:
            errors.append("material face must have exactly one outer wire")
        explorer.Next()
    descriptor = {
        **section,
        "edges": edges,
        "contours": contours,
        "edge_count": len(edges),
        "closed_contour_count": sum(c["closed"] for c in contours),
        "open_contour_count": sum(not c["closed"] for c in contours),
        "total_closed_area": sum(c["area"] or 0.0 for c in contours),
        "material_area": sum(
            (c["area"] or 0.0) * (1 if c["role"] == "material" else -1)
            for c in contours
        ),
        "area_method": "sampled_contours_diagnostic_only",
        "contour_method": "material_face_intersection",
        "topological_endpoint_snap_max_mm": max_snap,
        "material_topology": {
            "face_count": len(faces),
            "hole_count": len(holes),
            "valid": not errors and bool(faces),
            "errors": errors,
        },
    }
    return descriptor, edge_shapes, faces, holes

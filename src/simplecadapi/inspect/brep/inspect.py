"""Structured STEP BREP inspection."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from OCP.BRep import BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface
from OCP.BRepBndLib import BRepBndLib
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.Bnd import Bnd_Box
from OCP.TopAbs import (
    TopAbs_EDGE,
    TopAbs_FACE,
    TopAbs_SHELL,
    TopAbs_SOLID,
    TopAbs_VERTEX,
)
from OCP.TopExp import TopExp, TopExp_Explorer
from OCP.TopTools import TopTools_IndexedMapOfShape
from OCP.TopoDS import TopoDS, TopoDS_Shape

from .io import direction, load_step_rshape, measure_shape_mass_rtuple, xyz


@dataclass(frozen=True)
class BRepInspection:
    """JSON-serializable geometry and topology facts for one BREP."""

    source: str | None
    valid: bool
    counts: dict[str, int]
    bounding_box: list[float]
    volume: float
    surface_area: float
    center_of_mass: list[float]
    surface_type_counts: dict[str, int]
    edge_type_counts: dict[str, int]
    faces: list[dict[str, Any]]
    edges: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def summary(self) -> str:
        """One digest line: the facts an agent checks first, no per-face dump.

        The full record (tens of thousands of characters on a real part) is
        ``.to_dict()`` / the ``faces`` / ``edges`` lists.
        """
        box = self.bounding_box
        size = [round(box[i + 3] - box[i], 3) for i in range(3)]
        return (
            f"<BRepInspection {self.source or '?'}: valid={self.valid} "
            f"counts={self.counts} volume={self.volume:.6g} area={self.surface_area:.6g} "
            f"size(xyz)={size} surfaces={self.surface_type_counts} edges={self.edge_type_counts}>"
        )

    def __repr__(self) -> str:
        return self.summary()

    def write_json(self, path: str | Path, *, indent: int = 2) -> Path:
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(self.to_dict(), indent=indent), encoding="utf-8")
        return output


def _count_occurrences(shape: TopoDS_Shape, kind) -> int:
    explorer = TopExp_Explorer(shape, kind)
    count = 0
    while explorer.More():
        count += 1
        explorer.Next()
    return count


def _surface_parameters(adaptor: BRepAdaptor_Surface) -> dict[str, Any]:
    kind = str(adaptor.GetType()).split(".")[-1].removeprefix("GeomAbs_")
    result: dict[str, Any] = {"type": kind}
    if kind == "Plane":
        surface = adaptor.Plane()
        result.update(
            normal=direction(surface.Axis().Direction()),
            location=xyz(surface.Location()),
        )
    elif kind == "Cylinder":
        surface = adaptor.Cylinder()
        result.update(
            radius=float(surface.Radius()),
            axis=direction(surface.Axis().Direction()),
            location=xyz(surface.Location()),
        )
    elif kind == "Cone":
        surface = adaptor.Cone()
        result.update(
            reference_radius=float(surface.RefRadius()),
            semi_angle=float(surface.SemiAngle()),
            axis=direction(surface.Axis().Direction()),
            location=xyz(surface.Location()),
            apex=xyz(surface.Apex()),
        )
    elif kind == "Sphere":
        surface = adaptor.Sphere()
        result.update(radius=float(surface.Radius()), center=xyz(surface.Location()))
    elif kind == "Torus":
        surface = adaptor.Torus()
        result.update(
            major_radius=float(surface.MajorRadius()),
            minor_radius=float(surface.MinorRadius()),
            axis=direction(surface.Axis().Direction()),
            location=xyz(surface.Location()),
        )
    elif kind == "BSplineSurface":
        surface = adaptor.BSpline()
        rational = bool(surface.IsURational() or surface.IsVRational())
        u_poles = int(surface.NbUPoles())
        v_poles = int(surface.NbVPoles())
        result.update(
            u_degree=int(surface.UDegree()),
            v_degree=int(surface.VDegree()),
            u_poles=u_poles,
            v_poles=v_poles,
            u_knots=int(surface.NbUKnots()),
            v_knots=int(surface.NbVKnots()),
            u_periodic=bool(surface.IsUPeriodic()),
            v_periodic=bool(surface.IsVPeriodic()),
            rational=rational,
            u_knot_values=[
                float(surface.UKnot(index))
                for index in range(1, surface.NbUKnots() + 1)
            ],
            v_knot_values=[
                float(surface.VKnot(index))
                for index in range(1, surface.NbVKnots() + 1)
            ],
            u_multiplicities=[
                int(surface.UMultiplicity(index))
                for index in range(1, surface.NbUKnots() + 1)
            ],
            v_multiplicities=[
                int(surface.VMultiplicity(index))
                for index in range(1, surface.NbVKnots() + 1)
            ],
            control_points=[
                [
                    xyz(surface.Pole(u_index, v_index))
                    for v_index in range(1, v_poles + 1)
                ]
                for u_index in range(1, u_poles + 1)
            ],
        )
        if rational:
            result["weights"] = [
                [
                    float(surface.Weight(u_index, v_index))
                    for v_index in range(1, v_poles + 1)
                ]
                for u_index in range(1, u_poles + 1)
            ]
    return result


def _edge_parameters(edge) -> dict[str, Any]:
    adaptor = BRepAdaptor_Curve(edge)
    kind = str(adaptor.GetType()).split(".")[-1].removeprefix("GeomAbs_")
    first = float(adaptor.FirstParameter())
    last = float(adaptor.LastParameter())
    result: dict[str, Any] = {"type": kind, "first": first, "last": last}
    if kind == "Circle":
        circle = adaptor.Circle()
        result.update(
            radius=float(circle.Radius()),
            center=xyz(circle.Location()),
            axis=direction(circle.Axis().Direction()),
        )
    elif kind == "Line":
        result.update(
            line_start=xyz(adaptor.Value(first)), line_end=xyz(adaptor.Value(last))
        )
    elif kind == "BSplineCurve":
        curve = adaptor.BSpline()
        rational = bool(curve.IsRational())
        result.update(
            degree=int(curve.Degree()),
            poles=int(curve.NbPoles()),
            knots=int(curve.NbKnots()),
            periodic=bool(curve.IsPeriodic()),
            rational=rational,
            knot_values=[
                float(curve.Knot(index)) for index in range(1, curve.NbKnots() + 1)
            ],
            multiplicities=[
                int(curve.Multiplicity(index))
                for index in range(1, curve.NbKnots() + 1)
            ],
            control_points=[
                xyz(curve.Pole(index)) for index in range(1, curve.NbPoles() + 1)
            ],
        )
        if rational:
            result["weights"] = [
                float(curve.Weight(index)) for index in range(1, curve.NbPoles() + 1)
            ]
    return result


def inspect_shape_rbrepinspection(
    shape: TopoDS_Shape, *, source: str | Path | None = None
) -> BRepInspection:
    """Inspect one imported shape without relying on STEP entity numbering."""
    bounding_box = Bnd_Box()
    BRepBndLib.AddOptimal_s(shape, bounding_box)
    volume, center = measure_shape_mass_rtuple(shape, "volume")
    surface_area, _ = measure_shape_mass_rtuple(shape, "area")

    face_map = TopTools_IndexedMapOfShape()
    edge_map = TopTools_IndexedMapOfShape()
    vertex_map = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, TopAbs_FACE, face_map)
    TopExp.MapShapes_s(shape, TopAbs_EDGE, edge_map)
    TopExp.MapShapes_s(shape, TopAbs_VERTEX, vertex_map)

    face_edges: dict[int, list[int]] = {}
    edge_faces: dict[int, list[int]] = defaultdict(list)
    for face_index in range(1, face_map.Extent() + 1):
        face = TopoDS.Face_s(face_map.FindKey(face_index))
        explorer = TopExp_Explorer(face, TopAbs_EDGE)
        indices: list[int] = []
        while explorer.More():
            edge_index = edge_map.FindIndex(explorer.Current())
            indices.append(edge_index)
            edge_faces[edge_index].append(face_index)
            explorer.Next()
        face_edges[face_index] = indices

    faces: list[dict[str, Any]] = []
    for face_index in range(1, face_map.Extent() + 1):
        face = TopoDS.Face_s(face_map.FindKey(face_index))
        adaptor = BRepAdaptor_Surface(face, True)
        area, _ = measure_shape_mass_rtuple(face, "area")
        u0, u1 = adaptor.FirstUParameter(), adaptor.LastUParameter()
        v0, v1 = adaptor.FirstVParameter(), adaptor.LastVParameter()
        midpoint = adaptor.Value((u0 + u1) / 2.0, (v0 + v1) / 2.0)
        faces.append(
            {
                "index": face_index,
                "surface": _surface_parameters(adaptor),
                "area": area,
                "uv_bounds": [float(u0), float(u1), float(v0), float(v1)],
                "midpoint": xyz(midpoint),
                "edge_indices": face_edges[face_index],
            }
        )

    edges: list[dict[str, Any]] = []
    for edge_index in range(1, edge_map.Extent() + 1):
        edge = TopoDS.Edge_s(edge_map.FindKey(edge_index))
        length, midpoint = measure_shape_mass_rtuple(edge, "length")
        edges.append(
            {
                "index": edge_index,
                **_edge_parameters(edge),
                "length": length,
                "midpoint": midpoint.tolist(),
                "face_indices": edge_faces[edge_index],
            }
        )

    counts = {
        "solid": _count_occurrences(shape, TopAbs_SOLID),
        "shell": _count_occurrences(shape, TopAbs_SHELL),
        "face_occurrences": _count_occurrences(shape, TopAbs_FACE),
        "edge_occurrences": _count_occurrences(shape, TopAbs_EDGE),
        "vertex_occurrences": _count_occurrences(shape, TopAbs_VERTEX),
        "unique_faces": face_map.Extent(),
        "unique_edges": edge_map.Extent(),
        "unique_vertices": vertex_map.Extent(),
    }
    shell_closure = []
    shell_explorer = TopExp_Explorer(shape, TopAbs_SHELL)
    while shell_explorer.More():
        shell_closure.append(bool(BRep_Tool.IsClosed_s(shell_explorer.Current())))
        shell_explorer.Next()
    counts["open_shell"] = sum(not closed for closed in shell_closure)
    counts["closed_shell"] = sum(shell_closure)
    return BRepInspection(
        source=str(source) if source is not None else None,
        valid=bool(BRepCheck_Analyzer(shape).IsValid()),
        counts=counts,
        bounding_box=[float(value) for value in bounding_box.Get()],
        volume=volume,
        surface_area=surface_area,
        center_of_mass=center.tolist(),
        surface_type_counts=dict(Counter(face["surface"]["type"] for face in faces)),
        edge_type_counts=dict(Counter(edge["type"] for edge in edges)),
        faces=faces,
        edges=edges,
    )


def inspect_step_rbrepinspection(path: str | Path) -> BRepInspection:
    """Load and inspect one valid, single-root STEP file."""
    source = Path(path)
    return inspect_shape_rbrepinspection(load_step_rshape(source), source=source)

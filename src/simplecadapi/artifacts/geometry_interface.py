"""Stable geometry-interface descriptors independent of raw BRep bytes."""

from __future__ import annotations

import math
from collections import Counter
from typing import Any

from OCP.Bnd import Bnd_Box
from OCP.BRep import BRep_Tool
from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface
from OCP.BRepBndLib import BRepBndLib
from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps
from OCP.TopAbs import (
    TopAbs_EDGE,
    TopAbs_FACE,
    TopAbs_SHELL,
    TopAbs_SOLID,
    TopAbs_VERTEX,
    TopAbs_WIRE,
)
from OCP.TopExp import TopExp, TopExp_Explorer
from OCP.TopoDS import TopoDS, TopoDS_Shape
from OCP.TopTools import TopTools_IndexedMapOfShape

from ..core import Solid
from ..kernel.ocp_topology import vertex_point
from .canonical import canonical_bytes, content_hash

_GEOMETRY_INTERFACE_PROFILE = "simplecad-geometry-interface-1"
_DEFAULT_TOLERANCE = 1.0e-7
_BOUNDS_QUANTUM = 1.0e-4
_TOLERANCE_PROFILES = {
    "simplecad-default": _DEFAULT_TOLERANCE,
    "simplecad-strict": 1.0e-9,
    "simplecad-coarse": 1.0e-6,
}


def _tolerance_for_profile(profile: str) -> float:
    if not isinstance(profile, str) or not profile:
        raise ValueError("tolerance_profile must be a non-empty string")
    return _TOLERANCE_PROFILES.get(profile, _DEFAULT_TOLERANCE)


def _enum_suffix(value: Any, prefix: str) -> str:
    return str(value).split(".")[-1].removeprefix(prefix)


def _q(value: float, tolerance: float) -> int:
    return int(round(float(value) / tolerance))


def _qvec(values: Any, tolerance: float) -> tuple[int, ...]:
    return tuple(_q(float(value), tolerance) for value in values)


_JSON_SAFE_INT = 9_007_199_254_740_991


def _json_safe(value: Any) -> Any:
    """Quantized ints of large bodies (a 36 m slab's volume / 1e-7) pass the JSON safe range; hash them as
    decimal strings. Labels stay ints until here, so sorting and in-range hashes are unchanged."""
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return f"int:{value}" if abs(value) > _JSON_SAFE_INT else value
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return tuple(_json_safe(item) for item in value)
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


def _hash(payload: Any) -> str:
    return content_hash(_json_safe(payload), omit=())


def _raw_direction(values: Any, tolerance: float) -> list[float]:
    vector = [float(value) for value in values]
    magnitude = math.sqrt(sum(value * value for value in vector))
    if magnitude <= tolerance:
        raise ValueError("cannot canonicalize a zero direction")
    return [value / magnitude for value in vector]


def _canonical_direction(values: Any, tolerance: float) -> tuple[int, ...]:
    vector = _raw_direction(values, tolerance)
    for value in vector:
        if abs(value) > tolerance:
            if value < 0.0:
                vector = [-item for item in vector]
            break
    return _qvec(vector, tolerance)


def _canonical_axis(
    point: Any, direction: Any, tolerance: float
) -> tuple[tuple[int, ...], tuple[int, ...]]:
    unit = _raw_direction(direction, tolerance)
    for value in unit:
        if abs(value) > tolerance:
            if value < 0.0:
                unit = [-item for item in unit]
            break
    raw_point = [float(value) for value in point]
    projection = sum(raw_point[index] * unit[index] for index in range(3))
    closest = [raw_point[index] - projection * unit[index] for index in range(3)]
    return _qvec(closest, tolerance), _qvec(unit, tolerance)


def _canonical_plane(
    point: Any, normal: Any, tolerance: float
) -> tuple[tuple[int, ...], int]:
    unit = _raw_direction(normal, tolerance)
    distance = sum(float(point[index]) * unit[index] for index in range(3))
    for value in unit:
        if abs(value) > tolerance:
            if value < 0.0:
                unit = [-item for item in unit]
                distance = -distance
            break
    return _qvec(unit, tolerance), _q(distance, tolerance)


def _mass(shape: TopoDS_Shape, kind: str) -> tuple[float, tuple[float, float, float]]:
    properties = GProp_GProps()
    if kind == "volume":
        BRepGProp.VolumeProperties_s(shape, properties)
    elif kind == "area":
        BRepGProp.SurfaceProperties_s(shape, properties)
    elif kind == "length":
        BRepGProp.LinearProperties_s(shape, properties)
    else:
        raise ValueError(f"unsupported mass property kind: {kind}")
    point = properties.CentreOfMass()
    return float(properties.Mass()), (
        float(point.X()),
        float(point.Y()),
        float(point.Z()),
    )


def _bounds(shape: TopoDS_Shape, tolerance: float) -> tuple[Any, ...]:
    # Bounds are extents, not dimensional definitions: AddOptimal's result
    # wobbles by up to one shape-tolerance quantum between a freshly built
    # shape and the same shape read back from BRep bytes, so the quantization
    # grid must be far coarser than that wobble or the fingerprint flips on
    # every round-trip (observed as whole-graph refined-hash cascades).
    del tolerance
    box = Bnd_Box()
    box.SetGap(0.0)
    BRepBndLib.AddOptimal_s(shape, box, False, False)
    xmin, ymin, zmin, xmax, ymax, zmax = (float(value) for value in box.Get())
    return (
        _qvec((xmin, ymin, zmin), _BOUNDS_QUANTUM),
        _qvec((xmax, ymax, zmax), _BOUNDS_QUANTUM),
    )


def _point(value: Any) -> tuple[float, float, float]:
    return float(value.X()), float(value.Y()), float(value.Z())


def _direction(value: Any) -> tuple[float, float, float]:
    return float(value.X()), float(value.Y()), float(value.Z())


def _surface_definition_hash(
    adaptor: BRepAdaptor_Surface, kind: str, tolerance: float
) -> str:
    surface = adaptor.BSpline() if kind == "BSplineSurface" else adaptor.Bezier()
    u_count = int(surface.NbUPoles())
    v_count = int(surface.NbVPoles())
    rational = bool(surface.IsURational() or surface.IsVRational())
    payload: dict[str, Any] = {
        "kind": kind,
        "u_degree": int(surface.UDegree()),
        "v_degree": int(surface.VDegree()),
        "u_periodic": bool(surface.IsUPeriodic()),
        "v_periodic": bool(surface.IsVPeriodic()),
        "poles": [
            [
                _qvec(_point(surface.Pole(u, v)), tolerance)
                for v in range(1, v_count + 1)
            ]
            for u in range(1, u_count + 1)
        ],
        "weights": (
            [
                [_q(surface.Weight(u, v), tolerance) for v in range(1, v_count + 1)]
                for u in range(1, u_count + 1)
            ]
            if rational
            else None
        ),
    }
    if kind == "BSplineSurface":
        payload.update(
            u_knots=[
                _q(surface.UKnot(index), tolerance)
                for index in range(1, surface.NbUKnots() + 1)
            ],
            v_knots=[
                _q(surface.VKnot(index), tolerance)
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
        )
    return _hash(payload)


def _curve_definition_hash(
    adaptor: BRepAdaptor_Curve, kind: str, tolerance: float
) -> str:
    curve = adaptor.BSpline() if kind == "BSplineCurve" else adaptor.Bezier()
    rational = bool(curve.IsRational())
    payload: dict[str, Any] = {
        "kind": kind,
        "degree": int(curve.Degree()),
        "periodic": bool(curve.IsPeriodic()),
        "poles": [
            _qvec(_point(curve.Pole(index)), tolerance)
            for index in range(1, curve.NbPoles() + 1)
        ],
        "weights": (
            [
                _q(curve.Weight(index), tolerance)
                for index in range(1, curve.NbPoles() + 1)
            ]
            if rational
            else None
        ),
    }
    if kind == "BSplineCurve":
        payload.update(
            knots=[
                _q(curve.Knot(index), tolerance)
                for index in range(1, curve.NbKnots() + 1)
            ],
            multiplicities=[
                int(curve.Multiplicity(index))
                for index in range(1, curve.NbKnots() + 1)
            ],
        )
    return _hash(payload)


def _surface_samples(adaptor: BRepAdaptor_Surface, tolerance: float) -> tuple[Any, ...]:
    bounds = (
        float(adaptor.FirstUParameter()),
        float(adaptor.LastUParameter()),
        float(adaptor.FirstVParameter()),
        float(adaptor.LastVParameter()),
    )
    if not all(math.isfinite(value) for value in bounds):
        return ()
    u0, u1, v0, v1 = bounds
    return tuple(
        _qvec(_point(adaptor.Value(u0 + (u1 - u0) * u, v0 + (v1 - v0) * v)), tolerance)
        for u in (0.0, 0.5, 1.0)
        for v in (0.0, 0.5, 1.0)
    )


def _curve_samples(adaptor: BRepAdaptor_Curve, tolerance: float) -> tuple[Any, ...]:
    first = float(adaptor.FirstParameter())
    last = float(adaptor.LastParameter())
    if not math.isfinite(first) or not math.isfinite(last):
        return ()
    return tuple(
        _qvec(_point(adaptor.Value(first + (last - first) * ratio)), tolerance)
        for ratio in (0.0, 0.25, 0.5, 0.75, 1.0)
    )


def _surface_parameters(face: TopoDS_Shape, tolerance: float) -> tuple[Any, ...]:
    adaptor = BRepAdaptor_Surface(TopoDS.Face_s(face), True)
    kind = _enum_suffix(adaptor.GetType(), "GeomAbs_")
    try:
        if kind == "Plane":
            plane = adaptor.Plane()
            return (
                kind,
                _canonical_plane(
                    _point(plane.Location()),
                    _direction(plane.Axis().Direction()),
                    tolerance,
                ),
            )
        if kind == "Cylinder":
            cylinder = adaptor.Cylinder()
            return (
                kind,
                _q(cylinder.Radius(), tolerance),
                _canonical_axis(
                    _point(cylinder.Location()),
                    _direction(cylinder.Axis().Direction()),
                    tolerance,
                ),
            )
        if kind == "Cone":
            cone = adaptor.Cone()
            return (
                kind,
                _q(cone.RefRadius(), tolerance),
                _q(float(cone.SemiAngle()), tolerance),
                _canonical_axis(
                    _point(cone.Location()),
                    _direction(cone.Axis().Direction()),
                    tolerance,
                ),
                _qvec(_point(cone.Apex()), tolerance),
            )
        if kind == "Sphere":
            sphere = adaptor.Sphere()
            return (
                kind,
                _q(sphere.Radius(), tolerance),
                _qvec(_point(sphere.Location()), tolerance),
            )
        if kind == "Torus":
            torus = adaptor.Torus()
            return (
                kind,
                _q(torus.MajorRadius(), tolerance),
                _q(torus.MinorRadius(), tolerance),
                _qvec(_point(torus.Location()), tolerance),
                _canonical_direction(_direction(torus.Axis().Direction()), tolerance),
            )
        if kind in {"BSplineSurface", "BezierSurface"}:
            return (kind, _surface_definition_hash(adaptor, kind, tolerance))
        if kind == "SurfaceOfRevolution":
            axis = adaptor.AxeOfRevolution()
            return (
                kind,
                _canonical_axis(
                    _point(axis.Location()), _direction(axis.Direction()), tolerance
                ),
                _surface_samples(adaptor, tolerance),
            )
        if kind == "SurfaceOfExtrusion":
            return (
                kind,
                _canonical_direction(_direction(adaptor.Direction()), tolerance),
                _surface_samples(adaptor, tolerance),
            )
        if kind == "OffsetSurface":
            return (
                kind,
                _q(adaptor.OffsetValue(), tolerance),
                _surface_samples(adaptor, tolerance),
            )
    except Exception:
        return (kind, "parameters-unavailable", _surface_samples(adaptor, tolerance))
    return (kind, _surface_samples(adaptor, tolerance))


def _curve_parameters(edge: TopoDS_Shape, tolerance: float) -> tuple[Any, ...]:
    edge_value = TopoDS.Edge_s(edge)
    if BRep_Tool.Degenerated_s(edge_value):
        return ("DEGENERATE",)
    adaptor = BRepAdaptor_Curve(edge_value)
    kind = _enum_suffix(adaptor.GetType(), "GeomAbs_")
    try:
        if kind == "Line":
            line = adaptor.Line()
            return (
                kind,
                _canonical_axis(
                    _point(line.Location()), _direction(line.Direction()), tolerance
                ),
            )
        if kind == "Circle":
            circle = adaptor.Circle()
            return (
                kind,
                _q(circle.Radius(), tolerance),
                _qvec(_point(circle.Location()), tolerance),
                _canonical_direction(_direction(circle.Axis().Direction()), tolerance),
            )
        if kind == "Ellipse":
            ellipse = adaptor.Ellipse()
            return (
                kind,
                _q(ellipse.MajorRadius(), tolerance),
                _q(ellipse.MinorRadius(), tolerance),
                _qvec(_point(ellipse.Location()), tolerance),
                _canonical_direction(_direction(ellipse.Axis().Direction()), tolerance),
                _canonical_direction(
                    _direction(ellipse.XAxis().Direction()), tolerance
                ),
            )
        if kind == "Hyperbola":
            hyperbola = adaptor.Hyperbola()
            return (
                kind,
                _q(hyperbola.MajorRadius(), tolerance),
                _q(hyperbola.MinorRadius(), tolerance),
                _qvec(_point(hyperbola.Location()), tolerance),
                _canonical_direction(
                    _direction(hyperbola.Axis().Direction()), tolerance
                ),
                _canonical_direction(
                    _direction(hyperbola.XAxis().Direction()), tolerance
                ),
            )
        if kind == "Parabola":
            parabola = adaptor.Parabola()
            return (
                kind,
                _q(parabola.Focal(), tolerance),
                _qvec(_point(parabola.Location()), tolerance),
                _canonical_direction(
                    _direction(parabola.Axis().Direction()), tolerance
                ),
                _canonical_direction(
                    _direction(parabola.XAxis().Direction()), tolerance
                ),
            )
        if kind in {"BSplineCurve", "BezierCurve"}:
            return (kind, _curve_definition_hash(adaptor, kind, tolerance))
    except Exception:
        return (kind, "parameters-unavailable", _curve_samples(adaptor, tolerance))
    return (kind, _curve_samples(adaptor, tolerance))


def _shape_index_map(shape: TopoDS_Shape, kind: Any) -> TopTools_IndexedMapOfShape:
    result = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, kind, result)
    return result


def _entity_index(indexed: TopTools_IndexedMapOfShape, shape: TopoDS_Shape) -> int:
    value = int(indexed.FindIndex(shape))
    if value <= 0:
        raise ValueError("shape is not present in indexed topology map")
    return value - 1


def _explore(shape: TopoDS_Shape, kind: Any) -> list[TopoDS_Shape]:
    explorer = TopExp_Explorer(shape, kind)
    result: list[TopoDS_Shape] = []
    while explorer.More():
        result.append(explorer.Current())
        explorer.Next()
    return result


def _geometry_label(
    kind: str, shape: TopoDS_Shape, tolerance: float
) -> tuple[Any, ...]:
    if kind == "body":
        volume, center = _mass(shape, "volume")
        area, _ = _mass(shape, "area")
        return (
            kind,
            _q(volume, tolerance),
            _q(area, tolerance),
            _qvec(center, tolerance),
            _bounds(shape, tolerance),
        )
    if kind == "face":
        area, center = _mass(shape, "area")
        return (
            kind,
            _surface_parameters(shape, tolerance),
            _q(area, tolerance),
            _qvec(center, tolerance),
            _bounds(shape, tolerance),
        )
    if kind == "edge":
        edge = TopoDS.Edge_s(shape)
        length, center = _mass(shape, "length")
        vertices = [
            vertex_point(TopoDS.Vertex_s(vertex))
            for vertex in _explore(shape, TopAbs_VERTEX)
        ]
        samples = ()
        if not BRep_Tool.Degenerated_s(edge):
            samples = tuple(sorted(_curve_samples(BRepAdaptor_Curve(edge), tolerance)))
        return (
            kind,
            _curve_parameters(shape, tolerance),
            _q(length, tolerance),
            _qvec(center, tolerance),
            tuple(sorted(_qvec(item, tolerance) for item in vertices)),
            samples,
        )
    return (kind, _qvec(vertex_point(TopoDS.Vertex_s(shape)), tolerance))


def stable_topology_entity_hash(
    shape: TopoDS_Shape,
    kind: str,
    *,
    tolerance_profile: str = "simplecad-default",
) -> str:
    """Hash one topology carrier by normalized geometry, never BRep bytes."""

    tolerance = _tolerance_for_profile(tolerance_profile)
    normalized_kind = str(kind).lower()
    if normalized_kind == "solid":
        geometry: Any = _geometry_label("body", shape, tolerance)
    elif normalized_kind == "shell":
        geometry = (
            "shell",
            _bounds(shape, tolerance),
            tuple(
                sorted(
                    _geometry_label("face", item, tolerance)
                    for item in _explore(shape, TopAbs_FACE)
                )
            ),
        )
    elif normalized_kind == "wire":
        geometry = (
            "wire",
            _bounds(shape, tolerance),
            tuple(
                sorted(
                    _geometry_label("edge", item, tolerance)
                    for item in _explore(shape, TopAbs_EDGE)
                )
            ),
        )
    elif normalized_kind in {"face", "edge", "vertex"}:
        geometry = _geometry_label(normalized_kind, shape, tolerance)
    else:
        raise ValueError(f"unsupported topology entity kind: {kind}")
    return _hash(
        {
            "profile": "simplecad-topology-entity-1",
            "kind": normalized_kind,
            "geometry": geometry,
        }
    )


def geometry_interface_descriptor(
    solid: Solid,
    *,
    tolerance_profile: str = "simplecad-default",
) -> dict[str, Any]:
    """Return a traversal-independent, non-BRep-byte geometry descriptor."""

    if not isinstance(solid, Solid):
        raise TypeError("solid must be a Solid")
    tolerance = _tolerance_for_profile(tolerance_profile)
    shape = solid.wrapped
    maps = {
        "body": _shape_index_map(shape, TopAbs_SOLID),
        "face": _shape_index_map(shape, TopAbs_FACE),
        "edge": _shape_index_map(shape, TopAbs_EDGE),
        "vertex": _shape_index_map(shape, TopAbs_VERTEX),
    }
    nodes: dict[tuple[str, int], dict[str, Any]] = {}
    adjacency: dict[tuple[str, int], Counter[tuple[str, int]]] = {}

    def add_node(key: tuple[str, int], label: tuple[Any, ...]) -> None:
        nodes[key] = {"kind": key[0], "label": label}
        adjacency.setdefault(key, Counter())

    def link(first: tuple[str, int], second: tuple[str, int]) -> None:
        adjacency.setdefault(first, Counter())[second] += 1
        adjacency.setdefault(second, Counter())[first] += 1

    for kind in ("body", "face", "edge", "vertex"):
        indexed = maps[kind]
        for index in range(1, indexed.Extent() + 1):
            add_node(
                (kind, index - 1),
                _geometry_label(kind, indexed.FindKey(index), tolerance),
            )

    for body_index in range(maps["body"].Extent()):
        body = TopoDS.Solid_s(maps["body"].FindKey(body_index + 1))
        for face in _explore(body, TopAbs_FACE):
            link(
                ("body", body_index),
                ("face", _entity_index(maps["face"], face)),
            )
    for face_index in range(maps["face"].Extent()):
        face = TopoDS.Face_s(maps["face"].FindKey(face_index + 1))
        for edge in _explore(face, TopAbs_EDGE):
            link(
                ("face", face_index),
                ("edge", _entity_index(maps["edge"], edge)),
            )
    for edge_index in range(maps["edge"].Extent()):
        edge = TopoDS.Edge_s(maps["edge"].FindKey(edge_index + 1))
        for vertex in _explore(edge, TopAbs_VERTEX):
            link(
                ("edge", edge_index),
                ("vertex", _entity_index(maps["vertex"], vertex)),
            )

    refined: dict[tuple[str, int], str] = {
        key: _hash({"kind": value["kind"], "geometry": value["label"]})
        for key, value in nodes.items()
    }
    for _ in range(4):
        refined = {
            key: content_hash(
                {
                    "kind": nodes[key]["kind"],
                    "self": refined[key],
                    "neighbors": sorted(
                        neighbor_hash
                        for item, multiplicity in adjacency[key].items()
                        for neighbor_hash in [refined[item]] * multiplicity
                    ),
                },
                omit=(),
            )
            for key in nodes
        }

    node_records = [
        {
            "kind": value["kind"],
            "geometry": _json_safe(value["label"]),
            "refined": refined[key],
            "incidence_count": sum(adjacency[key].values()),
        }
        for key, value in nodes.items()
    ]
    node_records.sort(key=canonical_bytes)
    counts = Counter(value["kind"] for value in nodes.values())
    volume, centroid = _mass(shape, "volume")
    surface_area, _ = _mass(shape, "area")
    return _json_safe({
        "profile": _GEOMETRY_INTERFACE_PROFILE,
        "tolerance_profile": tolerance_profile,
        "tolerance": tolerance,
        "body_count": counts["body"],
        "face_count": counts["face"],
        "edge_count": counts["edge"],
        "vertex_count": counts["vertex"],
        "bounds": _bounds(shape, tolerance),
        "volume": _q(volume, tolerance),
        "surface_area": _q(surface_area, tolerance),
        "centroid": _qvec(centroid, tolerance),
        "nodes": node_records,
    })


def geometry_interface_fingerprint(
    solid: Solid,
    *,
    tolerance_profile: str = "simplecad-default",
) -> str:
    """Hash normalized geometry/topology descriptors, never raw BRep bytes."""

    descriptor = geometry_interface_descriptor(
        solid,
        tolerance_profile=tolerance_profile,
    )
    return _hash(descriptor)


__all__ = [
    "geometry_interface_descriptor",
    "geometry_interface_fingerprint",
    "stable_topology_entity_hash",
]

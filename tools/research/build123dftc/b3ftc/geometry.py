"""Kernel-independent JSON descriptions of build123d profile geometry.

The trace contains analytic curves and NURBS control data, never a saved BRep.
Coordinates are in the coordinate system of the actual feature input.
"""
from __future__ import annotations

from enum import Enum
import math
from typing import Any


def vector(value: Any) -> list[float]:
    if hasattr(value, "X"):
        return [float(getattr(value, n)() if callable(getattr(value, n)) else getattr(value, n)) for n in "XYZ"]
    if hasattr(value, "x"):
        return [float(value.x), float(value.y), float(value.z)]
    return [float(value.X()), float(value.Y()), float(value.Z())]


def plane(value: Any) -> dict[str, Any]:
    return {"origin": vector(value.origin), "x_dir": vector(value.x_dir),
            "y_dir": vector(value.y_dir), "normal": vector(value.z_dir)}


def location_matrix(value: Any) -> list[list[float]]:
    trsf = value.wrapped.Transformation()
    return [[float(trsf.Value(i, j)) for j in range(1, 5)] for i in range(1, 4)] + [[0., 0., 0., 1.]]


def serialize(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, Enum):
        return value.name
    if isinstance(value, dict):
        return {str(k): serialize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [serialize(v) for v in value]
    name = type(value).__name__
    if name == "Plane":
        return plane(value)
    if name == "Axis":
        return {"origin": vector(value.position), "direction": vector(value.direction)}
    if name in {"Location", "Rotation", "Pos", "Rot"} or hasattr(value, "wrapped") and hasattr(value.wrapped, "Transformation"):
        return {"matrix": location_matrix(value)}
    if name == "Matrix":
        return {"matrix": [[float(value.wrapped.Value(i, j)) for j in range(1, 5)] for i in range(1, 4)] + [[0., 0., 0., 1.]]}
    if name == "Vector":
        return vector(value)
    if hasattr(value, "wrapped"):
        return {"shape_type": name}
    return {"type": name, "repr": repr(value)}


def metrics(shape: Any) -> dict[str, Any]:
    from simplecadapi._cpp.occt.BRepGProp import BRepGProp
    from simplecadapi._cpp.occt.GProp import GProp_GProps
    shapes = shape if isinstance(shape, (list, tuple)) else [shape]
    solids = [s for item in shapes if item is not None for s in item.solids()]
    if not solids:
        return {"volume": 0., "bbox": None, "solid_count": 0}
    boxes = [s.bounding_box() for s in solids]
    low = [min(vector(box.min)[i] for box in boxes) for i in range(3)]
    high = [max(vector(box.max)[i] for box in boxes) for i in range(3)]
    volumes, areas = [], []
    for solid in solids:
        properties = GProp_GProps()
        BRepGProp.VolumePropertiesGK_s(solid.wrapped, properties, 1e-9, True, True)
        volumes.append(float(properties.Mass()))
        areas.append(surface_area(solid.wrapped))
    return {"volume": sum(volumes), "volume_gk": sum(volumes), "area": sum(areas), "default_volume": sum(float(s.volume) for s in solids), "bbox": low + high,
            "solid_count": len(solids)}


def surface_area(wrapped: Any) -> float:
    """Integrate per smooth span on a geometry copy, preserving the source model.

    OCCT's adaptive surface integrator can miss rational spline knot breaks.
    Splitting C0 boundaries/surfaces into C1 spans resolves those breaks before
    integration. This temporary topology is used only for the numeric metric.
    """
    from simplecadapi._cpp.occt.BRepBuilderAPI import BRepBuilderAPI_Copy
    from simplecadapi._cpp.occt.ShapeUpgrade import ShapeUpgrade_ShapeDivideContinuity
    from simplecadapi._cpp.occt.GeomAbs import GeomAbs_C1
    from simplecadapi._cpp.occt.BRepGProp import BRepGProp
    from simplecadapi._cpp.occt.GProp import GProp_GProps
    copied = BRepBuilderAPI_Copy(wrapped, True, False).Shape()
    divider = ShapeUpgrade_ShapeDivideContinuity(copied)
    divider.SetSurfaceCriterion(GeomAbs_C1)
    divider.SetBoundaryCriterion(GeomAbs_C1)
    divider.SetPCurveCriterion(GeomAbs_C1)
    divider.Perform()
    properties = GProp_GProps()
    BRepGProp.SurfaceProperties_s(S=divider.Result(), SProps=properties, Eps=1e-10, SkipShared=False)
    return float(properties.Mass())


def fingerprint(shape: Any, parent: Any = None) -> dict[str, Any]:
    from build123d import CenterOf
    kind = type(shape).__name__.lower()
    payload = {"kind": kind, "geom_type": shape.geom_type.name,
               "center": vector(shape.center(CenterOf.MASS)) if kind in {"edge", "face"} else vector(shape.center()),
               "bbox": vector(shape.bounding_box().min) + vector(shape.bounding_box().max)}
    if kind in {"edge", "wire"}:
        payload["length"] = float(shape.length)
        payload["start"] = vector(shape.position_at(0))
        payload["mid"] = vector(shape.position_at(.5))
        payload["end"] = vector(shape.position_at(1))
    if kind == "face":
        payload["area"] = float(shape.area)
        if shape.geom_type.name == "PLANE":
            try:
                payload["normal"] = vector(shape.normal_at())
            except Exception:
                pass
    if parent is not None:
        children = parent.edges() if kind == "edge" else parent.faces() if kind == "face" else parent.vertices()
        for index, child in enumerate(children):
            if child.wrapped.IsSame(shape.wrapped):
                payload["index"] = index
                break
    return payload


def edge(value: Any) -> dict[str, Any]:
    from simplecadapi._cpp.occt.BRepAdaptor import BRepAdaptor_Curve
    adaptor = BRepAdaptor_Curve(value.wrapped)
    kind = value.geom_type.name.lower()
    first, last = adaptor.FirstParameter(), adaptor.LastParameter()
    common = {"start": vector(value.position_at(0)), "end": vector(value.position_at(1)),
              "parameter_range": [float(first), float(last)], "reversed": not value.is_forward}
    if kind == "line":
        return {"kind": "line", **common}
    if kind == "circle":
        circle = adaptor.Circle()
        data = {"center": vector(circle.Location()), "radius": float(circle.Radius()),
                "normal": vector(circle.Axis().Direction()), "x_dir": vector(circle.XAxis().Direction())}
        if abs(last - first - 2 * math.pi) < 1e-7:
            return {"kind": "circle", **common, **data}
        return {"kind": "arc", "mid": vector(value.position_at(.5)), **common, **data}
    if kind == "ellipse" and abs(last - first - 2 * math.pi) < 1e-7:
        ellipse = adaptor.Ellipse()
        return {"kind": "ellipse", **common, "center": vector(ellipse.Location()),
                "major_radius": float(ellipse.MajorRadius()), "minor_radius": float(ellipse.MinorRadius()),
                "x_dir": vector(ellipse.XAxis().Direction()), "y_dir": vector(ellipse.YAxis().Direction()),
                "normal": vector(ellipse.Axis().Direction())}
    if kind in {"bspline", "bezier", "ellipse", "parabola", "hyperbola"}:
        # Segmentation preserves the exact trimmed curve, including NURBS weights.
        # Conic arcs become exact rational BSplines rather than sampled polylines.
        if kind not in {"bspline", "bezier"}:
            from simplecadapi._cpp.occt.Geom import Geom_TrimmedCurve
            from simplecadapi._cpp.occt.GeomConvert import GeomConvert
            from simplecadapi._cpp.occt.BRep import BRep_Tool
            curve = BRep_Tool.Curve_s(value.wrapped, first, last)
            spline = GeomConvert.CurveToBSplineCurve_s(Geom_TrimmedCurve(curve, first, last))
            kind = "bspline"
        else:
            spline = adaptor.BSpline() if kind == "bspline" else adaptor.Bezier()
            unclamped = kind == "bspline" and not spline.IsPeriodic() and (spline.Multiplicity(1) < spline.Degree()+1 or spline.Multiplicity(spline.NbKnots()) < spline.Degree()+1)
            if unclamped or abs(first - spline.FirstParameter()) > 1e-9 or abs(last - spline.LastParameter()) > 1e-9:
                spline = spline.Copy()
                spline.Segment(first, last)
        # Converted/segmented poles already describe exactly the edge extent.
        common["parameter_range"] = [float(spline.FirstParameter()), float(spline.LastParameter())]
        data = {"kind": kind, **common, "degree": spline.Degree(),
                "poles": [vector(spline.Pole(i)) for i in range(1, spline.NbPoles() + 1)],
                "weights": [float(spline.Weight(i)) for i in range(1, spline.NbPoles() + 1)]}
        if kind == "bspline":
            data.update(knots=[float(spline.Knot(i)) for i in range(1, spline.NbKnots() + 1)],
                        multiplicities=[spline.Multiplicity(i) for i in range(1, spline.NbKnots() + 1)],
                        periodic=spline.IsPeriodic())
        return data
    # Conics are kept analytic as a full parameterized curve description.
    if kind in {"parabola", "hyperbola"}:
        conic = adaptor.Parabola() if kind == "parabola" else adaptor.Hyperbola()
        data = {"kind": kind, **common, "center": vector(conic.Location()),
                "x_dir": vector(conic.XAxis().Direction()), "normal": vector(conic.Axis().Direction())}
        if kind == "parabola":
            data["focal"] = float(conic.Focal())
        else:
            data.update(major_radius=float(conic.MajorRadius()), minor_radius=float(conic.MinorRadius()))
        return data
    raise ValueError(f"Unsupported profile curve: {value.geom_type.name}")


def wire(value: Any) -> dict[str, Any]:
    from build123d import Edge
    from simplecadapi._cpp.occt.BRepTools import BRepTools_WireExplorer
    explorer = BRepTools_WireExplorer(value.wrapped)
    edges = []
    while explorer.More():
        edges.append(edge(Edge(explorer.Current())))
        explorer.Next()
    return {"edges": edges, "closed": bool(value.is_closed)}


def profile(value: Any) -> dict[str, Any]:
    from build123d import Face, Plane, Vertex, Wire
    if isinstance(value, Vertex):
        return {"kind": "vertex", "point": vector(value.center())}
    if isinstance(value, Wire):
        value = Face(value)
    if not isinstance(value, Face):
        raise ValueError(f"A planar profile was expected, got {type(value).__name__}")
    frame = Plane(value)
    return {"kind": "face", **plane(frame),
            "wires": [wire(value.outer_wire())] + [wire(w) for w in value.inner_wires()]}


def path(value: Any) -> dict[str, Any]:
    from build123d import Edge, Wire
    if isinstance(value, Edge):
        return {"edges": [edge(value)], "closed": bool(value.is_closed)}
    if not isinstance(value, Wire):
        value = Wire(value.edges())
    result = wire(value)
    try:
        frame = value.find_plane()
        if frame is not None:
            result.update(planar=True, **plane(frame))
    except Exception:
        pass
    return result

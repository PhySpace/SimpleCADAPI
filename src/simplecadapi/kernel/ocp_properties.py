"""OCP-native geometry properties, bounding boxes, distance and normals."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence, Tuple

from simplecadapi._cpp.occt.Bnd import Bnd_Box
from simplecadapi._cpp.occt.BRep import BRep_Tool
from simplecadapi._cpp.occt.BRepAdaptor import BRepAdaptor_Surface
from simplecadapi._cpp.occt.BRepBndLib import BRepBndLib
from simplecadapi._cpp.occt.BRepExtrema import BRepExtrema_DistShapeShape
from simplecadapi._cpp.occt.BRepGProp import BRepGProp
from simplecadapi._cpp.occt.BRepLProp import BRepLProp_SLProps
from simplecadapi._cpp.occt.GProp import GProp_GProps
from simplecadapi._cpp.occt.GeomAbs import GeomAbs_Plane
import math

from simplecadapi._cpp.occt.TopAbs import (
    TopAbs_COMPOUND,
    TopAbs_COMPSOLID,
    TopAbs_EDGE,
    TopAbs_FACE,
    TopAbs_REVERSED,
    TopAbs_SHELL,
    TopAbs_SOLID,
    TopAbs_VERTEX,
    TopAbs_WIRE,
)
from simplecadapi._cpp.occt.TopoDS import TopoDS, TopoDS_Edge, TopoDS_Face, TopoDS_Shape, TopoDS_Solid
from simplecadapi._cpp.occt.gp import gp_Pnt, gp_Vec

from .ocp_topology import vertex_point


@dataclass(frozen=True)
class Vec3:
    x: float
    y: float
    z: float

    def __iter__(self):
        yield self.x
        yield self.y
        yield self.z

    def to_tuple(self) -> tuple[float, float, float]:
        return (self.x, self.y, self.z)

    def dot(self, other: object) -> float:
        ox, oy, oz = _coerce_vec3(other)
        return self.x * ox + self.y * oy + self.z * oz

    def norm(self) -> float:
        return math.sqrt(self.dot(self))

    def normalized(self) -> "Vec3":
        n = self.norm()
        if n <= 1e-15:
            raise ValueError("Cannot normalize a zero-length vector")
        return Vec3(self.x / n, self.y / n, self.z / n)

    def getAngle(self, other: object) -> float:
        ox, oy, oz = _coerce_vec3(other)
        on = math.sqrt(ox * ox + oy * oy + oz * oz)
        sn = self.norm()
        if sn <= 1e-15 or on <= 1e-15:
            raise ValueError("Cannot compute angle with a zero-length vector")
        value = max(-1.0, min(1.0, self.dot((ox, oy, oz)) / (sn * on)))
        return math.acos(value)

    def __mul__(self, scalar: float) -> "Vec3":
        return Vec3(self.x * float(scalar), self.y * float(scalar), self.z * float(scalar))

    __rmul__ = __mul__

    def __repr__(self) -> str:
        return f"Vec3({self.x:.6g}, {self.y:.6g}, {self.z:.6g})"


def _coerce_vec3(value: object) -> tuple[float, float, float]:
    if isinstance(value, Vec3):
        return value.to_tuple()
    if hasattr(value, "x") and hasattr(value, "y") and hasattr(value, "z"):
        return (float(getattr(value, "x")), float(getattr(value, "y")), float(getattr(value, "z")))
    if isinstance(value, (tuple, list)) and len(value) == 3:
        return (float(value[0]), float(value[1]), float(value[2]))
    raise TypeError(f"Expected a 3D vector-like value, got {type(value).__name__}")


def _props_point(props: GProp_GProps) -> Vec3:
    p = props.CentreOfMass()
    return Vec3(float(p.X()), float(p.Y()), float(p.Z()))


def linear_length(edge: TopoDS_Edge) -> float:
    props = GProp_GProps()
    BRepGProp.LinearProperties_s(edge, props)
    return float(props.Mass())


def surface_area(face: TopoDS_Face) -> float:
    props = GProp_GProps()
    BRepGProp.SurfaceProperties_s(face, props)
    return float(props.Mass())


def volume(solid: TopoDS_Solid) -> float:
    props = GProp_GProps()
    # Integrate NURBS by knot spans. The fixed-order routine both loses
    # precision on rational curves and can crash on affine transformed trims.
    BRepGProp.VolumePropertiesGK_s(solid, props, 1e-9, True, True)
    return float(props.Mass())


def _bbox_center(shape: TopoDS_Shape) -> Vec3:
    bb = bounding_box(shape)
    return Vec3((bb.xmin + bb.xmax) / 2, (bb.ymin + bb.ymax) / 2, (bb.zmin + bb.zmax) / 2)


def _props_mass_point(props: GProp_GProps, eps: float = 1e-12) -> Vec3 | None:
    """Return the CentreOfMass when the reported mass is meaningfully nonzero."""
    try:
        mass = float(props.Mass())
    except Exception:
        return None
    if abs(mass) <= eps:
        return None
    return _props_point(props)


def center_of_mass(shape: TopoDS_Shape) -> Vec3:
    """Dimension-aware centre of mass.

    Selects the OCP mass-properties routine that matches the shape's own
    topological dimension. This avoids the numerical residue that
    ``VolumeProperties_s`` produces when applied to lower-dimensional shapes
    (e.g. a planar face), which previously leaked a bogus centre into
    ``Face.get_center()``.
    """

    try:
        kind = shape.ShapeType()
    except Exception:
        kind = None

    # Solids / compsolids / compounds carry a meaningful volume.
    if kind in (TopAbs_SOLID, TopAbs_COMPSOLID, TopAbs_COMPOUND):
        props = GProp_GProps()
        try:
            BRepGProp.VolumePropertiesGK_s(shape, props, 1e-9, True, True)
            point = _props_mass_point(props)
            if point is not None:
                return point
        except Exception:
            pass
        # A compound may wrap only faces/edges; fall through to the
        # lower-dimensional properties below.
        if kind == TopAbs_COMPOUND:
            try:
                BRepGProp.SurfaceProperties_s(shape, props)
                point = _props_mass_point(props)
                if point is not None:
                    return point
            except Exception:
                pass
            try:
                BRepGProp.LinearProperties_s(shape, props)
                point = _props_mass_point(props)
                if point is not None:
                    return point
            except Exception:
                pass
        return _bbox_center(shape)

    # Shells / faces are 2D -> use surface properties.
    if kind in (TopAbs_FACE, TopAbs_SHELL):
        props = GProp_GProps()
        try:
            BRepGProp.SurfaceProperties_s(shape, props)
            point = _props_mass_point(props)
            if point is not None:
                return point
        except Exception:
            pass
        return _bbox_center(shape)

    # Wires / edges are 1D -> use linear properties.
    if kind in (TopAbs_WIRE, TopAbs_EDGE):
        props = GProp_GProps()
        try:
            BRepGProp.LinearProperties_s(shape, props)
            point = _props_mass_point(props)
            if point is not None:
                return point
        except Exception:
            pass
        return _bbox_center(shape)

    # Vertex is a point.
    if kind == TopAbs_VERTEX:
        try:
            return Vec3(*vertex_point(TopoDS.Vertex_s(shape)))
        except Exception:
            pass
        return _bbox_center(shape)

    # Unknown / undetermined kind: fall back to bbox centre.
    return _bbox_center(shape)


@dataclass(frozen=True)
class BoundingBox:
    xmin: float
    ymin: float
    zmin: float
    xmax: float
    ymax: float
    zmax: float

    @property
    def xlen(self) -> float:
        return self.xmax - self.xmin

    @property
    def ylen(self) -> float:
        return self.ymax - self.ymin

    @property
    def zlen(self) -> float:
        return self.zmax - self.zmin


def bounding_box(shape: TopoDS_Shape) -> BoundingBox:
    box = Bnd_Box()
    box.SetGap(0.0)
    BRepBndLib.AddOptimal_s(shape, box, False, False)
    xmin, ymin, zmin, xmax, ymax, zmax = box.Get()
    return BoundingBox(float(xmin), float(ymin), float(zmin), float(xmax), float(ymax), float(zmax))


def distance(shape_a: TopoDS_Shape, shape_b: TopoDS_Shape) -> float:
    dist = BRepExtrema_DistShapeShape(shape_a, shape_b)
    dist.Perform()
    if not dist.IsDone():
        raise ValueError("OCP distance calculation failed")
    return float(dist.Value())


def face_normal_at(face: TopoDS_Face, u: float = 0.5, v: float = 0.5) -> Vec3:
    adaptor = BRepAdaptor_Surface(face, True)
    umin = float(adaptor.FirstUParameter())
    umax = float(adaptor.LastUParameter())
    vmin = float(adaptor.FirstVParameter())
    vmax = float(adaptor.LastVParameter())
    uu = umin + (umax - umin) * float(u)
    vv = vmin + (vmax - vmin) * float(v)
    props = BRepLProp_SLProps(adaptor, uu, vv, 1, 1e-7)
    if not props.IsNormalDefined():
        raise ValueError("Face normal is not defined at the requested parameters")
    n = props.Normal()
    if face.Orientation() == TopAbs_REVERSED:
        n.Reverse()
    return Vec3(float(n.X()), float(n.Y()), float(n.Z()))


def edge_center(edge: TopoDS_Edge) -> Vec3:
    return center_of_mass(edge)

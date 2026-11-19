"""Physical model projection and cached view geometry for engineering sheets."""

from dataclasses import replace

from simplecadapi._cpp.occt.BRep import BRep_Builder
from simplecadapi._cpp.occt.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface
from simplecadapi._cpp.occt.BRepBndLib import BRepBndLib
from simplecadapi._cpp.occt.Bnd import Bnd_Box
from simplecadapi._cpp.occt.GeomAbs import (
    GeomAbs_BSplineCurve,
    GeomAbs_BSplineSurface,
    GeomAbs_Line,
)
from simplecadapi._cpp.occt.TopAbs import TopAbs_SOLID
from simplecadapi._cpp.occt.TopoDS import TopoDS_Compound
from simplecadapi.dxf_engine.refs import view_frame
from simplecadapi.dxf_engine.views import build_view, _cut_near_half, _section_loops
from simplecadapi.inspect import brep

from .inspection import rigid_shape

MESH_DEFLECTION_MM = 0.02


def physical_shape(shape, model=None):
    """Exclude free PMI presentation or construction geometry from drawing measures."""
    if shape.ShapeType() == TopAbs_SOLID:
        return shape
    model = model or brep.index_shape_rbrepmodel(shape=shape)
    if not model.bodies:
        return shape
    if len(model.bodies) == 1:
        return model.bodies[0]
    compound = TopoDS_Compound()
    builder = BRep_Builder()
    builder.MakeCompound(compound)
    for body in model.bodies:
        builder.Add(compound, body)
    return compound


def projected_bounds(shape, frame):
    projected = rigid_shape(shape, dict(rotation=frame, translation_mm=(0, 0, 0)))
    box = Bnd_Box()
    BRepBndLib.AddOptimal_s(projected, box, False, False)
    x0, y0, _, x1, y1, _ = box.Get()
    return x0, y0, x1, y1


def projection_mode(model):
    spline_faces = sum(
        BRepAdaptor_Surface(face).GetType() == GeomAbs_BSplineSurface
        for face in model.faces
    )
    spline_edges = sum(
        BRepAdaptor_Curve(edge).GetType() == GeomAbs_BSplineCurve
        for edge in model.edges
    )
    # Repeated spline flanks with many spline intersections are costly for
    # exact HLR in some cameras, even when the solid has few faces.
    approximate = (
        spline_faces >= 6
        and spline_edges >= 32
        and spline_edges * 2 >= len(model.edges)
    )
    return ("polygonal" if approximate else "exact"), dict(
        faces=len(model.faces),
        edges=len(model.edges),
        spline_faces=spline_faces,
        spline_edges=spline_edges,
    )


class ProjectedLine:
    def GetType(self):
        return GeomAbs_Line


LINE = ProjectedLine()


class DrawingProjection:
    def __init__(self, shape, mode="exact", deflection_mm=None):
        self.shape = shape
        self.mode = mode
        self.deflection_mm = deflection_mm
        self.cache = {}
        self.mesh = None

    def view(self, view, bounds=None):
        key = (
            view.shape,
            tuple(view.n),
            tuple(view.xd),
            tuple(view.section) if view.section is not None else None,
        )
        cached = self.cache.get(key)
        if cached is None:
            frame = view_frame(view.n, view.xd)
            projected = view.shape
            hatch = []
            if view.section is not None:
                projected = _cut_near_half(view.shape, view.section, frame)
                hatch = _section_loops(projected, view.section, frame)
                if not hatch:
                    raise ValueError(
                        f"{view.name}: the cutting plane does not pass through the part"
                    )
            if self.mode == "polygonal":
                from .polygonal_hlr import mesh_shape, projected_segments

                if projected is self.shape:
                    if self.mesh is None:
                        self.mesh = mesh_shape(projected, self.deflection_mm)
                    mesh = self.mesh
                else:
                    mesh = mesh_shape(projected, self.deflection_mm)
                edges = [
                    (LINE, points, visible)
                    for points, visible in projected_segments(mesh, frame)
                    if visible or view.section is None
                ]
                if not edges:
                    raise ValueError(
                        f"{view.name}: polygonal HLR produced no projected edges"
                    )
                xs, ys = zip(*(point for _, points, _ in edges for point in points))
                rendered = (min(xs), min(ys), max(xs), max(ys))
            else:
                projection = build_view(replace(view, shape=projected, section=None))
                edges = [
                    row for row in projection["edges"] if row[2] or view.section is None
                ]
                # SDK's full section computes its bounds from visible edges only.
                xs, ys = zip(*(point for _, points, _ in edges for point in points))
                rendered = (min(xs), min(ys), max(xs), max(ys))
            measured = (
                bounds if bounds is not None else projected_bounds(projected, frame)
            )
            cached = dict(
                edges=edges,
                lbox=measured,
                outline_box=rendered,
                hatch=hatch,
                frame=frame,
            )
            self.cache[key] = cached
        return cached

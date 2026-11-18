"""Additional view types for the pinned SimpleCADAPI sheet engine."""

from __future__ import annotations

import math
from dataclasses import replace

import numpy as np
from simplecadapi._cpp.occt.BRep import BRep_Builder
from simplecadapi._cpp.occt.BRepAdaptor import BRepAdaptor_Surface
from simplecadapi._cpp.occt.GeomAbs import GeomAbs_Plane
from simplecadapi._cpp.occt.TopAbs import TopAbs_REVERSED
from simplecadapi._cpp.occt.TopoDS import TopoDS_Compound
from simplecadapi.dxf_engine import SheetPlan
from simplecadapi.dxf_engine.collide import conflicts
from simplecadapi.dxf_engine.geom2d import Box
from simplecadapi.dxf_engine.refs import view_frame
from simplecadapi.dxf_engine.views import _cut_near_half, _faces, _section_loops
from simplecadapi.inspect.brep.io import measure_shape_mass_rtuple
from simplecadapi.inspect.brep.model import _bounding_box

from .inspection import rigid_shape


def auxiliary_frame(reference, parent, *, reverse=False):
    kind, face = reference
    if kind != "face":
        raise ValueError("An auxiliary face reference must name a planar model face")
    surface = BRepAdaptor_Surface(face)
    if surface.GetType() != GeomAbs_Plane:
        raise ValueError("An auxiliary face reference must name a planar model face")
    normal = np.array(surface.Plane().Axis().Direction().Coord())
    if (face.Orientation() == TopAbs_REVERSED) != reverse:
        normal *= -1
    hinge = np.cross(parent.n, normal)
    length = math.hypot(*hinge)
    if length < 1e-8:
        raise ValueError(
            "An auxiliary view needs a parent that sees the target face edge-on"
        )
    return tuple(normal.tolist()), tuple((hinge / length).tolist())


def removed_section(view, volume):
    """Use actual cut faces as the projected shape, and preserve their hole loops."""
    frame = view_frame(view.n, view.xd)
    point = view.section
    cut = _cut_near_half(view.shape, point, frame)
    retained, _ = measure_shape_mass_rtuple(cut, kind="volume")
    margin = max(1e-9, abs(volume) * 1e-10)
    if not margin < retained < volume - margin:
        raise ValueError(
            f"{view.name}: removed section plane must pass through the solid with material on both sides"
        )
    loops = _section_loops(cut, point, frame)
    builder = BRep_Builder()
    faces = TopoDS_Compound()
    builder.MakeCompound(faces)
    count = 0
    n = frame[2]
    for face in _faces(cut):
        surface = BRepAdaptor_Surface(face)
        if surface.GetType() != GeomAbs_Plane:
            continue
        plane = surface.Plane()
        axis = plane.Axis().Direction().Coord()
        offset = np.subtract(plane.Location().Coord(), point)
        if abs(np.dot(axis, n)) > 1 - 1e-8 and abs(np.dot(offset, n)) < 1e-6:
            builder.Add(faces, face)
            count += 1
    if not count or not loops:
        raise ValueError(f"{view.name}: removed section has no usable material loops")
    projected = rigid_shape(faces, dict(rotation=frame, translation_mm=(0, 0, 0)))
    bounds = _bounding_box(projected)
    paper_bounds = (*bounds["min"][:2], *bounds["max"][:2])
    return replace(view, shape=faces, section=None), loops, paper_bounds


class ExtendedSheetPlan(SheetPlan):
    def __init__(self, decl, removed, auxiliary, projection, projector):
        super().__init__(decl)
        self.removed = removed
        self.auxiliary = auxiliary
        self.draft_projection = projection
        self.projector = projector
        self.auxiliary_marks = []
        self.intent_issues = []

    def issues(self):
        return super().issues() + self.intent_issues

    def _build_view(self, view):
        bounds = self.removed[view.name][2] if view.name in self.removed else None
        return self.projector.view(view, bounds)

    def _solve_sections(self):
        # Reuse the SDK's cutting-plane marks, while only the cut faces enter HLR.
        for name, (point, loops, bounds) in self.removed.items():
            # Sampled HLR points can miss a circle's extrema. Use kernel bounds for section extent dimensions.
            view = self.views[name]
            view["hatch"] = loops
            view["lbox"] = bounds
            view["bbox"] = Box(*self.tx(name, bounds[:2]), *self.tx(name, bounds[2:]))
            self.by_name[name].section = point
        try:
            super()._solve_sections()
        finally:
            for name in self.removed:
                self.by_name[name].section = None

        self.auxiliary_marks = []
        for name, (parent, label) in self.auxiliary.items():
            target = self.views[name]["bbox"]
            source = self.views[parent]["bbox"]
            right, up, _ = self.views[parent]["frame"]
            n = self.by_name[name].n
            u, v = float(np.dot(n, right)), float(np.dot(n, up))
            half = ((source.x1 - source.x0) / 2, (source.y1 - source.y0) / 2)
            center = ((source.x1 + source.x0) / 2, (source.y1 + source.y0) / 2)
            border = min(a / abs(d) for a, d in zip(half, (u, v)) if abs(d) > 1e-9)
            tip = center[0] + (border + 2) * u, center[1] + (border + 2) * v
            tail = tip[0] + 7 * u, tip[1] + 7 * v
            caption = f"AUX {label}"
            positions = [
                ((tail[0] - 4 * v, tail[1] + 4 * u), label, parent),
                (((target.x0 + target.x1) / 2, target.y1 + 5), caption, name),
            ]
            for index, (point, text, view) in enumerate(positions):
                key = f"aux:{name}:{index}"
                height, width = 3.5, max(3.5, len(text) * 2.5)
                line = [(tip, tail)] if index == 0 else []
                hits = conflicts(self, key, view, *point, width, height, 0, line)
                if hits:
                    obstacle = ", ".join(sorted({hit["id"] for hit in hits}))
                    raise ValueError(
                        f"Auxiliary mark {label}: adjust view placement to clear {obstacle}"
                    )
                self.text_obbs.append((key, *point, width, height, 0))
                for start, end in line:
                    self._reg_seg(key, start, end)
            self.auxiliary_marks.append((tip, tail, (u, v), positions))

    def projection_bounds(self):
        return {
            name: {
                "brep_bounds_mm": view["lbox"],
                "sampled_outline_bounds_mm": view["outline_box"],
                "max_outline_gap_mm": max(
                    abs(a - b) for a, b in zip(view["lbox"], view["outline_box"])
                ),
            }
            for name, view in self.views.items()
        }


def decorate_views(doc, plan):
    """Write solved auxiliary marks and the explicitly selected projection label."""
    from ezdxf.enums import TextEntityAlignment

    msp = doc.modelspace()
    changed = bool(plan.auxiliary_marks or plan.draft_projection is not None)
    if plan.draft_projection is not None:
        cell = (plan.fmt.title[0] + 46.5, plan.fmt.title[1] + 18.0)
        text = next(
            entity
            for entity in msp.query("TEXT")
            if math.dist(tuple(entity.dxf.insert)[:2], cell) < 1e-7
        )
        text.dxf.text = f"mm · {plan.draft_projection}-angle"
    for tip, tail, (u, v), labels in plan.auxiliary_marks:
        layer = {"layer": "DIMENSION"}
        base = tip[0] + 2.5 * u, tip[1] + 2.5 * v
        msp.add_line(base, tail, dxfattribs=layer)
        msp.add_solid(
            [tip, (base[0] - v, base[1] + u), (base[0] + v, base[1] - u)],
            dxfattribs=layer,
        )
        for point, label, _ in labels:
            msp.add_text(
                label, dxfattribs={"layer": "TEXT", "height": 3.5}
            ).set_placement(point, align=TextEntityAlignment.MIDDLE_CENTER)
    return changed

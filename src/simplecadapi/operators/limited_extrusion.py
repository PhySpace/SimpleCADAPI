"""Recorded extrusion terminated by a real target face or curved shell.

The construction follows the surface-history approach used by build123d:
intersect a long prism, sew the affected target faces, order contact surfaces,
and split by the selected surface. Bounding boxes only bound the temporary
prism; they never define the termination surface.
"""
from __future__ import annotations

import math
from typing import Sequence

import numpy as np
from OCP.BRepAlgoAPI import BRepAlgoAPI_Common, BRepAlgoAPI_Splitter
from OCP.BRepBuilderAPI import BRepBuilderAPI_Sewing
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepGProp import BRepGProp, BRepGProp_Face
from OCP.BRepPrimAPI import BRepPrimAPI_MakeHalfSpace, BRepPrimAPI_MakePrism
from OCP.BRepTools import BRepTools
from OCP.GProp import GProp_GProps
from OCP.TopAbs import TopAbs_COMPOUND, TopAbs_FACE, TopAbs_SHELL
from OCP.TopoDS import TopoDS, TopoDS_Iterator
from OCP.TopTools import TopTools_ListOfShape
from OCP.gp import gp_Pnt, gp_Vec

from ..kernel.ocp_booleans import solids_of
from ..kernel.ocp_export import make_compound_always
from ..kernel.ocp_properties import bounding_box, center_of_mass, distance, volume
from ..kernel.ocp_topology import faces_of
from ._support import Face, Solid, evaluate_value, get_current_cs
from .deformation import _finish, _finite_vector


def _top_level(shape):
    if shape.ShapeType() != TopAbs_COMPOUND:
        return [shape]
    output = []
    iterator = TopoDS_Iterator(shape)
    while iterator.More():
        output.extend(_top_level(iterator.Value()))
        iterator.Next()
    return output


def _crosses_direction(face, axis):
    """Ignore side walls tangent to the extrusion, including coincident walls."""
    u0, u1, v0, v1 = BRepTools.UVBounds_s(face)
    properties = BRepGProp_Face(face)
    for u in (.25, .5, .75):
        for v in (.25, .5, .75):
            point, normal = gp_Pnt(), gp_Vec()
            properties.Normal(u0 + u * (u1-u0), v0 + v * (v1-v0), point, normal)
            length = normal.Magnitude()
            if length > 1e-14 and abs(normal.X()*axis[0] + normal.Y()*axis[1] + normal.Z()*axis[2]) / length > 1e-8:
                return True
    return False


def _contact_surfaces(target, prism, axis):
    common = BRepAlgoAPI_Common(target, prism)
    common.Build()
    if not common.IsDone() or not faces_of(common.Shape()):
        raise ValueError("No intersection: extrusion does not contact target")
    history = common.History()
    modified = []
    intersection_faces = faces_of(common.Shape())
    for face in faces_of(target):
        affected = list(history.Modified(face))
        if affected:
            modified.extend(TopoDS.Face_s(item) for item in affected if item.ShapeType() == TopAbs_FACE)
        elif not history.IsRemoved(face) and any(item.IsSame(face) for item in intersection_faces):
            # A whole target may lie inside the temporary prism, in which case
            # unchanged boundary faces are still genuine contact surfaces.
            modified.append(face)
    if not modified:
        raise ValueError("No target boundary surfaces found in extrusion intersection")
    sewing = BRepBuilderAPI_Sewing(1e-6)
    for face in modified:
        if _crosses_direction(face, axis):
            sewing.Add(face)
    sewing.Perform()
    surfaces = _top_level(sewing.SewedShape())
    if not surfaces or any(part.ShapeType() not in {TopAbs_FACE, TopAbs_SHELL} for part in surfaces):
        raise ValueError("Kernel could not sew target contact surfaces")
    return surfaces


def _split_on_surface(prism, surface, keep_top):
    arguments, tools = TopTools_ListOfShape(), TopTools_ListOfShape()
    arguments.Append(prism)
    tools.Append(surface)
    splitter = BRepAlgoAPI_Splitter()
    splitter.SetArguments(arguments)
    splitter.SetTools(tools)
    splitter.Build()
    if not splitter.IsDone():
        raise ValueError("Kernel could not split extrusion on target surface")
    reference_face = TopoDS.Face_s(surface) if surface.ShapeType() == TopAbs_FACE else faces_of(surface)[0]
    u0, u1, v0, v1 = BRepTools.UVBounds_s(reference_face)
    point, normal = gp_Pnt(), gp_Vec()
    BRepGProp_Face(reference_face).Normal((u0+u1)/2, (v0+v1)/2, point, normal)
    if normal.Magnitude() <= 1e-14:
        raise ValueError("Undefined normal on termination surface")
    normal.Normalize()
    reference = point.Translated(normal)
    if surface.ShapeType() == TopAbs_FACE:
        halfspace = BRepPrimAPI_MakeHalfSpace(TopoDS.Face_s(surface), reference).Solid()
    else:
        halfspace = BRepPrimAPI_MakeHalfSpace(TopoDS.Shell_s(surface), reference).Solid()
    candidates = []
    for part in solids_of(splitter.Shape()):
        common = BRepAlgoAPI_Common(part, halfspace)
        common.Build()
        if not common.IsDone():
            raise ValueError("Kernel could not classify the termination side")
        properties = GProp_GProps()
        BRepGProp.LinearProperties_s(common.Shape(), properties)
        is_top = properties.Mass() >= 1e-6
        if is_top == keep_top:
            candidates.append(part)
    return candidates


def extrude_until_rsolid(
    profile: Face,
    target: Solid | Sequence[Solid],
    direction: Sequence[float] = (0, 0, 1),
    until: str = "NEXT",
) -> Solid:
    """Extrude a planar face until a target surface, including curved surfaces.

    The direction is interpreted in the current coordinate system and
    normalized before construction. ``until`` selects the termination:
    ``NEXT`` (forward, nearest intersecting target surface), ``LAST`` (forward,
    farthest), ``PREVIOUS`` (reverse, nearest) and ``FIRST`` (reverse,
    farthest). The temporary prism is intersected with the target, the target's
    boundary faces are taken from kernel history and sewn into surfaces, and
    the prism is split on the selected one. Bounding boxes only size the
    temporary prism; they do not define the termination surface, and side
    walls parallel to the direction do not join separate near and far limits.

    Targets must cover the profile at the requested contact: an uncovered,
    open or disconnected output is rejected, as are a missing contact, an
    invalid mode, a zero or nonfinite direction and an empty target sequence.
    Inputs are preserved. The operation is recorded as
    ``make_extrude_until_rsolid``; its ordered inputs are the profile followed
    by every target solid and its parameters keep ``direction``, ``until`` and
    ``target_count``, so a changed target is recomputed on replay (no final
    BRep is embedded).

    Args:
        profile: The planar face to extrude.
        target: A solid, or a sequence of solids, that bounds the extrusion.
        direction: Extrusion direction in current coordinate-system
            coordinates.
        until: ``"NEXT"``, ``"LAST"``, ``"PREVIOUS"`` or ``"FIRST"``.

    Returns:
        One valid solid.

    Raises:
        TypeError: ``profile`` is not a Face, or ``target`` is not a Solid or
            a sequence of Solid.
        ValueError: No target, no contact, insufficient coverage, a bad mode
            or direction, or an invalid kernel result.

    Examples:
        import simplecadapi as scad
        profile = scad.make_rectangle_rface(2, 2)
        ceiling = scad.make_box_rsolid(10, 10, 2, bottom_face_center=(0, 0, 5))
        near = scad.extrude_until_rsolid(profile, ceiling, until="NEXT")  # volume 20
        far = scad.extrude_until_rsolid(profile, ceiling, until="LAST")  # volume 28
        sphere = scad.make_sphere_rsolid(5, center=(0, 0, 10))
        curved = scad.extrude_until_rsolid(profile, sphere)
    """
    if not isinstance(profile, Face):
        raise TypeError("profile must be a Face")
    targets = [target] if isinstance(target, Solid) else list(target)
    if not targets:
        raise ValueError("target must contain at least one Solid")
    if any(not isinstance(item, Solid) for item in targets):
        raise TypeError("target must be a Solid or a sequence of Solid")
    mode = str(getattr(until, "name", until)).upper()
    if mode not in {"NEXT", "LAST", "PREVIOUS", "FIRST"}:
        raise ValueError("until must be NEXT, LAST, PREVIOUS, or FIRST")
    values = _finite_vector(direction, "direction")
    global_direction = get_current_cs().transform_vector(np.asarray(values))
    magnitude = float(np.linalg.norm(global_direction))
    if not math.isfinite(magnitude) or magnitude <= 1e-14:
        raise ValueError("direction must be a finite nonzero vector")
    axis = global_direction / magnitude
    if mode in {"PREVIOUS", "FIRST"}:
        axis = -axis
    bound_target = make_compound_always([item.wrapped for item in targets])
    box = bounding_box(make_compound_always([profile.wrapped, bound_target]))
    length = math.sqrt((box.xmax-box.xmin)**2 + (box.ymax-box.ymin)**2 + (box.zmax-box.zmin)**2)
    if length <= 1e-12:
        raise ValueError("Degenerate profile and target bounds")
    prism = BRepPrimAPI_MakePrism(profile.wrapped, gp_Vec(*(axis * length))).Shape()
    surfaces = sorted(_contact_surfaces(bound_target, prism, axis), key=lambda part: distance(part, profile.wrapped))
    nearest = mode in {"NEXT", "PREVIOUS"}
    surface = surfaces[0] if nearest else surfaces[-1]
    candidates = _split_on_surface(prism, surface, keep_top=nearest)
    if not candidates:
        raise ValueError("Extrusion produced no solid on the requested side of the target")
    origin = np.asarray(tuple(center_of_mass(profile.wrapped)))
    chosen = min(candidates, key=lambda part: np.dot(np.asarray(tuple(center_of_mass(part))) - origin, axis))
    if abs(volume(chosen) - volume(prism)) <= max(1e-8, abs(volume(prism))*1e-9):
        raise ValueError("Target termination surface does not completely cover the extrusion profile")
    if volume(chosen) <= 1e-12 or not BRepCheck_Analyzer(chosen).IsValid():
        raise ValueError("Target surface did not completely cover a valid limited extrusion")
    result = _finish(profile, chosen, "make_extrude_until_rsolid",
                     {"direction": direction, "until": mode, "target_count": len(targets)}, [profile, *targets])
    result._apply_tag("solid.extrusion", propagate=False)
    return result


__all__ = ("extrude_until_rsolid",)

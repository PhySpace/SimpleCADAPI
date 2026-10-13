"""Recorded tapered extrusions and sweeps with multiple explicit sections."""
from __future__ import annotations

import math
from typing import Sequence

import numpy as np
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
from OCP.BRepOffsetAPI import BRepOffsetAPI_MakeOffset, BRepOffsetAPI_MakePipeShell, BRepOffsetAPI_ThruSections
from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism
from OCP.BRepTools import BRepTools
from OCP.GeomAbs import GeomAbs_Intersection, GeomAbs_Plane
from OCP.LocOpe import LocOpe_DPrism
from OCP.TopAbs import TopAbs_WIRE
from OCP.TopExp import TopExp_Explorer
from OCP.TopoDS import TopoDS
from OCP.gp import gp_Dir, gp_Trsf, gp_Vec

from ._support import Face, Wire, Solid, evaluate_scalar, get_current_cs
from .deformation import _finish, _finite_vector


def extrude_taper_rsolid(
    profile: Face,
    vector: Sequence[float],
    taper: float,
    flip_inner: bool = True,
) -> Solid:
    """Extrude a planar face by a vector, with a taper in degrees.

    Positive taper shrinks the outer section. Inner loops optionally taper in
    the opposite direction. Analytic draft prisms are retained where valid;
    other orientations/holes use exact offset wire sections and solid lofts.
    """
    values = _finite_vector(vector, "vector")
    angle = float(evaluate_scalar(taper))
    if not math.isfinite(angle) or abs(angle) >= 90:
        raise ValueError("taper must be finite and between -90 and 90 degrees")
    displacement = get_current_cs().transform_vector(np.asarray(values))
    length = float(np.linalg.norm(displacement))
    if length <= 1e-12:
        raise ValueError("extrusion vector must be nonzero")
    surface = BRepAdaptor_Surface(profile.wrapped, True)
    if surface.GetType() != GeomAbs_Plane:
        raise ValueError("taper extrusion requires a planar profile")
    normal = np.asarray(tuple(profile.get_normal_at()), dtype=float)
    outer = BRepTools.OuterWire_s(profile.wrapped)
    wires = [outer]
    explorer = TopExp_Explorer(profile.wrapped, TopAbs_WIRE)
    while explorer.More():
        wire = TopoDS.Wire_s(explorer.Current())
        if not wire.IsSame(outer):
            wires.append(wire)
        explorer.Next()
    if angle == 0:
        shape = BRepPrimAPI_MakePrism(profile.wrapped, gp_Vec(*displacement)).Shape()
    elif np.linalg.norm(displacement / length - normal) < 1e-8 and normal[2] > 0 and len(wires) == 1 and angle > 0:
        shape = LocOpe_DPrism(profile.wrapped, length / math.cos(math.radians(angle)), math.radians(angle)).Shape()
    else:
        # Offset in the profile plane before translating the final section.
        move = gp_Trsf()
        move.SetTranslation(gp_Vec(*displacement))
        solids = []
        for i, wire in enumerate(wires):
            # Face inner wires wind opposite to the outer boundary. Normalize
            # their winding before applying the signed 2-D offset so that
            # flip_inner controls geometry rather than kernel wire orientation.
            if i:
                wire = TopoDS.Wire_s(wire.Reversed())
            offset = -length * math.tan(math.radians(angle)) * (-1 if i and flip_inner else 1)
            builder = BRepOffsetAPI_MakeOffset(wire, GeomAbs_Intersection, False)
            builder.Perform(offset)
            if not builder.IsDone():
                raise ValueError("taper collapses a profile loop")
            offset_shape = builder.Shape()
            exp = TopExp_Explorer(offset_shape, TopAbs_WIRE)
            found = []
            while exp.More():
                found.append(TopoDS.Wire_s(exp.Current()))
                exp.Next()
            if len(found) != 1:
                raise ValueError("taper changes loop connectivity")
            moved = BRepBuilderAPI_Transform(found[0], move, True).Shape()
            loft = BRepOffsetAPI_ThruSections(True, False)
            loft.AddWire(wire)
            loft.AddWire(TopoDS.Wire_s(moved))
            loft.Build()
            if not loft.IsDone():
                raise ValueError("kernel could not build tapered sections")
            solids.append(loft.Shape())
        shape = solids[0]
        for tool in solids[1:]:
            cut = BRepAlgoAPI_Cut(shape, tool)
            cut.Build()
            if not cut.IsDone():
                raise ValueError("kernel could not subtract tapered inner loop")
            shape = cut.Shape()
    return _finish(profile, shape, "make_extrude_taper_rsolid",
                   {"vector": vector, "taper": taper, "flip_inner": flip_inner}, [profile])


def sweep_multisection_rsolid(
    profiles: Sequence[Face | Wire],
    path: Wire,
    is_frenet: bool = False,
    binormal: Sequence[float] | Wire | None = None,
) -> Solid:
    """Sweep through explicit ordered section wires along a continuous path.

    Face sections use their outer boundary, as in build123d's multi-section
    pipe contract. Binormal may be a direction vector or auxiliary spine.
    Each supplied section and path remains a graph input for replay.
    """
    sections = list(profiles)
    if len(sections) < 2:
        raise ValueError("multi-section sweep requires at least two sections")
    builder = BRepOffsetAPI_MakePipeShell(path.wrapped)
    rotate = False
    if isinstance(binormal, Wire):
        builder.SetMode(binormal.wrapped, True)
    elif binormal is not None:
        values = _finite_vector(binormal, "binormal")
        direction = get_current_cs().transform_vector(np.asarray(values))
        if np.linalg.norm(direction) < 1e-12:
            raise ValueError("binormal direction must be nonzero")
        builder.SetMode(gp_Dir(*direction))
        rotate = True
    else:
        builder.SetMode(bool(is_frenet))
    for section in sections:
        if not isinstance(section, (Face, Wire)):
            raise TypeError("sections must be Face or Wire")
        wire = BRepTools.OuterWire_s(section.wrapped) if isinstance(section, Face) else section.wrapped
        builder.Add(wire, False, rotate)
    builder.Build()
    if not builder.IsDone() or not builder.MakeSolid():
        raise ValueError("kernel could not make a solid multi-section sweep")
    inputs = [*sections, path]
    params = {"profile_count": len(sections), "is_frenet": bool(is_frenet), "binormal": None}
    if isinstance(binormal, Wire):
        inputs.append(binormal)
        params["binormal_is_wire"] = True
    elif binormal is not None:
        params["binormal"] = binormal
    return _finish(sections[0], builder.Shape(), "make_sweep_multisection_rsolid", params, inputs)


__all__ = ("extrude_taper_rsolid", "sweep_multisection_rsolid")

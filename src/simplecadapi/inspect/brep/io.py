"""STEP loading and low-level BREP property helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import numpy as np
from simplecadapi._cpp.occt.BRepCheck import BRepCheck_Analyzer
from simplecadapi._cpp.occt.BRepGProp import BRepGProp
from simplecadapi._cpp.occt.GProp import GProp_GProps
from simplecadapi._cpp.occt.IFSelect import IFSelect_RetDone
from simplecadapi._cpp.occt.STEPControl import STEPControl_Reader
from simplecadapi._cpp.occt.TopoDS import TopoDS_Shape

PropertyKind = Literal["volume", "area", "length"]


def load_step_rshape(
    path: str | Path, *, require_single_root: bool = True, require_valid: bool = True
) -> TopoDS_Shape:
    """Load one transferred STEP shape and optionally require a valid BREP."""
    source = Path(path)
    reader = STEPControl_Reader()
    status = reader.ReadFile(str(source))
    if status != IFSelect_RetDone:
        raise ValueError(f"Could not read STEP file {source}: {status}")
    transferred = reader.TransferRoots()
    if transferred < 1 or reader.NbShapes() < 1:
        raise ValueError(f"STEP file {source} transferred no shapes")
    if require_single_root and (transferred != 1 or reader.NbShapes() != 1):
        raise ValueError(
            f"Expected one STEP root in {source}, got transferred={transferred}, shapes={reader.NbShapes()}"
        )
    shape = reader.Shape(1) if require_single_root else reader.OneShape()
    if require_valid and not BRepCheck_Analyzer(shape).IsValid():
        raise ValueError(f"STEP BREP is invalid: {source}")
    return shape


def measure_shape_mass_rtuple(shape: TopoDS_Shape, kind: PropertyKind) -> tuple[float, np.ndarray]:
    """Return mass-like value and center for volume, area, or length."""
    properties = GProp_GProps()
    if kind == "volume":
        BRepGProp.VolumeProperties_s(shape, properties)
    elif kind == "area":
        BRepGProp.SurfaceProperties_s(shape, properties)
    elif kind == "length":
        BRepGProp.LinearProperties_s(shape, properties)
    else:
        raise ValueError(f"Unsupported property kind: {kind}")
    return float(properties.Mass()), np.asarray(
        properties.CentreOfMass().Coord(), dtype=float
    )


def xyz(point) -> list[float]:
    """Convert an OCP point to a JSON-friendly XYZ list."""
    return [float(point.X()), float(point.Y()), float(point.Z())]


def direction(vector) -> list[float]:
    """Convert an OCP direction to a JSON-friendly XYZ list."""
    return [float(vector.X()), float(vector.Y()), float(vector.Z())]

"""Generate three small STEP targets; reconstruction code never imports this module."""

from __future__ import annotations

from pathlib import Path

from OCP.IFSelect import IFSelect_RetDone
from OCP.STEPControl import STEPControl_AsIs, STEPControl_Writer

import simplecadapi as scad


CASES = ("l1", "s1", "p1")


def target_shape(case: str) -> scad.Solid:
    if case == "l1":
        sections = [
            scad.make_rectangle_rwire(width=8, height=4, center=(0, 0, 0)),
            scad.make_rectangle_rwire(width=3, height=7, center=(1, 0.5, 10)),
        ]
        return scad.loft_rsolid(profiles=sections)
    if case == "s1":
        profile = scad.make_rectangle_rface(width=2, height=1)
        path = scad.make_interpolated_spline_rwire(
            points=[(0, 0, 0), (1, 0, 2), (3, 1, 4), (5, 0, 6)]
        )
        return scad.sweep_rsolid(profile=profile, path=path, is_frenet=True)
    if case == "p1":
        stations = [
            ((0, 0, 0), (0.3, 0, 1), 8, 4),
            ((3, 0, 10), (0, 0, 1), 14, 9),
            ((0, 0, 20), (-0.3, 0, 1), 5, 3),
        ]
        sections = [
            scad.make_rectangle_rwire(width=w, height=h, center=center, normal=normal)
            for center, normal, w, h in stations
        ]
        path = scad.make_interpolated_spline_rwire(
            points=[(0, 0, 0), (3, 0, 10), (0, 0, 20)]
        )
        return scad.loft_multisection_rsolid(profiles=sections, path=path)
    raise ValueError(f"Unknown case: {case}")


def write_target(case: str, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    writer = STEPControl_Writer()
    if writer.Transfer(target_shape(case).wrapped, STEPControl_AsIs) != IFSelect_RetDone:
        raise RuntimeError(f"STEP transfer failed for {case}")
    if writer.Write(str(output_path)) != IFSelect_RetDone:
        raise RuntimeError(f"STEP write failed for {case}")
    return output_path

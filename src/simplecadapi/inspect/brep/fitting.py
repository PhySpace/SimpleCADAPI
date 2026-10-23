"""Evidence-oriented analytic carrier fitting for reverse engineering."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
from simplecadapi._cpp.occt.BRepAdaptor import BRepAdaptor_Surface
from simplecadapi._cpp.occt.BRepTools import BRepTools
from simplecadapi._cpp.occt.TopoDS import TopoDS, TopoDS_Shape
from simplecadapi._cpp.occt.gp import gp_Pnt, gp_Vec

from .model import BRepModel, index_shape_rbrepmodel, load_step_rbrepmodel


def _model(value: BRepModel | TopoDS_Shape | str | Path) -> BRepModel:
    if isinstance(value, BRepModel):
        return value
    if isinstance(value, TopoDS_Shape):
        return index_shape_rbrepmodel(value)
    return load_step_rbrepmodel(value)


def _sample_face(face, u_samples: int, v_samples: int) -> tuple[np.ndarray, np.ndarray]:
    adaptor = BRepAdaptor_Surface(face, True)
    u_min, u_max, v_min, v_max = map(float, BRepTools.UVBounds_s(face))
    points = []
    normals = []
    for u_value in np.linspace(u_min, u_max, u_samples):
        for v_value in np.linspace(v_min, v_max, v_samples):
            point = gp_Pnt()
            du = gp_Vec()
            dv = gp_Vec()
            adaptor.D1(float(u_value), float(v_value), point, du, dv)
            normal = np.cross(np.asarray(du.Coord()), np.asarray(dv.Coord()))
            norm = float(np.linalg.norm(normal))
            if norm <= 1.0e-12:
                continue
            points.append(point.Coord())
            normals.append((normal / norm).tolist())
    if len(points) < 6:
        raise ValueError("face sampling produced fewer than six regular points")
    return np.asarray(points, dtype=float), np.asarray(normals, dtype=float)


def _statistics(residuals: np.ndarray) -> dict[str, float]:
    values = np.abs(np.asarray(residuals, dtype=float))
    return {
        "rms": float(np.sqrt(np.mean(values * values))),
        "mean": float(np.mean(values)),
        "maximum": float(np.max(values)),
    }


def _plane_fit(points: np.ndarray) -> dict[str, Any]:
    origin = points.mean(axis=0)
    _, _, right = np.linalg.svd(points - origin, full_matrices=False)
    normal = right[-1]
    residuals = (points - origin) @ normal
    return {
        "type": "plane",
        "parameters": {"origin": origin.tolist(), "normal": normal.tolist()},
        "residual": _statistics(residuals),
    }


def _sphere_fit(points: np.ndarray) -> dict[str, Any]:
    matrix = np.column_stack((2.0 * points, np.ones(len(points))))
    rhs = np.sum(points * points, axis=1)
    solution, *_ = np.linalg.lstsq(matrix, rhs, rcond=None)
    center = solution[:3]
    radius_squared = float(solution[3] + center @ center)
    if radius_squared <= 0.0:
        raise ValueError("sphere fit produced a non-positive squared radius")
    radius = float(np.sqrt(radius_squared))
    residuals = np.linalg.norm(points - center, axis=1) - radius
    return {
        "type": "sphere",
        "parameters": {"center": center.tolist(), "radius": radius},
        "residual": _statistics(residuals),
    }


def _orthogonal_basis(axis: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    reference = np.asarray((1.0, 0.0, 0.0))
    if abs(float(axis @ reference)) > 0.9:
        reference = np.asarray((0.0, 1.0, 0.0))
    first = np.cross(axis, reference)
    first /= np.linalg.norm(first)
    second = np.cross(axis, first)
    return first, second


def _circle_fit_2d(points: np.ndarray) -> tuple[np.ndarray, float]:
    matrix = np.column_stack((2.0 * points, np.ones(len(points))))
    rhs = np.sum(points * points, axis=1)
    solution, *_ = np.linalg.lstsq(matrix, rhs, rcond=None)
    center = solution[:2]
    radius_squared = float(solution[2] + center @ center)
    if radius_squared <= 0.0:
        raise ValueError("circle fit produced a non-positive squared radius")
    return center, float(np.sqrt(radius_squared))


def _cylinder_and_cone_fits(
    points: np.ndarray, normals: np.ndarray
) -> list[dict[str, Any]]:
    _, _, right = np.linalg.svd(normals, full_matrices=False)
    axis = right[-1]
    axis /= np.linalg.norm(axis)
    first, second = _orthogonal_basis(axis)
    projected = np.column_stack((points @ first, points @ second))
    center_2d, radius = _circle_fit_2d(projected)
    axial = points @ axis
    axis_point = center_2d[0] * first + center_2d[1] * second + axial.mean() * axis
    radial = np.linalg.norm(projected - center_2d, axis=1)
    candidates = [
        {
            "type": "cylinder",
            "parameters": {
                "axis_point": axis_point.tolist(),
                "axis_direction": axis.tolist(),
                "radius": radius,
            },
            "residual": _statistics(radial - radius),
        }
    ]

    line = np.column_stack((axial, np.ones(len(axial))))
    slope, intercept = np.linalg.lstsq(line, radial, rcond=None)[0]
    if abs(float(slope)) > 1.0e-9:
        apex_parameter = -float(intercept) / float(slope)
        apex = center_2d[0] * first + center_2d[1] * second + apex_parameter * axis
        predicted = slope * axial + intercept
        candidates.append(
            {
                "type": "cone",
                "parameters": {
                    "apex": apex.tolist(),
                    "axis_direction": axis.tolist(),
                    "half_angle_degrees": float(np.degrees(np.arctan(abs(slope)))),
                },
                "residual": _statistics(radial - predicted),
            }
        )
    return candidates


def fit_face_analytic_rdescriptor(
    model_or_path: BRepModel | TopoDS_Shape | str | Path,
    face_id: str,
    *,
    tolerance: float = 1.0e-3,
    u_samples: int = 11,
    v_samples: int = 11,
) -> dict[str, Any]:
    """Fit plane, sphere, cylinder, and cone carriers to one indexed face.

    Results are evidence, not feature-history assertions. Callers should use
    ``accepted`` and residuals instead of assuming the best candidate is exact.
    The report includes every fitted candidate and the selected carrier
    parameters.
    """
    if tolerance <= 0.0:
        raise ValueError("tolerance must be positive")
    if u_samples < 3 or v_samples < 3:
        raise ValueError("u_samples and v_samples must each be at least three")
    model = _model(model_or_path)
    kind, index, shape = model.resolve_entity(face_id)
    if kind != "face":
        raise ValueError("face_id must resolve to a face entity")
    face = TopoDS.Face_s(shape)
    points, normals = _sample_face(face, u_samples, v_samples)
    candidates = [_plane_fit(points), _sphere_fit(points)]
    candidates.extend(_cylinder_and_cone_fits(points, normals))
    candidates.sort(key=lambda item: item["residual"]["rms"])
    best = candidates[0]
    return {
        "model_path": model.source,
        "face_id": f"{kind}:{index}",
        "sample_count": len(points),
        "tolerance": float(tolerance),
        "accepted": bool(best["residual"]["maximum"] <= tolerance),
        "best_candidate": best,
        "candidates": candidates,
        "reason": (
            "best candidate maximum residual is within tolerance"
            if best["residual"]["maximum"] <= tolerance
            else "no analytic candidate is within tolerance"
        ),
    }


__all__ = ["fit_face_analytic_rdescriptor"]
